"""BUG-564 : le code du nœud technique SIEGE est protégé (pas de renommage puis suppression)."""
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Node, User


class SiegeCodeProtege(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('s_admin', password='x', role='ADMIN')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siège'})[0]

    def test_patch_code_siege_refuse(self):
        r = self.api.patch(f'/api/core/nodes/{self.siege.pk}/', {'code': 'X1'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('SIEGE', str(r.json()['detail']))
        self.siege.refresh_from_db()
        self.assertEqual(self.siege.code, 'SIEGE')

    def test_put_code_siege_refuse(self):
        r = self.api.put(f'/api/core/nodes/{self.siege.pk}/',
                         {'code': 'X1', 'name': 'Siège'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.siege.refresh_from_db()
        self.assertEqual(self.siege.code, 'SIEGE')

    def test_renommer_autre_noeud_en_siege_refuse(self):
        n = Node.objects.create(code='K8', name='TEST')
        r = self.api.patch(f'/api/core/nodes/{n.pk}/', {'code': 'SIEGE'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        n.refresh_from_db()
        self.assertEqual(n.code, 'K8')

    def test_autre_champ_du_siege_modifiable(self):
        r = self.api.patch(f'/api/core/nodes/{self.siege.pk}/', {'name': 'Siège central'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_renommage_noeud_ordinaire_ok(self):
        n = Node.objects.create(code='K8', name='TEST')
        r = self.api.patch(f'/api/core/nodes/{n.pk}/', {'code': 'K9'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_siege_reste_non_supprimable(self):
        self.api.patch(f'/api/core/nodes/{self.siege.pk}/', {'code': 'X1'}, format='json')
        r = self.api.delete(f'/api/core/nodes/{self.siege.pk}/')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertTrue(Node.objects.filter(pk=self.siege.pk).exists())
