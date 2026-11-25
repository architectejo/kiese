"""BUG-386 : vue globale des consommables (direction), envoi direction -> boulangeries,
Inventaire Physique journalier (remarque.md l.472). Données fictives uniquement."""
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock

from django.utils import timezone

from core.models import ActivityLog, Node
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk
from production.models import (ConsumableCount, ConsumableInventory, ConsumableMovement,
                               ConsumableStock, ConsumableType)

G = '/api/production/consumables/global/'
DISPATCH = '/api/production/consumables/dispatch/'
INV = '/api/production/inventories/'


class B(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code, label, unit in [('FLOUR', 'Farine', 'sac'), ('YEAST', 'Levure', 'paquet'),
                                  ('SALT', 'Sel', 'g'), ('OIL', 'Huile', 'L')]:
            ConsumableType.objects.get_or_create(code=code, defaults={'label': label, 'unit': unit})
        cls.siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siège', 'is_active': False})[0]
        cls.ssiege = cls.stock(cls.siege, 'FLOUR', '100')
        cls.s1 = cls.stock(cls.k1, 'FLOUR', '5')
        cls.s2 = cls.stock(cls.k2, 'FLOUR', '7')
        cls.yeast1 = cls.stock(cls.k1, 'YEAST', '2.5')

    @staticmethod
    def stock(node, code, qty):
        s, _ = ConsumableStock.objects.get_or_create(node=node, consumable_type=code,
                                                     defaults={'node_origin': node.code})
        ConsumableStock.objects.filter(pk=s.pk).update(quantity=D(qty))
        s.refresh_from_db()
        return s

    def q(self, st):
        st.refresh_from_db()
        return st.quantity


class GlobalViewTests(B):
    def test_hq_roles_read_matrix(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = cl(self.u[role]).get(G)
            self.assertEqual(r.status_code, 200, role)
        d = r.data
        codes = {t['code'] for t in d['types']}
        self.assertTrue({'FLOUR', 'YEAST', 'SALT', 'OIL'} <= codes)
        rows = {n['code']: n for n in d['nodes']}
        self.assertEqual(rows['P1']['stocks']['FLOUR'], '5.000')
        self.assertEqual(rows['P1']['stocks']['YEAST'], '2.500')
        self.assertEqual(rows['P2']['stocks']['FLOUR'], '7.000')
        self.assertNotIn('SIEGE', rows)
        self.assertEqual(d['direction']['stocks']['FLOUR'], '100.000')
        allq = sum(x.quantity for x in ConsumableStock.objects.filter(consumable_type='FLOUR'))
        self.assertEqual(D(d['totals_group']['FLOUR']), allq)
        self.assertEqual(D(d['totals_bakeries']['FLOUR']), allq - D('100'))
        self.assertIsInstance(d['totals_bakeries']['FLOUR'], str)

    def test_others_refused(self):
        self.assertEqual(cl(self.u['GERANT']).get(G).status_code, 403)
        self.assertEqual(cl(self.u['FACTURIER']).get(G).status_code, 403)
        self.assertEqual(cl(self.u['LIVREUR']).get(G).status_code, 403)
        self.assertIn(cl().get(G).status_code, (401, 403))


class DispatchTests(B):
    def body(self, **kw):
        b = {'consumable_type': 'FLOUR', 'note': 'dépannage',
             'allocations': [{'node': self.k1.pk, 'quantity': '10'}, {'node': 'P2', 'quantity': '2.5'}]}
        b.update(kw)
        return b

    def test_dispatch_atomic_nominal(self):
        n_log = ActivityLog.objects.count()
        r = cl(self.u['DIRECTION']).post(DISPATCH, self.body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['total_sent'], '12.500')
        self.assertEqual(r.data['direction_remaining'], '87.500')
        self.assertEqual(self.q(self.ssiege), D('87.500'))
        self.assertEqual(self.q(self.s1), D('15.000'))
        self.assertEqual(self.q(self.s2), D('9.500'))
        self.assertEqual(ConsumableMovement.objects.filter(stock=self.ssiege, movement_type='EXIT').count(), 2)
        self.assertEqual(ConsumableMovement.objects.filter(stock=self.s1, movement_type='ENTRY', quantity=D('10')).count(), 1)
        self.assertGreater(ActivityLog.objects.count(), n_log)
        # somme nulle au niveau du groupe
        self.assertEqual(sum(x.quantity for x in ConsumableStock.objects.filter(consumable_type='FLOUR')), D('112'))

    def test_creates_destination_stock_if_missing(self):
        ConsumableStock.objects.filter(node=self.k2, consumable_type='OIL').delete()
        self.stock(self.siege, 'OIL', '20')
        r = cl(self.u['ADMIN']).post(DISPATCH, {'consumable_type': 'OIL',
                                                'allocations': [{'node': self.k2.pk, 'quantity': '1.25'}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(ConsumableStock.objects.get(node=self.k2, consumable_type='OIL').quantity, D('1.250'))

    def test_insufficient_refused_nothing_written(self):
        b = self.body(allocations=[{'node': self.k1.pk, 'quantity': '60'}, {'node': self.k2.pk, 'quantity': '50'}])
        r = cl(self.u['DIRECTION']).post(DISPATCH, b, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('insuffisant', r.data['detail'])
        self.assertEqual(self.q(self.ssiege), D('100'))
        self.assertEqual(self.q(self.s1), D('5'))
        self.assertEqual(ConsumableMovement.objects.count(), 0)

    def test_validation_400(self):
        c = cl(self.u['DIRECTION'])
        bad = [
            self.body(allocations=[{'node': self.k1.pk, 'quantity': '0'}]),
            self.body(allocations=[{'node': self.k1.pk, 'quantity': '-3'}]),
            self.body(allocations=[{'node': self.k1.pk, 'quantity': 'abc'}]),
            self.body(allocations=[{'node': self.k1.pk, 'quantity': 'NaN'}]),
            self.body(allocations=[{'node': self.k1.pk, 'quantity': '1.2345'}]),
            self.body(allocations=[{'node': self.k1.pk, 'quantity': None}]),
            self.body(allocations=[]),
            self.body(allocations=[{'node': 'ZZZ', 'quantity': '1'}]),
            self.body(allocations=[{'node': 'SIEGE', 'quantity': '1'}]),
            self.body(allocations=[{'node': self.k1.pk, 'quantity': '1'}, {'node': 'P1', 'quantity': '1'}]),
            self.body(consumable_type='NOPE'),
        ]
        for b in bad:
            r = c.post(DISPATCH, b, format='json')
            self.assertEqual(r.status_code, 400, (b, r.content))
            self.assertIn('detail', r.data)
        self.assertEqual(self.q(self.ssiege), D('100'))
        self.assertEqual(ConsumableMovement.objects.count(), 0)

    def test_decimal_precision_no_float(self):
        r = cl(self.u['DIRECTION']).post(DISPATCH, {'consumable_type': 'YEAST', 'allocations': [
            {'node': self.k1.pk, 'quantity': '0.25'}]}, format='json')
        self.assertEqual(r.status_code, 400)  # stock direction levure = 0
        self.stock(self.siege, 'YEAST', '1.00')
        for _ in range(3):
            r = cl(self.u['DIRECTION']).post(DISPATCH, {'consumable_type': 'YEAST', 'allocations': [
                {'node': self.k1.pk, 'quantity': '0.25'}]}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.q(self.yeast1), D('3.250'))
        self.assertEqual(ConsumableStock.objects.get(node=self.siege, consumable_type='YEAST').quantity, D('0.250'))

    def test_roles_refused(self):
        for who in (self.u['COMPTABLE'], self.u['GERANT'], self.u['FACTURIER'], self.u['LIVREUR'], self.u2['GERANT']):
            r = cl(who).post(DISPATCH, self.body(), format='json')
            self.assertEqual(r.status_code, 403, who.role)
        self.assertEqual(self.q(self.ssiege), D('100'))
        self.assertEqual(self.q(self.s1), D('5'))


class InventoryTests(B):
    def lines(self, far='4.5'):
        return [{'consumable_type': 'FLOUR', 'physical_quantity': far},
                {'consumable_type': 'YEAST', 'physical_quantity': '2.25', 'notes': 'paquet ouvert'}]

    def post(self, user=None, **kw):
        body = {'comment': 'RAS', 'lines': self.lines()}
        body.update(kw)
        return cl(user or self.u['GERANT']).post(INV, body, format='json')

    def test_create_once_per_day_then_locked(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['node_code'], 'P1')
        by = {ln['consumable_type']: ln for ln in r.data['lines']}
        self.assertEqual(by['FLOUR']['system_quantity'], '5.000')
        self.assertEqual(by['FLOUR']['gap'], '-0.500')
        self.assertEqual(by['YEAST']['gap'], '-0.250')
        self.assertEqual(self.q(self.s1), D('5'))  # l'inventaire ne modifie pas le stock
        r2 = self.post(lines=self.lines('9'))
        self.assertEqual(r2.status_code, 400)
        self.assertIn('déjà', r2.data['detail'])
        self.assertEqual(ConsumableInventory.objects.filter(node=self.k1).count(), 1)
        self.assertEqual(ConsumableCount.objects.filter(node=self.k1).count(), 2)

    def test_lines_not_editable_comment_is_(self):
        inv_id = self.post().data['id']
        g = cl(self.u['GERANT'])
        u = f'{INV}{inv_id}/'
        r = g.patch(u, {'lines': [], 'comment': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = g.patch(u, {'inventory_date': '2020-01-01'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(g.put(u, {'comment': 'x'}, format='json').status_code, 405)
        r = g.patch(u, {'comment': 'Sac de farine mouillé'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['comment'], 'Sac de farine mouillé')
        self.assertEqual(ConsumableCount.objects.filter(inventory_id=inv_id).count(), 2)
        # les lignes ne sont pas modifiables via l'ancien endpoint de comptage
        cnt = ConsumableCount.objects.filter(inventory_id=inv_id).first()
        self.assertEqual(g.patch(f'/api/production/counts/{cnt.pk}/', {'physical_quantity': '1'}, format='json').status_code, 400)
        self.assertEqual(g.delete(f'/api/production/counts/{cnt.pk}/').status_code, 400)
        # ni créées à la main le même jour
        r = g.post('/api/production/counts/', {'consumable_type': 'SALT', 'count_date': str(timezone.localdate()),
                                               'physical_quantity': '3'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_next_day_allowed(self):
        self.assertEqual(self.post().status_code, 201)
        from core.workday import work_date_for
        tomorrow = work_date_for(self.k1) + timedelta(days=1)
        with mock.patch('core.workday.work_date_for', return_value=tomorrow):  # Q-018 : journee de midi a midi
            r = self.post(lines=self.lines('3'))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['inventory_date'], tomorrow.isoformat())
        self.assertEqual(ConsumableInventory.objects.filter(node=self.k1).count(), 2)

    def test_validation(self):
        g = self.u['GERANT']
        for lines in ([], [{'consumable_type': 'FLOUR', 'physical_quantity': '-1'}],
                      [{'consumable_type': 'FLOUR', 'physical_quantity': 'x'}],
                      [{'consumable_type': 'FLOUR', 'physical_quantity': '1.0001'}],
                      [{'consumable_type': 'NOPE', 'physical_quantity': '1'}],
                      [{'consumable_type': 'FLOUR', 'physical_quantity': '1'}, {'consumable_type': 'FLOUR', 'physical_quantity': '2'}]):
            r = self.post(g, lines=lines)
            self.assertEqual(r.status_code, 400, (lines, r.content))
        self.assertEqual(ConsumableInventory.objects.count(), 0)
        self.assertEqual(self.post(g, lines=[{'consumable_type': 'FLOUR', 'physical_quantity': '0'}]).status_code, 201)

    def test_only_gerant_creates(self):
        for who in (self.u['ADMIN'], self.u['DIRECTION'], self.u['COMPTABLE'], self.u['FACTURIER'], self.u['LIVREUR']):
            self.assertEqual(self.post(who).status_code, 403, who.role)
        self.assertEqual(ConsumableInventory.objects.count(), 0)

    def test_isolation_and_node_forging(self):
        # `node` dans le corps ignoré : K1 impose
        r = self.post(node=self.k2.pk)
        self.assertEqual(r.status_code, 201)
        inv_id = r.data['id']
        self.assertEqual(ConsumableInventory.objects.get(pk=inv_id).node_id, self.k1.pk)
        g2 = cl(self.u2['GERANT'])
        self.assertEqual(g2.get(f'{INV}{inv_id}/').status_code, 404)
        self.assertEqual(g2.patch(f'{INV}{inv_id}/', {'comment': 'pirate'}, format='json').status_code, 404)
        self.assertEqual(g2.get(f'{INV}node/P1/').status_code, 404)
        self.assertEqual(g2.get(INV).data, [])
        self.assertEqual(ConsumableInventory.objects.get(pk=inv_id).comment, 'RAS')
        # K2 peut saisir le sien le même jour
        self.assertEqual(cl(self.u2['GERANT']).post(INV, {'lines': self.lines()}, format='json').status_code, 201)
        # facturier / livreur refusés en lecture
        for who in (self.u['FACTURIER'], self.u['LIVREUR']):
            self.assertEqual(cl(who).get(INV).status_code, 403)
            self.assertEqual(cl(who).get(f'{INV}node/P1/').status_code, 403)

    def test_direction_reads_node_detail(self):
        self.post()
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = cl(self.u[role]).get(f'{INV}node/{self.k1.pk}/')
            self.assertEqual(r.status_code, 200, role)
            self.assertEqual(r.data['code'], 'P1')
            self.assertEqual(r.data['inventory']['comment'], 'RAS')
            self.assertEqual(len(r.data['inventory']['lines']), 2)
            self.assertEqual(r.data['history_dates'], [timezone.localdate().isoformat()])
        r = cl(self.u['DIRECTION']).get(f'{INV}node/P2/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['inventory'])
        self.assertEqual(cl(self.u['DIRECTION']).get(f'{INV}node/ZZZ/').status_code, 404)
        self.assertEqual(cl(self.u['DIRECTION']).get(f'{INV}?node=P1').data[0]['node_code'], 'P1')
        # la matrice globale indique le dernier inventaire
        g = cl(self.u['DIRECTION']).get(G).data
        row = [n for n in g['nodes'] if n['code'] == 'P1'][0]
        self.assertTrue(row['last_inventory']['has_comment'])
        # HQ ne peut pas modifier le commentaire
        inv_id = ConsumableInventory.objects.get().pk
        self.assertEqual(cl(self.u['DIRECTION']).patch(f'{INV}{inv_id}/', {'comment': 'x'}, format='json').status_code, 403)

    def test_today_status(self):
        g = cl(self.u['GERANT'])
        self.assertFalse(g.get(f'{INV}today/').data['done'])
        self.post()
        r = g.get(f'{INV}today/').data
        self.assertTrue(r['done'])
        self.assertEqual(r['inventory']['comment'], 'RAS')
