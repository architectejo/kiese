"""
BUG-197 (dev-backend, 2026-11-12) : numéro de reçu unique et cohérent
(préfixe = `invoice_date`, compteur sur ce même jour/nœud), y compris pour une
vente rétroactive suivie d'une vente du jour. Données fictives.
"""
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import get_config, make_bread_price, make_client, make_node, make_user
from sales.models import Invoice
from sales.views import _make_receipt_number

INV = '/api/sales/invoices/'
D = date(2026, 11, 12)
PREV = D - timedelta(days=1)


def _now(h, m=0, d=D):
    aware = timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())
    return patch('django.utils.timezone.now', return_value=aware.astimezone(dt_timezone.utc))


class ReceiptUniqueTests(TestCase):
    def setUp(self):
        self.node = make_node(code='V7')
        self.bp = make_bread_price('B197', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.cl = make_client(self.node)
        self.api = APIClient()
        self.api.force_authenticate(self.fact)
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()

    def _sale(self, **extra):
        p = {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': 500,
             'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}
        p.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.api.post(INV, p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return Invoice.objects.get(pk=r.data['id']).receipt_number

    def test_backdated_then_today_are_unique_and_prefix_follows_invoice_date(self):
        with _now(10):
            past = self._sale(invoice_date=str(PREV))
            today = self._sale()
            past2 = self._sale(invoice_date=str(PREV))
            today2 = self._sale()
        self.assertEqual(past, 'V7-20261111-0001')
        self.assertEqual(past2, 'V7-20261111-0002')
        self.assertEqual(today, 'V7-20261112-0001')
        self.assertEqual(today2, 'V7-20261112-0002')
        numbers = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_today_then_backdated_unique(self):
        with _now(10):
            today = self._sale()
            past = self._sale(invoice_date=str(PREV))
        self.assertEqual((today, past), ('V7-20261112-0001', 'V7-20261111-0001'))

    def test_legacy_duplicate_prefix_is_skipped(self):
        """Un numéro déjà émis (ancien préfixe incohérent) n'est jamais réutilisé."""
        with _now(10):
            Invoice.objects.create(
                node=self.node, client=self.cl, facturier=self.fact, team='A', payment_type='CASH',
                payment_amount=0, order_total=0, node_origin='V7',
                receipt_number='V7-20261112-0001', invoice_date=PREV)
            number = self._sale()
        self.assertEqual(number, 'V7-20261112-0002')

    def test_format_unchanged_and_default_date(self):
        with _now(10):
            self.assertEqual(_make_receipt_number('V7', D), 'V7-20261112-0001')
            self.assertEqual(_make_receipt_number('V7'), 'V7-20261112-0001')
