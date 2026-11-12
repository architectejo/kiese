"""
BUG-161 (B3) : la production raisonne en date de travail du nœud
(`core.workday.work_date_for`) : sessions (date/équipe par défaut), stock par
date, confirmation du stock de départ, rapport de clôture journalier ; et
expose `work_date` / `server_now` au frontend. Hors rotation, comportement
historique (date locale) strictement inchangé.
"""
from datetime import timezone as dt_timezone
from datetime import date, datetime, time
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmation, DailyTeamAssignment,
    ProductionSession, ProductionSessionLine,
)
from production.views import _build_daily_closure_report

D = date(2026, 11, 12)
PREV = date(2026, 11, 11)
OLDER = date(2026, 11, 10)
SESSIONS = '/api/production/sessions/'
OPENING = '/api/production/opening-confirmation/'
BY_DATE = '/api/production/bread-stocks/by-date/'
CLOSURE = '/api/production/daily-closure/'
SHIFT = '/api/production/sessions/shift-end-status/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    # Comme `timezone.now()` réel : datetime aware en UTC (BUG-189 : `.date()` = date UTC).
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.api = _api(self.gerant)

    def _rotation(self):
        self.node.team_rotation_enabled = True
        self.node.handover_time = time(12, 0)
        self.node.save()

    def _opening_payload(self, **extra):
        payload = {'team': 'A', 'lines': [{'bread_price': self.bp.pk, 'qty': 10}]}
        payload.update(extra)
        return payload


class SessionDefaultsTests(_Base):
    def _declare(self, **extra):
        payload = {'lines': [{'bread_price': self.bp.pk, 'quantity': 10}], 'flour_sacks_used': '1.00'}
        payload.update(extra)
        return self.api.post(SESSIONS, payload, format='json')

    def test_rotation_defaults_date_and_team_from_server(self):
        self._rotation()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        with _now(9, 0):
            r = self._declare()
        self.assertEqual(r.status_code, 201, r.data)
        session = ProductionSession.objects.get(pk=r.data['id'])
        self.assertEqual(session.date, PREV)
        self.assertEqual(session.team, 'B')

    def test_rotation_new_work_day_at_12_00(self):
        self._rotation()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        with _now(12, 0):
            r = self._declare()
        session = ProductionSession.objects.get(pk=r.data['id'])
        self.assertEqual((session.date, session.team), (D, 'A'))

    def test_rotation_explicit_payload_kept(self):
        self._rotation()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        with _now(9, 0):
            r = self._declare(date='2026-11-10', team='A')
        session = ProductionSession.objects.get(pk=r.data['id'])
        self.assertEqual((session.date, session.team), (OLDER, 'A'))

    def test_rotation_without_assignment_team_stays_required(self):
        self._rotation()
        with _now(9, 0):
            r = self._declare()
        # BUG-192 : sans désignation, refus explicite 403 TEAM_NOT_ASSIGNED
        # (cohérent avec opening-confirmation, B4) au lieu d'un 400 « team requis ».
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'TEAM_NOT_ASSIGNED')
        self.assertNotIn('date', r.data)

    def test_without_rotation_date_and_team_still_required(self):
        with _now(9, 0):
            r = self._declare()
        self.assertEqual(r.status_code, 400)
        self.assertIn('date', r.data)
        self.assertIn('team', r.data)

    def test_without_rotation_explicit_payload_unchanged(self):
        with _now(0, 30):
            r = self._declare(date='2026-11-12', team='A')
        self.assertEqual(r.status_code, 201, r.data)


class BreadStockByDateTests(_Base):
    def test_without_rotation_today_is_local_date_at_00_30(self):
        BreadStock.objects.create(node=self.node, bread_price=self.bp)
        with _now(0, 30):
            r = self.api.get(BY_DATE, {'date': '2026-11-12'})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['source'], 'live')
        self.assertEqual(r.data['work_date'], '2026-11-12')
        self.assertTrue(r.data['server_now'].startswith('2026-11-12T00:30'))

    def test_rotation_live_for_current_work_date_snapshot_before(self):
        self._rotation()
        with _now(3, 0):
            live = self.api.get(BY_DATE, {'date': '2026-11-11'})
            future = self.api.get(BY_DATE, {'date': '2026-11-12'})
            past = self.api.get(BY_DATE, {'date': '2026-11-10'})
            default = self.api.get(BY_DATE)
        self.assertEqual(live.data['source'], 'live')
        self.assertEqual(live.data['work_date'], '2026-11-11')
        self.assertEqual(future.status_code, 400)
        self.assertEqual(past.data['source'], 'snapshot')
        self.assertEqual(default.data['date'], '2026-11-11')
        with _now(12, 0):
            self.assertEqual(self.api.get(BY_DATE, {'date': '2026-11-12'}).data['source'], 'live')


class OpeningConfirmationTests(_Base):
    def test_get_default_date_without_rotation_is_local(self):
        with _now(0, 30):
            r = self.api.get(OPENING)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['date'], '2026-11-12')
        self.assertEqual(r.data['work_date'], '2026-11-12')
        self.assertIn('server_now', r.data)

    def test_get_default_date_rotation_is_work_date(self):
        self._rotation()
        with _now(9, 0):
            r = self.api.get(OPENING)
        self.assertEqual(r.data['date'], '2026-11-11')
        self.assertEqual(r.data['work_date'], '2026-11-11')
        with _now(12, 0):
            self.assertEqual(self.api.get(OPENING).data['date'], '2026-11-12')

    def test_post_default_date_rotation_is_work_date(self):
        self._rotation()
        # B4 : en rotation, l'équipe de service doit être désignée (la désignation passe d'abord).
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='A')
        with _now(9, 0):
            r = self.api.post(OPENING, self._opening_payload(), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['date'], '2026-11-11')
        self.assertTrue(DailyOpeningConfirmation.objects.filter(node=self.node, date=PREV).exists())
        self.assertFalse(DailyOpeningConfirmation.objects.filter(node=self.node, date=D).exists())

    def test_post_past_date_rejected_in_rotation(self):
        self._rotation()
        with _now(13, 0):
            r = self.api.post(OPENING, self._opening_payload(date='2026-11-11'), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(DailyOpeningConfirmation.objects.exists())
        self.assertFalse(ProductionSession.objects.exists())
        self.assertFalse(BreadStock.objects.exists())

    def test_post_calendar_date_after_midnight_rejected_in_rotation(self):
        # 03:00 le 12/11 : journée de travail = 11/11 ; le 12/11 n'a pas commencé.
        self._rotation()
        with _now(3, 0):
            r = self.api.post(OPENING, self._opening_payload(date='2026-11-12'), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(DailyOpeningConfirmation.objects.exists())

    def test_post_current_explicit_date_accepted_in_rotation(self):
        self._rotation()
        # B4 : désignation préalable de l'équipe de service obligatoire en rotation.
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        with _now(13, 0):
            r = self.api.post(OPENING, self._opening_payload(date='2026-11-12'), format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_post_past_date_still_accepted_without_rotation(self):
        with _now(13, 0):
            r = self.api.post(OPENING, self._opening_payload(date='2026-11-11'), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(DailyOpeningConfirmation.objects.filter(node=self.node, date=PREV).exists())

    def test_post_default_date_without_rotation_is_local_at_00_30(self):
        with _now(0, 30):
            r = self.api.post(OPENING, self._opening_payload(), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['date'], '2026-11-12')

    def test_rotation_rejection_does_not_touch_closed_previous_day(self):
        """Une confirmation de départ visant la veille ne réécrit ni snapshot ni session figés."""
        self._rotation()
        session = ProductionSession.objects.create(
            node=self.node, team='B', date=PREV, declared_by=self.gerant, node_origin='K1',
            is_closed=True,
        )
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp, date=PREV, team='B', qty_at_close=7,
        )
        with _now(13, 0):
            r = self.api.post(OPENING, self._opening_payload(date='2026-11-11'), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            DailyBreadStockSnapshot.objects.get(node=self.node, date=PREV).qty_at_close, 7,
        )
        self.assertEqual(ProductionSession.objects.get(pk=session.pk).lines.count(), 0)


class ClosureAndShiftTests(_Base):
    def test_closure_report_default_date_is_work_date(self):
        self._rotation()
        with _now(9, 0):
            report = _build_daily_closure_report(self.node)
        self.assertEqual(report['date'], '2026-11-11')
        self.assertEqual(report['work_date'], '2026-11-11')

    def test_closure_report_contains_the_day_of_the_previous_work_date(self):
        self._rotation()
        session = ProductionSession.objects.create(
            node=self.node, team='B', date=PREV, declared_by=self.gerant, node_origin='K1',
        )
        ProductionSessionLine.objects.create(session=session, bread_price=self.bp, quantity=12)
        with _now(9, 0):
            r = self.api.get(CLOSURE, {'date': '2026-11-11'})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['work_date'], '2026-11-11')
        self.assertIn('server_now', r.data)

    def test_closure_report_without_rotation_has_local_work_date(self):
        with _now(0, 30):
            r = self.api.get(CLOSURE, {'date': '2026-11-11'})
        self.assertEqual(r.data['date'], '2026-11-11')
        self.assertEqual(r.data['work_date'], '2026-11-12')

    def test_shift_end_status_exposes_work_date_in_rotation_only(self):
        with _now(9, 0):
            plain = self.api.get(SHIFT, {'node': 'K1'})
        self.assertEqual(plain.data, {'pending_validation': False})
        self._rotation()
        with _now(9, 0):
            rot = self.api.get(SHIFT, {'node': 'K1'})
        self.assertEqual(rot.data['pending_validation'], False)
        self.assertEqual(rot.data['work_date'], '2026-11-11')
        self.assertIn('server_now', rot.data)
