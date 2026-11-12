"""
Vérification indépendante (testeur-tresorerie, 2026-11-12) de BUG-189 (verrou de
vacation, date UTC) et du volet trésorerie de BUG-161/B3 (journée de travail).

Horloge simulée par une `Clock` qui avance de 1 ms à chaque appel de
`django.utils.timezone.now()` (renvoie de l'UTC aware comme le vrai `now()`) :
les `created_at` restent strictement ordonnés (ordre de la chaîne de hash).
Kinshasa = UTC+1. Données fictives uniquement.
"""
import unittest
from datetime import date, datetime, timedelta, time as dtime
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.models import Config, ExpenseCategory
from core.testing import make_node, make_user, make_bread_price, make_client, get_config
from production.models import DailyTeamAssignment
from sales.models import Invoice, InvoiceLine
from treasury.models import (
    CashClosure, CashbookEntry, FacturierReport, LocalExpense,
)

J = date(2026, 11, 11)      # journée de travail J
J1 = date(2026, 11, 12)     # J + 1


def _local(d, h, m=0, s=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m, s), timezone.get_current_timezone())


class Clock:
    def __init__(self, d, h, m=0, s=0):
        self.set(d, h, m, s)

    def set(self, d, h, m=0, s=0):
        self.cur = _local(d, h, m, s).astimezone(dt_timezone.utc)

    def _now(self):
        self.cur += timedelta(milliseconds=1)
        return self.cur

    def __enter__(self):
        self._patch = patch('django.utils.timezone.now', side_effect=self._now)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _sale(node, fact, client_obj, bread, qty, invoice_date, team='A', deliver=True):
    inv = Invoice.objects.create(
        node=node, client=client_obj, facturier=fact, team=team,
        status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
        node_origin=node.code, debt_before=Decimal('0.00'), invoice_date=invoice_date,
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    inv.payment_amount = inv.order_total
    inv.compute_debt_after()
    inv.save()
    if deliver:
        inv.deliver(livreur=fact)
    return inv


class _Base(TestCase):
    rotation = True
    handover = dtime(12, 0)

    def setUp(self):
        self.node = make_node(code='K1')
        self.node.team_rotation_enabled = self.rotation
        self.node.handover_time = self.handover
        self.node.save(update_fields=['team_rotation_enabled', 'handover_time'])
        self.gerant = make_user('GERANT', node=self.node, username='g_v1')
        self.facA = make_user('FACTURIER', node=self.node, team='A', username='fa_v1')
        self.comptable = make_user('COMPTABLE', username='c_v1')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price('MOYEN', 'Pain 300 FC', 300)
        self.api = _api(self.gerant)
        self.api_c = _api(self.comptable)
        self.cat, _ = ExpenseCategory.objects.get_or_create(code='EAU', defaults={'label': 'Eau'})

    def gen(self, d=None, api=None):
        r = (api or self.api).post('/api/treasury/reports/generate/', {'date': str(d)} if d else {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def closure(self, payload=None, api=None):
        return (api or self.api).post('/api/treasury/closures/', payload or {}, format='json')


class RotationLevel1And2Tests(_Base):
    def test_reports_grouped_by_work_day_and_closure_levels(self):
        with Clock(J1, 3, 0) as clk:                       # J+1 03:00 -> journée J
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J)       # 1500
            clk.set(J1, 11, 59)
            _sale(self.node, self.facA, self.client_obj, self.bread, 2, J)       # 600
            clk.set(J1, 12, 0)                              # relève pile -> journée J+1
            _sale(self.node, self.facA, self.client_obj, self.bread, 3, J1)      # 900 (autre équipe n'existe pas)
            # rapport sans date, 11:59:59 -> journée J
            clk.set(J1, 11, 59, 59)
            reports = self.gen()
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]['date'], str(J))
            self.assertEqual(Decimal(reports[0]['total_cash_sales']), Decimal('2100'))
            self.assertEqual(Decimal(reports[0]['theoretical_cash']), Decimal('2100'))
            # verrou : nouvelle livraison dans la journée J refusée
            late = _sale(self.node, self.facA, self.client_obj, self.bread, 1, J, deliver=False)
            with self.assertRaises(ValidationError):
                late.deliver(livreur=self.facA)
            # dépense J, clôture par défaut = J
            LocalExpense.objects.create(node=self.node, gerant=self.gerant, description='Eau',
                                        amount=Decimal('400'), category=self.cat, date=J)
            payload = {'bills_1000': 1, 'bills_500': 2, 'bills_200': 1, 'bills_100': 3, 'bills_50': 2}
            r = self.closure({'date': str(J), **payload})
            self.assertEqual(r.status_code, 201, r.content)
            body = r.json()
            self.assertEqual(body['date'], str(J))
            self.assertEqual(Decimal(body['net_cash']), Decimal('1700'))                 # 2100 - 400
            self.assertEqual(Decimal(body['physical_cash_total']), Decimal('2600'))      # somme billets
            self.assertEqual(Decimal(body['cash_gap']), Decimal('900'))                  # écart positif
            # double clôture même jour/nœud
            r2 = self.closure({'date': str(J), **payload})
            self.assertEqual(r2.status_code, 400, r2.content)
            # suggested_ca cohérent avec la clôture
            s = self.api.get('/api/treasury/journal/suggested_ca/', {'date': str(J)})
            self.assertEqual(s.status_code, 200)
            self.assertTrue(s.json()['available'])
            self.assertEqual(Decimal(s.json()['amount']), Decimal('2100'))
            # journée suivante à 12:00 : rapport J+1 = 900, clôture J+1 par défaut
            clk.set(J1, 12, 0, 30)
            r1 = self.gen()
            self.assertEqual(r1[0]['date'], str(J1))
            self.assertEqual(Decimal(r1[0]['total_cash_sales']), Decimal('900'))
            c2 = self.closure({'date': str(J1), 'bills_500': 1})
            self.assertEqual(c2.status_code, 201, c2.content)
            self.assertEqual(c2.json()['date'], str(J1))
            self.assertEqual(Decimal(c2.json()['cash_gap']), Decimal('500') - Decimal('900'))   # écart négatif

    def test_zero_gap_and_gap_not_editable_once_validated(self):
        with Clock(J1, 3, 0):
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J)
            self.gen()
            r = self.closure({'date': str(J), 'bills_1000': 1, 'bills_500': 1})   # 1500 = 1500 -> écart nul
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(Decimal(r.json()['cash_gap']), Decimal('0'))
            cid = r.json()['id']
            self.assertEqual(self.api_c.post(f'/api/treasury/closures/{cid}/validate/', {}, format='json').status_code, 200)
            p = self.api.patch(f'/api/treasury/closures/{cid}/', {'bills_50': 99}, format='json')
            self.assertEqual(p.status_code, 400, p.content)
            self.assertEqual(CashClosure.objects.get(pk=cid).bills_50, 0)

    def test_closure_recomputed_when_sale_arrives_after_preparation(self):
        """Vente livrée dans la journée après création de la clôture : rapport régénéré puis
        clôture non validée re-soumise -> totaux recalculés (BUG-034 : resoumission)."""
        with Clock(J1, 3, 0) as clk:
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J)
            self.gen()
            r = self.closure({'date': str(J), 'bills_1000': 1, 'bills_500': 1})
            cid = r.json()['id']
            # autre équipe : le verrou ne concerne que (nœud, équipe, jour)
            facB = make_user('FACTURIER', node=self.node, team='B', username='fb_v1')
            clk.set(J1, 10, 0)
            _sale(self.node, facB, self.client_obj, self.bread, 2, J, team='B')
            self.gen()
            self.assertEqual(self.api.patch(f'/api/treasury/closures/{cid}/', {'bills_500': 2}, format='json').status_code, 200)
            c = CashClosure.objects.get(pk=cid)
            self.assertEqual(c.total_entries, Decimal('2100.00'))
            self.assertEqual(c.net_cash, Decimal('2100.00'))
            self.assertEqual(c.physical_cash_total, Decimal('2000.00'))
            self.assertEqual(c.cash_gap, Decimal('-100.00'))


class RotationCashbookTests(_Base):
    def _closure_validated_pushed(self, d, bills):
        r = self.closure({'date': str(d), **bills})
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()['id']
        self.assertEqual(self.api_c.post(f'/api/treasury/closures/{cid}/validate/', {}, format='json').status_code, 200)
        p = self.api_c.post(f'/api/treasury/closures/{cid}/push_to_cashbook/', {}, format='json')
        self.assertEqual(p.status_code, 201, p.content)
        return p.json()

    def _both_verdicts(self):
        a = self.api_c.get('/api/treasury/cashbook/integrity_check/')
        self.assertEqual(a.status_code, 200, a.content)
        b = self.api_c.post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(b.status_code, 200, b.content)
        return a.json()['chain_valid'], b.json()['all_intact']

    def test_versement_date_piece_balance_and_chain_across_handover_and_midnight(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        with Clock(J1, 3, 0) as clk:
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J)       # 1500 (journée J)
            self.gen()
            e1 = self._closure_validated_pushed(J, {'bills_1000': 1, 'bills_500': 1})
            self.assertEqual(e1['piece_number'], 'VC-K1-20261111')
            self.assertEqual(e1['date'], str(J))
            self.assertEqual(Decimal(e1['running_balance']), Decimal('1500'))
            # double versement
            cid = CashClosure.objects.get(node=self.node, date=J).id
            self.assertEqual(self.api_c.post(f'/api/treasury/closures/{cid}/push_to_cashbook/', {}, format='json').status_code, 400)
            clk.set(J1, 12, 5)                                                   # nouvelle journée J+1
            _sale(self.node, self.facA, self.client_obj, self.bread, 3, J1)      # 900
            self.gen()
            LocalExpense.objects.create(node=self.node, gerant=self.gerant, description='Eau',
                                        amount=Decimal('100'), category=self.cat, date=J1)
            e2 = self._closure_validated_pushed(J1, {'bills_500': 1, 'bills_200': 1, 'bills_100': 1})
            self.assertEqual(e2['piece_number'], 'VC-K1-20261112')
            self.assertEqual(Decimal(e2['entry_amount']), Decimal('800'))        # 900 - 100
            self.assertEqual(Decimal(e2['running_balance']), Decimal('2300'))
            # série d'écritures supplémentaires à cheval sur minuit et relève (bordereaux/corrections)
            from treasury.views import append_cashbook_entry
            d = J1
            for i in range(30):
                clk.set(d + timedelta(days=1 + i // 3), (0, 11, 23)[i % 3], 59 if i % 3 == 2 else 30)
                append_cashbook_entry(
                    node=self.node, date=timezone.localdate(), piece_number=f'T-{i:03d}',
                    imputation='7000', label=f'Série {i}', entry_amount=Decimal('10'),
                    exit_amount=Decimal('0'), node_origin='K1',
                )
            self.assertEqual(CashbookEntry.objects.count(), 32)
            self.assertEqual(self._both_verdicts(), (True, True))
            last = CashbookEntry.objects.order_by('date', 'created_at').last()
            self.assertEqual(last.running_balance, Decimal('2600'))

    def test_direct_db_tampering_detected_by_both_endpoints(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        with Clock(J1, 3, 0):
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J)
            self.gen()
            self._closure_validated_pushed(J, {'bills_1000': 1, 'bills_500': 1})
            self.assertEqual(self._both_verdicts(), (True, True))
            CashbookEntry.objects.filter(node=self.node).update(entry_amount=Decimal('9999'))
            self.assertEqual(self._both_verdicts(), (False, False))

    def test_hash_single_function(self):
        import treasury.hashing as th
        import blockchain.views as bv
        import treasury.views as tv
        self.assertIs(bv.verify_cashbook_chain, th.verify_cashbook_chain)
        self.assertIs(tv.verify_cashbook_chain, th.verify_cashbook_chain)
        self.assertIs(tv.compute_cashbook_entry_hash, th.compute_cashbook_entry_hash)


class OutOfOrderPushProbe(_Base):
    """Sonde : deux boulangeries versent des journées de dates différentes dans le désordre
    (chaîne globale ordonnée (date, created_at) alors que previous_hash suit l'ordre d'ajout)."""

    def test_two_nodes_push_out_of_date_order_keeps_chain_valid(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        node2 = make_node(code='K2')
        g2 = make_user('GERANT', node=node2, username='g_v2')
        with Clock(J1, 3, 0) as clk:
            r1 = self.closure({'date': str(J), 'bills_50': 1})
            r2 = _api(g2).post('/api/treasury/closures/', {'date': str(J - timedelta(days=1)), 'bills_50': 1}, format='json')
            self.assertEqual((r1.status_code, r2.status_code), (201, 201), (r1.content, r2.content))
            for cid in (r1.json()['id'], r2.json()['id']):
                self.api_c.post(f'/api/treasury/closures/{cid}/validate/', {}, format='json')
            # J+1 de K1 versé AVANT J de K2
            self.assertEqual(self.api_c.post(f"/api/treasury/closures/{r1.json()['id']}/push_to_cashbook/", {}, format='json').status_code, 201)
            clk.set(J1, 4, 0)
            self.assertEqual(self.api_c.post(f"/api/treasury/closures/{r2.json()['id']}/push_to_cashbook/", {}, format='json').status_code, 201)
            a = self.api_c.get('/api/treasury/cashbook/integrity_check/').json()
            self.assertTrue(a['chain_valid'], a)


class NoRotationEquivalenceTests(_Base):
    rotation = False

    def test_no_rotation_local_calendar_date_at_00_30_and_03_00(self):
        with Clock(J1, 0, 30) as clk:
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J1)
            clk.set(J1, 3, 0)
            _sale(self.node, make_user('FACTURIER', node=self.node, team='B', username='fb_v2'),
                  self.client_obj, self.bread, 2, J1, team='B')
            reports = self.gen()
            self.assertEqual({r['date'] for r in reports}, {str(J1)})   # jamais J (UTC / relève ignorée)
            self.assertEqual(sum(Decimal(r['total_cash_sales']) for r in reports), Decimal('2100'))
            c = self.closure({'date': str(J1), 'bills_1000': 2})
            self.assertEqual(c.status_code, 201, c.content)
            self.assertEqual(c.json()['date'], str(J1))
            self.assertEqual(Decimal(c.json()['net_cash']), Decimal('2100'))

    def test_lock_with_and_without_backdated_setting_at_00_30(self):
        for allow in (False, True):
            FacturierReport.objects.all().delete()
            Invoice.objects.all().delete()
            cfg = get_config()
            cfg.allow_backdated_sales = allow
            cfg.save()
            with Clock(J1, 0, 30):
                first = _sale(self.node, self.facA, self.client_obj, self.bread, 5, J1)
                self.gen()
                second = _sale(self.node, self.facA, self.client_obj, self.bread, 1, J1, deliver=False)
                with self.assertRaises(ValidationError):
                    second.deliver(livreur=self.facA)

    def test_default_month_year_of_reports_at_00_30_on_first_of_month(self):
        from treasury.models import JournalEntry
        d1 = date(2026, 12, 1)
        with Clock(d1, 0, 30):                                  # 1er décembre 00:30 locale = 30/11 23:30 UTC
            r = self.api.get('/api/treasury/journal/monthly_report/')
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual((r.json()['month'], r.json()['year']), ('12', '2026'))


class RotationDefaultsTests(_Base):
    def test_rotation_default_month_is_work_month_before_handover(self):
        with Clock(date(2026, 12, 1), 3, 0):                   # journée de travail = 30/11
            r = self.api.get('/api/treasury/journal/monthly_report/')
            self.assertEqual((r.json()['month'], r.json()['year']), ('11', '2026'))
        with Clock(date(2026, 12, 1), 12, 0):
            r = self.api.get('/api/treasury/journal/monthly_report/')
            self.assertEqual((r.json()['month'], r.json()['year']), ('12', '2026'))

    def test_journal_entry_default_date_is_work_date_in_rotation(self):
        with Clock(J1, 3, 0):
            r = self.api.post('/api/treasury/journal/', {'imput': 'RATION', 'exit_amount': '100'}, format='json')
            self.assertIn(r.status_code, (201, 400), r.content)
            if r.status_code == 201:
                self.assertEqual(r.json()['date'], str(J))

    def test_future_closure_date_refused_and_current_work_date_accepted(self):
        with Clock(J1, 3, 0):
            self.assertEqual(self.closure({'date': str(J1)}).status_code, 400)   # J+1 calendaire = futur
            self.assertEqual(self.closure({'date': str(J)}).status_code, 201)    # journée courante
            self.assertEqual(self.closure({'date': str(J - timedelta(days=1))}).status_code, 400)  # passé sans réglage


class NodeIsolationTests(_Base):
    def test_two_nodes_with_different_handover_have_different_work_days(self):
        node2 = make_node(code='K2')
        node2.team_rotation_enabled = True
        node2.handover_time = dtime(6, 0)
        node2.save(update_fields=['team_rotation_enabled', 'handover_time'])
        g2 = make_user('GERANT', node=node2, username='g_v3')
        f2 = make_user('FACTURIER', node=node2, team='A', username='fa_v3')
        c2 = make_client(node2)
        with Clock(J1, 8, 0):
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J)     # K1 : journée J
            _sale(node2, f2, c2, self.bread, 2, J1)                              # K2 : journée J+1
            r1 = self.gen()
            r2 = self.gen(api=_api(g2))
            self.assertEqual(r1[0]['date'], str(J))
            self.assertEqual(r2[0]['date'], str(J1))
            self.assertEqual(Decimal(r1[0]['total_cash_sales']), Decimal('1500'))
            self.assertEqual(Decimal(r2[0]['total_cash_sales']), Decimal('600'))
            self.assertEqual(_api(g2).get('/api/treasury/reports/').json()['count']
                             if 'count' in _api(g2).get('/api/treasury/reports/').json()
                             else len(_api(g2).get('/api/treasury/reports/').json()), 1)


class RetroRotationTests(TransactionTestCase):
    """Ventes rétroactives (BUG-083/086) en rotation : plafond = journée de travail courante."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])
        self.gerant = make_user('GERANT', node=self.node, username='g_r1')
        self.facA = make_user('FACTURIER', node=self.node, team='A', username='fa_r1')
        self.comptable = make_user('COMPTABLE', username='c_r1')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price('MOYEN', 'Pain 300 FC', 300)
        self.api_f = _api(self.facA)
        self.api_g = _api(self.gerant)
        self.api_c = _api(self.comptable)
        DailyTeamAssignment.objects.create(node=self.node, work_date=J, team='A')

    def _post_invoice(self, d):
        return self.api_f.post('/api/sales/invoices/', {
            'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': '300',
            'invoice_date': str(d), 'lines': [{'bread_price': self.bread.pk, 'quantity': 1}],
        }, format='json')

    def test_invoice_date_ceiling_is_work_day_not_calendar_day(self):
        with Clock(J1, 3, 0):                                   # calendrier J+1, journée J
            r = self._post_invoice(J1)                          # futur selon la journée de travail
            self.assertEqual(r.status_code, 400, r.content)
            ok = self._post_invoice(J)
            self.assertEqual(ok.status_code, 201, ok.content)
            old = self._post_invoice(J - timedelta(days=1))     # passé, réglage OFF
            self.assertEqual(old.status_code, 400, old.content)

    def test_retroactive_delivery_on_already_pushed_day_writes_correction_chain_valid(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        prev = J - timedelta(days=1)
        with Clock(J1, 3, 0):
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, prev, deliver=False)
            inv0 = Invoice.objects.get()
            inv0.deliver(livreur=self.facA, delivered_at=_local(prev, 14, 0))
            self.assertEqual(self.api_g.post('/api/treasury/reports/generate/', {'date': str(prev)}, format='json').status_code, 200)
            cr = self.api_g.post('/api/treasury/closures/', {'date': str(prev), 'bills_1000': 1, 'bills_500': 1}, format='json')
            self.assertEqual(cr.status_code, 201, cr.content)
            cid = cr.json()['id']
            self.api_c.post(f'/api/treasury/closures/{cid}/validate/', {}, format='json')
            self.assertEqual(self.api_c.post(f'/api/treasury/closures/{cid}/push_to_cashbook/', {}, format='json').status_code, 201)
            before = CashbookEntry.objects.get(source_closure_id=cid, is_correction=False)
            snap = (before.block_hash, before.running_balance, before.entry_amount)
            r = self._post_invoice(prev)
            self.assertEqual(r.status_code, 201, r.content)
            d = self.api_f.post(f"/api/sales/invoices/{r.json()['id']}/deliver/", {'delivered_at': str(prev)}, format='json')
            self.assertEqual(d.status_code, 200, d.content)
            inv = Invoice.objects.get(pk=r.json()['id'])
            self.assertEqual(timezone.localtime(inv.delivered_at).date() in (prev, J), True)
            corr = CashbookEntry.objects.filter(is_correction=True)
            self.assertEqual(corr.count(), 1)
            self.assertEqual(corr.get().entry_amount, Decimal('300.00'))
            before.refresh_from_db()
            self.assertEqual(snap, (before.block_hash, before.running_balance, before.entry_amount))
            a = self.api_c.get('/api/treasury/cashbook/integrity_check/').json()
            b = self.api_c.post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
            self.assertTrue(a['chain_valid'])
            self.assertTrue(b['all_intact'])


class ClosureDeleteProbe(_Base):
    def test_validated_and_pushed_closure_cannot_be_deleted_by_gerant(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        with Clock(J1, 3, 0):
            r = self.closure({'date': str(J), 'bills_50': 3})
            cid = r.json()['id']
            self.api_c.post(f'/api/treasury/closures/{cid}/validate/', {}, format='json')
            self.api_c.post(f'/api/treasury/closures/{cid}/push_to_cashbook/', {}, format='json')
            d = self.api.delete(f'/api/treasury/closures/{cid}/')
            self.assertIn(d.status_code, (400, 403, 405), d.status_code)
            self.assertTrue(CashClosure.objects.filter(pk=cid).exists())
            self.assertTrue(self.api_c.get('/api/treasury/cashbook/integrity_check/').json()['chain_valid'])
