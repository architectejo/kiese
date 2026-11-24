"""Verification BUG-249 et BUG-250 (testeur-permissions, 2026-11-20b). Donnees fictives."""
from decimal import Decimal as Dc

from clients.models import Client, SocialContribution
from core.tests.test_permissions_regression_2026_11_19 import Base, cl

C = '/api/clients/contributions/'


def rows(resp):
    d = resp.data
    return d['results'] if isinstance(d, dict) and 'results' in d else d


class Bug249(Base):
    def count2(self):
        return SocialContribution.objects.filter(client=self.c2).count()

    def test_bulk_create_foreign_node(self):
        Client.objects.filter(pk=self.c2.pk).update(cotisation_sociale=Dc('3000'))
        r = cl(self.u['GERANT']).post(C + 'bulk_create_month/',
                                      {'node': str(self.k2.pk), 'month': 6, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(self.count2(), 1)  # seule la fixture

    def test_bulk_create_own_node_only(self):
        Client.objects.filter(pk__in=[self.c1.pk, self.c2.pk]).update(cotisation_sociale=Dc('3000'))
        r = cl(self.u['GERANT']).post(C + 'bulk_create_month/', {'month': 6, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['created'], 1)
        self.assertEqual(self.count2(), 1)

    def test_create_foreign_client_any_forged_node(self):
        for node in (self.k1, self.k2):
            r = cl(self.u['GERANT']).post(C, {'client': str(self.c2.pk), 'node': str(node.pk), 'month': 7,
                                              'year': 2026, 'amount': '3000'}, format='json')
            self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.count2(), 1)

    def test_patch_foreign_client_and_forged_node(self):
        g = cl(self.u['GERANT'])
        r = g.patch(f'{C}{self.contrib1.pk}/', {'client': str(self.c2.pk)}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        g.patch(f'{C}{self.contrib1.pk}/', {'node': str(self.k2.pk)}, format='json')
        self.contrib1.refresh_from_db()
        self.assertEqual((self.contrib1.client_id, self.contrib1.node_id), (self.c1.pk, self.k1.pk))
        self.assertEqual(g.get(f'{C}{self.contrib2.pk}/').status_code, 404)
        self.assertEqual(g.delete(f'{C}{self.contrib2.pk}/').status_code, 404)
        self.assertEqual(g.post(f'{C}{self.contrib2.pk}/toggle_paid/').status_code, 404)
        self.assertEqual(len(rows(g.get(C + '?node=' + str(self.k2.pk)))), 0)

    def test_legit_and_other_roles(self):
        r = cl(self.u['GERANT']).post(C, {'client': str(self.c1.pk), 'node': str(self.k2.pk), 'month': 8,
                                          'year': 2026, 'amount': '3000'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(SocialContribution.objects.get(pk=r.data['id']).node_id, self.k1.pk)
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).post(C, {'client': str(self.c1.pk), 'month': 9, 'year': 2026},
                                                   format='json').status_code, 403)
        self.assertEqual(cl().post(C + 'bulk_create_month/', {}, format='json').status_code, 401)

    def test_hq_consistent_node_only(self):
        d = cl(self.u['DIRECTION'])
        r = d.post(C, {'client': str(self.c2.pk), 'node': str(self.k2.pk), 'month': 10, 'year': 2026,
                       'amount': '3000'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        r = d.post(C, {'client': str(self.c2.pk), 'node': str(self.k1.pk), 'month': 11, 'year': 2026,
                       'amount': '3000'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class Bug250(Base):
    URL = '/api/clients/clients/'

    def body(self, **o):
        b = {'first_name': 'Zed', 'last_name': 'Fict', 'credit_limit': '9999999', 'commission_rate': '0.30',
             'node': str(self.k2.pk)}
        b.update(o)
        return b

    def test_facturier_forged_fields_ignored(self):
        r = cl(self.u['FACTURIER']).post(self.URL, self.body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        c = Client.objects.get(pk=r.data['id'])
        self.assertEqual((c.credit_limit, c.commission_rate, c.node_id), (Dc('50000'), Dc('0.25'), self.k1.pk))

    def test_facturier_cannot_patch_limit_or_rate(self):
        f = cl(self.u['FACTURIER'])
        f.patch(f'{self.URL}{self.c1.pk}/', {'credit_limit': '9999999', 'commission_rate': '0.30'}, format='json')
        self.c1.refresh_from_db()
        self.assertEqual((self.c1.credit_limit, self.c1.commission_rate), (Dc('50000'), Dc('0.25')))
        self.assertEqual(f.patch(f'{self.URL}{self.c1.pk}/', {'credit_limit': '1'}, format='json').status_code, 403)

    def test_livreur_cannot_create(self):
        """Q-025/Q-027 : le livreur cree comme le facturier (sa boulangerie, champs
        forges ignores) ; il ne modifie toujours pas un client (comme le facturier)."""
        r = cl(self.u['LIVREUR']).post(self.URL, self.body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        c = Client.objects.get(pk=r.data['id'])
        self.assertEqual((c.credit_limit, c.commission_rate, c.node_id), (Dc('50000'), Dc('0.25'), self.k1.pk))
        self.assertEqual(cl(self.u['LIVREUR']).patch(
            f'{self.URL}{self.c1.pk}/', {'credit_limit': '1'}, format='json').status_code, 403)

    def test_bounds_for_gerant_and_hq(self):
        for role in ('GERANT', 'DIRECTION'):
            c = cl(self.u[role])
            for over in ({'credit_limit': '99999999'}, {'credit_limit': '-1'}, {'commission_rate': '0.50'},
                         {'commission_rate': '-0.1'}):
                r = c.post(self.URL, self.body(node=str(self.k1.pk), **over), format='json')
                self.assertEqual(r.status_code, 400, (role, over, r.content))
        r = cl(self.u['GERANT']).post(self.URL, self.body(credit_limit='70000', commission_rate='0.30'),
                                      format='json')
        self.assertEqual(r.status_code, 201, r.content)
        c = Client.objects.get(pk=r.data['id'])
        self.assertEqual((c.credit_limit, c.commission_rate, c.node_id), (Dc('70000'), Dc('0.30'), self.k1.pk))
        r = cl(self.u['GERANT']).patch(f'{self.URL}{self.c2.pk}/', {'credit_limit': '1'}, format='json')
        self.assertEqual(r.status_code, 404)
