"""BUG-626 (a3) : sync des lignes d'inventaire (ConsumableCount) : une ligne rejouee avec une
autre quantite cree un doublon (type, inventaire). Donnees fictives uniquement."""
import uuid
from unittest import expectedFailure

from django.test import TestCase

from core.testing import make_node
from production.models import ConsumableInventory
from sync.tests.test_consumable_inventory_sync import CNT, INV, _api, _cnt, _inv, _push


class SyncInventaireV2(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api1 = _api(self.k1)

    def test_same_line_replayed_is_idempotent(self):
        inv_id = str(uuid.uuid4())
        for _ in range(3):
            r = _push(self.api1, {INV: [_inv(inv_id)], CNT: [_cnt(inv_id)]})
            self.assertEqual(r.status_code, 200)
        self.assertEqual(ConsumableInventory.objects.get(pk=inv_id).lines.count(), 1)

    @expectedFailure  # BUG-626
    def test_BUG_626_one_line_per_type_per_inventory(self):
        inv_id = str(uuid.uuid4())
        _push(self.api1, {INV: [_inv(inv_id)], CNT: [_cnt(inv_id, physical='9.500', gap='-0.500')]})
        _push(self.api1, {CNT: [_cnt(inv_id, physical='8.000', gap='-2.000')]})
        self.assertEqual(ConsumableInventory.objects.get(pk=inv_id).lines.filter(consumable_type='FARINE').count(), 1)

    @expectedFailure  # BUG-626
    def test_BUG_626_future_inventory_date_refused(self):
        r = _push(self.api1, {INV: [_inv(day='2099-01-01')]})
        self.assertEqual(r.data['results'][INV][0]['status'], 'REJECTED')
