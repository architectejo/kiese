"""
BUG-190 à BUG-194 et BUG-196 (volet backend), dev-backend 2026-11-12.

Rotation d'équipes (`Node.team_rotation_enabled`) : journée de travail de
relève à relève (relève 12:00 ici). Horloge simulée : `timezone.now` renvoie
un datetime UTC aware ; Kinshasa = UTC+1. Données fictives.
"""
from datetime import date, datetime, time
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_node, make_user
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmation, DailyTeamAssignment,
    ProductionSession,
)

J = date(2026, 11, 12)
J1 = date(2026, 11, 13)
ASSIGN = '/api/production/team-assignment/'
OPENING = '/api/production/opening-confirmation/'
SESSIONS = '/api/production/sessions/'
SHIFT = '/api/production/sessions/shift-end-status/'
CLOSURE = '/api/production/daily-closure/'


def _now(h, m=0, d=J):
    aware = timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())
    return patch('django.utils.timezone.now', return_value=aware.astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', sac_value_fc=Decimal('200000'))
        self.bp500 = make_bread_price('B190_500', 'Pain 500 FC', 500)
        self.bp300 = make_bread_price('B190_300', 'Pain 300 FC', 300)
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.g = APIClient()
        self.g.force_authenticate(self.gerant)

    def _rotation(self, node=None):
        node = node or self.node
        node.team_rotation_enabled = True
        node.handover_time = time(12, 0)
        node.save()

    def _assign(self, team):
        r = self.g.post(ASSIGN, {'team': team}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        return r

    def _produce(self, bp, qty, **extra):
        payload = {'flour_sacks_used': '1.00', 'lines': [{'bread_price': bp.pk, 'quantity': qty}]}
        payload.update(extra)
        return self.g.post(SESSIONS, payload, format='json')


class Bug190ClosureOfCorrectedTeamTests(_Base):
    def test_open_session_of_previous_designated_team_is_closed(self):
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            self.assertEqual(self._produce(self.bp500, 10).status_code, 201)
        with _now(14, 0):
            self._assign('B')  # correction de la journée courante : permise
        with _now(13, 0, d=J1):
            r = self.g.get(SHIFT)
        self.assertTrue(r.data['auto_closed'], r.data)
        self.assertEqual(r.data['team'], 'A')
        self.assertTrue(ProductionSession.objects.get(node=self.node, date=J, team='A').is_closed)
        snaps = DailyBreadStockSnapshot.objects.filter(node=self.node, date=J)
        self.assertEqual([(s.team, s.qty_at_close) for s in snaps], [('A', 10)])

    def test_pending_validation_proposed_before_grace_delay(self):
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            self._produce(self.bp500, 10)
            self._assign('B')
        with _now(12, 10, d=J1):
            r = self.g.get(SHIFT)
        self.assertTrue(r.data['pending_validation'])
        self.assertEqual(r.data['team'], 'A')

    def test_two_open_sessions_same_day_rest_recorded_once(self):
        """Session A (désignation corrigée) + session B : le reste n'est enregistré qu'une fois."""
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            self._produce(self.bp500, 10)
        with _now(14, 0):
            self._assign('B')
            self.assertEqual(self._produce(self.bp500, 5).status_code, 201)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500).qty_available
        with _now(13, 0, d=J1):
            r1 = self.g.get(SHIFT)   # session de l'équipe désignée (B) : porte le reste
            r2 = self.g.get(SHIFT)   # session restante (A) : clôturée sans second reste
            r3 = self.g.get(SHIFT)
        self.assertEqual((r1.data['auto_closed'], r1.data['team']), (True, 'B'))
        self.assertEqual((r2.data['auto_closed'], r2.data['team']), (True, 'A'))
        self.assertFalse(r3.data['pending_validation'])
        self.assertTrue(all(s.is_closed for s in ProductionSession.objects.filter(node=self.node)))
        snaps = list(DailyBreadStockSnapshot.objects.filter(node=self.node, date=J))
        self.assertEqual([(s.team, s.qty_at_close) for s in snaps], [('B', stock)])
        with _now(13, 5, d=J1):
            self._assign('A')
            prop = {c['bread_price']: c['qty_proposed'] for c in self.g.get(OPENING).data['categories']}
        self.assertEqual(prop[self.bp500.pk], stock)
        # rapport de la journée : reste du jour compté une seule fois
        with _now(13, 10, d=J1):
            rep = self.g.get(CLOSURE, {'date': str(J)})
        row = {x['bread_price']: x for x in rep.data['categories']}[self.bp500.pk]
        self.assertEqual(sum(v or 0 for v in row['reste_du_jour'].values()), stock)


class Bug191SingleSourceTests(_Base):
    def test_confirmed_category_not_chained_again_but_others_still_are(self):
        self._rotation()
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp500, date=J, team='A', qty_at_close=10)
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp300, date=J, team='A', qty_at_close=4)
        with _now(13, 0, d=J1):
            self._assign('B')
            c = self.g.post(OPENING, {'lines': [{'bread_price': self.bp500.pk, 'qty': 10}]}, format='json')
            self.assertEqual(c.status_code, 200, c.data)
            self._assign('A')
            rep = self.g.get(CLOSURE, {'date': str(J1)})
        rows = {x['bread_price']: x for x in rep.data['categories']}
        self.assertEqual(sum(rows[self.bp500.pk]['reste_du_hier'].values()), -10)
        # catégorie non confirmée : chaînage automatique inchangé, porté une seule fois
        self.assertEqual(sum(rows[self.bp300.pk]['reste_du_hier'].values()), -4)
        self.assertEqual(rows[self.bp300.pk]['reste_du_hier']['A'], -4)


class Bug192SessionTeamTests(_Base):
    def test_team_other_than_designated_is_refused(self):
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            r = self._produce(self.bp500, 5, team='B')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('équipe', r.data['detail'])
        self.assertEqual(ProductionSession.objects.count(), 0)

    def test_no_designation_is_403_team_not_assigned(self):
        self._rotation()
        with _now(13, 0):
            r = self._produce(self.bp500, 5, team='A')
            r2 = self._produce(self.bp500, 5)
        for resp in (r, r2):
            self.assertEqual(resp.status_code, 403, resp.data)
            self.assertEqual(resp.data['code'], 'TEAM_NOT_ASSIGNED')
        self.assertEqual(ProductionSession.objects.count(), 0)

    def test_designated_team_explicit_or_omitted_is_accepted(self):
        self._rotation()
        with _now(13, 0):
            self._assign('B')
            self.assertEqual(self._produce(self.bp500, 5, team='B').status_code, 201)
            self.assertEqual(self._produce(self.bp500, 5).status_code, 201)
        self.assertEqual(list(ProductionSession.objects.values_list('team', flat=True)), ['B'])

    def test_without_rotation_any_team_still_accepted(self):
        with _now(13, 0):
            r = self._produce(self.bp500, 5, team='B', date='2026-11-12')
        self.assertEqual(r.status_code, 201, r.data)


class Bug193TransferWorkDayTests(_Base):
    def _confirmed_transfer(self, h, m=0, d=J1):
        other = make_node(code='K2')
        a2 = APIClient()
        a2.force_authenticate(make_user('GERANT', node=other))
        with _now(h, m, d=d):
            c = self.g.post('/api/production/transfers/', {
                'from_node': other.pk,
                'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 15}],
            }, format='json')
            self.assertEqual(c.status_code, 201, c.data)
            tid = c.data['id']
            self.assertEqual(a2.post(f'/api/production/transfers/{tid}/respond_to_request/', {
                'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 15}],
            }, format='json').status_code, 200)
            self.assertEqual(self.g.post(f'/api/production/transfers/{tid}/confirm_reception/', {
                'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 15}],
            }, format='json').status_code, 200)
        return other, a2

    def _qty(self, api, day, key, node_param):
        rep = api.get(CLOSURE, {'date': str(day), 'node': node_param})
        self.assertEqual(rep.status_code, 200, rep.data)
        return {x['bread_price']: x for x in rep.data['categories']}[self.bp300.pk][key]['quantity']

    def test_rotation_transfer_at_03_00_belongs_to_calendar_day_both_sides(self):
        # BUG-247 (décision 2026-11-12) : un appro confirmé à 03:00 est du jour
        # calendaire J1, même en rotation (plus de rattachement à la veille).
        self._rotation()
        other, a2 = self._confirmed_transfer(3)
        self._rotation(other)
        with _now(14, 0, d=J1):
            self.assertEqual(self._qty(self.g, J1, 'appro_recu', self.node.code), 15)
            self.assertEqual(self._qty(self.g, J, 'appro_recu', self.node.code), 0)
        with _now(14, 0, d=J1):
            self.assertEqual(self._qty(a2, J1, 'appro_effectue', other.code), 15)
            self.assertEqual(self._qty(a2, J, 'appro_effectue', other.code), 0)

    def test_rotation_transfer_after_handover_belongs_to_current_work_day(self):
        self._rotation()
        self._confirmed_transfer(13)
        with _now(14, 0, d=J1):
            self.assertEqual(self._qty(self.g, J1, 'appro_recu', self.node.code), 15)
            self.assertEqual(self._qty(self.g, J, 'appro_recu', self.node.code), 0)


class Bug194NonObjectBodyTests(_Base):
    def test_opening_confirmation_post(self):
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            for body in (['A'], 'x', 3):
                r = self.g.post(OPENING, body, format='json')
                self.assertEqual(r.status_code, 400, r.data)
                self.assertEqual(r.data['detail'], "Corps de requête invalide : un objet JSON est attendu.")
        self.assertEqual(DailyOpeningConfirmation.objects.count(), 0)

    def test_session_close_and_transfer_actions(self):
        with _now(13, 0):
            s = self._produce(self.bp500, 5, team='A', date='2026-11-12')
            self.assertEqual(s.status_code, 201, s.data)
            r = self.g.post(f"{SESSIONS}{s.data['id']}/close/", ['x'], format='json')
            self.assertEqual(r.status_code, 400, r.data)
            self.assertIn('objet JSON', r.data['detail'])
            self.assertFalse(ProductionSession.objects.get(pk=s.data['id']).is_closed)

    def test_valid_body_unchanged(self):
        with _now(13, 0):
            r = self.g.post(OPENING, {'team': 'A', 'lines': [{'bread_price': self.bp500.pk, 'qty': 2}]},
                            format='json')
        self.assertEqual(r.status_code, 200, r.data)


class Bug196PreviousWorkdayOpenTests(_Base):
    def _open_previous_day(self):
        with _now(13, 0):
            self._assign('A')
            self.assertEqual(self._produce(self.bp500, 10).status_code, 201)

    def test_assignment_refused_while_previous_day_open(self):
        self._rotation()
        self._open_previous_day()
        with _now(12, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(r.data['code'], 'PREVIOUS_WORKDAY_OPEN')
        self.assertIn("Confirmez d'abord le reste du jour précédent", r.data['detail'])
        self.assertFalse(DailyTeamAssignment.objects.filter(node=self.node, work_date=J1).exists())

    def test_auto_closure_unblocks_assignment(self):
        self._rotation()
        self._open_previous_day()
        with _now(12, 5, d=J1):
            self.assertEqual(self.g.post(ASSIGN, {'team': 'B'}, format='json').status_code, 400)
        with _now(12, 31, d=J1):
            self.assertTrue(self.g.get(SHIFT).data['auto_closed'])
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['team'], 'B')

    def test_manual_closure_unblocks_assignment(self):
        self._rotation()
        self._open_previous_day()
        sid = ProductionSession.objects.get(node=self.node, date=J).pk
        with _now(12, 5, d=J1):
            c = self.g.post(f'{SESSIONS}{sid}/close/', {'remaining': []}, format='json')
            self.assertEqual(c.status_code, 200, c.data)
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_node_without_open_session_is_never_blocked(self):
        self._rotation()
        with _now(12, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_correction_of_current_day_remains_allowed(self):
        self._rotation()
        self._open_previous_day()
        DailyTeamAssignment.objects.create(node=self.node, work_date=J1, team='A')
        with _now(12, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['team'], 'B')

    def test_same_day_session_does_not_block_assignment(self):
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            self._produce(self.bp500, 10)
            self._assign('B')  # même journée : correction
            self.assertEqual(DailyTeamAssignment.objects.get(node=self.node, work_date=J).team, 'B')

    def test_without_rotation_unchanged(self):
        ProductionSession.objects.create(
            node=self.node, team='A', date=date(2026, 11, 10), declared_by=self.gerant, node_origin='K1')
        with _now(12, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertNotEqual(r.data.get('code'), 'PREVIOUS_WORKDAY_OPEN')
