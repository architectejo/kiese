"""
BUG-178 : une facture de régularisation (RG) n'est pas une vente — ni crédit,
ni cash, ni valeur vendue dans le rapport facturier Niveau 1. Une facture NS
(jamais livrée) reste exclue.

Le Niveau 2 (clôture) et le journal ne lisent que `FacturierReport`
(`total_cash_sales`) : ils héritent donc de la correction.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import FacturierReport


def _invoice(node, facturier, client, bread, qty, payment_type, payment=None,
             special_code='', deliver=True):
    inv = Invoice.objects.create(
        node=node, client=client, facturier=facturier, team='A',
        status=Invoice.Status.PENDING, payment_type=payment_type,
        special_code=special_code,
        node_origin=node.code, debt_before=Decimal('0.00'),
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    if payment is None:
        payment = inv.order_total if payment_type == Invoice.PaymentType.CASH else Decimal('0')
    inv.payment_amount = payment
    inv.compute_debt_after()
    inv.save()
    if deliver:
        inv.deliver(livreur=facturier)
    return inv


class RgNotCreditInFacturierReportTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant178')
        self.fac = make_user(role='FACTURIER', node=self.node, team='A', username='fact178')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _generate(self):
        resp = self.api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        return FacturierReport.objects.get(node=self.node, team='A')

    def test_rg_without_payment_creates_no_credit(self):
        _invoice(self.node, self.fac, self.client_obj, self.bread, 4,
                 Invoice.PaymentType.CASH, payment=Decimal('0'), special_code='RG')
        _invoice(self.node, self.fac, self.client_obj, self.bread, 1,
                 Invoice.PaymentType.CASH)  # vente normale 300 cash
        report = self._generate()
        self.assertEqual(report.total_credit_sales, Decimal('0.00'))

    def test_report_with_rg_equals_report_without_rg(self):
        _invoice(self.node, self.fac, self.client_obj, self.bread, 5, Invoice.PaymentType.CASH)
        _invoice(self.node, self.fac, self.client_obj, self.bread, 3,
                 Invoice.PaymentType.CREDIT, payment=Decimal('0'))
        _invoice(self.node, self.fac, self.client_obj, self.bread, 7,
                 Invoice.PaymentType.CASH, payment=Decimal('0'), special_code='RG')
        report = self._generate()
        self.assertEqual(report.total_cash_sales, Decimal('1500.00'))
        self.assertEqual(report.total_credit_sales, Decimal('900.00'))
        self.assertEqual(report.theoretical_cash, Decimal('1500.00'))
        self.assertEqual(report.breads_sold_by_category, {'Pain 300 FC': 8})

    def test_rg_credit_type_also_neutral(self):
        _invoice(self.node, self.fac, self.client_obj, self.bread, 2, Invoice.PaymentType.CASH)
        _invoice(self.node, self.fac, self.client_obj, self.bread, 7,
                 Invoice.PaymentType.CREDIT, payment=Decimal('0'), special_code='RG')
        report = self._generate()
        self.assertEqual(report.total_credit_sales, Decimal('0.00'))
        self.assertEqual(report.total_cash_sales, Decimal('600.00'))

    def test_only_rg_produces_no_report(self):
        _invoice(self.node, self.fac, self.client_obj, self.bread, 4,
                 Invoice.PaymentType.CASH, payment=Decimal('0'), special_code='RG')
        resp = self.api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertFalse(FacturierReport.objects.filter(node=self.node).exists(), resp.content)

    def test_pending_ns_absent_from_report(self):
        _invoice(self.node, self.fac, self.client_obj, self.bread, 2, Invoice.PaymentType.CASH)
        _invoice(self.node, self.fac, self.client_obj, self.bread, 6,
                 Invoice.PaymentType.CREDIT, payment=Decimal('0'),
                 special_code='NS', deliver=False)
        report = self._generate()
        self.assertEqual(report.total_cash_sales, Decimal('600.00'))
        self.assertEqual(report.total_credit_sales, Decimal('0.00'))

    def test_nominal_scenario_unchanged(self):
        _invoice(self.node, self.fac, self.client_obj, self.bread, 5, Invoice.PaymentType.CASH)
        _invoice(self.node, self.fac, self.client_obj, self.bread, 3,
                 Invoice.PaymentType.CREDIT, payment=Decimal('0'))
        report = self._generate()
        self.assertEqual(report.total_cash_sales, Decimal('1500.00'))
        self.assertEqual(report.total_credit_sales, Decimal('900.00'))
