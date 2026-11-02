"""
Passage de non-régression complet (mandat coordinateur, 2026-10-29) sur le
module Ventes/Facturation après les chantiers récents touchant
`Invoice.invoice_date`/`Invoice.deliver()` (BUG-083) et la validation de
date partagée via `core.utils.validate_requested_date` (BUG-086).

Objectif de ce fichier précis : un parcours de bout en bout d'un facturier
« normal » qui ne touche JAMAIS à un champ de date (ni `invoice_date` à la
création, ni `delivered_at` à la livraison), avec `Config.allow_backdated_sales`
dans son état par défaut (`False`, jamais modifié) — pour confirmer que rien
n'a changé pour l'écrasante majorité des utilisateurs qui n'utilisent pas la
fonctionnalité de ventes datées.

Rappel méthodologique (CLAUDE.md §7) : ce fichier n'écrit jamais sur le code
applicatif.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import BreadStock
from sales.models import Invoice


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class NormalFacturierJourneyUntouchedByBackdatingFeatureTests(TestCase):
    """Facture -> livraison -> reçu, sans aucun champ de date dans les payloads,
    réglage `allow_backdated_sales` dans son état par défaut."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp300 = make_bread_price('MINI', 'Pain 300 FC', 300)
        self.bp500 = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.livreur = make_user('LIVREUR', node=self.node)
        self.client_obj = make_client(self.node, credit_limit=Decimal('50000'))
        self.api_facturier = _api_for(self.facturier)
        self.api_livreur = _api_for(self.livreur)
        # Confirme explicitement l'état par défaut du réglage BUG-083, jamais
        # modifié par ce test — c'est le point précis que le mandat demande
        # de vérifier (comportement "exactement comme avant tous ces
        # changements" quand le réglage est désactivé).
        self.assertFalse(Config.get_instance().allow_backdated_sales)
        # Stock initial pour vérifier le déstockage réel (pas seulement que
        # la facture passe).
        BreadStock.objects.create(node=self.node, bread_price=self.bp300, qty_produced=100)
        BreadStock.objects.create(node=self.node, bread_price=self.bp500, qty_produced=50)

    def test_full_invoice_delivery_receipt_cycle_without_any_date_field(self):
        today = date.today()

        # 1) Création de la facture par le facturier — AUCUN champ de date
        #    dans le payload (ni `invoice_date`), exactement comme avant BUG-083.
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '2600.00',
            'lines': [
                {'bread_price': self.bp300.pk, 'quantity': 2},   # 600
                {'bread_price': self.bp500.pk, 'quantity': 4},   # 2000
            ],
        }
        create_resp = self.api_facturier.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(create_resp.status_code, 201, create_resp.data)
        invoice_id = create_resp.data['id']

        invoice = Invoice.objects.get(pk=invoice_id)
        # Statut en attente de livraison (CLAUDE.md §5.2 : flux facturier -> livraison).
        self.assertEqual(invoice.status, Invoice.Status.PENDING)
        # `invoice_date` par défaut = aujourd'hui, sans qu'on l'ait fourni.
        self.assertEqual(invoice.invoice_date, today)
        self.assertIsNone(invoice.delivered_at)
        self.assertEqual(invoice.order_total, Decimal('2600.00'))
        self.assertEqual(invoice.debt_before, Decimal('0.00'))
        self.assertEqual(invoice.debt_after, Decimal('0.00'))  # payé intégralement
        self.assertTrue(invoice.receipt_number)

        # Déstockage immédiat à la création (comportement en vigueur,
        # confirmé non régressé par BUG-083/086 : le stock baisse dès la
        # création, pas seulement à la livraison).
        stock_mini = BreadStock.objects.get(node=self.node, bread_price=self.bp300)
        stock_moyen = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock_mini.qty_available, 98)   # 100 - 2
        self.assertEqual(stock_moyen.qty_available, 46)  # 50 - 4

        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('0.00'))

        # 2) Livraison confirmée par le LIVREUR (remarque.md : facturier OU
        #    livreur) — AUCUN `delivered_at` dans le payload.
        deliver_resp = self.api_livreur.post(f'/api/sales/invoices/{invoice_id}/deliver/', {}, format='json')
        self.assertEqual(deliver_resp.status_code, 200, deliver_resp.data)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.DELIVERED)
        self.assertIsNotNone(invoice.delivered_at)
        # Livré "maintenant" -> daté d'aujourd'hui (pas une date arbitraire).
        # `delivered_at` est stocké en UTC (USE_TZ=True) : conversion à
        # l'heure locale (Africa/Kinshasa) avant extraction de la date
        # calendaire — voir investigation BUG-083 (testeur-ventes, 2026-10-30).
        self.assertEqual(timezone.localtime(invoice.delivered_at).date(), today)
        self.assertEqual(invoice.livreur_id, self.livreur.id)
        # `invoice_date` strictement inchangé par la livraison.
        self.assertEqual(invoice.invoice_date, today)

        # Le stock n'est PAS déduit une seconde fois à la livraison.
        stock_mini.refresh_from_db()
        stock_moyen.refresh_from_db()
        self.assertEqual(stock_mini.qty_available, 98)
        self.assertEqual(stock_moyen.qty_available, 46)

        # 3) Contenu exploitable pour le reçu (CLAUDE.md §5.2) : toutes les
        #    mentions nécessaires sont bien présentes dans la réponse API
        #    consommée par le frontend (ThermalReceipt.tsx).
        detail_resp = self.api_facturier.get(f'/api/sales/invoices/{invoice_id}/')
        self.assertEqual(detail_resp.status_code, 200, detail_resp.data)
        data = detail_resp.data
        for field in (
            'receipt_number', 'node_display', 'client_display', 'client_code',
            'facturier_display', 'livreur_display', 'team',
            'order_total', 'payment_amount', 'debt_before', 'debt_after',
            'commission_rate', 'invoice_date', 'delivered_at', 'lines',
        ):
            self.assertIn(field, data)
        self.assertEqual(len(data['lines']), 2)
        self.assertEqual(data['livreur'], self.livreur.pk)
        self.assertIn(self.facturier.team, ('A', 'B'))
