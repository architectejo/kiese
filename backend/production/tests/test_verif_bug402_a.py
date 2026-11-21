"""
Vérification indépendante BUG-402 par testeur-production (2026-11-21).

CUMP d'un consommable quand une entrée arrive sur un stock négatif
(`ConsumableMovement.save()`, branche ENTRY). Toutes les valeurs attendues sont
calculées à la main (voir le commentaire de chaque test). Données fictives.

Règle vérifiée : un stock négatif n'a aucune valeur. Le CUMP vaut
`(max(ancien,0) x ancien_CUMP + qté x prix) / (max(ancien,0) + qté)`, arrondi à
4 décimales ; la quantité du stock reste `ancien + qté`.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest import expectedFailure, mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user
from production.models import (
    ConsumableType, ConsumableStock, ConsumableMovement, ConsumableCount,
)

D = Decimal


class Base(TestCase):
    code = 'FLOUR'

    def setUp(self):
        self.node = make_node()
        ConsumableType.objects.get_or_create(
            code=self.code, defaults={'label': self.code, 'unit': 'u'},
        )
        self.stock = ConsumableStock.objects.create(node=self.node, consumable_type=self.code)

    def move(self, kind, qty, price='0', stock=None):
        stock = stock or self.stock
        ConsumableMovement.objects.create(
            node=self.node, stock=stock, movement_type=kind,
            quantity=D(qty), unit_price=D(price),
        )
        self.stock.refresh_from_db()
        return self.stock

    def assertStock(self, qty, avg):
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, D(qty))
        self.assertEqual(self.stock.average_unit_cost, D(avg))


class NegativeStockCumpTests(Base):
    def test_example_from_dev_b_exit_5_then_entry_10(self):
        # -5 puis +10 a 100 000 : stock 5, CUMP 100 000 (avant correction : 200 000).
        self.move('EXIT', '5')
        self.move('ENTRY', '10', '100000')
        self.assertStock('5.000', '100000.0000')

    def test_entry_not_covering_deficit(self):
        # -5 puis +3 : stock -2 ; la quantite valorisee est 3, CUMP = prix de l'entree.
        self.move('EXIT', '5')
        self.move('ENTRY', '3', '100000')
        self.assertStock('-2.000', '100000.0000')

    def test_entry_exactly_covering_deficit_gives_zero_stock_and_entry_price(self):
        # -5 puis +5 a 90 000 : stock 0, CUMP 90 000 (priced_qty = 5 > 0).
        self.move('EXIT', '5')
        self.move('ENTRY', '5', '90000')
        self.assertStock('0.000', '90000.0000')

    def test_negative_stock_ignores_previous_cump(self):
        # 4 @ 80 000, sortie de 9 -> stock -5 (CUMP 80 000 conserve). Entree 10 @ 100 000 :
        # ancienne quantite bornee a 0 -> CUMP 100 000 (et non (-5*80000+10*100000)/5 = 120 000).
        self.move('ENTRY', '4', '80000')
        self.move('EXIT', '9')
        self.assertStock('-5.000', '80000.0000')
        self.move('ENTRY', '10', '100000')
        self.assertStock('5.000', '100000.0000')

    def test_stock_minus_5_then_two_entries(self):
        # -5 ; +2 @100000 -> -3, CUMP 100000 ; +4 @130000 -> ancien -3 borne a 0 -> qte 1, CUMP 130000.
        self.move('EXIT', '5')
        self.move('ENTRY', '2', '100000')
        self.assertStock('-3.000', '100000.0000')
        self.move('ENTRY', '4', '130000')
        self.assertStock('1.000', '130000.0000')
        # +3 @110000 : ancien 1 (> 0) -> (1*130000 + 3*110000) / 4 = 460000/4 = 115000, qte 4.
        self.move('ENTRY', '3', '110000')
        self.assertStock('4.000', '115000.0000')

    def test_zero_stock_ignores_old_cump(self):
        # 4 @ 80 000 puis sortie de 4 -> stock 0, CUMP 80 000 ; entree 5 @ 100 000 -> 100 000.
        self.move('ENTRY', '4', '80000')
        self.move('EXIT', '4')
        self.assertStock('0.000', '80000.0000')
        self.move('ENTRY', '5', '100000')
        self.assertStock('5.000', '100000.0000')

    def test_positive_stock_classic_weighted_average(self):
        # (10*100000 + 30*120000) / 40 = 4 600 000 / 40 = 115 000.
        self.move('ENTRY', '10', '100000')
        self.move('ENTRY', '30', '120000')
        self.assertStock('40.000', '115000.0000')

    def test_exits_do_not_change_cump(self):
        self.move('ENTRY', '10', '100000')
        self.move('EXIT', '3')
        self.move('EXIT', '9')  # stock -2
        self.assertStock('-2.000', '100000.0000')

    def test_zero_price_entry_on_positive_stock_dilutes(self):
        # (10*100000 + 10*0) / 20 = 50 000.
        self.move('ENTRY', '10', '100000')
        self.move('ENTRY', '10', '0')
        self.assertStock('20.000', '50000.0000')

    def test_zero_price_entry_on_negative_stock(self):
        # -5 puis +10 @ 0 : valeur 0 -> CUMP 0, stock 5 (pas de division par zero).
        self.move('EXIT', '5')
        self.move('ENTRY', '10', '0')
        self.assertStock('5.000', '0.0000')


class DecimalUnitsTests(TestCase):
    def setUp(self):
        self.node = make_node()

    def stock_of(self, code, unit):
        ConsumableType.objects.get_or_create(code=code, defaults={'label': code, 'unit': unit})
        return ConsumableStock.objects.create(node=self.node, consumable_type=code)

    def move(self, stock, kind, qty, price='0'):
        ConsumableMovement.objects.create(
            node=self.node, stock=stock, movement_type=kind, quantity=D(qty), unit_price=D(price),
        )
        stock.refresh_from_db()

    def test_salt_in_grams(self):
        s = self.stock_of('SALT', 'g')
        self.move(s, 'EXIT', '1500')
        self.move(s, 'ENTRY', '5000', '0.35')
        self.assertEqual(s.quantity, D('3500.000'))
        self.assertEqual(s.average_unit_cost, D('0.3500'))
        # (3500*0.35 + 2500*0.45) / 6000 = (1225 + 1125) / 6000 = 0,391666... -> 0,3917
        self.move(s, 'ENTRY', '2500', '0.45')
        self.assertEqual(s.quantity, D('6000.000'))
        self.assertEqual(s.average_unit_cost, D('0.3917'))

    def test_yeast_quarter_packets(self):
        s = self.stock_of('YEAST', 'paquets')
        self.move(s, 'EXIT', '0.25')
        self.assertEqual(s.quantity, D('-0.250'))
        self.move(s, 'ENTRY', '0.75', '8000')
        self.assertEqual(s.quantity, D('0.500'))
        self.assertEqual(s.average_unit_cost, D('8000.0000'))
        # (0,5*8000 + 0,25*8400) / 0,75 = (4000 + 2100) / 0,75 = 8133,3333...
        self.move(s, 'ENTRY', '0.25', '8400')
        self.assertEqual(s.quantity, D('0.750'))
        self.assertEqual(s.average_unit_cost, D('8133.3333'))

    def test_oil_litres(self):
        s = self.stock_of('OIL', 'L')
        self.move(s, 'EXIT', '0.33')
        self.move(s, 'ENTRY', '1.5', '3000')
        self.assertEqual(s.quantity, D('1.170'))
        self.assertEqual(s.average_unit_cost, D('3000.0000'))
        # (1,17*3000 + 0,33*3200) / 1,5 = (3510 + 1056) / 1,5 = 3044
        self.move(s, 'ENTRY', '0.33', '3200')
        self.assertEqual(s.quantity, D('1.500'))
        self.assertEqual(s.average_unit_cost, D('3044.0000'))

    def test_rounding_four_decimals_and_type(self):
        s = self.stock_of('FLOUR', 'sacs')
        self.move(s, 'ENTRY', '1', '100000')
        # (1*100000 + 2*100001) / 3 = 300002/3 = 100000,666666... -> 100000,6667
        self.move(s, 'ENTRY', '2', '100001')
        self.assertEqual(s.average_unit_cost, D('100000.6667'))
        self.assertEqual(s.average_unit_cost.as_tuple().exponent, -4)
        self.assertIsInstance(s.average_unit_cost, Decimal)

    def test_rounding_four_decimals_second_case(self):
        s = self.stock_of('SALT', 'g')
        self.move(s, 'ENTRY', '3', '1')
        # (3*1 + 4*2) / 7 = 11/7 = 1,571428... -> 1,5714
        self.move(s, 'ENTRY', '4', '2')
        self.assertEqual(s.average_unit_cost, D('1.5714'))


class ExitValuationAfterRecoveryTests(Base):
    def test_exit_valued_at_cump_after_recovery(self):
        self.move('EXIT', '5')  # valorisee a 0 (aucune entree encore)
        self.move('ENTRY', '10', '100000')
        self.move('EXIT', '2')
        exits = ConsumableMovement.objects.filter(movement_type='EXIT').order_by('created_at')
        self.assertEqual([e.unit_price for e in exits], [D('0.00'), D('100000.00')])
        self.assertStock('3.000', '100000.0000')
        # +7 @130000 : (3*100000 + 7*130000) / 10 = 1 210 000 / 10 = 121 000 ; sortie suivante a 121 000.
        self.move('ENTRY', '7', '130000')
        self.assertStock('10.000', '121000.0000')
        self.move('EXIT', '1')
        last = ConsumableMovement.objects.filter(movement_type='EXIT').order_by('-created_at', '-pk').first()
        self.assertEqual(last.unit_price, D('121000.00'))

    def test_income_statement_cogs_uses_corrected_cump(self):
        # Sortie 5 (a 0) ; entree 10 @100000 ; sortie 4 a 100000 -> cout farine = 4*100000 = 400 000
        # (avant correction : 4*200000 = 800 000).
        from finance.views import _income_statement_for_year
        self.move('EXIT', '5')
        self.move('ENTRY', '10', '100000')
        self.move('EXIT', '4')
        res = _income_statement_for_year(timezone.now().year)
        self.assertEqual(res['cost_flour'], D('400000'))

    def test_flour_history_reader_unaffected(self):
        user = make_user(role='GERANT', node=self.node)
        api = APIClient()
        api.force_authenticate(user)
        self.move('EXIT', '5')
        self.move('ENTRY', '10', '100000')
        resp = api.get('/api/production/movements/flour_history/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(D(resp.data[0]['total_cost']), D('1000000'))
        self.assertEqual(D(resp.data[0]['unit_price']), D('100000'))


class QuantityEdgeTests(Base):
    """Quantites <= 0 acceptees (decision client BUG-216)."""

    def test_zero_quantity_entry_on_positive_stock_keeps_cump(self):
        self.move('ENTRY', '10', '100000')
        self.move('ENTRY', '0', '0')
        self.assertStock('10.000', '100000.0000')

    def test_zero_quantity_entry_on_positive_stock_with_price_keeps_cump(self):
        self.move('ENTRY', '10', '100000')
        self.move('ENTRY', '0', '555')
        self.assertStock('10.000', '100000.0000')

    @expectedFailure
    def test_zero_quantity_zero_price_entry_on_empty_stock_keeps_cump(self):
        """BUG-360 : une entree de quantite 0 sur un stock <= 0 remplace le CUMP par son prix (0)."""
        self.move('ENTRY', '4', '80000')
        self.move('EXIT', '4')
        self.assertStock('0.000', '80000.0000')
        self.move('ENTRY', '0', '0')
        self.assertStock('0.000', '80000.0000')  # attendu ; obtenu 0.0000

    def test_negative_quantity_entry_same_price_keeps_cump(self):
        # +10 @100000 ; entree -2 @100000 (correction) : (10*100000 - 2*100000)/8 = 100000, stock 8.
        self.move('ENTRY', '10', '100000')
        self.move('ENTRY', '-2', '100000')
        self.assertStock('8.000', '100000.0000')

    def test_negative_quantity_entry_larger_than_stock_does_not_crash(self):
        # priced = 10 + (-20) = -10 <= 0 -> branche « sinon » : CUMP = prix, stock -10.
        self.move('ENTRY', '10', '100000')
        self.move('ENTRY', '-20', '90000')
        self.assertStock('-10.000', '90000.0000')

    def test_string_quantity_is_normalised(self):
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity='2.5', unit_price='100000',
        )
        self.assertStock('2.500', '100000.0000')

    def test_zero_priced_exit_arg_is_ignored(self):
        # La sortie ignore le prix transmis (BUG-123) : valorisee au CUMP du stock.
        self.move('ENTRY', '10', '100000')
        self.move('EXIT', '1', '999')
        e = ConsumableMovement.objects.get(movement_type='EXIT')
        self.assertEqual(e.unit_price, D('100000.00'))


class AtomicityAndStaleInstanceTests(Base):
    def test_failure_while_saving_stock_rolls_back_movement(self):
        self.move('EXIT', '5')
        with mock.patch.object(ConsumableStock, 'save', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                ConsumableMovement.objects.create(
                    node=self.node, stock=self.stock, movement_type='ENTRY',
                    quantity=D('10'), unit_price=D('100000'),
                )
        self.assertEqual(ConsumableMovement.objects.filter(movement_type='ENTRY').count(), 0)
        self.assertStock('-5.000', '0.0000')

    def test_stale_instances_do_not_lose_updates(self):
        # Deux instances chargees AVANT les ecritures (quantite 0 en memoire) : le calcul lit
        # le stock sous verrou en base, pas l'instance. 4 @100000 puis 6 @110000 :
        # (4*100000 + 6*110000) / 10 = 1 060 000 / 10 = 106 000.
        s1 = ConsumableStock.objects.get(pk=self.stock.pk)
        s2 = ConsumableStock.objects.get(pk=self.stock.pk)
        ConsumableMovement.objects.create(node=self.node, stock=s1, movement_type='ENTRY',
                                          quantity=D('4'), unit_price=D('100000'))
        ConsumableMovement.objects.create(node=self.node, stock=s2, movement_type='ENTRY',
                                          quantity=D('6'), unit_price=D('110000'))
        self.assertStock('10.000', '106000.0000')

    def test_stale_instance_after_negative(self):
        s_stale = ConsumableStock.objects.get(pk=self.stock.pk)
        self.move('EXIT', '5')
        ConsumableMovement.objects.create(node=self.node, stock=s_stale, movement_type='ENTRY',
                                          quantity=D('10'), unit_price=D('100000'))
        self.assertStock('5.000', '100000.0000')

    def test_entry_branch_takes_a_row_lock(self):
        import inspect
        src = inspect.getsource(ConsumableMovement.save)
        self.assertGreaterEqual(src.count('select_for_update()'), 2)  # EXIT et ENTRY


class SyncOrderTests(TestCase):
    def setUp(self):
        self.node = make_node()
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})

    def push(self, kind, qty, price='0.00', supplier=''):
        from sync.services import _push_consumable_movement
        rec = {
            'id': str(uuid.uuid4()), 'node': self.node.code, 'consumable_type': 'FLOUR',
            'movement_type': kind, 'quantity': qty, 'unit_price': price,
            'created_at': '2026-11-10T08:00:00Z',
        }
        if supplier:
            rec['supplier'] = supplier
        res = _push_consumable_movement(self.node, rec)
        return rec['id'], res

    def stock(self):
        return ConsumableStock.objects.get(node=self.node, consumable_type='FLOUR')

    def test_exit_before_entry_example(self):
        exit_id, _ = self.push('EXIT', '5.000')
        self.push('ENTRY', '10.000', '100000.00', 'MIDEMA')
        s = self.stock()
        self.assertEqual(s.quantity, D('5.000'))
        self.assertEqual(s.average_unit_cost, D('100000.0000'))
        self.assertEqual(ConsumableMovement.objects.get(pk=exit_id).unit_price, D('100000.00'))

    def test_exit_before_partial_entry_then_second_entry(self):
        exit_id, _ = self.push('EXIT', '5.000')
        self.push('ENTRY', '3.000', '100000.00', 'MIDEMA')
        s = self.stock()
        self.assertEqual(s.quantity, D('-2.000'))
        self.assertEqual(s.average_unit_cost, D('100000.0000'))
        self.assertEqual(ConsumableMovement.objects.get(pk=exit_id).unit_price, D('100000.00'))
        # 2e entree 7 @120000 : ancien -2 borne a 0 -> CUMP 120000, stock 5.
        self.push('ENTRY', '7.000', '120000.00', 'MIDEMA')
        s = self.stock()
        self.assertEqual(s.quantity, D('5.000'))
        self.assertEqual(s.average_unit_cost, D('120000.0000'))

    def test_replay_does_not_double_apply(self):
        eid, _ = self.push('EXIT', '5.000')
        from sync.services import _push_consumable_movement
        _push_consumable_movement(self.node, {
            'id': eid, 'node': self.node.code, 'consumable_type': 'FLOUR',
            'movement_type': 'EXIT', 'quantity': '5.000', 'unit_price': '0.00',
        })
        self.assertEqual(self.stock().quantity, D('-5.000'))


class OtherReadersAndInventoryTests(Base):
    def setUp(self):
        super().setUp()
        self.user = make_user(role='GERANT', node=self.node)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_inventory_count_gap_and_no_effect_on_cump(self):
        self.move('EXIT', '5')
        self.move('ENTRY', '10', '100000')  # stock 5
        resp = self.api.post('/api/production/counts/', {
            'consumable_type': 'FLOUR', 'count_date': date.today().isoformat(),
            'physical_quantity': '3',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(D(str(resp.data['system_quantity'])), D('5'))
        self.assertEqual(D(str(resp.data['gap'])), D('-2'))  # 3 - 5
        self.assertStock('5.000', '100000.0000')
        self.assertEqual(ConsumableMovement.objects.count(), 2)
        self.assertEqual(ConsumableCount.objects.count(), 1)

    def test_inventory_on_negative_stock(self):
        self.move('EXIT', '5')
        resp = self.api.post('/api/production/counts/', {
            'consumable_type': 'FLOUR', 'count_date': date.today().isoformat(),
            'physical_quantity': '0',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(D(str(resp.data['gap'])), D('5'))  # 0 - (-5)
        self.assertStock('-5.000', '0.0000')

    def test_api_entry_on_negative_stock_and_stock_list_exposes_cump(self):
        self.move('EXIT', '5')
        resp = self.api.post('/api/production/movements/', {
            'stock': str(self.stock.pk), 'movement_type': 'ENTRY',
            'quantity': '10', 'unit_price': '100000', 'supplier': 'MIDEMA',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        lst = self.api.get('/api/production/stocks/')
        self.assertEqual(lst.status_code, 200)
        rows = lst.data['results'] if isinstance(lst.data, dict) else lst.data
        row = next(r for r in rows if r['consumable_type'] == 'FLOUR')
        self.assertEqual(D(str(row['average_unit_cost'])), D('100000'))
        self.assertEqual(D(str(row['quantity'])), D('5'))

    def test_movement_update_and_delete_do_not_touch_cump(self):
        # Comportement existant (BUG-222) : update/delete ajustent la quantite, pas le CUMP.
        self.move('EXIT', '5')
        self.move('ENTRY', '10', '100000')
        m = ConsumableMovement.objects.get(movement_type='ENTRY')
        m.delete()
        self.assertStock('-5.000', '100000.0000')  # CUMP non rejoue : limite connue, voir rapport
