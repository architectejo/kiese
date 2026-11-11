"""
BUG-155 (remarque.md l.414, décisions client actées dans
docs/qa/REGISTRE_BUGS.md) : détection — puis, le cas échéant, clôture
forcée automatique — du dépassement de l'heure de fin de créneau d'une
équipe (`Node.team_a_end_time`) sans clôture manuelle de sa
`ProductionSession` du jour.

`GET /api/production/sessions/shift-end-status/?node=<code>` :
  - heure de fin pas encore atteinte, ou session déjà close, ou absente →
    `{"pending_validation": false}` (pas d'action).
  - heure de fin dépassée de moins de `SHIFT_END_GRACE_MINUTES` (30 min),
    session existante non close → `pending_validation=true`, PAS de
    clôture, `remaining` pré-rempli depuis `BreadStock.qty_available`.
  - heure de fin dépassée de 30 min ou plus, session toujours non close →
    clôture forcée automatique (même logique que `close()`, via
    `_close_production_session`), `auto_closed=true`.

Ne duplique jamais la logique de clôture déjà vérifiée sous BUG-093/
BUG-152 (`ProductionSessionViewSet.close()`) : passe par la même fonction
interne `_close_production_session`.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import ProductionSession, BreadDisposal

SESSION_DATE = date(2026, 10, 10)
END_TIME = time(13, 0)


def _aware(hour, minute):
    return timezone.make_aware(
        datetime(SESSION_DATE.year, SESSION_DATE.month, SESSION_DATE.day, hour, minute),
        timezone.get_current_timezone(),
    )


class ShiftEndStatusTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.node.team_a_end_time = END_TIME
        # BUG-155 : l'équipe B n'a volontairement aucun créneau déclaré
        # dans ces tests, pour isoler le comportement de l'équipe A sans
        # qu'une boucle sur B n'interfère avec les assertions.
        self.node.save(update_fields=['team_a_end_time'])

        self.user = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)

        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def _declare(self, qty=200, team='A'):
        resp = self.client_api.post('/api/production/sessions/', {
            'team': team, 'date': SESSION_DATE.isoformat(), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def _status(self, mocked_now):
        with patch('django.utils.timezone.now', return_value=mocked_now):
            return self.client_api.get(
                '/api/production/sessions/shift-end-status/', {'node': self.node.code},
            )

    def test_less_than_grace_period_pending_validation_no_closure(self):
        """
        13h00 + 20 min (< 30 min de grâce) : la session n'est pas close,
        `pending_validation=true`, aucune clôture n'a lieu.
        """
        session_data = self._declare(qty=200)

        resp = self._status(_aware(13, 20))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['team'], 'A')
        self.assertEqual(str(resp.data['session']), str(session_data['id']))
        self.assertTrue(resp.data['pending_validation'])
        self.assertFalse(resp.data['auto_closed'])
        self.assertEqual(
            resp.data['remaining'],
            [{'bread_price': self.bp.pk, 'label': str(self.bp), 'quantity_suggested': 200}],
        )

        session = ProductionSession.objects.get(pk=session_data['id'])
        self.assertFalse(session.is_closed)
        self.assertEqual(BreadDisposal.objects.filter(session=session).count(), 0)

    def test_more_than_grace_period_triggers_automatic_closure(self):
        """
        13h00 + 35 min (>= 30 min de grâce) : clôture forcée automatique,
        avec le reste physique courant (`BreadStock.qty_available` = 200,
        rien vendu ni disposé) comme `BreadDisposal` REMAINING.
        """
        session_data = self._declare(qty=200)

        resp = self._status(_aware(13, 35))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data, {'pending_validation': False, 'auto_closed': True, 'team': 'A'})

        session = ProductionSession.objects.get(pk=session_data['id'])
        self.assertTrue(session.is_closed)
        self.assertIsNotNone(session.closed_at)
        self.assertEqual(session.closure_summary['production_declared']['breads'], 200)
        self.assertEqual(session.closure_summary['gap']['breads'], 200)

        remaining = BreadDisposal.objects.filter(
            session=session, disposal_type=BreadDisposal.DisposalType.REMAINING,
        )
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().quantity, 200)

    def test_exactly_at_grace_boundary_triggers_closure(self):
        """Limite : exactement 30 minutes de dépassement déclenche la clôture (>=)."""
        session_data = self._declare(qty=100)

        resp = self._status(_aware(13, 30))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['auto_closed'])

        session = ProductionSession.objects.get(pk=session_data['id'])
        self.assertTrue(session.is_closed)

    def test_already_closed_session_is_left_untouched(self):
        """
        Session déjà close manuellement avant la fin de créneau : aucune
        action, même largement après l'heure de fin de créneau.
        """
        session_data = self._declare(qty=200)
        close_resp = self.client_api.post(f'/api/production/sessions/{session_data["id"]}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)
        closed_at_before = ProductionSession.objects.get(pk=session_data['id']).closed_at

        resp = self._status(_aware(14, 0))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data, {'pending_validation': False})

        session = ProductionSession.objects.get(pk=session_data['id'])
        self.assertEqual(session.closed_at, closed_at_before)

    def test_no_session_for_team_and_day_reports_nothing_pending(self):
        """Aucune fournée déclarée pour l'équipe A ce jour : rien à clôturer."""
        resp = self._status(_aware(14, 0))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data, {'pending_validation': False})

    def test_end_time_not_yet_reached_reports_nothing_pending(self):
        """Avant l'heure de fin de créneau : aucune action, même session ouverte."""
        self._declare(qty=200)

        resp = self._status(_aware(12, 59))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data, {'pending_validation': False})

    def test_voluntary_close_still_works_identically_bug152_non_regression(self):
        """
        Non-régression BUG-093/BUG-152 : l'appel volontaire à `close()`
        (hors toute logique de fin de créneau) reste rigoureusement
        inchangé — y compris la déclaration du reste du jour en même temps
        que la clôture via `remaining` dans le corps de la requête.
        """
        session_data = self._declare(qty=200)

        close_resp = self.client_api.post(
            f'/api/production/sessions/{session_data["id"]}/close/',
            {'remaining': [{'bread_price': self.bp.pk, 'quantity': 42}]},
            format='json',
        )
        self.assertEqual(close_resp.status_code, 200, close_resp.data)
        self.assertTrue(close_resp.data['is_closed'])

        session = ProductionSession.objects.get(pk=session_data['id'])
        remaining = BreadDisposal.objects.filter(
            session=session, disposal_type=BreadDisposal.DisposalType.REMAINING,
        )
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().quantity, 42)

        # Rejouer l'appel « fin de créneau » largement après l'heure de fin
        # ne doit jamais toucher à cette session déjà close manuellement.
        resp = self._status(_aware(14, 0))
        self.assertEqual(resp.data, {'pending_validation': False})
        remaining_after = BreadDisposal.objects.filter(
            session=session, disposal_type=BreadDisposal.DisposalType.REMAINING,
        )
        self.assertEqual(remaining_after.count(), 1)
        self.assertEqual(remaining_after.first().quantity, 42)
