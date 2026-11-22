"""BUG-516 : TamperAlert.node et BlockchainSnapshot.node en PROTECT.

Supprimer un noeud ne doit pas effacer les preuves d'integrite du livre de caisse.
"""
from django.db.models import ProtectedError
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Node, User
from blockchain.models import TamperAlert, BlockchainSnapshot


class NodeDeleteKeepsIntegrityProofs(TestCase):
    def setUp(self):
        self.node = Node.objects.create(code='K9', name='K9 TEST')
        self.admin = User.objects.create_user(username='adm516', password='x', role=User.Role.ADMIN)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.url = f'/api/core/nodes/{self.node.pk}/'

    def test_orm_delete_refused_with_alert(self):
        TamperAlert.objects.create(node=self.node, affected_model='CashbookEntry', description='x')
        with self.assertRaises(ProtectedError):
            self.node.delete()
        self.assertEqual(TamperAlert.objects.count(), 1)

    def test_orm_delete_refused_with_snapshot(self):
        BlockchainSnapshot.objects.create(node=self.node, snapshot_date='2026-11-01')
        with self.assertRaises(ProtectedError):
            self.node.delete()
        self.assertEqual(BlockchainSnapshot.objects.count(), 1)

    def test_api_delete_400_with_alert(self):
        TamperAlert.objects.create(node=self.node, affected_model='CashbookEntry', description='x')
        r = self.api.delete(self.url)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('Impossible', r.data['detail'])
        self.assertEqual(TamperAlert.objects.count(), 1)
        self.assertTrue(Node.objects.filter(pk=self.node.pk).exists())

    def test_api_delete_400_with_snapshot(self):
        BlockchainSnapshot.objects.create(node=self.node, snapshot_date='2026-11-01')
        r = self.api.delete(self.url)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(BlockchainSnapshot.objects.count(), 1)

    def test_empty_node_still_deletable(self):
        self.assertEqual(self.api.delete(self.url).status_code, 204)
