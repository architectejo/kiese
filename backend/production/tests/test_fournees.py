"""
Déclaration de Fournée — BUG-014 (docs/qa/REGISTRE_BUGS.md), CLAUDE.md §5.4,
remarque.md l.1-6 / l.22-32.

Couvre :
- Valeur théorique = sacs × valeur du sac (Node.sac_value_fc ou Config par défaut).
- Manquant / excédent signés correctement.
- Changement de la valeur du sac sans fausser l'historique des fournées déjà déclarées.
- Ajout/suppression d'une catégorie de pain (ex. pain de 200 FC).
- Consommables décimaux (sel en g, levure en paquets 0,25, huile en litres 0,33)
  décrémentés du stock à la déclaration.
- Stock de pains incrémenté par la fournée.
"""
from decimal import Decimal
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import BreadPrice
from core.testing import make_node, make_user, make_bread_price, get_config
from production.models import (
    ConsumableType, ConsumableStock, ConsumableMovement, BreadStock,
)


class FourneeValeurTests(TestCase):
    """§3.1 — calcul en valeur (sac → valeur théorique), manquant/excédent."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.user = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def _declare(self, flour_sacks, qty_500, team='A', date='2026-10-01'):
        payload = {
            'team': team, 'date': date,
            'flour_sacks_used': str(flour_sacks),
            'lines': [{'bread_price': self.bp500.pk, 'quantity': qty_500}],
        }
        return self.client_api.post('/api/production/sessions/', payload, format='json')

    def test_theoretical_yield_uses_node_sac_value(self):
        """1 sac à 200 000 FC : la valeur théorique doit être sacs × 200 000."""
        resp = self._declare(flour_sacks=1, qty_500=200)  # 200 × 500 = 100 000 FC produits
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['theoretical_yield'], 200000)
        self.assertEqual(resp.data['total_fc_produced'], 100000)
        # Manquant : réel < théorique → yield_gap négatif
        self.assertEqual(resp.data['yield_gap'], 100000 - 200000)
        self.assertLess(resp.data['yield_gap'], 0)

    def test_excedent_is_positive(self):
        """Si la valeur produite dépasse le théorique, l'écart doit être positif (excédent)."""
        resp = self._declare(flour_sacks=1, qty_500=500)  # 500 × 500 = 250 000 FC > 200 000
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertGreater(resp.data['yield_gap'], 0)
        self.assertEqual(resp.data['yield_gap'], 50000)

    def test_bread_stock_incremented_by_fournee(self):
        resp = self._declare(flour_sacks=1, qty_500=200, team='A')
        self.assertEqual(resp.status_code, 201, resp.data)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_produced, 200)
        self.assertEqual(stock.qty_available, 200)

    def test_sac_value_change_does_not_corrupt_historical_session_on_unrelated_edit(self):
        """
        CLAUDE.md §5.4 : la valeur du sac peut varier sans fausser l'historique.
        Une session déclarée avec sac=200 000 FC doit garder son rendement
        théorique d'origine même si on la modifie plus tard (ex: juste pour
        ajouter un commentaire) après que la valeur du sac a changé.
        """
        resp = self._declare(flour_sacks=1, qty_500=200, team='A', date='2026-10-01')
        self.assertEqual(resp.status_code, 201, resp.data)
        session_id = resp.data['id']
        self.assertEqual(resp.data['theoretical_yield'], 200000)

        # La valeur théorique par sac de la boulangerie change (ex: 230 000 FC).
        self.node.sac_value_fc = Decimal('230000')
        self.node.save(update_fields=['sac_value_fc'])

        # Édition non liée à la valeur (ex: ajout d'un commentaire sur la fournée).
        patch_resp = self.client_api.patch(
            f'/api/production/sessions/{session_id}/', {'notes': 'Commentaire ajouté après coup'},
            format='json',
        )
        self.assertEqual(patch_resp.status_code, 200, patch_resp.data)

        # BUG attendu : le rendement théorique de cette fournée PASSÉE a été
        # recalculé avec la NOUVELLE valeur du sac (230 000) au lieu de garder
        # celle en vigueur au moment de la déclaration (200 000) — l'historique
        # est faussé par un changement de configuration ultérieur.
        self.assertEqual(
            patch_resp.data['theoretical_yield'], 200000,
            "L'historique d'une fournée déjà déclarée ne doit pas changer "
            "quand la valeur du sac de la boulangerie est modifiée plus tard."
        )


class BreadCategoryConfigurableTests(TestCase):
    """
    remarque.md l.1-6 / l.182 : la Direction doit pouvoir ajouter ou supprimer
    une catégorie de pain (ex. pain de 200 FC), au-delà des 4 catégories
    MINI/MOYEN/GRAND/PREMIUM codées en dur dans BreadPrice.category.
    """

    def setUp(self):
        self.user = make_user(role='DIRECTION')
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)
        # Les 4 catégories fixes existent déjà (comme en production réelle).
        for cat, price in [('MINI', 300), ('MOYEN', 500), ('GRAND', 1000), ('PREMIUM', 1500)]:
            make_bread_price(category=cat, label=f'Pain {price} FC', unit_price=price)

    def test_direction_can_add_a_new_bread_category_beyond_the_fixed_four(self):
        """
        BUG attendu : BreadPrice.category est un TextChoices figé à 4 valeurs
        (MINI/MOYEN/GRAND/PREMIUM, unique=True) — il est donc impossible
        d'ajouter une 5e catégorie comme le "pain de 200 FC" demandé par le
        client, même si les 4 existantes sont déjà prises par d'autres prix.
        """
        resp = self.client_api.post('/api/core/bread-prices/', {
            'category': 'MICRO_200',
            'label': 'Pain 200 FC',
            'unit_price': 200,
            'is_active': True,
        }, format='json')
        self.assertEqual(
            resp.status_code, 201,
            "La Direction doit pouvoir ajouter une nouvelle catégorie de pain "
            f"(ex. 200 FC) — réponse reçue : {resp.status_code} {resp.data}"
        )

    def test_direction_can_deactivate_remove_a_bread_category(self):
        bp = BreadPrice.objects.get(category='MINI')
        resp = self.client_api.patch(f'/api/core/bread-prices/{bp.pk}/', {'is_active': False}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        bp.refresh_from_db()
        self.assertFalse(bp.is_active)


class FourneeConsumablesTests(TestCase):
    """remarque.md l.22-32 : consommables décimaux décrémentés à la fournée."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.user = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        ConsumableType.objects.get_or_create(code='SALT', defaults={'label': 'Sel', 'unit': 'g'})
        ConsumableType.objects.get_or_create(code='YEAST', defaults={'label': 'Levure', 'unit': 'paquets'})
        ConsumableType.objects.get_or_create(code='OIL', defaults={'label': 'Huile', 'unit': 'L'})
        for code, qty in [('FLOUR', '10.000'), ('SALT', '5000.000'), ('YEAST', '10.000'), ('OIL', '20.000')]:
            ConsumableStock.objects.create(node=self.node, consumable_type=code, quantity=Decimal(qty))
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def test_salt_yeast_oil_decimal_quantities_are_decremented(self):
        """Sel en grammes (entier), levure 0,25 paquet, huile 0,33 litre — valeurs flottantes."""
        payload = {
            'team': 'A', 'date': '2026-10-02',
            'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 200}],
            'consumables_used': [
                {'consumable_type': 'SALT', 'quantity': 300},       # grammes
                {'consumable_type': 'YEAST', 'quantity': '0.25'},   # 1/4 de paquet
                {'consumable_type': 'OIL', 'quantity': '0.33'},     # 1/3 de litre
            ],
        }
        resp = self.client_api.post('/api/production/sessions/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        flour = ConsumableStock.objects.get(node=self.node, consumable_type='FLOUR')
        salt = ConsumableStock.objects.get(node=self.node, consumable_type='SALT')
        yeast = ConsumableStock.objects.get(node=self.node, consumable_type='YEAST')
        oil = ConsumableStock.objects.get(node=self.node, consumable_type='OIL')

        self.assertEqual(flour.quantity, Decimal('9.000'))
        self.assertEqual(salt.quantity, Decimal('4700.000'))
        self.assertEqual(yeast.quantity, Decimal('9.750'))
        self.assertEqual(oil.quantity, Decimal('19.670'))

        # Les mouvements de sortie doivent exister et être rattachés à la session.
        self.assertTrue(
            ConsumableMovement.objects.filter(
                node=self.node, stock=yeast, movement_type='EXIT', quantity=Decimal('0.250')
            ).exists()
        )
