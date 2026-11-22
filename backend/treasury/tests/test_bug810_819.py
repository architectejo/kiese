"""Non-regression BUG-810 a BUG-819 (dev-backend, Dev C, 2026-11-22). Donnees fictives.

Les tests attaquants (@expectedFailure) restent dans test_cycle1_tresorerie_c.py ; ceux-ci
verifient la correction et ses bords (sans marque).
"""
from datetime import timedelta
from decimal import Decimal as Dc

from core.testing import make_user
from treasury.models import CashbookEntry, DailySavings, DisbursementVoucher, FacturierReport, JournalEntry
from treasury.tests.test_cycle1_tresorerie_c import BILLS, Base, cl, rows, today


class Bug810(Base):
    def test_non_numeric_or_unknown_node_in_body_is_400_with_detail(self):
        self.report(self.n1, 'A', '1000')
        for url, body in (('/api/treasury/closures/', {'date': str(today())}),
                          ('/api/treasury/expenses/', {'description': 'x', 'amount': '10',
                                                       'category': self.cat.id, 'date': str(today())}),
                          ('/api/treasury/reports/generate/', {})):
            for bad in ('abc', '999999', 'ZZ9'):
                with self.subTest(url=url, bad=bad):
                    r = cl(self.dirn).post(url, {**body, 'node': bad}, format='json')
                    self.assertEqual(r.status_code, 400, (url, r.status_code))
                    self.assertIn('detail', r.json())

    def test_node_code_in_body_is_accepted_for_hq(self):
        r = cl(self.dirn).post('/api/treasury/expenses/', {
            'description': 'x', 'amount': '10', 'category': self.cat.id,
            'date': str(today()), 'node': 'C2'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['node'], self.n2.id)


class Bug811(Base):
    def test_closure_without_any_denomination_is_400_and_nothing_saved(self):
        self.report(self.n1, 'A', '10000')
        r = cl(self.g1).post('/api/treasury/closures/', {'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('billetage', r.json()['detail'].lower())
        self.assertFalse(self.n1.cashclosure_set.exists() if hasattr(self.n1, 'cashclosure_set') else False)
        # un seul champ de billetage (meme a 0) suffit : la ventilation est fournie
        r2 = cl(self.g1).post('/api/treasury/closures/', {'date': str(today()), 'bills_50': 0}, format='json')
        self.assertEqual(r2.status_code, 201, r2.content)

    def test_patch_without_bills_stays_possible_after_rejection(self):
        """Le point (b) (modification du billetage sans trace) est A CLARIFIER : non modifie."""
        c = self.close(self.g1, {'bills_5000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'x'}, format='json')
        r = cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/", {'notes': 'ok'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)


class Bug812(Base):
    def test_report_requires_team_A_or_B(self):
        for team in ('', 'C'):
            g = make_user('GERANT', self.n2, team=team)
            r = cl(g).post('/api/treasury/reports/', {'date': str(today())}, format='json')
            self.assertEqual(r.status_code, 400, (team, r.content))
        self.assertFalse(FacturierReport.objects.exclude(team__in=('A', 'B')).exists())
        g = make_user('GERANT', self.n2, team='B')
        self.assertEqual(cl(g).post('/api/treasury/reports/', {'date': str(today())}, format='json').status_code, 201)


class Bug813(Base):
    def test_future_expense_refused_on_create_and_update(self):
        self.assertEqual(self.expense(self.g1, '10', date=today() + timedelta(days=1)).status_code, 400)
        e = self.expense(self.g1, '10').json()
        r = cl(self.g1).patch(f"/api/treasury/expenses/{e['id']}/",
                              {'date': str(today() + timedelta(days=3))}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_confirmed_closure_day_freezes_expenses(self):
        self.report(self.n1, 'A', '10000')
        e = self.expense(self.g1, '1000').json()
        c = self.close(self.g1, {'bills_5000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        self.assertEqual(self.expense(self.g1, '500').status_code, 400)
        u = f"/api/treasury/expenses/{e['id']}/"
        self.assertEqual(cl(self.g1).patch(u, {'amount': '1'}, format='json').status_code, 400)
        self.assertEqual(cl(self.g1).delete(u).status_code, 400)
        self.assertEqual(self.n1.localexpense_set.count() if hasattr(self.n1, 'localexpense_set') else 1, 1)
        # l'autre boulangerie n'est pas gelee
        self.assertEqual(self.expense(self.g2, '500').status_code, 201)

    def test_unconfirmed_closure_day_still_allows_expenses(self):
        self.close(self.g1, {'bills_5000': 1})
        e = self.expense(self.g1, '500')
        self.assertEqual(e.status_code, 201)
        self.assertEqual(cl(self.g1).delete(f"/api/treasury/expenses/{e.json()['id']}/").status_code, 204)


class Bug814_815(Base):
    def sav(self, user, **kw):
        body = {'date': str(today()), 'daily_revenue': '100000', 'flour_sacks': '2'}
        body.update(kw)
        return cl(user).post('/api/treasury/savings/', body, format='json')

    def test_rate_zero_honoured_and_missing_rate_uses_config(self):
        r = self.sav(self.g1, savings_rate='0')
        self.assertEqual(Dc(r.json()['savings_amount']), Dc('0'))
        r2 = self.sav(self.g2)  # taux absent -> configuration
        self.assertGreater(Dc(r2.json()['savings_amount']), 0)

    def test_patch_date_to_existing_day_is_400_but_same_day_ok(self):
        d1 = str(today() - timedelta(days=1))
        self.sav(self.g1, date=d1)
        r2 = self.sav(self.g1).json()
        u = f"/api/treasury/savings/{r2['id']}/"
        r = cl(self.g1).patch(u, {'date': d1}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(DailySavings.objects.filter(node=self.n1).count(), 2)
        self.assertEqual(cl(self.g1).patch(u, {'date': str(today())}, format='json').status_code, 200)
        self.assertEqual(cl(self.g1).patch(u, {'daily_revenue': '1000'}, format='json').status_code, 200)


class Bug816(Base):
    def test_voucher_is_append_only_and_chain_stays_valid(self):
        append = __import__('treasury.views', fromlist=['append_cashbook_entry']).append_cashbook_entry
        append(node=self.n1, date=today(), piece_number='VC-C1-1', imputation='7000', label='seed',
               entry_amount=Dc('100000'), node_origin='C1')
        b = {k: 0 for k in BILLS}; b['bills_20000'] = 1
        v = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'A', **b}, format='json').json()
        u = f"/api/treasury/vouchers/{v['id']}/"
        for who in (self.dirn, self.adm, self.compt):
            for m in ('put', 'patch', 'delete'):
                self.assertEqual(getattr(cl(who), m)(u, {'bills_20000': 4}, format='json').status_code, 405, (who.role, m))
        # les roles non siege restent refuses (403) avant la methode
        self.assertEqual(cl(self.g1).delete(u).status_code, 403)
        self.assertTrue(DisbursementVoucher.objects.filter(pk=v['id']).exists())
        self.assertEqual(DisbursementVoucher.objects.get(pk=v['id']).physical_cash_total, Dc('20000'))
        self.assertTrue(self.chain_ok())
        self.assertEqual(CashbookEntry.objects.filter(source_bordereau_id=v['id']).count(), 1)
        self.assertEqual(cl(self.dirn).get(u).status_code, 200)


class Bug817(Base):
    def post(self, **kw):
        body = {'date': str(today()), 'imput': 'CA', 'label': 'x', 'entry_amount': '0', 'exit_amount': '0'}
        body.update(kw)
        return cl(self.g1).post('/api/treasury/journal/', body, format='json')

    def balances(self):
        return [(str(e.date), e.running_balance, e.month_carried)
                for e in JournalEntry.objects.filter(node=self.n1).order_by('date', 'created_at', 'pk')]

    def test_future_date_refused(self):
        r = self.post(entry_amount='5', date=str(today() + timedelta(days=40)))
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(JournalEntry.objects.exists())

    def test_backdated_entry_is_recomputed_and_following_entries_follow(self):
        self.post(entry_amount='1000', date='2026-03-10')
        r = self.post(entry_amount='100', date='2026-03-05')
        self.assertEqual(Dc(r.json()['running_balance']), Dc('100'))
        self.assertEqual(self.balances(), [('2026-03-05', Dc('100'), Dc('0')), ('2026-03-10', Dc('1100'), Dc('0'))])
        # une sortie le 7 : le 10 est decale, le solde final reste = somme
        self.post(exit_amount='30', imput='APPRO', date='2026-03-07')
        self.assertEqual([b for _, b, _ in self.balances()], [Dc('100'), Dc('70'), Dc('1070')])

    def test_backdated_across_months_updates_carry_over(self):
        self.post(entry_amount='500', date='2026-04-02')
        self.post(entry_amount='200', date='2026-03-20')
        self.assertEqual(self.balances(), [('2026-03-20', Dc('200'), Dc('0')), ('2026-04-02', Dc('700'), Dc('200'))])
        self.post(entry_amount='50', date='2026-04-01')
        self.assertEqual(self.balances(), [('2026-03-20', Dc('200'), Dc('0')),
                                           ('2026-04-01', Dc('250'), Dc('200')),
                                           ('2026-04-02', Dc('750'), Dc('200'))])

    def test_hash_chain_not_touched_by_journal(self):
        self.post(entry_amount='1', date='2026-03-10')
        self.post(entry_amount='1', date='2026-03-05')
        self.assertTrue(self.chain_ok())


class Bug818(Base):
    def test_bad_period_params_are_400_with_detail(self):
        for u in ('/api/treasury/cashbook/', '/api/treasury/cashbook/period_summary/', '/api/treasury/vouchers/final_report/'):
            for q in ({'date_from': 'garbage'}, {'date_to': '99999-01-01'}, {'date_from': '2026-02-30'}):
                with self.subTest(u=u, q=q):
                    r = cl(self.dirn).get(u, q)
                    self.assertEqual(r.status_code, 400, (u, q, r.status_code))
                    self.assertIn('detail', r.json())
        r = cl(self.dirn).get('/api/treasury/journal/suggested_ca/', {'node': 'abc', 'date': str(today())})
        self.assertEqual(r.status_code, 400)

    def test_valid_periods_still_work(self):
        d = str(today())
        for u in ('/api/treasury/cashbook/', '/api/treasury/cashbook/period_summary/', '/api/treasury/vouchers/final_report/'):
            self.assertEqual(cl(self.dirn).get(u, {'date_from': d, 'date_to': d}).status_code, 200)
        r = cl(self.dirn).get('/api/treasury/journal/suggested_ca/', {'node': 'C1', 'date': d})
        self.assertEqual(r.status_code, 200)


class Bug819(Base):
    def test_huge_expenses_make_closure_400_without_residue(self):
        self.expense(self.g1, '999999999999.99')
        self.expense(self.g1, '999999999999.99')
        r = self.close(self.g1)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(self.n1.cashclosure_set.exists() if hasattr(self.n1, 'cashclosure_set') else False)
        from treasury.models import CashClosure
        self.assertFalse(CashClosure.objects.filter(node=self.n1).exists())
        self.assertEqual(self.close(self.g2).status_code, 201)

    def test_huge_expenses_make_resubmission_400_and_keep_closure(self):
        c = self.close(self.g1, {'bills_50': 1}).json()
        self.expense(self.g1, '999999999999.99'); self.expense(self.g1, '999999999999.99')
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'x'}, format='json')
        r = cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/", {'bills_50': 2}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        got = [x['id'] for x in rows(cl(self.g1).get('/api/treasury/closures/'))]
        self.assertIn(c['id'], got)
