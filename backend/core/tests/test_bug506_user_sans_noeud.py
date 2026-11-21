"""BUG-506 : un compte GERANT/FACTURIER/LIVREUR ne peut pas exister sans boulangerie,
et un compte orphelin (créé hors API) ne voit aucune donnée."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from core import serializers as core_serializers
from core.models import Node, User


def _node(code):
    return Node.objects.create(code=code, name=code)


class Bug506(TestCase):
    def setUp(self):
        self.k1 = _node('K1')
        self.k2 = _node('K2')
        self.direction = User.objects.create_user('b506_dir', password='x', role='DIRECTION')
        self.admin = User.objects.create_user('b506_adm', password='x', role='ADMIN')

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_create_bakery_roles_without_node_refused(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = self.api(self.direction).post('/api/core/users/', {
                'username': 'o_' + role, 'password': 'abcdef12xyz', 'role': role}, format='json')
            self.assertEqual(r.status_code, 400, role)
            self.assertIn('node', r.data)
            self.assertFalse(User.objects.filter(username='o_' + role).exists())

    def test_create_hq_roles_without_node_allowed_and_with_node_ok(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = self.api(self.admin).post('/api/core/users/', {
                'username': 'h_' + role, 'password': 'abcdef12xyz', 'role': role}, format='json')
            self.assertEqual(r.status_code, 201, (role, r.content))
        r = self.api(self.direction).post('/api/core/users/', {
            'username': 'g_ok', 'password': 'abcdef12xyz', 'role': 'GERANT', 'node': self.k1.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_patch_node_null_refused(self):
        g = User.objects.create_user('b506_g', password='x', role='GERANT', node=self.k1)
        r = self.api(self.direction).patch(f'/api/core/users/{g.pk}/', {'node': None}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        g.refresh_from_db()
        self.assertEqual(g.node_id, self.k1.pk)

    def test_role_change_to_bakery_role_without_node_refused(self):
        c = User.objects.create_user('b506_c', password='x', role='COMPTABLE')
        r = self.api(self.direction).patch(f'/api/core/users/{c.pk}/', {'role': 'FACTURIER'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = self.api(self.direction).patch(
            f'/api/core/users/{c.pk}/', {'role': 'FACTURIER', 'node': self.k1.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_patch_unrelated_field_of_valid_user_still_ok(self):
        g = User.objects.create_user('b506_g2', password='x', role='GERANT', node=self.k1)
        r = self.api(self.direction).patch(f'/api/core/users/{g.pk}/', {'phone': '0810000000'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_orphan_sees_nothing_in_core_clients_commissions(self):
        Client.objects.create(first_name='A', last_name='B', node=self.k2)
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            orphan = User.objects.create_user('orph_' + role, password='x', role=role)
            for url in ('/api/clients/clients/', '/api/clients/contributions/', '/api/clients/distributions/',
                        '/api/clients/distribution-lines/', '/api/commissions/periods/',
                        '/api/commissions/commissions/', '/api/core/colis/',
                        '/api/core/notifications/'):
                r = self.api(orphan).get(url)
                if r.status_code != 200:
                    continue
                data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
                self.assertEqual(len(data), 0, (role, url))

    def test_orphan_defense_depends_on_guard(self):
        """Montre que le test précédent échoue sans la garde (mock)."""
        Client.objects.create(first_name='A', last_name='B', node=self.k2)
        orphan = User.objects.create_user('orph_f', password='x', role='FACTURIER')
        with mock.patch('clients.views.is_node_less_non_hq', return_value=False):
            r = self.api(orphan).get('/api/clients/clients/')
        data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        self.assertEqual(len(data), 1)

    def test_validation_depends_on_guard(self):
        with mock.patch.object(core_serializers, 'BAKERY_BOUND_ROLES', ()):
            r = self.api(self.direction).post('/api/core/users/', {
                'username': 'o_x', 'password': 'abcdef12xyz', 'role': 'GERANT'}, format='json')
        self.assertEqual(r.status_code, 201)

    def test_command_lists_without_modifying(self):
        o = User.objects.create_user('orph_cmd', password='x', role='LIVREUR')
        out = StringIO()
        call_command('check_users_sans_noeud', stdout=out)
        self.assertIn('orph_cmd', out.getvalue())
        o.refresh_from_db()
        self.assertIsNone(o.node_id)
