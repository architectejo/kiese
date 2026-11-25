"""
Q-017 (reponse client 2026-11-24) : toutes les boulangeries sont en rotation de 24 h ;
heure de cloture/releve 12:00 par defaut. Donnees fictives.
"""
import datetime as dt
from importlib import import_module
from io import StringIO

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Node
from core.testing import make_user


class RotationParDefautTests(TestCase):
    def test_une_nouvelle_boulangerie_est_en_rotation_a_12h(self):
        n = Node.objects.create(code='ZQ1', name='Test')
        n.refresh_from_db()
        self.assertTrue(n.team_rotation_enabled)
        self.assertEqual(n.handover_time, dt.time(12, 0))

    def test_creation_via_api_sans_champ_est_en_rotation(self):
        c = APIClient()
        c.force_authenticate(make_user('DIRECTION', node=None))
        r = c.post('/api/core/nodes/', {'code': 'ZQ2', 'name': 'Test API'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['team_rotation_enabled'])
        self.assertEqual(r.data['handover_time'], '12:00:00')

    def test_migration_de_donnees_active_toutes_les_boulangeries_hors_siege(self):
        mig = import_module('core.migrations.0026_node_rotation_default_true')
        a = Node.objects.create(code='ZQ3', name='A')
        b = Node.objects.get(code='SIEGE')
        Node.objects.filter(pk__in=[a.pk, b.pk]).update(team_rotation_enabled=False)
        mig.enable_rotation_everywhere(apps, None)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertTrue(a.team_rotation_enabled)
        self.assertEqual(a.handover_time, dt.time(12, 0))
        self.assertFalse(b.team_rotation_enabled)  # noeud technique laisse tel quel

    def test_seed_aligne_les_8_boulangeries_meme_existantes(self):
        Node.objects.create(code='K1', name='TABORA', team_rotation_enabled=False)
        call_command('seed_kiese', stdout=StringIO())
        codes = ['K1', 'K2', 'K3', 'K4', 'K5', 'K6', 'B1', 'B2']
        nodes = Node.objects.filter(code__in=codes)
        self.assertEqual(nodes.count(), 8)
        for n in nodes:
            self.assertTrue(n.team_rotation_enabled, n.code)
            self.assertEqual(n.handover_time, dt.time(12, 0), n.code)

    def test_le_reglage_est_diffuse_dans_node_settings_de_la_synchro(self):
        from sync.views import _node_settings_block
        n = Node.objects.create(code='ZQ4', name='Sync')
        block = _node_settings_block(n)
        self.assertIs(block['team_rotation_enabled'], True)
        self.assertEqual(block['handover_time'], '12:00')
