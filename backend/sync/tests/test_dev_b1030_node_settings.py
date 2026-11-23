"""BUG-1030 (Q-026) : le pull diffuse le bloc `node_settings` du nœud du poste, appliqué localement.
Un seul processus : la base joue tour à tour le cloud (réponse du pull) puis le poste (on remet le Node
à ses défauts avant d'appliquer). Données FICTIVES."""
import datetime
from decimal import Decimal as D

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from core.models import Config, Node
from core.testing import make_node, make_user
from sync.management.commands.sync_now import apply_pull_response
from sync.models import NodeAuthToken

PULL = '/api/sync/pull/'
FIELDS = ['default_commission_rate', 'card_fee_fc', 'monthly_social_contribution', 'sac_value_fc',
          'handover_time', 'block_sales_after_closure', 'team_rotation_enabled',
          'team_a_start_time', 'team_a_end_time', 'team_b_start_time', 'team_b_end_time']


def pull(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    c = APIClient(raise_request_exception=False)
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    r = c.get(PULL)
    assert r.status_code == 200, getattr(r, 'data', None)
    return r.json()


def snapshot(node):
    node.refresh_from_db()
    return {f: getattr(node, f) for f in FIELDS}


class NodeSettings1030(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', sac_value_fc=D('200000'))
        self.k2 = make_node(code='K2')
        Node.objects.filter(pk=self.k1.pk).update(
            default_commission_rate=D('0.30'), card_fee_fc=D('1500'), monthly_social_contribution=D('2500'),
            handover_time=datetime.time(15, 30), block_sales_after_closure=True, team_rotation_enabled=True,
            team_a_start_time=datetime.time(6, 0), team_a_end_time=datetime.time(13, 0))
        Node.objects.filter(pk=self.k2.pk).update(
            default_commission_rate=D('0.11'), card_fee_fc=D('7777'), monthly_social_contribution=D('3333'),
            sac_value_fc=D('654321'), handover_time=datetime.time(9, 45))
        self.cloud_k1 = snapshot(self.k1)

    def reset_poste(self):
        """Le poste local a ses défauts d'installation."""
        Node.objects.filter(pk=self.k1.pk).update(
            default_commission_rate=None, card_fee_fc=D('1000'), monthly_social_contribution=D('2000'),
            sac_value_fc=None, handover_time=datetime.time(12, 0), block_sales_after_closure=False,
            team_rotation_enabled=False, team_a_start_time=None, team_a_end_time=None)

    def test_le_bloc_contient_les_valeurs_du_noeud_en_chaines(self):
        ns = pull(self.k1)['node_settings']
        self.assertEqual(ns['default_commission_rate'], '0.30')
        self.assertEqual(ns['card_fee_fc'], '1500.00')
        self.assertEqual(ns['monthly_social_contribution'], '2500.00')
        self.assertEqual(ns['sac_value_fc'], '200000.00')
        self.assertEqual(ns['handover_time'], '15:30')
        self.assertIs(ns['block_sales_after_closure'], True)
        self.assertEqual(ns['team_a_start_time'], '06:00')
        self.assertIsNone(ns['team_b_start_time'])

    def test_aucune_valeur_d_une_autre_boulangerie_ni_champ_sensible(self):
        data = pull(self.k1)
        blob = str(data['node_settings'])
        for other in ('0.11', '7777', '3333', '654321', '09:45'):
            self.assertNotIn(other, blob)
        self.assertEqual(set(data['node_settings']), set(FIELDS))
        self.assertNotIn('K2', blob)
        self.assertEqual(data['node_code'], 'K1')

    def test_le_poste_recoit_les_valeurs_de_sa_boulangerie_et_pas_celles_d_une_autre(self):
        data = pull(self.k1)
        self.reset_poste()
        k2_before = snapshot(self.k2)
        apply_pull_response(data)
        self.assertEqual(snapshot(self.k1), self.cloud_k1)
        self.assertEqual(snapshot(self.k2), k2_before)

    def test_identite_du_noeud_local_jamais_ecrasee(self):
        data = pull(self.k1)
        data['node_settings'].update({'code': 'ZZ', 'name': 'Pirate', 'is_active': False, 'last_sync': None})
        Node.objects.filter(pk=self.k1.pk).update(name='Nom local', is_active=True)
        apply_pull_response(data)
        n = Node.objects.get(pk=self.k1.pk)
        self.assertEqual((n.code, n.name, n.is_active), ('K1', 'Nom local', True))
        self.assertFalse(Node.objects.filter(code='ZZ').exists())

    def test_cloud_ancien_sans_bloc_n_efface_rien(self):
        data = pull(self.k1)
        del data['node_settings']
        before = snapshot(self.k1)
        apply_pull_response(data)
        self.assertEqual(snapshot(self.k1), before)

    def test_bloc_partiel_ne_touche_que_les_champs_presents(self):
        before = snapshot(self.k1)
        apply_pull_response({'node_code': 'K1', 'node_settings': {'card_fee_fc': '1800'}})
        after = snapshot(self.k1)
        self.assertEqual(after['card_fee_fc'], D('1800.00'))
        after['card_fee_fc'] = before['card_fee_fc']
        self.assertEqual(after, before)

    def test_valeurs_invalides_ignorees_sans_500(self):
        before = snapshot(self.k1)
        hostile = {
            'default_commission_rate': '1.50', 'card_fee_fc': '-5', 'monthly_social_contribution': 'abc',
            'sac_value_fc': 'NaN', 'handover_time': '25:99', 'block_sales_after_closure': 'oui',
            'team_rotation_enabled': 1, 'team_a_start_time': {'x': 1}, 'team_a_end_time': '6h',
            'team_b_start_time': True, 'team_b_end_time': [],
        }
        with self.assertLogs('sync', level='WARNING'):
            apply_pull_response({'node_code': 'K1', 'node_settings': hostile})
        self.assertEqual(snapshot(self.k1), before)
        for junk in ('texte', 12, None, [1], True):
            apply_pull_response({'node_code': 'K1', 'node_settings': junk})
        self.assertEqual(snapshot(self.k1), before)

    def test_un_champ_invalide_n_empeche_pas_les_champs_valides(self):
        with self.assertLogs('sync', level='WARNING'):
            apply_pull_response({'node_code': 'K1', 'node_settings': {'card_fee_fc': 'x', 'handover_time': '18:00'}})
        n = snapshot(self.k1)
        self.assertEqual(n['handover_time'], datetime.time(18, 0))
        self.assertEqual(n['card_fee_fc'], D('1500.00'))

    def test_poste_inconnu_du_cloud_non_cree(self):
        count = Node.objects.count()
        apply_pull_response({'node_code': 'Q9', 'node_settings': {'card_fee_fc': '10'}})
        self.assertEqual(Node.objects.count(), count)

    def test_rejeu_idempotent(self):
        data = pull(self.k1)
        self.reset_poste()
        apply_pull_response(data)
        first = snapshot(self.k1)
        apply_pull_response(data)
        apply_pull_response(data)
        self.assertEqual(snapshot(self.k1), first)
        self.assertEqual(first, self.cloud_k1)

    def test_aucune_ecriture_si_inchange(self):
        data = pull(self.k1)
        stamp = Node.objects.get(pk=self.k1.pk).updated_at
        with self.assertNumQueries(1):  # lecture du Node local seule, aucun UPDATE
            from sync.management.commands.sync_now import _apply_pulled_node_settings
            self.assertFalse(_apply_pulled_node_settings(data['node_settings'], 'K1'))
        self.assertEqual(Node.objects.get(pk=self.k1.pk).updated_at, stamp)

    def test_une_modification_cloud_redescend_au_pull_suivant(self):
        self.reset_poste()
        apply_pull_response(pull(self.k1))
        Node.objects.filter(pk=self.k1.pk).update(default_commission_rate=D('0.20'))
        apply_pull_response(pull(self.k1))
        self.assertEqual(Node.objects.get(pk=self.k1.pk).default_commission_rate, D('0.20'))

    def test_le_taux_recu_s_applique_a_la_creation_d_un_client_sur_le_poste(self):
        cfg = Config.get_instance()
        cfg.default_commission_rate = D('0.25')
        cfg.save()
        data = pull(self.k1)
        self.reset_poste()
        apply_pull_response(data)
        gerant = make_user('GERANT', node=Node.objects.get(pk=self.k1.pk), team='')
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(gerant)
        r = c.post('/api/clients/clients/', {'first_name': 'Fictif', 'last_name': 'Poste'}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        self.assertEqual(Client.objects.get(pk=r.data['id']).commission_rate, D('0.30'))
