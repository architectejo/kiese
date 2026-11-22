"""BUG-503/504/505 + audit FK : un non-siege ne reference que des objets de son noeud."""
from decimal import Decimal as Dc

from core.tests.test_permissions_regression_2026_11_19 import Base, cl
from production.models import ConsumableMovement, ConsumableStock
from treasury.models import FacturierReport


def _stock(node, code='FAR'):
    return ConsumableStock.objects.get_or_create(
        node=node, consumable_type=code, defaults={'unit': 'sac', 'node_origin': node.code})[0]


class MovementForeignStockTests(Base):
    def setUp(self):
        self.st1, self.st2 = _stock(self.k1), _stock(self.k2)

    def _post(self, c, stock, **extra):
        body = {'stock': str(stock.pk), 'movement_type': 'ENTRY', 'quantity': '5', 'unit_price': '1000'}
        body.update(extra)
        return c.post('/api/production/movements/', body, format='json')

    def test_foreign_stock_refused_without_effect(self):
        for user in (self.u['GERANT'], self.u2['GERANT']):
            foreign = self.st2 if user.node_id == self.k1.pk else self.st1
            n0, q0 = ConsumableMovement.objects.count(), ConsumableStock.objects.get(pk=foreign.pk).quantity
            r = self._post(cl(user), foreign, node=foreign.node_id)
            self.assertEqual(r.status_code, 404, r.content)
            self.assertIn('detail', r.data)
            self.assertEqual(ConsumableMovement.objects.count(), n0)
            self.assertEqual(ConsumableStock.objects.get(pk=foreign.pk).quantity, q0)

    def test_unknown_stock_same_answer(self):
        r = self._post(cl(self.u['GERANT']), self.st2)
        r2 = cl(self.u['GERANT']).post('/api/production/movements/', {
            'stock': '00000000-0000-0000-0000-000000000000', 'movement_type': 'ENTRY', 'quantity': '1'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertIn(r2.status_code, (400, 404))

    def test_own_stock_ok(self):
        r = self._post(cl(self.u['GERANT']), self.st1)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(ConsumableStock.objects.get(pk=self.st1.pk).quantity, Dc('5'))

    def test_hq_allowed_on_any_node_and_mismatch_refused(self):
        r = self._post(cl(self.u['DIRECTION']), self.st2, node=self.k2.pk)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['node'], self.k2.pk)
        r = self._post(cl(self.u['DIRECTION']), self.st2, node=self.k1.pk)
        self.assertEqual(r.status_code, 400, r.content)

    def test_foreign_session_refused(self):
        r = self._post(cl(self.u['GERANT']), self.st1, session=str(self.s2.pk))
        self.assertEqual(r.status_code, 404, r.content)

    def test_disposal_foreign_session_refused(self):
        from core.models import BreadPrice
        bp = BreadPrice.objects.first()
        if bp is None:
            bp = BreadPrice.objects.create(label='T', unit_price=100)
        r = cl(self.u['GERANT']).post('/api/production/disposals/', {
            'session': str(self.s2.pk), 'bread_price': bp.pk, 'disposal_type': 'DECLASSED', 'quantity': 1},
            format='json')
        self.assertEqual(r.status_code, 404, r.content)

    def test_other_roles_and_anonymous(self):
        for user in (self.u['FACTURIER'], self.u['LIVREUR']):
            self.assertIn(self._post(cl(user), self.st2).status_code, (403, 404))
        self.assertEqual(self._post(cl(), self.st2).status_code, 401)
        self.assertEqual(ConsumableStock.objects.get(pk=self.st2.pk).quantity, Dc('0'))


class FlourHistoryNodeTests(Base):
    def setUp(self):
        for node in (self.k1, self.k2):
            ConsumableMovement.objects.create(
                node=node, stock=_stock(node, 'FLOUR'), movement_type='ENTRY', quantity=Dc('2'),
                unit_price=Dc('1000'), supplier='', description='x', node_origin=node.code)

    def test_non_hq_confined_to_own_node(self):
        for user in (self.u['GERANT'], self.u['FACTURIER'], self.u['LIVREUR'], self.u2['GERANT']):
            r = cl(user).get(f'/api/production/movements/flour_history/?node={self.k2.pk}')
            if r.status_code == 403:
                continue
            self.assertEqual(r.status_code, 200)
            self.assertEqual({x['node'] for x in r.data}, {user.node.code}, user.role)

    def test_hq_can_filter_and_anonymous_401(self):
        r = cl(self.u['DIRECTION']).get(f'/api/production/movements/flour_history/?node={self.k2.pk}')
        self.assertEqual({x['node'] for x in r.data}, {'P2'})
        self.assertEqual(cl().get('/api/production/movements/flour_history/').status_code, 401)
