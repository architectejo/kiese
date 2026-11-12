"""
BUG-177 (volet backend) : factures « Non Servi » (NS) et « Régularisation »
(RG) — effets sur stock, dette, livraison, purge et annulation.

Décisions (docs/qa/REGISTRE_BUGS.md, BUG-177) : une NS ne déduit JAMAIS de
stock ; CREDIT = dette `order_total - paiement`, CASH = aucune dette ; pas de
contrôle de plafond ; CM 0 ; `deliver` refusé ; exemptée de `cleanup_expired`.
Une RG : CM 0, ni paiement ni dette, livraison normale.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import BreadStock
from sales.models import Invoice


class NsRgInvoiceTests(TestCase):
    def setUp(self):
        self.node = make_node()
        self.bp = make_bread_price('BUG177_500', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.gerant = make_user('GERANT', node=self.node)
        self.client_obj = make_client(self.node, credit_limit=Decimal('50000.00'))
        self.api = APIClient()
        self.api.force_authenticate(self.facturier)
        self.gerant_api = APIClient()
        self.gerant_api.force_authenticate(self.gerant)

    def _post(self, code, payment_type, payment='0.00', qty=4, client=True, api=None):
        payload = {
            'payment_type': payment_type, 'payment_amount': payment,
            'special_code': code,
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }
        if client:
            payload['client'] = str(self.client_obj.pk)
        return (api or self.api).post('/api/sales/invoices/', payload, format='json')

    def _sent(self):
        return sum(BreadStock.objects.filter(node=self.node, bread_price=self.bp).values_list('qty_sent', flat=True))

    def _debt(self):
        self.client_obj.refresh_from_db()
        return self.client_obj.current_debt

    def test_ns_cash_no_debt_no_destock(self):
        resp = self._post('NS', 'CASH', payment='700.00')
        self.assertEqual(resp.status_code, 201, resp.data)
        inv = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(inv.order_total, Decimal('2000.00'))
        self.assertEqual(inv.status, Invoice.Status.PENDING)
        self.assertEqual(inv.payment_amount, Decimal('0.00'))
        self.assertEqual(inv.commission_rate, Decimal('0.00'))
        self.assertEqual(inv.debt_after, inv.debt_before)
        self.assertEqual(self._debt(), Decimal('0.00'))
        self.assertEqual(self._sent(), 0)

    def test_ns_credit_records_debt_without_destock(self):
        resp = self._post('NS', 'CREDIT', payment='500.00')
        self.assertEqual(resp.status_code, 201, resp.data)
        inv = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(inv.debt_after, Decimal('1500.00'))
        self.assertEqual(self._debt(), Decimal('1500.00'))
        self.assertEqual(self._sent(), 0)
        self.assertEqual(inv.commission_rate, Decimal('0.00'))

    def test_ns_ignores_credit_ceiling(self):
        Client.objects.filter(pk=self.client_obj.pk).update(current_debt=Decimal('60000.00'))
        resp = self._post('NS', 'CREDIT', payment='0.00')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(self._debt(), Decimal('62000.00'))
        # Contrôle : une vente normale dans la même situation reste bloquée.
        blocked = self._post('', 'CREDIT', payment='0.00')
        self.assertEqual(blocked.status_code, 403)

    def test_deliver_ns_is_refused(self):
        inv_id = self._post('NS', 'CASH').data['id']
        for api in (self.api, self.gerant_api):
            resp = api.post(f'/api/sales/invoices/{inv_id}/deliver/')
            self.assertEqual(resp.status_code, 400)
            self.assertIn('Non Servi', resp.data['detail'])
        self.assertEqual(Invoice.objects.get(pk=inv_id).status, Invoice.Status.PENDING)

    def test_cleanup_expired_spares_ns_but_purges_normal(self):
        ns_id = self._post('NS', 'CREDIT', payment='0.00').data['id']
        normal_id = self._post('', 'CASH', payment='2000.00').data['id']
        old = timezone.now() - timedelta(hours=13)
        Invoice.objects.filter(pk__in=[ns_id, normal_id]).update(created_at=old)
        resp = self.gerant_api.post('/api/sales/invoices/cleanup_expired/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted'], 1)
        self.assertTrue(Invoice.objects.filter(pk=ns_id).exists())
        self.assertFalse(Invoice.objects.filter(pk=normal_id).exists())
        self.assertEqual(self._debt(), Decimal('2000.00'))  # dette NS conservée

    def test_cancel_ns_credit_cancels_debt_and_does_not_restore_stock(self):
        inv_id = self._post('NS', 'CREDIT', payment='0.00').data['id']
        self.assertEqual(self._debt(), Decimal('2000.00'))
        resp = self.api.post(f'/api/sales/invoices/{inv_id}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self._debt(), Decimal('0.00'))
        self.assertEqual(self._sent(), 0)  # pas de stock « rendu » en négatif

    def test_cancel_ns_cash_leaves_debt_untouched(self):
        inv_id = self._post('NS', 'CASH').data['id']
        self.api.post(f'/api/sales/invoices/{inv_id}/cancel/')
        self.assertEqual(self._debt(), Decimal('0.00'))
        self.assertEqual(self._sent(), 0)

    def test_ns_not_in_pending_deliveries(self):
        self._post('NS', 'CASH')
        normal_id = self._post('', 'CASH', payment='2000.00').data['id']
        resp = self.api.get('/api/sales/invoices/pending_deliveries/')
        self.assertEqual([r['id'] for r in resp.data], [normal_id])

    def test_rg_no_debt_cm_zero_and_normal_delivery(self):
        resp = self._post('RG', 'CREDIT', payment='0.00')
        self.assertEqual(resp.status_code, 201, resp.data)
        inv = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(inv.commission_rate, Decimal('0.00'))
        self.assertEqual(inv.debt_after, inv.debt_before)
        self.assertEqual(self._debt(), Decimal('0.00'))
        self.assertEqual(self._sent(), 4)  # livraison réelle : stock déduit
        dres = self.api.post(f'/api/sales/invoices/{inv.pk}/deliver/')
        self.assertEqual(dres.status_code, 200, dres.data)
        self.assertEqual(Invoice.objects.get(pk=inv.pk).status, Invoice.Status.DELIVERED)

    def test_rg_cancel_does_not_touch_debt(self):
        inv_id = self._post('RG', 'CREDIT').data['id']
        self.api.post(f'/api/sales/invoices/{inv_id}/cancel/')
        self.assertEqual(self._debt(), Decimal('0.00'))
        self.assertEqual(self._sent(), 0)  # +4 puis -4
