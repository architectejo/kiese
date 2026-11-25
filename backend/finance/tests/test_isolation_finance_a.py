"""Isolation du module finance (dev-backend a7) : matrice role x route x `?node=`.

Hypothese a verifier : un gerant / facturier / livreur de K1 pourrait lire le DOC 1 ou
les etats financiers de K2 (ou consolides) via `?node=`. Les routes etant en
`IsAuthenticated` sur les @action, mais `get_permissions()` du ViewSet imposant
`IsHeadquarters` partout (BUG-101), tout non-siege doit recevoir 403, quel que soit
`?node=`. Les chiffres du siege ne changent pas. Donnees fictives uniquement.
"""
from decimal import Decimal as Dc

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from core.models import BreadPrice, Node
from finance.models import FinancialYear
from sales.models import Invoice, InvoiceLine

User = get_user_model()
HQ_ROLES = ('ADMIN', 'DIRECTION', 'COMPTABLE')
DATE = '2026-03-10'


def _client_for(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


def _body(resp):
    if hasattr(resp, 'streaming_content'):
        return b''.join(resp.streaming_content).decode('utf-8-sig')
    return str(resp.data)


class FinanceIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code='F1', name='Fin K1', sac_value_fc=Dc('200000'), team_rotation_enabled=False)
        cls.k2 = Node.objects.create(code='F2', name='Fin K2', sac_value_fc=Dc('200000'), team_rotation_enabled=False)
        mk = lambda name, role, node=None: User.objects.create(
            username=name, role=role, node=node, first_name=name, last_name='Qa')
        cls.hq = {r: mk(f'fi_{r.lower()}', r) for r in HQ_ROLES}
        cls.k1_users = {r: mk(f'fi1_{r.lower()}', r, cls.k1) for r in ('GERANT', 'FACTURIER', 'LIVREUR')}
        cls.nodeless = {r: mk(f'fi0_{r.lower()}', r) for r in ('GERANT', 'FACTURIER', 'LIVREUR')}
        cls.fy = FinancialYear.objects.create(year=2026)
        bp = BreadPrice.objects.get_or_create(
            category='MOYEN', defaults={'label': 'Pain 500', 'unit_price': 500})[0]
        # Une facture livree par boulangerie (clients distincts) pour le DOC 1.
        for node, last in ((cls.k1, 'UnPrime'), (cls.k2, 'DeuxSecret')):
            client = Client.objects.create(node=node, node_origin=node.code, first_name='X',
                                           last_name=last, credit_limit=Dc('50000'),
                                           commission_rate=Dc('0.25'))
            inv = Invoice.objects.create(node=node, client=client, facturier=cls.hq['ADMIN'],
                                         team='A', node_origin=node.code)
            InvoiceLine.objects.create(invoice=inv, bread_price=bp, quantity=4)
            Invoice.objects.filter(pk=inv.pk).update(
                status='DELIVERED', invoice_date=DATE, order_total=Dc('2000'))

    # -- routes -------------------------------------------------------------
    def routes(self, node_param):
        """(methode, url, corps) de CHAQUE route du module (ModelViewSet + @action)."""
        base = '/api/finance/years/'
        pk = self.fy.pk
        q = {'month': '3', 'year': '2026'}
        if node_param is not None:
            q['node'] = node_param
        qs = '?' + '&'.join(f'{k}={v}' for k, v in q.items())
        qy = '?year=2026' + (f'&node={node_param}' if node_param is not None else '')
        return [
            ('get', base + (qy if node_param is not None else ''), None),
            ('post', base, {'year': 2030}),
            ('get', f'{base}{pk}/', None),
            ('put', f'{base}{pk}/', {'year': 2026}),
            ('patch', f'{base}{pk}/', {}),
            ('delete', f'{base}{pk}/', None),
            ('get', f'{base}{pk}/income_statement/' + qy, None),
            ('get', f'{base}{pk}/cashflow/' + qy, None),
            ('get', f'{base}{pk}/balance_sheet/' + qy, None),
            ('get', f'{base}{pk}/comparative/' + qy, None),
            ('get', base + 'summary/' + qy, None),
            ('get', base + 'doc1_report/' + qs, None),
            ('get', base + 'doc1_export/' + qs, None),
        ]

    def call(self, client, method, url, body):
        fn = getattr(client, method)
        return fn(url, body, format='json') if body is not None else fn(url)

    def node_params(self):
        return [None, str(self.k2.pk), self.k2.code, self.k2.code.lower(), 'ZZZ']

    # -- anonyme ------------------------------------------------------------
    def test_anonymous_401_on_every_route(self):
        for np in self.node_params():
            for method, url, body in self.routes(np):
                r = self.call(_client_for(), method, url, body)
                self.assertEqual(r.status_code, 401, (method, url))

    # -- non-siege : 403 partout, ?node= sans effet --------------------------
    def _assert_forbidden(self, user, label):
        c = _client_for(user)
        for np in self.node_params():
            for method, url, body in self.routes(np):
                r = self.call(c, method, url, body)
                self.assertEqual(r.status_code, 403, (label, method, url))
                self.assertNotIn('DeuxSecret', _body(r), (label, url))
                self.assertNotIn('UnPrime', _body(r), (label, url))

    def test_k1_gerant_forbidden_everywhere(self):
        self._assert_forbidden(self.k1_users['GERANT'], 'gerant K1')

    def test_k1_facturier_forbidden_everywhere(self):
        self._assert_forbidden(self.k1_users['FACTURIER'], 'facturier K1')

    def test_k1_livreur_forbidden_everywhere(self):
        self._assert_forbidden(self.k1_users['LIVREUR'], 'livreur K1')

    def test_nodeless_accounts_forbidden_everywhere(self):
        for role, user in self.nodeless.items():
            self._assert_forbidden(user, f'{role} sans boulangerie')

    def test_k1_gerant_cannot_write_financial_year(self):
        c = _client_for(self.k1_users['GERANT'])
        r = c.post('/api/finance/years/', {'year': 2031}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(FinancialYear.objects.filter(year=2031).exists())
        r = c.delete(f'/api/finance/years/{self.fy.pk}/')
        self.assertEqual(r.status_code, 403)
        self.assertTrue(FinancialYear.objects.filter(pk=self.fy.pk).exists())

    # -- siege : non-regression des chiffres -----------------------------------
    def test_hq_reads_all_routes_200(self):
        for role, user in self.hq.items():
            c = _client_for(user)
            for method, url, body in self.routes(self.k1.code):
                if method != 'get':
                    continue
                r = self.call(c, method, url, body)
                self.assertEqual(r.status_code, 200, (role, url))

    def test_hq_doc1_figures_per_node_unchanged(self):
        for role, user in self.hq.items():
            c = _client_for(user)
            for ident, name, other in ((self.k1, 'UnPrime', 'DeuxSecret'),
                                       (self.k2, 'DeuxSecret', 'UnPrime')):
                for np in (str(ident.pk), ident.code):
                    r = c.get('/api/finance/years/doc1_report/',
                              {'node': np, 'month': '3', 'year': '2026'})
                    self.assertEqual(r.status_code, 200, (role, np))
                    rows = r.data['results'] if isinstance(r.data, dict) else r.data
                    self.assertEqual(len(rows), 1)
                    self.assertIn(name, rows[0]['client_name'])
                    self.assertEqual(rows[0]['invoice_total'], '2000.00')
                    self.assertNotIn(other, str(rows))
                    r = c.get('/api/finance/years/doc1_export/',
                              {'node': np, 'month': '3', 'year': '2026'})
                    self.assertEqual(r.status_code, 200)
                    text = _body(r)
                    self.assertIn(name, text)
                    self.assertNotIn(other, text)

    def test_hq_consolidated_income_statement_sums_all_nodes(self):
        r = _client_for(self.hq['DIRECTION']).get(f'/api/finance/years/{self.fy.pk}/income_statement/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Dc(str(r.data['total_revenue'])), Dc('4000'))  # 2 x (4 x 500)

    def test_hq_summary_unknown_node_is_400_not_403(self):
        r = _client_for(self.hq['ADMIN']).get('/api/finance/years/summary/?node=ZZZ')
        self.assertEqual(r.status_code, 400)
