"""
BUG-146 : une sortie (EXIT) de consommable qui arrive au Cloud avant son
entrée (ENTRY) est valorisée au CUMP courant (0 sur une ligne créée
paresseusement). Une fois l'entrée arrivée, `unit_price` de la sortie doit
être ré-estampillé au CUMP, de façon idempotente et atomique.
"""
import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node
from production.models import ConsumableMovement, ConsumableStock
from sync.models import NodeAuthToken, SyncConflictLog
from sync.services import _restamp_orphan_exits

LABEL = 'production.ConsumableMovement'


class ExitBeforeEntryRestampTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        _, raw = NodeAuthToken.issue_for_node(self.node)
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')

    def _push(self, record_id, mtype, qty, price='0'):
        resp = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {LABEL: [{
                'id': record_id, 'node': 'K1', 'consumable_type': 'FLOUR', 'unit': 'sacs',
                'movement_type': mtype, 'quantity': qty, 'unit_price': price,
                'node_origin': 'K1',
            }]},
        }, format='json')
        self.assertEqual(resp.data['results'][LABEL][0]['status'], 'ACCEPTED')

    def test_exit_restamped_at_cump_once_entry_arrives(self):
        exit_id, entry_id = str(uuid.uuid4()), str(uuid.uuid4())
        self._push(exit_id, 'EXIT', '5.000')
        self.assertEqual(ConsumableMovement.objects.get(pk=exit_id).unit_price, Decimal('0.00'))
        self._push(entry_id, 'ENTRY', '10.000', '100000.00')

        mv = ConsumableMovement.objects.get(pk=exit_id)
        self.assertEqual(mv.unit_price, Decimal('100000.00'))
        stock = ConsumableStock.objects.get(node=self.node, consumable_type='FLOUR')
        self.assertEqual(stock.quantity, Decimal('5.000'))  # pas de double décrément
        marker = SyncConflictLog.objects.get(object_id=exit_id)
        self.assertTrue(marker.is_resolved)

    def test_restamp_is_idempotent_and_replay_creates_no_duplicate(self):
        exit_id, entry_id = str(uuid.uuid4()), str(uuid.uuid4())
        self._push(exit_id, 'EXIT', '5.000')
        self._push(entry_id, 'ENTRY', '10.000', '100000.00')
        # Rejeu des deux envois + un second ENTRY au prix différent : la sortie
        # déjà ré-estampillée ne bouge plus.
        self._push(exit_id, 'EXIT', '5.000')
        self._push(entry_id, 'ENTRY', '10.000', '100000.00')
        self._push(str(uuid.uuid4()), 'ENTRY', '10.000', '300000.00')
        stock = ConsumableStock.objects.get(node=self.node, consumable_type='FLOUR')
        self.assertEqual(_restamp_orphan_exits(stock.pk), 0)
        self.assertEqual(ConsumableMovement.objects.filter(pk=exit_id).count(), 1)
        self.assertEqual(ConsumableMovement.objects.get(pk=exit_id).unit_price, Decimal('100000.00'))
        self.assertEqual(SyncConflictLog.objects.filter(object_id=exit_id).count(), 1)

    def test_zero_priced_entry_keeps_exit_pending_then_later_entry_fixes_it(self):
        exit_id = str(uuid.uuid4())
        self._push(exit_id, 'EXIT', '1.000')
        self._push(str(uuid.uuid4()), 'ENTRY', '2.000', '0')
        self.assertFalse(SyncConflictLog.objects.get(object_id=exit_id).is_resolved)
        self._push(str(uuid.uuid4()), 'ENTRY', '2.000', '50000.00')
        self.assertEqual(ConsumableMovement.objects.get(pk=exit_id).unit_price, Decimal('25000.00'))

    def test_exit_after_entry_is_not_tracked(self):
        self._push(str(uuid.uuid4()), 'ENTRY', '10.000', '100000.00')
        exit_id = str(uuid.uuid4())
        self._push(exit_id, 'EXIT', '2.000')
        self.assertEqual(ConsumableMovement.objects.get(pk=exit_id).unit_price, Decimal('100000.00'))
        self.assertFalse(SyncConflictLog.objects.filter(object_id=exit_id).exists())
