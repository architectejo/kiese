"""
Vérification indépendante BUG-161 B1/B2 volet production, testeur-production,
2026-11-11 : bornes de la journée de travail autour de la relève (minuit,
relève à 00:00, relève tardive), robustesse de l'API de désignation et
application des migrations core 0017/0018 + production 0023 sur des lignes
existantes (base de test uniquement, jamais db.sqlite3).
"""
from datetime import date, datetime, time
from unittest import expectedFailure
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user
from core.workday import business_date, workday_bounds, next_handover, suggested_team
from production.models import DailyTeamAssignment

URL = '/api/production/team-assignment/'
D = date(2026, 11, 11)


def _at(d, h, m=0, s=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m, s), timezone.get_current_timezone())


def _now(d, h, m=0, s=0):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m, s))


class WorkdayBoundaryTests(TestCase):
    def test_default_handover_midnight_crossing(self):
        n = make_node()  # 12:00
        self.assertEqual(business_date(n, _at(D, 23, 59, 59)), D)
        self.assertEqual(business_date(n, _at(date(2026, 11, 12), 0, 0, 0)), D)
        self.assertEqual(business_date(n, _at(date(2026, 11, 12), 11, 59, 59)), D)
        self.assertEqual(business_date(n, _at(date(2026, 11, 12), 12, 0, 0)), date(2026, 11, 12))

    def test_handover_at_midnight_equals_calendar_date(self):
        n = make_node(); n.handover_time = time(0, 0); n.save()
        for h, m, s in ((0, 0, 0), (0, 0, 1), (11, 59, 59), (12, 0, 0), (23, 59, 59)):
            self.assertEqual(business_date(n, _at(D, h, m, s)), D, (h, m, s))
        self.assertEqual(next_handover(n, _at(D, 0, 0, 0)), _at(date(2026, 11, 12), 0))
        self.assertEqual(next_handover(n, _at(D, 23, 59)), _at(date(2026, 11, 12), 0))

    def test_late_handover_2330(self):
        n = make_node(); n.handover_time = time(23, 30); n.save()
        self.assertEqual(business_date(n, _at(D, 23, 29, 59)), date(2026, 11, 10))
        self.assertEqual(business_date(n, _at(D, 23, 30)), D)
        self.assertEqual(business_date(n, _at(date(2026, 11, 12), 0, 15)), D)
        start, end = workday_bounds(n, D)
        self.assertEqual((start, end), (_at(D, 23, 30), _at(date(2026, 11, 12), 23, 30)))

    def test_year_boundary(self):
        n = make_node()
        self.assertEqual(business_date(n, _at(date(2027, 1, 1), 3)), date(2026, 12, 31))

    def test_suggestion_after_skipped_days_uses_last_known(self):
        n = make_node()
        DailyTeamAssignment.objects.create(node=n, work_date=D, team='B')
        # 3 jours plus tard, sans désignation intermédiaire : l'autre que la dernière (B -> A)
        self.assertEqual(suggested_team(n, _at(date(2026, 11, 14), 13)), 'A')


class AssignmentApiRobustnessTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.gerant = make_user('GERANT', node=self.node)
        self.api = APIClient(); self.api.force_authenticate(self.gerant)

    def test_post_midnight_exactly_on_midnight_targets_previous_workday(self):
        # BUG-227 : la journée de relève ne s'applique qu'en mode rotation.
        self.node.team_rotation_enabled = True; self.node.save(update_fields=['team_rotation_enabled'])
        with _now(date(2026, 11, 12), 0, 0, 0):
            r = self.api.post(URL, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['work_date'], '2026-11-11')

    def test_post_at_handover_instant_targets_new_day(self):
        with _now(date(2026, 11, 12), 12, 0, 0):
            r = self.api.post(URL, {'team': 'B'}, format='json')
        self.assertEqual(r.data['work_date'], '2026-11-12')

    def test_midnight_handover_post_targets_localdate(self):
        self.node.handover_time = time(0, 0); self.node.save()
        with _now(D, 0, 0, 0):
            r = self.api.post(URL, {'team': 'A'}, format='json')
        self.assertEqual(r.data['work_date'], '2026-11-11')

    def test_non_string_team_payloads_rejected_without_500(self):
        with _now(D, 13):
            for bad in (['A'], {'x': 1}, 1, True):
                r = self.api.post(URL, {'team': bad}, format='json')
                self.assertEqual(r.status_code, 400, (bad, getattr(r, 'data', None)))

    def test_non_object_json_body_does_not_500(self):
        with _now(D, 13):
            r = self.api.post(URL, ['A'], format='json')
        self.assertLess(r.status_code, 500, "corps JSON non objet : erreur serveur")

    def test_changing_handover_after_assignment_moves_work_date(self):
        """Caractérisation : déplacer la relève (12:00 -> 18:00) à 14:00 renvoie à la journée de la
        veille ; la désignation de la journée courante n'est donc plus visible."""
        # BUG-227 : la journée de relève ne s'applique qu'en mode rotation.
        self.node.team_rotation_enabled = True; self.node.save(update_fields=['team_rotation_enabled'])
        with _now(D, 14):
            self.api.post(URL, {'team': 'A'}, format='json')
            self.node.handover_time = time(18, 0); self.node.save()
            g = self.api.get(URL)
        self.assertEqual(g.data['work_date'], '2026-11-10')
        self.assertIsNone(g.data['team'])

    def test_activity_log_records_actor_and_node(self):
        from core.models import ActivityLog
        with _now(D, 13):
            self.api.post(URL, {'team': 'A'}, format='json')
        log = ActivityLog.objects.get(action="Désignation équipe de service")
        self.assertEqual(log.user, self.gerant)
        self.assertIn('K1', log.description)


class MigrationAppliesOnExistingRowsTests(TransactionTestCase):
    """Rejoue core 0016 -> 0018 et production 0022 -> 0023 sur une base de test avec des lignes."""

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_forward_migration_preserves_rows_and_sets_defaults(self):
        executor = MigrationExecutor(connection)
        old = [('core', '0016_node_team_a_end_time_node_team_a_start_time_and_more'),
               ('production', '0022_bug158_breaddisposal_negative_remaining')]
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        Node = apps.get_model('core', 'Node')
        before = Node.objects.count()
        Node.objects.create(code='MIG1', name='Node migration test')
        Node.objects.create(code='MIG2', name='Node migration test 2')

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        new = [('core', '0018_bug161_b2_team_assignment'), ('production', '0023_bug161_b2_team_assignment')]
        executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        Node = apps.get_model('core', 'Node')
        self.assertEqual(Node.objects.count(), before + 2)
        self.assertTrue(Node.objects.filter(code__in=['MIG1', 'MIG2']).count() == 2)
        for n in Node.objects.all():
            self.assertEqual(n.handover_time, time(12, 0))
            self.assertFalse(n.team_rotation_enabled)
        DTA = apps.get_model('production', 'DailyTeamAssignment')
        self.assertEqual(DTA.objects.count(), 0)
