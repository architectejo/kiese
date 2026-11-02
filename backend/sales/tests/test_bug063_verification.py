"""
Vérification indépendante de BUG-063 (docs/qa/REGISTRE_BUGS.md).

Testeur-ventes (vérification indépendante, 2026-10-23) — ne modifie jamais
le code applicatif (CLAUDE.md §7). Reproduit le cas exact du bug original
(`bread_price` envoyé comme chaîne JSON depuis le frontend, y compris sur
plusieurs lignes à la fois, ex. ["3", "7"] au lieu de [3, 7]) et confirme
qu'un identifiant non numérique reste correctement rejeté (400 propre,
jamais une exception serveur).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class Bug063IndependentVerificationTests(TestCase):
    """BUG-063 (CORRIGÉ) : comparaison de types str/int sur bp_ids."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp_a = make_bread_price('MINI', 'Pain 300 FC', 300)
        self.bp_b = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.facturier)

    def test_multiple_bread_price_ids_sent_as_strings_are_all_accepted(self):
        """Cas exact du bug original : plusieurs lignes, chaque `bread_price`
        envoyé comme chaîne JSON (ex. ["3", "7"] plutôt que [3, 7]) — aucune
        ligne ne doit être signalée à tort comme BreadPrice introuvable."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '1600.00',
            'lines': [
                {'bread_price': str(self.bp_a.pk), 'quantity': 2},
                {'bread_price': str(self.bp_b.pk), 'quantity': 2},
            ],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(invoice.order_total, Decimal('1600.00'))
        self.assertEqual(
            {l.bread_price_id for l in invoice.lines.all()},
            {self.bp_a.pk, self.bp_b.pk},
        )

    def test_nonexistent_bread_price_id_sent_as_string_is_still_rejected(self):
        """Un identifiant inexistant envoyé comme chaîne doit toujours être
        refusé (400) — la normalisation de type ne doit pas masquer un vrai
        BreadPrice introuvable."""
        bogus_pk = self.bp_a.pk + self.bp_b.pk + 9999
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '300.00',
            'lines': [
                {'bread_price': str(bogus_pk), 'quantity': 1},
            ],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_non_numeric_bread_price_identifier_is_rejected_cleanly(self):
        """Cas limite : identifiant non numérique (ni int ni chaîne numérique)
        doit rester un refus métier propre (400), jamais une exception
        serveur (500) ni un faux succès."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '300.00',
            'lines': [
                {'bread_price': 'abc', 'quantity': 1},
            ],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_float_like_string_identifier_is_rejected_cleanly(self):
        """Cas limite supplémentaire : chaîne numérique flottante (ex. "1.5")
        n'est pas un identifiant valide — doit rester un 400 propre plutôt
        qu'une exception serveur (int("1.5") lève ValueError)."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '300.00',
            'lines': [
                {'bread_price': '1.5', 'quantity': 1},
            ],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
