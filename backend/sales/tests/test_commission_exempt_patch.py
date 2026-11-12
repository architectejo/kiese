"""
BUG-233 : régression de BUG-215 sur BUG-052 — PATCH de `commission_exempt`
réservé au GÉRANT et au-dessus ; liste blanche stricte ; PUT/DELETE -> 405.
Données fictives uniquement.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice

INV = '/api/sales/invoices/'


class CommissionExemptPatchTests(TestCase):
    def setUp(self):
        self.node = make_node(code='C1')
        self.other = make_node(code='C2')
        self.bp = make_bread_price('B200', 'Pain 500 FC', 500)
        self.cl = make_client(self.node)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.livreur = make_user('LIVREUR', node=self.node, team='A')
        self.gerant = make_user('GERANT', node=self.node)
        self.gerant_other = make_user('GERANT', node=self.other)
        self.direction = make_user('DIRECTION')
        self.inv = Invoice.objects.create(
            node=self.node, client=self.cl, facturier=self.fact, team='A',
            payment_type='CASH', payment_amount=500, debt_before=0,
            order_total=500, commission_rate='0.25', commission_exempt=False,
            node_origin=self.node.code, receipt_number='C1-CMX-001',
            status=Invoice.Status.DELIVERED,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _url(self):
        return f'{INV}{self.inv.pk}/'

    def test_gerant_peut_exonerer_et_cm_passe_a_zero(self):
        r = self._api(self.gerant).patch(self._url(), {'commission_exempt': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.inv.refresh_from_db()
        self.assertTrue(self.inv.commission_exempt)
        self.assertEqual(self.inv.commission_rate, Decimal('0.00'))
        self.assertEqual(self.inv.order_total, 500)
        self.assertEqual(self.inv.payment_amount, 500)

    def test_retour_a_non_exonere_restaure_le_taux_du_client(self):
        self.cl.commission_rate = Decimal('0.30')
        self.cl.save()
        api = self._api(self.gerant)
        api.patch(self._url(), {'commission_exempt': True}, format='json')
        r = api.patch(self._url(), {'commission_exempt': False}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.inv.refresh_from_db()
        self.assertFalse(self.inv.commission_exempt)
        self.assertEqual(self.inv.commission_rate, Decimal('0.30'))

    def test_direction_peut_patcher(self):
        r = self._api(self.direction).patch(self._url(), {'commission_exempt': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_facturier_et_livreur_refuses_403(self):
        for u in (self.fact, self.livreur):
            r = self._api(u).patch(self._url(), {'commission_exempt': True}, format='json')
            self.assertEqual(r.status_code, 403, u.role)
        self.inv.refresh_from_db()
        self.assertFalse(self.inv.commission_exempt)

    def test_gerant_d_une_autre_boulangerie_ne_voit_pas_la_facture(self):
        r = self._api(self.gerant_other).patch(self._url(), {'commission_exempt': True}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_champ_interdit_refuse_en_400_francais(self):
        for payload in (
            {'payment_amount': '1000'}, {'order_total': '1'}, {'status': 'CANCELLED'},
            {'client': str(self.cl.pk)}, {'commission_rate': '0.30'}, {'invoice_date': '2026-01-01'},
            {'lines': []},
            {'commission_exempt': True, 'payment_amount': '1000'},
        ):
            r = self._api(self.gerant).patch(self._url(), payload, format='json')
            self.assertEqual(r.status_code, 400, payload)
            self.assertIn('detail', r.data)
        self.inv.refresh_from_db()
        self.assertFalse(self.inv.commission_exempt)
        self.assertEqual(self.inv.payment_amount, 500)
        self.assertEqual(self.inv.commission_rate, Decimal('0.25'))
        self.assertEqual(self.inv.status, Invoice.Status.DELIVERED)

    def test_valeur_non_booleenne_refusee(self):
        r = self._api(self.gerant).patch(self._url(), {'commission_exempt': 'peut-etre'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_put_et_delete_restent_405(self):
        api = self._api(self.gerant)
        self.assertEqual(api.put(self._url(), {'commission_exempt': True}, format='json').status_code, 405)
        self.assertEqual(api.delete(self._url()).status_code, 405)
        self.assertTrue(Invoice.objects.filter(pk=self.inv.pk).exists())

    def test_facture_soldee_reste_a_cm_zero_apres_retour_non_exonere(self):
        Invoice.objects.filter(pk=self.inv.pk).update(is_soldee=True, commission_rate='0.00')
        r = self._api(self.gerant).patch(self._url(), {'commission_exempt': False}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.commission_rate, Decimal('0.00'))

    def test_facture_annulee_refusee(self):
        Invoice.objects.filter(pk=self.inv.pk).update(status=Invoice.Status.CANCELLED)
        r = self._api(self.gerant).patch(self._url(), {'commission_exempt': True}, format='json')
        self.assertEqual(r.status_code, 400)
