"""
Vérification indépendante BUG-143 par testeur-production (2026-11-10).

Scénario construit moi-même (pas une relecture des tests de dev-backend) :
cas limite distinct de ceux déjà couverts dans
`test_bug143_consumable_exit_allows_negative_stock.py` — dans tous les tests
de dev-backend, une `ConsumableStock` existe déjà (quantité à 0, mais la
LIGNE existe). Ici, on vérifie le cas où AUCUNE ligne `ConsumableStock`
n'existe du tout pour (node, FLOUR) au moment de la déclaration de fournée —
ce qui est la situation exacte d'une base « fraîchement réinitialisée » si
personne n'a encore ouvert la page Stocks Consommables (qui est le seul
endroit, via `ConsumableStockViewSet._ensure_stock_accounts()`, où la ligne
est auto-créée).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price
from production.models import ConsumableType, ConsumableStock, ConsumableMovement


class NoStockRowAtAllTests(TestCase):
    """
    Si aucune ligne ConsumableStock n'existe pour ce consommable à ce nœud
    (jamais auto-créée, jamais approvisionnée), `_record_consumable_exits`
    (production/views.py) fait `ConsumableStock.objects.filter(...).first()`
    -> None -> `if stock:` est faux -> la boucle `continue` silencieusement :
    AUCUN ConsumableMovement n'est créé, AUCUNE notification n'est levée, et
    la consommation de farine n'est tout simplement jamais enregistrée.
    """

    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        self.bread_price = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        # Volontairement : AUCUNE ConsumableStock créée pour ce (node, FLOUR).
        self.assertEqual(
            ConsumableStock.objects.filter(node=self.node, consumable_type='FLOUR').count(), 0,
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_fournee_succeeds_but_flour_consumption_is_silently_not_recorded(self):
        payload = {
            'team': 'A', 'date': '2026-11-10',
            'flour_sacks_used': '2.00',
            'lines': [{'bread_price': self.bread_price.pk, 'quantity': 300}],
        }
        resp = self.api.post('/api/production/sessions/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        # La fournée est bien enregistrée (conforme à la demande client, BUG-143).
        # Mais la consommation de farine est totalement perdue : pas de
        # ConsumableStock créée, pas de ConsumableMovement. (Une notification
        # "Manquant de Rendement" peut être levée par ailleurs — sans rapport
        # avec le stock de consommables — ce n'est pas vérifié ici.)
        self.assertEqual(
            ConsumableStock.objects.filter(node=self.node, consumable_type='FLOUR').count(), 0,
            "Documenté ici (pas une régression de BUG-143 en soi) : voir BUG-147.",
        )
        self.assertEqual(ConsumableMovement.objects.filter(node=self.node).count(), 0)


class NormalPathStillDecrementsStockTests(TestCase):
    """Contrôle positif : quand la ligne ConsumableStock existe (quantité 0
    ou non), le chemin normal décrit par dev-backend fonctionne bien — pour
    bien isoler que le problème ci-dessus est spécifique à l'ABSENCE de la
    ligne, pas une régression générale de BUG-143."""

    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        self.bread_price = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'),
            average_unit_cost=Decimal('210000.0000'),
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_fournee_on_zero_stock_row_succeeds_and_goes_negative_with_notification(self):
        notif_before = SystemNotification.objects.count()
        payload = {
            'team': 'B', 'date': '2026-11-10',
            'flour_sacks_used': '4.50',
            'lines': [{'bread_price': self.bread_price.pk, 'quantity': 600}],
        }
        resp = self.api.post('/api/production/sessions/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal('-4.500'))
        movement = ConsumableMovement.objects.get(node=self.node, stock=self.stock)
        self.assertEqual(movement.unit_price, Decimal('210000.0000'))  # CUMP figé, BUG-123 intact.
        self.assertGreater(SystemNotification.objects.count(), notif_before)


class SyncConsumableValuationRiskTests(TestCase):
    """
    Examen du risque signalé par dev-backend sur `sync/services.py`
    (valorisation COGS potentiellement incorrecte si une sortie désordonnée
    arrive au Cloud avant son entrée). On reproduit le scénario pour vérifier
    l'ampleur réelle du risque et confirmer que le stock, lui, est bien
    remis à niveau en quantité une fois l'entrée rejouée (déjà testé par
    dev-backend) — on vérifie ici spécifiquement le `unit_price` figé sur le
    mouvement EXIT historique, qui NE se corrige PAS rétroactivement.
    """

    def test_exit_synced_before_entry_leaves_stale_unit_price_on_the_exit_movement(self):
        from sync.services import _push_consumable_movement
        node = make_node()
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})

        # Payload EXIT arrivant en premier (désordre réseau entre nœuds).
        exit_payload = {
            'id': '11111111-1111-1111-1111-111111111111',
            'node': node.code,
            'consumable_type': 'FLOUR',
            'movement_type': 'EXIT',
            'quantity': '5.000',
            'unit_price': '0.00',
            'created_at': '2026-11-10T08:00:00Z',
        }
        _push_consumable_movement(node, exit_payload)

        stock = ConsumableStock.objects.get(node=node, consumable_type='FLOUR')
        exit_movement = ConsumableMovement.objects.get(
            node=node, movement_type='EXIT',
        )
        # Valorisée au CUMP courant du stock au moment de l'arrivée = 0 (ligne
        # venant d'être créée paresseusement) : c'est exactement le risque
        # décrit par dev-backend.
        self.assertEqual(exit_movement.unit_price, Decimal('0.0000'))
        self.assertEqual(stock.quantity, Decimal('-5.000'))

        # L'entrée correspondante arrive ensuite, avec un vrai prix d'achat.
        entry_payload = {
            'id': '22222222-2222-2222-2222-222222222222',
            'node': node.code,
            'consumable_type': 'FLOUR',
            'movement_type': 'ENTRY',
            'quantity': '10.000',
            'unit_price': '210000.00',
            'supplier': 'MIDEMA',
            'created_at': '2026-11-10T09:00:00Z',
        }
        _push_consumable_movement(node, entry_payload)

        stock.refresh_from_db()
        exit_movement.refresh_from_db()
        # Le stock redevient correct en quantité (déjà couvert par dev-backend).
        self.assertEqual(stock.quantity, Decimal('5.000'))
        # MAIS le unit_price de la sortie déjà écrite reste figé à 0 — jamais
        # recalculé rétroactivement : confirmé, c'est le risque réel signalé.
        self.assertEqual(exit_movement.unit_price, Decimal('0.0000'))
