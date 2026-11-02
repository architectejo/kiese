"""
Tests de génération des périodes de commissions (CommissionPeriodViewSet.
generate / ClientCommissionViewSet.payroll_listing) — CLAUDE.md §5.3,
BUG-012.

Les factures sont créées directement par l'ORM (le flux de facturation
lui-même est du périmètre de `testeur-ventes` — ici on ne teste que la
frontière avec `commissions`).
"""
from datetime import date
from decimal import Decimal
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from core.testing import make_node, make_user, make_client, make_bread_price
from commissions.models import CommissionPeriod, ClientCommission
from sales.models import Invoice, InvoiceLine


TODAY = date.today()


def _make_delivered_invoice(node, client, bread_price, quantity, unit_total=None, is_soldee=False,
                             payment_amount=None, commission_exempt=False):
    invoice = Invoice.objects.create(
        node=node, client=client,
        payment_type=Invoice.PaymentType.CASH,
        status=Invoice.Status.DELIVERED,
        payment_amount=payment_amount if payment_amount is not None else Decimal('0.00'),
        is_soldee=is_soldee,
        commission_exempt=commission_exempt,
        node_origin=node.code,
    )
    InvoiceLine.objects.create(invoice=invoice, bread_price=bread_price, quantity=quantity)
    invoice.compute_order_total()
    invoice.save(update_fields=['order_total'])
    return invoice


class GenerateCommissionPeriodTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.bp = make_bread_price(category='MOYEN', unit_price=500)
        self.client = make_client(self.node, commission_rate=Decimal('0.25'))
        self.direction = make_user(role='DIRECTION', node=None)
        self.api = APIClient()
        self.api.force_authenticate(user=self.direction)

    def test_generate_computes_cm_brute_from_delivered_invoices(self):
        _make_delivered_invoice(self.node, self.client, self.bp, quantity=400)  # 400 x 500 = 200000 FC
        resp = self.api.post('/api/commissions/periods/generate/', {
            'node': str(self.node.pk), 'month': TODAY.month, 'year': TODAY.year,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

        commission = ClientCommission.objects.get(client=self.client)
        self.assertEqual(commission.order_value, Decimal('200000.00'))
        self.assertEqual(commission.commission_gross, Decimal('50000.00'))  # 200000 x 0.25

    def test_payroll_listing_vertical_totals_match_manual_sum(self):
        client_a = make_client(self.node, commission_rate=Decimal('0.25'), last_name='DEMO-A')
        client_b = make_client(self.node, commission_rate=Decimal('0.30'), last_name='DEMO-B')
        _make_delivered_invoice(self.node, client_a, self.bp, quantity=200)  # 100000 FC
        _make_delivered_invoice(self.node, client_b, self.bp, quantity=100)  # 50000 FC

        resp = self.api.post('/api/commissions/periods/generate/', {
            'node': str(self.node.pk), 'month': TODAY.month, 'year': TODAY.year,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        period = CommissionPeriod.objects.get(node=self.node, month=TODAY.month, year=TODAY.year)

        listing = self.api.get('/api/commissions/commissions/payroll_listing/', {'period': str(period.pk)})
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        rows = listing.json()
        total_cm = sum(Decimal(r['commission_gross']) for r in rows)
        total_net = sum(Decimal(r['net_payable']) for r in rows)

        manual_cm = Decimal('100000.00') * Decimal('0.25') + Decimal('50000.00') * Decimal('0.30')
        self.assertEqual(total_cm, manual_cm)
        self.assertEqual(total_cm, Decimal('40000.00'))
        self.assertEqual(
            total_net,
            sum(c.net_payable for c in ClientCommission.objects.filter(period=period)),
        )


class OccasionalSaleCommissionGenerationTests(TestCase):
    """BUG : une vente occasionnelle (CLIENT DIVERS, `Invoice.client = None`,
    autorisée par CLAUDE.md §5.1/remarque.md l.134) fait planter la
    génération de la période de commissions dès qu'elle est DELIVERED dans
    le mois, car `CommissionPeriodViewSet.generate()` ne filtre pas les
    factures sans client avant de construire `by_client` (commissions/views.py
    ~l.98-135) : `client_id=None` finit par appeler `client.cotisation_sociale`
    sur `client = None` → AttributeError, 500 au lieu de 201."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.bp = make_bread_price(category='MOYEN', unit_price=500)
        self.direction = make_user(role='DIRECTION', node=None)
        self.api = APIClient(raise_request_exception=False)
        self.api.force_authenticate(user=self.direction)

    # BUG-019 (docs/qa/REGISTRE_BUGS.md) — corrigé : `@expectedFailure` retiré définitivement.
    def test_generate_does_not_crash_on_client_less_occasional_sale(self):
        _make_delivered_invoice(self.node, None, self.bp, quantity=10)
        resp = self.api.post('/api/commissions/periods/generate/', {
            'node': str(self.node.pk), 'month': TODAY.month, 'year': TODAY.year,
        }, format='json')
        self.assertEqual(
            resp.status_code, status.HTTP_201_CREATED,
            f"La génération plante sur une vente occasionnelle (client=None) : {getattr(resp, 'data', resp.content)}"
        )


class SoldeeSaleCommissionTests(TestCase):
    """BUG : CLAUDE.md §5.1 — les ventes VENTE SOLDE/VENTE CASH doivent avoir
    CM = 0. `is_soldee=True` est bien exclu du calcul de la dette (BP) côté
    `sales/views.py`, mais `CommissionPeriodViewSet.generate()` agrège
    `order_total` de TOUTES les factures DELIVERED du client, soldées ou
    non (commissions/views.py ~l.104-107), sans jamais exclure les factures
    `is_soldee=True` ni mettre leur taux de commission à 0."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.bp = make_bread_price(category='MOYEN', unit_price=500)
        self.client = make_client(self.node, commission_rate=Decimal('0.25'))
        self.direction = make_user(role='DIRECTION', node=None)
        self.api = APIClient()
        self.api.force_authenticate(user=self.direction)

    # BUG-020 (docs/qa/REGISTRE_BUGS.md) — corrigé : `@expectedFailure` retiré définitivement.
    def test_soldee_invoice_value_is_excluded_from_commission_base(self):
        _make_delivered_invoice(self.node, self.client, self.bp, quantity=200)  # normal : 100000 FC
        _make_delivered_invoice(self.node, self.client, self.bp, quantity=100, is_soldee=True)  # soldée : 50000 FC, CM attendue = 0

        resp = self.api.post('/api/commissions/periods/generate/', {
            'node': str(self.node.pk), 'month': TODAY.month, 'year': TODAY.year,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

        commission = ClientCommission.objects.get(client=self.client)
        self.assertEqual(
            commission.order_value, Decimal('100000.00'),
            "La valeur de la vente soldée (50000 FC) a été incluse dans la base de "
            "calcul de la commission, alors que CLAUDE.md §5.1 impose CM = 0 pour "
            "les ventes VENTE SOLDE/VENTE CASH."
        )


class CommissionExemptInvoiceCommissionTests(TestCase):
    """
    BUG-052 : une facture normale (is_soldee=False) explicitement exonérée
    de commission (`Invoice.commission_exempt=True`) doit, comme une vente
    VENTE SOLDE (BUG-020), avoir sa valeur exclue de la base de calcul de la
    commission (`order_value`) — mais sans aucun impact sur son prix ni sur
    la BP du client, qui restent du périmètre de `sales`, pas de ce test.
    """

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.bp = make_bread_price(category='MOYEN', unit_price=500)
        self.client = make_client(self.node, commission_rate=Decimal('0.25'))
        self.direction = make_user(role='DIRECTION', node=None)
        self.api = APIClient()
        self.api.force_authenticate(user=self.direction)

    def test_commission_exempt_invoice_value_is_excluded_from_commission_base(self):
        _make_delivered_invoice(self.node, self.client, self.bp, quantity=200)  # normal : 100000 FC
        _make_delivered_invoice(
            self.node, self.client, self.bp, quantity=100, commission_exempt=True
        )  # exonérée : 50000 FC, CM attendue = 0

        resp = self.api.post('/api/commissions/periods/generate/', {
            'node': str(self.node.pk), 'month': TODAY.month, 'year': TODAY.year,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

        commission = ClientCommission.objects.get(client=self.client)
        self.assertEqual(
            commission.order_value, Decimal('100000.00'),
            "La valeur de la facture exonérée de commission (50000 FC) a été incluse "
            "dans la base de calcul de la commission, alors que BUG-052 impose CM = 0 "
            "pour une facture normale marquée commission_exempt=True."
        )
