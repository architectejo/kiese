"""
BUG-161 (B3) : `work_date_for(node, instant)` — source unique de la date de
travail côté serveur. Hors rotation : date locale du calendrier (comportement
historique, jamais la date UTC) ; en rotation : journée de relève à relève.
"""
from datetime import date, datetime, time, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.testing import make_node, get_config
from core.utils import validate_requested_date
from core.workday import (
    work_date_for, work_time_info, delivered_on_work_date_filter, workday_bounds,
)

D = date(2026, 11, 12)
PREV = date(2026, 11, 11)


def _at(d, h, m=0, s=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m, s), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    # Comme `timezone.now()` réel : datetime aware en UTC (BUG-189 : `.date()` = date UTC).
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class WorkDateForTests(TestCase):
    def setUp(self):
        self.plain = make_node(code='K1')
        self.rot = make_node(code='K2')
        self.rot.team_rotation_enabled = True
        self.rot.handover_time = time(12, 0)
        self.rot.save()

    def test_without_rotation_is_local_calendar_date_at_00_30(self):
        # 00:30 locale = 23:30 UTC la veille : la date de travail est LOCALE.
        instant = _at(D, 0, 30)
        self.assertEqual(instant.astimezone(dt_timezone.utc).date(), PREV)
        self.assertEqual(work_date_for(self.plain, instant), D)
        with _now(0, 30):
            self.assertEqual(work_date_for(self.plain), D)
            self.assertEqual(work_date_for(self.plain), timezone.localdate())

    def test_without_rotation_ignores_handover_time(self):
        # Équivalence : relève 12:00 mais rotation inactive -> date calendaire.
        self.assertEqual(work_date_for(self.plain, _at(D, 3, 0)), D)
        self.assertEqual(work_date_for(self.plain, _at(D, 11, 59)), D)

    def test_rotation_before_and_at_handover(self):
        self.assertEqual(work_date_for(self.rot, _at(D, 3, 0)), PREV)
        self.assertEqual(work_date_for(self.rot, _at(D, 9, 0)), PREV)
        self.assertEqual(work_date_for(self.rot, _at(D, 11, 59, 59)), PREV)
        self.assertEqual(work_date_for(self.rot, _at(D, 12, 0)), D)
        self.assertEqual(work_date_for(self.rot, _at(D, 23, 59)), D)

    def test_rotation_with_midnight_handover_equals_calendar_date(self):
        self.rot.handover_time = time(0, 0)
        self.rot.save()
        for h in (0, 3, 12, 23):
            self.assertEqual(work_date_for(self.rot, _at(D, h, 0)), D)

    def test_rotation_default_instant_uses_now(self):
        with _now(3, 0):
            self.assertEqual(work_date_for(self.rot), PREV)
        with _now(12, 0):
            self.assertEqual(work_date_for(self.rot), D)

    def test_node_none_falls_back_to_local_date(self):
        with _now(0, 30):
            self.assertEqual(work_date_for(None), D)

    def test_work_time_info(self):
        with _now(3, 0):
            info = work_time_info(self.rot)
            self.assertEqual(info['work_date'], '2026-11-11')
            self.assertTrue(info['server_now'].startswith('2026-11-12T03:00:00'))
            self.assertEqual(work_time_info(self.plain)['work_date'], '2026-11-12')

    def test_delivered_filter_matches_bounds(self):
        self.assertEqual(delivered_on_work_date_filter(self.plain, D), {'delivered_at__date': D})
        start, end = workday_bounds(self.rot, PREV)
        self.assertEqual(
            delivered_on_work_date_filter(self.rot, PREV),
            {'delivered_at__gte': start, 'delivered_at__lt': end},
        )


class ValidateRequestedDateWorkDateTests(TestCase):
    def setUp(self):
        self.plain = make_node(code='K1')
        self.rot = make_node(code='K2')
        self.rot.team_rotation_enabled = True
        self.rot.save()
        self.config = get_config()
        self.config.allow_backdated_sales = True
        self.config.save()

    def test_without_rotation_today_is_local_date(self):
        with _now(0, 30):
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X', node=self.plain))
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X'))
            self.assertIn('future', validate_requested_date(
                date(2026, 11, 13), self.config, field_label='X', node=self.plain))

    def test_rotation_future_means_after_current_work_date(self):
        with _now(3, 0):  # journée de travail = 11/11
            self.assertIsNone(validate_requested_date(PREV, self.config, field_label='X', node=self.rot))
            err = validate_requested_date(D, self.config, field_label='X', node=self.rot)
            self.assertIn('future', err)
            # même date acceptée pour une boulangerie sans rotation
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X', node=self.plain))
        with _now(12, 0):  # nouvelle journée = 12/11
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X', node=self.rot))

    def test_rotation_past_refused_when_backdating_disabled(self):
        self.config.allow_backdated_sales = False
        self.config.save()
        with _now(3, 0):
            # la journée courante (11/11) reste acceptée, 10/11 refusée
            self.assertIsNone(validate_requested_date(PREV, self.config, field_label='X', node=self.rot))
            self.assertIsNotNone(validate_requested_date(
                date(2026, 11, 10), self.config, field_label='X', node=self.rot))
