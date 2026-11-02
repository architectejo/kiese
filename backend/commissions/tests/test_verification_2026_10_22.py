"""
Vérification indépendante de BUG-019/BUG-020 (phase 4, 2026-10-22).

Scénario supplémentaire non couvert exactement par les tests de phase 2
(qui testent chaque cas séparément) : un seul client avec, dans le même
mois, une vente normale, une vente VENTE SOLDE et une vente occasionnelle
(client=None) qui porterait le même numéro de boulangerie/mois — on vérifie
que les deux corrections (filtre combiné `client__isnull=False,
is_soldee=False`) cohabitent sans interaction parasite et que le calcul de
la CM reste exact au FC près (Decimal), comparé à un calcul manuel.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from core.testing import make_node, make_user, make_client, make_bread_price
from commissions.models import ClientCommission
from sales.models import Invoice, InvoiceLine

TODAY = date.today()


def _make_delivered_invoice(node, client, bread_price, quantity, is_soldee=False):
    invoice = Invoice.objects.create(
        node=node, client=client,
        payment_type=Invoice.PaymentType.CASH,
        status=Invoice.Status.DELIVERED,
        is_soldee=is_soldee,
        node_origin=node.code,
    )
    InvoiceLine.objects.create(invoice=invoice, bread_price=bread_price, quantity=quantity)
    invoice.compute_order_total()
    invoice.save(update_fields=['order_total'])
    return invoice


class CombinedOccasionalAndSoldeeSaleTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K2', name='K2 - COQ')
        self.bp = make_bread_price(category='MOYEN', unit_price=500)
        self.client = make_client(self.node, commission_rate=Decimal('0.30'))
        self.direction = make_user(role='DIRECTION', node=None)
        self.api = APIClient()
        self.api.force_authenticate(user=self.direction)

    def test_generate_mixes_normal_soldee_and_occasional_without_crash_and_exact_cm(self):
        # Vente normale du client : 300 pains x 500 FC = 150 000 FC
        _make_delivered_invoice(self.node, self.client, self.bp, quantity=300)
        # Vente VENTE SOLDE du même client : 120 pains x 500 FC = 60 000 FC, CM = 0 attendue
        _make_delivered_invoice(self.node, self.client, self.bp, quantity=120, is_soldee=True)
        # Vente occasionnelle (client=None) dans le même nœud/mois : ne doit
        # pas faire planter la génération ni être rattachée à aucun client.
        _make_delivered_invoice(self.node, None, self.bp, quantity=50)

        resp = self.api.post('/api/commissions/periods/generate/', {
            'node': str(self.node.pk), 'month': TODAY.month, 'year': TODAY.year,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(resp.json()['generated'], 1)  # un seul client réellement traité

        commission = ClientCommission.objects.get(client=self.client)
        manual_order_value = Decimal('300') * Decimal('500')  # seule la vente normale
        manual_cm = manual_order_value * Decimal('0.30')
        self.assertEqual(commission.order_value, manual_order_value)
        self.assertEqual(commission.order_value, Decimal('150000.00'))
        self.assertEqual(commission.commission_gross, manual_cm)
        self.assertEqual(commission.commission_gross, Decimal('45000.00'))
        self.assertIsInstance(commission.commission_gross, Decimal)
