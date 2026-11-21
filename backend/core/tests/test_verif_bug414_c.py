"""Verification independante BUG-414 (testeur-permissions, Dev C) : DELETE /api/core/nodes/<id>/."""
import uuid
from decimal import Decimal
from io import StringIO
from unittest import expectedFailure

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from blockchain.models import TamperAlert
from clients.models import Client
from core.models import ActivityLog, BreadPrice, Node, User
from production.models import BreadStock, ProductionSession
from sales.models import Invoice


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


class Base(TestCase):
    def setUp(self):
        self.k1 = Node.objects.create(code='K1', name='TABORA')
        self.k2 = Node.objects.create(code='K2', name='COQ')

        def mk(name, role, node=None):
            return User.objects.create_user(name, password='x', role=role, node=node)

        self.admin = mk('v_admin', 'ADMIN')
        self.direction = mk('v_dir', 'DIRECTION')
        self.comptable = mk('v_cpt', 'COMPTABLE')
        self.gerant = mk('v_ger', 'GERANT', self.k1)
        self.fact = mk('v_fac', 'FACTURIER', self.k1)
        self.liv = mk('v_liv', 'LIVREUR', self.k1)

    def url(self, pk):
        return f'/api/core/nodes/{pk}/'

    def empty_node(self, code='K9'):
        return Node.objects.create(code=code, name='VIDE ' + code)


class WhoCanDelete(Base):
    def test_roles(self):
        expected = [(self.admin, 204), (self.direction, 204), (self.comptable, 403),
                    (self.gerant, 403), (self.fact, 403), (self.liv, 403)]
        for i, (user, code) in enumerate(expected):
            n = self.empty_node(f'Z{i}')
            r = api(user).delete(self.url(n.pk))
            self.assertEqual(r.status_code, code, (user.username, r.content))
            self.assertEqual(Node.objects.filter(pk=n.pk).exists(), code != 204, user.username)

    def test_anonymous_refused(self):
        n = self.empty_node()
        r = api().delete(self.url(n.pk))
        self.assertIn(r.status_code, (401, 403))
        self.assertTrue(Node.objects.filter(pk=n.pk).exists())

    def test_gerant_cannot_delete_own_node(self):
        r = api(self.gerant).delete(self.url(self.k1.pk))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Node.objects.filter(pk=self.k1.pk).exists())


class ActiveAndInactiveUsers(Base):
    def test_active_users_block_and_nothing_changes(self):
        r = api(self.admin).delete(self.url(self.k1.pk))
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('3', r.data['detail'])
        self.assertTrue(Node.objects.filter(pk=self.k1.pk).exists())
        for u in (self.gerant, self.fact, self.liv):
            u.refresh_from_db()
            self.assertEqual(u.node_id, self.k1.pk)
        self.assertFalse(ActivityLog.objects.filter(action='DELETE').exists())

    def test_one_active_among_inactive_blocks(self):
        User.objects.filter(pk__in=[self.gerant.pk, self.fact.pk]).update(is_active=False)
        r = api(self.direction).delete(self.url(self.k1.pk))
        self.assertEqual(r.status_code, 400)
        self.assertIn('1 compte', r.data['detail'])

    def test_only_inactive_users_do_not_block_and_become_orphans(self):
        User.objects.filter(node=self.k1).update(is_active=False)
        r = api(self.admin).delete(self.url(self.k1.pk))
        self.assertEqual(r.status_code, 204, r.content)
        for u in (self.gerant, self.fact, self.liv):
            u.refresh_from_db()
            self.assertIsNone(u.node_id)
            self.assertFalse(u.is_active)
        out = StringIO()
        call_command('check_users_sans_noeud', stdout=out)
        txt = out.getvalue()
        self.assertIn('3 compte(s)', txt)
        self.assertIn('inactif', txt)

    def test_reactivated_orphan_sees_nothing(self):
        User.objects.filter(node=self.k1).update(is_active=False)
        api(self.admin).delete(self.url(self.k1.pk))
        r = api(self.admin).patch(f'/api/core/users/{self.gerant.pk}/', {'is_active': True}, format='json')
        self.gerant.refresh_from_db()
        if r.status_code == 200 and self.gerant.is_active:
            res = api(self.gerant).get('/api/production/sessions/')
            data = res.data['results'] if isinstance(res.data, dict) and 'results' in res.data else res.data
            self.assertEqual(res.status_code, 200)
            self.assertEqual(len(data), 0)

    def test_reactivating_orphan_gerant_is_refused(self):
        # PATCH is_active=True sur un compte lie a une boulangerie sans noeud : refuse (400).
        User.objects.filter(node=self.k1).update(is_active=False)
        api(self.admin).delete(self.url(self.k1.pk))
        r = api(self.admin).patch(f'/api/core/users/{self.gerant.pk}/', {'is_active': True}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_hq_users_not_counted(self):
        n = self.empty_node()
        self.assertEqual(api(self.admin).delete(self.url(n.pk)).status_code, 204)
        self.assertTrue(User.objects.filter(pk=self.direction.pk).exists())


class ProtectedRelations(Base):
    def assert_400_kept(self, node):
        r = api(self.admin).delete(self.url(node.pk))
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('Impossible', r.data['detail'])
        self.assertTrue(Node.objects.filter(pk=node.pk).exists())
        self.assertFalse(ActivityLog.objects.filter(action='DELETE').exists())

    def test_with_client(self):
        n = self.empty_node()
        Client.objects.create(first_name='A', last_name='B', node=n)
        self.assert_400_kept(n)

    def test_with_invoice(self):
        n = self.empty_node()
        Invoice.objects.create(node=n, facturier=self.fact, team='A')
        self.assert_400_kept(n)

    def test_with_session(self):
        n = self.empty_node()
        ProductionSession.objects.create(node=n, team='A', date='2026-11-01')
        self.assert_400_kept(n)

    def test_with_bread_stock(self):
        n = self.empty_node()
        bp = BreadPrice.objects.create(category='V414', label='V414', unit_price=Decimal('300'))
        BreadStock.objects.create(node=n, bread_price=bp)
        self.assert_400_kept(n)

    def test_atomic_protected_does_not_cascade_delete_alerts(self):
        n = self.empty_node()
        Client.objects.create(first_name='A', last_name='B', node=n)
        TamperAlert.objects.create(node=n, affected_model='X', description='d')
        r = api(self.admin).delete(self.url(n.pk))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(TamperAlert.objects.filter(node=n).count(), 1)

    @expectedFailure
    def test_unresolved_tamper_alert_must_not_be_erased_by_node_delete(self):
        # BUG-516 : TamperAlert.node est en CASCADE ; supprimer un noeud sans autre
        # historique efface silencieusement les alertes de falsification.
        n = self.empty_node()
        TamperAlert.objects.create(node=n, affected_model='CashbookEntry', description='hash casse')
        r = api(self.admin).delete(self.url(n.pk))
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(TamperAlert.objects.filter(node=n).count(), 1)


class SiegeAndIds(Base):
    def test_siege_node_is_deletable_today(self):
        s = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege'})[0]
        self.assertEqual(api(self.admin).delete(self.url(s.pk)).status_code, 204)

    @expectedFailure
    def test_siege_node_should_be_protected(self):
        # BUG-517 : le noeud fictif SIEGE n'est pas protege contre la suppression.
        s = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege'})[0]
        self.assertEqual(api(self.admin).delete(self.url(s.pk)).status_code, 400)

    def test_unknown_and_forged_ids_404(self):
        for bad in ('999999', 'abc', str(uuid.uuid4()), '-1', '0'):
            r = api(self.admin).delete(self.url(bad))
            self.assertEqual(r.status_code, 404, (bad, r.status_code))

    def test_double_delete(self):
        n = self.empty_node()
        self.assertEqual(api(self.admin).delete(self.url(n.pk)).status_code, 204)
        self.assertEqual(api(self.admin).delete(self.url(n.pk)).status_code, 404)
        self.assertEqual(ActivityLog.objects.filter(action='DELETE').count(), 1)

    def test_journal_written_with_user_and_label(self):
        n = self.empty_node('K7')
        api(self.direction).delete(self.url(n.pk))
        log = ActivityLog.objects.get(action='DELETE')
        self.assertIn('K7', log.description)
        self.assertEqual(log.user_id, self.direction.pk)

    def test_check_command_clean_after_successful_delete(self):
        n = self.empty_node()
        api(self.admin).delete(self.url(n.pk))
        out = StringIO()
        call_command('check_users_sans_noeud', stdout=out)
        self.assertIn('Aucun compte', out.getvalue())

    def test_other_node_untouched(self):
        n = self.empty_node()
        api(self.admin).delete(self.url(n.pk))
        self.assertTrue(Node.objects.filter(pk=self.k2.pk).exists())
        self.fact.refresh_from_db()
        self.assertEqual(self.fact.node_id, self.k1.pk)
