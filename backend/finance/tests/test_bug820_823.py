"""BUG-820 (créances d'un exercice clos), BUG-822 (DOC 1, quantités signées) et
BUG-823 (DOC 1, prix hors 200/300/500/1000 -> `qty_other`). Données fictives."""
from datetime import date
from decimal import Decimal as D

from core.testing import make_bread_price
from finance.tests.test_audit_c_cycle2_c import Cycle2Base
from finance.tests.test_audit_c_cycle1_c import _api
from finance.views import _balance_sheet_for_year


class Bug820(Cycle2Base):
    def test_backdated_invoice_entered_later(self):
        d = date(self.year - 1, 12, 31)
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', d)
        self.sale(self.f1, self.cl, [(self.bp_grand, 1)], 0, 'CREDIT', date(self.year - 1, 12, 5))
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('1500.00'))

    def test_cancelled_pending_invoice(self):
        day = date(self.year - 1, 12, 20)
        api = _api(self.f1)
        ra = api.post('/api/sales/invoices/', {
            'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': '0',
            'invoice_date': str(day), 'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 2}]},
            format='json')
        self.assertEqual(ra.status_code, 201, ra.data)
        self.sale(self.f1, self.cl, [(self.bp_grand, 1)], 0, 'CREDIT', day)
        self.assertEqual(api.post(f"/api/sales/invoices/{ra.data['id']}/cancel/", {},
                                  format='json').status_code, 200)
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('500.00'))


class Bug822823Doc1(Cycle2Base):
    def test_negative_adjustment_subtracts_quantities(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 2)
        self.assertEqual(self.doc1(self.d1)[0]['qty_500'], 8)

    def test_other_price_goes_to_qty_other_without_loss(self):
        bp250 = make_bread_price('MICRO_250', 'Pain 250 FC', 250)
        self.sale(self.f1, self.cl, [(bp250, 4), (self.bp_grand, 1)], 1500, 'CASH', self.d1)
        row = self.doc1(self.d1)[0]
        self.assertEqual(row['qty_other'], 4)
        self.assertEqual(row['qty_500'], 1)
        r = _api(self.hq).get('/api/finance/years/doc1_export/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year})
        body = b''.join(r.streaming_content).decode('utf-8-sig')
        self.assertIn('QTÉ AUTRES', body)
