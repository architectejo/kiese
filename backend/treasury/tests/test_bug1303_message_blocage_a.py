"""BUG-1303 (décision client Q-020) : le message de blocage des ventes mentionne
« la direction ou le comptable ». Données fictives."""
import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_client, make_node, make_user
from treasury.closure_lock import closure_status

EXPECTED = ("Ventes bloquées : clôture du jour en attente de validation "
            "par la direction ou le comptable.")


class Bug1303MessageBlocage(TestCase):
    def setUp(self):
        self.node = make_node(code='MB1')
        self.node.block_sales_after_closure = True
        self.node.handover_time = dt.time(0, 0)
        self.node.save()
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='mb1_fa')
        self.bp = make_bread_price('MB3', 'Pain 300', 300)
        self.cl = make_client(self.node)

    def test_reason_closure_status(self):
        st = closure_status(self.node)
        self.assertTrue(st['blocked'])
        self.assertEqual(st['reason'], EXPECTED)

    def test_detail_403_creation_facture(self):
        c = APIClient()
        c.raise_request_exception = False
        c.force_authenticate(self.fa)
        r = c.post('/api/sales/invoices/', {
            'payment_type': 'CREDIT', 'payment_amount': 0, 'client': str(self.cl.pk),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertIn('direction ou le comptable', r.json()['detail'])
