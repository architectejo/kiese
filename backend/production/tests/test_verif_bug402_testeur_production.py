"""
Vérification indépendante de BUG-402 (testeur-production, 2026-11-21) :
CUMP d'une ENTRY sur stock négatif / nul, cas limites non couverts par le
test du développeur (test_bug402_cump_stock_negatif.py).
"""
from decimal import Decimal

from django.test import TestCase

from core.testing import make_node
from production.models import ConsumableStock, ConsumableMovement, ConsumableType

D = Decimal


class Base(TestCase):
    ctype = 'FLOUR'
    unit = 'sac'

    def setUp(self):
        self.node = make_node()
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type=self.ctype, quantity=D('0.000'), unit=self.unit,
        )

    def mv(self, kind, qty, price='0.00'):
        m = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type=kind,
            quantity=D(qty), unit_price=D(price),
        )
        self.stock.refresh_from_db()
        return m


class CumpEdgeCases(Base):
    def test_exit_then_exact_entry_returns_to_zero_and_cump_is_entry_price(self):
        self.mv('EXIT', '5.000')
        self.mv('ENTRY', '5.000', '90000.00')
        self.assertEqual(self.stock.quantity, D('0.000'))
        self.assertEqual(self.stock.average_unit_cost, D('90000.0000'))

    def test_entry_smaller_than_deficit_stock_stays_negative_cump_is_entry_price(self):
        self.mv('EXIT', '5.000')
        self.mv('ENTRY', '2.000', '90000.00')
        self.assertEqual(self.stock.quantity, D('-3.000'))
        self.assertEqual(self.stock.average_unit_cost, D('90000.0000'))
        # Pas de division par zéro ni de CUMP négatif.
        self.assertGreaterEqual(self.stock.average_unit_cost, 0)

    def test_entry_smaller_than_deficit_then_second_entry_recovers_cleanly(self):
        self.mv('EXIT', '5.000')
        self.mv('ENTRY', '2.000', '90000.00')     # -3
        self.mv('ENTRY', '10.000', '100000.00')   # +7, base 0
        self.assertEqual(self.stock.quantity, D('7.000'))
        self.assertEqual(self.stock.average_unit_cost, D('100000.0000'))

    def test_several_exits_then_entry(self):
        for _ in range(3):
            self.mv('EXIT', '2.000')
        self.mv('ENTRY', '10.000', '120000.00')
        self.assertEqual(self.stock.quantity, D('4.000'))
        self.assertEqual(self.stock.average_unit_cost, D('120000.0000'))

    def test_entry_on_zero_stock_with_zero_cump(self):
        self.mv('ENTRY', '4.000', '50000.00')
        self.assertEqual(self.stock.average_unit_cost, D('50000.0000'))

    def test_entry_on_zero_stock_keeps_old_cump_irrelevant(self):
        self.mv('ENTRY', '2.000', '80000.00')
        self.mv('EXIT', '2.000')                  # 0, CUMP 80000
        self.mv('ENTRY', '2.000', '100000.00')    # base 0 -> 100000
        self.assertEqual(self.stock.average_unit_cost, D('100000.0000'))

    def test_successive_entries_after_negative_pass_weighted_normally(self):
        self.mv('EXIT', '3.000')
        self.mv('ENTRY', '5.000', '100000.00')    # +2 @100000
        self.mv('ENTRY', '2.000', '130000.00')    # +4 : (2*100000+2*130000)/4
        self.assertEqual(self.stock.quantity, D('4.000'))
        self.assertEqual(self.stock.average_unit_cost, D('115000.0000'))
        self.mv('ENTRY', '4.000', '100000.00')    # +8 : (4*115000+4*100000)/8
        self.assertEqual(self.stock.average_unit_cost, D('107500.0000'))

    def test_exit_after_entry_on_negative_valued_at_cump_and_does_not_change_cump(self):
        self.mv('EXIT', '5.000')
        self.mv('ENTRY', '10.000', '100000.00')
        out = self.mv('EXIT', '2.000')
        out.refresh_from_db()
        self.assertEqual(out.unit_price, D('100000.00'))
        self.assertEqual(self.stock.average_unit_cost, D('100000.0000'))
        self.assertEqual(self.stock.quantity, D('3.000'))

    def test_exit_on_negative_stock_valued_at_current_cump_not_altered(self):
        self.mv('ENTRY', '2.000', '80000.00')
        out = self.mv('EXIT', '5.000')           # -3
        out.refresh_from_db()
        self.assertEqual(out.unit_price, D('80000.00'))
        self.assertEqual(self.stock.average_unit_cost, D('80000.0000'))
        out2 = self.mv('EXIT', '1.000')          # -4, toujours 80000
        out2.refresh_from_db()
        self.assertEqual(out2.unit_price, D('80000.00'))
        self.assertEqual(self.stock.quantity, D('-4.000'))

    def test_adjustment_style_edit_does_not_touch_cump(self):
        e = self.mv('ENTRY', '10.000', '100000.00')
        e.quantity = D('12.000')
        e.save()
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, D('12.000'))
        self.assertEqual(self.stock.average_unit_cost, D('100000.0000'))

    def test_four_decimal_rounding_stored(self):
        self.mv('ENTRY', '3.000', '100.00')
        self.mv('ENTRY', '4.000', '101.00')       # 704/7 = 100.571428...
        self.assertEqual(self.stock.average_unit_cost, D('100.5714'))

    def test_four_decimal_rounding_after_negative(self):
        self.mv('EXIT', '1.000')
        self.mv('ENTRY', '3.000', '100.00')       # +2 @100
        self.mv('ENTRY', '1.000', '101.00')       # (2*100+101)/3 = 100.3333
        self.assertEqual(self.stock.average_unit_cost, D('100.3333'))


class SaltDecimals(Base):
    ctype, unit = 'SALT', 'g'

    def test_salt_grams(self):
        self.mv('EXIT', '500.000')
        self.mv('ENTRY', '2000.000', '3.00')
        self.assertEqual(self.stock.quantity, D('1500.000'))
        self.assertEqual(self.stock.average_unit_cost, D('3.0000'))


class YeastDecimals(Base):
    ctype, unit = 'YEAST', 'paquet'

    def test_yeast_quarter_packs(self):
        self.mv('EXIT', '0.250')
        self.mv('ENTRY', '0.100', '4000.00')      # -0.15 reste négatif
        self.assertEqual(self.stock.quantity, D('-0.150'))
        self.assertEqual(self.stock.average_unit_cost, D('4000.0000'))
        self.mv('ENTRY', '1.000', '4400.00')      # +0.85, base 0
        self.assertEqual(self.stock.quantity, D('0.850'))
        self.assertEqual(self.stock.average_unit_cost, D('4400.0000'))
        self.mv('ENTRY', '0.250', '5000.00')      # (0.85*4400+0.25*5000)/1.1
        self.assertEqual(self.stock.average_unit_cost, D('4536.3636'))


class OilDecimals(Base):
    ctype, unit = 'OIL', 'L'

    def test_oil_liters_033(self):
        self.mv('EXIT', '0.330')
        self.mv('EXIT', '0.330')
        self.mv('ENTRY', '5.000', '6000.00')
        self.assertEqual(self.stock.quantity, D('4.340'))
        self.assertEqual(self.stock.average_unit_cost, D('6000.0000'))
        out = self.mv('EXIT', '0.330')
        out.refresh_from_db()
        self.assertEqual(out.unit_price, D('6000.00'))


class SyncNotBroken(TestCase):
    def test_sync_exit_before_entry_ends_with_stock_cump_and_exit_consistent(self):
        from sync.services import _push_consumable_movement
        node = make_node()
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        r1 = _push_consumable_movement(node, {
            'id': '22222222-2222-2222-2222-222222222222', 'node': node.code,
            'consumable_type': 'FLOUR', 'movement_type': 'EXIT',
            'quantity': '5.000', 'unit_price': '0.00',
            'created_at': '2026-11-10T08:00:00Z',
        })
        r2 = _push_consumable_movement(node, {
            'id': '33333333-3333-3333-3333-333333333333', 'node': node.code,
            'consumable_type': 'FLOUR', 'movement_type': 'ENTRY',
            'quantity': '10.000', 'unit_price': '100000.00',
            'created_at': '2026-11-09T08:00:00Z',
        })
        self.assertTrue(r1.get('ok', True), r1)
        self.assertTrue(r2.get('ok', True), r2)
        stock = ConsumableStock.objects.get(node=node, consumable_type='FLOUR')
        self.assertEqual(stock.quantity, D('5.000'))
        self.assertEqual(stock.average_unit_cost, D('100000.0000'))
        out = ConsumableMovement.objects.get(movement_type='EXIT', node=node)
        self.assertEqual(out.unit_price, D('100000.00'))
