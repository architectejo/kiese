"""
BUG-097 (docs/qa/REGISTRE_BUGS.md) : correction/annulation d'une commande
déjà enregistrée via une nouvelle facture liée (« grande trace »), jamais
une mutation de l'originale — remarque.md, « Réclamation des agents du
client », point 4.

Décisions du coordinateur (2026-10-30), implémentées à l'identique :
1. `Invoice.adjusts` (FK self, PROTECT) + `Invoice.is_adjustment` (bool) +
   `Invoice.adjustment_sign` (+1/-1) — `InvoiceLine.quantity` reste positif
   (magnitude), le signe est porté par la facture entière.
2. Stock : retour/ajout physique PAR DÉFAUT. `adjustment_sign=-1` restitue
   le stock, `adjustment_sign=+1` le décrémente comme une vente normale.
3. Commission déjà clôturée : avertissement seul (jamais de blocage), via
   `_warn_if_commission_period_locked` (BUG-083), déclenché systématiquement.
4. BP : l'ajustement est une "mini-facture" liée, `order_total`/
   `payment_amount` portent le signe, `debt_after` via la formule standard.
5. Permission : GERANT et au-dessus uniquement (`IsGerant`) — jamais
   FACTURIER ni LIVREUR.
6. Traçabilité : `is_adjustment=True`, lié via `adjusts`, exposé par
   `InvoiceSerializer` (`adjusts`, `is_adjustment`, `adjustment_sign`,
   `adjustments_count`).
7. Endpoint : `POST /api/sales/invoices/{id}/adjust/`.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config, SystemNotification
from core.testing import make_node, make_user, make_bread_price, make_client
from clients.models import Client
from production.models import BreadStock, _adjust_bread_stock
from sales.models import Invoice
from commissions.models import CommissionPeriod, ClientCommission


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class InvoiceAdjustmentDecreaseTests(TestCase):
    """Ajustement négatif (diminution) : décision coordinateur points 1, 2, 4."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.gerant)

        # Facture d'origine livrée : 10 pains à 500 FC, versement intégral.
        create_payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '5000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 10}],
        }
        resp = self.api.post('/api/sales/invoices/', create_payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.original = Invoice.objects.get(pk=resp.data['id'])
        self.original.deliver(self.gerant)
        self.client_obj.refresh_from_db()

    def test_decrease_adjustment_creates_new_linked_invoice_without_mutating_original(self):
        original_order_total = self.original.order_total
        original_payment_amount = self.original.payment_amount
        original_lines_snapshot = [(l.bread_price_id, l.quantity) for l in self.original.lines.all()]

        payload = {
            'adjustment_sign': -1,
            'payment_amount': '1500.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 3}],
        }
        resp = self.api.post(f'/api/sales/invoices/{self.original.pk}/adjust/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        self.original.refresh_from_db()
        # « Grande trace » : la facture d'origine n'a JAMAIS été mutée.
        self.assertEqual(self.original.order_total, original_order_total)
        self.assertEqual(self.original.payment_amount, original_payment_amount)
        self.assertEqual(
            [(l.bread_price_id, l.quantity) for l in self.original.lines.all()],
            original_lines_snapshot,
        )

        adjustment = Invoice.objects.get(pk=resp.data['id'])
        self.assertTrue(adjustment.is_adjustment)
        self.assertEqual(adjustment.adjusts_id, self.original.pk)
        self.assertEqual(adjustment.adjustment_sign, -1)
        # Lignes de l'ajustement : magnitude positive (3), jamais -3.
        self.assertEqual(list(adjustment.lines.values_list('quantity', flat=True)), [3])
        # Signe appliqué au niveau de la facture entière.
        self.assertEqual(adjustment.order_total, Decimal('-1500.00'))   # -(3 * 500)
        self.assertEqual(adjustment.payment_amount, Decimal('-1500.00'))

    def test_decrease_adjustment_returns_bread_to_stock(self):
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        qty_sent_before = stock.qty_sent

        payload = {
            'adjustment_sign': -1,
            'payment_amount': '1500.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 3}],
        }
        resp = self.api.post(f'/api/sales/invoices/{self.original.pk}/adjust/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        stock.refresh_from_db()
        # Décision coordinateur point 2 : une diminution restitue le stock
        # (le pain revient) — qty_sent diminue de 3.
        self.assertEqual(stock.qty_sent, qty_sent_before - 3)

    def test_decrease_adjustment_recomputes_bp_with_standard_formula(self):
        debt_before_adjustment = self.client_obj.current_debt

        payload = {
            'adjustment_sign': -1,
            'payment_amount': '1500.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 3}],
        }
        resp = self.api.post(f'/api/sales/invoices/{self.original.pk}/adjust/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        adjustment = Invoice.objects.get(pk=resp.data['id'])
        self.client_obj.refresh_from_db()

        # BP_après = BP_avant + valeur_commande(-1500) - paiement(-1500) = BP_avant
        expected_debt_after = debt_before_adjustment + adjustment.order_total - adjustment.payment_amount
        self.assertEqual(adjustment.debt_before, debt_before_adjustment)
        self.assertEqual(adjustment.debt_after, expected_debt_after)
        self.assertEqual(self.client_obj.current_debt, expected_debt_after)

    def test_decrease_adjustment_cannot_exceed_remaining_quantity(self):
        """Impossible de retirer plus de pains que ce qui reste net sur la facture d'origine."""
        payload = {
            'adjustment_sign': -1,
            'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 11}],  # > 10 vendus
        }
        resp = self.api.post(f'/api/sales/invoices/{self.original.pk}/adjust/', payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('detail', resp.data)


class InvoiceAdjustmentIncreaseTests(TestCase):
    """Ajustement positif (augmentation) : décision coordinateur points 1, 2, 4."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.gerant)

        create_payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '5000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 10}],
        }
        resp = self.api.post('/api/sales/invoices/', create_payload, format='json')
        self.original = Invoice.objects.get(pk=resp.data['id'])
        self.original.deliver(self.gerant)
        self.client_obj.refresh_from_db()

    def test_increase_adjustment_decreases_stock_like_a_normal_sale(self):
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        qty_sent_before = stock.qty_sent

        payload = {
            'adjustment_sign': 1,
            'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post(f'/api/sales/invoices/{self.original.pk}/adjust/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        stock.refresh_from_db()
        self.assertEqual(stock.qty_sent, qty_sent_before + 2)

        adjustment = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(adjustment.order_total, Decimal('1000.00'))  # +(2 * 500)
        self.assertEqual(adjustment.payment_amount, Decimal('0.00'))
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('1000.00'))


class InvoiceAdjustmentCommissionLockedPeriodTests(TestCase):
    """Décision coordinateur point 3 : avertissement, jamais de blocage."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.gerant)

        create_payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '5000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 10}],
        }
        resp = self.api.post('/api/sales/invoices/', create_payload, format='json')
        self.original = Invoice.objects.get(pk=resp.data['id'])
        self.original.deliver(self.gerant)
        self.client_obj.refresh_from_db()

        self.period = CommissionPeriod.objects.create(
            node=self.node,
            month=self.original.invoice_date.month,
            year=self.original.invoice_date.year,
            is_closed=True,
        )

    def test_adjustment_on_closed_period_warns_but_never_blocks(self):
        SystemNotification.objects.all().delete()
        payload = {
            'adjustment_sign': -1,
            'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post(f'/api/sales/invoices/{self.original.pk}/adjust/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)  # jamais bloqué

        self.assertTrue(
            SystemNotification.objects.filter(title__icontains='période close').exists()
            or SystemNotification.objects.filter(message__icontains=self.original.receipt_number).exists()
        )


class InvoiceAdjustmentPermissionTests(TestCase):
    """Décision coordinateur point 5 : GERANT+ uniquement, jamais FACTURIER/LIVREUR."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.livreur = make_user('LIVREUR', node=self.node)
        self.client_obj = make_client(self.node)

        create_payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '5000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 10}],
        }
        resp = _api_for(self.gerant).post('/api/sales/invoices/', create_payload, format='json')
        self.original = Invoice.objects.get(pk=resp.data['id'])
        self.original.deliver(self.gerant)

    def _adjust_payload(self):
        return {
            'adjustment_sign': -1,
            'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }

    def test_facturier_forbidden(self):
        resp = _api_for(self.facturier).post(
            f'/api/sales/invoices/{self.original.pk}/adjust/', self._adjust_payload(), format='json'
        )
        self.assertEqual(resp.status_code, 403, resp.data)

    def test_livreur_forbidden(self):
        resp = _api_for(self.livreur).post(
            f'/api/sales/invoices/{self.original.pk}/adjust/', self._adjust_payload(), format='json'
        )
        self.assertEqual(resp.status_code, 403, resp.data)

    def test_gerant_allowed(self):
        resp = _api_for(self.gerant).post(
            f'/api/sales/invoices/{self.original.pk}/adjust/', self._adjust_payload(), format='json'
        )
        self.assertEqual(resp.status_code, 201, resp.data)


class InvoiceAdjustmentCannotTargetAdjustmentOrCancelledTests(TestCase):
    """Validation minimale (décision coordinateur point 7) : pas de chaîne d'ajustements, pas sur une facture annulée."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.gerant)

        create_payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '5000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 10}],
        }
        resp = self.api.post('/api/sales/invoices/', create_payload, format='json')
        self.original = Invoice.objects.get(pk=resp.data['id'])
        self.original.deliver(self.gerant)

    def test_cannot_adjust_an_adjustment(self):
        first_adjust_payload = {
            'adjustment_sign': -1,
            'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post(f'/api/sales/invoices/{self.original.pk}/adjust/', first_adjust_payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        adjustment_id = resp.data['id']

        resp2 = self.api.post(f'/api/sales/invoices/{adjustment_id}/adjust/', first_adjust_payload, format='json')
        self.assertEqual(resp2.status_code, 400, resp2.data)

    def test_cannot_adjust_cancelled_invoice(self):
        pending_payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', pending_payload, format='json')
        pending_invoice = Invoice.objects.get(pk=resp.data['id'])
        self.api.post(f'/api/sales/invoices/{pending_invoice.pk}/cancel/')

        resp2 = self.api.post(
            f'/api/sales/invoices/{pending_invoice.pk}/adjust/',
            {'adjustment_sign': -1, 'payment_amount': '0.00', 'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]},
            format='json',
        )
        self.assertEqual(resp2.status_code, 400, resp2.data)
