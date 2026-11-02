"""
Vérification BUG-116 (docs/qa/REGISTRE_BUGS.md) — reçu imprimable pour un
remboursement de dette / dépôt sans commande.

Le correctif est entièrement frontend (`Clients.tsx::handleRepaymentSubmit`,
`ThermalReceipt.tsx`) : il consomme la réponse JSON déjà renvoyée par
`POST /api/sales/invoices/` (`salesApi.createRepayment`, inchangé) pour
construire un `ReceiptData` et afficher `<ThermalReceipt>`. Ce test ne
touche à aucun code applicatif (CLAUDE.md §7.2) : il vérifie, côté API,
que :

1. Un seul appel réseau / une seule facture est créée par remboursement
   (pas de facture fantôme introduite par le correctif) ;
2. La réponse contient bien, avec les valeurs exactes attendues, tous les
   champs lus par `handleRepaymentSubmit` pour construire le reçu
   (`receipt_number`, `order_total`, `payment_amount`, `commission_rate`,
   `debt_before`, `debt_after`, `delivered_at`/`invoice_date`) — aussi bien
   pour un remboursement de dette classique (BP positive -> réduite) que
   pour un dépôt « client épargne » (BP qui devient négative, CLAUDE.md
   §5.1).
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


# Champs lus par Clients.tsx::handleRepaymentSubmit (BUG-116) pour construire
# le ReceiptData affiché par <ThermalReceipt>.
RECEIPT_FIELDS = [
    'receipt_number', 'order_total', 'payment_amount', 'commission_rate',
    'debt_before', 'debt_after', 'invoice_date', 'delivered_at',
]


class RepaymentReceiptDataTests(TestCase):
    """BUG-116 : la réponse serveur du remboursement porte tout ce qu'il faut pour le reçu."""

    def setUp(self):
        self.node = make_node(code='K1')
        make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.api = _api_for(self.facturier)

    def _repayment_payload(self, client_obj, amount):
        return {
            'client': str(client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': amount,
            'is_debt_repayment': True,
            'lines': [],
        }

    def test_classic_debt_repayment_response_has_exact_receipt_fields(self):
        """Dette 10 000 FC, remboursement partiel de 4 000 FC -> BP 6 000 FC."""
        client_obj = make_client(self.node, current_debt=Decimal('10000.00'))
        before_count = Invoice.objects.count()

        resp = self.api.post('/api/sales/invoices/', self._repayment_payload(client_obj, '4000.00'), format='json')

        self.assertEqual(resp.status_code, 201, resp.data)
        # Un seul appel réseau -> une seule facture créée (pas de doublon introduit par le correctif).
        self.assertEqual(Invoice.objects.count(), before_count + 1)

        for field in RECEIPT_FIELDS:
            self.assertIn(field, resp.data, f"Champ '{field}' absent de la réponse — le reçu ne pourrait pas s'afficher correctement.")

        self.assertTrue(resp.data['receipt_number'])
        self.assertEqual(Decimal(resp.data['order_total']), Decimal('0.00'))
        self.assertEqual(Decimal(resp.data['payment_amount']), Decimal('4000.00'))
        self.assertEqual(Decimal(resp.data['commission_rate']), Decimal('0.00'))
        self.assertEqual(Decimal(resp.data['debt_before']), Decimal('10000.00'))
        self.assertEqual(Decimal(resp.data['debt_after']), Decimal('6000.00'))
        self.assertTrue(resp.data['invoice_date'] or resp.data['delivered_at'])
        self.assertEqual(resp.data['lines'], [])
        self.assertTrue(resp.data['is_debt_repayment'])

        client_obj.refresh_from_db()
        self.assertEqual(client_obj.current_debt, Decimal('6000.00'))

    def test_savings_client_deposit_makes_bp_negative_and_receipt_fields_match(self):
        """Client épargne (BP initiale = 0) : dépôt de 5 000 FC sans commande -> BP = -5 000 FC."""
        client_obj = make_client(self.node, current_debt=Decimal('0.00'))
        before_count = Invoice.objects.count()

        resp = self.api.post('/api/sales/invoices/', self._repayment_payload(client_obj, '5000.00'), format='json')

        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Invoice.objects.count(), before_count + 1)

        self.assertEqual(Decimal(resp.data['debt_before']), Decimal('0.00'))
        self.assertEqual(Decimal(resp.data['debt_after']), Decimal('-5000.00'))
        self.assertEqual(Decimal(resp.data['payment_amount']), Decimal('5000.00'))
        self.assertEqual(Decimal(resp.data['order_total']), Decimal('0.00'))
        self.assertEqual(resp.data['lines'], [])

        client_obj.refresh_from_db()
        self.assertEqual(client_obj.current_debt, Decimal('-5000.00'))

    def test_repayment_does_not_create_a_second_invoice(self):
        """
        Garde-fou explicite demandé par la mission de vérification : le correctif
        frontend ne doit introduire aucun second appel `POST /api/sales/invoices/`.
        Un seul remboursement -> une seule facture, quel que soit le nombre de
        champs désormais lus côté client pour construire le reçu.
        """
        client_obj = make_client(self.node, current_debt=Decimal('2000.00'))
        resp = self.api.post('/api/sales/invoices/', self._repayment_payload(client_obj, '2000.00'), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        invoices = Invoice.objects.filter(client=client_obj, is_debt_repayment=True)
        self.assertEqual(invoices.count(), 1)
        self.assertEqual(invoices.first().receipt_number, resp.data['receipt_number'])
