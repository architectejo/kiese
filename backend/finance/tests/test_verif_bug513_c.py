"""
Caractérisation BUG-513 côté `finance/` (auditeur-comptable, Dev C, 2026-11-22).

Exemple fictif : 100 pains livrés quand le tarif MINI vaut 300 FC (30 000 FC),
puis le tarif passe à 400 FC.
  - Compte de résultat : `line_total` est figé sur la ligne et le regroupement
    se fait par `BreadPrice.category` (pas par prix) -> le chiffre d'affaires
    ne bouge pas (test qui passe).
  - DOC 1 (`doc1_report` / `doc1_export`) : les quantités par palier sont
    classées d'après le tarif COURANT (`line.bread_price.unit_price`, 200/300/
    500/1000 seulement) -> après passage à 400 FC, les 100 pains disparaissent
    de la colonne 300 et ne tombent dans aucune colonne (test `expectedFailure`).
Données entièrement fictives.
"""
import unittest
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import BreadPrice
from core.testing import make_node, make_client, make_user
from sales.models import Invoice, InvoiceLine
from finance.views import _income_statement_for_year


class Bug513FinanceTariffChangeTests(TestCase):

    def setUp(self):
        self.node = make_node(code='K9', name='K9 - AUDIT513')
        self.client_obj = make_client(self.node)
        self.bp = BreadPrice.objects.create(category='MINI', label='Pain 300 FC (513)', unit_price=300, is_active=True)
        inv = Invoice.objects.create(
            node=self.node, client=self.client_obj, status='DELIVERED',
            order_total=Decimal('30000.00'), payment_amount=Decimal('30000.00'),
        )
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=100)
        self.line = InvoiceLine.objects.get(invoice=inv)
        self.today = timezone.now()
        self.admin = make_user(role='ADMIN', node=None, username='admin_bug513')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def _change_tariff(self, new_price=400):
        self.bp.unit_price = new_price
        self.bp.save()

    def _doc1(self):
        resp = self.api.get('/api/finance/years/doc1_report/', {
            'node': str(self.node.id), 'month': str(self.today.month), 'year': str(self.today.year),
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(resp.data), 1)
        return resp.data[0]

    def test_precondition_line_frozen_at_300(self):
        self.assertEqual((self.line.unit_price, self.line.full_unit_price, self.line.line_total), (300, 300, 30000))
        self.assertEqual(self._doc1()['qty_300'], 100)

    def test_income_statement_revenue_unchanged_after_tariff_change(self):
        before = _income_statement_for_year(self.today.year)
        self._change_tariff()
        after = _income_statement_for_year(self.today.year)
        self.assertEqual(before['total_revenue'], Decimal('30000'))
        self.assertEqual(after['total_revenue'], before['total_revenue'])
        self.assertEqual(after['revenue_300'], before['revenue_300'])

    def test_frozen_line_unchanged_after_tariff_change(self):
        self._change_tariff()
        ln = InvoiceLine.objects.get(pk=self.line.pk)
        self.assertEqual((ln.unit_price, ln.full_unit_price, ln.line_total), (300, 300, 30000))

    @unittest.expectedFailure  # BUG-518 : DOC 1 classe les quantites d'apres le tarif courant
    def test_doc1_quantities_stable_after_tariff_change(self):
        self._change_tariff()
        row = self._doc1()
        # Attendu : les 100 pains vendus a 300 FC restent comptes dans la colonne 300.
        self.assertEqual(row['qty_300'], 100)


class Bug520CustomCategoryRevenueTests(TestCase):
    """BUG-520 : une categorie de pain hors MINI/MOYEN/GRAND/PREMIUM (configurable,
    CLAUDE.md §5.4) est absente de `total_revenue`."""

    @unittest.expectedFailure  # BUG-520
    def test_custom_category_sales_are_in_total_revenue(self):
        node = make_node(code='K8', name='K8 - AUDIT520')
        cl = make_client(node)
        bp = BreadPrice.objects.create(category='MICRO_200', label='Pain 200 FC (520)', unit_price=200, is_active=True)
        inv = Invoice.objects.create(node=node, client=cl, status='DELIVERED',
                                     order_total=Decimal('2000.00'), payment_amount=Decimal('2000.00'))
        InvoiceLine.objects.create(invoice=inv, bread_price=bp, quantity=10)
        data = _income_statement_for_year(timezone.now().year)
        self.assertEqual(data['total_revenue'], Decimal('2000'))
