"""
BUG-004 (suite, 2026-11-02) : câblage de `clients.SocialContribution`/
`SocialDistribution`/`SocialDistributionLine` dans `sync.services.PUSH_HANDLERS`
après leur migration vers `SyncableModel` (PK UUIDv4) —
`clients/migrations/0008_social_syncable_step1.py` et
`0009_social_syncable_step2.py`.

Ces modèles sont mono-nœud (toujours créés/modifiés par le gérant d'une
seule boulangerie, jamais partagés entre deux nœuds comme `Client`/
`Invoice`) : pas de scénario de conflit multi-nœud à couvrir ici, juste
l'idempotence habituelle (upsert UUID, rejeu sans doublon) et l'ordre de
dépendance (`SocialDistribution` avant `SocialDistributionLine`).
"""
import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client, SocialContribution, SocialDistribution, SocialDistributionLine
from core.testing import make_node, make_client
from sync.models import NodeAuthToken


def _issue_token(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return api


class SocialContributionSyncTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.api = _issue_token(self.node)
        self.client_obj = make_client(self.node)

    def _payload(self, contrib_id, **overrides):
        payload = {
            'id': contrib_id, 'client': str(self.client_obj.pk), 'node': 'K1',
            'month': 10, 'year': 2026, 'amount': '3000.00',
            'is_paid': False, 'node_origin': 'K1',
        }
        payload.update(overrides)
        return payload

    def test_contribution_push_is_accepted_and_idempotent(self):
        contrib_id = str(uuid.uuid4())
        batch = {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialContribution': [self._payload(contrib_id)]},
        }
        resp1 = self.api.post('/api/sync/push/', batch, format='json')
        self.assertEqual(resp1.data['results']['clients.SocialContribution'][0]['status'], 'ACCEPTED', resp1.data)
        self.assertEqual(SocialContribution.objects.filter(pk=contrib_id).count(), 1)

        # Rejeu (coupure avant accusé de réception) : aucun doublon.
        resp2 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialContribution': [self._payload(contrib_id)]},
        }, format='json')
        self.assertEqual(resp2.data['results']['clients.SocialContribution'][0]['status'], 'ACCEPTED')
        self.assertEqual(SocialContribution.objects.filter(pk=contrib_id).count(), 1)

    def test_contribution_missing_client_dependency_is_rejected_explicitly(self):
        contrib_id = str(uuid.uuid4())
        payload = self._payload(contrib_id, client=str(uuid.uuid4()))
        resp = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialContribution': [payload]},
        }, format='json')
        self.assertEqual(resp.data['results']['clients.SocialContribution'][0]['status'], 'REJECTED')
        self.assertEqual(resp.data['results']['clients.SocialContribution'][0]['reason'], 'dépendance manquante : client')
        self.assertFalse(SocialContribution.objects.filter(pk=contrib_id).exists())

    def test_toggle_paid_transition_is_applied_idempotently(self):
        contrib_id = str(uuid.uuid4())
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialContribution': [self._payload(contrib_id)]},
        }, format='json')

        resp = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialContribution': [
                self._payload(contrib_id, is_paid=True, paid_at='2026-10-15T10:00:00Z'),
            ]},
        }, format='json')
        self.assertEqual(resp.data['results']['clients.SocialContribution'][0]['status'], 'ACCEPTED')
        contribution = SocialContribution.objects.get(pk=contrib_id)
        self.assertTrue(contribution.is_paid)

        # Rejeu du même état "payé" : no-op, toujours payé, aucune erreur.
        resp2 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialContribution': [
                self._payload(contrib_id, is_paid=True, paid_at='2026-10-15T10:00:00Z'),
            ]},
        }, format='json')
        self.assertEqual(resp2.data['results']['clients.SocialContribution'][0]['status'], 'ACCEPTED')
        self.assertEqual(SocialContribution.objects.filter(pk=contrib_id).count(), 1)


class SocialDistributionAndLineSyncTests(TestCase):
    """SYNC.md §3.5 : `SocialDistribution` doit précéder `SocialDistributionLine`."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.api = _issue_token(self.node)
        self.client_obj = make_client(self.node)

    def _distribution_payload(self, dist_id, is_closed=False):
        return {
            'id': dist_id, 'node': 'K1', 'year': 2026, 'tarif': '700.00',
            'is_closed': is_closed, 'node_origin': 'K1',
        }

    def _line_payload(self, line_id, dist_id, **overrides):
        payload = {
            'id': line_id, 'distribution': dist_id, 'client': str(self.client_obj.pk),
            'indice': 2, 'total_social': '6000.00', 'remise': '1400.00',
            'merite': '0.00', 'total_payer': '1400.00',
            'position': 'present', 'form': 'especes', 'node_origin': 'K1',
        }
        payload.update(overrides)
        return payload

    def test_distribution_then_line_accepted_in_dependency_order(self):
        dist_id = str(uuid.uuid4())
        line_id = str(uuid.uuid4())
        resp = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'clients.SocialDistribution': [self._distribution_payload(dist_id)],
                'clients.SocialDistributionLine': [self._line_payload(line_id, dist_id)],
            },
        }, format='json')
        self.assertEqual(resp.data['results']['clients.SocialDistribution'][0]['status'], 'ACCEPTED', resp.data)
        self.assertEqual(resp.data['results']['clients.SocialDistributionLine'][0]['status'], 'ACCEPTED', resp.data)
        self.assertTrue(SocialDistribution.objects.filter(pk=dist_id).exists())
        line = SocialDistributionLine.objects.get(pk=line_id)
        self.assertEqual(line.distribution_id, uuid.UUID(dist_id))
        self.assertEqual(line.total_payer, Decimal('1400.00'))

    def test_line_referencing_unknown_distribution_is_rejected_then_accepted_after_retry(self):
        dist_id = str(uuid.uuid4())
        line_id = str(uuid.uuid4())
        line_payload = self._line_payload(line_id, dist_id)

        resp1 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialDistributionLine': [line_payload]},
        }, format='json')
        self.assertEqual(resp1.data['results']['clients.SocialDistributionLine'][0]['status'], 'REJECTED')
        self.assertEqual(
            resp1.data['results']['clients.SocialDistributionLine'][0]['reason'],
            'dépendance manquante : distribution',
        )
        self.assertFalse(SocialDistributionLine.objects.filter(pk=line_id).exists())

        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialDistribution': [self._distribution_payload(dist_id)]},
        }, format='json')

        resp2 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialDistributionLine': [line_payload]},
        }, format='json')
        self.assertEqual(resp2.data['results']['clients.SocialDistributionLine'][0]['status'], 'ACCEPTED')
        self.assertEqual(SocialDistributionLine.objects.filter(pk=line_id).count(), 1)

        # Rejeu (coupure avant accusé) : toujours un seul enregistrement.
        resp3 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialDistributionLine': [line_payload]},
        }, format='json')
        self.assertEqual(resp3.data['results']['clients.SocialDistributionLine'][0]['status'], 'ACCEPTED')
        self.assertEqual(SocialDistributionLine.objects.filter(pk=line_id).count(), 1)

    def test_distribution_closure_transition_is_forward_only(self):
        dist_id = str(uuid.uuid4())
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialDistribution': [self._distribution_payload(dist_id, is_closed=False)]},
        }, format='json')

        resp = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'clients.SocialDistribution': [self._distribution_payload(dist_id, is_closed=True)]},
        }, format='json')
        self.assertEqual(resp.data['results']['clients.SocialDistribution'][0]['status'], 'ACCEPTED')
        self.assertTrue(SocialDistribution.objects.get(pk=dist_id).is_closed)

    def test_line_fields_are_updated_idempotently_before_closure(self):
        """Le gérant recalcule une ligne (mérite ajouté après coup) avant que
        la distribution ne soit clôturée — rejoué deux fois, pas de doublon,
        valeurs finales correctes."""
        dist_id = str(uuid.uuid4())
        line_id = str(uuid.uuid4())
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'clients.SocialDistribution': [self._distribution_payload(dist_id)],
                'clients.SocialDistributionLine': [self._line_payload(line_id, dist_id)],
            },
        }, format='json')

        updated_payload = self._line_payload(
            line_id, dist_id, merite='500.00', total_payer='1900.00',
        )
        for _ in range(2):
            resp = self.api.post('/api/sync/push/', {
                'batch_id': str(uuid.uuid4()),
                'records': {'clients.SocialDistributionLine': [updated_payload]},
            }, format='json')
            self.assertEqual(resp.data['results']['clients.SocialDistributionLine'][0]['status'], 'ACCEPTED')

        line = SocialDistributionLine.objects.get(pk=line_id)
        self.assertEqual(line.merite, Decimal('500.00'))
        self.assertEqual(line.total_payer, Decimal('1900.00'))
        self.assertEqual(SocialDistributionLine.objects.filter(pk=line_id).count(), 1)


class SocialModelsOutboundPayloadTests(TestCase):
    """`sync_now.build_outbound_payload` remonte les enregistrements locaux
    non encore synchronisés de ces 3 modèles (SYNC.md §3.2)."""

    def test_unsynced_social_records_are_included_in_outbound_payload(self):
        from sync.management.commands.sync_now import build_outbound_payload

        node = make_node(code='K1')
        client = make_client(node)
        contribution = SocialContribution.objects.create(
            client=client, node=node, month=1, year=2026, amount=Decimal('3000.00'),
            node_origin='K1',
        )
        distribution = SocialDistribution.objects.create(
            node=node, year=2026, tarif=Decimal('700.00'), node_origin='K1',
        )
        line = SocialDistributionLine.objects.create(
            distribution=distribution, client=client, indice=2,
            total_social=Decimal('6000.00'), node_origin='K1',
        )

        payload = build_outbound_payload('K1')
        records = payload['records']
        self.assertEqual([r['id'] for r in records['clients.SocialContribution']], [str(contribution.pk)])
        self.assertEqual([r['id'] for r in records['clients.SocialDistribution']], [str(distribution.pk)])
        self.assertEqual([r['id'] for r in records['clients.SocialDistributionLine']], [str(line.pk)])

    def test_already_synced_social_records_are_excluded(self):
        from sync.management.commands.sync_now import build_outbound_payload

        node = make_node(code='K1')
        client = make_client(node)
        contribution = SocialContribution(
            client=client, node=node, month=1, year=2026, amount=Decimal('3000.00'),
            node_origin='K1',
        )
        # `SyncableModel.save()` force `is_synced=False` à toute écriture
        # locale (node_origin != 'CLOUD') sauf `_sync_bypass=True` — ce test
        # simule un enregistrement déjà confirmé par un cycle `sync_now`
        # précédent (`apply_push_response`, qui fait le même `update()`).
        contribution.save(_sync_bypass=True)

        payload = build_outbound_payload('K1')
        self.assertEqual(payload['records']['clients.SocialContribution'], [])
