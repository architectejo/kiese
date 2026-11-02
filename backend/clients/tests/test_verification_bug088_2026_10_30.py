"""
Vérification indépendante de BUG-088 (docs/qa/REGISTRE_BUGS.md), par le
testeur-clients-commissions, le 2026-10-30.

Reproduit intégralement le scénario cassé décrit dans le ticket :
`Clients.tsx` (vente directe au comptoir) crée un « Client Occasionnel » via
`POST /api/clients/clients/`, lit `res.data.id` dans la réponse 201, puis
l'utilise immédiatement pour créer une facture via
`POST /api/sales/invoices/`. Avant la correction de
`ClientCreateSerializer`, `res.data.id` était `undefined` et la facture
n'était jamais créée (échec silencieux côté frontend). Ce test reproduit le
flux côté API, indépendamment du test de contrat déjà écrit par dev-backend
(`clients/tests/test_api.py::ClientCreateResponseContractTests`).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from clients.models import Client
from sales.models import Invoice


class Bug088EndToEndOccasionalClientInvoiceTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        # NB : le ticket BUG-088 d'origine a été reproduit et corrigé avec un
        # utilisateur GERANT (seul rôle autorisé par `IsGerant` à créer un
        # client — `POST /api/clients/clients/` renvoie 403 pour un
        # FACTURIER, indépendamment de BUG-088 ; voir BUG-089 ouvert
        # séparément par ce test de vérification).
        self.gerant = make_user(role='GERANT', node=self.node, team='A')
        self.api = APIClient()
        self.api.force_authenticate(user=self.gerant)
        self.bread = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)

    def test_occasional_client_creation_then_invoice_creation_end_to_end(self):
        # Étape 1 — exactement ce que fait Clients.tsx::triggerCasualSale /
        # la vente directe au comptoir : créer le client occasionnel.
        create_resp = self.api.post('/api/clients/clients/', {
            'first_name': 'Client', 'last_name': 'Occasionnel',
            'phone': '+243 000 000 000', 'address': 'Vente directe au comptoir',
            'notes': 'Occasionnel',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED, create_resp.content)

        # Étape 2 — exactement ce que fait Clients.tsx : lire res.data.id.
        client_api_id = create_resp.data.get('id')
        self.assertIsNotNone(
            client_api_id,
            "res.data.id doit être défini immédiatement après la création "
            "(BUG-088) — sinon la facture suivante ne peut jamais être "
            "enchaînée et l'échec est silencieux côté frontend."
        )
        self.assertTrue(Client.objects.filter(pk=client_api_id).exists())

        # Étape 3 — enchaîner la facture avec cet id, comme salesApi.create(...)
        # dans Clients.tsx (vente cash immédiate, commission_rate = 0 pour une
        # vente occasionnelle).
        invoice_resp = self.api.post('/api/sales/invoices/', {
            'client': str(client_api_id),
            'payment_amount': '1000.00',
            'payment_type': 'CASH',
            'commission_rate': '0.00',
            'lines': [
                {'bread_price': str(self.bread.pk), 'quantity': 2},
            ],
        }, format='json')
        self.assertEqual(
            invoice_resp.status_code, status.HTTP_201_CREATED, invoice_resp.content
        )

        invoice = Invoice.objects.get(pk=invoice_resp.data['id'])
        self.assertEqual(str(invoice.client_id), str(client_api_id))
        self.assertEqual(invoice.order_total, Decimal('1000.00'))
        self.assertEqual(invoice.payment_amount, Decimal('1000.00'))
