"""
BUG-161 (B5) : en rotation, la fin de la journée de travail = la relève.
`shift-end-status` détecte (puis clôture de force après SHIFT_END_GRACE_MINUTES)
la session de la journée de travail PRÉCÉDENTE de l'équipe désignée ce jour-là.
Plusieurs journées passées ouvertes : ordre chronologique, une par appel.
Hors rotation : code A/B historique inchangé.
"""
from datetime import timezone as dt_timezone
from datetime import date, datetime, time
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyTeamAssignment, ProductionSession,
    ProductionSessionLine,
)

D = date(2026, 11, 12)
PREV = date(2026, 11, 11)
OLDER = date(2026, 11, 10)
SHIFT = '/api/production/sessions/shift-end-status/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _rotation(self, node=None, handover=time(12, 0)):
        node = node or self.node
        node.team_rotation_enabled = True
        node.handover_time = handover
        node.save()

    def _session(self, d, team, qty=10, node=None, assign=True):
        node = node or self.node
        if assign:
            DailyTeamAssignment.objects.get_or_create(node=node, work_date=d, defaults={'team': team})
        s = ProductionSession.objects.create(
            node=node, team=team, date=d, declared_by=self.gerant, node_origin=node.code,
        )
        ProductionSessionLine.objects.create(session=s, bread_price=self.bp, quantity=qty)
        stock, _ = BreadStock.objects.get_or_create(node=node, bread_price=self.bp)
        BreadStock.objects.filter(pk=stock.pk).update(qty_produced=qty)
        return s

    def _status(self, node=None):
        return self.api.get(SHIFT, {'node': (node or self.node).code})


class HandoverDetectionTests(_Base):
    def test_before_handover_nothing_pending(self):
        self._rotation()
        s = self._session(PREV, 'A')
        with _now(11, 59):
            r = self._status()
        self.assertFalse(r.data['pending_validation'])
        self.assertEqual(r.data['work_date'], '2026-11-11')
        self.assertIn('server_now', r.data)
        self.assertFalse(ProductionSession.objects.get(pk=s.pk).is_closed)

    def test_at_handover_pending_validation_for_designated_team(self):
        self._rotation()
        s = self._session(PREV, 'B')
        with _now(12, 0):
            r = self._status()
        self.assertTrue(r.data['pending_validation'])
        self.assertFalse(r.data['auto_closed'])
        self.assertEqual(r.data['team'], 'B')
        self.assertEqual(r.data['session'], s.pk)
        self.assertEqual(r.data['work_date'], '2026-11-11')
        self.assertEqual(r.data['current_work_date'], '2026-11-12')
        self.assertEqual(len(r.data['remaining']), 1)

    def test_midnight_is_not_a_closure_moment(self):
        self._rotation()
        s = self._session(PREV, 'A')
        # 00:00 le 12/11 : la journée de travail du 11/11 court encore jusqu'à 12:00.
        with _now(0, 0):
            r = self._status()
        self.assertFalse(r.data['pending_validation'])
        self.assertFalse(ProductionSession.objects.get(pk=s.pk).is_closed)

    def test_grace_period_then_forced_closure(self):
        self._rotation()
        s = self._session(PREV, 'A', qty=10)
        with _now(12, 29):
            self.assertTrue(self._status().data['pending_validation'])
        with _now(12, 30):
            r = self._status()
        self.assertEqual(r.data['pending_validation'], False)
        self.assertTrue(r.data['auto_closed'])
        self.assertEqual(r.data['team'], 'A')
        self.assertEqual(r.data['work_date'], '2026-11-11')
        s.refresh_from_db()
        self.assertTrue(s.is_closed)
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, date=PREV, team='A')
        self.assertEqual(snap.qty_at_close, 10)

    def test_idempotent_after_closure(self):
        self._rotation()
        self._session(PREV, 'A')
        with _now(13, 0):
            self.assertTrue(self._status().data['auto_closed'])
            r = self._status()
        self.assertFalse(r.data['pending_validation'])
        self.assertNotIn('auto_closed', r.data)
        self.assertEqual(DailyBreadStockSnapshot.objects.filter(node=self.node, date=PREV).count(), 1)

    def test_negative_stock_kept_with_warning(self):
        self._rotation()
        self._session(PREV, 'A', qty=1)
        BreadStock.objects.filter(node=self.node).update(qty_disposed=4)
        with _now(13, 0):
            self.assertTrue(self._status().data['auto_closed'])
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, date=PREV)
        self.assertEqual(snap.qty_at_close, -3)
        self.assertTrue(SystemNotification.objects.filter(severity='WARNING').exists())

    def test_current_work_day_session_never_closed(self):
        self._rotation()
        s = self._session(D, 'A')
        with _now(23, 0):
            r = self._status()
        self.assertFalse(r.data['pending_validation'])
        self.assertFalse(ProductionSession.objects.get(pk=s.pk).is_closed)

    def test_handover_at_midnight(self):
        self._rotation(handover=time(0, 0))
        s = self._session(PREV, 'A')
        with _now(0, 10):
            self.assertTrue(self._status().data['pending_validation'])
        with _now(0, 30):
            self.assertTrue(self._status().data['auto_closed'])
        s.refresh_from_db()
        self.assertTrue(s.is_closed)

    def test_handover_at_23_30(self):
        self._rotation(handover=time(23, 30))
        s = self._session(PREV, 'A')
        # Journée du 11/11 : 23:30 le 11 -> 23:30 le 12. À 23:00 le 12 : pas de relève.
        with _now(23, 0):
            self.assertFalse(self._status().data['pending_validation'])
        with _now(23, 45):
            r = self._status()
        self.assertTrue(r.data['pending_validation'])
        with _now(0, 5, d=date(2026, 11, 13)):
            r = self._status()
        self.assertTrue(r.data['auto_closed'])
        s.refresh_from_db()
        self.assertTrue(s.is_closed)

    def test_two_nodes_with_different_handovers(self):
        other = make_node(code='K2')
        self._rotation()                                    # K1 12:00
        self._rotation(other, handover=time(18, 0))         # K2 18:00
        self._session(PREV, 'A')
        self._session(PREV, 'B', node=other)
        g2 = make_user('GERANT', node=other, team='A')
        api2 = APIClient()
        api2.force_authenticate(g2)
        with _now(12, 10):
            k1 = self._status()
            k2 = api2.get(SHIFT, {'node': 'K2'})
        self.assertTrue(k1.data['pending_validation'])
        self.assertFalse(k2.data['pending_validation'])      # K2 : relève à 18:00
        with _now(18, 5):
            k2 = api2.get(SHIFT, {'node': 'K2'})
        self.assertTrue(k2.data['pending_validation'])
        self.assertEqual(k2.data['team'], 'B')

    def test_only_designated_team_session_is_targeted(self):
        self._rotation()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        self._session(PREV, 'A', assign=False)
        sb = self._session(PREV, 'B', assign=False)
        with _now(12, 5):
            r = self._status()
        self.assertEqual(r.data['session'], sb.pk)

    def test_no_session_nothing_to_do(self):
        self._rotation()
        with _now(13, 0):
            r = self._status()
        self.assertEqual(r.data['pending_validation'], False)
        self.assertEqual(r.data['work_date'], '2026-11-12')


class SeveralPastDaysTests(_Base):
    def test_processed_in_chronological_order_one_per_call(self):
        self._rotation()
        s1 = self._session(OLDER, 'A')
        s2 = self._session(PREV, 'B')
        with _now(15, 0):
            r1 = self._status()
            self.assertTrue(r1.data['auto_closed'])
            self.assertEqual(r1.data['work_date'], '2026-11-10')
            s1.refresh_from_db()
            s2.refresh_from_db()
            self.assertTrue(s1.is_closed)
            self.assertFalse(s2.is_closed)
            r2 = self._status()
            self.assertTrue(r2.data['auto_closed'])
            self.assertEqual(r2.data['work_date'], '2026-11-11')
            self.assertEqual(r2.data['team'], 'B')
            r3 = self._status()
        s2.refresh_from_db()
        self.assertTrue(s2.is_closed)
        self.assertFalse(r3.data['pending_validation'])
        self.assertEqual(DailyBreadStockSnapshot.objects.filter(node=self.node).count(), 2)

    def test_oldest_day_first_even_when_newer_is_in_grace(self):
        self._rotation()
        self._session(OLDER, 'A')
        self._session(PREV, 'B')
        with _now(12, 10):
            r = self._status()
            # OLDER est dépassée depuis longtemps : clôturée en premier.
            self.assertTrue(r.data['auto_closed'])
            self.assertEqual(r.data['work_date'], '2026-11-10')
            r = self._status()
        self.assertTrue(r.data['pending_validation'])
        self.assertEqual(r.data['work_date'], '2026-11-11')


class WithoutRotationTests(_Base):
    def test_legacy_shift_loop_unchanged(self):
        self.node.team_a_end_time = time(13, 0)
        self.node.save()
        s = ProductionSession.objects.create(
            node=self.node, team='A', date=D, declared_by=self.gerant, node_origin='K1',
        )
        with _now(13, 40):
            r = self._status()
        self.assertEqual(r.data, {'pending_validation': False, 'auto_closed': True, 'team': 'A'})
        s.refresh_from_db()
        self.assertTrue(s.is_closed)

    def test_previous_day_session_ignored_without_rotation(self):
        self._session(PREV, 'A', assign=False)
        with _now(15, 0):
            r = self._status()
        self.assertEqual(r.data, {'pending_validation': False})
