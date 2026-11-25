"""
BUG-161 (B3) / BUG-247 / BUG-1130 : `work_date_for(node, instant)` - source unique
de la date de travail cote serveur. DECISION CLIENT 2026-11-24 (Q-018, remplace
celle du 2026-11-12 « jour calendaire ») : JOURNEE COMPTABLE DE MIDI A MIDI
(heure de cloture `Node.handover_time`, 12:00 par defaut), date locale (jamais
UTC), avec ou sans rotation. Une vente a D+1 09:00 appartient a la journee D.
Tests adaptes en BUG-1130 : les attentes calendaires (03:00 = jour calendaire,
00:30 = jour calendaire) deviennent des attentes de journee comptable.
"""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
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
    # Comme `timezone.now()` reel : datetime aware en UTC (BUG-189 : `.date()` = date UTC).
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class WorkDateForTests(TestCase):
    def setUp(self):
        self.plain = make_node(code='K1')
        self.rot = make_node(code='K2')
        self.rot.team_rotation_enabled = True
        self.rot.handover_time = time(12, 0)
        self.rot.save()

    def test_without_rotation_is_local_business_day_at_00_30(self):
        # 00:30 locale = 23:30 UTC la veille : la date est LOCALE, et BUG-1130 :
        # avant 12:00 on est encore dans la journee comptable de la veille.
        instant = _at(D, 0, 30)
        self.assertEqual(instant.astimezone(dt_timezone.utc).date(), PREV)
        self.assertEqual(work_date_for(self.plain, instant), PREV)
        with _now(0, 30):
            self.assertEqual(work_date_for(self.plain), PREV)
        with _now(12, 30):
            self.assertEqual(work_date_for(self.plain), D)
            self.assertEqual(work_date_for(self.plain), timezone.localdate())

    def test_without_rotation_same_midi_a_midi_rule(self):
        # BUG-1130 : meme regle avec ou sans rotation (Q-017/Q-018).
        self.assertEqual(work_date_for(self.plain, _at(D, 3, 0)), PREV)
        self.assertEqual(work_date_for(self.plain, _at(D, 11, 59)), PREV)
        self.assertEqual(work_date_for(self.plain, _at(D, 12, 0)), D)

    def test_rotation_work_date_is_business_day_around_handover(self):
        # BUG-1130 : une vente a 03:00 est de la journee de la veille (midi a midi).
        for h, m, s in ((0, 0, 0), (0, 30, 0), (3, 0, 0), (9, 0, 0), (11, 59, 59)):
            self.assertEqual(work_date_for(self.rot, _at(D, h, m, s)), PREV)
        for h, m, s in ((12, 0, 0), (23, 59, 0)):
            self.assertEqual(work_date_for(self.rot, _at(D, h, m, s)), D)

    def test_rotation_shift_date_keeps_handover_semantics(self):
        # La designation d'equipe reste rattachee a la periode de service.
        self.assertEqual(business_date(self.rot, _at(D, 3, 0)), PREV)
        self.assertEqual(business_date(self.rot, _at(D, 11, 59, 59)), PREV)
        self.assertEqual(business_date(self.rot, _at(D, 12, 0)), D)
        self.assertEqual(shift_date(self.rot, _at(D, 3, 0)), PREV)
        # Hors rotation la designation reste calendaire (BUG-227, perimetre team_rotation_enabled).
        self.assertEqual(shift_date(self.plain, _at(D, 3, 0)), D)

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

    def test_node_none_falls_back_to_default_noon(self):
        with _now(0, 30):
            self.assertEqual(work_date_for(None), PREV)
        with _now(12, 30):
            self.assertEqual(work_date_for(None), D)

    def test_work_time_info(self):
        with _now(3, 0):
            info = work_time_info(self.rot)
            self.assertEqual(info['work_date'], '2026-11-11')
            self.assertTrue(info['server_now'].startswith('2026-11-12T03:00:00'))
            self.assertEqual(work_time_info(self.plain)['work_date'], '2026-11-11')

    def test_delivered_filter_matches_bounds(self):
        start, end = workday_bounds(self.plain, D)
        self.assertEqual(delivered_on_work_date_filter(self.plain, D),
                         {'delivered_at__gte': start, 'delivered_at__lt': end})
        self.assertEqual((start, end), (_at(D, 12), _at(D + timedelta(days=1), 12)))
        start, end = workday_bounds(self.rot, PREV)
        self.assertEqual(delivered_on_work_date_filter(self.rot, PREV),
                         {'delivered_at__gte': start, 'delivered_at__lt': end})
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

    def test_without_rotation_today_is_business_day(self):
        with _now(0, 30):  # BUG-1130 : journee comptable = 11/11
            self.assertIsNone(validate_requested_date(PREV, self.config, field_label='X', node=self.plain))
            self.assertIsNone(validate_requested_date(PREV, self.config, field_label='X'))
            self.assertIn('future', validate_requested_date(D, self.config, field_label='X', node=self.plain))

    def test_rotation_future_means_after_current_business_day(self):
        with _now(3, 0):  # BUG-1130 : journee comptable = 11/11
            self.assertIsNone(validate_requested_date(date(2026, 11, 10), self.config, field_label='X', node=self.rot))
            self.assertIsNone(validate_requested_date(PREV, self.config, field_label='X', node=self.rot))
            err = validate_requested_date(D, self.config, field_label='X', node=self.rot)
            self.assertIn('future', err)
            self.assertIsNone(validate_requested_date(PREV, self.config, field_label='X', node=self.plain))
        with _now(12, 0):
            self.assertIsNone(validate_requested_date(D, self.config, field_label='X', node=self.rot))

    def test_rotation_past_refused_when_backdating_disabled(self):
        self.config.allow_backdated_sales = False
        self.config.save()
        with _now(3, 0):
            # la journee comptable courante (11/11) reste acceptee, 10/11 refuse
            self.assertIsNone(validate_requested_date(PREV, self.config, field_label='X', node=self.rot))
            self.assertIsNotNone(validate_requested_date(
                date(2026, 11, 10), self.config, field_label='X', node=self.rot))
