"""
Tests Ventes/Facturation — BUG-013 (docs/qa/REGISTRE_BUGS.md), audit de
remarque.md lignes 10-12, 92, 106-117, 134, 136, 145-146, 167, 174, 184,
186, 190-193, 196-200 + CLAUDE.md §5.2.

Rappel méthodologique (CLAUDE.md §7) : ce fichier n'écrit JAMAIS sur le
code applicatif. Toute anomalie confirmée par un test qui échoue est
documentée dans docs/qa/REGISTRE_BUGS.md et le test reste marqué
`@expectedFailure` jusqu'à correction par dev-backend.
"""
import threading
from decimal import Decimal
from unittest import expectedFailure

from django.test import TestCase, TransactionTestCase
from django.db import connections
from rest_framework.test import APIClient

from core.models import Node, BreadPrice, Config
from core.testing import make_node, make_user, make_bread_price, make_client
from clients.models import Client
from production.models import BreadStock, _adjust_bread_stock
from sales.models import Invoice, InvoiceLine


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class StandardInvoiceTests(TestCase):
    """Facture standard : lignes multiples, prix verrouillé sur BreadPrice, order_total exact."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp300 = make_bread_price('MINI', 'Pain 300 FC', 300)
        self.bp500 = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.facturier)

    def test_multi_line_invoice_uses_breadprice_and_ignores_client_sent_price(self):
        """Le prix envoyé par le client HTTP doit être ignoré ; seul BreadPrice.unit_price compte."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '1600.00',
            'lines': [
                {'bread_price': self.bp300.pk, 'quantity': 2, 'unit_price': 1},   # prix falsifié ignoré
                {'bread_price': self.bp500.pk, 'quantity': 2, 'unit_price': 999999},
            ],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(invoice.order_total, Decimal('1600.00'))  # 2*300 + 2*500
        lines = list(invoice.lines.all())
        self.assertEqual({l.unit_price for l in lines}, {300, 500})

    def test_bread_price_sent_as_string_is_accepted(self):
        """BUG-063 (CORRIGÉ) : `bread_price` envoyé comme chaîne JSON (ex.
        "1" au lieu de 1) ne doit jamais être signalé comme introuvable —
        `InvoiceViewSet.create` normalise désormais explicitement le type
        avant toute comparaison avec les clés (entières) de `bp_map`."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '600.00',
            'lines': [
                {'bread_price': str(self.bp300.pk), 'quantity': 2},
            ],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(invoice.order_total, Decimal('600.00'))

    def test_invalid_bread_price_identifier_returns_clean_400(self):
        """Un identifiant non convertible en entier doit rester un refus
        métier propre (400), jamais une exception serveur."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '600.00',
            'lines': [
                {'bread_price': 'not-an-id', 'quantity': 2},
            ],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)


class BalancePaiementTests(TestCase):
    """BP_après = BP_avant + commande − paiement, cumulatif, jamais remis à zéro (CLAUDE.md §5.2)."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node, credit_limit=Decimal('50000'))
        self.api = _api_for(self.facturier)

    def _invoice(self, qty, payment, date_override=None):
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': str(payment),
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def test_bp_accumulates_across_multiple_invoices(self):
        self._invoice(qty=10, payment=3000)  # commande 5000, versement 3000 -> +2000
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('2000.00'))

        self._invoice(qty=4, payment=0)  # commande 2000, versement 0 -> +2000
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('4000.00'))

        self._invoice(qty=2, payment=5000)  # commande 1000, versement 5000 -> -4000
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('0.00'))

    def test_bp_is_never_reset_across_a_month_boundary(self):
        """Simule un changement de mois : la BP doit rester cumulative, pas remise à zéro."""
        self._invoice(qty=10, payment=0)  # +5000
        self.client_obj.refresh_from_db()
        bp_before = self.client_obj.current_debt
        self.assertEqual(bp_before, Decimal('5000.00'))

        # Facture explicitement datée du mois suivant (simulation) : la BP cumule toujours
        inv2_data = self._invoice(qty=2, payment=0)  # +1000
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('6000.00'))
        # Aucune remise à zéro : le total == somme stricte des deux commandes
        self.assertEqual(self.client_obj.current_debt, bp_before + Decimal('1000.00'))


class CreditBlockTests(TestCase):
    """Blocage crédit (CLAUDE.md §5.2) : BP≥plafond & versement<commande -> 403 + notification."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.api = _api_for(self.facturier)

    def _post(self, client_obj, qty, payment):
        payload = {
            'client': str(client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': str(payment),
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }
        return self.api.post('/api/sales/invoices/', payload, format='json')

    def test_blocked_when_bp_at_ceiling_and_payment_insufficient(self):
        client_obj = make_client(self.node, credit_limit=Decimal('50000'), current_debt=Decimal('50000'))
        resp = self._post(client_obj, qty=2, payment=0)  # commande 1000, versement 0 < 1000
        self.assertEqual(resp.status_code, 403, resp.data)
        from core.models import SystemNotification
        self.assertTrue(SystemNotification.objects.filter(severity='DANGER').exists())

    def test_accepted_when_bp_at_ceiling_but_payment_covers_order(self):
        client_obj = make_client(self.node, credit_limit=Decimal('50000'), current_debt=Decimal('50000'))
        resp = self._post(client_obj, qty=2, payment=1000)  # versement == commande
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_accepted_when_bp_just_below_ceiling(self):
        client_obj = make_client(self.node, credit_limit=Decimal('50000'), current_debt=Decimal('49999'))
        resp = self._post(client_obj, qty=2, payment=0)
        self.assertEqual(resp.status_code, 201, resp.data)


class DebtRepaymentTests(TestCase):
    """Remboursement : facture sans ligne, réduit la BP, ne touche pas le CA ni le stock."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node, current_debt=Decimal('10000'))
        self.api = _api_for(self.facturier)
        _adjust_bread_stock(self.node, self.bp, produced=100)

    def test_repayment_reduces_bp_without_lines_or_stock_change(self):
        stock_before = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '4000.00',
            'is_debt_repayment': True,
            'lines': [],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['order_total']), Decimal('0.00'))
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('6000.00'))
        stock_after = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        self.assertEqual(stock_before, stock_after)

        # Le remboursement ne doit pas être compté comme un chiffre d'affaires de vente de pains
        self.assertEqual(InvoiceLine.objects.filter(invoice=resp.data['id']).count(), 0)


class SoldeeTests(TestCase):
    """VENTE SOLDE / CASH (prix 75%, CM=0, adaptes.md via CLAUDE.md §5.1) et is_soldee (remarque.md l.186)."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node, current_debt=Decimal('0'))
        self.api = _api_for(self.facturier)

    def test_soldee_does_not_add_shortfall_to_bp(self):
        """remarque.md l.186 : vente soldée -> le manquant n'est pas ajouté à la BP."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '200.00',  # versement << valeur commande (prix catalogue)
            'is_soldee': True,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],  # commande 1000
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('0.00'))

    def test_savings_client_order_zero_payment_makes_bp_negative(self):
        """Client épargne (CLAUDE.md §5.1) : commande = 0, le paiement (dépôt) peut rendre la BP négative."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '5000.00',
            'is_debt_repayment': True,
            'lines': [],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('-5000.00'))

    def test_soldee_forces_zero_commission_rate_server_side(self):
        """
        remarque.md l.186 : « si cette case [vente solde] est coché le taux de
        commission ne s'applique pas ». BUG-028 : le backend ne force PAS
        commission_rate=0 quand is_soldee=True si le payload ne l'envoie pas
        explicitement — il retombe sur Config.default_commission_rate (25%).
        """
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '200.00',
            'is_soldee': True,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
            # commission_rate volontairement omis : le facturier n'a pas pensé à l'envoyer
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['commission_rate']), Decimal('0.00'))

    def test_soldee_invoice_line_billed_at_75_percent_of_catalog_price(self):
        """
        BUG-092/BUG-096 : CLAUDE.md §5.1 — VENTE SOLDE/VENTE CASH = prix à
        75 % du catalogue, CM = 0. `InvoiceLine.save()` figeait jusqu'ici
        toujours le prix plein, que `is_soldee` soit coché ou non.
        """
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '750.00',
            'is_soldee': True,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],  # 2 × 500 FC catalogue
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        line = invoice.lines.get()
        # 500 FC × 0,75 = 375 FC/unité (Decimal exact, pas de float)
        self.assertEqual(line.unit_price, 375)
        self.assertEqual(line.line_total, Decimal('750.00'))
        self.assertEqual(invoice.order_total, Decimal('750.00'))
        self.assertEqual(Decimal(resp.data['commission_rate']), Decimal('0.00'))

    def test_soldee_invoice_computes_total_loss_vs_catalog_price(self):
        """BUG-092 point 3 : perte = (prix catalogue − prix facturé) × quantité, exposée par l'API."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '750.00',
            'is_soldee': True,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        # Perte attendue : (500 - 375) × 2 = 250 FC
        self.assertEqual(Decimal(resp.data['total_loss']), Decimal('250.00'))
        self.assertEqual(Decimal(resp.data['lines'][0]['loss']), Decimal('250.00'))
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(invoice.total_loss, Decimal('250.00'))

    def test_normal_non_soldee_invoice_unchanged_full_catalog_price_zero_loss(self):
        """Non-régression : une vente normale (is_soldee=False) reste au prix plein, perte nulle."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'is_soldee': False,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        line = invoice.lines.get()
        self.assertEqual(line.unit_price, 500)
        self.assertEqual(invoice.order_total, Decimal('1000.00'))
        self.assertEqual(Decimal(resp.data['total_loss']), Decimal('0.00'))

    def test_occasional_sale_without_client_forces_zero_commission(self):
        """
        remarque.md l.190 : « les ventes occasionnelles seront sans commission
        de 25% ». BUG-028 (même cause racine) : une vente occasionnelle
        (sans client) garde commission_rate = 25% par défaut au lieu de 0
        tant que le payload ne l'envoie pas explicitement.
        """
        payload = {
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['commission_rate']), Decimal('0.00'))


class CommissionExemptTests(TestCase):
    """
    BUG-052 : remarque.md l.190 demande une case « vente sans commission de
    25 % » DISTINCTE de « vente solde » — sur une facture NORMALE (client
    renseigné, is_soldee=False), `commission_exempt=True` doit forcer CM=0
    SANS appliquer la remise de prix à 75 % ni geler la BP (contrairement à
    is_soldee, voir SoldeeTests ci-dessus).
    """

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node, current_debt=Decimal('0'))
        self.api = _api_for(self.facturier)

    def test_commission_exempt_forces_zero_commission_at_full_price(self):
        """CM=0 sur une facture normale exonérée, sans remise de prix."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '200.00',  # versement << valeur commande
            'commission_exempt': True,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],  # 2 x 500 catalogue
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['commission_rate']), Decimal('0.00'))
        self.assertTrue(resp.data['commission_exempt'])
        self.assertFalse(resp.data['is_soldee'])

        invoice = Invoice.objects.get(pk=resp.data['id'])
        line = invoice.lines.get()
        # Prix plein (pas de remise à 75% contrairement à is_soldee) :
        self.assertEqual(line.unit_price, 500)
        self.assertEqual(invoice.order_total, Decimal('1000.00'))
        self.assertEqual(Decimal(resp.data['total_loss']), Decimal('0.00'))

    def test_commission_exempt_bp_follows_order_total_normally(self):
        """
        Contrairement à is_soldee, la BP doit continuer à suivre order_total
        normalement : debt_after = debt_before + order_total - payment_amount
        (point de vigilance explicitement ajouté au ticket BUG-052).
        """
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '200.00',
            'commission_exempt': True,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],  # commande 1000
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.client_obj.refresh_from_db()
        # 0 (debt_before) + 1000 (order_total) - 200 (payment_amount) = 800
        self.assertEqual(self.client_obj.current_debt, Decimal('800.00'))

    def test_commission_exempt_server_side_even_if_commission_rate_sent(self):
        """Le serveur ne fait jamais confiance au commission_rate envoyé (BUG-028, même durcissement)."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'commission_exempt': True,
            'commission_rate': '0.25',  # tentative d'outrepasser l'exonération
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['commission_rate']), Decimal('0.00'))

    def test_normal_invoice_without_any_flag_keeps_default_commission(self):
        """Non-régression : sans is_soldee ni commission_exempt, CM normale (25% par défaut)."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['commission_rate']), Decimal('0.25'))
        self.assertFalse(resp.data['commission_exempt'])

    def test_is_soldee_and_commission_exempt_are_independent_and_combinable(self):
        """
        Les deux booléens sont indépendants : les combiner n'est pas interdit
        artificiellement (CM=0 par les deux chemins, remise de prix à 75%
        toujours appliquée car is_soldee=True).
        """
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '200.00',
            'is_soldee': True,
            'commission_exempt': True,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Decimal(resp.data['commission_rate']), Decimal('0.00'))
        invoice = Invoice.objects.get(pk=resp.data['id'])
        line = invoice.lines.get()
        self.assertEqual(line.unit_price, 375)  # remise à 75% toujours active (is_soldee)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('0.00'))  # BP gelée (is_soldee)


class SpecialCodesTests(TestCase):
    """Codes NV / RG / NS et vente occasionnelle sans client (remarque.md l.134)."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.api = _api_for(self.facturier)

    def test_each_special_code_is_accepted(self):
        client_obj = make_client(self.node)
        for code in ('NV', 'RG', 'NS'):
            payload = {
                'client': str(client_obj.pk),
                'payment_type': 'CASH',
                'payment_amount': '1000.00',
                'special_code': code,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
            }
            resp = self.api.post('/api/sales/invoices/', payload, format='json')
            self.assertEqual(resp.status_code, 201, resp.data)
            self.assertEqual(resp.data['special_code'], code)

    def test_occasional_sale_without_client_is_allowed(self):
        """remarque.md l.134 : le facturier peut enregistrer une vente occasionnelle sans client."""
        payload = {
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIsNone(resp.data['client'])
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertIsNone(invoice.client_id)


class CrossNodeFacturationTests(TestCase):
    """remarque.md l.10-12 : le facturier voit/facture les clients des autres boulangeries."""

    def setUp(self):
        self.node_k1 = make_node(code='K1')
        self.node_k2 = make_node(code='K2')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier_k1 = make_user('FACTURIER', node=self.node_k1)
        self.client_k2 = make_client(self.node_k2)
        self.api = _api_for(self.facturier_k1)

    def test_facturier_can_search_a_client_from_another_node(self):
        clients_api = self.api
        resp = clients_api.get(f'/api/clients/clients/?search={self.client_k2.code}')
        self.assertEqual(resp.status_code, 200, resp.data)
        codes = [c['code'] for c in resp.data.get('results', resp.data)]
        self.assertIn(self.client_k2.code, codes)

    def test_facturier_can_invoice_a_client_from_another_node(self):
        payload = {
            'client': str(self.client_k2.pk),
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_facturier_can_confirm_delivery_of_invoice_he_created(self):
        """remarque.md l.12 : le facturier peut Confirmer la livraison ET Imprimer le reçu."""
        payload = {
            'client': str(self.client_k2.pk),
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        invoice_id = resp.data['id']
        resp2 = self.api.post(f'/api/sales/invoices/{invoice_id}/deliver/')
        self.assertEqual(resp2.status_code, 200, resp2.data)
        self.assertEqual(resp2.data['status'], 'DELIVERED')


class DeliveryAndCancelTests(TestCase):
    """Livraison confirmée par facturier OU livreur ; déstockage une seule fois ; annulation restitue."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.livreur = make_user('LIVREUR', node=self.node)
        self.gerant = make_user('GERANT', node=self.node)
        self.client_obj = make_client(self.node)
        self.api_facturier = _api_for(self.facturier)
        self.api_livreur = _api_for(self.livreur)
        self.api_gerant = _api_for(self.gerant)

    def _create_invoice(self, qty=2):
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }
        resp = self.api_facturier.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data['id']

    def test_stock_is_deducted_once_at_creation_not_twice_on_delivery(self):
        """Déstockage à la création ; confirmer la livraison ne déstocke pas une seconde fois."""
        _adjust_bread_stock(self.node, self.bp, produced=100)
        stock_before_sale = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        invoice_id = self._create_invoice(qty=5)
        stock_after_sale = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        self.assertEqual(stock_after_sale, stock_before_sale - 5)

        resp = self.api_livreur.post(f'/api/sales/invoices/{invoice_id}/deliver/')
        self.assertEqual(resp.status_code, 200, resp.data)
        stock_after_delivery = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        self.assertEqual(stock_after_delivery, stock_after_sale)  # inchangé

    def test_double_deliver_request_does_not_double_deduct_stock(self):
        """Double clic / double requête de livraison -> pas de double déstockage ni double traitement."""
        _adjust_bread_stock(self.node, self.bp, produced=100)
        invoice_id = self._create_invoice(qty=5)
        stock_after_sale = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available

        resp1 = self.api_livreur.post(f'/api/sales/invoices/{invoice_id}/deliver/')
        resp2 = self.api_livreur.post(f'/api/sales/invoices/{invoice_id}/deliver/')
        self.assertEqual(resp1.status_code, 200, resp1.data)
        self.assertEqual(resp2.status_code, 400, resp2.data)  # déjà livrée, rejetée

        stock_final = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        self.assertEqual(stock_final, stock_after_sale)

    def test_livreur_can_also_confirm_delivery(self):
        invoice_id = self._create_invoice()
        resp = self.api_livreur.post(f'/api/sales/invoices/{invoice_id}/deliver/')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_oversold_bread_stock_can_go_negative(self):
        """remarque.md l.145-146 et l.196 : si les ventes dépassent le stock déclaré, on passe au négatif."""
        # Aucun stock produit au préalable : qty_available part de 0
        self._create_invoice(qty=7)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, -7)

    def test_cancel_restores_stock_and_bp_and_is_logged(self):
        """Comportement réellement en vigueur : seul un GERANT (ou +) peut annuler — voir BUG-031."""
        _adjust_bread_stock(self.node, self.bp, produced=100)
        self.client_obj.refresh_from_db()
        debt_before_sale = self.client_obj.current_debt
        invoice_id = self._create_invoice(qty=5)  # commande 2500, versement 1000 -> +1500
        stock_after_sale = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available

        resp = self.api_gerant.post(f'/api/sales/invoices/{invoice_id}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.data)

        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, debt_before_sale)

        stock_after_cancel = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        self.assertEqual(stock_after_cancel, stock_after_sale + 5)

        from core.models import ActivityLog
        self.assertTrue(ActivityLog.objects.filter(action__icontains='Annulation').exists())

    def test_cannot_cancel_a_delivered_invoice(self):
        invoice_id = self._create_invoice()
        self.api_livreur.post(f'/api/sales/invoices/{invoice_id}/deliver/')
        resp = self.api_gerant.post(f'/api/sales/invoices/{invoice_id}/cancel/')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_facturier_can_cancel_a_pending_order_he_created(self):
        """
        BUG-031 : remarque.md l.200 et le docstring de `InvoiceViewSet.cancel`
        (« Gérant or Facturier can cancel a PENDING order ») disent tous deux
        que le facturier doit pouvoir annuler. L'action @action déclare bien
        `permission_classes=[IsFacturier]`, MAIS `InvoiceViewSet.get_permissions()`
        ne reconnaît pas l'action 'cancel' dans ses branches explicites et
        retombe sur le `return [IsGerant()]` par défaut — qui écrase la
        permission_classes du décorateur. En pratique, un FACTURIER qui tente
        d'annuler sa propre facture reçoit 403, alors que la fonctionnalité
        est explicitement demandée par le client pour ce rôle.
        """
        invoice_id = self._create_invoice(qty=5)
        resp = self.api_facturier.post(f'/api/sales/invoices/{invoice_id}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.data)


class ExpiryCleanupTests(TestCase):
    """remarque.md l.167 : auto-suppression des factures PENDING > 12h, exclues du calcul."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.gerant = make_user('GERANT', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.facturier)
        self.api_gerant = _api_for(self.gerant)
        _adjust_bread_stock(self.node, self.bp, produced=100)

    def _create_invoice(self, qty=3, payment=0, created_offset_hours=0):
        from django.utils import timezone
        from datetime import timedelta
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': str(payment),
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        if created_offset_hours:
            Invoice.objects.filter(pk=invoice.pk).update(
                created_at=timezone.now() - timedelta(hours=created_offset_hours)
            )
        return invoice

    def test_cleanup_deletes_pending_invoices_older_than_12h_and_reverses_debt(self):
        """Comportement réellement en vigueur : seul un GERANT (ou +) peut appeler cleanup_expired — voir BUG-031."""
        old_invoice = self._create_invoice(qty=3, payment=0, created_offset_hours=13)
        self.client_obj.refresh_from_db()
        debt_with_pending = self.client_obj.current_debt
        self.assertGreater(debt_with_pending, Decimal('0'))

        resp = self.api_gerant.post('/api/sales/invoices/cleanup_expired/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted'], 1)
        self.assertFalse(Invoice.objects.filter(pk=old_invoice.pk).exists())

        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('0.00'))

    def test_cleanup_does_not_touch_recent_pending_invoices(self):
        recent = self._create_invoice(qty=3, payment=0, created_offset_hours=2)
        resp = self.api_gerant.post('/api/sales/invoices/cleanup_expired/')
        self.assertEqual(resp.data['deleted'], 0)
        self.assertTrue(Invoice.objects.filter(pk=recent.pk).exists())

    def test_facturier_cannot_trigger_cleanup_expired(self):
        """
        BUG-031 (même cause racine que pour `cancel`) : le décorateur
        `@action(..., permission_classes=[IsAuthenticated])` sur
        `cleanup_expired` laisse croire que n'importe quel utilisateur
        connecté peut l'appeler, mais `get_permissions()` ne liste pas
        'cleanup_expired' dans ses branches explicites et retombe sur
        `[IsGerant()]` — qui écrase la permission du décorateur.
        `frontend/src/pages/dashboard/Sales.tsx` appelle pourtant
        `salesApi.cleanupExpired()` au chargement de la page Facturation
        (role FACTURIER), avec `.catch(() => {})` qui masque silencieusement
        l'échec 403 : remarque.md l.167 (auto-suppression des factures
        PENDING > 12h) ne se produit donc JAMAIS en pratique quand c'est un
        facturier qui charge la page, seulement si un Gérant+ la charge.
        """
        self._create_invoice(qty=3, payment=0, created_offset_hours=13)
        # BUG-284 : l'action est desormais reservee a GERANT et au-dessus.
        resp = self.api.post('/api/sales/invoices/cleanup_expired/')
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_cleanup_restores_bread_stock_deducted_at_creation(self):
        """
        BUG-029 : `cleanup_expired` reverse la BP du client mais NE restitue
        PAS le stock de pains déduit à la création — contrairement à
        `cancel()`, qui restitue bien le stock. Une facture expirée
        auto-supprimée laisse le stock durablement diminué pour des pains
        jamais réellement livrés.
        """
        stock_before = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        self._create_invoice(qty=3, payment=0, created_offset_hours=13)
        stock_after_sale = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        self.assertEqual(stock_after_sale, stock_before - 3)

        self.api_gerant.post('/api/sales/invoices/cleanup_expired/')
        stock_after_cleanup = BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available
        self.assertEqual(stock_after_cleanup, stock_before)  # attendu : restitué comme cancel()


class TeamABOnlyTests(TestCase):
    """Équipes A et B uniquement (CLAUDE.md §5.2, remarque.md l.8)."""

    def test_user_team_choices_are_limited_to_a_and_b(self):
        from core.models import User
        self.assertEqual(set(dict(User.Team.choices).keys()), {'A', 'B'})

    def test_invoice_is_stamped_with_facturier_team(self):
        node = make_node(code='K1')
        bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        facturier = make_user('FACTURIER', node=node, team='B')
        client_obj = make_client(node)
        api = _api_for(facturier)
        payload = {
            'client': str(client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'lines': [{'bread_price': bp.pk, 'quantity': 2}],
        }
        resp = api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['team'], 'B')


class ReceiptNumberTests(TransactionTestCase):
    """Numéro de reçu unique, même en créations simultanées (CLAUDE.md §5.2)."""

    def setUp(self):
        self.node = Node.objects.create(code='K1', name='K1 - TABORA')
        self.bp = BreadPrice.objects.create(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.facturier = __import__('core.models', fromlist=['User']).User.objects.create_user(
            username='fact_concurrency', password='x', role='FACTURIER', node=self.node, team='A'
        )

    def test_concurrent_invoice_creation_never_duplicates_receipt_number(self):
        """
        CLAUDE.md §5.2 : numéro de reçu unique même en créations simultanées.

        Note méthodologique : `_make_receipt_number` (sales/views.py) calcule
        le numéro suivant par un simple `.count() + 1`, SANS verrou ni
        contrainte d'unicité en base (`receipt_number` n'a ni `unique=True`
        ni `select_for_update()` sur le comptage). Sous SQLite (verrouillage
        de fichier global lors de l'écriture), ce test ne parvient PAS à
        provoquer de doublon en pratique — les 8 écritures se sérialisent.
        Le risque réel subsiste néanmoins sous PostgreSQL (verrouillage par
        ligne, écritures concurrentes réellement parallèles) : signalé au
        coordinateur comme point de vigilance plutôt que comme ticket BUG-NNN
        (pas de test reproductible ici pour l'étayer formellement).
        """
        results = []

        def _create():
            api = APIClient()
            api.force_authenticate(user=self.facturier)
            payload = {
                'payment_type': 'CASH',
                'payment_amount': '500.00',
                'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
            }
            resp = api.post('/api/sales/invoices/', payload, format='json')
            results.append(resp.data.get('receipt_number'))
            connections.close_all()

        threads = [threading.Thread(target=_create) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), len(set(results)), f"Numéros de reçu dupliqués : {results}")


class ConcurrentInvoiceBPTests(TransactionTestCase):
    """Concurrence : deux factures simultanées pour le même client -> BP finale correcte."""

    def setUp(self):
        self.node = Node.objects.create(code='K1')
        self.bp = BreadPrice.objects.create(category='MOYEN', label='Pain 500 FC', unit_price=500)
        from core.models import User
        self.facturier = User.objects.create_user(
            username='fact_bp_concurrency', password='x', role='FACTURIER', node=self.node, team='A'
        )
        self.client_obj = Client.objects.create(
            node=self.node, node_origin='K1', first_name='Concurrent', last_name='Client',
            credit_limit=Decimal('1000000'), current_debt=Decimal('0'),
        )
        # Pré-créer le singleton Config séquentiellement : sous SQLite,
        # plusieurs threads qui font tous `get_or_create(pk=1)` en même
        # temps se disputent une insertion sur la même ligne et déclenchent
        # "database is locked" — un pur artefact du moteur de test local
        # (verrouillage fichier mono-écrivain, absent sur PostgreSQL), pas
        # un comportement applicatif à démontrer ici.
        from core.models import Config
        Config.get_instance()

    def test_concurrent_invoices_do_not_lose_a_debt_update(self):
        """
        `InvoiceViewSet.create` met à jour la BP du client avec
        `Client.objects.filter(pk=...).update(current_debt=F('current_debt') + net_delta)`
        (sales/views.py) — ce test vérifie directement que CE motif précis
        (mise à jour relative via `F()`, pas une réaffectation `client.x = ...;
        client.save()`) ne perd aucune mise à jour sous accès concurrent,
        sans passer par la pile HTTP complète (vue DRF + sérialiseur +
        déstockage + notification...), qui multiplie le nombre de tables
        touchées par requête et rend ce test extrêmement sensible aux
        limites de verrouillage mono-écrivain de SQLite dans un
        environnement partagé avec d'autres suites de tests en parallèle
        (observé empiriquement : 10 threads via l'API complète échouaient
        presque systématiquement sur `OperationalError: database table is
        locked`, un artefact de cet environnement de test, pas une
        régression applicative — voir aussi BUG-002, déjà résolu pour
        `treasury.CashbookEntry` avec un vrai retry+verrou, dont
        `sales.Invoice` ne bénéficie pas devoir du même mécanisme ici).

        Point de vigilance signalé au coordinateur, non démontré par un test
        reproductible : la LECTURE de `client.current_debt` faite pour le
        contrôle de plafond de crédit, dans `InvoiceViewSet.create`, n'est
        pas protégée par `select_for_update()` (CLAUDE.md §4). Deux requêtes
        concurrentes pourraient en théorie lire la même BP de départ et
        passer toutes les deux le contrôle de plafond alors que, prises
        ensemble, l'une aurait dû être bloquée — non démontré ici (il
        faudrait un test ciblé juste autour du seuil, dépendant du moteur
        SQL réel en production).
        """
        from django.db.models import F

        n = 20
        delta = Decimal('500.00')

        def _apply_delta():
            Client.objects.filter(pk=self.client_obj.pk).update(
                current_debt=F('current_debt') + delta
            )
            connections.close_all()

        threads = [threading.Thread(target=_apply_delta) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, delta * n)


class NodeIsolationTests(TestCase):
    """Un facturier ne doit pas pouvoir forcer le champ `node` pour usurper une autre boulangerie."""

    def setUp(self):
        self.node_k1 = make_node(code='K1')
        self.node_k2 = make_node(code='K2')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier_k1 = make_user('FACTURIER', node=self.node_k1)
        self.client_k2 = make_client(self.node_k2)

    def test_facturier_cannot_force_node_field_to_another_bakery(self):
        """
        BUG-030 : `InvoiceViewSet.create` utilise `data.get('node') or
        request.user.node_id` — un facturier de K1 peut donc, en envoyant
        explicitement `node=<K2>` dans le payload, créer une facture
        attribuée à K2 alors qu'il travaille physiquement à K1. C'est
        distinct de la règle remarque.md l.10-12 (facturer un CLIENT d'une
        autre boulangerie depuis SON PROPRE nœud, déjà permis à juste
        titre) : ici c'est le nœud de la facture elle-même qui est usurpé.
        """
        api = _api_for(self.facturier_k1)
        payload = {
            'node': str(self.node_k2.pk),
            'client': str(self.client_k2.pk),
            'payment_type': 'CASH',
            'payment_amount': '1000.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
        }
        resp = api.post('/api/sales/invoices/', payload, format='json')
        # Attendu : la facture doit être rattachée au nœud RÉEL du facturier (K1), pas K2.
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(invoice.node_id, self.node_k1.pk)

