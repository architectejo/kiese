"""Contre-attaques testeur-permissions (2026-11-22-a) sur BUG-503/504/505/362.
Donnees fictives. Aucun correctif applicatif."""
from decimal import Decimal as Dc

from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk
from production.models import ConsumableMovement, ConsumableStock
from treasury.models import FacturierReport


def _stock(node, code='FAR', qty=None):
    s = ConsumableStock.objects.get_or_create(
        node=node, consumable_type=code, defaults={'unit': 'sac', 'node_origin': node.code})[0]
    if qty is not None:
        ConsumableStock.objects.filter(pk=s.pk).update(quantity=qty)
        s.refresh_from_db()
    return s


def rows(r):
    d = r.data
    return d['results'] if isinstance(d, dict) and 'results' in d else d


class V504Movements(Base):
    def setUp(self):
        self.st1, self.st2 = _stock(self.k1, qty=Dc('10')), _stock(self.k2, qty=Dc('10'))

    def q2(self):
        return ConsumableStock.objects.get(pk=self.st2.pk).quantity

    def test_sortie_on_foreign_stock_cannot_drain(self):
        g = cl(self.u['GERANT'])
        for extra in ({}, {'node': self.k2.pk}, {'node': self.k1.pk}):
            r = g.post('/api/production/movements/', {
                'stock': str(self.st2.pk), 'movement_type': 'EXIT', 'quantity': '10', **extra}, format='json')
            self.assertIn(r.status_code, (400, 404), (extra, r.status_code))
            self.assertEqual(self.q2(), Dc('10'), extra)

    def test_patch_put_own_movement_towards_foreign_stock(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/movements/', {
            'stock': str(self.st1.pk), 'movement_type': 'ENTRY', 'quantity': '1', 'unit_price': '10'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        url = f"/api/production/movements/{r.data['id']}/"
        for method in (g.patch, g.put):
            r2 = method(url, {'stock': str(self.st2.pk), 'node': self.k2.pk,
                              'movement_type': 'ENTRY', 'quantity': '99'}, format='json')
            self.assertGreaterEqual(r2.status_code, 400, (method, r2.status_code))
        self.assertEqual(self.q2(), Dc('10'))
        m = ConsumableMovement.objects.get(pk=r.data['id'])
        self.assertEqual(m.stock_id, self.st1.pk)
        self.assertEqual(m.node_id, self.k1.pk)

    def test_foreign_movement_detail_and_delete_404(self):
        m = ConsumableMovement.objects.create(
            node=self.k2, stock=self.st2, movement_type='ENTRY', quantity=Dc('1'),
            unit_price=Dc('1'), supplier='', description='x', node_origin='P2')
        g = cl(self.u['GERANT'])
        url = f'/api/production/movements/{m.pk}/'
        self.assertEqual(g.get(url).status_code, 404)
        self.assertEqual(g.patch(url, {'quantity': '5'}, format='json').status_code, 404)
        self.assertEqual(g.delete(url).status_code, 404)
        self.assertTrue(ConsumableMovement.objects.filter(pk=m.pk).exists())

    def test_list_node_param_does_not_leak(self):
        ConsumableMovement.objects.create(
            node=self.k2, stock=self.st2, movement_type='ENTRY', quantity=Dc('1'),
            unit_price=Dc('1'), supplier='', description='x', node_origin='P2')
        r = cl(self.u['GERANT']).get(f'/api/production/movements/?node={self.k2.pk}')
        self.assertEqual(len(rows(r)), 0)

    def test_foreign_session_in_patch_of_disposal_or_movement(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/movements/', {
            'stock': str(self.st1.pk), 'movement_type': 'ENTRY', 'quantity': '1', 'unit_price': '10'}, format='json')
        r2 = g.patch(f"/api/production/movements/{r.data['id']}/", {'session': str(self.s2.pk)}, format='json')
        self.assertEqual(r2.status_code, 404, r2.content)

    def test_facturier_livreur_cannot_move(self):
        for role in ('FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).post('/api/production/movements/', {
                'stock': str(self.st1.pk), 'movement_type': 'ENTRY', 'quantity': '1'}, format='json')
            self.assertEqual(r.status_code, 403, role)

    def test_hq_roles(self):
        # siege : OK sur tout noeud coherent ; COMPTABLE reste hors ecriture ou OK, jamais 5xx
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = cl(self.u[role]).post('/api/production/movements/', {
                'stock': str(self.st2.pk), 'movement_type': 'ENTRY', 'quantity': '1', 'unit_price': '5'},
                format='json')
            self.assertLess(r.status_code, 500, role)
            r = cl(self.u[role]).post('/api/production/movements/', {
                'stock': str(self.st2.pk), 'node': self.k1.pk, 'movement_type': 'ENTRY', 'quantity': '1'},
                format='json')
            self.assertIn(r.status_code, (400, 403), (role, r.status_code))


class V503Reports(Base):
    def body(self, **kw):
        return {'date': '2026-11-11', 'total_cash_sales': '1000', 'total_credit_sales': '0', **kw}

    def test_patch_put_forged_node_on_own_report(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/treasury/reports/', self.body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        url = f"/api/treasury/reports/{r.data['id']}/"
        for method in (g.patch, g.put):
            method(url, self.body(node=self.k2.pk), format='json')
        rep = FacturierReport.objects.get(pk=r.data['id'])
        self.assertEqual(rep.node_id, self.k1.pk)
        self.assertFalse(FacturierReport.objects.filter(node=self.k2).exists())

    def test_foreign_report_by_uuid(self):
        rep = FacturierReport.objects.create(node=self.k2, team='A', date='2026-11-10', node_origin='P2')
        g = cl(self.u['GERANT'])
        url = f'/api/treasury/reports/{rep.pk}/'
        self.assertEqual(g.get(url).status_code, 404)
        self.assertEqual(g.patch(url, {'total_cash_sales': '1'}, format='json').status_code, 404)
        self.assertEqual(g.delete(url).status_code, 404)
        self.assertEqual(g.post(url + 'validate/').status_code, 404)

    def test_forged_node_variants_form_data(self):
        g = cl(self.u['GERANT'])
        for node in (self.k2.pk, str(self.k2.pk), 999999, 'x', None, ''):
            r = g.post('/api/treasury/reports/', self.body(node=node, date='2026-11-14'), format='json')
            self.assertLess(r.status_code, 500, (node, r.status_code))
            self.assertFalse(FacturierReport.objects.filter(node=self.k2).exists(), node)
            FacturierReport.objects.filter(date='2026-11-14').delete()
        r = g.post('/api/treasury/reports/', {**self.body(date='2026-11-15'), 'node': str(self.k2.pk)})
        self.assertLess(r.status_code, 500)
        self.assertFalse(FacturierReport.objects.filter(node=self.k2).exists())

    def test_forged_facturier_and_node_origin_ignored(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/treasury/reports/', self.body(date='2026-11-16', facturier=self.u2['FACTURIER'].pk,
                                                       node_origin='P2'), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        rep = FacturierReport.objects.get(pk=r.data['id'])
        self.assertEqual(rep.facturier_id, self.u['GERANT'].pk)
        self.assertEqual(rep.node_origin, 'P1')

    def test_generate_forged_node_and_list_param(self):
        g = cl(self.u['GERANT'])
        FacturierReport.objects.create(node=self.k2, team='A', date='2026-11-10', node_origin='P2')
        r = g.get(f'/api/treasury/reports/?node={self.k2.pk}')
        self.assertEqual(len(rows(r)), 0)

    def test_hq_roles_report(self):
        for role in ('ADMIN', 'DIRECTION'):
            r = cl(self.u[role]).post('/api/treasury/reports/', self.body(node=self.k2.pk, date=f'2026-10-0{1 if role == "ADMIN" else 2}'), format='json')
            self.assertLess(r.status_code, 500, role)
        r = cl(self.u['COMPTABLE']).post('/api/treasury/reports/', self.body(node=self.k2.pk, date='2026-10-05'),
                                         format='json')
        self.assertLess(r.status_code, 500)


class V505FlourHistory(Base):
    def test_param_variants(self):
        for n in (self.k1, self.k2):
            ConsumableMovement.objects.create(
                node=n, stock=_stock(n, 'FLOUR'), movement_type='ENTRY', quantity=Dc('2'),
                unit_price=Dc('1'), supplier='', description='x', node_origin=n.code)
        for q in (f'?node={self.k2.pk}', f'?node={self.k2.code}', f'?node=&node={self.k2.pk}',
                  f'?node={self.k2.pk}&node={self.k1.pk}'):
            r = cl(self.u['GERANT']).get('/api/production/movements/flour_history/' + q)
            self.assertEqual(r.status_code, 200)
            self.assertNotIn('P2', {x['node'] for x in r.data}, q)


class V362NodeLess(Base):
    def setUp(self):
        self.orph = {r: mk(f'orph_{r.lower()}', r, None) for r in ('GERANT', 'FACTURIER', 'LIVREUR')}
        self.st2 = _stock(self.k2, qty=Dc('10'))

    def test_detail_by_uuid_and_node_param(self):
        rep = FacturierReport.objects.create(node=self.k2, team='A', date='2026-11-10', node_origin='P2')
        for role, u in self.orph.items():
            c = cl(u)
            for url in (f'/api/treasury/reports/{rep.pk}/', f'/api/production/sessions/{self.s2.pk}/',
                        f'/api/production/stocks/{self.st2.pk}/'):
                self.assertIn(c.get(url).status_code, (403, 404), (role, url))
            for url in ('/api/production/sessions/', '/api/production/stocks/', '/api/treasury/reports/',
                        '/api/production/movements/flour_history/', '/api/production/bread-stock/',
                        '/api/production/stock-by-date/'):
                r = c.get(f'{url}?node={self.k2.pk}')
                self.assertIn(r.status_code, (200, 403, 404), (role, url, r.status_code))
                if r.status_code == 200 and not isinstance(r.data, dict) or (
                        r.status_code == 200 and 'results' in r.data):
                    self.assertEqual(len(rows(r)), 0, (role, url))
            # stocks non auto-crees pour K2
            self.assertEqual(ConsumableStock.objects.filter(node=self.k2).count(), 1, role)

    def test_writes_forged_all_methods_403(self):
        s = self.s2
        for role, u in self.orph.items():
            c = cl(u)
            for method, url, body in (
                ('patch', f'/api/production/sessions/{s.pk}/', {'notes': 'x'}),
                ('put', f'/api/production/sessions/{s.pk}/', {'notes': 'x'}),
                ('delete', f'/api/production/sessions/{s.pk}/', None),
                ('post', '/api/production/movements/', {'stock': str(self.st2.pk), 'node': self.k2.pk,
                                                       'movement_type': 'EXIT', 'quantity': '10'}),
                ('post', '/api/treasury/reports/', {'node': self.k2.pk, 'date': '2026-11-11'}),
                ('post', '/api/treasury/expenses/', {'node': self.k2.pk, 'description': 'x', 'amount': '1',
                                                    'date': '2026-11-21'}),
                ('post', '/api/treasury/closures/', {'node': self.k2.pk, 'date': '2026-11-11'}),
                ('post', '/api/sales/invoices/', {'node': self.k2.pk, 'client': str(self.c2.pk), 'lines': []}),
            ):
                r = getattr(c, method)(url, body, format='json') if body is not None else getattr(c, method)(url)
                self.assertEqual(r.status_code, 403, (role, method, url, r.status_code))
        self.assertTrue(type(s).objects.filter(pk=s.pk).exists())
        self.assertEqual(ConsumableStock.objects.get(pk=self.st2.pk).quantity, Dc('10'))

    def test_hq_without_node_still_allowed_and_node_user_unchanged(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = cl(self.u[role]).get('/api/production/sessions/')
            self.assertEqual(r.status_code, 200, role)
            self.assertEqual({str(x['node']) for x in rows(r)}, {str(self.k1.pk), str(self.k2.pk)}, role)
        r = cl(self.u['DIRECTION']).get('/api/sales/invoices/')
        self.assertEqual(r.status_code, 200)
        r = cl(self.u['GERANT']).get(f'/api/production/sessions/{self.s2.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_anonymous_and_safe_methods(self):
        self.assertEqual(cl().post('/api/production/movements/', {}, format='json').status_code, 401)
        # OPTIONS/HEAD d'un compte orphelin : pas de 5xx
        c = cl(self.orph['GERANT'])
        self.assertLess(c.options('/api/production/movements/').status_code, 500)
        self.assertLess(c.head('/api/production/sessions/').status_code, 500)
