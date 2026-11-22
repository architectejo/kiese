"""Verification independante de BUG-521 (testeur-permissions, Dev C, 2026-11-22-c4).

`GET /api/clients/clients/deficit_report/` : isolation, roles, parametre `node`,
contenu, pagination ; + boite noire de `bassins` (meme famille : `node` non valide).
Donnees fictives uniquement.
"""
from decimal import Decimal as Dc
from unittest import expectedFailure

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk, ROLES, HQ

URL = '/api/clients/clients/deficit_report/'


class VerifBase(Base):
    def setUp(self):
        # K1 : c1 (dette 90000, CM 10) + c1b (dette 5, CM 10 -> pas en deficit)
        # K2 : c2 (dette 70000, CM 20)
        self.c1b = Client.objects.create(node=self.k1, node_origin='P1', first_name='Cle', last_name='Sain',
                                         credit_limit=Dc('50000'), commission_rate=Dc('0.25'))
        self.p1 = CommissionPeriod.objects.create(node=self.k1, month=10, year=2026, node_origin='P1')
        self.p2 = CommissionPeriod.objects.create(node=self.k2, month=10, year=2026, node_origin='P2')
        # periode plus ancienne K1 (ne doit pas etre prise)
        self.p1_old = CommissionPeriod.objects.create(node=self.k1, month=9, year=2026, node_origin='P1')
        ClientCommission.objects.create(period=self.p1, client=self.c1, order_value=Dc('100'),
                                        commission_gross=Dc('10'), node_origin='P1')
        ClientCommission.objects.create(period=self.p1, client=self.c1b, order_value=Dc('100'),
                                        commission_gross=Dc('10'), node_origin='P1')
        ClientCommission.objects.create(period=self.p2, client=self.c2, order_value=Dc('100'),
                                        commission_gross=Dc('20'), node_origin='P2')
        ClientCommission.objects.create(period=self.p1_old, client=self.c1b, order_value=Dc('100'),
                                        commission_gross=Dc('1'), node_origin='P1')
        Client.objects.filter(pk=self.c1.pk).update(current_debt=Dc('90000'))
        Client.objects.filter(pk=self.c1b.pk).update(current_debt=Dc('5'))
        Client.objects.filter(pk=self.c2.pk).update(current_debt=Dc('70000'))

    def codes(self, r):
        return {x['client_code'] for x in r.data}


class Isolation(VerifBase):
    def test_gerant_k1_never_sees_k2_by_any_node_spelling(self):
        g = cl(self.u['GERANT'])
        for q in ('', f'?node={self.k2.pk}', f'?node={self.k2.code}', '?node=ZZZ', '?node=P2',
                  '?node=', '?node=999999', f'?node={self.k2.pk}&node={self.k1.pk}',
                  f'?node={self.k2.pk}&page_size=1000', '?page_size=1&page=2', '?limit=1000&offset=0',
                  '?format=json'):
            r = g.get(URL + q)
            self.assertEqual(r.status_code, 200, q)
            self.assertEqual(self.codes(r), {self.c1.code}, q)
            self.assertNotIn(self.c2.code, str(r.data), q)
            self.assertNotIn('Deux', str(r.data), q)

    def test_k2_gerant_symmetric(self):
        r = cl(self.u2['GERANT']).get(URL + f'?node={self.k1.pk}')
        self.assertEqual(self.codes(r), {self.c2.code})

    def test_response_is_plain_unpaginated_list(self):
        r = cl(self.u['GERANT']).get(URL + '?page_size=1')
        self.assertIsInstance(r.data, list)
        self.assertEqual(len(r.data), 1)

    def test_node_less_accounts_empty_even_with_node_param(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            u = mk(f'v521_orph_{role.lower()}', role, None)
            r = cl(u).get(URL + f'?node={self.k2.pk}')
            # gerant : 200 vide ; facturier/livreur : 403 (role)
            if role == 'GERANT':
                self.assertEqual(r.status_code, 200)
                self.assertEqual(list(r.data), [])
            else:
                self.assertEqual(r.status_code, 403)

    def test_gerant_with_other_node_cannot_use_foreign_node_even_if_own_empty(self):
        # gerant K3 sans periode : ne doit pas retomber sur K1/K2
        k3 = type(self.k1).objects.create(code='P3', name='Perm K3', sac_value_fc=Dc('1'))
        g3 = mk('v521_g3', 'GERANT', k3)
        for q in ('', f'?node={self.k1.pk}', f'?node={self.k2.pk}'):
            r = cl(g3).get(URL + q)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(list(r.data), [], q)


class Roles(VerifBase):
    def test_matrix(self):
        allowed = HQ | {'GERANT'}
        self.assertEqual(cl().get(URL).status_code, 401)
        for role in ROLES:
            r = cl(self.u[role]).get(URL)
            self.assertEqual(r.status_code, 200 if role in allowed else 403, role)

    def test_write_methods_not_allowed(self):
        for m in ('post', 'put', 'patch', 'delete'):
            r = getattr(cl(self.u['ADMIN']), m)(URL)
            self.assertIn(r.status_code, (404, 405), m)


class HQBehaviour(VerifBase):
    def test_hq_roles_filter_and_validation(self):
        for role in HQ:
            c = cl(self.u[role])
            self.assertEqual(self.codes(c.get(URL + f'?node={self.k2.pk}')), {self.c2.code}, role)
            self.assertEqual(self.codes(c.get(URL + f'?node={self.k1.pk}')), {self.c1.code}, role)
            for bad in ('ZZZ', 'P2', '1.5', '1e3', '0x1', '%00', "1'--", '-1x'):
                r = c.get(URL, {'node': bad})
                self.assertEqual(r.status_code, 400, (role, bad))
                self.assertIn('detail', r.data)
            # entier inexistant : pas de 500, liste vide
            r = c.get(URL + '?node=999999')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(list(r.data), [])

    def test_hq_without_node_gets_latest_period_overall(self):
        # comportement herite : sans ?node, la periode la plus recente tous noeuds confondus
        r = cl(self.u['DIRECTION']).get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertLess(len(r.data), 3)


class Overflow(VerifBase):
    @expectedFailure  # BUG-532
    def test_BUG_532_huge_integer_node_is_not_a_500(self):
        r = cl(self.u['DIRECTION']).get(URL + '?node=' + '9' * 40)
        self.assertLess(r.status_code, 500)


class Content(VerifBase):
    def test_legit_figures_unchanged_for_gerant(self):
        r = cl(self.u['GERANT']).get(URL)
        self.assertEqual(len(r.data), 1)
        row = r.data[0]
        self.assertEqual(row['client_code'], self.c1.code)
        self.assertEqual(row['client_name'], self.c1.full_name)
        self.assertEqual(Dc(row['order_value']), Dc('100'))
        self.assertEqual(Dc(row['commission_gross']), Dc('10'))
        self.assertEqual(Dc(row['current_debt']), Dc('90000'))
        self.assertEqual(Dc(row['deficit']), Dc('89990'))
        self.assertEqual(row['period'], str(self.p1))
        self.assertEqual(set(row), {'client_code', 'client_name', 'order_value', 'commission_gross',
                                    'current_debt', 'deficit', 'period'})

    def test_ordering_desc_by_debt(self):
        extra = Client.objects.create(node=self.k1, node_origin='P1', first_name='Zed', last_name='Gros',
                                      credit_limit=Dc('50000'), commission_rate=Dc('0.25'))
        Client.objects.filter(pk=extra.pk).update(current_debt=Dc('95000'))
        ClientCommission.objects.create(period=self.p1, client=extra, order_value=Dc('1'),
                                        commission_gross=Dc('1'), node_origin='P1')
        r = cl(self.u['GERANT']).get(URL)
        self.assertEqual([x['client_code'] for x in r.data], [extra.code, self.c1.code])

    def test_foreign_client_commission_row_in_own_period_not_leaked_by_period_choice(self):
        # une periode K2 plus recente que celle de K1 ne doit pas etre servie au gerant K1
        CommissionPeriod.objects.create(node=self.k2, month=12, year=2027, node_origin='P2')
        r = cl(self.u['GERANT']).get(URL)
        self.assertEqual(self.codes(r), {self.c1.code})


class Bassins(VerifBase):
    """Boite noire de `bassins` (clients/views.py, `node` non valide, IsAuthenticated)."""
    B = '/api/clients/clients/bassins/'

    def q(self, node):
        return f'?node={node}&month=10&year=2026'

    @expectedFailure  # BUG-531
    def test_BUG_531_node_param_garbage_not_500(self):
        for role in ('GERANT', 'DIRECTION'):
            for bad in ('ZZZ', 'P2'):
                r = cl(self.u[role]).get(self.B + self.q(bad))
                self.assertLess(r.status_code, 500, (role, bad))

    def test_own_node_works_for_gerant(self):
        r = cl(self.u['GERANT']).get(self.B + self.q(self.k1.pk))
        self.assertEqual(r.status_code, 200)
        self.assertEqual({x['client_code'] for x in r.data['rows']}, {self.c1.code, self.c1b.code})

    @expectedFailure  # BUG-531
    def test_BUG_531_gerant_k1_cannot_read_k2_bassins(self):
        r = cl(self.u['GERANT']).get(self.B + self.q(self.k2.pk))
        leaked = {x['client_code'] for x in r.data.get('rows', [])}
        self.assertNotIn(self.c2.code, leaked)

    def test_facturier_livreur_refused_on_bassins(self):
        # (get_permissions() de ClientViewSet prime sur le decorateur @action : IsGerant)
        for role in ('FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).get(self.B + self.q(self.k1.pk))
            self.assertEqual(r.status_code, 403, role)

    @expectedFailure  # BUG-531
    def test_BUG_531_node_less_gerant_gets_nothing(self):
        r = cl(mk('v521_orph_bas', 'GERANT', None)).get(self.B + self.q(self.k2.pk))
        self.assertEqual(list(r.data.get('rows', [])), [])
