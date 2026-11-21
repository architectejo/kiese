"""
BUG-402 : le CUMP ne doit pas être gonflé quand une entrée arrive sur un
stock négatif (sortie autorisée en négatif par BUG-143). Seule la part de
stock réellement positive pèse dans la moyenne pondérée.
"""
from decimal import Decimal

from django.test import TestCase

from core.testing import make_node
from production.models import ConsumableStock, ConsumableMovement


class CumpOnNegativeStockTests(TestCase):
    def setUp(self):
        self.node = make_node()
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'), unit='sac',
        )

    def _mv(self, kind, qty, price='0.00'):
        return ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type=kind,
            quantity=Decimal(qty), unit_price=Decimal(price),
        )

    def test_entry_on_negative_stock_sets_cump_to_entry_price(self):
        self._mv('EXIT', '5.000')
        self._mv('ENTRY', '10.000', '100000.00')
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('5.000'))
        self.assertEqual(self.stock.average_unit_cost, Decimal('100000.0000'))

    def test_entry_on_negative_stock_with_existing_cost_ignores_the_deficit(self):
        self._mv('ENTRY', '2.000', '80000.00')
        self._mv('EXIT', '5.000')  # stock = -3, CUMP 80000
        self._mv('ENTRY', '10.000', '100000.00')
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('7.000'))
        self.assertEqual(self.stock.average_unit_cost, Decimal('100000.0000'))

    def test_entry_on_positive_stock_is_unchanged(self):
        self._mv('ENTRY', '10.000', '200000.00')
        self._mv('ENTRY', '10.000', '220000.00')
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('210000.0000'))

    def test_exit_after_recovery_is_valued_at_corrected_cump(self):
        self._mv('EXIT', '5.000')
        self._mv('ENTRY', '10.000', '100000.00')
        out = self._mv('EXIT', '1.000')
        out.refresh_from_db()
        self.assertEqual(out.unit_price, Decimal('100000.00'))
