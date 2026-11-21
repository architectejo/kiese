"""
Verification independante BUG-177, volet TRESORERIE seulement (testeur-tresorerie,
2026-11-21, Dev C) : une facture NS (non servie) ou RG (regularisation) ne doit
entrer ni dans le rapport facturier (Niveau 1), ni dans la cloture (Niveau 2),
ni dans le livre de caisse ; la NS ne peut pas etre livree par l'API.
Donnees fictives uniquement.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import CashClosure, FacturierReport


def _inv(node, fac, client, bread, qty, ptype, pay, code='', status=None):
    inv = Invoice.objects.create(
        node=node, client=client, facturier=fac, team='A',
        status=Invoice.Status.PENDING, payment_type=ptype, special_code=code,
        node_origin=node.code, debt_before=Decimal('0.00'),
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    inv.payment_amount = Decimal(pay)
    inv.compute_debt_after()
    inv.save()
    return inv


class Bug177TreasuryTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.gerant = make_user('GERANT', node=self.node, username='g177c')
        self.fac = make_user('FACTURIER', node=self.node, team='A', username='f177c')
        self.cl = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        self.fac_api = APIClient()
        self.fac_api.force_authenticate(self.fac)

    def _gen(self):
        r = self.api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_ns_cash_and_credit_never_in_level1_and_level2(self):
        normal = _inv(self.node, self.fac, self.cl, self.bread, 5, Invoice.PaymentType.CASH, '1500')
        normal.deliver(livreur=self.fac)
        ns_cash = _inv(self.node, self.fac, self.cl, self.bread, 4, Invoice.PaymentType.CASH, '1200', code='NS')
        _inv(self.node, self.fac, self.cl, self.bread, 6, Invoice.PaymentType.CREDIT, '0', code='NS')
        self._gen()
        r = FacturierReport.objects.get(node=self.node, team='A')
        self.assertEqual(r.total_cash_sales, Decimal('1500'))
        self.assertEqual(r.total_credit_sales, Decimal('0'))
        self.assertEqual(r.theoretical_cash, Decimal('1500'))
        self.assertEqual(r.breads_sold_by_category, {'Pain 300 FC': 5})
        # la NS n'est jamais livrable
        resp = self.fac_api.post(f'/api/sales/invoices/{ns_cash.id}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        ns_cash.refresh_from_db()
        self.assertNotEqual(ns_cash.status, Invoice.Status.DELIVERED)
        # Niveau 2
        c = self.api.post('/api/treasury/closures/', {
            'date': str(date.today()), 'bills_1000': 1, 'bills_500': 1,
        }, format='json')
        self.assertEqual(c.status_code, 201, c.content)
        clo = CashClosure.objects.get(pk=c.data['id'])
        self.assertEqual(clo.total_entries, Decimal('1500'))
        self.assertEqual(clo.net_cash, Decimal('1500'))
        self.assertEqual(clo.cash_gap, Decimal('0'))

    def test_day_with_only_ns_gives_zero_report(self):
        _inv(self.node, self.fac, self.cl, self.bread, 4, Invoice.PaymentType.CASH, '0', code='NS')
        self._gen()
        total = sum((x.total_cash_sales + x.total_credit_sales for x in FacturierReport.objects.all()), Decimal('0'))
        self.assertEqual(total, Decimal('0'))
