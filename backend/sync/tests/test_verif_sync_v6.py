"""
Sync - ronde b22 (testeur clients/commissions, 2026-11-23). Verification independante de BUG-1030 (bloc
node_settings du pull) et re-examen de BUG-1103 de bout en bout : le cloud regle K1 a 0,30, le poste K1 tire
(pull), un facturier du poste cree un client -> 0,30 ; poste K2 -> 0,25. Une seule base joue le cloud puis
le poste (on remet le Node a ses defauts avant d'appliquer). Donnees FICTIVES.
"""
import logging
import tempfile
from decimal import Decimal as D
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase

from clients.models import Client
from clients.tests.test_clients_v6 import node_api
from clients.tests.test_clients_v13 import TOP_KEYS
from clients.tests.test_clients_v17 import CL, api
from core.models import Config, Node
from core.testing import make_node, make_user
from sync import desktop_client
from sync.management.commands.sync_now import apply_pull_response

LOG = logging.getLogger('b22')
CLOUD = 'http://cloud.test'


class BoutEnBout1103(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        cfg = Config.get_instance()
        cfg.default_commission_rate = D('0.25')
        cfg.save()
        Node.objects.filter(pk=self.k1.pk).update(default_commission_rate=D('0.30'))
        self.f1 = make_user('FACTURIER', node=self.k1)
        self.l1 = make_user('LIVREUR', node=self.k1)
        self.f2 = make_user('FACTURIER', node=self.k2)

    def frozen_bridge(self, node):
        """Reponse du cloud figee AVANT que le poste (meme base) ne remette son taux local."""
        data = self.cloud_pull(node)

        def fake_get(url, headers=None, timeout=None, params=None):
            m = MagicMock(status_code=200)
            m.json.return_value = data
            m.text = ''
            return m
        return fake_get

    def poste_vierge(self, node, rate=None):
        Node.objects.filter(pk=node.pk).update(default_commission_rate=rate)

    def cloud_pull(self, node):
        r = node_api(node).get('/api/sync/pull/')
        self.assertEqual(r.status_code, 200)
        return r.json()

    def creer(self, user):
        user = type(user).objects.get(pk=user.pk)  # requete reelle : utilisateur relu
        r = api(user).post(CL, {'first_name': 'Fictif', 'last_name': 'Poste'}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        return Client.objects.get(pk=r.data['id']).commission_rate

    def test_poste_k1_apres_pull_030_poste_k2_025(self):
        d1, d2 = self.cloud_pull(self.k1), self.cloud_pull(self.k2)
        self.poste_vierge(self.k1, D('0.10'))
        self.poste_vierge(self.k2, D('0.12'))
        self.assertEqual(self.creer(self.f1), D('0.10'))  # avant pull : taux local perime
        apply_pull_response(d1)
        self.assertEqual(self.creer(self.f1), D('0.30'))
        self.assertEqual(self.creer(self.l1), D('0.30'))
        apply_pull_response(d2)  # K2 : vide dans le cloud -> repli Config
        self.assertEqual(self.creer(self.f2), D('0.25'))

    def test_pull_de_k2_n_affecte_pas_k1(self):
        Node.objects.filter(pk=self.k2.pk).update(default_commission_rate=D('0.11'))
        d2 = self.cloud_pull(self.k2)
        self.poste_vierge(self.k1, None)
        apply_pull_response(d2)
        self.assertIsNone(Node.objects.get(code='K1').default_commission_rate)

    def test_changement_cloud_ne_touche_pas_les_clients_deja_crees_et_s_applique_aux_suivants(self):
        d = self.cloud_pull(self.k1)
        self.poste_vierge(self.k1)
        apply_pull_response(d)
        r = api(type(self.f1).objects.get(pk=self.f1.pk)).post(CL, {'first_name': 'A', 'last_name': 'B'}, format='json')
        first = Client.objects.get(pk=r.data['id'])
        Node.objects.filter(pk=self.k1.pk).update(default_commission_rate=D('0.28'))
        apply_pull_response(self.cloud_pull(self.k1))
        first.refresh_from_db()
        self.assertEqual(first.commission_rate, D('0.30'))
        self.assertEqual(self.creer(self.f1), D('0.28'))

    def test_cloud_ancien_sans_bloc_le_poste_garde_son_taux(self):
        d = self.cloud_pull(self.k1)
        del d['node_settings']
        self.poste_vierge(self.k1, D('0.20'))
        apply_pull_response(d)
        self.assertEqual(self.creer(self.f1), D('0.20'))

    def test_application_idempotente_pas_de_reecriture(self):
        d = self.cloud_pull(self.k1)
        self.poste_vierge(self.k1)
        apply_pull_response(d)
        stamp = Node.objects.get(pk=self.k1.pk).updated_at
        apply_pull_response(d)
        apply_pull_response(d)
        self.assertEqual(Node.objects.get(pk=self.k1.pk).updated_at, stamp)

    def test_taux_invalide_du_cloud_ignore_et_poste_garde_le_sien(self):
        d = self.cloud_pull(self.k1)
        for bad in ('abc', '-0.1', '1.5', 'NaN', True, [0.3], {'a': 1}):
            d['node_settings']['default_commission_rate'] = bad
            self.poste_vierge(self.k1, D('0.22'))
            apply_pull_response(d)
            self.assertEqual(Node.objects.get(code='K1').default_commission_rate, D('0.22'), bad)

    def test_le_cloud_repasse_a_vide_vide_le_taux_local(self):
        Node.objects.filter(pk=self.k1.pk).update(default_commission_rate=None)
        d = self.cloud_pull(self.k1)
        self.assertIsNone(d['node_settings']['default_commission_rate'])
        self.poste_vierge(self.k1, D('0.30'))
        apply_pull_response(d)
        self.assertIsNone(Node.objects.get(code='K1').default_commission_rate)
        self.assertEqual(self.creer(self.f1), D('0.25'))

    def test_chemin_commande_sync_now(self):
        fake = self.frozen_bridge(self.k1)
        self.poste_vierge(self.k1, D('0.10'))
        push = MagicMock(status_code=200)
        push.json.return_value = {'batch_id': '00000000-0000-4000-8000-000000000001', 'results': {}}
        with patch('requests.post', return_value=push), patch('requests.get', side_effect=fake):
            call_command('sync_now', node_code='K1', cloud_url=CLOUD, node_token='t', stdout=StringIO())
        self.assertEqual(Node.objects.get(code='K1').default_commission_rate, D('0.30'))
        self.assertEqual(self.creer(self.f1), D('0.30'))

    def test_chemin_desktop(self):
        fake = self.frozen_bridge(self.k1)
        self.poste_vierge(self.k1, D('0.10'))
        with patch.object(desktop_client.requests, 'get', fake), tempfile.TemporaryDirectory() as tmp:
            desktop_client._pull_only(LOG, CLOUD, {}, tmp, 'K1')
        self.assertEqual(Node.objects.get(code='K1').default_commission_rate, D('0.30'))
        self.assertEqual(self.creer(self.f1), D('0.30'))

    def test_confidentialite_du_pull_cles_de_premier_niveau_et_bloc(self):
        Node.objects.filter(pk=self.k2.pk).update(default_commission_rate=D('0.11'), card_fee_fc=D('7777'))
        d = self.cloud_pull(self.k1)
        self.assertTrue(set(d) <= TOP_KEYS, set(d) - TOP_KEYS)
        self.assertIn('node_settings', TOP_KEYS)
        for leak in ('7777', '0.11', 'K2'):
            self.assertNotIn(leak, str(d['node_settings']))
        r = node_api(self.k1).get('/api/sync/pull/', {'node': 'K2', 'node_code': 'K2'})
        self.assertEqual(r.json()['node_code'], 'K1')
        self.assertNotEqual(r.json()['node_settings']['card_fee_fc'], '7777.00')
