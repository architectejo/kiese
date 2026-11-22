"""
Audit comptable, cycle 4 (verification BUG-850 a 854 + recoupement N / N-1, DOC 1). Donnees fictives.
Lecture seule du code applicatif. Les ecarts sont portes par des `@expectedFailure`.
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal as D
from unittest import expectedFailure

from django.utils import timezone

from core.testing import make_client
from finance.models import FinancialYear
from finance.tests.test_audit_c_cycle1_c import _api
from finance.tests.test_audit_c_cycle2_c import Cycle2Base
from finance.views import _balance_sheet_for_year, _income_statement_for_year
from sales.models import Invoice


class _V4(Cycle2Base):
    def pending(self, user, client, qty, pay, day, ptype='CREDIT', code='', bp=None):
        r = _api(user).post('/api/sales/invoices/', {
            'client': str(client.pk), 'payment_type': ptype, 'payment_amount': str(pay),
            'special_code': code, 'invoice_date': str(day),
            'lines': [{'bread_price': (bp or self.bp_grand).pk, 'quantity': qty}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def not_served(self, inv):
        r = _api(self.f1).post(f'/api/sales/invoices/{inv}/mark-not-served/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def closed_bs(self):
        return _balance_sheet_for_year(self.year - 1)['receivables']


class Verif850NotServed(_V4):
    """BUG-850 : angles d'attaque autres que celui du correcteur."""

    def test_cash_pending_marked_not_served_matches_current_debt(self):
        inv = self.pending(self.f1, self.cl, 8, 4000, date(self.year - 1, 12, 20), ptype='CASH')
        self.not_served(inv)
        self.cl.refresh_from_db()
        self.assertEqual(self.closed_bs(), self.cl.current_debt)

    def test_not_served_after_delivered_invoice_same_client(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 0, 'CREDIT', date(self.year - 1, 12, 10))   # +2000
        inv = self.pending(self.f1, self.cl, 8, 1500, date(self.year - 1, 12, 20))
        self.not_served(inv)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('500.00'))
        self.assertEqual(self.closed_bs(), D('500.00'))

    def test_not_served_dated_next_year_not_in_closed_year(self):
        inv = self.pending(self.f1, self.cl, 8, 1000, date(self.year, 1, 2))
        self.not_served(inv)
        self.assertEqual(self.closed_bs(), D('0'))

    def test_partial_delivery_then_adjustment_matches_current_debt(self):
        day = date(self.year - 1, 12, 15)
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 1000, 'CREDIT', day)   # +4000
        r = _api(self.g1).post(f'/api/sales/invoices/{inv}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': '0', 'invoice_date': str(day),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.cl.refresh_from_db()
        self.assertEqual(self.closed_bs(), self.cl.current_debt)


class Verif851Divers(_V4):
    def _params(self):
        return {'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year}

    def _divers(self, qty=1, pay=500, ptype='CASH'):
        r = _api(self.f1).post('/api/sales/invoices/', {
            'payment_type': ptype, 'payment_amount': str(pay), 'invoice_date': str(self.d1),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': qty}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        d = _api(self.f1).post(f"/api/sales/invoices/{r.data['id']}/deliver/", {}, format='json')
        self.assertEqual(d.status_code, 200, d.data)
        return r.data['id']

    def test_two_divers_invoices_aggregate_on_one_row(self):
        self._divers(1, 500)
        self._divers(2, 1000)
        rows = [r for r in self.doc1(self.d1) if r['client_name'] == 'CLIENT DIVERS']
        self.assertEqual(len(rows), 1)
        self.assertEqual((D(rows[0]['invoice_total']), D(rows[0]['payment_amount'])), (D('1500'), D('1500')))
        self.assertEqual(rows[0]['qty_500'], 3)
        self.assertEqual(rows[0]['client_code'], '')

    def test_divers_adjustment_and_csv_columns_consistent(self):
        inv = self._divers(4, 2000)
        r = _api(self.g1).post(f'/api/sales/invoices/{inv}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': '0', 'invoice_date': str(self.d1),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        rep = [x for x in self.doc1(self.d1) if x['client_name'] == 'CLIENT DIVERS'][0]
        self.assertEqual((rep['qty_500'], D(rep['invoice_total'])), (3, D('1500')))
        exp = _api(self.hq).get('/api/finance/years/doc1_export/', self._params())
        rows = list(csv.reader(io.StringIO(b''.join(exp.streaming_content).decode('utf-8-sig'))))
        self.assertEqual(len(rows[0]), len(rows[1]))
        self.assertEqual(rows[1][1], 'CLIENT DIVERS')

    def test_doc1_total_matches_invoices_total_with_divers(self):
        self._divers(2, 1000)
        self.sale(self.f1, self.cl, [(self.bp_grand, 3)], 500, 'CREDIT', self.d1)
        tot = sum(D(r['invoice_total']) for r in self.doc1(self.d1))
        self.assertEqual(tot, D('2500'))
        self.assertEqual(_income_statement_for_year(self.d1.year)['total_revenue'], D('2500'))


class Verif852Year(_V4):
    def test_non_integer_and_missing_year(self):
        for payload in ({'year': 'abc'}, {'year': None}, {}, {'year': 2000.5}, {'year': '2024'}):
            r = _api(self.direction).post('/api/finance/years/', payload, format='json')
            if payload.get('year') == '2024':
                self.assertEqual(r.status_code, 201, r.content)
            else:
                self.assertEqual(r.status_code, 400, (payload, r.content))

    def test_bounds_and_states_at_limits(self):
        for y in (2000, 2100):
            fy = FinancialYear.objects.create(year=y)
            for path in ('income_statement', 'cashflow', 'balance_sheet', 'comparative'):
                r = _api(self.direction).get(f'/api/finance/years/{fy.pk}/{path}/')
                self.assertEqual(r.status_code, 200, (y, path, r.content))

    def test_duplicate_year_rejected_cleanly(self):
        _api(self.direction).post('/api/finance/years/', {'year': 2050}, format='json')
        r = _api(self.direction).post('/api/finance/years/', {'year': 2050}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_gerant_cannot_create_year(self):
        r = _api(self.g1).post('/api/finance/years/', {'year': 2051}, format='json')
        self.assertEqual(r.status_code, 403)


class Verif853Csv(_V4):
    def _csv(self):
        r = _api(self.hq).get('/api/finance/years/doc1_export/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year})
        return list(csv.reader(io.StringIO(b''.join(r.streaming_content).decode('utf-8-sig'))))

    def test_first_name_and_tab_and_dde_variants(self):
        names = ['=1+1', '+SUM(A1)', '-2+3', '@SUM(1)', '\t=1', '\r=1', '=cmd|calc!A1']
        for i, n in enumerate(names):
            c = make_client(self.k1, credit_limit=D('900000'), last_name=n)
            self.sale(self.f1, c, [(self.bp_grand, 1)], 500, 'CASH', self.d1)
        rows = self._csv()[1:]
        for row in rows:
            for cell in row[:2]:
                self.assertNotIn(cell[:1], ('=', '+', '-', '@', '\t', '\r'), cell)

    def test_client_whose_first_name_starts_with_formula(self):
        c = make_client(self.k1, credit_limit=D('900000'), last_name='Dupont')
        c.first_name = '=HYPERLINK("http://x")'
        c.save()
        self.sale(self.f1, c, [(self.bp_grand, 1)], 500, 'CASH', self.d1)
        for row in self._csv()[1:]:
            for cell in row[:2]:
                self.assertNotIn(cell[:1], ('=', '+', '-', '@'), cell)

    def test_plain_names_unchanged(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 1)], 500, 'CASH', self.d1)
        self.assertEqual(self._csv()[1][1], self.cl.full_name)


class Verif854Bp(_V4):
    def test_bp_matches_current_debt_with_adjustment_and_repayment(self):
        d20, d5 = self.d1.replace(day=20), self.d1.replace(day=5)
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 6)], 500, 'CREDIT', d20)
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', d5)
        self.adjust(inv, -1, 1)
        r = _api(self.f1).post('/api/sales/invoices/', {
            'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': '300',
            'is_debt_repayment': True, 'invoice_date': str(d20), 'lines': []}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.cl.refresh_from_db()
        self.assertEqual(D(self.doc1(self.d1)[0]['debt_after']), self.cl.current_debt)

    def test_cross_node_client_bp_is_global(self):
        """Un client de K1 facture a K2 : BP fin de mois dans DOC 1 de K2 = BP globale."""
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
        self.sale(self.f2, self.cl, [(self.bp_grand, 4)], 0, 'CREDIT', self.d1)
        self.cl.refresh_from_db()
        r = _api(self.hq).get('/api/finance/years/doc1_report/', {
            'node': self.k2.pk, 'month': self.d1.month, 'year': self.d1.year})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(D(r.data[0]['debt_after']), self.cl.current_debt)

    def test_month_with_later_not_served_payment(self):
        """Une facture non servie du mois suivant (versement conserve) n'entre pas dans la BP fin de mois."""
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
        later = (self.d1.replace(day=1) + timedelta(days=40)).replace(day=3)
        inv = self.pending(self.f1, self.cl, 2, 400, later)
        self.not_served(inv)
        self.assertEqual(D(self.doc1(self.d1)[0]['debt_after']), D('1000.00'))


class Bug870Doc1NotServedPayment(_V4):
    """Un versement conserve d'une facture « Non servi » est un encaissement reel (BUG-320 : cash
    facturier et commissions le comptent). DOC 1 (PAIEMENT) l'ignore."""

    @expectedFailure
    def test_doc1_payment_total_includes_not_served_kept_payment(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 1000, 'CASH', self.d1)
        other = make_client(self.k1, credit_limit=D('900000'), last_name='Zo')
        inv = self.pending(self.f1, other, 2, 400, self.d1)
        self.not_served(inv)
        total_paid = sum(D(r['payment_amount']) for r in self.doc1(self.d1))
        self.assertEqual(total_paid, D('1400'))

    def test_commissions_count_the_same_payment_characterisation(self):
        other = make_client(self.k1, credit_limit=D('900000'), last_name='Zo')
        inv = self.pending(self.f1, other, 2, 400, self.d1)
        self.not_served(inv)
        self.assertEqual(Invoice.objects.get(pk=inv).payment_amount, D('400.00'))
        self.assertEqual(self.doc1(self.d1), [])   # aucune ligne : le client encaisse 400 reste invisible
