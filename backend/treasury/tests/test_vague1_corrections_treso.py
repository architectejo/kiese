"""
Non-régression des corrections BUG-200 à BUG-207 (dev-backend, 2026-11-12).
Complète les sondes de `test_vague1_db_testeur_tresorerie.py`. Données fictives.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import ExpenseCategory
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice
from treasury.models import CashClosure, CashbookEntry, DailySavings, FacturierReport, JournalEntry
from treasury.tests.test_vague1_db_testeur_tresorerie import _api, _deliver


class Bug200HqCanStillConfirmTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_c200')
        self.comptable = make_user('COMPTABLE', username='c_c200')
        self.closure = CashClosure.objects.create(
            node=self.node, gerant=self.gerant, date=date(2026, 11, 9),
            total_entries=Decimal('1000'), total_expenses=Decimal('0'), net_cash=Decimal('1000'))

    def test_comptable_validates_then_pushes_gerant_cannot_reject_or_push(self):
        c = _api(self.comptable)
        self.assertEqual(c.post(f'/api/treasury/closures/{self.closure.id}/validate/', {}, format='json').status_code, 200)
        self.assertEqual(_api(self.gerant).post(
            f'/api/treasury/closures/{self.closure.id}/push_to_cashbook/', {}, format='json').status_code, 403)
        self.assertEqual(c.post(f'/api/treasury/closures/{self.closure.id}/push_to_cashbook/', {}, format='json').status_code, 201)

    def test_gerant_still_creates_and_deletes_unvalidated_closure(self):
        r = _api(self.gerant).delete(f'/api/treasury/closures/{self.closure.id}/')
        self.assertEqual(r.status_code, 204)


class Bug201BillsBoundsTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_c201')

    def test_oversized_bills_message_in_french(self):
        r = _api(self.gerant).post('/api/treasury/closures/', {'date': str(date.today()), 'bills_50': 100001}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('bills_50', r.json())
        self.assertEqual(CashClosure.objects.count(), 0)

    def test_negative_bills_rejected(self):
        r = _api(self.gerant).post('/api/treasury/closures/', {'date': str(date.today()), 'bills_50': -1}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_max_bills_accepted(self):
        r = _api(self.gerant).post('/api/treasury/closures/', {'date': str(date.today()), 'bills_20000': 100000}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_corrupted_closure_does_not_break_list_and_can_be_deleted(self):
        good = CashClosure.objects.create(node=self.node, gerant=self.gerant, date=date(2026, 11, 8))
        bad = CashClosure.objects.create(node=self.node, gerant=self.gerant, date=date(2026, 11, 10))
        with connection.cursor() as cur:
            cur.execute("UPDATE treasury_cashclosure SET physical_cash_total = 999999999990000, cash_gap = 999999999990000 WHERE id = %s",
                        [bad.id.hex if hasattr(bad.id, 'hex') else str(bad.id)])
        api = _api(self.gerant)
        r = api.get('/api/treasury/closures/')
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        ids = [x['id'] for x in body.get('results', body)]
        self.assertIn(str(good.id), ids)
        self.assertNotIn(str(bad.id), ids)
        # journal CA et suggested_ca du jour corrompu : pas de 500
        r = api.get('/api/treasury/journal/suggested_ca/', {'date': '2026-11-10', 'node': self.node.id})
        self.assertEqual(r.status_code, 200, r.content)
        r = api.post('/api/treasury/journal/', {'date': '2026-11-10', 'imput': 'CA', 'label': 'x', 'entry_amount': '10'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(api.delete(f'/api/treasury/closures/{bad.id}/').status_code, 204)
        self.assertFalse(CashClosure.objects.filter(pk=bad.pk).exists())


class Bug202JournalTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_c202')
        self.fac = make_user('FACTURIER', node=self.node, team='A', username='f_c202')

    def test_facturier_cannot_create_journal_entry(self):
        r = _api(self.fac).post('/api/treasury/journal/', {'date': '2026-11-08', 'imput': 'CA', 'label': 'x', 'entry_amount': '5'}, format='json')
        self.assertEqual(r.status_code, 403, r.content)

    def test_gerant_cannot_patch_or_delete_either(self):
        api = _api(self.gerant)
        e = api.post('/api/treasury/journal/', {'date': '2026-11-08', 'imput': 'LIVRAISON', 'label': 'x', 'entry_amount': '10'}, format='json').json()
        self.assertEqual(api.patch(f"/api/treasury/journal/{e['id']}/", {'entry_amount': '99'}, format='json').status_code, 405)
        self.assertEqual(api.delete(f"/api/treasury/journal/{e['id']}/").status_code, 405)
        self.assertEqual(JournalEntry.objects.get(pk=e['id']).entry_amount, Decimal('10.00'))

    def test_negative_entry_amount_rejected(self):
        r = _api(self.gerant).post('/api/treasury/journal/', {'date': '2026-11-08', 'imput': 'CA', 'label': 'n', 'entry_amount': '-1'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class Bug203ReportTests(TestCase):
    def test_totals_ignored_on_manual_create_and_validated_frozen_and_not_deletable(self):
        node = make_node(code='K3', name='ATHENEE')
        gerant = make_user('GERANT', node=node, username='g_c203')
        fa = make_user('FACTURIER', node=node, team='A', username='f_c203')
        _deliver(node, fa, 'A', make_client(node), make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300),
                 5, Invoice.PaymentType.CASH)
        api = _api(gerant)
        api.post('/api/treasury/reports/generate/', {}, format='json')
        rep = FacturierReport.objects.get(node=node, team='A')
        # is_validated ne peut pas être forcé par PATCH
        api.patch(f'/api/treasury/reports/{rep.id}/', {'is_validated': True, 'total_credit_sales': '1'}, format='json')
        rep.refresh_from_db()
        self.assertFalse(rep.is_validated)
        self.assertEqual(rep.total_credit_sales, Decimal('0.00'))
        api.post(f'/api/treasury/reports/{rep.id}/validate/')
        self.assertEqual(api.delete(f'/api/treasury/reports/{rep.id}/').status_code, 403)
        self.assertTrue(FacturierReport.objects.filter(pk=rep.pk).exists())


class Bug204CorrectionPieceTests(TestCase):
    def test_distinct_short_numbers_even_for_long_node_code(self):
        from treasury.services import record_backdated_correction
        node = make_node(code='K3', name='ATHENEE')
        gerant = make_user('GERANT', node=node, username='g_c204')
        fac = make_user('FACTURIER', node=node, team='A', username='f_c204')
        closure = CashClosure.objects.create(node=node, gerant=gerant, date=date(2026, 11, 9), is_validated=True,
                                             total_entries=Decimal('100'), net_cash=Decimal('100'))
        inv = _deliver(node, fac, 'A', make_client(node), make_bread_price(category='MINI', label='Pain 200 FC', unit_price=200),
                       1, Invoice.PaymentType.CASH)
        nums = [record_backdated_correction(closure, Decimal(d), inv, acting_user=gerant).piece_number for d in (50, 20, -5)]
        self.assertEqual(len(set(nums)), 3, nums)
        self.assertTrue(all(len(n) <= 30 for n in nums), nums)
        self.assertEqual(nums[0], 'CORR-K3-20261109-01')


class Bug205ExpenseTests(TestCase):
    def test_positive_expense_accepted(self):
        node = make_node(code='K3', name='ATHENEE')
        gerant = make_user('GERANT', node=node, username='g_c205')
        cat = ExpenseCategory.objects.create(code='ZZ_C205', label='ZZ')
        r = _api(gerant).post('/api/treasury/expenses/', {'description': 'ok', 'amount': '500', 'category': cat.id,
                                                          'date': '2026-11-09'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)


class Bug206SavingsTests(TestCase):
    def setUp(self):
        self.k3 = make_node(code='K3', name='ATHENEE')
        self.k1 = make_node(code='K1', name='TABORA')
        self.g3 = make_user('GERANT', node=self.k3, username='g_c206')
        self.hq = make_user('COMPTABLE', username='c_c206')
        self.other = DailySavings.objects.create(
            node=self.k1, date=date(2026, 11, 8), flour_sacks=Decimal('1'),
            daily_revenue=Decimal('1000'), savings_rate=Decimal('0.1'), savings_amount=Decimal('100'))

    def test_monthly_total_ignores_node_param_for_non_hq(self):
        r = _api(self.g3).get('/api/treasury/savings/monthly_total/', {'node': self.k1.id, 'month': 11, 'year': 2026})
        self.assertEqual(Decimal(r.json()['total_savings']), Decimal('0'))

    def test_hq_can_still_filter_by_node(self):
        r = _api(self.hq).get('/api/treasury/savings/', {'node': self.k1.id})
        body = r.json()
        self.assertEqual([x['id'] for x in body.get('results', body)], [self.other.id])

    def test_gerant_creates_valid_savings(self):
        r = _api(self.g3).post('/api/treasury/savings/', {'date': '2026-11-07', 'flour_sacks': 1,
                                                          'daily_revenue': '1000', 'savings_rate': '0.1'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Decimal(r.json()['savings_amount']), Decimal('100.00'))


class Bug207PeriodSummaryTests(TestCase):
    def test_both_totals_are_strings(self):
        from treasury.views import append_cashbook_entry
        node = make_node(code='K3', name='ATHENEE')
        append_cashbook_entry(node=node, date=date(2026, 11, 9), piece_number='VC-K3-20261109', imputation='7000',
                              label='x', entry_amount=Decimal('18400.50'), exit_amount=Decimal('0'), node_origin='K3')
        r = _api(make_user('COMPTABLE', username='c_c207')).get(
            '/api/treasury/cashbook/period_summary/', {'date_from': '2026-11-01', 'date_to': '2026-11-30'})
        row = r.json()[0]
        self.assertEqual(row['total_entries'], '18400.50')
        self.assertEqual(row['total_exits'], '0.00')
