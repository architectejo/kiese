"""
BUG-386 (sync) : synchronisation de `production.ConsumableInventory`
(inventaire physique journalier) et du lien `ConsumableCount.inventory`.

Avant correction, ces deux modèles n'étaient pas dans `PUSH_HANDLERS` :
le lot était rejeté « modèle non supporté en V1 » et rien ne remontait.
"""
import uuid
from datetime import date
from decimal import Decimal
from io import StringIO

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node
from production.models import ConsumableCount, ConsumableInventory
from sync.models import NodeAuthToken, SyncConflictLog
from sync.management.commands.sync_now import apply_push_response, build_outbound_payload

INV = 'production.ConsumableInventory'
CNT = 'production.ConsumableCount'


def _api(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return api


def _push(api, records):
    return api.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()), 'records': records}, format='json')


def _inv(inv_id=None, node='K1', day='2026-11-20', **extra):
    rec = {'id': inv_id or str(uuid.uuid4()), 'node': node, 'inventory_date': day,
           'comment': 'RAS', 'node_origin': node}
    rec.update(extra)
    return rec


def _cnt(inv_id=None, node='K1', day='2026-11-20', ctype='FARINE', system='10.000', physical='9.500',
         gap='-0.500', **extra):
    rec = {'node': node, 'consumable_type': ctype, 'count_date': day,
           'system_quantity': system, 'physical_quantity': physical, 'gap': gap, 'notes': ''}
    if inv_id is not None:
        rec['inventory'] = inv_id
    rec.update(extra)
    return rec


class ConsumableInventorySyncTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.api1 = _api(self.k1)
        self.api2 = _api(self.k2)

    def test_inventaire_et_lignes_acceptes_et_lies(self):
        inv_id = str(uuid.uuid4())
        resp = _push(self.api1, {INV: [_inv(inv_id)], CNT: [_cnt(inv_id), _cnt(inv_id, ctype='SEL')]})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['results'][INV][0]['status'], 'ACCEPTED')
        self.assertEqual([r['status'] for r in resp.data['results'][CNT]], ['ACCEPTED', 'ACCEPTED'])
        inv = ConsumableInventory.objects.get(pk=inv_id)
        self.assertEqual(inv.node, self.k1)
        self.assertEqual(inv.inventory_date, date(2026, 11, 20))
        self.assertTrue(inv.is_synced)
        self.assertEqual(inv.lines.count(), 2)
        line = inv.lines.get(consumable_type='FARINE')
        self.assertEqual(line.gap, Decimal('-0.500'))

    def test_rejeu_sans_doublon(self):
        inv_id = str(uuid.uuid4())
        recs = {INV: [_inv(inv_id)], CNT: [_cnt(inv_id)]}
        _push(self.api1, recs)
        resp = _push(self.api1, recs)
        self.assertEqual(resp.data['results'][INV][0]['status'], 'ACCEPTED')
        self.assertEqual(resp.data['results'][CNT][0]['status'], 'ACCEPTED')
        self.assertEqual(ConsumableInventory.objects.count(), 1)
        self.assertEqual(ConsumableCount.objects.count(), 1)

    def test_ancien_payload_comptage_sans_inventory(self):
        resp = _push(self.api1, {CNT: [_cnt()]})
        self.assertEqual(resp.data['results'][CNT][0]['status'], 'ACCEPTED', resp.data)
        c = ConsumableCount.objects.get()
        self.assertIsNone(c.inventory)
        # rejeu : pas de doublon
        _push(self.api1, {CNT: [_cnt()]})
        self.assertEqual(ConsumableCount.objects.count(), 1)

    def test_ligne_avant_inventaire_rejetee_puis_acceptee(self):
        inv_id = str(uuid.uuid4())
        r1 = _push(self.api1, {CNT: [_cnt(inv_id)]})
        self.assertEqual(r1.data['results'][CNT][0]['status'], 'REJECTED')
        self.assertIn('dépendance manquante', r1.data['results'][CNT][0]['reason'])
        r2 = _push(self.api1, {INV: [_inv(inv_id)], CNT: [_cnt(inv_id)]})
        self.assertEqual(r2.data['results'][CNT][0]['status'], 'ACCEPTED')
        self.assertEqual(ConsumableCount.objects.count(), 1)

    def test_unicite_noeud_jour_conflit_journalise(self):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        _push(self.api1, {INV: [_inv(first)]})
        resp = _push(self.api1, {INV: [_inv(second)]})
        self.assertEqual(resp.data['results'][INV][0]['status'], 'REJECTED')
        self.assertEqual(ConsumableInventory.objects.count(), 1)
        self.assertTrue(SyncConflictLog.objects.filter(
            model_label=INV, object_id=second, conflict_type='CONSUMABLE_INVENTORY_DUPLICATE').exists())

    def test_meme_jour_noeuds_differents_ok(self):
        _push(self.api1, {INV: [_inv(node='K1')]})
        resp = _push(self.api2, {INV: [_inv(node='K2')]})
        self.assertEqual(resp.data['results'][INV][0]['status'], 'ACCEPTED')
        self.assertEqual(ConsumableInventory.objects.count(), 2)

    def test_isolation_noeud_origine(self):
        # K1 ne peut pas pousser un inventaire ou un comptage au nom de K2.
        r = _push(self.api1, {INV: [_inv(node='K2')]})
        self.assertEqual(r.data['results'][INV][0]['status'], 'REJECTED')
        r = _push(self.api1, {INV: [_inv(node='K1', node_origin='K2')]})
        self.assertEqual(r.data['results'][INV][0]['status'], 'REJECTED')
        r = _push(self.api1, {CNT: [_cnt(node='K2')]})
        self.assertEqual(r.data['results'][CNT][0]['status'], 'REJECTED')
        self.assertEqual(ConsumableInventory.objects.count(), 0)
        self.assertEqual(ConsumableCount.objects.count(), 0)

    def test_noeud_tiers_ne_modifie_ni_ne_rattache(self):
        inv_id = str(uuid.uuid4())
        _push(self.api1, {INV: [_inv(inv_id, comment='original')]})
        r = _push(self.api2, {INV: [_inv(inv_id, node='K2', comment='pirate')]})
        self.assertEqual(r.data['results'][INV][0]['status'], 'REJECTED')
        self.assertEqual(ConsumableInventory.objects.get(pk=inv_id).comment, 'original')
        self.assertTrue(SyncConflictLog.objects.filter(
            model_label=INV, object_id=inv_id, conflict_type='NON_PROPRIETAIRE').exists())
        r = _push(self.api2, {CNT: [_cnt(inv_id, node='K2')]})
        self.assertEqual(r.data['results'][CNT][0]['status'], 'REJECTED')
        self.assertEqual(ConsumableCount.objects.count(), 0)

    def test_commentaire_seul_modifiable(self):
        inv_id = str(uuid.uuid4())
        _push(self.api1, {INV: [_inv(inv_id, comment='a')]})
        r = _push(self.api1, {INV: [_inv(inv_id, comment='b')]})
        self.assertEqual(r.data['results'][INV][0]['status'], 'ACCEPTED')
        self.assertEqual(ConsumableInventory.objects.get(pk=inv_id).comment, 'b')
        r = _push(self.api1, {INV: [_inv(inv_id, day='2026-11-21')]})
        self.assertEqual(r.data['results'][INV][0]['status'], 'REJECTED')
        self.assertEqual(ConsumableInventory.objects.get(pk=inv_id).inventory_date, date(2026, 11, 20))

    def test_validation_stricte_inventaire(self):
        bad = [
            _inv(inv_id='pas-un-uuid'),
            _inv(day='20/11/2026'),
            _inv(day=None),
            _inv(comment=123),
        ]
        for rec in bad:
            r = _push(self.api1, {INV: [rec]})
            self.assertEqual(r.data['results'][INV][0]['status'], 'REJECTED', rec)
        self.assertEqual(ConsumableInventory.objects.count(), 0)

    def test_validation_stricte_comptage(self):
        inv_id = str(uuid.uuid4())
        _push(self.api1, {INV: [_inv(inv_id)]})
        bad = [
            _cnt(inv_id, physical='abc'),
            _cnt(inv_id, physical='NaN'),
            _cnt(inv_id, physical='Infinity'),
            _cnt(inv_id, physical='9.5005', gap='-0.4995'),   # > 3 décimales
            _cnt(inv_id, physical='99999999', gap='99999989'),  # hors plage max_digits=10
            _cnt(inv_id, gap='1.000'),                          # écart incohérent
            _cnt(inv_id, physical=True),
            _cnt(inv_id, day='2026-13-40'),
            _cnt(inv_id, day='2026-11-19'),                     # ≠ date de l'inventaire
            _cnt(inv_id, ctype=''),
            _cnt('pas-un-uuid'),
        ]
        for rec in bad:
            r = _push(self.api1, {CNT: [rec]})
            self.assertEqual(r.data['results'][CNT][0]['status'], 'REJECTED', rec)
        self.assertEqual(ConsumableCount.objects.count(), 0)

    def test_aller_retour_sync_now_payload(self):
        """Le payload sortant d'un nœud local est accepté par le Cloud et
        l'accusé marque l'inventaire `is_synced=True` (aucune ligne perdue)."""
        inv = ConsumableInventory(node=self.k1, inventory_date=date(2026, 11, 20),
                                  comment='x', node_origin='K1')
        inv.save()
        self.assertFalse(ConsumableInventory.objects.get(pk=inv.pk).is_synced)
        ConsumableCount.objects.create(
            node=self.k1, consumable_type='LEVURE', count_date=date(2026, 11, 20),
            system_quantity=Decimal('2.250'), physical_quantity=Decimal('2.000'),
            gap=Decimal('-0.250'), inventory=inv,
        )
        payload = build_outbound_payload('K1')
        self.assertEqual(len(payload['records'][INV]), 1)
        self.assertEqual(len(payload['records'][CNT]), 1)
        self.assertEqual(payload['records'][CNT][0]['inventory'], str(inv.pk))

        # « Cloud » : on repart d'une base sans ces enregistrements.
        ConsumableCount.objects.all().delete()
        ConsumableInventory.objects.all().delete()
        resp = _push(self.api1, payload['records'])
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['results'][INV][0]['status'], 'ACCEPTED')
        self.assertEqual(resp.data['results'][CNT][0]['status'], 'ACCEPTED')
        apply_push_response(resp.data)
        restored = ConsumableInventory.objects.get(pk=inv.pk)
        self.assertTrue(restored.is_synced)
        self.assertEqual(restored.lines.get().physical_quantity, Decimal('2.000'))
