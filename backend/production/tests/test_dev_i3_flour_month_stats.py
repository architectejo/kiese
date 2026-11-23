"""Lot I-3 : statistiques mensuelles de la farine. Donnees entierement fictives,
valeurs attendues calculees a la main (voir commentaires)."""
import datetime
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Node, User
from production.models import ConsumableMovement, ConsumableStock, ProductionSession

URL = '/api/production/consumables/flour-month-stats/'


def mk(username, role, node=None):
    return User.objects.create(username=username, role=role, node=node, first_name=username, last_name='Qa')


def cl(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


def at(day):
    return timezone.make_aware(datetime.datetime(2026, 11, day, 12, 0))


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.siege, _ = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege', 'is_active': False})
        cls.p1 = Node.objects.create(code='Q1', name='Fictive 1')
        cls.p2 = Node.objects.create(code='Q2', name='Fictive 2')
        cls.p9 = Node.objects.create(code='Q9', name='Fictive inactive', is_active=False)
        Node.objects.exclude(code__in=['SIEGE', 'Q1', 'Q2', 'Q9']).update(is_active=False)  # noeuds semes
        cls.u = {
            'ADMIN': mk('i3_admin', 'ADMIN'), 'DIRECTION': mk('i3_dir', 'DIRECTION'),
            'COMPTABLE': mk('i3_compta', 'COMPTABLE'),
            'GERANT1': mk('i3_g1', 'GERANT', cls.p1), 'GERANT0': mk('i3_g0', 'GERANT'),
            'FACTURIER': mk('i3_fact', 'FACTURIER', cls.p1), 'LIVREUR': mk('i3_liv', 'LIVREUR', cls.p1),
        }
        # Stock direction : 100 au depart, puis deux achats le 2 novembre.
        stock = ConsumableStock.objects.create(node=cls.siege, consumable_type='FLOUR', quantity=D('100'), unit='sac')
        for qty, price in ((D('40'), D('1000')), (D('10'), D('1200'))):
            m = ConsumableMovement.objects.create(
                node=cls.siege, stock=stock, movement_type='ENTRY', quantity=qty, unit_price=price)
            ConsumableMovement.objects.filter(pk=m.pk).update(created_at=at(2))
        S = ProductionSession.objects.create
        S(node=cls.p1, team='A', date='2026-11-01', flour_sacks_used=D('2'), is_closed=True)
        S(node=cls.p2, team='A', date='2026-11-01', flour_sacks_used=D('1'), is_closed=True)
        S(node=cls.p1, team='A', date='2026-11-02', flour_sacks_used=D('1.5'), is_closed=True)
        S(node=cls.p1, team='B', date='2026-11-02', flour_sacks_used=D('0.5'), is_closed=False)
        S(node=cls.p2, team='A', date='2026-11-03', flour_sacks_used=D('4'), is_closed=True)
        S(node=cls.p9, team='A', date='2026-11-03', flour_sacks_used=D('5'), is_closed=True)  # inactive : ignoree

    def get(self, who, query='?month=2026-11'):
        return cl(self.u[who] if who else None).get(URL + query)


class Calculation(Base):
    def test_hand_computed_values(self):
        r = self.get('DIRECTION')
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual(b['month'], '2026-11')
        self.assertEqual(b['days_in_month'], 30)
        self.assertEqual([x['code'] for x in b['bakeries']], ['Q1', 'Q2'])  # ni SIEGE ni inactive
        self.assertEqual(len(b['rows']), 30)
        self.assertEqual(b['rows'][0]['date'], '2026-11-01')
        self.assertEqual(b['rows'][29]['date'], '2026-11-30')
        d1, d2, d3, d4 = b['rows'][:4]
        self.assertEqual(d1['consumption'], {'Q1': '2.00', 'Q2': '1.00'})
        self.assertEqual(d1['total'], '3.00')
        self.assertEqual(d2['consumption'], {'Q1': '2.00', 'Q2': '0.00'})  # ouverte + cloturee comptees
        self.assertEqual(d2['open_sessions'], 1)
        self.assertEqual(d1['open_sessions'], 0)
        self.assertEqual(d3['consumption'], {'Q1': '0.00', 'Q2': '4.00'})
        self.assertEqual(d3['total'], '4.00')
        # achats du 2 : 40 + 10 = 50 sacs ; PT = 40*1000 + 10*1200 = 52000 ; PU = 1040
        self.assertEqual((d2['entry_quantity'], d2['total_price'], d2['unit_price']), ('50.00', '52000.00', '1040.00'))
        self.assertEqual((d1['entry_quantity'], d1['unit_price'], d1['total_price']), ('0.00', None, '0.00'))
        # solde : 100 -3 = 97 ; +50 -2 = 145 ; -4 = 141 ; puis plat
        self.assertEqual([d1['balance'], d2['balance'], d3['balance'], d4['balance']],
                         ['97.00', '145.00', '141.00', '141.00'])
        self.assertEqual(b['opening_balance'], '100.00')
        self.assertEqual(b['closing_balance'], '141.00')
        s = b['summary']
        self.assertEqual(s['total'], {'Q1': '4.00', 'Q2': '5.00', 'total': '9.00'})
        self.assertEqual(s['active_days'], {'Q1': 2, 'Q2': 2, 'total': 3})
        self.assertEqual(s['average_per_day'], {'Q1': '2.00', 'Q2': '2.50', 'total': '3.00'})
        self.assertEqual(s['average_per_calendar_day'], {'Q1': '0.13', 'Q2': '0.17', 'total': '0.30'})
        self.assertEqual(b['purchases'], {'quantity': '50.00', 'total_price': '52000.00', 'average_unit_price': '1040.00'})
        self.assertNotIn('ecart', ' '.join(b['summary'].keys()))

    def test_no_float_in_payload(self):
        def walk(x):
            if isinstance(x, float):
                self.fail('float dans la reponse')
            if isinstance(x, dict):
                [walk(v) for v in x.values()]
            if isinstance(x, list):
                [walk(v) for v in x]
        walk(self.get('ADMIN').json())

    def test_month_without_data(self):
        b = self.get('COMPTABLE', '?month=2026-05').json()
        self.assertEqual(len(b['rows']), 31)
        self.assertEqual(b['summary']['total']['total'], '0.00')
        self.assertEqual(b['summary']['average_per_day']['total'], '0.00')
        self.assertTrue(all(r['balance'] == '100.00' and r['total'] == '0.00' for r in b['rows']))
        self.assertEqual(b['purchases']['quantity'], '0.00')
        self.assertIsNone(b['purchases']['average_unit_price'])

    def test_leap_february(self):
        self.assertEqual(self.get('ADMIN', '?month=2024-02').json()['days_in_month'], 29)

    def test_node_filter_for_hq(self):
        b = self.get('ADMIN', '?month=2026-11&node=q2').json()
        self.assertEqual([x['code'] for x in b['bakeries']], ['Q2'])
        self.assertEqual(b['summary']['total'], {'Q2': '5.00', 'total': '5.00'})
        b = self.get('ADMIN', f'?month=2026-11&node={self.p1.pk}').json()
        self.assertEqual([x['code'] for x in b['bakeries']], ['Q1'])

    def test_bad_node_filter_is_400(self):
        for q in ('SIEGE', 'Q9', 'ZZZ', '0', '-3', '99999999999'):
            r = self.get('ADMIN', f'?month=2026-11&node={q}')
            self.assertEqual(r.status_code, 400, q)
            self.assertIn('detail', r.json())


class Roles(Base):
    def test_allowed_and_denied(self):
        for who in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT1'):
            self.assertEqual(self.get(who).status_code, 200, who)
        for who in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(self.get(who).status_code, 403, who)
        self.assertEqual(self.get(None).status_code, 401)

    def test_manager_isolation(self):
        b = self.get('GERANT1', '?month=2026-11&node=Q2').json()  # node ignore
        self.assertEqual([x['code'] for x in b['bakeries']], ['Q1'])
        self.assertEqual(b['summary']['total'], {'Q1': '4.00', 'total': '4.00'})
        self.assertFalse(b['direction_visible'])
        for k in ('purchases', 'opening_balance', 'closing_balance'):
            self.assertNotIn(k, b)
        self.assertNotIn('balance', b['rows'][0])
        self.assertNotIn('entry_quantity', b['rows'][0])

    def test_manager_without_node_sees_nothing(self):
        b = self.get('GERANT0').json()
        self.assertEqual(b['bakeries'], [])
        self.assertEqual(b['summary']['total'], {'total': '0.00'})


class Validation(Base):
    def test_bad_months_are_400_french(self):
        for q in ('', '?month=', '?month=2026-13', '?month=2026-00', '?month=2026-1', '?month=202611',
                  '?month=1999-12', '?month=2201-01', '?month=2026-11-01', '?month=%20%202026-11',
                  '?month=2026-11%0A', '?month=abc', '?month=%D9%A2%D9%A0%D9%A2%D9%A6-11',
                  '?month=2026-1e', '?month=9999-99', '?month=2099-01', '?month=2026-11&month=x'):
            r = self.get('ADMIN', q)
            self.assertEqual(r.status_code, 400, q)
            self.assertIn('detail', r.json(), q)

    def test_limits_ok(self):
        self.assertEqual(self.get('ADMIN', '?month=2000-01').status_code, 200)
        self.assertEqual(self.get('ADMIN', '?month=2027-11').status_code, 200)  # +12 mois


class Performance(Base):
    def test_bounded_queries_30_days_8_bakeries(self):
        nodes = [Node.objects.create(code=f'W{i}', name=f'W{i}') for i in range(6)] + [self.p1, self.p2]
        rows = [ProductionSession(node=n, team='B', date=datetime.date(2026, 11, d), flour_sacks_used=D('1.25'))
                for n in nodes for d in range(10, 31)]
        ProductionSession.objects.bulk_create(rows)
        self.get('DIRECTION')  # amorce le singleton Config du middleware (hors vue)
        with self.assertNumQueries(7):  # 6 de la vue + 1 lecture Config du middleware
            r = self.get('DIRECTION')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()['bakeries']), 8)
        with self.assertNumQueries(3):  # 2 de la vue + Config
            self.assertEqual(self.get('GERANT1').status_code, 200)
