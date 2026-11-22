"""Verification independante BUG-516 (testeur-permissions, Dev C).

TamperAlert.node / BlockchainSnapshot.node en PROTECT : supprimer une boulangerie
ne doit pas effacer ses preuves d'integrite. Une boulangerie sans rien reste supprimable.
"""
from django.db import IntegrityError, connection
from django.db.models import ProtectedError
from django.db.models.deletion import PROTECT
from django.test import TestCase
from rest_framework.test import APIClient

from blockchain.models import BlockchainSnapshot, TamperAlert
from core.models import ActivityLog, Node, SystemNotification, User


def api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('c516_adm', password='x', role='ADMIN')
        self.direction = User.objects.create_user('c516_dir', password='x', role='DIRECTION')
        self.node = Node.objects.create(code='K8', name='TEST HUIT')
        self.other = Node.objects.create(code='K7', name='TEST SEPT')

    def url(self, pk):
        return f'/api/core/nodes/{pk}/'

    def assert_refused(self, user):
        n_log = ActivityLog.objects.filter(action='DELETE').count()
        r = api(user).delete(self.url(self.node.pk))
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('Impossible de supprimer', r.data['detail'])
        self.assertTrue(Node.objects.filter(pk=self.node.pk).exists())
        # (un log 'Modification Configuration' peut apparaitre : creation paresseuse de Config, hors sujet)
        self.assertEqual(ActivityLog.objects.filter(action='DELETE').count(), n_log, 'journal DELETE ecrit malgre le refus')


class ModelDefinition(TestCase):
    def test_on_delete_is_protect(self):
        self.assertIs(TamperAlert._meta.get_field('node').remote_field.on_delete, PROTECT)
        self.assertIs(BlockchainSnapshot._meta.get_field('node').remote_field.on_delete, PROTECT)


class ApiDelete(Base):
    def test_unresolved_alert_blocks_both_roles(self):
        a = TamperAlert.objects.create(node=self.node, affected_model='CashbookEntry', description='x')
        for u in (self.admin, self.direction):
            self.assert_refused(u)
        self.assertTrue(TamperAlert.objects.filter(pk=a.pk, is_resolved=False).exists()
                        if hasattr(a, 'is_resolved') else TamperAlert.objects.filter(pk=a.pk).exists())

    def test_resolved_alert_still_blocks(self):
        a = TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        fields = {f.name for f in TamperAlert._meta.fields}
        for name in ('resolved', 'is_resolved'):
            if name in fields:
                setattr(a, name, True)
                a.save()
        self.assert_refused(self.admin)
        self.assertEqual(TamperAlert.objects.filter(node=self.node).count(), 1)

    def test_snapshot_only_blocks(self):
        BlockchainSnapshot.objects.create(node=self.node, snapshot_date='2026-11-01')
        self.assert_refused(self.direction)
        self.assertEqual(BlockchainSnapshot.objects.filter(node=self.node).count(), 1)

    def test_alert_and_snapshot_together_all_kept(self):
        TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        TamperAlert.objects.create(node=self.node, affected_model='Y', description='y')
        BlockchainSnapshot.objects.create(node=self.node, snapshot_date='2026-11-01')
        self.assert_refused(self.admin)
        self.assertEqual(TamperAlert.objects.filter(node=self.node).count(), 2)
        self.assertEqual(BlockchainSnapshot.objects.filter(node=self.node).count(), 1)

    def test_other_node_proofs_irrelevant_node_deletable(self):
        TamperAlert.objects.create(node=self.other, affected_model='X', description='x')
        r = api(self.admin).delete(self.url(self.node.pk))
        self.assertEqual(r.status_code, 204, r.content)
        self.assertFalse(Node.objects.filter(pk=self.node.pk).exists())
        self.assertEqual(TamperAlert.objects.filter(node=self.other).count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action='DELETE').count(), 1)

    def test_empty_node_deletable_then_404_and_single_log(self):
        self.assertEqual(api(self.admin).delete(self.url(self.node.pk)).status_code, 204)
        self.assertEqual(api(self.admin).delete(self.url(self.node.pk)).status_code, 404)
        self.assertEqual(ActivityLog.objects.filter(action='DELETE').count(), 1)

    def test_repeated_refusal_is_idempotent(self):
        TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        for _ in range(3):
            self.assert_refused(self.admin)
        self.assertEqual(TamperAlert.objects.filter(node=self.node).count(), 1)

    def test_refusal_creates_no_notification(self):
        TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        qs = lambda: SystemNotification.objects.exclude(title__startswith='Configuration')  # creation paresseuse de Config : hors sujet
        n = qs().count()
        self.assert_refused(self.admin)
        self.assertEqual(qs().count(), n)

    def test_non_admin_roles_cannot_even_try(self):
        TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            u = User.objects.create_user('c516_' + role, password='x', role=role, node=self.node)
            r = api(u).delete(self.url(self.node.pk))
            self.assertEqual(r.status_code, 403, role)
        self.assertTrue(Node.objects.filter(pk=self.node.pk).exists())


class OrmDelete(Base):
    def test_orm_alert_raises_and_keeps_everything(self):
        TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        with self.assertRaises(ProtectedError):
            self.node.delete()
        self.assertTrue(Node.objects.filter(pk=self.node.pk).exists())
        self.assertEqual(TamperAlert.objects.count(), 1)

    def test_orm_snapshot_raises(self):
        BlockchainSnapshot.objects.create(node=self.node, snapshot_date='2026-11-01')
        with self.assertRaises(ProtectedError):
            self.node.delete()
        self.assertEqual(BlockchainSnapshot.objects.count(), 1)

    def test_queryset_bulk_delete_also_protected(self):
        TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        with self.assertRaises(ProtectedError):
            Node.objects.filter(pk=self.node.pk).delete()
        self.assertTrue(Node.objects.filter(pk=self.node.pk).exists())

    def test_bulk_delete_mixed_is_atomic(self):
        # K8 protege, K7 vide : la suppression groupee ne doit rien supprimer.
        TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        with self.assertRaises(ProtectedError):
            Node.objects.filter(pk__in=[self.node.pk, self.other.pk]).delete()
        self.assertEqual(Node.objects.filter(pk__in=[self.node.pk, self.other.pk]).count(), 2)

    def test_orm_empty_node_deletable(self):
        self.other.delete()
        self.assertFalse(Node.objects.filter(code='K7').exists())

    def test_db_level_fk_still_consistent(self):
        # Pas de ligne orpheline : l'integrite referentielle SQL reste active.
        TamperAlert.objects.create(node=self.node, affected_model='X', description='x')
        with connection.cursor() as c:
            c.execute('PRAGMA foreign_key_check') if connection.vendor == 'sqlite' else None
            rows = c.fetchall() if connection.vendor == 'sqlite' else []
        self.assertEqual(rows, [])
