"""BUG-414 : supprimer une boulangerie ne doit pas laisser de comptes actifs orphelins
(User.node est en SET_NULL).

Choix documenté : seuls les comptes ACTIFS bloquent la suppression (HTTP 400, style du
projet pour les ProtectedError). Un compte désactivé ne peut pas se connecter : il ne
bloque pas, et son rattachement passe à NULL. Les relations en PROTECT (clients...) sont
traduites en 400 au lieu d'une erreur 500."""
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from core import views as core_views
from core.models import ActivityLog, Node, User


class Bug414(TestCase):
    def setUp(self):
        self.k1 = Node.objects.create(code='K1', name='TABORA')
        self.k2 = Node.objects.create(code='K2', name='COQ')
        self.direction = User.objects.create_user('b414_dir', password='x', role='DIRECTION')
        self.gerant = User.objects.create_user('b414_ger', password='x', role='GERANT', node=self.k1)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def delete(self, node, user=None):
        return self.api(user or self.direction).delete(f'/api/core/nodes/{node.pk}/')

    def test_refused_with_active_users(self):
        User.objects.create_user('b414_fac', password='x', role='FACTURIER', node=self.k1)
        r = self.delete(self.k1)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('2', r.data['detail'])
        self.assertTrue(Node.objects.filter(pk=self.k1.pk).exists())
        self.gerant.refresh_from_db()
        self.assertEqual(self.gerant.node_id, self.k1.pk)

    def test_succeeds_without_users_and_logs(self):
        r = self.delete(self.k2)
        self.assertEqual(r.status_code, 204, r.content)
        self.assertFalse(Node.objects.filter(pk=self.k2.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='DELETE', description__contains='K2').exists())
        self.assertFalse(User.objects.filter(is_active=True, role='GERANT', node__isnull=True).exists())

    def test_inactive_users_do_not_block(self):
        self.gerant.is_active = False
        self.gerant.save()
        r = self.delete(self.k1)
        self.assertEqual(r.status_code, 204, r.content)
        self.assertFalse(User.objects.filter(is_active=True, node__isnull=True, role='GERANT').exists())

    def test_protected_relations_give_400_not_500(self):
        self.gerant.delete()
        Client.objects.create(first_name='A', last_name='B', node=self.k1)
        r = self.delete(self.k1)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('detail', r.data)
        self.assertTrue(Node.objects.filter(pk=self.k1.pk).exists())

    def test_rights_unchanged(self):
        self.gerant.node = self.k1
        r = self.delete(self.k2, user=self.gerant)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Node.objects.filter(pk=self.k2.pk).exists())

    def test_fails_without_fix(self):
        """Montre le défaut : sans le contrôle (destroy du parent), le compte est orphelin."""
        parent_destroy = core_views.viewsets.ModelViewSet.destroy
        with mock.patch.object(core_views.NodeViewSet, 'destroy', parent_destroy):
            r = self.delete(self.k1)
        self.assertEqual(r.status_code, 204)
        self.gerant.refresh_from_db()
        self.assertIsNone(self.gerant.node_id)  # orphelin actif : le défaut du ticket
