"""
BUG-056 — `ProductionSessionViewSet.perform_create`/`perform_update` ne
reprenaient pas le motif déjà appliqué ailleurs (BUG-022/025/030) : un GERANT
non-HQ pouvait forger `node` dans le payload pour déclarer ou modifier une
fournée rattachée à une autre boulangerie, avec impact réel sur le stock de
pains de la boulangerie usurpée (CLAUDE.md §4, §5.4).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import ProductionSession, BreadStock


class ForgedNodeOnProductionSessionTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='TK1', sac_value_fc=Decimal('200000'))
        self.k2 = make_node(code='TK2', sac_value_fc=Decimal('200000'))
        self.gerant_k1 = make_user(role='GERANT', node=self.k1)
        self.bp = make_bread_price(category='MOYEN', label='Pain Test 500 FC', unit_price=500)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.gerant_k1)

    def test_gerant_k1_cannot_declare_session_for_k2(self):
        """POST avec `node` forgé (K2) depuis un GERANT K1 : la session doit
        toujours être rattachée à K1, jamais à K2."""
        payload = {
            'team': 'A', 'date': '2026-10-05',
            'flour_sacks_used': '1',
            'node': str(self.k2.pk),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 200}],
        }
        resp = self.client_api.post('/api/production/sessions/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        session = ProductionSession.objects.get(pk=resp.data['id'])
        self.assertEqual(
            session.node_id, self.k1.pk,
            "FAILLE : GERANT K1 a déclaré une fournée rattachée à "
            f"{session.node.code} via un `node` forgé dans le payload."
        )
        # Impact réel sur le stock : le pain doit être crédité à K1, pas K2.
        stock_k1 = BreadStock.objects.filter(node=self.k1, bread_price=self.bp).first()
        stock_k2 = BreadStock.objects.filter(node=self.k2, bread_price=self.bp).first()
        self.assertIsNotNone(stock_k1)
        self.assertEqual(stock_k1.qty_produced, 200)
        self.assertTrue(stock_k2 is None or stock_k2.qty_produced == 0)

    def test_gerant_k1_cannot_move_existing_session_to_k2_on_update(self):
        """PATCH avec `node` forgé (K2) sur une session existante de K1 : elle
        doit rester rattachée à K1."""
        create_payload = {
            'team': 'B', 'date': '2026-10-06',
            'flour_sacks_used': '1',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 100}],
        }
        resp = self.client_api.post('/api/production/sessions/', create_payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        session_id = resp.data['id']

        patch_resp = self.client_api.patch(
            f'/api/production/sessions/{session_id}/',
            {'node': str(self.k2.pk), 'notes': 'Tentative de forgeage'},
            format='json',
        )
        self.assertEqual(patch_resp.status_code, 200, patch_resp.data)
        session = ProductionSession.objects.get(pk=session_id)
        self.assertEqual(
            session.node_id, self.k1.pk,
            "FAILLE : GERANT K1 a réaffecté une fournée existante à "
            f"{session.node.code} via un `node` forgé dans le payload d'édition."
        )
