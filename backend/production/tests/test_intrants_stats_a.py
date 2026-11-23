"""BUG-1060 (lot I-1) : statistiques journalieres des intrants. Valeurs FICTIVES calculees a la main
(aucune donnee du client). Jour de reference : aujourd'hui (les mouvements sont horodates maintenant)."""
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Node
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk
from production.models import (ConsumableCount, ConsumableInventory, ConsumableMovement,
                               ConsumableStock, ConsumableType, ProductionSession)

URL = '/api/production/intrants-stats/'
TODAY = timezone.localdate()


def stock(node, code, qty):
    s, _ = ConsumableStock.objects.get_or_create(node=node, consumable_type=code,
                                                 defaults={'node_origin': node.code})
    ConsumableStock.objects.filter(pk=s.pk).update(quantity=D(qty))
    s.refresh_from_db()
    return s


def move(node, st, kind, qty, session=None):
    return ConsumableMovement.objects.create(
        node=node, stock=st, movement_type=kind, quantity=D(qty), session=session,
        node_origin=node.code)


def declare(node, code, qty, day=None):
    day = day or TODAY
    inv, _ = ConsumableInventory.objects.get_or_create(
        node=node, inventory_date=day, defaults={'node_origin': node.code})
    ConsumableCount.objects.create(
        node=node, consumable_type=code, count_date=day, system_quantity=D('0'),
        physical_quantity=D(qty), gap=D('0'), inventory=inv)


class Intrants(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code, label, unit in [('FLOUR', 'Farine', 'sacs'), ('YEAST', 'Levure', 'paquets'),
                                  ('SALT', 'Sel', 'g'), ('OIL', 'Huile', 'litres')]:
            ConsumableType.objects.get_or_create(code=code, defaults={'label': label, 'unit': unit})
        cls.siege = Node.objects.get_or_create(
            code='SIEGE', defaults={'name': 'Siège', 'is_active': False})[0]

    def get(self, user, **params):
        return cl(user).get(URL, params)

    @staticmethod
    def row(resp, code):
        return {r['code']: r for r in resp.data['rows']}[code]

    def scenario_flour(self):
        # P1 : initial 20, entree 10, sortie libre 4, fournee du jour 5 sacs (sortie 5)
        s1 = stock(self.k1, 'FLOUR', '20')
        sess = ProductionSession.objects.create(node=self.k1, team='A', date=TODAY,
                                                flour_sacks_used=D('5'))
        move(self.k1, s1, 'ENTRY', '10')
        move(self.k1, s1, 'EXIT', '4')
        move(self.k1, s1, 'EXIT', '5', session=sess)
        declare(self.k1, 'FLOUR', '20')
        # P2 : stock 7, 2 sacs declares sans mouvement, aucun inventaire
        stock(self.k2, 'FLOUR', '7')
        ProductionSession.objects.create(node=self.k2, team='A', date=TODAY, flour_sacks_used=D('2'))
        # D1 : 100 au depart, 8 envoyes
        sd = stock(self.siege, 'FLOUR', '100')
        move(self.siege, sd, 'EXIT', '8')


class Calculs(Intrants):
    def test_flour_rows_totals_and_direction(self):
        self.scenario_flour()
        r = self.get(self.u['DIRECTION'], type='FLOUR', date=TODAY.isoformat())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['date'], TODAY.isoformat())
        self.assertEqual(r.data['type'], 'FLOUR')
        self.assertTrue(r.data['hypotheses'])
        p1 = self.row(r, 'P1')
        self.assertEqual((p1['initial'], p1['entry'], p1['exit']), ('20.000', '10.000', '4.000'))
        self.assertEqual(p1['total_before_production'], '26.000')
        self.assertEqual(p1['consumption'], '5.000')
        self.assertEqual(p1['balance'], '21.000')
        self.assertEqual(p1['production_reference'], '5.000')
        self.assertEqual(p1['consumption_index'], '1.0000')
        self.assertEqual(p1['declared_remaining'], '20.000')
        self.assertEqual(p1['gap'], '-1.000')  # declare 20 - comptable 21
        p2 = self.row(r, 'P2')
        self.assertEqual((p2['initial'], p2['entry'], p2['exit']), ('7.000', '0.000', '0.000'))
        self.assertEqual(p2['total_before_production'], '7.000')
        self.assertEqual(p2['balance'], '5.000')
        self.assertIsNone(p2['declared_remaining'])
        self.assertIsNone(p2['gap'])  # pas l'oppose du solde
        d1 = self.row(r, 'D1')
        self.assertTrue(d1['is_direction'])
        self.assertEqual((d1['initial'], d1['exit'], d1['balance']), ('100.000', '8.000', '92.000'))
        self.assertIsNone(d1['consumption_index'])
        t = r.data['totals']
        self.assertEqual(t['code'], 'TOTAUX')
        self.assertEqual(t['initial'], '127.000')
        self.assertEqual(t['entry'], '10.000')
        self.assertEqual(t['exit'], '12.000')
        self.assertEqual(t['total_before_production'], '125.000')
        self.assertEqual(t['consumption'], '7.000')
        self.assertEqual(t['balance'], '118.000')
        self.assertEqual(t['production_reference'], '7.000')
        self.assertEqual(t['consumption_index'], '1.0000')
        self.assertEqual(t['declared_remaining'], '20.000')
        self.assertEqual(t['gap'], '-1.000')

    def test_yeast_decimal_index_and_declared_gap(self):
        s1 = stock(self.k1, 'YEAST', '3.5')
        sess = ProductionSession.objects.create(node=self.k1, team='A', date=TODAY,
                                                flour_sacks_used=D('3'))
        move(self.k1, s1, 'ENTRY', '1.25')
        move(self.k1, s1, 'EXIT', '0.75', session=sess)
        declare(self.k1, 'YEAST', '4.5')
        r = self.get(self.u['ADMIN'], type='YEAST', date=TODAY.isoformat())
        p1 = self.row(r, 'P1')
        self.assertEqual((p1['initial'], p1['entry'], p1['exit']), ('3.500', '1.250', '0.000'))
        self.assertEqual(p1['total_before_production'], '4.750')
        self.assertEqual(p1['consumption'], '0.750')
        self.assertEqual(p1['balance'], '4.000')
        self.assertEqual(p1['production_reference'], '3.000')
        self.assertEqual(p1['consumption_index'], '0.2500')
        self.assertEqual(p1['gap'], '0.500')
        self.assertEqual(r.data['unit'], 'paquets')

    def test_zero_sacks_gives_null_index_without_division(self):
        s2 = stock(self.k2, 'YEAST', '2')
        sess = ProductionSession.objects.create(node=self.k2, team='A', date=TODAY,
                                                flour_sacks_used=D('0'))
        move(self.k2, s2, 'EXIT', '0.5', session=sess)
        r = self.get(self.u['COMPTABLE'], type='YEAST', date=TODAY.isoformat())
        p2 = self.row(r, 'P2')
        self.assertEqual(p2['consumption'], '0.500')
        self.assertEqual(p2['production_reference'], '0.000')
        self.assertIsNone(p2['consumption_index'])
        self.assertIsNone(r.data['totals']['consumption_index'])

    def test_day_without_data(self):
        r = self.get(self.u['DIRECTION'], type='FLOUR', date='2026-01-05')
        self.assertEqual(r.status_code, 200)
        for row in r.data['rows'] + [r.data['totals']]:
            self.assertEqual(row['initial'], '0.000')
            self.assertEqual(row['balance'], '0.000')
            self.assertIsNone(row['consumption_index'])
            self.assertIsNone(row['declared_remaining'])
            self.assertIsNone(row['gap'])

    def test_past_day_initial_excludes_later_movements(self):
        s2 = stock(self.k2, 'FLOUR', '0')
        old = move(self.k2, s2, 'ENTRY', '6')
        ConsumableMovement.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=1))
        move(self.k2, s2, 'ENTRY', '1')  # aujourd'hui ; stock courant = 7
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        r = self.get(self.u['DIRECTION'], type='FLOUR', date=yesterday)
        p2 = self.row(r, 'P2')
        self.assertEqual((p2['initial'], p2['entry'], p2['total_before_production']),
                         ('0.000', '6.000', '6.000'))
        r = self.get(self.u['DIRECTION'], type='FLOUR', date=TODAY.isoformat())
        p2 = self.row(r, 'P2')
        self.assertEqual((p2['initial'], p2['entry'], p2['total_before_production']),
                         ('6.000', '1.000', '7.000'))

    def test_salt_and_oil_structure_uses_simple_hypothesis(self):
        so = stock(self.k1, 'OIL', '10')
        move(self.k1, so, 'ENTRY', '4')
        move(self.k1, so, 'EXIT', '2')
        r = self.get(self.u['DIRECTION'], type='OIL', date=TODAY.isoformat())
        p1 = self.row(r, 'P1')
        self.assertEqual(p1['total_before_production'], '12.000')  # 10 + 4 - 2, pas 10 + 4 x 2
        r = self.get(self.u['DIRECTION'], type='SALT', date=TODAY.isoformat())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['unit'], 'g')

    def test_node_filter_hides_direction(self):
        self.scenario_flour()
        r = self.get(self.u['DIRECTION'], type='FLOUR', date=TODAY.isoformat(), node='P1')
        self.assertEqual([x['code'] for x in r.data['rows']], ['P1'])
        self.assertEqual(r.data['totals']['initial'], '20.000')
        r = self.get(self.u['DIRECTION'], type='FLOUR', node=str(self.k2.pk))
        self.assertEqual([x['code'] for x in r.data['rows']], ['P2'])


class Droits(Intrants):
    def test_roles(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'):
            self.assertEqual(self.get(self.u[role], type='FLOUR').status_code, 200, role)
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(self.get(self.u[role], type='FLOUR').status_code, 403, role)
        self.assertIn(cl().get(URL, {'type': 'FLOUR'}).status_code, (401, 403))

    def test_gerant_sees_only_his_bakery_without_direction(self):
        self.scenario_flour()
        r = self.get(self.u['GERANT'], type='FLOUR', date=TODAY.isoformat())
        self.assertEqual([x['code'] for x in r.data['rows']], ['P1'])
        self.assertEqual(r.data['totals']['initial'], '20.000')
        self.assertNotIn('D1', {x['code'] for x in r.data['rows']})
        self.assertEqual(self.get(self.u['GERANT'], type='FLOUR', node='P1').status_code, 200)

    def test_gerant_cannot_read_other_bakery_or_direction(self):
        for ref in ('P2', str(self.k2.pk), 'SIEGE'):
            r = self.get(self.u['GERANT'], type='FLOUR', node=ref)
            self.assertEqual(r.status_code, 404, ref)
        self.assertEqual(self.get(self.u2['GERANT'], type='FLOUR').data['rows'][0]['code'], 'P2')

    def test_gerant_without_bakery_refused(self):
        orphan = mk('orphan_gerant', 'GERANT', None)
        r = self.get(orphan, type='FLOUR')
        self.assertEqual(r.status_code, 403)
        self.assertIn('detail', r.data)


class Parametres(Intrants):
    def test_invalid_type(self):
        for bad in (None, '', 'true', 'NaN', 'SUCRE', 'flour; drop', '%00'):
            params = {} if bad is None else {'type': bad}
            r = self.get(self.u['DIRECTION'], **params)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('detail', r.data)

    def test_invalid_dates(self):
        for bad in ('abc', '2026-02-30', '2026-13-01', '20261123', 'NaN', 'true', '2026-11-23x',
                    '1999-12-31', '2101-01-01', '٢٠٢٦-١١-٢٣', '', '2026-W47-1'):
            r = self.get(self.u['DIRECTION'], type='FLOUR', date=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('detail', r.data)

    def test_invalid_node(self):
        for bad in ('true', 'NaN', '0', '-1', '1.5', 'ZZZ', '9' * 30):
            r = self.get(self.u['DIRECTION'], type='FLOUR', node=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('detail', r.data)
        self.assertEqual(self.get(self.u['DIRECTION'], type='FLOUR', node='SIEGE').status_code, 404)

    def test_type_is_case_insensitive_default_date_today(self):
        r = self.get(self.u['DIRECTION'], type='flour')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['date'], TODAY.isoformat())


class Sel(Intrants):
    """Regle ferme du client : 1 sac de sel = 20 kg = 204 boites (valeurs fictives)."""

    def configure(self):
        ConsumableType.objects.filter(code='SALT').update(
            bag_weight_g=D('20000'), units_per_bag=204)

    def salt_row(self, **kw):
        r = self.get(self.u['DIRECTION'], type='SALT', date=TODAY.isoformat())
        self.assertEqual(r.status_code, 200)
        return r, self.row(r, 'P1')

    def test_one_bag_is_204_boxes(self):
        self.configure()
        stock(self.k1, 'SALT', '20000')
        r, p1 = self.salt_row()
        self.assertEqual(p1['initial'], '20000.000')  # reste stocke en grammes
        self.assertEqual((p1['initial_bags'], p1['initial_units']), ('1.000', '204.0'))
        self.assertEqual(r.data['conversion'], {
            'bag_weight_g': '20000.000', 'units_per_bag': 204, 'unit_weight_g': '98.0392'})
        self.assertEqual(r.data['totals']['initial_units'], '204.0')
        self.assertIsNone(p1['declared_remaining_bags'])  # non declare -> null
        self.assertIsNone(p1['gap_units'])

    def test_98_grams_is_about_one_box_no_early_rounding(self):
        self.configure()
        stock(self.k1, 'SALT', '98')
        _, p1 = self.salt_row()
        self.assertEqual(p1['initial_units'], '1.0')     # 98 x 204 / 20000 = 0,9996
        self.assertEqual(p1['initial_bags'], '0.005')    # 98 / 20000 = 0,0049

    def test_partial_bag_and_flows(self):
        self.configure()
        st = stock(self.k1, 'SALT', '30000')
        move(self.k1, st, 'ENTRY', '10000')
        move(self.k1, st, 'EXIT', '5000')
        declare(self.k1, 'SALT', '25000')
        r, p1 = self.salt_row()
        # initial 30000 ; entree 10000 ; sortie 5000 ; total 35000 = solde ; declare 25000
        self.assertEqual((p1['initial_bags'], p1['initial_units']), ('1.500', '306.0'))
        self.assertEqual((p1['entry_bags'], p1['entry_units']), ('0.500', '102.0'))
        self.assertEqual((p1['exit_bags'], p1['exit_units']), ('0.250', '51.0'))
        self.assertEqual((p1['balance_bags'], p1['balance_units']), ('1.750', '357.0'))
        self.assertEqual((p1['declared_remaining_bags'], p1['declared_remaining_units']),
                         ('1.250', '255.0'))
        self.assertEqual((p1['gap'], p1['gap_bags'], p1['gap_units']), ('-10000.000', '-0.500', '-102.0'))
        self.assertEqual(r.data['totals']['balance_units'], '357.0')

    def test_not_configured_gives_null_and_explicit_hypothesis(self):
        ConsumableType.objects.filter(code='SALT').update(bag_weight_g=None, units_per_bag=None)
        stock(self.k1, 'SALT', '20000')
        r, p1 = self.salt_row()
        self.assertEqual(p1['initial'], '20000.000')
        self.assertIsNone(p1['initial_bags'])
        self.assertIsNone(p1['initial_units'])
        self.assertIsNone(r.data['totals']['initial_bags'])
        self.assertEqual(r.data['conversion'], {
            'bag_weight_g': None, 'units_per_bag': None, 'unit_weight_g': None})
        self.assertTrue(any('non configurée' in h for h in r.data['hypotheses']))
        self.assertFalse(any('non appliquée' in h for h in r.data['hypotheses']))

    def test_other_types_have_no_conversion_fields(self):
        stock(self.k1, 'YEAST', '3')
        r = self.get(self.u['DIRECTION'], type='YEAST', date=TODAY.isoformat())
        self.assertNotIn('conversion', r.data)
        self.assertNotIn('initial_bags', self.row(r, 'P1'))

    def test_rights_unchanged_for_salt(self):
        self.configure()
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'):
            self.assertEqual(self.get(self.u[role], type='SALT').status_code, 200, role)
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(self.get(self.u[role], type='SALT').status_code, 403, role)
        g = self.get(self.u['GERANT'], type='SALT')
        self.assertEqual([x['code'] for x in g.data['rows']], ['P1'])

    def test_type_api_exposes_and_validates_fields(self):
        ct = ConsumableType.objects.get(code='SALT')
        url = f'/api/production/consumable-types/{ct.pk}/'
        r = cl(self.u['GERANT']).get(url)
        self.assertEqual(r.status_code, 200)
        self.assertIn('bag_weight_g', r.data)
        self.assertEqual(cl(self.u['GERANT']).patch(
            url, {'bag_weight_g': '20000', 'units_per_bag': 204}, format='json').status_code, 403)
        ok = cl(self.u['DIRECTION']).patch(
            url, {'bag_weight_g': '20000', 'units_per_bag': 204}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
        bad = cl(self.u['DIRECTION']).patch(url, {'units_per_bag': 0}, format='json')
        self.assertEqual(bad.status_code, 400)
        half = cl(self.u['DIRECTION']).patch(url, {'bag_weight_g': None}, format='json')
        self.assertEqual(half.status_code, 400)  # un seul des deux champs
