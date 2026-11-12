"""
BUG-161 (B4) : boîte « Stock de départ du jour » aux heures de rotation.

En rotation (`Node.team_rotation_enabled`) : une confirmation par PÉRIODE DE
SERVICE (de relève à relève, BUG-247 : la date de travail reste calendaire),
quelle que soit l'équipe ; l'équipe concernée
est l'équipe désignée ; chaînage inter-équipes (le reste de A devient le
départ de B) ; confirmer un départ ne modifie JAMAIS le snapshot ni le rapport
de la journée précédente. Hors rotation : comportement historique inchangé.
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
    ProductionSession,
)
from production.views import _build_daily_closure_report

D = date(2026, 11, 12)
PREV = date(2026, 11, 11)
OPENING = '/api/production/opening-confirmation/'
SESSIONS = '/api/production/sessions/'


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

    def _assign(self, d, team, node=None):
        DailyTeamAssignment.objects.create(node=node or self.node, work_date=d, team=team)

    def _post(self, qty=10, **extra):
        payload = {'lines': [{'bread_price': self.bp.pk, 'qty': qty}]}
        payload.update(extra)
        return self.api.post(OPENING, payload, format='json')

    def _proposed(self, response):
        return {c['bread_price']: c['qty_proposed'] for c in response.data['categories']}[self.bp.pk]


class RotationNeedsConfirmationTests(_Base):
    def test_no_assignment_requires_assignment_first(self):
        self._rotation()
        with _now(12, 0):
            r = self.api.get(OPENING)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['team_assignment_required'])
        self.assertFalse(r.data['needs_confirmation'])
        self.assertIsNone(r.data['opening_team'])

    def test_assigned_team_needs_confirmation_at_handover(self):
        self._rotation()
        self._assign(D, 'B')
        with _now(12, 0):
            r = self.api.get(OPENING)
        self.assertFalse(r.data['team_assignment_required'])
        self.assertTrue(r.data['needs_confirmation'])
        self.assertEqual(r.data['opening_team'], 'B')
        self.assertEqual(r.data['team'], 'B')
        self.assertEqual(r.data['work_date'], '2026-11-12')

    def test_before_handover_belongs_to_previous_work_day(self):
        # 11:59 : encore la journée du 11/11, désignée A et déjà confirmée.
        self._rotation()
        self._assign(PREV, 'A')
        self._assign(D, 'B')
        with _now(9, 0):
            self.assertTrue(self.api.get(OPENING).data['needs_confirmation'])
            self.assertEqual(self._post(team='A').status_code, 200)
        with _now(11, 59):
            r = self.api.get(OPENING)
        self.assertEqual(r.data['date'], '2026-11-12')  # BUG-247 : date calendaire
        self.assertEqual(r.data['team'], 'A')           # équipe de la période démarrée le 11/11
        self.assertFalse(r.data['needs_confirmation'])
        with _now(12, 0):
            r = self.api.get(OPENING)
        self.assertEqual(r.data['date'], '2026-11-12')
        self.assertTrue(r.data['needs_confirmation'])

    def test_midnight_does_not_reopen_box(self):
        self._rotation()
        self._assign(D, 'A')
        with _now(13, 0):
            self.assertEqual(self._post().status_code, 200)
        with _now(0, 0, d=date(2026, 11, 13)):
            r = self.api.get(OPENING)
        self.assertEqual(r.data['date'], '2026-11-13')  # BUG-247 : minuit change la date, pas l'équipe
        self.assertFalse(r.data['needs_confirmation'])

    def test_confirmation_by_any_team_clears_the_box(self):
        self._rotation()
        self._assign(D, 'B')
        c = DailyOpeningConfirmation.objects.create(node=self.node, team='A', date=D, confirmed_by=self.gerant)
        DailyOpeningConfirmation.objects.filter(pk=c.pk).update(confirmed_at=_at(D, 12, 30))
        with _now(13, 0):
            r = self.api.get(OPENING)
        self.assertFalse(r.data['needs_confirmation'])

    def test_handover_at_midnight(self):
        self._rotation(handover=time(0, 0))
        self._assign(D, 'A')
        with _now(0, 0):
            r = self.api.get(OPENING)
        self.assertEqual(r.data['date'], '2026-11-12')
        self.assertTrue(r.data['needs_confirmation'])

    def test_handover_at_23_30(self):
        self._rotation(handover=time(23, 30))
        self._assign(PREV, 'A')
        self._assign(D, 'B')
        with _now(23, 29):
            r = self.api.get(OPENING)
        self.assertEqual(r.data['date'], '2026-11-12')
        self.assertEqual(r.data['opening_team'], 'A')
        with _now(23, 30):
            r = self.api.get(OPENING)
        self.assertEqual(r.data['date'], '2026-11-12')
        self.assertEqual(r.data['opening_team'], 'B')
        self.assertTrue(r.data['needs_confirmation'])

    def test_two_nodes_with_different_handovers(self):
        other = make_node(code='K2')
        self._rotation()                                   # K1 : 12:00
        self._rotation(other, handover=time(18, 0))        # K2 : 18:00
        self._assign(D, 'A')
        self._assign(PREV, 'B', node=other)
        self._assign(D, 'A', node=other)
        g2 = make_user('GERANT', node=other, team='A')
        api2 = APIClient()
        api2.force_authenticate(g2)
        with _now(13, 0):
            k1 = self.api.get(OPENING)
            k2 = api2.get(OPENING)
        self.assertEqual(k1.data['date'], '2026-11-12')
        self.assertEqual(k2.data['date'], '2026-11-12')    # BUG-247 : même date calendaire
        self.assertEqual(k2.data['team'], 'B')             # K2 n'a pas encore sa relève
        self.assertEqual(k2.data['opening_team'], 'B')

    def test_without_rotation_response_is_unchanged(self):
        with _now(13, 0):
            r = self.api.get(OPENING)
        self.assertIn('opening_team', r.data)
        self.assertNotIn('team_assignment_required', r.data)
        self.assertNotIn('rotation', r.data)
        self.assertIn('needs_confirmation', r.data)


class RotationPostTests(_Base):
    def test_post_without_assignment_refused(self):
        self._rotation()
        with _now(13, 0):
            r = self._post(team='A')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['code'], 'TEAM_NOT_ASSIGNED')
        self.assertFalse(DailyOpeningConfirmation.objects.exists())

    def test_post_records_for_designated_team_without_team_field(self):
        self._rotation()
        self._assign(D, 'B')
        with _now(13, 0):
            r = self._post()
        self.assertEqual(r.status_code, 200, r.data)
        conf = DailyOpeningConfirmation.objects.get(node=self.node, date=D)
        self.assertEqual(conf.team, 'B')
        self.assertEqual(r.data['team'], 'B')
        self.assertTrue(ProductionSession.objects.filter(node=self.node, date=D, team='B').exists())

    def test_post_other_team_rejected(self):
        self._rotation()
        self._assign(D, 'B')
        with _now(13, 0):
            r = self._post(team='A')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(DailyOpeningConfirmation.objects.exists())
        self.assertFalse(BreadStock.objects.exists())

    def test_post_same_team_explicit_ok_and_idempotent(self):
        self._rotation()
        self._assign(D, 'A')
        with _now(13, 0):
            self.assertEqual(self._post(team='A', qty=5).status_code, 200)
            self.assertEqual(self._post(team='A', qty=8).status_code, 200)
        self.assertEqual(DailyOpeningConfirmation.objects.filter(node=self.node, date=D).count(), 1)

    def test_post_after_midnight_uses_previous_work_day_team(self):
        self._rotation()
        self._assign(PREV, 'A')
        self._assign(D, 'B')
        with _now(2, 0):
            r = self._post()
        self.assertEqual(r.data['date'], '2026-11-12')  # BUG-247 : date calendaire
        self.assertEqual(r.data['team'], 'A')           # équipe de la période démarrée le 11/11

    def test_without_rotation_team_still_required(self):
        with _now(13, 0):
            r = self._post()
        self.assertEqual(r.status_code, 400)
        with _now(13, 0):
            r = self._post(team='B')
        self.assertEqual(r.status_code, 200, r.data)


class ChainingTests(_Base):
    def _snapshot(self, d, team, qty):
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp, date=d, team=team, qty_at_close=qty,
        )

    def test_proposed_quantity_comes_from_last_snapshot_any_team(self):
        self._rotation()
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=99)
        self._snapshot(PREV, 'A', 7)
        self._assign(D, 'B')
        with _now(12, 0):
            r = self.api.get(OPENING)
        self.assertEqual(self._proposed(r), 7)

    def test_chain_a_then_b_then_a(self):
        self._rotation()
        self._snapshot(date(2026, 11, 10), 'A', 4)
        self._snapshot(PREV, 'B', 9)
        self._assign(D, 'A')
        with _now(12, 0):
            self.assertEqual(self._proposed(self.api.get(OPENING)), 9)
        self._snapshot(D, 'A', 3)
        self._assign(date(2026, 11, 13), 'B')
        with _now(12, 0, d=date(2026, 11, 13)):
            self.assertEqual(self._proposed(self.api.get(OPENING)), 3)

    def test_without_snapshot_falls_back_to_current_stock(self):
        self._rotation()
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=12)
        self._assign(D, 'A')
        with _now(12, 0):
            self.assertEqual(self._proposed(self.api.get(OPENING)), 12)

    def test_without_rotation_proposed_is_current_stock(self):
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=12)
        self._snapshot(PREV, 'A', 7)
        with _now(12, 0):
            self.assertEqual(self._proposed(self.api.get(OPENING)), 12)

    def test_report_reste_du_hier_chained_on_designated_team_only(self):
        self._rotation()
        self._snapshot(PREV, 'A', 7)
        self._assign(D, 'B')
        report = _build_daily_closure_report(self.node, D)
        cat = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(cat['reste_du_hier'], {'A': 0, 'B': -7})

    def test_report_without_rotation_keeps_per_team_chain(self):
        self._snapshot(PREV, 'A', 7)
        report = _build_daily_closure_report(self.node, D)
        cat = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(cat['reste_du_hier'], {'A': -7, 'B': 0})

    def test_report_confirmed_value_still_wins(self):
        self._rotation()
        self._snapshot(PREV, 'A', 7)
        self._assign(D, 'B')
        with _now(13, 0):
            self.assertEqual(self._post(qty=5).status_code, 200)
        report = _build_daily_closure_report(self.node, D)
        cat = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(cat['reste_du_hier']['B'], -5)


class PreviousDayFrozenTests(_Base):
    """Garde (e) : confirmer/modifier un départ J+1 ne touche pas la clôture de J."""

    def _closed_day(self):
        self._assign(PREV, 'A')
        with _now(13, 0, d=PREV):
            r = self.api.post(SESSIONS, {
                'flour_sacks_used': '1.00', 'lines': [{'bread_price': self.bp.pk, 'quantity': 20}],
            }, format='json')
            self.assertEqual(r.status_code, 201, r.data)
            sid = r.data['id']
            c = self.api.post(f'{SESSIONS}{sid}/close/', {
                'remaining': [{'bread_price': self.bp.pk, 'quantity': 6}],
            }, format='json')
            self.assertEqual(c.status_code, 200, c.data)
        return sid

    def _state(self):
        snap = list(DailyBreadStockSnapshot.objects.filter(node=self.node, date=PREV)
                    .values_list('team', 'bread_price_id', 'qty_at_close', 'updated_at'))
        report = _build_daily_closure_report(self.node, PREV)
        report.pop('server_now', None)  # horodatage de la réponse, non métier
        session = ProductionSession.objects.get(node=self.node, date=PREV)
        return snap, report, session.closed_at, session.closure_summary, session.lines.count()

    def test_confirming_next_day_start_with_gap_leaves_previous_day_untouched(self):
        self._rotation()
        self._closed_day()
        self._assign(D, 'B')
        before = self._state()
        self.assertEqual(before[0][0][2], 6)
        with _now(12, 5):
            self.assertEqual(self._proposed(self.api.get(OPENING)), 6)
            r = self._post(qty=2)            # écart : 6 proposé, 2 confirmé
            self.assertEqual(r.status_code, 200, r.data)
            r = self._post(qty=11)           # modification
            self.assertEqual(r.status_code, 200, r.data)
        after = self._state()
        self.assertEqual(before, after)
        self.assertTrue(ProductionSession.objects.get(node=self.node, date=PREV).is_closed)
        # BUG-247 : le rapport du jour D (UN seul, deux équipes) démarre sur le
        # reste de l'équipe A (période démarrée la veille) ; la confirmation de
        # l'équipe entrante B à la relève est un transfert interne, jamais
        # additionnée telle quelle au « reste du hier » : seul son ÉCART avec le
        # dernier reste déclaré (11 confirmés - 6) est ajouté au départ de journée.
        report_d = _build_daily_closure_report(self.node, D)
        cat = next(c for c in report_d['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(cat['reste_du_hier'], {'A': -11, 'B': 0})
