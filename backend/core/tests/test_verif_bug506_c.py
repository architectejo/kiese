"""Verification independante BUG-506 (Dev C, testeur-permissions, 2026-11-21c2)."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client, SocialContribution
from core.models import Node, User

BAKERY_ROLES = ('GERANT', 'FACTURIER', 'LIVREUR')


def cl(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


def rows(r):
    return r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data


class Bug506Verif(TestCase):
    def setUp(self):
        self.k1 = Node.objects.create(code='K1', name='K1')
        self.k2 = Node.objects.create(code='K2', name='K2')
        self.admin = User.objects.create_user('v6_adm', password='x', role='ADMIN')
        self.dir = User.objects.create_user('v6_dir', password='x', role='DIRECTION')
        self.c2 = Client.objects.create(first_name='Deux', last_name='Autre', node=self.k2)

    def _post(self, actor, role, **extra):
        return cl(actor).post('/api/core/users/', {
            'username': f'v6n_{role}_{User.objects.count()}', 'password': 'abcdef12xyz', 'role': role, **extra},
            format='json')

    def test_create_refused_without_node_by_admin_and_direction(self):
        for actor in (self.admin, self.dir):
            for role in BAKERY_ROLES:
                for extra in ({}, {'node': None}):
                    r = self._post(actor, role, **extra)
                    self.assertEqual(r.status_code, 400, (actor.role, role, extra, r.content))
        self.assertFalse(User.objects.filter(username__startswith='v6n_').exists())

    def test_hq_roles_without_node_still_work(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            self.assertEqual(self._post(self.admin, role).status_code, 201, role)
        hq = User.objects.get(role='COMPTABLE')
        self.assertEqual(cl(hq).get('/api/core/users/').status_code, 200)
        self.assertEqual(cl(hq).get('/api/clients/clients/').status_code, 200)
        self.assertGreaterEqual(len(rows(cl(self.dir).get('/api/clients/clients/'))), 1)

    def test_put_and_patch_variants(self):
        g = User.objects.create_user('v6_g', password='x', role='GERANT', node=self.k1)
        c = cl(self.dir)
        url = f'/api/core/users/{g.pk}/'
        r = c.put(url, {'username': 'v6_g', 'role': 'GERANT', 'node': None}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = c.put(url, {'username': 'v6_g', 'role': 'GERANT'}, format='json')  # node omis
        self.assertIn(r.status_code, (200, 400))
        for body in ({'node': None}, {'node': None, 'role': 'FACTURIER'}, {'node': ''}):
            r = c.patch(url, body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.content))
        g.refresh_from_db()
        self.assertEqual(g.node_id, self.k1.pk)

    def test_role_change_from_hq_without_node_refused(self):
        for hq_role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            u = User.objects.create_user('v6_h' + hq_role, password='x', role=hq_role)
            for new in BAKERY_ROLES:
                r = cl(self.admin).patch(f'/api/core/users/{u.pk}/', {'role': new}, format='json')
                self.assertEqual(r.status_code, 400, (hq_role, new, r.content))
            u.refresh_from_db()
            self.assertEqual(u.role, hq_role)
            r = cl(self.admin).patch(f'/api/core/users/{u.pk}/', {'role': 'GERANT', 'node': self.k1.pk}, format='json')
            self.assertEqual(r.status_code, 200, r.content)

    def test_hq_user_node_null_patch_still_ok(self):
        d = User.objects.create_user('v6_d2', password='x', role='DIRECTION', node=self.k1)
        r = cl(self.admin).patch(f'/api/core/users/{d.pk}/', {'node': None}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_bakery_user_moved_to_other_node_still_ok(self):
        g = User.objects.create_user('v6_g3', password='x', role='GERANT', node=self.k1)
        r = cl(self.dir).patch(f'/api/core/users/{g.pk}/', {'node': self.k2.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_node_deleted_leaves_orphan_who_sees_nothing(self):
        n3 = Node.objects.create(code='K3', name='K3')
        g = User.objects.create_user('v6_g4', password='x', role='GERANT', node=n3)
        n3.delete()
        g.refresh_from_db()
        self.assertIsNone(g.node_id)
        for url in ('/api/clients/clients/', '/api/clients/contributions/', '/api/clients/distributions/',
                    '/api/clients/distribution-lines/', '/api/commissions/periods/',
                    '/api/commissions/commissions/', '/api/core/notifications/', '/api/core/colis/'):
            r = cl(g).get(url)
            if r.status_code in (403, 404):
                continue
            self.assertEqual(r.status_code, 200, url)
            self.assertEqual(len(rows(r)), 0, f'orphelin voit des donnees : {url}')

    def test_orphan_each_role_sees_nothing_and_cannot_write_k2(self):
        for role in BAKERY_ROLES:
            o = User.objects.create(username='v6_o' + role, role=role)
            c = cl(o)
            for url in ('/api/clients/clients/?search=Deux', '/api/clients/contributions/',
                        '/api/clients/distributions/', '/api/commissions/periods/',
                        '/api/commissions/commissions/', '/api/core/notifications/'):
                r = c.get(url)
                if r.status_code in (403, 404):
                    continue
                self.assertEqual(len(rows(r)), 0, (role, url))
            r = c.get(f'/api/clients/clients/{self.c2.pk}/')
            self.assertIn(r.status_code, (403, 404), role)
            c.post('/api/clients/clients/', {'first_name': 'Zed', 'last_name': 'Zed', 'node': self.k2.pk}, format='json')
            self.assertFalse(Client.objects.filter(first_name='Zed').exists(), role)
            c.post('/api/clients/contributions/', {'client': str(self.c2.pk), 'node': self.k2.pk, 'amount': '100'},
                   format='json')
            self.assertEqual(SocialContribution.objects.count(), 0, role)

    def test_orphan_filter_param_cannot_reach_k2(self):
        o = User.objects.create(username='v6_of', role='GERANT')
        r = cl(o).get(f'/api/commissions/commissions/?period__node={self.k2.pk}')
        self.assertEqual(len(rows(r)), 0)

    def test_orphan_user_list_forbidden(self):
        o = User.objects.create(username='v6_ou', role='GERANT')
        self.assertEqual(cl(o).get('/api/core/users/').status_code, 403)

    def test_management_command_readonly(self):
        User.objects.create_user('v6_cmd_ok', password='x', role='GERANT', node=self.k1)
        User.objects.create(username='v6_cmd_orph', role='LIVREUR')
        User.objects.create(username='v6_cmd_off', role='FACTURIER', is_active=False)
        out = StringIO()
        snap = lambda: list(User.objects.order_by('pk').values_list('pk', 'role', 'node_id', 'is_active'))
        before = snap()
        call_command('check_users_sans_noeud', stdout=out)
        txt = out.getvalue()
        self.assertIn('v6_cmd_orph', txt)
        self.assertIn('v6_cmd_off', txt)
        self.assertIn('inactif', txt)
        self.assertNotIn('v6_cmd_ok', txt)
        self.assertNotIn('v6_adm', txt)
        self.assertNotIn('v6_dir', txt)
        self.assertEqual(before, snap())

    def test_management_command_empty(self):
        out = StringIO()
        call_command('check_users_sans_noeud', stdout=out)
        self.assertIn('Aucun compte', out.getvalue())
