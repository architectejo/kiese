"""
BUG-350 (lot L1, volet tests) : boîte « Stock de départ » autour de l'heure de
relève (`Node.handover_time`, 12:00 par défaut), horloge simulée.

Tout le fichier travaille sur des boulangeries créées dans le test ;
`team_rotation_enabled` n'est JAMAIS activé ailleurs (aucune configuration de
production modifiée, Q-017 en attente). Horloge : `mock.patch` de
`django.utils.timezone.now` (freezegun n'est pas installé).

Couvre : avant la relève, à l'heure, +30 min, le lendemain, minuit ; l'ordre
reste du jour -> équipe entrante désignée -> stock de départ ; une seule
équipe concernée par période ; comportement hors rotation caractérisé ; rôles
et isolation des nœuds.
"""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_node, make_user
from production.models import (
    BreadStock, DailyOpeningConfirmation, DailyTeamAssignment, ProductionSession,
)

D = date(2026, 11, 12)          # jour de référence (jeudi)
PREV = D - timedelta(days=1)
NEXT = D + timedelta(days=1)
OPENING = '/api/production/opening-confirmation/'
ASSIGN = '/api/production/team-assignment/'
SESSIONS = '/api/production/sessions/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.node.team_rotation_enabled = True   # boulangerie de test uniquement
        self.node.save()
        self.assertEqual(self.node.handover_time, time(12, 0))
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _assign(self, d, team, node=None):
        DailyTeamAssignment.objects.create(node=node or self.node, work_date=d, team=team)

    def _post(self, qty=10, api=None, **extra):
        payload = {'lines': [{'bread_price': self.bp.pk, 'qty': qty}]}
        payload.update(extra)
        return (api or self.api).post(OPENING, payload, format='json')

    def _get(self, api=None, **params):
        return (api or self.api).get(OPENING, params)

    def _needs(self):
        r = self._get()
        self.assertEqual(r.status_code, 200, r.data)
        return r.data['needs_confirmation']


class HandoverClockTests(_Base):
    """Rotation active : une confirmation par période de service, relève 12:00."""

    def test_before_handover_without_assignment_no_box(self):
        with _now(11, 59):
            r = self._get()
        self.assertTrue(r.data['rotation'])
        self.assertTrue(r.data['team_assignment_required'])
        self.assertFalse(r.data['needs_confirmation'])

    def test_before_handover_previous_period_team_still_owes_confirmation(self):
        # 11:59 : encore la période démarrée la veille (équipe A, non confirmée).
        self._assign(PREV, 'A')
        self._assign(D, 'B')                      # désignation déjà posée pour midi
        with _now(11, 59):
            r = self._get()
        self.assertEqual(r.data['team'], 'A')
        self.assertTrue(r.data['needs_confirmation'])
        self.assertEqual(r.data['date'], '2026-11-11')  # BUG-1130 : journée comptable (midi à midi)

    def test_before_handover_previous_period_confirmed_no_box(self):
        self._assign(PREV, 'A')
        self._assign(D, 'B')
        with _now(9, 0):
            self.assertEqual(self._post(team='A').status_code, 200)
        with _now(11, 59):
            self.assertFalse(self._needs())

    def test_at_handover_incoming_team_must_confirm(self):
        self._assign(PREV, 'A')
        self._assign(D, 'B')
        with _now(9, 0):
            self.assertEqual(self._post().status_code, 200)
        with _now(12, 0):
            r = self._get()
        self.assertEqual(r.data['team'], 'B')
        self.assertEqual(r.data['opening_team'], 'B')
        self.assertTrue(r.data['needs_confirmation'])
        self.assertFalse(r.data['teams']['A']['confirmed'])   # la confirmation de 09:00 est d'une période révolue

    def test_thirty_minutes_after_handover_still_needed_until_posted(self):
        self._assign(PREV, 'A')
        self._assign(D, 'B')
        with _now(9, 0):
            self._post()
        with _now(12, 30):
            self.assertTrue(self._needs())
            r = self._post(qty=4)
            self.assertEqual(r.status_code, 200, r.data)
            self.assertFalse(self._needs())
        conf = DailyOpeningConfirmation.objects.get(node=self.node, team='B', date=D)
        self.assertEqual(conf.confirmed_by, self.gerant)
        self.assertEqual(conf.lines.get().qty_confirmed, 4)

    def test_box_stays_closed_until_next_handover_then_reopens(self):
        self._assign(D, 'A')
        self._assign(NEXT, 'B')
        with _now(12, 10):
            self.assertEqual(self._post().status_code, 200)
        with _now(18, 0):
            self.assertFalse(self._needs())
        with _now(11, 59, d=NEXT):
            self.assertFalse(self._needs())          # encore la période du 12
        with _now(12, 0, d=NEXT):
            r = self._get()
            self.assertTrue(r.data['needs_confirmation'])
            self.assertEqual(r.data['team'], 'B')
            self.assertEqual(r.data['date'], '2026-11-13')

    def test_midnight_crossing_neither_reopens_nor_blocks(self):
        self._assign(D, 'A')
        with _now(13, 0):
            self.assertEqual(self._post().status_code, 200)
        with _now(23, 59):
            self.assertFalse(self._needs())
        with _now(0, 0, d=NEXT):
            r = self._get()
        self.assertEqual(r.data['date'], '2026-11-12')       # BUG-1130 : minuit ne change pas la journée...
        self.assertEqual(r.data['team'], 'A')                # ...ni l'équipe
        self.assertFalse(r.data['needs_confirmation'])       # ...ni la confirmation

    def test_midnight_unconfirmed_period_still_pending_after_midnight(self):
        self._assign(D, 'A')
        with _now(23, 59):
            self.assertTrue(self._needs())
        with _now(0, 5, d=NEXT):
            self.assertTrue(self._needs())
            # BUG-1130 : la confirmation d'après minuit reste datée de la journée comptable en cours (D).
            self.assertEqual(self._post().status_code, 200)
            self.assertFalse(self._needs())
        self.assertTrue(DailyOpeningConfirmation.objects.filter(node=self.node, team='A', date=D).exists())

    def test_same_team_redesignated_on_consecutive_periods_same_calendar_day(self):
        # Période PREV (B) confirmée le matin de D (clé [B, D]) ; à 12:00 la
        # même équipe B est de nouveau désignée : la boîte doit rouvrir et la
        # nouvelle confirmation (même clé node/équipe/date) doit la refermer.
        self._assign(PREV, 'B')
        self._assign(D, 'B')
        with _now(9, 0):
            self.assertEqual(self._post(qty=3).status_code, 200)
        with _now(12, 0):
            self.assertTrue(self._needs())
            self.assertEqual(self._post(qty=5).status_code, 200)
            self.assertFalse(self._needs())
        self.assertEqual(DailyOpeningConfirmation.objects.filter(node=self.node, team='B', date=D).count(), 1)

    def test_custom_handover_time_is_honoured(self):
        self.node.handover_time = time(14, 30)
        self.node.save()
        self._assign(PREV, 'A')
        self._assign(D, 'B')
        with _now(9, 0):
            self._post()
        with _now(12, 0):
            self.assertFalse(self._needs())          # 12:00 n'est plus une relève
        with _now(14, 29):
            self.assertFalse(self._needs())
        with _now(14, 30):
            r = self._get()
        self.assertTrue(r.data['needs_confirmation'])
        self.assertEqual(r.data['team'], 'B')


class OrderAtHandoverTests(_Base):
    """Ordre : reste du jour de l'équipe sortante -> désignation entrante -> stock de départ."""

    def _open_previous_period(self):
        self._assign(PREV, 'A')
        with _now(13, 0, d=PREV):
            r = self.api.post(SESSIONS, {
                'flour_sacks_used': '1.00', 'lines': [{'bread_price': self.bp.pk, 'quantity': 20}],
            }, format='json')
            self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def test_order_remaining_then_assignment_then_opening_stock(self):
        sid = self._open_previous_period()
        with _now(12, 0):
            # 1. Pas de désignation, pas de boîte de stock de départ.
            r = self._get()
            self.assertTrue(r.data['team_assignment_required'])
            self.assertFalse(r.data['needs_confirmation'])
            # POST du stock de départ refusé tant qu'aucune équipe n'est désignée.
            p = self._post()
            self.assertEqual(p.status_code, 403, p.data)
            self.assertEqual(p.data['code'], 'TEAM_NOT_ASSIGNED')
            # 2. Désignation refusée tant que le reste du jour sortant n'est pas confirmé.
            a = self.api.post(ASSIGN, {'team': 'B'}, format='json')
            self.assertEqual(a.status_code, 400, a.data)
            self.assertEqual(a.data['code'], 'PREVIOUS_WORKDAY_OPEN')
        with _now(12, 5):
            # Reste du jour déclaré (clôture de la session sortante).
            c = self.api.post(f'{SESSIONS}{sid}/close/', {
                'remaining': [{'bread_price': self.bp.pk, 'quantity': 6}],
            }, format='json')
            self.assertEqual(c.status_code, 200, c.data)
            # Désignation maintenant possible.
            a = self.api.post(ASSIGN, {'team': 'B'}, format='json')
            self.assertEqual(a.status_code, 200, a.data)
            # 3. Boîte « stock de départ » : équipe entrante, proposition = reste déclaré.
            r = self._get()
            self.assertTrue(r.data['needs_confirmation'])
            self.assertEqual(r.data['team'], 'B')
            proposed = {c_['bread_price']: c_['qty_proposed'] for c_ in r.data['categories']}
            self.assertEqual(proposed[self.bp.pk], 6)
            self.assertEqual(self._post(qty=6).status_code, 200)
            self.assertFalse(self._needs())
        self.assertTrue(ProductionSession.objects.get(pk=sid).is_closed)


class OneTeamPerPeriodTests(_Base):
    def test_only_designated_team_is_confirmed(self):
        self._assign(D, 'B')
        with _now(12, 10):
            self.assertEqual(self._post().status_code, 200)
            r = self._get()
        self.assertTrue(r.data['teams']['B']['confirmed'])
        self.assertFalse(r.data['teams']['A']['confirmed'])
        self.assertEqual(DailyOpeningConfirmation.objects.filter(node=self.node).count(), 1)

    def test_other_team_confirmation_is_refused(self):
        self._assign(D, 'B')
        with _now(12, 10):
            r = self._post(team='A')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(DailyOpeningConfirmation.objects.filter(node=self.node).exists())

    def test_resubmission_in_same_period_is_idempotent(self):
        self._assign(D, 'A')
        with _now(12, 10):
            self.assertEqual(self._post(qty=3).status_code, 200)
        with _now(12, 20):
            self.assertEqual(self._post(qty=8).status_code, 200)
        self.assertEqual(DailyOpeningConfirmation.objects.filter(node=self.node).count(), 1)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, 8)

    def test_redesignation_after_confirmation_does_not_ask_again_known_minor(self):
        # Caractérisation (analyse A1 §1 bis point 5, mineur) : la confirmation
        # d'une équipe couvre toute la période ; si le gérant corrige ensuite la
        # désignation (A -> B), l'équipe corrigée n'est pas re-sollicitée.
        self._assign(D, 'A')
        with _now(12, 10):
            self.assertEqual(self._post().status_code, 200)
            self.assertEqual(self.api.post(ASSIGN, {'team': 'B'}, format='json').status_code, 200)
            r = self._get()
        self.assertEqual(r.data['team'], 'B')
        self.assertFalse(r.data['needs_confirmation'])


class WithoutRotationCharacterizationTests(TestCase):
    """Hors rotation : une fois par jour, équipe du premier créneau (inchangé)."""

    def setUp(self):
        self.node = make_node(code='K2')
        self.node.team_a_start_time = time(6, 0)
        self.node.team_a_end_time = time(11, 30)
        self.node.team_b_start_time = time(14, 30)
        self.node.team_b_end_time = time(20, 0)
        self.node.save()
        self.assertFalse(self.node.team_rotation_enabled)
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _get(self):
        return self.api.get(OPENING)

    def _post(self, team, qty=10):
        return self.api.post(OPENING, {'team': team, 'lines': [{'bread_price': self.bp.pk, 'qty': qty}]}, format='json')

    def test_opening_team_is_first_slot_and_box_pending_all_day(self):
        for h, m in ((6, 0), (12, 0), (14, 30), (21, 0)):
            with _now(h, m):
                r = self._get()
                self.assertFalse(r.data.get('rotation', False))
                self.assertEqual(r.data['opening_team'], 'A')
                self.assertTrue(r.data['needs_confirmation'], f'{h}:{m}')

    def test_no_new_box_at_noon_or_second_slot_after_morning_confirmation(self):
        # BUG-1130 : hors rotation aussi, la journée change à 12:00 (heure de clôture, midi à midi) ;
        # une confirmation faite après 12:00 vaut jusqu'à la clôture du lendemain, sans nouvelle boîte.
        with _now(12, 10):
            self.assertEqual(self._post('A').status_code, 200)
        for h, m, d in ((12, 30, D), (14, 30, D), (23, 59, D), (0, 5, NEXT), (11, 59, NEXT)):
            with _now(h, m, d=d):
                self.assertFalse(self._get().data['needs_confirmation'], f'{h}:{m}')
        with _now(12, 0, d=NEXT):
            self.assertTrue(self._get().data['needs_confirmation'])

    def test_second_team_confirmation_does_not_replace_first_slot(self):
        with _now(14, 40):
            self.assertEqual(self._post('B').status_code, 200)
            self.assertTrue(self._get().data['needs_confirmation'])   # A n'a pas confirmé

    def test_new_day_asks_again(self):
        with _now(12, 10):
            self._post('A')
        with _now(12, 10, d=NEXT):  # BUG-1130 : nouvelle journée comptable à 12:00
            self.assertTrue(self._get().data['needs_confirmation'])

    def test_team_is_required_without_rotation(self):
        with _now(7, 0):
            r = self.api.post(OPENING, {'lines': [{'bread_price': self.bp.pk, 'qty': 1}]}, format='json')
        self.assertEqual(r.status_code, 400)


class RolesAndIsolationTests(_Base):
    def setUp(self):
        super().setUp()
        self.other = make_node(code='K2')
        self.other.team_rotation_enabled = True
        self.other.save()
        self._assign(D, 'A')
        self._assign(D, 'B', node=self.other)

    def _api(self, role, node=None):
        api = APIClient()
        api.force_authenticate(make_user(role, node=node))
        return api

    def test_gerant_and_facturier_can_get_and_post(self):
        for role in ('GERANT', 'FACTURIER'):
            api = self._api(role, self.node)
            with _now(12, 5):
                self.assertEqual(self._get(api=api).status_code, 200, role)
                self.assertEqual(self._post(api=api).status_code, 200, role)
                self.assertFalse(self._get(api=api).data['needs_confirmation'], role)

    def test_livreur_same_rights_as_facturier(self):
        # BUG-1050 (decision client Q-027) : le livreur a les memes ecrans et droits que le facturier ;
        # l'ancien test exigeait un 403. Le livreur est maintenant traite exactement comme le facturier.
        livreur = self._api('LIVREUR', self.node)
        facturier = self._api('FACTURIER', self.node)
        with _now(12, 5):
            self.assertEqual(self._get(api=livreur).status_code, self._get(api=facturier).status_code)
            self.assertNotEqual(self._get(api=livreur).status_code, 403)

    def test_headquarters_must_name_the_node(self):
        # Côté API, le siège n'a pas de nœud propre : `node` est obligatoire
        # (la boîte n'est de toute façon pas montée pour ces rôles côté UI).
        for role in ('DIRECTION', 'ADMIN'):
            api = self._api(role)
            with _now(12, 5):
                self.assertEqual(self._get(api=api).status_code, 400, role)
                self.assertEqual(self._get(api=api, node='K1').status_code, 200, role)

    def test_node_param_is_ignored_for_branch_users(self):
        api = self._api('GERANT', self.other)          # gérant de K2
        with _now(12, 5):
            r = self._get(api=api, node='K1')
        self.assertEqual(r.data['node'], 'K2')
        self.assertEqual(r.data['team'], 'B')           # désignation de K2, pas celle de K1

    def test_confirmation_of_one_node_does_not_clear_the_other(self):
        with _now(12, 5):
            self.assertEqual(self._post().status_code, 200)          # K1
            self.assertFalse(self._needs())
            other_api = self._api('GERANT', self.other)
            self.assertTrue(self._get(api=other_api).data['needs_confirmation'])
            # Un gérant K2 qui vise K1 dans le corps confirme K2, jamais K1.
            self.assertEqual(self._post(api=other_api, node='K1').status_code, 200)
        self.assertEqual(DailyOpeningConfirmation.objects.filter(node=self.node).count(), 1)
        self.assertEqual(DailyOpeningConfirmation.objects.filter(node=self.other).count(), 1)

    def test_each_node_has_its_own_handover_hour(self):
        self.other.handover_time = time(18, 0)
        self.other.save()
        other_api = self._api('GERANT', self.other)
        with _now(12, 5):
            self.assertTrue(self._needs())                                       # K1 : relève passée
            # K2 : à 12:05 on est encore dans la période démarrée la veille (non désignée).
            self.assertTrue(self._get(api=other_api).data['team_assignment_required'])
