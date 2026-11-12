"""
BUG-161 (B2) : désignation manuelle de l'équipe de service du jour
(`DailyTeamAssignment`, `GET/POST /api/production/team-assignment/`,
`core.workday.current_team` / `suggested_team`).
"""
from datetime import date, datetime, time
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import ActivityLog
from core.testing import make_node, make_user
from core.workday import current_team, suggested_team
from production.models import DailyTeamAssignment

URL = '/api/production/team-assignment/'
D = date(2026, 11, 11)
NEXT = date(2026, 11, 12)


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m))


class ModelTests(TestCase):
    def test_unique_per_node_and_work_date(self):
        node = make_node()
        DailyTeamAssignment.objects.create(node=node, work_date=D, team='A')
        with self.assertRaises(IntegrityError), transaction.atomic():
            DailyTeamAssignment.objects.create(node=node, work_date=D, team='B')
        # autre nœud ou autre jour : permis
        DailyTeamAssignment.objects.create(node=make_node(), work_date=D, team='B')
        DailyTeamAssignment.objects.create(node=node, work_date=NEXT, team='B')


class WorkdayHelpersTests(TestCase):
    def setUp(self):
        self.node = make_node()  # relève 12:00 par défaut

    def test_current_team_none_without_assignment(self):
        self.assertIsNone(current_team(self.node, _at(D, 13)))

    def test_handover_boundary_11h59_vs_12h00(self):
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        self.assertEqual(current_team(self.node, _at(NEXT, 11, 59)), 'A')
        self.assertIsNone(current_team(self.node, _at(NEXT, 12, 0)))

    def test_suggested_is_other_team_than_previous_day(self):
        self.assertEqual(suggested_team(self.node, _at(D, 13)), 'A')  # pas d'historique
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        self.assertEqual(suggested_team(self.node, _at(NEXT, 13)), 'B')
        DailyTeamAssignment.objects.create(node=self.node, work_date=NEXT, team='B')
        self.assertEqual(suggested_team(self.node, _at(date(2026, 11, 13), 13)), 'A')

    def test_suggestion_ignores_other_nodes(self):
        other = make_node()
        DailyTeamAssignment.objects.create(node=other, work_date=D, team='A')
        self.assertEqual(suggested_team(self.node, _at(NEXT, 13)), 'A')


class TeamAssignmentApiTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.other = make_node(code='K2')
        self.facturier = make_user('FACTURIER', node=self.node)
        self.gerant = make_user('GERANT', node=self.node)
        self.api = _api(self.gerant)

    def test_get_without_assignment(self):
        with _now(13):
            r = self.api.get(URL)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['work_date'], '2026-11-11')
        self.assertEqual(r.data['handover_time'], '12:00')
        self.assertIsNone(r.data['team'])
        self.assertEqual(r.data['suggested'], 'A')
        self.assertIsNone(r.data['assigned_by'])
        self.assertIn('server_now', r.data)

    def test_post_then_get(self):
        with _now(13):
            r = self.api.post(URL, {'team': 'B'}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data['team'], 'B')
            g = self.api.get(URL)
        self.assertEqual(g.data['team'], 'B')
        self.assertTrue(g.data['assigned_by'])
        a = DailyTeamAssignment.objects.get(node=self.node)
        self.assertEqual((a.work_date, a.team, a.assigned_by), (D, 'B', self.gerant))

    def test_suggestion_is_other_team_than_yesterday(self):
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        with _now(13, d=NEXT):
            r = self.api.get(URL)
        self.assertIsNone(r.data['team'])
        self.assertEqual(r.data['suggested'], 'B')

    def test_handover_11h59_keeps_yesterdays_assignment_12h00_does_not(self):
        # BUG-227 : la journée de relève (J-1 avant la relève) ne s'applique
        # qu'en mode rotation ; hors rotation la date est calendaire.
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        with _now(11, 59, NEXT):
            g = self.api.get(URL)
            self.assertEqual(g.data['team'], 'A')
            # BUG-247 : `work_date` = date calendaire ; `shift_date` = période de service.
            self.assertEqual(g.data['work_date'], '2026-11-12')
            self.assertEqual(g.data['shift_date'], '2026-11-11')
        with _now(12, 0, NEXT):
            r = self.api.get(URL)
        self.assertIsNone(r.data['team'])
        self.assertEqual(r.data['work_date'], '2026-11-12')
        self.assertEqual(r.data['shift_date'], '2026-11-12')

    def test_post_between_midnight_and_handover_targets_previous_workday(self):
        # BUG-227 : journée de relève = mode rotation uniquement.
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])
        with _now(3, 0, NEXT):
            r = self.api.post(URL, {'team': 'A'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(DailyTeamAssignment.objects.filter(node=self.node, work_date=D).exists())

    def test_past_or_future_date_refused(self):
        with _now(13):
            for bad in ('2026-11-10', '2026-11-12'):
                r = self.api.post(URL, {'team': 'A', 'work_date': bad}, format='json')
                self.assertEqual(r.status_code, 400, r.data)
                self.assertIn('detail', r.data)
            r = self.api.post(URL, {'team': 'A', 'date': '2026-11-12'}, format='json')
            self.assertEqual(r.status_code, 400)
            self.assertEqual(DailyTeamAssignment.objects.count(), 0)
            # la date courante explicite est acceptée
            r = self.api.post(URL, {'team': 'A', 'work_date': '2026-11-11'}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(DailyTeamAssignment.objects.count(), 1)

    def test_invalid_team_refused(self):
        for bad in ('C', '', None, 'a'):
            r = self.api.post(URL, {'team': bad}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.data))

    def test_change_is_allowed_and_logged_with_old_value(self):
        with _now(13):
            self.api.post(URL, {'team': 'A'}, format='json')
            r = self.api.post(URL, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(DailyTeamAssignment.objects.get(node=self.node).team, 'B')
        self.assertTrue(ActivityLog.objects.filter(action="Désignation équipe de service").exists())
        change = ActivityLog.objects.get(action="Changement équipe de service")
        self.assertIn('équipe A remplacée par B', change.description)

    def test_same_team_resubmit_is_not_logged_as_change(self):
        with _now(13):
            self.api.post(URL, {'team': 'A'}, format='json')
            self.api.post(URL, {'team': 'A'}, format='json')
        self.assertFalse(ActivityLog.objects.filter(action="Changement équipe de service").exists())

    def test_facturier_can_assign_livreur_cannot(self):
        with _now(13):
            r = _api(self.facturier).post(URL, {'team': 'A'}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            livreur = make_user('LIVREUR', node=self.node)
            self.assertEqual(_api(livreur).get(URL).status_code, 403)
            self.assertEqual(_api(livreur).post(URL, {'team': 'A'}, format='json').status_code, 403)
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_non_hq_user_is_scoped_to_own_node(self):
        other_fact = make_user('FACTURIER', node=self.other)
        with _now(13):
            r = _api(other_fact).post(URL, {'team': 'B', 'node': 'K1'}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            g = _api(other_fact).get(URL, {'node': 'K1'})
        self.assertEqual(g.data['team'], 'B')
        self.assertFalse(DailyTeamAssignment.objects.filter(node=self.node).exists())
        self.assertTrue(DailyTeamAssignment.objects.filter(node=self.other, team='B').exists())

    def test_hq_must_give_node_and_can_target_any(self):
        direction = make_user('DIRECTION', node=None)
        api = _api(direction)
        with _now(13):
            self.assertEqual(api.get(URL).status_code, 400)
            self.assertEqual(api.post(URL, {'team': 'A'}, format='json').status_code, 400)
            r = api.post(URL, {'team': 'B', 'node': 'K2'}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            r = api.post(URL, {'team': 'B', 'node': 'ZZ'}, format='json')
            self.assertEqual(r.status_code, 400)
        self.assertTrue(DailyTeamAssignment.objects.filter(node=self.other, team='B').exists())

    def test_handover_time_per_node(self):
        self.node.handover_time = time(6, 0)
        self.node.save()
        with _now(7):
            r = self.api.post(URL, {'team': 'A'}, format='json')
        self.assertEqual(r.data['handover_time'], '06:00')
        with _now(7, d=NEXT):
            self.assertIsNone(self.api.get(URL).data['team'])
