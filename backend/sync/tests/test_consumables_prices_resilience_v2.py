"""
Testeur charge/resilience, ronde b2 (2026-11-22) : nouveaux angles sur
`production.ConsumableInventory` / `production.ConsumableCount` (BUG-386),
les prix figes de `InvoiceLine` (BUG-519) et la reprise apres coupure.

Defaut non corrige = `@expectedFailure` + ticket BUG-7NN. Donnees fictives.
"""
import itertools
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import ConsumableCount, ConsumableInventory
from sales.models import Invoice, InvoiceLine
from sync import services
from sync.management.commands.sync_now import apply_push_response, build_outbound_payload
from sync.models import NodeAuthToken, SyncBatchLog

URL = '/api/sync/push/'
INV = 'production.ConsumableInventory'
CNT = 'production.ConsumableCount'
LINE = 'sales.InvoiceLine'


def _api(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    api = APIClient(raise_request_exception=False)
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return api


def _push(api, records, batch_id=None):
    return api.post(URL, {'batch_id': batch_id or str(uuid.uuid4()), 'records': records}, format='json')


def _inv(inv_id=None, node='K1', day='2026-11-20', **extra):
    rec = {'id': inv_id or str(uuid.uuid4()), 'node': node, 'inventory_date': day,
           'comment': 'RAS', 'node_origin': node}
    rec.update(extra)
    return rec


def _cnt(inv_id=None, node='K1', day='2026-11-20', ctype='FARINE', system='10.000',
         physical='9.500', gap='-0.500', **extra):
    rec = {'node': node, 'consumable_type': ctype, 'count_date': day,
           'system_quantity': system, 'physical_quantity': physical, 'gap': gap, 'notes': ''}
    if inv_id is not None:
        rec['inventory'] = inv_id
    rec.update(extra)
    return rec


def _st(resp, label, idx=0):
    return resp.data['results'][label][idx]['status']


class ConsumableHostileTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api = _api(self.k1)

    def test_uuid_equivalent_majuscules_est_le_meme_inventaire(self):
        inv_id = str(uuid.uuid4())
        _push(self.api, {INV: [_inv(inv_id)]})
        resp = _push(self.api, {INV: [_inv(inv_id.upper())]})
        self.assertEqual(_st(resp, INV), 'ACCEPTED')
        self.assertEqual(ConsumableInventory.objects.count(), 1)

    def test_types_hostiles_inventaire_rejetes_sans_500(self):
        bad_values = [None, '', 5, 2.5, True, [], {}, 'x' * 100, '2026-02-30', '20/11/2026']
        for bad in bad_values:
            resp = _push(self.api, {INV: [_inv(inventory_date=bad)]})
            self.assertEqual(resp.status_code, 200, repr(bad))
            self.assertEqual(_st(resp, INV), 'REJECTED', repr(bad))
        for bad in (5, ['x'], {'a': 1}, True):
            resp = _push(self.api, {INV: [_inv(comment=bad)]})
            self.assertEqual(_st(resp, INV), 'REJECTED', repr(bad))
        self.assertEqual(ConsumableInventory.objects.count(), 0)

    def test_types_hostiles_comptage_rejetes_sans_500(self):
        cases = [
            dict(system_quantity='NaN'), dict(physical_quantity='Infinity'),
            dict(system_quantity=True), dict(system_quantity=[1]), dict(gap=None),
            dict(system_quantity='1' * 30), dict(physical_quantity='0.0001', gap='-9.9999'),
            dict(consumable_type=''), dict(consumable_type='X' * 11), dict(consumable_type=5),
            dict(count_date='2026-99-99'), dict(notes=7), dict(inventory=12345),
        ]
        for case in cases:
            resp = _push(self.api, {CNT: [_cnt(**case)]})
            self.assertEqual(resp.status_code, 200, case)
            self.assertEqual(_st(resp, CNT), 'REJECTED', case)
        self.assertEqual(ConsumableCount.objects.count(), 0)

    def test_inventaire_date_future_rejete(self):
        future = (date.today() + timedelta(days=400)).isoformat()
        resp = _push(self.api, {INV: [_inv(day=future)]})
        self.assertEqual(_st(resp, INV), 'REJECTED')

    def test_quantite_physique_negative_rejetee(self):
        resp = _push(self.api, {CNT: [_cnt(system='1.000', physical='-3.000', gap='-4.000')]})
        self.assertEqual(_st(resp, CNT), 'REJECTED')

    @expectedFailure  # BUG-729
    def test_type_de_consommable_inconnu_rejete(self):
        # `ConsumableType` (Configuration) fait foi ; un code fantaisie pollue les etats.
        resp = _push(self.api, {CNT: [_cnt(ctype='ZZZ')]})
        self.assertEqual(_st(resp, CNT), 'REJECTED')

    def test_deux_lignes_meme_type_meme_inventaire_valeurs_differentes_refusees(self):
        inv_id = str(uuid.uuid4())
        _push(self.api, {INV: [_inv(inv_id)]})
        r1 = _push(self.api, {CNT: [_cnt(inv_id, physical='9.500', gap='-0.500')]})
        r2 = _push(self.api, {CNT: [_cnt(inv_id, physical='1.000', gap='-9.000')]})
        self.assertEqual(_st(r1, CNT), 'ACCEPTED')
        self.assertEqual(_st(r2, CNT), 'REJECTED')
        self.assertEqual(ConsumableCount.objects.filter(inventory_id=inv_id, consumable_type='FARINE').count(), 1)

    def test_comptage_decimal_a_trois_decimales_sel_levure_huile(self):
        inv_id = str(uuid.uuid4())
        _push(self.api, {INV: [_inv(inv_id)]})
        for ctype, sysq, phys, gap in (('SEL', '1500.000', '1499.500', '-0.500'),
                                       ('LEVURE', '0.250', '0.125', '-0.125'),
                                       ('HUILE', '2.750', '2.750', '0.000')):
            resp = _push(self.api, {CNT: [_cnt(inv_id, ctype=ctype, system=sysq, physical=phys, gap=gap)]})
            self.assertEqual(_st(resp, CNT), 'ACCEPTED', ctype)
        self.assertEqual(ConsumableCount.objects.get(consumable_type='LEVURE').gap, Decimal('-0.125'))

    def test_lot_inventaire_avec_cles_inversees_et_rejeu_triple(self):
        inv_id = str(uuid.uuid4())
        recs = {CNT: [_cnt(inv_id)], INV: [_inv(inv_id)]}
        for _ in range(3):
            resp = _push(self.api, recs)
            self.assertEqual(_st(resp, CNT), 'ACCEPTED')
        self.assertEqual(ConsumableInventory.objects.count(), 1)
        self.assertEqual(ConsumableCount.objects.count(), 1)


class OutboundPartialSyncTests(TestCase):
    """Un inventaire accepte dont une ligne est rejetee ne doit pas perdre cette ligne."""

    def test_ligne_rejetee_reste_a_renvoyer(self):
        k1 = make_node(code='K1')
        api = _api(k1)
        inv = ConsumableInventory(node=k1, inventory_date=date(2026, 11, 20), node_origin='K1')
        inv.save()
        good = ConsumableCount.objects.create(
            node=k1, consumable_type='FARINE', count_date=date(2026, 11, 20),
            system_quantity=Decimal('10'), physical_quantity=Decimal('9'), gap=Decimal('-1'), inventory=inv)
        bad = ConsumableCount.objects.create(
            node=k1, consumable_type='SEL', count_date=date(2026, 11, 20),
            system_quantity=Decimal('10'), physical_quantity=Decimal('9'), gap=Decimal('-1'), inventory=inv)
        # Le Cloud refusera cette ligne (ecart incoherent) : on simule la donnee locale corrompue.
        ConsumableCount.objects.filter(pk=bad.pk).update(gap=Decimal('5'))
        self.assertTrue(ConsumableInventory.objects.get(pk=inv.pk).is_synced is False)

        payload = build_outbound_payload('K1')
        resp = _push(api, payload['records'] if 'records' in payload else payload)
        self.assertEqual(resp.status_code, 200)
        statuses = sorted(r['status'] for r in resp.data['results'][CNT])
        self.assertEqual(statuses, ['ACCEPTED', 'REJECTED'])
        apply_push_response(resp.data)

        # Cycle suivant : la ligne rejetee doit toujours etre dans le lot sortant.
        again = build_outbound_payload('K1')
        again_records = again['records'] if 'records' in again else again
        sent_types = {r['consumable_type'] for r in again_records.get(CNT, [])}
        self.assertIn('SEL', sent_types, "ligne rejetee definitivement perdue (inventaire marque synchronise)")
        self.assertTrue(good.pk)


class ResilienceTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api = _api(self.k1)

    def _records(self, n=3):
        from decimal import Decimal as D
        clients = [{'id': str(uuid.uuid4()), 'node': 'K1', 'first_name': f'F{i}', 'last_name': 'L',
                    'node_origin': 'K1'} for i in range(n)]
        invs = [{'id': str(uuid.uuid4()), 'node': 'K1', 'client': c['id'], 'status': 'PENDING',
                 'payment_type': 'CREDIT', 'order_total': '1000', 'payment_amount': '0',
                 'node_origin': 'K1'} for c in clients]
        mvs = [{'id': str(uuid.uuid4()), 'client': c['id'], 'invoice': i['id'], 'amount': '1000',
                'kind': 'ORDER'} for c, i in zip(clients, invs)]
        return {'clients.Client': clients, 'sales.Invoice': invs, 'sync.DebtMovement': mvs}, D('1000.00')

    def test_reponse_perdue_apres_traitement_le_rejeu_ne_duplique_rien(self):
        recs, amount = self._records()
        bid = str(uuid.uuid4())
        _push(self.api, recs, batch_id=bid)  # reponse "perdue" cote noeud
        again = _push(self.api, recs, batch_id=bid)
        self.assertTrue(again.data['replayed'])
        from clients.models import Client
        self.assertEqual(Client.objects.count(), 3)
        self.assertEqual(Invoice.objects.count(), 3)
        for c in Client.objects.all():
            self.assertEqual(c.current_debt, amount)

    def test_coupure_en_milieu_de_lot_puis_reprise_sans_perte_ni_doublon(self):
        recs, amount = self._records()
        bid = str(uuid.uuid4())
        real = services.PUSH_HANDLERS['sales.Invoice']
        state = {'n': 0}

        def crashing(node, record):
            state['n'] += 1
            if state['n'] == 2:
                raise OperationalError('disk I/O error')  # coupure franche (pas "locked")
            return real(node, record)

        with patch.dict(services.PUSH_HANDLERS, {'sales.Invoice': crashing}):
            first = _push(self.api, recs, batch_id=bid)
        self.assertGreaterEqual(first.status_code, 500)
        # Aucun journal de lot fige : le rejeu doit pouvoir tout terminer.
        self.assertFalse(SyncBatchLog.objects.filter(batch_id=bid).exists())
        second = _push(self.api, recs, batch_id=bid)
        self.assertEqual(second.status_code, 200)
        for label in recs:
            self.assertEqual([r['status'] for r in second.data['results'][label]], ['ACCEPTED'] * 3, label)
        from clients.models import Client
        self.assertEqual(Client.objects.count(), 3)
        self.assertEqual(Invoice.objects.count(), 3)
        for c in Client.objects.all():
            self.assertEqual(c.current_debt, amount)

    def test_apply_push_response_tolere_reponse_cloud_malformee(self):
        # Reponse hostile/ancienne version : ne doit pas lever et ne marque rien a tort.
        k1_client = make_client(self.k1)
        k1_client.is_synced = False
        k1_client.save(_sync_bypass=True)
        type(k1_client).objects.filter(pk=k1_client.pk).update(is_synced=False)
        for bad in ({'results': {'clients.Client': [{'status': 'ACCEPTED'}]}},
                    {'results': {'clients.Client': [{'id': 'pas-uuid', 'status': 'ACCEPTED'}]}},
                    {'results': {'clients.Client': 'x'}},
                    {'results': []}, {'results': None}):
            try:
                apply_push_response(bad)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"apply_push_response a leve {type(exc).__name__} sur {bad}")
        k1_client.refresh_from_db()
        self.assertFalse(k1_client.is_synced)


class InvoiceLinePricesHostileTests(TestCase):
    _ids = itertools.count(700001)

    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.api = _api(self.k1)
        self.bp = make_bread_price('QB7', 'Pain 300', 300)
        fa = make_user('FACTURIER', node=self.k1, team='A', username='v2_fa')
        cl = make_client(self.k1)
        self.inv = Invoice.objects.create(
            node=self.k1, client=cl, facturier=fa, team='A', status='PENDING', payment_type='CREDIT',
            payment_amount=Decimal('0'), order_total=Decimal('0'), initial_order_total=Decimal('0'))
        fa2 = make_user('FACTURIER', node=self.k2, team='A', username='v2_fa2')
        self.foreign_inv = Invoice.objects.create(
            node=self.k2, client=make_client(self.k2), facturier=fa2, team='A', status='PENDING',
            payment_type='CREDIT', payment_amount=Decimal('0'), order_total=Decimal('0'),
            initial_order_total=Decimal('0'))

    def _line(self, invoice=None, **kw):
        rec = {'id': next(self._ids), 'invoice': str((invoice or self.inv).pk),
               'bread_price': self.bp.pk, 'quantity': 10}
        rec.update(kw)
        return rec

    def test_debordement_line_total_rejete_sans_ligne_residuelle(self):
        rec = self._line(quantity=1_000_000, unit_price=100_000_000, full_unit_price=100_000_000)
        resp = _push(self.api, {LINE: [rec]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_st(resp, LINE), 'REJECTED')
        self.assertFalse(InvoiceLine.objects.filter(pk=rec['id']).exists())

    def test_prix_et_quantites_hostiles_rejetes(self):
        for kw in (dict(unit_price='1e3'), dict(unit_price=' 300 ', full_unit_price='300.5'),
                   dict(quantity='1e3'), dict(quantity=-1), dict(quantity=1_000_001),
                   dict(quantity=[1]), dict(unit_price={'a': 1}), dict(unit_price='٣٠٠')):
            before = InvoiceLine.objects.count()
            resp = _push(self.api, {LINE: [self._line(**kw)]})
            self.assertEqual(resp.status_code, 200, kw)
            if _st(resp, LINE) == 'ACCEPTED':
                # Seules les formes numeriquement equivalentes a un entier FC sont tolerees.
                self.assertIn(list(kw)[0], ('unit_price',), kw)
            else:
                self.assertEqual(InvoiceLine.objects.count(), before, kw)

    def test_ligne_ajoutee_a_la_facture_d_une_autre_boulangerie_refusee(self):
        rec = self._line(invoice=self.foreign_inv)
        resp = _push(self.api, {LINE: [rec]})  # jeton K1, facture K2
        self.assertEqual(_st(resp, LINE), 'REJECTED')
        self.assertFalse(InvoiceLine.objects.filter(invoice=self.foreign_inv).exists())

    def test_prix_net_superieur_au_prix_plein_rejete(self):
        resp = _push(self.api, {LINE: [self._line(unit_price=900_000, full_unit_price=300)]})
        self.assertEqual(_st(resp, LINE), 'REJECTED')

    def test_rejeu_de_ligne_avec_prix_modifies_ne_change_pas_le_prix_fige(self):
        rec = self._line(unit_price=300, full_unit_price=300)
        _push(self.api, {LINE: [rec]})
        _push(self.api, {LINE: [dict(rec, unit_price=1, full_unit_price=1)]})
        line = InvoiceLine.objects.get(pk=rec['id'])
        self.assertEqual((line.unit_price, line.full_unit_price), (300, 300))
        self.assertEqual(InvoiceLine.objects.filter(pk=rec['id']).count(), 1)

    @expectedFailure  # BUG-732
    def test_total_facture_doit_correspondre_a_la_somme_des_lignes(self):
        # Facture poussee a 1 000 FC, puis ligne de 10 x 300 = 3 000 FC : incoherence acceptee.
        resp = _push(self.api, {LINE: [self._line(unit_price=300, full_unit_price=300)]})
        total = sum(l.line_total for l in InvoiceLine.objects.filter(invoice=self.inv))
        self.inv.refresh_from_db()
        self.assertTrue(_st(resp, LINE) == 'REJECTED' or total == self.inv.order_total,
                        f"lignes={total} entete={self.inv.order_total}")
