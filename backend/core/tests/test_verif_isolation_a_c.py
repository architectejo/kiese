"""Contre-verification Dev C (testeur-permissions, 2026-11-22-c) du lot A :
BUG-503 / 504 / 505 / 362 (isolation inter-boulangeries).

Cible ce que les tests de A ne couvrent pas : transferts (BreadTransfer),
disposals / counts / stocks, tresorerie (clotures, depenses, journal,
epargne, bordereaux), ventes (facture etrangere, `node` force, actions
personnalisees), balayage automatique des routes GET avec `?node=<autre>`,
comptes du siege non casses, exception 5.1 (facturier cherche, n'ecrit pas).
Donnees fictives uniquement.
"""
from decimal import Decimal as Dc
from unittest import expectedFailure

from rest_framework.schemas.generators import EndpointEnumerator

from core.models import ExpenseCategory, Node
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk
from clients.models import Client
from production.models import (BreadDisposal, BreadTransfer, BreadTransferLine,
                               ConsumableCount, ConsumableMovement, ConsumableStock)
from sales.models import Invoice
from treasury.models import (CashClosure, DisbursementVoucher, FacturierReport,
                             JournalEntry, LocalExpense, DailySavings)

D = '2026-11-18'


def rows(r):
    d = r.data
    return d['results'] if isinstance(d, dict) and 'results' in d else d


def _stock(node, code='FAR', qty=Dc('10')):
    s, _ = ConsumableStock.objects.get_or_create(
        node=node, consumable_type=code, defaults={'unit': 'sac', 'node_origin': node.code})
    ConsumableStock.objects.filter(pk=s.pk).update(quantity=qty)
    s.refresh_from_db()
    return s


class IsoBase(Base):
    """Base + K3 + donnees de K2 de toute nature (cibles des attaques de K1)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.k3 = Node.objects.create(code='P3', name='Perm K3', sac_value_fc=Dc('200000'))
        cls.u3 = mk('pr3_gerant', 'GERANT', cls.k3)
        cls.cat = ExpenseCategory.objects.get_or_create(code='ISOC', defaults={'label': 'Cat iso C'})[0]
        cls.st1 = _stock(cls.k1)
        cls.st2 = _stock(cls.k2)
        cls.mv2 = ConsumableMovement.objects.create(
            node=cls.k2, stock=cls.st2, movement_type='ENTRY', quantity=Dc('1'),
            unit_price=Dc('1'), supplier='F2', description='x', node_origin='P2')
        cls.disp2 = BreadDisposal.objects.create(
            node=cls.k2, session=cls.s2, bread_price=cls.bp, disposal_type='UNSOLD', quantity=3,
            node_origin='P2')
        cls.cnt2 = ConsumableCount.objects.create(
            node=cls.k2, consumable_type='FAR', count_date=D, system_quantity=Dc('1'),
            physical_quantity=Dc('1'), gap=Dc('0'))
        cls.rep2 = FacturierReport.objects.create(node=cls.k2, team='A', date='2026-11-10', node_origin='P2')
        cls.exp2 = LocalExpense.objects.create(
            node=cls.k2, description='dep K2', amount=Dc('100'), category=cls.cat, date=D, node_origin='P2')
        cls.clo2 = CashClosure.objects.create(node=cls.k2, date=D, node_origin='P2')
        cls.jr2 = JournalEntry.objects.create(node=cls.k2, date=D, imput='CA', entry_amount=Dc('5'))
        cls.sav2 = DailySavings.objects.create(node=cls.k2, date=D)
        cls.vou2 = DisbursementVoucher.objects.create(date=D, motif='v', node_origin='P2')
        cls.inv2 = Invoice.objects.create(node=cls.k2, client=cls.c2, facturier=cls.u2['FACTURIER'],
                                          team='A', node_origin='P2')
        cls.tr23 = BreadTransfer.objects.create(from_node=cls.k2, to_node=cls.k3,
                                                initiated_by=cls.u3, node_origin='P3')
        BreadTransferLine.objects.create(transfer=cls.tr23, bread_price=cls.bp, quantity_sent=4)


# ---------------------------------------------------------------------------
# A. Transferts inter-boulangeries
# ---------------------------------------------------------------------------
class TransferIsolation(IsoBase):
    def lines(self):
        return [{'bread_price': self.bp.pk, 'quantity_sent': 5}]

    def test_tiers_transfer_invisible_and_untouchable(self):
        """Transfert K2->K3 : un gerant K1 (tiers) ne le voit ni ne l'agit."""
        g = cl(self.u['GERANT'])
        url = f'/api/production/transfers/{self.tr23.pk}/'
        self.assertEqual(len([t for t in rows(g.get('/api/production/transfers/'))
                              if str(t['id']) == str(self.tr23.pk)]), 0)
        self.assertEqual(g.get(url).status_code, 404)
        self.assertEqual(g.patch(url, {'notes': 'x'}, format='json').status_code, 404)
        self.assertEqual(g.put(url, {'from_node': self.k2.pk, 'to_node': self.k1.pk}, format='json').status_code, 404)
        self.assertEqual(g.delete(url).status_code, 404)
        for act in ('respond_to_request', 'confirm_reception', 'resolve_dispute'):
            r = g.post(url + act + '/', {'approved': True, 'lines': []}, format='json')
            self.assertIn(r.status_code, (403, 404), (act, r.status_code))
        self.assertTrue(BreadTransfer.objects.filter(pk=self.tr23.pk, from_node=self.k2, to_node=self.k3).exists())

    def test_create_forged_to_node_and_initiator_ignored(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/transfers/', {
            'from_node': self.k2.pk, 'to_node': self.k3.pk, 'initiated_by': self.u3.pk,
            'transfer_status': 'CONFIRMED', 'lines': self.lines()}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        t = BreadTransfer.objects.get(pk=r.data['id'])
        self.assertEqual(t.to_node_id, self.k1.pk)          # demandeur = noeud de l'appelant
        self.assertEqual(t.initiated_by_id, self.u['GERANT'].pk)
        self.assertEqual(t.transfer_status, 'PENDING')
        self.assertEqual(t.node_origin, 'P1')

    def test_cannot_request_in_name_of_other_node(self):
        """to_node = K1 impose ; `from_node` = K1 (soi-meme) refuse."""
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/transfers/', {'from_node': self.k1.pk, 'to_node': self.k2.pk,
                                                   'lines': self.lines()}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def _pending(self):
        t = BreadTransfer.objects.create(from_node=self.k2, to_node=self.k1,
                                         initiated_by=self.u['GERANT'], node_origin='P1')
        BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=2)
        return t, f'/api/production/transfers/{t.pk}/'

    def test_patch_pending_transfer_cannot_rewire_to_node(self):
        """Le demandeur (K1) ne doit pas pouvoir se faire passer pour une autre boulangerie (to_node)."""
        g = cl(self.u['GERANT'])
        t, url = self._pending()
        for method, body in ((g.patch, {'to_node': self.k3.pk}), (g.patch, {'to_node': self.k2.pk}),
                             (g.put, {'from_node': self.k2.pk, 'to_node': self.k3.pk})):
            method(url, body, format='json')
            t.refresh_from_db()
            self.assertEqual(t.to_node_id, self.k1.pk, body)

    def test_patch_pending_transfer_cannot_rewire_from_node(self):
        g = cl(self.u['GERANT'])
        t, url = self._pending()
        for method, body in ((g.patch, {'from_node': self.k3.pk}),
                             (g.put, {'from_node': self.k3.pk, 'to_node': self.k1.pk})):
            method(url, body, format='json')
            t.refresh_from_db()
            self.assertEqual(t.from_node_id, self.k2.pk, body)

    def test_roles_and_side_of_transfer(self):
        t = BreadTransfer.objects.create(from_node=self.k2, to_node=self.k1,
                                         initiated_by=self.u['GERANT'], node_origin='P1')
        BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=2)
        url = f'/api/production/transfers/{t.pk}/'
        # le demandeur (to_node) ne repond pas a sa propre demande
        r = cl(self.u['GERANT']).post(url + 'respond_to_request/', {'approved': True, 'lines': [
            {'bread_price': self.bp.pk, 'quantity_sent': 2}]}, format='json')
        self.assertEqual(r.status_code, 403, r.content)
        # facturier / livreur : aucune ecriture sur un transfert
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.post('/api/production/transfers/', {'from_node': self.k2.pk,
                                                                     'lines': self.lines()}, format='json').status_code, 403)
            self.assertEqual(c.post(url + 'respond_to_request/', {'approved': False}, format='json').status_code, 403)
            self.assertEqual(c.delete(url).status_code, 403)
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'PENDING')

    def test_stock_untouched_by_tiers_actions(self):
        from production.models import BreadStock
        before = list(BreadStock.objects.values_list('pk', 'qty_produced', 'qty_sent', 'qty_received', 'qty_disposed', 'qty_adjusted').order_by('pk'))
        g = cl(self.u['GERANT'])
        for act in ('respond_to_request', 'confirm_reception', 'resolve_dispute'):
            g.post(f'/api/production/transfers/{self.tr23.pk}/{act}/', {'approved': True}, format='json')
        self.assertEqual(before, list(BreadStock.objects.values_list('pk', 'qty_produced', 'qty_sent', 'qty_received', 'qty_disposed', 'qty_adjusted').order_by('pk')))


# ---------------------------------------------------------------------------
# B. Production : stocks, mouvements EXIT, disposals, counts, sessions
# ---------------------------------------------------------------------------
class ProductionIsolation(IsoBase):
    def test_exit_variants_on_foreign_stock(self):
        g = cl(self.u['GERANT'])
        q0 = ConsumableStock.objects.get(pk=self.st2.pk).quantity
        for body in ({'stock': str(self.st2.pk), 'movement_type': 'EXIT', 'quantity': '1',
                      'session': str(self.s1.pk)},
                     {'stock': str(self.st2.pk), 'movement_type': 'EXIT', 'quantity': '1',
                      'node': str(self.k1.pk), 'recorded_by': self.u['GERANT'].pk},
                     {'stock': str(self.st2.pk), 'movement_type': 'ADJUSTMENT', 'quantity': '-5'},
                     {'stock': str(self.st2.pk), 'movement_type': 'ENTRY', 'quantity': '5', 'unit_price': '1'}):
            r = g.post('/api/production/movements/', body, format='json')
            self.assertGreaterEqual(r.status_code, 400, (body, r.status_code))
            self.assertLess(r.status_code, 500, body)
        self.assertEqual(ConsumableStock.objects.get(pk=self.st2.pk).quantity, q0)

    def test_own_exit_then_delete_does_not_touch_other_node(self):
        g = cl(self.u['GERANT'])
        q0 = ConsumableStock.objects.get(pk=self.st2.pk).quantity
        r = g.post('/api/production/movements/', {'stock': str(self.st1.pk), 'movement_type': 'EXIT',
                                                  'quantity': '1'}, format='json')
        self.assertLess(r.status_code, 500)
        if r.status_code == 201:
            g.delete(f"/api/production/movements/{r.data.get('id')}/")
        self.assertEqual(ConsumableStock.objects.get(pk=self.st2.pk).quantity, q0)

    def test_foreign_objects_by_uuid_all_methods(self):
        g = cl(self.u['GERANT'])
        for base, pk in (('stocks', self.st2.pk), ('movements', self.mv2.pk), ('disposals', self.disp2.pk),
                         ('counts', self.cnt2.pk), ('sessions', self.s2.pk)):
            url = f'/api/production/{base}/{pk}/'
            self.assertEqual(g.get(url).status_code, 404, base)
            self.assertEqual(g.patch(url, {'notes': 'x'}, format='json').status_code, 404, base)
            self.assertEqual(g.put(url, {'node': self.k1.pk}, format='json').status_code, 404, base)
            self.assertEqual(g.delete(url).status_code, 404, base)

    def test_stock_post_and_patch_forged_node(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/stocks/', {'node': self.k2.pk, 'consumable_type': 'SEL', 'unit': 'g',
                                               'quantity': '99'}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        self.assertFalse(ConsumableStock.objects.filter(node=self.k2, consumable_type='SEL', quantity=99).exists())
        r = g.patch(f'/api/production/stocks/{self.st1.pk}/', {'node': self.k2.pk, 'quantity': '77'}, format='json')
        s = ConsumableStock.objects.get(pk=self.st1.pk)
        self.assertEqual(s.node_id, self.k1.pk, r.content)

    def test_disposal_forged_node_and_foreign_session(self):
        g = cl(self.u['GERANT'])
        base = {'bread_price': self.bp.pk, 'disposal_type': 'UNSOLD', 'quantity': 1}
        for body in ({**base, 'session': str(self.s2.pk)},
                     {**base, 'session': str(self.s2.pk), 'node': self.k2.pk},
                     {**base, 'session': str(self.s1.pk), 'node': self.k2.pk}):
            r = g.post('/api/production/disposals/', body, format='json')
            self.assertLess(r.status_code, 500, (body, r.content))
        self.assertEqual(BreadDisposal.objects.filter(node=self.k2).count(), 1)  # seulement le disposal de depart
        self.assertEqual(BreadDisposal.objects.filter(session=self.s2).count(), 1)
        # PATCH d'un disposal propre vers la session / le noeud de K2
        r = g.post('/api/production/disposals/', {**base, 'session': str(self.s1.pk)}, format='json')
        if r.status_code == 201:
            url = f"/api/production/disposals/{r.data['id']}/"
            for body in ({'session': str(self.s2.pk)}, {'node': self.k2.pk}):
                g.patch(url, body, format='json')
            d = BreadDisposal.objects.get(pk=r.data['id'])
            self.assertEqual((d.node_id, d.session_id), (self.k1.pk, self.s1.pk))

    def test_count_forged_node(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/counts/', {'node': self.k2.pk, 'consumable_type': 'FAR',
                                               'count_date': D, 'physical_quantity': '3'}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        self.assertEqual(ConsumableCount.objects.filter(node=self.k2).count(), 1)

    def test_session_post_forged_node_and_actions_on_foreign_session(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/sessions/', {'flour_sacks_used': '1', 'team': 'B', 'date': '2026-11-19',
                                                  'node': self.k2.pk}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        from production.models import ProductionSession
        self.assertEqual(ProductionSession.objects.filter(node=self.k2).count(), 1)
        from production.views import ProductionSessionViewSet
        for a in ProductionSessionViewSet.get_extra_actions():
            if not a.detail:
                continue
            for m in (x.lower() for x in a.mapping):
                rr = getattr(g, m)(f'/api/production/sessions/{self.s2.pk}/{a.url_path}/', {}, format='json')
                self.assertEqual(rr.status_code, 404, (a.url_path, m, rr.status_code))

    def test_list_actions_with_node_param_for_gerant(self):
        g = cl(self.u['GERANT'])
        for u in ('/api/production/sessions/reconciliation/', '/api/production/sessions/shift-end-status/',
                  '/api/production/daily-closure/', '/api/production/daily-closure/clients/',
                  '/api/production/opening-confirmation/', '/api/production/bread-stocks/by-date/',
                  '/api/production/team-assignment/'):
            r = g.get(f'{u}?node={self.k2.pk}&date={D}')
            self.assertLess(r.status_code, 500, u)
            self.assertNotIn(f'"node": {self.k2.pk}', r.content.decode(), u)
            self.assertNotIn('Perm K2', r.content.decode(), u)


# ---------------------------------------------------------------------------
# C. Tresorerie
# ---------------------------------------------------------------------------
class TreasuryIsolation(IsoBase):
    def test_foreign_objects_by_uuid(self):
        g = cl(self.u['GERANT'])
        for base, pk in (('expenses', self.exp2.pk), ('reports', self.rep2.pk), ('closures', self.clo2.pk),
                         ('journal', self.jr2.pk), ('savings', self.sav2.pk)):
            url = f'/api/treasury/{base}/{pk}/'
            self.assertEqual(g.get(url).status_code, 404, base)
            self.assertIn(g.patch(url, {'description': 'x'}, format='json').status_code, (404, 405), base)
            self.assertIn(g.delete(url).status_code, (404, 405), base)
        self.assertTrue(LocalExpense.objects.filter(pk=self.exp2.pk).exists())
        self.assertTrue(CashClosure.objects.filter(pk=self.clo2.pk).exists())

    def test_foreign_extra_actions_404_or_403(self):
        from treasury.views import CashClosureViewSet, FacturierReportViewSet
        for vs, base, obj in ((CashClosureViewSet, 'closures', self.clo2), (FacturierReportViewSet, 'reports', self.rep2)):
            for a in vs.get_extra_actions():
                if not a.detail:
                    continue
                for m in (x.lower() for x in a.mapping):
                    for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
                        r = getattr(cl(self.u[role]), m)(f'/api/treasury/{base}/{obj.pk}/{a.url_path}/', {}, format='json')
                        self.assertIn(r.status_code, (403, 404), (base, a.url_path, role, r.status_code))
        self.assertFalse(CashClosure.objects.get(pk=self.clo2.pk).is_validated)

    def test_closure_and_expense_create_forged_node(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/treasury/closures/', {'node': self.k2.pk, 'date': '2026-11-19', 'bills_1000': 1,
                                                'physical_cash_total': '1000'}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        self.assertEqual(CashClosure.objects.filter(node=self.k2).count(), 1)
        r = g.post('/api/treasury/expenses/', {'node': self.k2.pk, 'description': 'forge', 'amount': '5',
                                               'category': self.cat.pk, 'date': '2026-11-19'}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        self.assertEqual(LocalExpense.objects.filter(node=self.k2).count(), 1)
        # PATCH d'une depense propre vers K2
        if r.status_code == 201:
            g.patch(f"/api/treasury/expenses/{r.data['id']}/", {'node': self.k2.pk}, format='json')
            self.assertEqual(LocalExpense.objects.filter(node=self.k2).count(), 1)

    def test_journal_savings_node_param_and_summaries(self):
        g = cl(self.u['GERANT'])
        for u in ('/api/treasury/journal/', '/api/treasury/savings/', '/api/treasury/journal/monthly_summary/',
                  '/api/treasury/savings/monthly_total/', '/api/treasury/journal/reconciliation/',
                  '/api/treasury/expenses/', '/api/treasury/closures/', '/api/treasury/reports/'):
            r = g.get(f'{u}?node={self.k2.pk}&month=11&year=2026&date={D}')
            self.assertLess(r.status_code, 500, u)
            ids = self._ids(r)
            for obj in (self.jr2, self.sav2, self.exp2, self.clo2, self.rep2):
                self.assertNotIn(str(obj.pk), ids, (u, type(obj).__name__))

    @staticmethod
    def _ids(r):
        import json
        out = set()

        def walk(o):
            if isinstance(o, dict):
                if 'id' in o:
                    out.add(str(o['id']))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        try:
            walk(json.loads(r.content))
        except ValueError:
            pass
        return out

    def test_journal_post_forged_node(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/treasury/journal/', {'node': self.k2.pk, 'date': '2026-11-19', 'imput': 'CA',
                                               'entry_amount': '10'}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        r = g.post('/api/treasury/savings/', {'node': self.k2.pk, 'date': '2026-11-19',
                                               'flour_sacks': '1', 'daily_revenue': '10'}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        self.assertEqual(JournalEntry.objects.filter(node=self.k2).count(), 1)
        self.assertEqual(DailySavings.objects.filter(node=self.k2).count(), 1)

    def test_report_generate_forged_node(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/treasury/reports/generate/', {'node': self.k2.pk, 'date': D}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        self.assertEqual(FacturierReport.objects.filter(node=self.k2).count(), 1)

    def test_vouchers_and_cashbook_hq_only(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for u in ('/api/treasury/vouchers/', f'/api/treasury/vouchers/{self.vou2.pk}/',
                      '/api/treasury/cashbook/', '/api/treasury/direction-cash-counts/'):
                self.assertEqual(c.get(u).status_code, 403, (role, u))
            self.assertEqual(c.post('/api/treasury/vouchers/', {'date': D, 'motif': 'x'}, format='json').status_code, 403)
            self.assertEqual(c.delete(f'/api/treasury/vouchers/{self.vou2.pk}/').status_code, 403)
        self.assertTrue(DisbursementVoucher.objects.filter(pk=self.vou2.pk).exists())

    def test_node_less_accounts_treasury_extra(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(mk(f'orph2_{role.lower()}', role, None))
            for u in ('/api/treasury/journal/', '/api/treasury/savings/', '/api/treasury/closures/',
                      '/api/treasury/expenses/', '/api/treasury/reports/'):
                r = c.get(u)
                self.assertIn(r.status_code, (200, 403), (role, u))
                if r.status_code == 200:
                    self.assertEqual(len(rows(r)), 0, (role, u))


# ---------------------------------------------------------------------------
# D. Ventes
# ---------------------------------------------------------------------------
class SalesIsolation(IsoBase):
    def test_foreign_invoice_by_uuid_all_roles_and_actions(self):
        from sales.views import InvoiceViewSet
        base = f'/api/sales/invoices/{self.inv2.pk}/'
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.get(base).status_code, 404, role)
            self.assertIn(c.patch(base, {'commission_exempt': True}, format='json').status_code, (403, 404), role)
            self.assertIn(c.delete(base).status_code, (403, 404, 405), role)
            for a in InvoiceViewSet.get_extra_actions():
                if not a.detail:
                    continue
                for m in (x.lower() for x in a.mapping):
                    r = getattr(c, m)(f'{base}{a.url_path}/', {}, format='json')
                    self.assertIn(r.status_code, (403, 404), (role, a.url_path, m, r.status_code))
        self.assertEqual(Invoice.objects.get(pk=self.inv2.pk).status, Invoice.Status.PENDING)

    def test_create_with_forged_node_is_pinned(self):
        f = cl(self.u['FACTURIER'])
        r = f.post('/api/sales/invoices/', {
            'node': self.k2.pk, 'client': str(self.c1.pk), 'payment_type': 'CASH', 'payment_amount': '0',
            'lines': [{'bread_price': str(self.bp.pk), 'quantity': 2}]}, format='json')
        self.assertIn(r.status_code, (200, 201, 400, 403, 409), r.content)
        self.assertFalse(Invoice.objects.filter(node=self.k2).exclude(pk=self.inv2.pk).exists())

    def test_facturier_may_invoice_foreign_client_but_invoice_stays_on_own_node(self):
        """Exception 5.1 : client K2 facturable depuis K1 ; la facture reste rattachee a K1."""
        f = cl(self.u['FACTURIER'])
        r = f.post('/api/sales/invoices/', {
            'client': str(self.c2.pk), 'payment_type': 'CASH', 'payment_amount': '0',
            'lines': [{'bread_price': str(self.bp.pk), 'quantity': 2}]}, format='json')
        if r.status_code in (200, 201):
            inv = Invoice.objects.get(pk=r.data['id'])
            self.assertEqual(inv.node_id, self.k1.pk)
        else:
            self.assertLess(r.status_code, 500, r.content)

    def test_gerant_creation_blocked_and_sales_lists(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).get(f'/api/sales/invoices/?node={self.k2.pk}')
            self.assertEqual(r.status_code, 200)
            self.assertNotIn(str(self.inv2.pk), r.content.decode(), role)
        for u in ('/api/sales/invoices/bread_summary/', '/api/sales/invoices/bread-summary/'):
            r = cl(self.u['GERANT']).get(f'{u}?node={self.k2.pk}&date={D}')
            self.assertIn(r.status_code, (403, 404))
        r = cl(self.u['LIVREUR']).get(f'/api/sales/invoices/bread_summary/?node={self.k2.pk}&date={D}')
        self.assertIn(r.status_code, (403, 404))

    def test_client_search_allowed_but_no_write_for_facturier_livreur(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            r = c.get('/api/clients/clients/?search=Deux')
            self.assertEqual(r.status_code, 200)
            self.assertIn(str(self.c2.pk), {str(x['id']) for x in rows(r)}, role)
            url = f'/api/clients/clients/{self.c2.pk}/'
            self.assertIn(c.get(url).status_code, (200, 403, 404))
            for m, body in (('patch', {'credit_limit': '9999999'}), ('patch', {'first_name': 'X'}),
                            ('put', {'first_name': 'X'}), ('delete', None)):
                r = getattr(c, m)(url, body, format='json') if body is not None else getattr(c, m)(url)
                self.assertIn(r.status_code, (403, 404, 405), (role, m, r.status_code))
        self.c2.refresh_from_db()
        self.assertEqual(self.c2.credit_limit, Dc('50000'))
        self.assertEqual(self.c2.first_name, 'Bob')

    def test_gerant_k1_cannot_reach_k2_client(self):
        g = cl(self.u['GERANT'])
        url = f'/api/clients/clients/{self.c2.pk}/'
        self.assertEqual(g.get(url).status_code, 404)
        self.assertEqual(g.patch(url, {'credit_limit': '1'}, format='json').status_code, 404)
        r = g.get('/api/clients/clients/?search=Deux')
        self.assertNotIn(str(self.c2.pk), {str(x['id']) for x in rows(r)})


# ---------------------------------------------------------------------------
# E. Comptes du siege non casses
# ---------------------------------------------------------------------------
class HQNotBroken(IsoBase):
    def test_hq_reads_all_nodes(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            c = cl(self.u[role])
            for u in ('/api/production/sessions/', '/api/production/stocks/', '/api/production/movements/',
                      '/api/production/transfers/', '/api/treasury/reports/', '/api/treasury/expenses/',
                      '/api/treasury/closures/', '/api/sales/invoices/'):
                r = c.get(u)
                self.assertEqual(r.status_code, 200, (role, u))
                self.assertGreaterEqual(len(rows(r)), 1, (role, u))
            r = c.get(f'/api/production/movements/flour_history/?node={self.k2.pk}')
            self.assertEqual(r.status_code, 200, role)
            r = c.get(f'/api/production/stocks/{self.st2.pk}/')
            self.assertEqual(r.status_code, 200, role)

    def test_hq_vouchers(self):
        for role in ('ADMIN', 'DIRECTION'):
            self.assertEqual(cl(self.u[role]).get('/api/treasury/vouchers/').status_code, 200, role)

    def test_gerant_k1_flour_history_not_hq(self):
        r = cl(self.u['GERANT']).get(f'/api/production/movements/flour_history/?node={self.k2.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('F2', r.content.decode())


# ---------------------------------------------------------------------------
# F. Balayage automatique : GET de toute route sans parametre avec ?node=<autre>
# ---------------------------------------------------------------------------
class SweepNodeParam(IsoBase):
    LEAK_KEYS = {'node', 'node_id', 'node_origin', 'from_node', 'to_node', 'node_display', 'node_code',
                 'from_node_display', 'to_node_display'}

    def leaks(self, obj, path=''):
        """Retourne les (chemin, valeur) qui designent K2/K3 dans un JSON."""
        bad = {self.k2.pk, str(self.k2.pk), 'P2', self.k2.name, self.k3.pk, str(self.k3.pk), 'P3', self.k3.name}
        out = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in self.LEAK_KEYS and not isinstance(v, (dict, list)) and v in bad:
                    out.append((f'{path}.{k}', v))
                out += self.leaks(v, f'{path}.{k}')
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                out += self.leaks(v, f'{path}[{i}]')
        return out

    def get_routes(self):
        routes = []
        for path, _m, _cb in EndpointEnumerator().get_api_endpoints():
            pass
        for path, method, _cb in EndpointEnumerator().get_api_endpoints():
            if method == 'GET' and '{' not in path and path.startswith('/api/') \
                    and not path.startswith(('/api/docs', '/api/schema')):
                routes.append(path)
        return sorted(set(routes))

    def sweep(self, user, skip=()):
        skip = tuple(skip) + ('/api/chat/users', '/api/clients/clients/deficit_report',
                              '/api/production/sessions/reconciliation')
        import json
        c = cl(user)
        bad = []
        for path in self.get_routes():
            if any(path.startswith(s) for s in skip):
                continue
            for q in (f'?node={self.k2.pk}&date={D}&month=11&year=2026',
                      f'?node={self.k2.code}&date={D}', f'?node_id={self.k2.pk}&from_node={self.k2.pk}'):
                r = c.get(path + q)
                self.assertLess(r.status_code, 500, (path, q, r.status_code))
                if r.status_code == 200 and 'json' in r.get('Content-Type', ''):
                    try:
                        data = json.loads(r.content)
                    except ValueError:
                        continue
                    bad += [(path, q) + x for x in self.leaks(data)]
        return bad

    def test_sweep_gerant(self):
        bad = self.sweep(self.u['GERANT'])
        self.assertEqual(bad[:10], [], 'fuite inter-noeuds (gerant K1)')

    def test_sweep_facturier_livreur(self):
        # exception 5.1 : clients de toutes les boulangeries pour facturier/livreur
        for role in ('FACTURIER', 'LIVREUR'):
            bad = self.sweep(self.u[role], skip=('/api/clients/clients',))
            self.assertEqual(bad[:10], [], f'fuite inter-noeuds ({role} K1)')

    def test_sweep_node_less(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            bad = self.sweep(mk(f'orph3_{role.lower()}', role, None), skip=('/api/clients/clients',))
            self.assertEqual(bad[:10], [], f'fuite compte sans boulangerie ({role})')


# ---------------------------------------------------------------------------
# G. Nouveau defaut trouve par le balayage
# ---------------------------------------------------------------------------
class DeficitReportLeak(IsoBase):
    """BUG-521 : `clients/clients/deficit_report/` (IsAuthenticated) ne filtre pas par noeud."""

    def setUp(self):
        from commissions.models import ClientCommission, CommissionPeriod
        p = CommissionPeriod.objects.create(node=self.k2, month=10, year=2026, node_origin='P2')
        ClientCommission.objects.create(
            period=p, client=self.c2, order_value=Dc('100'), commission_gross=Dc('10'), node_origin='P2')
        Client.objects.filter(pk=self.c2.pk).update(current_debt=Dc('90000'))

    def test_gerant_k1_does_not_see_k2_deficit_clients(self):
        # BUG-521 corrige : facturier/livreur n'ont pas a lire les commissions (403, cf. BUG-253).
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            for q in ('', f'?node={self.k2.pk}'):
                r = cl(self.u[role]).get('/api/clients/clients/deficit_report/' + q)
                if role == 'GERANT':
                    self.assertEqual(r.status_code, 200)
                    self.assertNotIn(self.c2.code, {x['client_code'] for x in r.data}, (role, q))
                else:
                    self.assertEqual(r.status_code, 403, (role, q))

    def test_node_param_non_numeric_is_not_a_500(self):
        r = cl(self.u['GERANT']).get('/api/clients/clients/deficit_report/?node=P2')
        self.assertLess(r.status_code, 500)


class ReconciliationScope(IsoBase):
    """`reconciliation` renvoie en echo le `node` demande ; les DONNEES doivent rester celles du noeud de l'appelant."""

    def _strip(self, d):
        return {k: v for k, v in d.items() if k not in ('node', 'date')}

    def test_gerant_node_param_data_is_own_node(self):
        g = cl(self.u['GERANT'])
        own = g.get(f'/api/production/sessions/reconciliation/?date={D}')
        forged = g.get(f'/api/production/sessions/reconciliation/?node={self.k2.pk}&date={D}')
        self.assertEqual(forged.status_code, 200)
        self.assertEqual(self._strip(own.data), self._strip(forged.data))

    def test_node_less_gets_empty_data(self):
        c = cl(mk('orph4_g', 'GERANT', None))
        r = c.get(f'/api/production/sessions/reconciliation/?node={self.k2.pk}&date={D}')
        self.assertEqual(r.status_code, 200)
        empty = cl(mk('orph4_g2', 'GERANT', None)).get('/api/production/sessions/reconciliation/?date=2000-01-01')
        self.assertEqual(self._strip(r.data), self._strip(empty.data))
