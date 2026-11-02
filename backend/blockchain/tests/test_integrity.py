"""
BUG-001 (docs/qa/REGISTRE_BUGS.md) : avant la correction, `blockchain`
revérifiait avec une formule de hash différente de celle utilisée par
`treasury` à l'écriture, et en plus reconstruisait un chaînage local par
nœud alors que le Livre de Caisse Direction est une seule chaîne globale.
Résultat : une chaîne parfaitement saine était signalée falsifiée.

Ce test reproduit le scénario bout-en-bout attendu par le ticket : des
écritures créées via `treasury.views.append_cashbook_entry` doivent être
validées par `/api/blockchain/snapshots/run_check/`, sans fausse alerte, et
sans créer de `TamperAlert` ni d'écriture marquée `is_tampered`.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Node, User
from treasury.models import CashbookEntry
from treasury.views import append_cashbook_entry
from blockchain.models import TamperAlert, BlockchainSnapshot


class RunCheckIntegrationTests(TestCase):
    def setUp(self):
        self.node = Node.objects.create(code='K1', name='K1 - TABORA')
        self.node2 = Node.objects.create(code='K2', name='K2 - COQ')
        self.admin = User.objects.create_user(
            username='admin-test', password='x', role=User.Role.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _append(self, node, i):
        return append_cashbook_entry(
            node=node,
            date='2026-10-01',
            piece_number=f'VC-{node.code}-{i:03d}',
            imputation='7000',
            label=f'Versement {node.code} #{i}',
            entry_amount=Decimal('500.00'),
            exit_amount=Decimal('0.00'),
            node_origin=node.code,
        )

    def test_healthy_chain_across_two_nodes_is_not_flagged_as_tampered(self):
        for i in range(5):
            self._append(self.node, i)
        for i in range(3):
            self._append(self.node2, i)

        response = self.client.post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data['all_intact'], data)
        for node_result in data['results']:
            self.assertTrue(node_result['is_intact'], node_result)
            self.assertEqual(node_result['tampered_count'], 0)

        self.assertEqual(TamperAlert.objects.count(), 0)
        self.assertFalse(CashbookEntry.objects.filter(is_tampered=True).exists())
        self.assertEqual(BlockchainSnapshot.objects.filter(is_intact=False).count(), 0)

    def test_tampered_entry_is_flagged_and_raises_an_alert(self):
        entries = [self._append(self.node, i) for i in range(4)]
        CashbookEntry.objects.filter(pk=entries[2].pk).update(entry_amount=Decimal('777777.00'))

        response = self.client.post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertFalse(data['all_intact'])
        self.assertEqual(TamperAlert.objects.filter(is_resolved=False).count(), 1)
        self.assertTrue(CashbookEntry.objects.get(pk=entries[2].pk).is_tampered)
        self.assertTrue(CashbookEntry.objects.get(pk=entries[3].pk).is_tampered)
        self.assertFalse(CashbookEntry.objects.get(pk=entries[0].pk).is_tampered)
