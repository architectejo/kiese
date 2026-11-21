"""
BUG-402 : le CUMP ne doit pas être gonflé quand une entrée arrive sur un
stock négatif (sorties autorisées en négatif, BUG-143). L'ancienne quantité
est bornée à 0 dans la moyenne pondérée ; la quantité du stock reste exacte.
Données fictives uniquement.
"""
from decimal import Decimal

from django.test import TestCase

from core.testing import make_node
from production.models import ConsumableType, ConsumableStock, ConsumableMovement

D = Decimal


class CumpNegativeStockTests(TestCase):
    def setUp(self):
        self.node = make_node()
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        self.stock = ConsumableStock.objects.create(node=self.node, consumable_type='FLOUR')

    def _move(self, kind, qty, price='0', stock=None):
        stock = stock or self.stock
        ConsumableMovement.objects.create(
            node=self.node, stock=stock, movement_type=kind,
            quantity=D(qty), unit_price=D(price),
        )
        stock.refresh_from_db()
        return stock

    def test_entry_on_negative_stock_not_inflated(self):
        self._move('EXIT', '5')
        s = self._move('ENTRY', '10', '100000')
        self.assertEqual(s.quantity, D('5.000'))
        self.assertEqual(s.average_unit_cost, D('100000.0000'))

    def test_entry_on_negative_stock_not_covering_deficit(self):
        self._move('EXIT', '5')
        s = self._move('ENTRY', '3', '100000')
        self.assertEqual(s.quantity, D('-2.000'))
        self.assertEqual(s.average_unit_cost, D('100000.0000'))

    def test_entry_on_zero_stock(self):
        s = self._move('ENTRY', '4', '90000')
        self.assertEqual(s.quantity, D('4.000'))
        self.assertEqual(s.average_unit_cost, D('90000.0000'))

    def test_entry_on_positive_stock_weighted(self):
        self._move('ENTRY', '10', '100000')
        s = self._move('ENTRY', '10', '120000')
        self.assertEqual(s.quantity, D('20.000'))
        self.assertEqual(s.average_unit_cost, D('110000.0000'))

    def test_several_entries_after_negative(self):
        self._move('EXIT', '2')
        self._move('ENTRY', '4', '100000')
        s = self._move('ENTRY', '6', '110000')
        # Étape 1 : stock -2 -> 2, CUMP 100000 (ancienne quantité bornée à 0).
        # Étape 2 : ancien stock = 2 (positif) -> (2*100000 + 6*110000) / 8.
        self.assertEqual(s.quantity, D('8.000'))
        self.assertEqual(s.average_unit_cost, D('107500.0000'))

    def test_exit_after_recovery_valued_at_correct_cump(self):
        self._move('EXIT', '5')
        self._move('ENTRY', '10', '100000')
        self._move('EXIT', '1')
        m = ConsumableMovement.objects.filter(movement_type='EXIT').order_by('-created_at').first()
        self.assertEqual(m.unit_price, D('100000.00'))

    def test_decimal_units_salt_grams(self):
        self._move('EXIT', '500')
        s = self._move('ENTRY', '2500', '0.40')
        self.assertEqual(s.quantity, D('2000.000'))
        self.assertEqual(s.average_unit_cost, D('0.4000'))

    def test_decimal_units_yeast_packets(self):
        s = self._move('ENTRY', '0.25', '8000')
        self.assertEqual(s.average_unit_cost, D('8000.0000'))
        s = self._move('EXIT', '0.5')
        self.assertEqual(s.quantity, D('-0.250'))
        s = self._move('ENTRY', '0.75', '9000')
        self.assertEqual(s.quantity, D('0.500'))
        self.assertEqual(s.average_unit_cost, D('9000.0000'))

    def test_decimal_units_oil_litres_rounding(self):
        self._move('ENTRY', '1.5', '3000')
        s = self._move('ENTRY', '1', '3100')
        # (1.5*3000 + 1*3100) / 2.5 = 3040 ; puis arrondi à 4 décimales.
        self.assertEqual(s.average_unit_cost, D('3040.0000'))
        s = self._move('ENTRY', '0.333', '3001')
        # (2.5*3040 + 0.333*3001) / 2.833 = 3035.4158...
        self.assertEqual(s.average_unit_cost, D('3035.4158'))
        self.assertEqual(s.average_unit_cost.as_tuple().exponent, -4)

    def test_sync_exit_before_entry_cump_and_restamp(self):
        from sync.services import _push_consumable_movement
        _push_consumable_movement(self.node, {
            'id': '33333333-3333-3333-3333-333333333333', 'node': self.node.code,
            'consumable_type': 'FLOUR', 'movement_type': 'EXIT', 'quantity': '5.000',
            'unit_price': '0.00', 'created_at': '2026-11-10T08:00:00Z',
        })
        _push_consumable_movement(self.node, {
            'id': '44444444-4444-4444-4444-444444444444', 'node': self.node.code,
            'consumable_type': 'FLOUR', 'movement_type': 'ENTRY', 'quantity': '10.000',
            'unit_price': '100000.00', 'supplier': 'MIDEMA',
            'created_at': '2026-11-10T09:00:00Z',
        })
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, D('5.000'))
        self.assertEqual(self.stock.average_unit_cost, D('100000.0000'))
        exit_m = ConsumableMovement.objects.get(movement_type='EXIT')
        self.assertEqual(exit_m.unit_price, D('100000.00'))
