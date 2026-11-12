"""
Vague 4 (base réelle K2) — testeur-production, 2026-11-12 : vérification de BUG-271/272
(jour calendaire). Tests indépendants de ceux du développeur. Les `@expectedFailure`
portent la référence du ticket du registre (docs/qa/REGISTRE_BUGS.md) ; les retirer
une fois le ticket corrigé. Aucun code applicatif n'est modifié.
"""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_node, make_user
from production.models import DailyTeamAssignment, ProductionSession

J = date(2026, 11, 12)
J1 = date(2026, 11, 13)
ASSIGN = '/api/production/team-assignment/'
SESSIONS = '/api/production/sessions/'
SHIFT = '/api/production/sessions/shift-end-status/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=J):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K2', sac_value_fc=Decimal('200000'))
        self.node.team_rotation_enabled = True
        self.node.handover_time = time(12, 0)
        self.node.save()
        self.bp = make_bread_price('V4_500', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.g = APIClient()
        self.g.force_authenticate(self.gerant)

    def _assign(self, team):
        r = self.g.post(ASSIGN, {'team': team}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)

    def _produce(self, team='A', qty=10):
        return self.g.post(SESSIONS, {
            'team': team, 'flour_sacks_used': '1.00', 'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }, format='json')


class SameTeamTwoConsecutivePeriodsTests(_Base):
    def test_bug278_same_team_designated_again_can_declare_after_handover(self):
        """
        BUG-278 : la session d'une équipe est unique par (équipe, jour calendaire). L'équipe A
        qui poursuit après minuit (session J+1 ouverte automatiquement) est clôturée à la
        relève de J+1 ; si elle est de nouveau désignée pour la période suivante (désignation
        manuelle autorisée), elle ne peut plus déclarer aucune fournée de l'après-midi :
        400 « Session de production clôturée pour l'équipe A le J+1 ».
        """
        with _now(13, 0):
            self._assign('A')
            self.assertEqual(self._produce('A').status_code, 201)
        with _now(0, 10, d=J1):  # passage de minuit : J clôturée, session J+1 ouverte pour A
            r = self.g.get(SHIFT)
            self.assertTrue(r.data['auto_closed'])
        self.assertTrue(ProductionSession.objects.filter(node=self.node, team='A', date=J1, is_closed=False).exists())
        with _now(12, 40, d=J1):  # relève passée de 40 min : clôture forcée de la session de A
            r = self.g.get(SHIFT)
            self.assertTrue(r.data['auto_closed'])
            self._assign('A')  # A est de nouveau désignée
            r = self._produce('A', 20)
        self.assertEqual(r.status_code, 201, r.data)
