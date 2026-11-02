"""
Transferts Inter-Boulangeries — BUG-014, CLAUDE.md §5.4, remarque.md l.198.

Workflow attendu en 3 temps (remarque.md l.198) :
  1. A (to_node) demande des pains à B (from_node) → PENDING.
  2. B répond (positive → RESPONDED avec quantités envoyées / négative → CANCELLED).
  3. A confirme la réception réelle → CONFIRMED (si quantités identiques) ou
     DISPUTED (si écart) → alerte + blocage de la clôture journalière.

Autres règles vérifiées :
  - Somme du stock groupe inchangée après une validation complète.
  - Seul un utilisateur de la boulangerie destinataire (ou le siège) peut
    confirmer la réception ; la boulangerie émettrice ne peut pas valider
    son propre envoi.
  - Double validation → un seul mouvement.
  - Transfert multi-lignes.
"""
from decimal import Decimal
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user, make_bread_price
from production.models import BreadStock, BreadTransfer, _adjust_bread_stock


class ThreeStepTransferWorkflowTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.user_k1 = make_user(role='GERANT', node=self.k1, username='gerant_k1')
        self.user_k2 = make_user(role='GERANT', node=self.k2, username='gerant_k2')
        self.bp300 = make_bread_price(category='MINI', label='Pain 300 FC', unit_price=300)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        # K1 (le fournisseur) a du stock à envoyer.
        _adjust_bread_stock(self.k1, self.bp300, produced=500)
        _adjust_bread_stock(self.k1, self.bp500, produced=300)

        self.client_k1 = APIClient()
        self.client_k1.force_authenticate(self.user_k1)
        self.client_k2 = APIClient()
        self.client_k2.force_authenticate(self.user_k2)
        # BUG-086 (treasury) : la date de clôture codée en dur ci-dessous
        # ('2026-10-05', dans test_disputed_transfer_blocks_daily_closure_
        # of_concerned_bakery) est antérieure à aujourd'hui dès que
        # l'horloge système avance — sans ce réglage, la nouvelle validation
        # de date de clôture (BUG-086, treasury/views.py) la refuserait AVANT
        # même d'atteindre le contrôle de transfert en écart (BUG-037) que ce
        # test cible, ce qui ferait réussir l'assertion tolérante (400/403)
        # pour la mauvaise raison plutôt que de prouver le blocage BUG-037.
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def _request_from_k2(self, lines):
        """K2 (to_node) demande des pains à K1 (from_node)."""
        return self.client_k2.post('/api/production/transfers/', {
            'from_node': self.k1.pk, 'lines': lines,
        }, format='json')

    def test_full_three_step_flow_with_matching_quantities(self):
        create_resp = self._request_from_k2([
            {'bread_price': self.bp300.pk, 'quantity_sent': 100},
        ])
        self.assertEqual(create_resp.status_code, 201, create_resp.data)
        transfer_id = create_resp.data['id']
        self.assertEqual(create_resp.data['transfer_status'], 'PENDING')

        # Étape 2 — K1 répond positivement, confirme les quantités.
        respond_resp = self.client_k1.post(
            f'/api/production/transfers/{transfer_id}/respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 100}]},
            format='json',
        )
        self.assertEqual(respond_resp.status_code, 200, respond_resp.data)
        self.assertEqual(respond_resp.data['transfer_status'], 'RESPONDED')

        k1_stock = BreadStock.objects.get(node=self.k1, bread_price=self.bp300)
        self.assertEqual(k1_stock.qty_available, 400)  # 500 - 100 déjà déduit à l'envoi

        # Étape 3 — K2 confirme la réception réelle.
        confirm_resp = self.client_k2.post(
            f'/api/production/transfers/{transfer_id}/confirm_reception/',
            {'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 100}]},
            format='json',
        )
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.data)
        self.assertEqual(confirm_resp.data['transfer_status'], 'CONFIRMED')

        k2_stock = BreadStock.objects.get(node=self.k2, bread_price=self.bp300)
        self.assertEqual(k2_stock.qty_available, 100)

        # Somme du stock groupe inchangée (500 + 300 au départ, aucune perte).
        total_group = (
            BreadStock.objects.filter(bread_price=self.bp300).count() and
            sum(s.qty_available for s in BreadStock.objects.filter(bread_price=self.bp300))
        )
        self.assertEqual(total_group, 500)  # 400 chez K1 + 100 chez K2

    def test_partial_validation_creates_dispute_and_notification(self):
        from core.models import SystemNotification
        create_resp = self._request_from_k2([{'bread_price': self.bp300.pk, 'quantity_sent': 100}])
        transfer_id = create_resp.data['id']
        self.client_k1.post(
            f'/api/production/transfers/{transfer_id}/respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 100}]},
            format='json',
        )
        notif_before = SystemNotification.objects.count()
        confirm_resp = self.client_k2.post(
            f'/api/production/transfers/{transfer_id}/confirm_reception/',
            {'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 98}]},
            format='json',
        )
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.data)
        self.assertEqual(confirm_resp.data['transfer_status'], 'DISPUTED')
        self.assertGreater(SystemNotification.objects.count(), notif_before)

    # BUG-037 (testeur-tresorerie) — corrigé par dev-backend le 2026-10-22
    # dans backend/treasury/views.py (_unresolved_incoming_transfer_gap) —
    # voir docs/qa/REGISTRE_BUGS.md. @expectedFailure retiré : ce test
    # référence explicitement BUG-037, qui est dans le périmètre de cette
    # correction (contrairement aux autres tests de ce fichier, non touchés).
    def test_disputed_transfer_blocks_daily_closure_of_concerned_bakery(self):
        """
        CLAUDE.md §5.4 : un écart de quantité validée doit entraîner une
        alerte ET un blocage de la clôture journalière de la boulangerie
        concernée — actuellement seule l'alerte existe, rien n'empêche de
        clôturer la caisse malgré un transfert en litige.
        """
        from core.testing import get_config
        create_resp = self._request_from_k2([{'bread_price': self.bp300.pk, 'quantity_sent': 100}])
        transfer_id = create_resp.data['id']
        self.client_k1.post(
            f'/api/production/transfers/{transfer_id}/respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 100}]},
            format='json',
        )
        self.client_k2.post(
            f'/api/production/transfers/{transfer_id}/confirm_reception/',
            {'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 98}]},
            format='json',
        )
        transfer = BreadTransfer.objects.get(pk=transfer_id)
        self.assertEqual(transfer.transfer_status, 'DISPUTED')

        close_resp = self.client_k2.post('/api/treasury/closures/', {
            'date': '2026-10-05',
        }, format='json')
        self.assertIn(
            close_resp.status_code, (400, 403),
            "La clôture journalière de K2 doit être bloquée tant que le "
            "transfert en litige n'est pas résolu — réponse reçue : "
            f"{close_resp.status_code} {close_resp.data if hasattr(close_resp, 'data') else ''}"
        )

    def test_source_bakery_cannot_confirm_its_own_shipment(self):
        """
        CLAUDE.md : seul un utilisateur de la boulangerie destinataire (ou le
        siège) peut valider la réception ; K1 (émettrice) ne doit pas pouvoir
        confirmer elle-même la réception à la place de K2.
        """
        create_resp = self._request_from_k2([{'bread_price': self.bp300.pk, 'quantity_sent': 100}])
        transfer_id = create_resp.data['id']
        self.client_k1.post(
            f'/api/production/transfers/{transfer_id}/respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 100}]},
            format='json',
        )
        # K1 (l'émettrice, from_node) tente de confirmer la réception à la place de K2.
        confirm_resp = self.client_k1.post(
            f'/api/production/transfers/{transfer_id}/confirm_reception/',
            {'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 100}]},
            format='json',
        )
        self.assertEqual(
            confirm_resp.status_code, 403,
            "K1 (boulangerie émettrice) a pu confirmer elle-même la réception "
            "de son propre envoi à la place de K2 — aucune vérification de "
            f"nœud sur cette action. Réponse reçue : {confirm_resp.status_code}"
        )

    def test_destination_bakery_cannot_respond_to_its_own_request(self):
        """De même, K2 (destinataire) ne doit pas pouvoir répondre à sa propre demande à la place de K1."""
        create_resp = self._request_from_k2([{'bread_price': self.bp300.pk, 'quantity_sent': 100}])
        transfer_id = create_resp.data['id']
        respond_resp = self.client_k2.post(
            f'/api/production/transfers/{transfer_id}/respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 100}]},
            format='json',
        )
        self.assertEqual(
            respond_resp.status_code, 403,
            "K2 (demandeur) a pu répondre lui-même à sa propre demande à la "
            f"place de K1 — réponse reçue : {respond_resp.status_code}"
        )

    def test_double_confirmation_creates_only_one_stock_movement(self):
        create_resp = self._request_from_k2([{'bread_price': self.bp300.pk, 'quantity_sent': 100}])
        transfer_id = create_resp.data['id']
        self.client_k1.post(
            f'/api/production/transfers/{transfer_id}/respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 100}]},
            format='json',
        )
        first = self.client_k2.post(
            f'/api/production/transfers/{transfer_id}/confirm_reception/',
            {'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 100}]},
            format='json',
        )
        self.assertEqual(first.status_code, 200, first.data)
        second = self.client_k2.post(
            f'/api/production/transfers/{transfer_id}/confirm_reception/',
            {'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 100}]},
            format='json',
        )
        # Une 2e confirmation sur un transfert déjà CONFIRMED doit être
        # rejetée (le statut n'est plus RESPONDED).
        self.assertEqual(second.status_code, 400, second.data)
        k2_stock = BreadStock.objects.get(node=self.k2, bread_price=self.bp300)
        self.assertEqual(k2_stock.qty_received, 100)

    def test_multiline_transfer(self):
        create_resp = self._request_from_k2([
            {'bread_price': self.bp300.pk, 'quantity_sent': 100},
            {'bread_price': self.bp500.pk, 'quantity_sent': 50},
        ])
        self.assertEqual(create_resp.status_code, 201, create_resp.data)
        transfer_id = create_resp.data['id']
        self.assertEqual(len(create_resp.data['lines']), 2)

        self.client_k1.post(
            f'/api/production/transfers/{transfer_id}/respond_to_request/',
            {'approved': True, 'lines': [
                {'bread_price': self.bp300.pk, 'quantity_sent': 100},
                {'bread_price': self.bp500.pk, 'quantity_sent': 50},
            ]}, format='json',
        )
        confirm_resp = self.client_k2.post(
            f'/api/production/transfers/{transfer_id}/confirm_reception/',
            {'lines': [
                {'bread_price': self.bp300.pk, 'quantity_received': 100},
                {'bread_price': self.bp500.pk, 'quantity_received': 50},
            ]}, format='json',
        )
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.data)
        self.assertEqual(confirm_resp.data['transfer_status'], 'CONFIRMED')
        self.assertEqual(BreadStock.objects.get(node=self.k2, bread_price=self.bp300).qty_available, 100)
        self.assertEqual(BreadStock.objects.get(node=self.k2, bread_price=self.bp500).qty_available, 50)
