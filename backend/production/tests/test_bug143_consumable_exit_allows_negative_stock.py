"""
BUG-143 — demande client directe le 2026-11-10 (prioritaire sur tout document
de référence antérieur, CLAUDE.md §1) : ANNULE le choix fait par BUG-041.

Une sortie de consommable (`ConsumableMovement` EXIT) — y compris via la
déclaration d'une fournée (`POST /api/production/sessions/`) — ne doit plus
JAMAIS être refusée pour cause de stock insuffisant, même si le stock
disponible est nul (cas réel constaté : base fraîchement réinitialisée,
aucun stock de consommable encore saisi). Le stock devient négatif, valorisé
au CUMP (`ConsumableStock.average_unit_cost`) déjà en place avant la sortie,
et une notification signale (sans bloquer) le passage en négatif.

Avant ce correctif, `ConsumableMovement.save()` levait une `ValidationError`
(BUG-041) : ce test échouait (`ValidationError`/HTTP 400). Il doit désormais
réussir.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price
from production.models import ConsumableType, ConsumableStock, ConsumableMovement


class ConsumableExitAllowsNegativeStockModelTests(TestCase):
    def setUp(self):
        self.node = make_node()
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})

    def test_exit_on_zero_stock_is_accepted_and_goes_negative(self):
        """Cas réel du client : stock de consommable encore à 0."""
        stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'),
            average_unit_cost=Decimal('210000.0000'),
        )
        notif_before = SystemNotification.objects.count()

        movement = ConsumableMovement.objects.create(
            node=self.node, stock=stock, movement_type='EXIT', quantity=Decimal('3.000'),
        )

        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal('-3.000'))
        # CUMP figé depuis le stock au moment de la sortie (BUG-123), intact.
        self.assertEqual(movement.unit_price, Decimal('210000.0000'))
        self.assertGreater(
            SystemNotification.objects.count(), notif_before,
            "Le passage en négatif doit être signalé par une notification (sans bloquer)."
        )

    def test_exit_exceeding_existing_positive_stock_is_accepted_and_goes_negative(self):
        stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('5.000'),
            average_unit_cost=Decimal('210000.0000'),
        )
        ConsumableMovement.objects.create(
            node=self.node, stock=stock, movement_type='EXIT', quantity=Decimal('8.000'),
        )
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal('-3.000'))


class FourneeConsumableExitAllowsNegativeStockAPITests(TestCase):
    """Même règle via le flux réel de déclaration de fournée."""

    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        self.bread_price = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        # Stock à 0 — base fraîchement réinitialisée, rien encore saisi.
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'),
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_declaring_a_fournee_with_insufficient_flour_stock_succeeds(self):
        payload = {
            'team': 'A', 'date': '2026-11-10',
            'flour_sacks_used': '2.00',
            'lines': [{'bread_price': self.bread_price.pk, 'quantity': 300}],
        }
        resp = self.api.post('/api/production/sessions/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('-2.000'))
        self.assertTrue(
            ConsumableMovement.objects.filter(
                node=self.node, stock=self.stock, movement_type='EXIT', quantity=Decimal('2.000')
            ).exists()
        )
