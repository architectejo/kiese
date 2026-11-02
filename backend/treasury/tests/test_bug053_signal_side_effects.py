"""
Vérification indépendante (testeur-tresorerie, phase 4) du signal `pre_save`
sur `sales.Invoice` ajouté par la correction de BUG-036
(`backend/treasury/signals.py`, branché depuis `treasury/apps.py::ready()`).

Objet : confirmer que ce signal ne casse aucun autre flux de sauvegarde de
facture (création normale, annulation, remboursement) et qu'il se déclenche
bien uniquement au bon moment (transition PENDING -> DELIVERED).

Ce fichier documente en plus une anomalie trouvée pendant cette
vérification : lorsqu'une livraison est bloquée par le signal (vacation
déjà rapportée), `Invoice.deliver()` a déjà, à ce moment-là, sauvegardé la
mise à jour du client (`total_breads_received`/`category`) — et ni
`Invoice.deliver()` ni l'action `InvoiceViewSet.deliver` (contrairement à
`InvoiceViewSet.create`, qui est `@transaction.atomic`) n'entourent cette
séquence d'une transaction. Le blocage de la facture (qui reste `PENDING`
en base, comme attendu) laisse donc une mise à jour fantôme du client :
`total_breads_received` augmente et la catégorie peut changer, pour une
livraison qui n'a jamais eu lieu. Voir BUG-053 dans le registre.
"""
import unittest
from decimal import Decimal

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import FacturierReport


def _make_pending_invoice(node, client_obj, facturier, qty, bread):
    inv = Invoice.objects.create(
        node=node, client=client_obj, facturier=facturier, team='A',
        status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
        node_origin=node.code, debt_before=Decimal('0.00'),
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    inv.payment_amount = inv.order_total
    inv.compute_debt_after()
    inv.save()
    return inv


class SignalDoesNotAffectNormalFlowsTests(TestCase):
    """Le signal ne doit gêner ni la création, ni une livraison normale,
    ni une annulation, ni un remboursement — seule la livraison sur une
    vacation déjà rapportée doit être bloquée."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.facturier = make_user(role='FACTURIER', node=self.node, team='A', username='fact_sig_1')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)

    def test_normal_creation_is_not_affected(self):
        inv = _make_pending_invoice(self.node, self.client_obj, self.facturier, 5, self.bread)
        self.assertEqual(inv.status, Invoice.Status.PENDING)

    def test_normal_delivery_without_existing_report_succeeds(self):
        inv = _make_pending_invoice(self.node, self.client_obj, self.facturier, 5, self.bread)
        inv.deliver(livreur=self.facturier)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.DELIVERED)

    def test_cancellation_of_a_pending_invoice_is_not_affected(self):
        inv = _make_pending_invoice(self.node, self.client_obj, self.facturier, 5, self.bread)
        inv.status = Invoice.Status.CANCELLED
        inv.save(update_fields=['status'])
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.CANCELLED)

    def test_resaving_an_already_delivered_invoice_is_not_blocked(self):
        """Une resauvegarde anodine (ex. correction de notes) d'une facture
        déjà DELIVERED ne doit pas être bloquée même si un rapport existe
        déjà pour sa vacation — ce n'est pas un nouvel événement de
        livraison."""
        inv = _make_pending_invoice(self.node, self.client_obj, self.facturier, 5, self.bread)
        inv.deliver(livreur=self.facturier)

        gerant = make_user(role='GERANT', node=self.node, username='gerant_sig_1')
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(gerant)
        resp = api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp.status_code, 200)

        # Resauvegarde anodine d'une facture déjà livrée : ne doit pas lever.
        inv.receipt_number = inv.receipt_number  # no-op volontaire
        inv.save()  # ne doit pas lever ValidationError

    def test_debt_repayment_invoice_delivered_directly_is_not_spuriously_blocked(self):
        """Un remboursement (facture sans ligne, commande=0) créé directement
        DELIVERED (flux occasionnel) ne doit pas être bloqué si aucun rapport
        n'existe encore pour sa vacation."""
        inv = Invoice.objects.create(
            node=self.node, client=self.client_obj, facturier=self.facturier, team='A',
            status=Invoice.Status.DELIVERED, payment_type=Invoice.PaymentType.CASH,
            node_origin=self.node.code, debt_before=Decimal('1000.00'),
            order_total=Decimal('0.00'), payment_amount=Decimal('1000.00'),
            is_debt_repayment=True,
        )
        inv.delivered_at = inv.delivered_at  # champ auto_now_add non utilisé ici
        import django.utils.timezone as tz
        inv.delivered_at = tz.now()
        inv.save()  # ne doit pas lever


class DeliveryBlockedSideEffectTests(TestCase):
    """
    Documente une conséquence non désirée de la correction BUG-036 : la
    mise à jour du client dans `Invoice.deliver()` n'est pas protégée par
    une transaction (contrairement à `InvoiceViewSet.create`), donc un
    blocage du signal au moment de `self.save()` laisse une mise à jour
    fantôme du compteur de pains du client, alors que la facture reste
    PENDING en base (livraison jamais effective). Voir BUG-053.
    """

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_sig_2')
        self.facturier = make_user(role='FACTURIER', node=self.node, team='A', username='fact_sig_2')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)

    def test_blocked_delivery_still_leaves_client_bread_counter_incremented(self):
        from rest_framework.test import APIClient

        # 1) Une première facture est livrée normalement sur la vacation.
        first = _make_pending_invoice(self.node, self.client_obj, self.facturier, 5, self.bread)
        first.deliver(livreur=self.facturier)

        api = APIClient()
        api.force_authenticate(self.gerant)
        resp = api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp.status_code, 200)
        FacturierReport.objects.get(node=self.node, team='A')  # existe désormais

        self.client_obj.refresh_from_db()
        breads_before_blocked_attempt = self.client_obj.total_breads_received
        self.assertEqual(breads_before_blocked_attempt, 5)

        # 2) Une deuxième facture est créée puis sa livraison est tentée
        #    sur la même vacation déjà rapportée : doit être bloquée.
        second = _make_pending_invoice(self.node, self.client_obj, self.facturier, 7, self.bread)
        with self.assertRaises(ValidationError):
            second.deliver(livreur=self.facturier)

        second.refresh_from_db()
        self.assertEqual(
            second.status, Invoice.Status.PENDING,
            "La facture bloquée doit rester PENDING : la livraison n'a jamais eu lieu.",
        )

        self.client_obj.refresh_from_db()
        self.assertEqual(
            self.client_obj.total_breads_received, breads_before_blocked_attempt,
            "BUG-053 : `Invoice.deliver()` incrémente et sauvegarde "
            "`Client.total_breads_received`/`category` AVANT `self.save()` "
            "(qui est l'étape bloquée par le signal BUG-036), sans transaction "
            "entourant la séquence (contrairement à `InvoiceViewSet.create`, "
            "qui est `@transaction.atomic`) : une livraison bloquée laisse donc "
            "une mise à jour fantôme et durable du compteur de pains du client "
            "(et potentiellement de sa catégorie), alors qu'aucune livraison "
            "n'a réellement eu lieu.",
        )
