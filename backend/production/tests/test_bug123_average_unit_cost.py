"""
BUG-123 (Q-005) : `ConsumableStock.average_unit_cost` (CUMP) doit être
recalculé à chaque entrée et utilisé pour valoriser chaque sortie, afin que
le Compte de Résultat puisse valoriser la CONSOMMATION RÉELLE en production
(mouvements EXIT) plutôt que les achats du mois (ENTRY) — décision du client
du 2026-11-02, docs/qa/QUESTIONS_CLIENT.md Q-005.
"""
from decimal import Decimal

from django.test import TestCase

from core.testing import make_node
from production.models import ConsumableStock, ConsumableMovement


class WeightedAverageUnitCostTests(TestCase):
    def setUp(self):
        self.node = make_node()
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'), unit='sac',
        )

    def test_single_entry_sets_the_average_cost(self):
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('200000.00'),
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('200000.0000'))

    def test_second_entry_at_a_different_price_recomputes_the_weighted_average(self):
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('200000.00'),
        )
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('220000.00'),
        )
        self.stock.refresh_from_db()
        # (10x200000 + 10x220000) / 20 = 210000
        self.assertEqual(self.stock.average_unit_cost, Decimal('210000.0000'))

    def test_exit_movement_is_stamped_with_the_current_average_cost(self):
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('200000.00'),
        )
        exit_mv = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='EXIT',
            quantity=Decimal('4.000'), unit_price=Decimal('999999.00'),  # ignoré, écrasé par le CUMP
        )
        exit_mv.refresh_from_db()
        self.assertEqual(exit_mv.unit_price, Decimal('200000.00'))

    def test_exit_does_not_change_the_average_cost_of_remaining_stock(self):
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('200000.00'),
        )
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='EXIT',
            quantity=Decimal('4.000'),
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('200000.0000'))
        self.assertEqual(self.stock.quantity, Decimal('6.000'))
