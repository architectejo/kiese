"""
BUG-093 (docs/qa/REGISTRE_BUGS.md), remarque.md section Clôture point 2 :
clôture d'une fournée avec recoupement automatique (ventes + dispositions du
jour), reliquat NV calculé par soustraction, et écart final figé — la saisie
manuelle (sacs de farine + total pains par catégorie) est conservée, le reste
devient automatique.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import ProductionSession, BreadDisposal


class ProductionSessionCloseTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.user = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def _declare(self, qty, date='2026-10-10', team='A'):
        resp = self.client_api.post('/api/production/sessions/', {
            'team': team, 'date': date, 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def test_close_computes_automatic_recoupement_and_marks_session_closed(self):
        """
        200 pains produits (100 000 FC), 120 vendus (facture livrée,
        60 000 FC), 30 déclassés (DECLASSED, 0 FC) : reliquat NV attendu =
        200 - 120 - 30 = 50 pains. La session doit être figée (`is_closed`)
        avec `closed_at` renseigné et le détail du recoupement exposé.
        """
        from sales.models import Invoice

        session_data = self._declare(qty=200)
        session_id = session_data['id']

        client_obj = make_client(self.node)
        facturier = make_user('FACTURIER', node=self.node)
        sales_api = APIClient()
        sales_api.force_authenticate(facturier)

        invoice_resp = sales_api.post('/api/sales/invoices/', {
            'client': str(client_obj.pk), 'payment_type': 'CASH', 'payment_amount': '60000',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 120}],
        }, format='json')
        self.assertEqual(invoice_resp.status_code, 201, invoice_resp.data)
        invoice = Invoice.objects.get(pk=invoice_resp.data['id'])
        invoice.invoice_date = session_data['date']
        invoice.save(update_fields=['invoice_date'])
        deliver_resp = sales_api.post(f'/api/sales/invoices/{invoice.pk}/deliver/')
        self.assertEqual(deliver_resp.status_code, 200, deliver_resp.data)

        disposal_resp = self.client_api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': self.bp.pk,
            'disposal_type': 'DECLASSED', 'quantity': 30, 'unit_price_sold': 0,
        }, format='json')
        self.assertEqual(disposal_resp.status_code, 201, disposal_resp.data)

        close_resp = self.client_api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)
        self.assertTrue(close_resp.data['is_closed'])
        self.assertIsNotNone(close_resp.data['closed_at'])

        summary = close_resp.data['closure_summary']
        self.assertEqual(summary['production_declared']['breads'], 200)
        self.assertEqual(summary['sales']['breads'], 120)
        self.assertEqual(summary['returns']['breads'], 30)
        self.assertEqual(summary['gap']['breads'], 50)
        self.assertEqual(summary['nv']['breads'], 50)
        self.assertFalse(summary['anomaly'])

        session = ProductionSession.objects.get(pk=session_id)
        self.assertTrue(session.is_closed)
        self.assertIsNotNone(session.closed_at)
        self.assertEqual(session.closure_summary['nv']['breads'], 50)

    def test_closed_session_cannot_be_modified(self):
        session_data = self._declare(qty=200)
        session_id = session_data['id']
        close_resp = self.client_api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)

        patch_resp = self.client_api.patch(
            f'/api/production/sessions/{session_id}/', {'notes': 'Tentative après clôture'},
            format='json',
        )
        self.assertEqual(patch_resp.status_code, 400, patch_resp.data)

    def test_double_close_is_rejected(self):
        session_data = self._declare(qty=200)
        session_id = session_data['id']
        first = self.client_api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(first.status_code, 200, first.data)
        second = self.client_api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(second.status_code, 400, second.data)

    def test_negative_reliquat_is_reported_as_anomaly_without_blocking_closure(self):
        """
        Anomalie : plus de pains disposés que produits déclarés. La clôture
        doit tout de même réussir (on signale, on ne bloque pas) et une
        notification DANGER doit être créée.
        """
        session_data = self._declare(qty=50)
        session_id = session_data['id']

        disposal_resp = self.client_api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': self.bp.pk,
            'disposal_type': 'UNSOLD', 'quantity': 80, 'unit_price_sold': 0,
        }, format='json')
        self.assertEqual(disposal_resp.status_code, 201, disposal_resp.data)

        close_resp = self.client_api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)
        summary = close_resp.data['closure_summary']
        self.assertEqual(summary['gap']['breads'], 50 - 80)
        self.assertTrue(summary['anomaly'])
        self.assertEqual(summary['nv']['breads'], 0)

        self.assertTrue(
            SystemNotification.objects.filter(
                severity='DANGER', node_origin=self.node.code,
            ).exists()
        )

    def test_reconciliation_action_remains_read_only_and_available_after_close(self):
        """Non-régression : `reconciliation` reste consultable après clôture."""
        session_data = self._declare(qty=200)
        session_id = session_data['id']
        close_resp = self.client_api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)

        recon_resp = self.client_api.get('/api/production/sessions/reconciliation/', {
            'node': self.node.pk, 'date': session_data['date'],
        })
        self.assertEqual(recon_resp.status_code, 200, recon_resp.data)
        self.assertEqual(recon_resp.data['production_declared']['breads'], 200)
        self.assertEqual(recon_resp.data['gap']['breads'], 200)

        # La session clôturée reste par ailleurs lisible normalement.
        detail_resp = self.client_api.get(f'/api/production/sessions/{session_id}/')
        self.assertEqual(detail_resp.status_code, 200, detail_resp.data)
        self.assertTrue(detail_resp.data['is_closed'])
