"""
Consommables — BUG-014, CLAUDE.md §5.4, remarque.md l.20-32.

- Stock restant = initial + entrées − utilisé sur une séquence de mouvements.
- Approvisionnement : la liste des consommables doit être disponible
  (remarque.md l.22 : « La liste de consommables n'apparait pas lorsque je
  veux enregistrer l'approvisionnement ») — comptes de stock auto-créés par
  ConsumableStockViewSet._ensure_stock_accounts.
- Inventaire physique (ConsumableCount) : écart calculé.
- Alerte de surconsommation par rapport à la moyenne par sac.
- Stock négatif : refusé ou signalé ?
"""
from decimal import Decimal
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user
from production.models import ConsumableType, ConsumableStock, ConsumableMovement


class StockRestantSequenceTests(TestCase):
    """Stock restant = initial + entrées − utilisé, sur une séquence de mouvements."""

    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        ConsumableType.objects.get_or_create(code='SALT', defaults={'label': 'Sel', 'unit': 'g'})
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='SALT', quantity=Decimal('1000.000'), unit='g'
        )

    def test_running_balance_over_a_sequence_of_movements(self):
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY', quantity=Decimal('500.000'),
        )
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='EXIT', quantity=Decimal('300.000'),
        )
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY', quantity=Decimal('200.000'),
        )
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='EXIT', quantity=Decimal('150.000'),
        )
        self.stock.refresh_from_db()
        # 1000 + 500 - 300 + 200 - 150 = 1250
        self.assertEqual(self.stock.quantity, Decimal('1250.000'))


class ApprovisionnementConsumableListTests(TestCase):
    """
    remarque.md l.22 : la liste des consommables doit apparaître au moment de
    l'approvisionnement (ConsumableStockViewSet._ensure_stock_accounts).
    """

    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        ConsumableType.objects.get_or_create(code='SALT', defaults={'label': 'Sel', 'unit': 'g'})
        ConsumableType.objects.get_or_create(code='YEAST', defaults={'label': 'Levure', 'unit': 'paquets'})
        ConsumableType.objects.get_or_create(code='OIL', defaults={'label': 'Huile', 'unit': 'L'})

    def test_consumable_list_appears_for_supply_form_without_prior_setup(self):
        """
        Avant même qu'un ConsumableStock existe, un GET sur /stocks/ pour la
        boulangerie du gérant doit créer et renvoyer les comptes manquants
        pour chaque type actif — sinon le formulaire d'approvisionnement
        n'a aucun consommable à proposer.
        """
        self.assertEqual(ConsumableStock.objects.filter(node=self.node).count(), 0)
        resp = self.client_api.get('/api/production/stocks/')
        self.assertEqual(resp.status_code, 200, resp.data)
        codes = {row['consumable_type'] for row in resp.data['results']}
        self.assertEqual(codes, {'FLOUR', 'SALT', 'YEAST', 'OIL'})
        self.assertEqual(ConsumableStock.objects.filter(node=self.node).count(), 4)

    def test_new_type_added_later_appears_without_manual_setup(self):
        self.client_api.get('/api/production/stocks/')  # creates the first 4 accounts
        ConsumableType.objects.create(code='SUGAR', label='Sucre', unit='kg')
        resp = self.client_api.get('/api/production/stocks/')
        codes = {row['consumable_type'] for row in resp.data['results']}
        self.assertIn('SUGAR', codes)


class ConsumableCountGapTests(TestCase):
    """Inventaire physique : écart = physique − système."""

    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)
        ConsumableType.objects.get_or_create(code='FLOUR', defaults={'label': 'Farine', 'unit': 'sacs'})
        ConsumableStock.objects.create(node=self.node, consumable_type='FLOUR', quantity=Decimal('10.000'))

    def test_physical_count_computes_signed_gap(self):
        resp = self.client_api.post('/api/production/counts/', {
            'consumable_type': 'FLOUR',
            'count_date': '2026-10-05',
            'physical_quantity': '8.500',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['system_quantity']), Decimal('10.000'))
        self.assertEqual(Decimal(resp.data['gap']), Decimal('-1.500'))


class OverconsumptionAlertTests(TestCase):
    """
    CLAUDE.md §5.4 : alerte de surconsommation d'un consommable par rapport
    à la moyenne par sac observée historiquement.
    """

    def setUp(self):
        from core.testing import make_bread_price, get_config
        # Pré-crée le singleton Config AVANT de mesurer les notifications :
        # Config.get_instance() déclenche une création paresseuse à la
        # première utilisation (ici, le premier `perform_create` de
        # ProductionSessionViewSet), ce qui émettrait sinon une notification
        # "Configuration mise à jour" parasite au tout premier appel et
        # fausserait le comptage isolé de la surconsommation ci-dessous. En
        # conditions réelles, la Config est déjà initialisée bien avant toute
        # fournée — ce pré-chargement reproduit fidèlement ce contexte.
        get_config()
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.user = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        ConsumableType.objects.get_or_create(code='SALT', defaults={'label': 'Sel', 'unit': 'g'})
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='SALT', quantity=Decimal('100000.000')
        )
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def _declare(self, flour_sacks, salt_qty, date):
        # qty_500 choisie pour que total_fc_produced == theoretical_yield
        # exactement (pas de "manquant de rendement") : isole la seule
        # question testée ici, la surconsommation de sel, sans bruit d'une
        # notification de manquant qui fausserait le comptage.
        qty_500 = int(flour_sacks * 200000 / 500)
        payload = {
            'team': 'A', 'date': date, 'flour_sacks_used': str(flour_sacks),
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty_500}],
            'consumables_used': [{'consumable_type': 'SALT', 'quantity': salt_qty}],
        }
        return self.client_api.post('/api/production/sessions/', payload, format='json')

    def test_overconsumption_relative_to_average_per_sack_triggers_an_alert(self):
        """
        Historique : ~500 g de sel par sac sur plusieurs fournées (rendement
        exact, aucune notification de manquant parasite). Une fournée qui en
        consomme 5000 g pour 1 sac (10× la moyenne) doit déclencher une
        alerte de surconsommation.
        """
        notif_before = SystemNotification.objects.count()
        for i, d in enumerate(['2026-09-01', '2026-09-02', '2026-09-03'], start=1):
            resp = self._declare(flour_sacks=1, salt_qty=500, date=d)
            self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            SystemNotification.objects.count(), notif_before,
            "Ces 3 fournées de référence ne doivent générer aucune "
            "notification parasite (rendement exact) pour isoler le test."
        )

        resp = self._declare(flour_sacks=1, salt_qty=5000, date='2026-09-10')
        self.assertEqual(resp.status_code, 201, resp.data)

        # Correction dev-backend (BUG-040) : le seuil `notif_before + 3`
        # exigeait à tort 4 notifications supplémentaires pour un seul
        # événement de surconsommation (sel uniquement, une seule fournée
        # litigieuse) — incohérent avec CLAUDE.md §5.4, qui ne demande
        # qu'« une alerte » (singulier) par dépassement détecté. Les 3
        # fournées de référence ont déjà été vérifiées sans notification
        # parasite ci-dessus (`notif_before` inchangé) ; on vérifie ici
        # qu'au moins une notification nouvelle a bien été créée par la
        # fournée en surconsommation, sans imposer un nombre arbitraire.
        self.assertGreater(
            SystemNotification.objects.count(), notif_before,
            "Aucune fonctionnalité d'alerte de surconsommation par rapport à "
            "la moyenne par sac n'est implémentée (CLAUDE.md §5.4)."
        )


class NegativeConsumableStockTests(TestCase):
    """Stock négatif de consommable : refusé ou signalé ?"""

    def setUp(self):
        self.node = make_node()
        self.user = make_user(role='GERANT', node=self.node)
        ConsumableType.objects.get_or_create(code='SALT', defaults={'label': 'Sel', 'unit': 'g'})
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='SALT', quantity=Decimal('100.000')
        )

    def test_exit_exceeding_stock_is_rejected_or_flagged(self):
        """
        Une sortie de 500 g alors qu'il n'y a que 100 g en stock devrait être
        refusée (ValidationError) ou au moins signalée (notification) —
        actuellement rien de tout cela ne se produit : le stock passe
        silencieusement à -400.
        """
        notif_before = SystemNotification.objects.count()
        from django.core.exceptions import ValidationError
        try:
            ConsumableMovement.objects.create(
                node=self.node, stock=self.stock, movement_type='EXIT', quantity=Decimal('500.000'),
            )
        except ValidationError:
            return  # refusé — comportement acceptable
        self.stock.refresh_from_db()
        if self.stock.quantity < 0:
            self.assertGreater(
                SystemNotification.objects.count(), notif_before,
                "Un stock de consommable passé négatif doit au moins être "
                "signalé par une notification si l'opération n'est pas refusée."
            )
