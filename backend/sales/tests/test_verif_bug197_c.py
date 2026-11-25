"""
Vérification indépendante de BUG-197 (testeur-ventes, ronde C, 2026-11-21) :
numéro de reçu unique et préfixe = invoice_date, sur les 3 chemins de création
(vente, remboursement, ajustement), à la frontière de mois, entre nœuds.
Données fictives.
"""
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import get_config, make_bread_price, make_client, make_node, make_user
from sales.models import Invoice

INV = '/api/sales/invoices/'
D = date(2026, 12, 1)           # lendemain d'une fin de mois
EOM = date(2026, 11, 30)


def _now(h=13, d=D):
    aware = timezone.make_aware(datetime(d.year, d.month, d.day, h, 0), timezone.get_current_timezone())
    return patch('django.utils.timezone.now', return_value=aware.astimezone(dt_timezone.utc))


class VerifBug197C(TestCase):
    def setUp(self):
        self.n1 = make_node(code='V8')
        self.n2 = make_node(code='V9')
        self.bp = make_bread_price('C197', 'Pain 500 FC', 500)
        self.f1 = make_user('FACTURIER', node=self.n1, team='A')
        self.f2 = make_user('FACTURIER', node=self.n2, team='A')
        self.g1 = make_user('GERANT', node=self.n1)
        self.c1 = make_client(self.n1)
        self.c2 = make_client(self.n2)
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()

    def _api(self, u):
        a = APIClient()
        a.force_authenticate(u)
        return a

    def _post(self, user, client, **extra):
        p = {'client': str(client.pk), 'payment_type': 'CASH', 'payment_amount': 500,
             'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}
        p.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            r = self._api(user).post(INV, p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return Invoice.objects.get(pk=r.data['id'])

    def test_month_boundary_backdated_prefix_and_uniqueness(self):
        with _now():
            a = self._post(self.f1, self.c1, invoice_date=str(EOM))
            b = self._post(self.f1, self.c1)
            c = self._post(self.f1, self.c1, invoice_date=str(EOM))
        self.assertEqual(a.receipt_number, 'V8-20261130-0001')
        self.assertEqual(c.receipt_number, 'V8-20261130-0002')
        self.assertEqual(b.receipt_number, 'V8-20261201-0001')

    def test_refund_backdated_uses_invoice_date(self):
        with _now():
            self._post(self.f1, self.c1)  # vente du jour -> ...1201-0001
            r = self._post(self.f1, self.c1, invoice_date=str(EOM), lines=[], payment_amount=300,
                           is_debt_repayment=True)
            r2 = self._post(self.f1, self.c1, invoice_date=str(EOM), lines=[], payment_amount=200,
                            is_debt_repayment=True)
        self.assertTrue(r.is_debt_repayment)
        self.assertEqual(r.receipt_number, 'V8-20261130-0001')
        self.assertEqual(r2.receipt_number, 'V8-20261130-0002')

    def test_adjustment_backdated_unique(self):
        with _now():
            orig = self._post(self.f1, self.c1)
            orig.deliver(self.g1)
            self._post(self.f1, self.c1, invoice_date=str(EOM))  # V8-20261130-0001
            with self.captureOnCommitCallbacks(execute=True):
                r = self._api(self.g1).post(f'{INV}{orig.pk}/adjust/', {
                    'adjustment_sign': -1, 'payment_amount': '500.00',
                    'invoice_date': str(EOM),
                    'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        adj = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(adj.invoice_date, EOM)
        self.assertEqual(adj.receipt_number, 'V8-20261130-0002')
        nums = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(nums), len(set(nums)))

    def test_nodes_are_independent(self):
        with _now():
            a = self._post(self.f1, self.c1, invoice_date=str(EOM))
            b = self._post(self.f2, self.c2, invoice_date=str(EOM))
        self.assertEqual(a.receipt_number, 'V8-20261130-0001')
        self.assertEqual(b.receipt_number, 'V9-20261130-0001')

    def test_many_mixed_all_unique(self):
        with _now():
            for i in range(6):
                self._post(self.f1, self.c1, invoice_date=str(D - timedelta(days=i % 3)))
        nums = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(nums), 6)
        self.assertEqual(len(set(nums)), 6)
        for inv in Invoice.objects.all():
            self.assertTrue(inv.receipt_number.startswith(f"V8-{inv.invoice_date.strftime('%Y%m%d')}-"))
