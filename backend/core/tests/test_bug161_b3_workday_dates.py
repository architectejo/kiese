"""
BUG-161 (B3) / BUG-247 : `work_date_for(node, instant)` — source unique de la
date de travail côté serveur. DÉCISION CLIENT 2026-11-12 : date LOCALE du
calendrier (jamais la date UTC), avec ou sans rotation (plus de journée de
relève à relève). La date de PÉRIODE de service (`business_date`) ne sert qu'à
la désignation d'équipe.
"""
from datetime import date, datetime, time, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.testing import make_node, get_config
from core.utils import validate_requested_date
from core.workday import (
    work_date_for, work_time_info, delivered_on_work_date_filter, workday_bounds,
    business_date, shift_date,
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

    def test_rotation_work_date_is_calendar_date_around_handover(self):
        # BUG-247 : une vente à 03:00 est du jour calendaire, pas de la veille ;
        # la relève de 12:00 ne change pas la date de travail.
        for h, m, s in ((0, 0, 0), (0, 30, 0), (3, 0, 0), (9, 0, 0), (11, 59, 59), (12, 0, 0), (23, 59, 0)):
            self.assertEqual(work_date_for(self.rot, _at(D, h, m, s)), D)

    def test_rotation_shift_date_keeps_handover_semantics(self):
        # La désignation d'équipe reste rattachée à la période de service.
        self.assertEqual(business_date(self.rot, _at(D, 3, 0)), PREV)
        self.assertEqual(business_date(self.rot, _at(D, 11, 59, 59)), PREV)
        self.assertEqual(business_date(self.rot, _at(D, 12, 0)), D)
        self.assertEqual(shift_date(self.rot, _at(D, 3, 0)), PREV)
        self.assertEqual(shift_date(self.plain, _at(D, 3, 0)), D)

    def test_rotation_with_midnight_handover_equals_calendar_date(self):
        self.rot.handover_time = time(0, 0)
        self.rot.save()
        for h in (0, 3, 12, 23):
            self.assertEqual(work_date_for(self.rot, _at(D, h, 0)), D)

    def test_rotation_default_instant_uses_now(self):
        with _now(3, 0):
            self.assertEqual(work_date_for(self.rot), D)
        with _now(12, 0):
            self.assertEqual(work_date_for(self.rot), D)

    def test_node_none_falls_back_to_local_date(self):
        with _now(0, 30):
            self.assertEqual(work_date_for(None), D)

    def test_work_time_info(self):
        with _now(3, 0):
            info = work_time_info(self.rot)
            self.assertEqual(info['work_date'], '2026-11-12')
            self.assertTrue(info['server_now'].startswith('2026-11-12T03:00:00'))
            self.assertEqual(work_time_info(self.plain)['work_date'], '2026-11-12')

    def test_delivered_filter_matches_bounds(self):
        self.assertEqual(delivered_on_work_date_filter(self.plain, D), {'delivered_at__date': D})
        # BUG-247 : même filtre calendaire en rotation.
        self.assertEqual(delivered_on_work_date_filter(self.rot, PREV), {'delivered_at__date': PREV})
        start, end = workday_bounds(self.rot, PREV)  # bornes de période de service
        self.assertEqual((end - start).total_seconds(), 24 * 3600)


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

    def test_rotation_future_means_after_current_calendar_date(self):
        with _now(3, 0):  # BUG-247 : date de travail = 12/11 (calendaire)
            self.assertIsNone(validate_requested_date(PREV, self.config, field_label='X', node=self.rot))
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X', node=self.rot))
            err = validate_requested_date(date(2026, 11, 13), self.config, field_label='X', node=self.rot)
            self.assertIn('future', err)
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X', node=self.plain))
        with _now(12, 0):
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X', node=self.rot))

    def test_rotation_past_refused_when_backdating_disabled(self):
        self.config.allow_backdated_sales = False
        self.config.save()
        with _now(3, 0):
            # le jour calendaire courant (12/11) reste accepté, 11/11 refusé
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X', node=self.rot))
            self.assertIsNotNone(validate_requested_date(PREV, self.config, field_label='X', node=self.rot))
