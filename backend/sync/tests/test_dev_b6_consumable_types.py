"""BUG-1117 : la conversion sac/boites des ConsumableType (configuration du cloud) descend par le pull
(bloc additif `consumable_types`) et s'applique sur les types EXISTANTS du poste. Donnees FICTIVES."""
from decimal import Decimal as D

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node
from production.models import ConsumableType
from sync.management.commands.sync_now import apply_pull_response
from sync.models import NodeAuthToken

PULL = '/api/sync/pull/'


def pull(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    c = APIClient(raise_request_exception=False)
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    r = c.get(PULL)
    assert r.status_code == 200, getattr(r, 'data', None)
    return r.json()


def salt():
    return ConsumableType.objects.get(code='SALT')


def conv():
    s = salt()
    return (s.bag_weight_g, s.units_per_bag)


class ConsumableTypes1117(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        for code, label, unit in [('SALT', 'Sel', 'g'), ('FLOUR', 'Farine', 'sacs')]:
            ConsumableType.objects.get_or_create(code=code, defaults={'label': label, 'unit': unit})
        ConsumableType.objects.filter(code='SALT').update(bag_weight_g=D('20000'), units_per_bag=204)

    def block(self, **kw):
        return {'node_code': 'K1', 'consumable_types': [{'code': 'SALT', **kw}]}

    def test_le_pull_porte_les_champs(self):
        rows = {r['code']: r for r in pull(self.k1)['consumable_types']}
        self.assertEqual(rows['SALT'], {'code': 'SALT', 'bag_weight_g': '20000.000', 'units_per_bag': 204})
        self.assertIsNone(rows['FLOUR']['bag_weight_g'])
        self.assertIsNone(rows['FLOUR']['units_per_bag'])

    def test_application_et_idempotence(self):
        data = pull(self.k1)
        ConsumableType.objects.filter(code='SALT').update(bag_weight_g=None, units_per_bag=None)
        apply_pull_response(data)
        self.assertEqual(conv(), (D('20000'), 204))
        stamp = salt().updated_at
        apply_pull_response(data)
        self.assertEqual(conv(), (D('20000'), 204))
        self.assertEqual(salt().updated_at, stamp)          # aucune ecriture au rejeu

    def test_retour_a_non_configure_descend_aussi(self):
        apply_pull_response(self.block(bag_weight_g=None, units_per_bag=None))
        self.assertEqual(conv(), (None, None))

    def test_valeurs_invalides_ignorees_sans_erreur(self):
        bad = [
            {'bag_weight_g': '0', 'units_per_bag': 204}, {'bag_weight_g': '-5', 'units_per_bag': 204},
            {'bag_weight_g': '20000', 'units_per_bag': 0}, {'bag_weight_g': '20000', 'units_per_bag': -1},
            {'bag_weight_g': 'abc', 'units_per_bag': 204}, {'bag_weight_g': '20000', 'units_per_bag': '2.5'},
            {'bag_weight_g': '٢٠٠٠٠', 'units_per_bag': 204},   # chiffres non ASCII
            {'bag_weight_g': '20000', 'units_per_bag': '٢٠٤'},
            {'bag_weight_g': '1e9', 'units_per_bag': 204}, {'bag_weight_g': '99999999999', 'units_per_bag': 204},
            {'bag_weight_g': '20000', 'units_per_bag': 10 ** 9},
            {'bag_weight_g': '20000', 'units_per_bag': None}, {'bag_weight_g': None, 'units_per_bag': 204},
            {'bag_weight_g': True, 'units_per_bag': 204}, {'bag_weight_g': '20000', 'units_per_bag': True},
            {'bag_weight_g': ['1'], 'units_per_bag': 204}, {'bag_weight_g': '20000.0001', 'units_per_bag': 204},
            {'bag_weight_g': 'NaN', 'units_per_bag': 204}, {'bag_weight_g': 'Infinity', 'units_per_bag': 204},
            {},
        ]
        for row in bad:
            apply_pull_response(self.block(**row))
            self.assertEqual(conv(), (D('20000'), 204), row)
        junk = [None, 'x', 5, {'code': 'SALT'},
                [None, 3, 'SALT', {'code': 5}, {'code': 'SALT', 'units_per_bag': 1}]]
        for item in junk:
            apply_pull_response({'node_code': 'K1', 'consumable_types': item})
        self.assertEqual(conv(), (D('20000'), 204))

    def test_invalide_est_journalise(self):
        with self.assertLogs('sync', level='WARNING'):
            apply_pull_response(self.block(bag_weight_g='-5', units_per_bag=204))

    def test_une_ligne_invalide_n_empeche_pas_les_autres(self):
        apply_pull_response({'node_code': 'K1', 'consumable_types': [
            {'code': 'SALT', 'bag_weight_g': 'oops', 'units_per_bag': 1},
            {'code': 'FLOUR', 'bag_weight_g': '50000', 'units_per_bag': 10}]})
        self.assertEqual(salt().units_per_bag, 204)
        self.assertEqual(ConsumableType.objects.get(code='FLOUR').units_per_bag, 10)

    def test_aucune_creation_et_champs_hors_conversion_intacts(self):
        before = ConsumableType.objects.count()
        ident = (salt().label, salt().unit, salt().is_active)
        apply_pull_response({'node_code': 'K1', 'consumable_types': [
            {'code': 'NEWT', 'bag_weight_g': '1000', 'units_per_bag': 5},
            {'code': 'SALT', 'label': 'Pirate', 'unit': 'kg', 'is_active': False,
             'bag_weight_g': '25000', 'units_per_bag': 250}]})
        self.assertEqual(ConsumableType.objects.count(), before)
        self.assertFalse(ConsumableType.objects.filter(code='NEWT').exists())
        s = salt()
        self.assertEqual((s.label, s.unit, s.is_active), ident)
        self.assertEqual(conv(), (D('25000'), 250))

    def test_cloud_ancien_sans_le_bloc(self):
        data = pull(self.k1)
        del data['consumable_types']
        apply_pull_response(data)
        apply_pull_response({'node_code': 'K1'})
        self.assertEqual(conv(), (D('20000'), 204))

    def test_le_bloc_ne_depend_pas_du_noeud(self):
        k2 = make_node(code='K2')
        self.assertEqual(pull(self.k1)['consumable_types'], pull(k2)['consumable_types'])
