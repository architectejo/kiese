"""
BUG-147 : une fournée déclarée alors qu'aucune ligne ConsumableStock n'existe
pour (nœud, consommable) doit créer la ligne à la volée et enregistrer la
sortie (stock négatif autorisé, règle BUG-143 inchangée).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import ConsumableType, ConsumableStock, ConsumableMovement, ProductionSession


class Bug147AutoCreateStockTests(TestCase):
    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        ConsumableType.objects.get_or_create(code='SALT', defaults={'label': 'Sel', 'unit': 'g'})
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def _post(self, **extra):
        payload = {
            'team': 'A', 'date': '2026-11-10', 'flour_sacks_used': '2.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 300}],
        }
        payload.update(extra)
        return self.api.post('/api/production/sessions/', payload, format='json')

    def test_flour_stock_and_exit_created_on_the_fly(self):
        self.assertFalse(ConsumableStock.objects.filter(node=self.node).exists())
        r = self._post()
        self.assertEqual(r.status_code, 201, r.data)
        stock = ConsumableStock.objects.get(node=self.node, consumable_type='FLOUR')
        self.assertEqual(stock.quantity, Decimal('-2.000'))
        self.assertEqual(stock.unit, 'sacs')
        mv = ConsumableMovement.objects.get(node=self.node, stock=stock)
        self.assertEqual(mv.movement_type, 'EXIT')
        self.assertEqual(mv.quantity, Decimal('2.000'))

    def test_extra_consumable_stock_created_too(self):
        r = self._post(consumables_used=[{'consumable_type': 'SALT', 'quantity': '500'}])
        self.assertEqual(r.status_code, 201, r.data)
        salt = ConsumableStock.objects.get(node=self.node, consumable_type='SALT')
        self.assertEqual(salt.quantity, Decimal('-500.000'))

    def test_existing_stock_is_reused_not_duplicated(self):
        ConsumableStock.objects.create(node=self.node, consumable_type='FLOUR', quantity=Decimal('10.000'))
        r = self._post()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(ConsumableStock.objects.filter(node=self.node, consumable_type='FLOUR').count(), 1)
        self.assertEqual(
            ConsumableStock.objects.get(node=self.node, consumable_type='FLOUR').quantity, Decimal('8.000'),
        )

    def test_patch_flour_regularisation_creates_missing_stock(self):
        r = self._post()
        self.assertEqual(r.status_code, 201, r.data)
        ConsumableMovement.objects.all().delete()
        ConsumableStock.objects.all().delete()
        session = ProductionSession.objects.get(node=self.node)
        r2 = self.api.patch(
            f'/api/production/sessions/{session.pk}/', {'flour_sacks_used': '3.00'}, format='json',
        )
        self.assertIn(r2.status_code, (200, 201), r2.data)
        stock = ConsumableStock.objects.get(node=self.node, consumable_type='FLOUR')
        self.assertEqual(stock.quantity, Decimal('-1.000'))
