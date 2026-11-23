"""Cycle 6, partie C (testeur-tresorerie, 2026-11-23-c7) : verification independante de
BUG-863 et BUG-677 (ExpenseCategory.scope sur les depenses locales), BUG-860/861 deja
VERIFIES (non rouverts), puis nouveaux angles (categorie inactive, transferts BUG-675 vs
cloture de caisse, billetage, livre). Donnees fictives.
"""
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.models import ExpenseCategory, SystemNotification
from treasury.models import CashbookEntry, CashClosure, LocalExpense
from treasury.tests.test_cycle1_tresorerie_c import Base, cl, rows, today


def notifs():
    return SystemNotification.objects.filter(title__startswith='Écart de Caisse').count()


def last_gap_notif():
    return SystemNotification.objects.filter(title__startswith='Écart de Caisse').latest('created_at')


class V863(Base):
    def _closure(self, cash='10000', bills=None):
        self.report(self.n1, 'A', cash)
        return self.close(self.g1, bills or {'bills_10000': 1}).json()

    def validate(self, c):
        return cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')

    def test_positive_gap_warning(self):
        c = self._closure()
        self.expense(self.g1, '500')
        n = notifs()
        self.assertEqual(self.validate(c).status_code, 200)
        self.assertEqual(notifs(), n + 1)
        self.assertEqual(last_gap_notif().severity, 'WARNING')

    def test_big_gap_danger(self):
        c = self._closure()
        self.expense(self.g1, '10000')
        self.validate(c)
        self.assertEqual(last_gap_notif().severity, 'DANGER')

    def test_exact_no_notification(self):
        c = self._closure()
        n = notifs()
        self.validate(c)
        self.assertEqual(notifs(), n)

    def test_unchanged_nonzero_gap_not_renotified(self):
        c = self._closure(bills={'bills_5000': 1})   # -5000 notifie a la creation
        n = notifs()
        self.assertEqual(n, 1)
        self.validate(c)
        self.assertEqual(notifs(), n)

    def test_gap_returning_to_zero_no_notification(self):
        c = self._closure(bills={'bills_5000': 1, 'bills_1000': 5})   # compte 10000, ecart 0... puis depense
        self.expense(self.g1, '500')
        n = notifs()
        self.validate(c)
        self.assertEqual(CashClosure.objects.get(pk=c['id']).cash_gap, Dc('500'))
        self.assertEqual(notifs(), n + 1)

    def test_node_origin(self):
        c = self._closure()
        self.expense(self.g1, '500')
        self.validate(c)
        self.assertEqual(last_gap_notif().node_origin, 'C1')

    def test_double_validate_no_double_notification(self):
        c = self._closure()
        self.expense(self.g1, '500')
        self.validate(c)
        n = notifs()
        self.assertEqual(self.validate(c).status_code, 400)
        self.assertEqual(notifs(), n)


class V677(Base):
    def setUp(self):
        self.dcat = ExpenseCategory.objects.create(code='DIRX', label='Direction X', scope='DIRECTION')
        self.bcat = ExpenseCategory.objects.create(code='BAKX', label='Boulangerie X', scope='BAKERY')

    def post(self, user, cat, **kw):
        return cl(user).post('/api/treasury/expenses/', {
            'description': 'x', 'amount': 100, 'category': cat.id, 'date': str(today()), **kw}, format='json')

    def test_gerant_refused_direction_category(self):
        r = self.post(self.g1, self.dcat)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(LocalExpense.objects.exists())

    def test_gerant_accepts_bakery_and_both(self):
        self.assertEqual(self.post(self.g1, self.bcat).status_code, 201)
        self.assertEqual(self.post(self.g1, self.cat).status_code, 201)

    def test_patch_to_direction_category_refused(self):
        e = self.post(self.g1, self.bcat).json()
        r = cl(self.g1).patch(f"/api/treasury/expenses/{e['id']}/", {'category': self.dcat.id}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(LocalExpense.objects.get().category_id, self.bcat.id)

    def test_put_to_direction_category_refused(self):
        e = self.post(self.g1, self.bcat).json()
        r = cl(self.g1).put(f"/api/treasury/expenses/{e['id']}/", {
            'description': 'x', 'amount': 100, 'category': self.dcat.id, 'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_facturier_cannot_post_anyway(self):
        self.assertIn(self.post(self.fac, self.dcat).status_code, (400, 403))
        self.assertFalse(LocalExpense.objects.exists())

    def test_hq_can_use_direction_category(self):
        r = self.post(self.compt, self.dcat, node=self.n1.id)
        self.assertEqual(r.status_code, 201, r.content)

    def test_category_list_hidden_for_gerant_visible_for_hq(self):
        g = {c['code'] for c in rows(cl(self.g1).get('/api/core/expense-categories/'))}
        h = {c['code'] for c in rows(cl(self.compt).get('/api/core/expense-categories/'))}
        self.assertNotIn('DIRX', g)
        self.assertIn('BAKX', g)
        self.assertIn('DIRX', h)

    def test_gerant_cannot_change_scope(self):
        r = cl(self.g1).patch(f'/api/core/expense-categories/{self.dcat.id}/', {'scope': 'BOTH'}, format='json')
        self.assertIn(r.status_code, (403, 404))
        self.dcat.refresh_from_db()
        self.assertEqual(self.dcat.scope, 'DIRECTION')

    def test_invalid_scope_rejected(self):
        r = cl(self.compt).patch(f'/api/core/expense-categories/{self.bcat.id}/', {'scope': 'XXX'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_gerant_direct_retrieve_direction_category_404(self):
        r = cl(self.g1).get(f'/api/core/expense-categories/{self.dcat.id}/')
        self.assertEqual(r.status_code, 404)

    def test_existing_expense_survives_scope_change_and_other_patch(self):
        e = self.post(self.g1, self.bcat).json()
        cl(self.compt).patch(f'/api/core/expense-categories/{self.bcat.id}/', {'scope': 'DIRECTION'}, format='json')
        r = cl(self.g1).patch(f"/api/treasury/expenses/{e['id']}/", {'description': 'maj'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        c = self.close(self.g1).json()
        self.assertEqual(Dc(c['total_expenses']), Dc('100'))

    def test_BUG_871_inactive_category_refused_for_new_expense(self):
        ExpenseCategory.objects.filter(pk=self.bcat.pk).update(is_active=False)
        r = self.post(self.g1, self.bcat)
        self.assertEqual(r.status_code, 400, r.content)

    def test_scope_filter_both_included(self):
        d = {c['code'] for c in rows(cl(self.compt).get('/api/core/expense-categories/?scope=BAKERY'))}
        self.assertIn('BAKX', d)
        self.assertIn('EAUC', d)
        self.assertNotIn('DIRX', d)


class Interactions(Base):
    def _transfer(self, src, dst, sent, recv, **kw):
        from production.models import BreadTransfer, BreadTransferLine
        from core.testing import make_bread_price
        bread = make_bread_price('MOYEN', f'Pain 300 {src.code}{dst.code}{sent}{recv}', 300)
        t = BreadTransfer.objects.create(from_node=src, to_node=dst, node_origin=src.code, **kw)
        BreadTransferLine.objects.create(transfer=t, bread_price=bread, quantity_sent=sent, quantity_received=recv)
        return t

    def test_matching_transfer_does_not_change_cash_closure(self):
        self._transfer(self.n2, self.n1, 50, 50)
        self.report(self.n1, 'A', '10000')
        r = self.close(self.g1, {'bills_10000': 1})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((Dc(r.json()['net_cash']), Dc(r.json()['cash_gap'])), (Dc('10000'), Dc('0')))

    def test_outgoing_gap_blocks_receiver_only(self):
        self._transfer(self.n1, self.n2, 50, 40)
        self.assertEqual(self.close(self.g1).status_code, 201)
        self.assertEqual(self.close(self.g2).status_code, 400)

    def test_cancelled_transfer_gap_ignored(self):
        from production.models import BreadTransfer
        self._transfer(self.n2, self.n1, 50, 10, transfer_status=BreadTransfer.TransferStatus.CANCELLED)
        self.assertEqual(self.close(self.g1).status_code, 201)

    def test_gap_after_confirmation_blocks_versement(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        self._transfer(self.n2, self.n1, 50, 49)
        r = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(CashbookEntry.objects.exists())

    def test_chain_and_balance_two_nodes_with_bakery_category(self):
        cat = ExpenseCategory.objects.create(code='BKY', label='B', scope='BAKERY')
        self.report(self.n1, 'A', '10000')
        self.report(self.n2, 'A', '7000')
        cl(self.g1).post('/api/treasury/expenses/', {'description': 'x', 'amount': 1500, 'category': cat.id,
                                                      'date': str(today())}, format='json')
        c1 = self.close(self.g1, {'bills_5000': 1, 'bills_1000': 3, 'bills_500': 1}).json()
        c2 = self.close(self.g2, {'bills_5000': 1, 'bills_1000': 2}).json()
        self.versement(c1['id'])
        self.versement(c2['id'])
        bal = [e.running_balance for e in CashbookEntry.chain_queryset()]
        self.assertEqual(bal, [Dc('8500'), Dc('15500')])
        self.assertTrue(self.chain_ok())
