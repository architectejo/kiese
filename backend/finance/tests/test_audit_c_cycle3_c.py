"""
Audit comptable, cycle test 3, partie C (finance) - 2026-11-22. Données fictives uniquement.
Vérification de BUG-820/822(DOC 1)/823 sous de nouveaux angles, scénario du cycle 1 après les
corrections de trésorerie (BUG-810 à 839), nouveaux angles (BUG-850 à 859).
Les défauts ouverts sont portés par des `@expectedFailure` à retirer à la correction.
"""
import csv
import io
import json
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.testing import make_client, make_bread_price
from finance.models import FinancialYear
from finance.tests.test_audit_c_cycle1_c import _Base, _api, _bills, _dates
from finance.tests.test_audit_c_cycle2_c import Cycle2Base
from finance.views import _balance_sheet_for_year, _income_statement_for_year
from sales.models import Invoice
from treasury.models import CashbookEntry, CashClosure


class Verif820Attacks(Cycle2Base):
    """BUG-820 : la somme des `debt_delta` doit suivre `current_debt` pour TOUS les états de facture."""

    def _pending(self, qty, pay, day, ptype='CREDIT'):
        r = _api(self.f1).post('/api/sales/invoices/', {
            'client': str(self.cl.pk), 'payment_type': ptype, 'payment_amount': str(pay),
            'invoice_date': str(day), 'lines': [{'bread_price': self.bp_grand.pk, 'quantity': qty}]},
            format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def test_not_served_invoice_with_kept_payment_matches_current_debt(self):
        """8xGRAND (4 000) + versement 1 000 puis « Non servi » : BP réelle -1 000 (versement
        conservé, BUG-318) ; le bilan reconstitué d'un exercice clos doit l'être aussi."""
        day = date(self.year - 1, 12, 20)
        inv = self._pending(8, 1000, day)
        r = _api(self.f1).post(f'/api/sales/invoices/{inv}/mark-not-served/', {'reason': 'test'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('-1000.00'))
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('-1000.00'))

    def test_expired_pending_invoice_matches_current_debt(self):
        day = date(self.year - 1, 12, 20)
        inv = self._pending(8, 1000, day)
        Invoice.objects.filter(pk=inv).update(created_at=timezone.now() - timedelta(hours=30))
        from sales.services import expire_pending_invoices
        self.assertEqual(expire_pending_invoices(), 1)
        self.cl.refresh_from_db()
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], self.cl.current_debt)

    def test_partial_delivery_matches_current_debt(self):
        day = date(self.year - 1, 12, 20)
        inv = self._pending(8, 0, day)
        line = Invoice.objects.get(pk=inv).lines.first()
        r = _api(self.f1).post(f'/api/sales/invoices/{inv}/deliver/',
                               {'lines': [{'id': line.pk, 'quantity': 3}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('1500.00'))
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('1500.00'))

    def test_ns_code_credit_and_rg_and_soldee_follow_current_debt(self):
        day = date(self.year - 1, 11, 20)
        r = _api(self.f1).post('/api/sales/invoices/', {
            'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': '500', 'special_code': 'NS',
            'invoice_date': str(day), 'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 4}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', day, code='RG')
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', day, soldee=True)
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', day)
        self.cl.refresh_from_db()
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], self.cl.current_debt)

    def test_adjustment_follows_current_debt(self):
        day = date(self.year - 1, 11, 20)
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 1000, 'CREDIT', day)   # +4000
        r = _api(self.g1).post(f'/api/sales/invoices/{inv}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': '0', 'invoice_date': str(day),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 3}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('2500.00'))
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('2500.00'))

    def test_invoice_dated_after_year_end_is_excluded(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', date(self.year - 1, 12, 31))
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('1000.00'))

    def test_two_closed_years_are_isolated(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', date(self.year - 2, 6, 1))
        self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 0, 'CREDIT', date(self.year - 1, 6, 1))
        self.assertEqual(_balance_sheet_for_year(self.year - 2)['receivables'], D('1000.00'))
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('3000.00'))


class Verif822823Attacks(Cycle2Base):
    def test_other_price_negative_adjustment(self):
        bp250 = make_bread_price('MICRO_250', 'Pain 250 FC', 250)
        inv = self.sale(self.f1, self.cl, [(bp250, 6)], 1500, 'CASH', self.d1)
        self.adjust(inv, -1, 2, bp=bp250)
        row = self.doc1(self.d1)[0]
        self.assertEqual(row['qty_other'], 4)
        self.assertEqual(D(row['invoice_total']), D('1000'))

    def test_positive_adjustment_of_regularisation_in_doc1(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 5)], 0, 'CREDIT', self.d1, code='RG')
        self.adjust(inv, 1, 2)
        self.assertEqual(self.doc1(self.d1)[0]['qty_500'], 7)

    def test_doc1_export_matches_report_with_negative_adjustment(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 2)
        r = _api(self.hq).get('/api/finance/years/doc1_export/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year})
        body = b''.join(r.streaming_content).decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(body)))
        self.assertEqual(rows[1][4], '8')       # QTÉ 500
        self.assertEqual(rows[1][6], '0')       # QTÉ AUTRES


class Verif3CsvAndEdges(Cycle2Base):
    def test_doc1_csv_cell_starting_with_equals_is_neutralised(self):
        """Un nom de client commençant par = + - @ est interprété comme formule par Excel."""
        evil = make_client(self.k1, credit_limit=D('900000'), last_name='=HYPERLINK("http://x","a")')
        self.sale(self.f1, evil, [(self.bp_grand, 1)], 500, 'CASH', self.d1)
        r = _api(self.hq).get('/api/finance/years/doc1_export/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year})
        body = b''.join(r.streaming_content).decode('utf-8-sig')
        cells = [c for row in csv.reader(io.StringIO(body)) for c in row]
        self.assertFalse([c for c in cells if c.startswith('=')], cells)

    def test_doc1_with_client_divers_invoice(self):
        """Vente à CLIENT DIVERS (sans client) : DOC 1 ne doit pas planter."""
        r = _api(self.f1).post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': '500', 'invoice_date': str(self.d1),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        d = _api(self.f1).post(f"/api/sales/invoices/{r.data['id']}/deliver/", {}, format='json')
        self.assertEqual(d.status_code, 200, d.data)
        rep = _api(self.hq).get('/api/finance/years/doc1_report/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year})
        self.assertEqual(rep.status_code, 200, getattr(rep, 'data', rep.content))
        exp = _api(self.hq).get('/api/finance/years/doc1_export/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year})
        self.assertEqual(exp.status_code, 200)
        b''.join(exp.streaming_content)

    def test_financial_year_edge_values_do_not_crash(self):
        # BUG-852 : 0 et 1 sont desormais refuses par l'API (validate_year 2000-2100) ; on teste les bornes valides
        for y in (2000, 2100):
            fy = FinancialYear.objects.create(year=y)
            for path in ('income_statement', 'cashflow', 'balance_sheet', 'comparative'):
                r = _api(self.direction).get(f'/api/finance/years/{fy.pk}/{path}/')
                self.assertEqual(r.status_code, 200, (y, path))

    def test_financial_year_create_rejects_absurd_year(self):
        r = _api(self.direction).post('/api/finance/years/', {'year': 0}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = _api(self.direction).post('/api/finance/years/', {'year': 65000}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class Verif3Doc1Bp(Cycle2Base):
    def test_doc1_bp_end_of_month_with_backdated_invoice_equals_real_bp(self):
        """Facture du 20 saisie, puis facture du 5 saisie ensuite (antidatée) : la BP réelle fin de mois
        est 1 500 (chaîne par saisie) ; DOC 1 retient `debt_after` de la facture la plus récente par date (1 000)."""
        d20, d5 = self.d1.replace(day=20), self.d1.replace(day=5)
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', d20)
        self.sale(self.f1, self.cl, [(self.bp_grand, 1)], 0, 'CREDIT', d5)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('1500.00'))
        self.assertEqual(D(self.doc1(self.d1)[0]['debt_after']), D('1500.00'))

    def test_doc1_bp_two_invoices_same_day_takes_last_entered(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
        self.sale(self.f1, self.cl, [(self.bp_grand, 1)], 0, 'CREDIT', self.d1)
        self.assertEqual(D(self.doc1(self.d1)[0]['debt_after']), D('1500.00'))


class Verif3Permissions(Cycle2Base):
    PATHS = ('income_statement', 'cashflow', 'balance_sheet', 'comparative')

    def test_matrix(self):
        fy = FinancialYear.objects.create(year=self.year)
        for user, ok in ((self.hq, True), (self.direction, True), (self.comptable, True),
                         (self.g1, False), (self.f1, False)):
            for p in self.PATHS:
                r = _api(user).get(f'/api/finance/years/{fy.pk}/{p}/')
                self.assertEqual(r.status_code == 200, ok, (user.role, p, r.status_code))
            for url in ('/api/finance/years/summary/',
                        '/api/finance/years/doc1_report/?node=%s&month=1&year=2026' % self.k1.pk,
                        '/api/finance/years/doc1_export/?node=%s&month=1&year=2026' % self.k1.pk,
                        '/api/finance/years/'):
                r = _api(user).get(url)
                self.assertEqual(r.status_code in (200, 400), ok, (user.role, url, r.status_code))

    def test_anonymous_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get('/api/finance/years/summary/').status_code, (401, 403))

    def test_gerant_cannot_write_years(self):
        for u in (self.g1, self.f1):
            self.assertEqual(_api(u).post('/api/finance/years/', {'year': 2031}, format='json').status_code, 403)
        fy = FinancialYear.objects.create(year=2032)
        self.assertEqual(_api(self.g1).delete(f'/api/finance/years/{fy.pk}/').status_code, 403)

    def test_closed_year_is_not_a_lock(self):
        """Caractérisation : `is_closed` n'empêche aucune saisie datée de l'exercice (documentaire)."""
        fy = FinancialYear.objects.create(year=self.year - 1, is_closed=True)
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 1000, 'CASH', date(self.year - 1, 12, 15))
        self.assertEqual(_income_statement_for_year(fy.year)['total_revenue'], D('1000'))


class Verif3Performance(Cycle2Base):
    def _count(self, url, params=None):
        with CaptureQueriesContext(connection) as ctx:
            r = _api(self.hq).get(url, params or {})
        self.assertEqual(r.status_code, 200)
        n = len(ctx)
        if hasattr(r, 'streaming_content'):
            with CaptureQueriesContext(connection) as ctx2:
                b''.join(r.streaming_content)
            n += len(ctx2)
        return n

    def _all(self, fy, fyp, p):
        return [self._count('/api/finance/years/doc1_report/', p),
                self._count('/api/finance/years/doc1_export/', p),
                self._count(f'/api/finance/years/{fy.pk}/comparative/'),
                self._count(f'/api/finance/years/{fyp.pk}/balance_sheet/'),
                self._count('/api/finance/years/summary/')]

    def test_endpoints_do_not_grow_with_clients(self):
        fy = FinancialYear.objects.create(year=self.year)
        fyp = FinancialYear.objects.create(year=self.year - 1)
        p = {'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year}
        for i in range(2):
            c = make_client(self.k1, credit_limit=D('900000'), last_name=f'P{i}')
            self.sale(self.f1, c, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
            self.sale(self.f1, c, [(self.bp_grand, 1)], 0, 'CREDIT', date(self.year - 1, 12, 2))
        base = self._all(fy, fyp, p)
        for i in range(2, 8):
            c = make_client(self.k1, credit_limit=D('900000'), last_name=f'P{i}')
            inv = self.sale(self.f1, c, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
            self.adjust(inv, -1, 1)
            self.sale(self.f1, c, [(self.bp_grand, 1)], 0, 'CREDIT', date(self.year - 1, 12, 2))
        self.assertEqual(base, self._all(fy, fyp, p))


class Verif3YearBoundary(Cycle2Base):
    def test_consumable_exit_at_local_midnight_goes_to_the_right_year(self):
        """01/01 00:30 heure de Kinshasa = 31/12 23:30 UTC : le coût va en N, pas en N-1."""
        from production.models import ConsumableMovement
        self.stock_move(self.k1, 'FLOUR', 'ENTRY', 10, 4000, date(self.year - 1, 12, 1))
        mv = self.stock_move(self.k1, 'FLOUR', 'EXIT', 1, 0, date(self.year - 1, 12, 1))
        ts = timezone.make_aware(datetime(self.year, 1, 1, 0, 30, 0))
        ConsumableMovement.objects.filter(pk=mv.pk).update(created_at=ts)
        self.assertEqual(_income_statement_for_year(self.year)['cost_flour'], D('4000.00'))
        self.assertEqual(_income_statement_for_year(self.year - 1)['cost_flour'], D('0.00'))

    def test_previous_year_block_equals_direct_computation(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 2000, 'CASH', date(self.year - 1, 12, 31))
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 1000, 'CASH', self.d1)
        fy, _ = FinancialYear.objects.get_or_create(year=self.year)
        j = json.loads(_api(self.direction).get(f'/api/finance/years/{fy.pk}/comparative/').content)
        self.assertEqual(j['income_statement_prev']['total_revenue'], '2000.00')
        self.assertEqual(j['income_statement']['total_revenue'], '1000.00')
        j2 = json.loads(_api(self.direction).get(f'/api/finance/years/{fy.pk}/income_statement/').content)
        self.assertEqual(j2['previous_year'], j['income_statement_prev'])
        self.assertEqual(j2['revenue_growth_pct'], -50.0)


class Verif3TreasuryReplay(_Base):
    """Scénario du cycle 1 rejoué avec les garde-fous de trésorerie (BUG-811 billetage, 813
    dépenses figées, 817 antidatage, 839 versement) : les états ne bougent pas."""

    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.d1 = _dates()[0]
        cls.year = cls.d1.year
        cls.cl = make_client(cls.k1, credit_limit=D('900000'), last_name='Zr')
        cls.sale(cls.f1, cls.cl, [(cls.bp_grand, 10)], 5000, 'CASH', cls.d1)
        cls.expense(cls.g1, 1500, cls.d1)
        cls.close_and_push(cls.g1, cls.d1, _bills(**{'5000': 1, '1000': 3, '500': 1}))

    def _snapshot(self):
        return (_income_statement_for_year(self.year), _balance_sheet_for_year(self.year),
                CashbookEntry.objects.count(), CashClosure.objects.count())

    def test_guards_leave_states_unchanged(self):
        before = self._snapshot()
        g = _api(self.g1)
        r = g.post('/api/treasury/expenses/', {'description': 'x', 'amount': '100', 'category': self.cat.pk,
                                               'date': str(self.d1)}, format='json')
        self.assertIn(r.status_code, (400, 403, 409), r.content)
        day2 = self.d1.replace(day=self.d1.day + 1)
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 1000, 'CASH', day2)
        g.post('/api/treasury/reports/generate/', {'date': str(day2)}, format='json')
        c = g.post('/api/treasury/closures/', {'date': str(day2)}, format='json')
        self.assertIn(c.status_code, (400, 403, 409), c.content)
        r = g.post('/api/treasury/expenses/', {
            'description': 'x', 'amount': '100', 'category': self.cat.pk,
            'date': str(timezone.localdate() + timedelta(days=3))}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        after = self._snapshot()
        self.assertEqual(before[0]['operational_expenses'], after[0]['operational_expenses'])
        self.assertEqual(before[1]['cash_position'], after[1]['cash_position'])
        self.assertEqual(before[2:], after[2:])

    def test_double_push_does_not_double_cash(self):
        closure = CashClosure.objects.get(node=self.k1, date=self.d1)
        r = _api(self.comptable).post(f'/api/treasury/closures/{closure.pk}/push_to_cashbook/', {}, format='json')
        self.assertNotEqual(r.status_code, 201, r.content)
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(last.running_balance, D('3500'))
        self.assertEqual(_balance_sheet_for_year(self.year)['cash_position'], D('3500.00'))

    def test_balance_cash_equals_cashflow_closing(self):
        fy, _ = FinancialYear.objects.get_or_create(year=self.year)
        b = json.loads(_api(self.direction).get(f'/api/finance/years/{fy.pk}/balance_sheet/').content)
        cf = json.loads(_api(self.direction).get(f'/api/finance/years/{fy.pk}/cashflow/').content)
        self.assertEqual(b['cash_position'], cf['closing_balance'])
        self.assertEqual(D(b['total_assets']), D(b['receivables']) + D(b['cash_position']))
