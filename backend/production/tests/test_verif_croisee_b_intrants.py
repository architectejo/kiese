"""B-5 : verification croisee (dev-b) de BUG-1060/1061 (statistiques d'intrants, sel).
Valeurs FICTIVES, calculees a la main, independantes des tests de dev-a."""
from datetime import timedelta
from decimal import Decimal as D

from django.utils import timezone

from core.models import Node
from core.tests.test_permissions_regression_2026_11_19 import Base, cl
from production.models import (ConsumableCount, ConsumableInventory, ConsumableMovement,
                               ConsumableStock, ConsumableType, ProductionSession)

URL = '/api/production/intrants-stats/'
TODAY = timezone.localdate()
E, X = ConsumableMovement.MovementType.ENTRY, ConsumableMovement.MovementType.EXIT


def setstock(node, code, qty):
    s, _ = ConsumableStock.objects.get_or_create(node=node, consumable_type=code,
                                                 defaults={'node_origin': node.code})
    ConsumableStock.objects.filter(pk=s.pk).update(quantity=D(qty))
    return ConsumableStock.objects.get(pk=s.pk)


def mv(node, st, kind, qty, session=None):
    return ConsumableMovement.objects.create(node=node, stock=st, movement_type=kind,
                                             quantity=D(qty), session=session, node_origin=node.code)


def declare(node, code, qty):
    inv, _ = ConsumableInventory.objects.get_or_create(
        node=node, inventory_date=TODAY, defaults={'node_origin': node.code})
    ConsumableCount.objects.create(node=node, consumable_type=code, count_date=TODAY,
                                   system_quantity=D('0'), physical_quantity=D(qty), gap=D('0'),
                                   inventory=inv)


class VerifCroiseeIntrants(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code, label, unit in [('FLOUR', 'Farine', 'sacs'), ('YEAST', 'Levure', 'paquets'),
                                  ('SALT', 'Sel', 'g'), ('OIL', 'Huile', 'litres')]:
            ConsumableType.objects.get_or_create(code=code, defaults={'label': label, 'unit': unit})
        ConsumableType.objects.filter(code='SALT').update(bag_weight_g=D('20000'), units_per_bag=204)
        cls.siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege', 'is_active': False})[0]

    def get(self, user, **p):
        return cl(user).get(URL, p)

    def rows(self, r):
        return {x['code']: x for x in r.data['rows']}

    def test_farine_calcul_complet(self):
        # P1 : initial 20, entree 10, sortie libre 4, fournee de 5 sacs -> stock courant 21 apres mouvements
        sess = ProductionSession.objects.create(node=self.k1, team='B', date=TODAY,
                                                flour_sacks_used=D('5'), declared_by=self.u['GERANT'])
        st = setstock(self.k1, 'FLOUR', '20')  # le mouvement ajuste le stock : 20+10-4-5 = 21
        mv(self.k1, st, E, '10')
        mv(self.k1, st, X, '4')
        mv(self.k1, st, X, '5', session=sess)
        declare(self.k1, 'FLOUR', '20')
        setstock(self.k2, 'FLOUR', '7')
        setstock(self.siege, 'FLOUR', '3')
        r = self.get(self.u['DIRECTION'], type='FLOUR', date=TODAY.isoformat())
        self.assertEqual(r.status_code, 200, r.data)
        rows = self.rows(r)
        a = rows['P1']
        self.assertEqual(D(a['initial']), D('20'))
        self.assertEqual(D(a['entry']), D('10'))
        self.assertEqual(D(a['exit']), D('4'))
        self.assertEqual(D(a['total_before_production']), D('26'))
        self.assertEqual(D(a['consumption']), D('5'))
        self.assertEqual(D(a['balance']), D('21'))
        self.assertEqual(D(a['consumption_index']), D('1'))
        self.assertEqual(D(a['declared_remaining']), D('20'))
        self.assertEqual(D(a['gap']), D('-1'))          # declare - comptable
        b = rows['P2']
        self.assertIsNone(b['declared_remaining'])
        self.assertIsNone(b['gap'])                      # vide si non declare
        self.assertIsNone(b['consumption_index'])        # 0 sac : pas de division par zero
        self.assertEqual(D(b['balance']), D('7'))
        d1 = rows['D1']
        self.assertTrue(d1['is_direction'])
        self.assertEqual(D(d1['balance']), D('3'))
        t = r.data['totals']
        self.assertEqual(D(t['balance']), D('31'))       # 21 + 7 + 3
        self.assertEqual(D(t['gap']), D('-1'))           # seule ligne declaree

    def test_jour_passe_ignore_les_mouvements_du_jour(self):
        st = setstock(self.k1, 'YEAST', '3')
        mv(self.k1, st, E, '2')
        r = self.get(self.u['ADMIN'], type='YEAST', date=(TODAY - timedelta(days=3)).isoformat())
        a = self.rows(r)['P1']
        self.assertEqual(D(a['entry']), D('0'))
        self.assertEqual(D(a['initial']), D('3'))        # 5 - entree du jour 2

    def test_sel_conversion_exacte(self):
        setstock(self.k1, 'SALT', '20000')
        setstock(self.k2, 'SALT', '1000')
        r = self.get(self.u['DIRECTION'], type='SALT', date=TODAY.isoformat())
        self.assertEqual(r.data['conversion']['units_per_bag'], 204)
        self.assertEqual(D(r.data['conversion']['bag_weight_g']), D('20000'))
        self.assertEqual(D(r.data['conversion']['unit_weight_g']), D('98.0392'))
        rows = self.rows(r)
        self.assertEqual(D(rows['P1']['balance_bags']), D('1.000'))
        self.assertEqual(D(rows['P1']['balance_units']), D('204.0'))
        self.assertEqual(D(rows['P2']['balance_bags']), D('0.050'))
        self.assertEqual(D(rows['P2']['balance_units']), D('10.2'))
        self.assertEqual(D(r.data['totals']['balance_units']), D('214.2'))
        self.assertEqual(D(r.data['totals']['balance']), D('21000'))   # stock reste en grammes

    def test_sel_non_configure_et_autres_types_sans_equivalents(self):
        ConsumableType.objects.filter(code='SALT').update(bag_weight_g=None, units_per_bag=None)
        setstock(self.k1, 'SALT', '500')
        r = self.get(self.u['ADMIN'], type='SALT', date=TODAY.isoformat())
        self.assertIsNone(self.rows(r)['P1']['balance_units'])
        r = self.get(self.u['ADMIN'], type='OIL', date=TODAY.isoformat())
        self.assertNotIn('balance_units', self.rows(r)['P1'])

    def test_roles_et_D1(self):
        q = dict(type='FLOUR', date=TODAY.isoformat())
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = self.get(self.u[role], **q)
            self.assertEqual(r.status_code, 200, role)
            self.assertTrue({'P1', 'P2', 'D1'} <= set(self.rows(r)), role)
        g = self.get(self.u['GERANT'], **q)
        self.assertEqual(g.status_code, 200)
        self.assertEqual(set(self.rows(g)), {'P1'})      # sa boulangerie, sans D1
        self.assertEqual(self.get(self.u['GERANT'], node='P2', **q).status_code, 404)
        self.assertEqual(self.get(self.u['GERANT'], node='SIEGE', **q).status_code, 404)
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(self.get(self.u[role], **q).status_code, 403, role)
        self.assertEqual(cl().get(URL, q).status_code, 401)

    def test_parametres_invalides(self):
        u = self.u['ADMIN']
        for p in (dict(), dict(type='SUCRE'), dict(type='FLOUR', date='24/11/2026'),
                  dict(type='FLOUR', date='2026-02-30'), dict(type='FLOUR', date='1999-01-01')):
            r = self.get(u, **p)
            self.assertEqual(r.status_code, 400, p)
            self.assertIn('detail', r.data)
