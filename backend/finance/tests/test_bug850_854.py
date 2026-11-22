"""
Non-régression BUG-850 à BUG-854 (finance, dev-backend, 2026-11-22). Données fictives uniquement.
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal as D

from django.utils import timezone

from core.testing import make_client
from finance.models import FinancialYear
from finance.tests.test_audit_c_cycle1_c import _api
from finance.tests.test_audit_c_cycle2_c import Cycle2Base
from finance.views import _balance_sheet_for_year
from sales.models import Invoice


class Bug850NotServed(Cycle2Base):
    def _pending(self, qty, pay, day):
        r = _api(self.f1).post('/api/sales/invoices/', {
            'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': str(pay),
            'invoice_date': str(day), 'lines': [{'bread_price': self.bp_grand.pk, 'quantity': qty}]},
            format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def test_manual_not_served_keeps_payment_in_closed_year_balance(self):
        inv = self._pending(8, 1000, date(self.year - 1, 12, 20))
        r = _api(self.f1).post(f'/api/sales/invoices/{inv}/mark-not-served/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('-1000.00'))
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('-1000.00'))

    def test_expired_invoice_matches_current_debt(self):
        inv = self._pending(8, 1000, date(self.year - 1, 12, 20))
        Invoice.objects.filter(pk=inv).update(created_at=timezone.now() - timedelta(hours=30))
        from sales.services import expire_pending_invoices
        self.assertEqual(expire_pending_invoices(), 1)
        self.cl.refresh_from_db()
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], self.cl.current_debt)

    def test_cancelled_invoice_still_excluded(self):
        inv = self._pending(8, 0, date(self.year - 1, 12, 20))
        r = _api(self.f1).post(f'/api/sales/invoices/{inv}/cancel/', {}, format='json')
        self.assertIn(r.status_code, (200, 204), getattr(r, 'data', r.content))
        self.cl.refresh_from_db()
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], self.cl.current_debt)


class Bug851ClientDivers(Cycle2Base):
    def _divers(self):
        r = _api(self.f1).post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': '500', 'invoice_date': str(self.d1),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        d = _api(self.f1).post(f"/api/sales/invoices/{r.data['id']}/deliver/", {}, format='json')
        self.assertEqual(d.status_code, 200, d.data)

    def _params(self):
        return {'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year}

    def test_report_and_export_with_client_divers(self):
        self._divers()
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
        rep = _api(self.hq).get('/api/finance/years/doc1_report/', self._params())
        self.assertEqual(rep.status_code, 200)
        names = [r['client_name'] for r in rep.data]
        self.assertIn('CLIENT DIVERS', names)
        self.assertEqual(len(names), 2)
        divers = [r for r in rep.data if r['client_name'] == 'CLIENT DIVERS'][0]
        self.assertEqual(D(divers['invoice_total']), D('500'))
        self.assertEqual(D(divers['debt_after']), D('0'))
        exp = _api(self.hq).get('/api/finance/years/doc1_export/', self._params())
        self.assertEqual(exp.status_code, 200)
        body = b''.join(exp.streaming_content).decode('utf-8-sig')
        self.assertIn('CLIENT DIVERS', body)


class Bug852YearValidation(Cycle2Base):
    def test_create_rejects_out_of_range_year(self):
        for y in (0, 1, 1999, 2101, 65000):
            r = _api(self.direction).post('/api/finance/years/', {'year': y}, format='json')
            self.assertEqual(r.status_code, 400, (y, r.content))
            self.assertIn('année', str(r.json()).lower())
        self.assertFalse(FinancialYear.objects.filter(year__in=(0, 1, 1999, 2101, 65000)).exists())

    def test_create_and_update_accept_valid_year(self):
        r = _api(self.direction).post('/api/finance/years/', {'year': 2040}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        r2 = _api(self.direction).patch(f"/api/finance/years/{r.json()['id']}/", {'year': 0}, format='json')
        self.assertEqual(r2.status_code, 400, r2.content)
        for y in (2000, 2100):
            self.assertEqual(
                _api(self.direction).post('/api/finance/years/', {'year': y}, format='json').status_code, 201)


class Bug853CsvInjection(Cycle2Base):
    def test_text_cells_neutralised_numbers_untouched(self):
        for i, prefix in enumerate(('=', '+', '-', '@')):
            c = make_client(self.k1, credit_limit=D('900000'), last_name=f'{prefix}CMD{i}')
            self.sale(self.f1, c, [(self.bp_grand, 1)], 500, 'CASH', self.d1)
        neg = make_client(self.k1, credit_limit=D('900000'), last_name='Zneg')
        self.sale(self.f1, neg, [(self.bp_grand, 1)], 1500, 'CASH', self.d1)   # BP -1000
        r = _api(self.hq).get('/api/finance/years/doc1_export/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year})
        body = b''.join(r.streaming_content).decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(body)))[1:]
        names = [row[1] for row in rows]
        for i, prefix in enumerate(('=', '+', '-', '@')):
            self.assertTrue([n for n in names if n.startswith(f"'{prefix}CMD{i}")], names)
        self.assertFalse([c for row in rows for c in row[:2] if c[:1] in '=+-@'])
        zneg = [row for row in rows if row[1].startswith('Zneg')][0]
        self.assertEqual(zneg[9], '-1000.00')


class Bug854BpEndOfMonth(Cycle2Base):
    def test_backdated_invoice_is_included(self):
        d20, d5 = self.d1.replace(day=20), self.d1.replace(day=5)
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', d20)
        self.sale(self.f1, self.cl, [(self.bp_grand, 1)], 0, 'CREDIT', d5)
        self.cl.refresh_from_db()
        self.assertEqual(D(self.doc1(self.d1)[0]['debt_after']), self.cl.current_debt)

    def test_opening_debt_without_invoice_is_kept(self):
        self.cl.current_debt = D('700.00')
        self.cl.save(update_fields=['current_debt'])
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
        self.assertEqual(D(self.doc1(self.d1)[0]['debt_after']), D('1700.00'))

    def test_later_month_invoice_not_counted(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self.d1)
        later = (self.d1.replace(day=1) + timedelta(days=40)).replace(day=3)
        self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 0, 'CREDIT', later)
        self.assertEqual(D(self.doc1(self.d1)[0]['debt_after']), D('1000.00'))
