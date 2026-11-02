"""
Vérification indépendante de BUG-056 (testeur-permissions, 2026-10-23).

Ne relit pas seulement le test de dev-backend
(`test_bug056_forged_node.py`) : tente activement l'exploitation avec un
GERANT du nœud K1 qui force `node=K2` dans le payload, en création (POST),
en édition complète (PUT) et en édition partielle (PATCH), et vérifie
l'effet réel sur `BreadStock` ainsi que l'isolation en lecture
(liste/détail) de la session créée.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import ProductionSession, BreadStock


class Bug056IndependentVerificationTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='VK1', sac_value_fc=Decimal('200000'))
        self.k2 = make_node(code='VK2', sac_value_fc=Decimal('200000'))
        self.gerant_k1 = make_user(role='GERANT', node=self.k1)
        self.bp = make_bread_price(category='MOYEN', label='Pain Vérif 500 FC', unit_price=500)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.gerant_k1)

    def test_post_with_forged_node_k2_stays_on_k1_and_is_not_visible_to_k2(self):
        """GERANT K1 force node=K2 à la création : la session et le stock de
        pains doivent rester sur K1, et la session ne doit jamais apparaître
        dans une liste filtrée (en pratique) sur K2."""
        payload = {
            'team': 'A', 'date': '2026-10-07',
            'flour_sacks_used': '2',
            'node': str(self.k2.pk),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 400}],
        }
        resp = self.client_api.post('/api/production/sessions/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        session = ProductionSession.objects.get(pk=resp.data['id'])
        self.assertEqual(
            session.node_id, self.k1.pk,
            f"EXPLOIT RÉUSSI : node forgé K2 a été accepté, session rattachée à {session.node.code}."
        )

        stock_k1 = BreadStock.objects.filter(node=self.k1, bread_price=self.bp).first()
        stock_k2 = BreadStock.objects.filter(node=self.k2, bread_price=self.bp).first()
        self.assertIsNotNone(stock_k1, "Le stock devrait avoir été crédité sur K1.")
        self.assertEqual(stock_k1.qty_produced, 400)
        self.assertTrue(
            stock_k2 is None or stock_k2.qty_produced == 0,
            "FUITE : du stock a été crédité sur K2 via le node forgé."
        )

        # L'API elle-même répond avec le node réel (K1), jamais celui forgé.
        self.assertEqual(str(resp.data.get('node')), str(self.k1.pk))

    def test_put_full_update_with_forged_node_k2_does_not_move_session(self):
        """Édition complète (PUT, pas seulement PATCH) avec node=K2 forgé :
        la session existante de K1 doit rester sur K1."""
        create_payload = {
            'team': 'B', 'date': '2026-10-08',
            'flour_sacks_used': '1',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 150}],
        }
        resp = self.client_api.post('/api/production/sessions/', create_payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        session_id = resp.data['id']

        put_payload = {
            'team': 'B', 'date': '2026-10-08',
            'flour_sacks_used': '1',
            'node': str(self.k2.pk),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 150}],
        }
        put_resp = self.client_api.put(
            f'/api/production/sessions/{session_id}/', put_payload, format='json'
        )
        self.assertEqual(put_resp.status_code, 200, put_resp.data)
        session = ProductionSession.objects.get(pk=session_id)
        self.assertEqual(
            session.node_id, self.k1.pk,
            f"EXPLOIT RÉUSSI via PUT : session réaffectée à {session.node.code}."
        )

    def test_gerant_k2_cannot_see_or_reach_k1_session_by_known_uuid(self):
        """Isolation en lecture : un GERANT K2 ne doit ni voir la session de
        K1 en liste, ni y accéder en détail en connaissant son UUID."""
        create_payload = {
            'team': 'A', 'date': '2026-10-09',
            'flour_sacks_used': '1',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 50}],
        }
        resp = self.client_api.post('/api/production/sessions/', create_payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        session_id = resp.data['id']

        gerant_k2 = make_user(role='GERANT', node=self.k2)
        client_k2 = APIClient()
        client_k2.force_authenticate(gerant_k2)

        list_resp = client_k2.get('/api/production/sessions/')
        self.assertEqual(list_resp.status_code, 200, list_resp.data)
        ids = [str(item['id']) for item in list_resp.data.get('results', list_resp.data)]
        self.assertNotIn(
            str(session_id), ids,
            "FUITE : la session de K1 apparaît dans la liste d'un GERANT K2."
        )

        detail_resp = client_k2.get(f'/api/production/sessions/{session_id}/')
        self.assertIn(
            detail_resp.status_code, (403, 404),
            "FUITE : un GERANT K2 a pu accéder en détail à une session de K1 "
            f"via son UUID (status {detail_resp.status_code})."
        )

    def test_patch_to_remove_node_from_payload_entirely_still_safe(self):
        """Sanity check : une édition normale (sans tenter de node) continue
        de fonctionner et de rester sur K1 (non-régression fonctionnelle)."""
        create_payload = {
            'team': 'B', 'date': '2026-10-10',
            'flour_sacks_used': '1',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 80}],
        }
        resp = self.client_api.post('/api/production/sessions/', create_payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        session_id = resp.data['id']

        patch_resp = self.client_api.patch(
            f'/api/production/sessions/{session_id}/',
            {'notes': 'Édition normale sans node'},
            format='json',
        )
        self.assertEqual(patch_resp.status_code, 200, patch_resp.data)
        session = ProductionSession.objects.get(pk=session_id)
        self.assertEqual(session.node_id, self.k1.pk)
