"""
Verification independante (testeur-ventes, Dev C, 2026-11-22-c) de BUG-508 (migrations 0011/0012),
BUG-197, BUG-519, BUG-527 et controle de non-regression (BP, blocage credit, remboursement, recu).
Donnees fictives uniquement.
"""
import itertools
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal
from importlib import import_module
from unittest.mock import patch

from django.apps import apps as global_apps
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.testing import get_config, make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine

D = Decimal
INV = '/api/sales/invoices/'
MIG12 = import_module('sales.migrations.0012_bug508_backfill_full_unit_price')


def _api(u):
    a = APIClient()
    a.force_authenticate(u)
    return a


# --------------------------------------------------------------------------- BUG-508
class Backfill508(TransactionTestCase):
    """Rejeu des migrations sur donnees fictives : normales, soldees, tarifs changes."""

    def setUp(self):
        self.node = make_node(code='QV8')
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='qv8_fa')
        self.cl = make_client(self.node)
        self.bps = {p: make_bread_price(f'QV{p}', f'Pain {p}', p) for p in (50, 150, 300, 500)}

    def _mk(self, price, soldee, qty=2):
        inv = Invoice.objects.create(node=self.node, client=self.cl, facturier=self.fa, team='A',
                                     status='PENDING', payment_type='CREDIT', is_soldee=soldee)
        return InvoiceLine.objects.create(invoice=inv, bread_price=self.bps[price], quantity=qty).pk

    def _vals(self, pk):
        return InvoiceLine.objects.values_list('unit_price', 'full_unit_price', 'line_total').get(pk=pk)

    def _migrate(self, target):
        ex = MigrationExecutor(connection)
        ex.migrate([target] if target else ex.loader.graph.leaf_nodes())

    def tearDown(self):
        self._migrate(None)  # laisse le schema a jour pour les autres tests

    def test_retro_remplissage_complet_sur_aller_retour_0010(self):
        normal = {p: self._mk(p, False) for p in self.bps}
        solde = {p: self._mk(p, True) for p in self.bps}
        self._migrate(('sales', '0010_bug318_not_served'))  # colonne supprimee (0011 inversee)
        self._migrate(None)                                  # 0011 + 0012 rejoues
        for p, pk in normal.items():
            self.assertEqual(self._vals(pk), (p, p, 2 * p), p)
        for p, pk in solde.items():
            u, f, t = self._vals(pk)
            self.assertEqual(f, p, f'prix plein soldee {p}')
            self.assertEqual(u, int((D(p) * D('0.75')).quantize(D('1'), rounding=ROUND_HALF_UP)))
            self.assertEqual(t, 2 * u)
        self.assertFalse(InvoiceLine.objects.filter(full_unit_price__isnull=True).exists())

    def test_soldee_tarif_change_approximation_bornee(self):
        pk150 = self._mk(150, True)    # fige 113
        pk300 = self._mk(300, True)    # fige 225
        for p in (150, 300):
            self.bps[p].unit_price = 400
            self.bps[p].save()
        self._migrate(('sales', '0010_bug318_not_served'))
        self._migrate(None)
        self.assertEqual(self._vals(pk300)[1], 300)
        self.assertLessEqual(abs(self._vals(pk150)[1] - 150), 1)   # limite documentee (151)
        self.assertEqual(self._vals(pk150)[0], 113)
        self.assertEqual(self._vals(pk150)[2], 226)

    def test_unit_price_et_total_jamais_touches_et_idempotence(self):
        pks = [self._mk(p, s) for p in (50, 300) for s in (False, True)]
        before = [(InvoiceLine.objects.get(pk=pk).unit_price, InvoiceLine.objects.get(pk=pk).line_total) for pk in pks]
        InvoiceLine.objects.update(full_unit_price=None)
        MIG12.backfill(global_apps, connection.schema_editor())
        first = [self._vals(pk) for pk in pks]
        MIG12.backfill(global_apps, connection.schema_editor())
        self.assertEqual(first, [self._vals(pk) for pk in pks])
        self.assertEqual(before, [(v[0], v[2]) for v in first])

    def test_lignes_deja_remplies_et_plus_de_500_soldees(self):
        keep = self._mk(300, True)
        InvoiceLine.objects.filter(pk=keep).update(full_unit_price=321)
        inv = Invoice.objects.create(node=self.node, client=self.cl, facturier=self.fa, team='A',
                                     status='PENDING', payment_type='CREDIT', is_soldee=True)
        InvoiceLine.objects.bulk_create([
            InvoiceLine(invoice=inv, bread_price=self.bps[300], quantity=1, unit_price=225, full_unit_price=None)
            for _ in range(1203)])
        MIG12.backfill(global_apps, connection.schema_editor())
        self.assertEqual(self._vals(keep)[1], 321)
        self.assertEqual(InvoiceLine.objects.filter(invoice=inv, full_unit_price=300).count(), 1203)


# --------------------------------------------------------------------------- BUG-519
class Sync519(TestCase):
    _ids = itertools.count(770001)

    def setUp(self):
        from sync.services import _push_invoice_line
        self.push = _push_invoice_line
        self.node = make_node(code='QV5')
        self.bp = make_bread_price('QV519', 'Pain 150', 150)
        fa = make_user('FACTURIER', node=self.node, team='A', username='qv5_fa')
        cl = make_client(self.node)
        self.inv = Invoice.objects.create(node=self.node, client=cl, facturier=fa, team='A', status='PENDING',
                                          payment_type='CREDIT', is_soldee=True)

    def _p(self, **kw):
        rec = {'id': next(self._ids), 'invoice': str(self.inv.pk), 'bread_price': self.bp.pk, 'quantity': 10}
        rec.update(kw)
        with transaction.atomic():
            res = self.push(self.node, rec)
        return rec['id'], res

    def _retarif(self):
        self.bp.unit_price = 400
        self.bp.save()

    def test_soldee_prix_du_noeud_conserves_apres_changement_cloud(self):
        self._retarif()
        lid, res = self._p(unit_price='113', full_unit_price='150')
        self.assertNotEqual(res['status'], 'REJECTED')
        l = InvoiceLine.objects.get(pk=lid)
        self.assertEqual((l.unit_price, l.full_unit_price, l.line_total, l.loss), (113, 150, 1130, D(370)))

    def test_ancien_payload_sans_prix_inchange(self):
        self._retarif()
        lid, res = self._p()
        l = InvoiceLine.objects.get(pk=lid)
        self.assertEqual((l.full_unit_price, l.unit_price), (400, 300))

    def test_ancien_payload_avec_null_explicite(self):
        lid, res = self._p(unit_price=None, full_unit_price=None)
        self.assertNotEqual(res['status'], 'REJECTED')
        self.assertEqual(InvoiceLine.objects.get(pk=lid).full_unit_price, 150)

    def test_prix_zero_accepte_et_valeurs_invalides_rejetees(self):
        lid, res = self._p(unit_price=0, full_unit_price=0)
        self.assertNotEqual(res['status'], 'REJECTED')
        l = InvoiceLine.objects.get(pk=lid)
        self.assertEqual((l.unit_price, l.full_unit_price, l.line_total), (0, 0, 0))
        n = InvoiceLine.objects.count()
        for bad in (100_000_001, 10 ** 30, '9' * 40, ' ', '', {}, '0x10', 'Infinity', 'NaN'):
            for f in ('unit_price', 'full_unit_price'):
                _, r = self._p(**{f: bad})
                self.assertEqual(r['status'], 'REJECTED', (f, bad))
        self.assertEqual(InvoiceLine.objects.count(), n)

    def test_rejeu_meme_id_ne_change_pas_les_prix(self):
        lid, _ = self._p(unit_price=113, full_unit_price=150)
        self._retarif()
        rec = {'id': lid, 'invoice': str(self.inv.pk), 'bread_price': self.bp.pk, 'quantity': 10,
               'unit_price': 999, 'full_unit_price': 999}
        with transaction.atomic():
            self.push(self.node, rec)
        l = InvoiceLine.objects.get(pk=lid)
        self.assertEqual((l.unit_price, l.full_unit_price), (113, 150))
        self.assertEqual(InvoiceLine.objects.filter(pk=lid).count(), 1)

    def test_export_sync_now_transporte_les_deux_prix(self):
        from sync.management.commands import sync_now
        with open(sync_now.__file__, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn("'full_unit_price': _dec(l.full_unit_price)", src)
        self.assertIn("'unit_price': _dec(l.unit_price)", src)


# --------------------------------------------------------------------------- BUG-197
def _now(d, h=10):
    aware = timezone.make_aware(datetime(d.year, d.month, d.day, h, 0), timezone.get_current_timezone())
    return patch('django.utils.timezone.now', return_value=aware.astimezone(dt_timezone.utc))


class Receipt197(TestCase):
    def setUp(self):
        self.n = make_node(code='QV7')
        self.bp = make_bread_price('QV197', 'Pain 500', 500)
        self.f = make_user('FACTURIER', node=self.n, team='A', username='qv7_fa')
        self.cl = make_client(self.n)
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()

    def _post(self, **extra):
        p = {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': 500,
             'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}
        p.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            r = _api(self.f).post(INV, p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return Invoice.objects.get(pk=r.data['id'])

    def test_numeros_heritages_en_double_jamais_reutilises(self):
        with _now(date(2026, 12, 1)):
            a = self._post()
            Invoice.objects.filter(pk=a.pk).update(receipt_number='QV7-20261201-0002')  # numero herite decale
            self._post()
            self._post()
        nums = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(nums), 3)
        self.assertEqual(len(set(nums)), 3, nums)

    def test_vente_retroactive_puis_vente_du_jour_et_remboursement_meme_jour(self):
        day = date(2026, 12, 1)
        back = day - timedelta(days=1)
        with _now(day):
            r1 = self._post(invoice_date=str(back))
            r2 = self._post()
            r3 = self._post(invoice_date=str(back), lines=[], payment_amount=100, is_debt_repayment=True)
        self.assertEqual(r1.receipt_number, 'QV7-20261130-0001')
        self.assertEqual(r2.receipt_number, 'QV7-20261201-0001')
        self.assertEqual(r3.receipt_number, 'QV7-20261130-0002')

    def test_fin_dannee(self):
        with _now(date(2027, 1, 2)):
            a = self._post(invoice_date='2026-12-31')
            b = self._post(invoice_date='2026-12-31')
        self.assertEqual((a.receipt_number, b.receipt_number), ('QV7-20261231-0001', 'QV7-20261231-0002'))


# --------------------------------------------------------------------------- BUG-527 + non-regression
class DailySummary527(TestCase):
    def setUp(self):
        self.n = make_node(code='QV2')
        self.g = make_user('GERANT', node=self.n, username='qv2_g')
        self.hq = make_user('DIRECTION', node=None, username='qv2_d')

    def test_dates_invalides_en_400(self):
        for u in (self.g, self.hq):
            for bad in ('abc', '2026-13-45', '2026-02-30', '0000-00-00', "2026-11-01'; DROP", '2026-11-22T10:00',
                        'x' * 5000, '99999-01-01'):
                r = _api(u).get(INV + 'daily_summary/', {'date': bad})
                self.assertEqual(r.status_code, 400, (u.role, bad[:20], r.status_code))
                self.assertIn('detail', r.data)

    def test_formats_iso_alternatifs_jamais_500(self):
        for ok in ('2026-11-22', '20261122', '2026-W47-7', ''):
            r = _api(self.g).get(INV + 'daily_summary/', {'date': ok})
            self.assertIn(r.status_code, (200, 400), (ok, r.status_code))
        self.assertEqual(_api(self.g).get(INV + 'daily_summary/').status_code, 200)

    def test_voisines_jamais_500(self):
        for ep in ('bread_summary/', 'daily_summary/'):
            for bad in ('abc', '2026-13-45', '20261122'):
                r = _api(self.hq).get(INV + ep, {'date': bad, 'node': 'ZZZ'})
                self.assertLess(r.status_code, 500, (ep, bad))


class NonRegression(TestCase):
    def setUp(self):
        self.n = make_node(code='QV3')
        self.bp = make_bread_price('QV300', 'Pain 300', 300)
        self.f = make_user('FACTURIER', node=self.n, team='A', username='qv3_f')
        self.g = make_user('GERANT', node=self.n, username='qv3_g')
        self.cl = make_client(self.n, credit_limit=D('50000'))

    def _post(self, user=None, **extra):
        p = {'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
             'lines': [{'bread_price': self.bp.pk, 'quantity': 10}]}
        p.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return _api(user or self.f).post(INV, p, format='json')

    def test_bp_cumul_et_prix_catalogue_ignore_prix_client(self):
        r = self._post(payment_amount=1000, lines=[{'bread_price': self.bp.pk, 'quantity': 10, 'unit_price': 1}])
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.order_total, inv.debt_before, inv.debt_after), (D(3000), D(0), D(2000)))
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D(2000))
        self.assertEqual(inv.lines.get().unit_price, 300)

    def test_blocage_credit(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=D(50000))
        self.assertEqual(self._post(payment_amount=2999).status_code, 403)
        self.assertEqual(self._post(payment_amount=3000).status_code, 201)
        Client.objects.filter(pk=self.cl.pk).update(current_debt=D(49999))
        self.assertEqual(self._post(payment_amount=0).status_code, 201)

    def test_remboursement_non_vente(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=D(5000))
        r = self._post(lines=[], payment_amount=2000, is_debt_repayment=True)
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.order_total, inv.lines.count(), inv.is_debt_repayment), (D(0), 0, True))
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D(3000))
        self.assertEqual(inv.debt_after, D(3000))

    def test_recu_mentions_en_api(self):
        r = self._post(payment_amount=500)
        self.assertEqual(r.status_code, 201)
        body = _api(self.g).get(f"{INV}{r.data['id']}/").data
        for key in ('receipt_number', 'debt_before', 'debt_after', 'order_total', 'payment_amount', 'commission_rate'):
            self.assertIn(key, body, key)
        self.assertTrue(body['receipt_number'].startswith('QV3-'))
