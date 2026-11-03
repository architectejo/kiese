"""
BUG-121 (Q-001) : la grille de prix de référence seedée par
`manage.py seed_kiese` doit être 200/300/500/1000 FC (fichier Excel réel
d'août 2026, confirmé par le client), pas 300/400/500/1000 FC (cahier des
charges initial, écrasé par remarque.md > adaptes.md).

Convention de `category` alignée avec `seed_from_excel.py` et
`scripts/charge/volumetrie.py` (MINI=200, MOYEN=300, GRAND=500, PREMIUM=1000),
déjà utilisée ailleurs dans le dépôt pour ce même palier.
"""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from core.models import BreadPrice


class SeedKieseBreadPriceGridTests(TestCase):
    def test_seed_kiese_creates_the_200_300_500_1000_grid(self):
        call_command('seed_kiese')

        prices = {
            bp.category: bp.unit_price
            for bp in BreadPrice.objects.all()
        }

        self.assertEqual(prices.get('MINI'), Decimal('200'))
        self.assertEqual(prices.get('MOYEN'), Decimal('300'))
        self.assertEqual(prices.get('GRAND'), Decimal('500'))
        self.assertEqual(prices.get('PREMIUM'), Decimal('1000'))

        # Grille 300/400/500/1000 (cahier des charges) ne doit plus être seedée.
        self.assertNotIn(Decimal('400'), prices.values())
