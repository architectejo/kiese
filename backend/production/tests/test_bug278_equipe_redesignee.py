"""
BUG-278 (dev-backend, 2026-11-12) : la MÊME équipe redésignée pour la période
suivante peut déclarer une fournée et confirmer son stock de départ le même
jour calendaire (réouverture contrôlée de la session close, sans second
rapport ni double comptage du reste). Couvre aussi la valeur théorique /
manquant / excédent et les ventes consolidées pour deux équipes un même jour.
Données fictives uniquement.
"""
from datetime import date, datetime, time
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import ActivityLog
from core.testing import make_bread_price, make_node, make_user
from production.models import (
    BreadDisposal, DailyBreadStockSnapshot, ProductionSession,
)

J = date(2026, 11, 12)
J1 = date(2026, 11, 13)
ASSIGN = '/api/production/team-assignment/'
SESSIONS = '/api/production/sessions/'
SHIFT = '/api/production/sessions/shift-end-status/'
OPENING = '/api/production/opening-confirmation/'


def _now(h, m=0, d=J):
    aware = timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())
    return patch('django.utils.timezone.now', return_value=aware.astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K2', sac_value_fc=Decimal('200000'))
        self.node.team_rotation_enabled = True
        self.node.handover_time = time(12, 0)
        self.node.save()
        self.bp = make_bread_price('B278_500', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.g = APIClient()
        self.g.force_authenticate(self.gerant)

    def _assign(self, team):
        r = self.g.post(ASSIGN, {'team': team}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)

    def _produce(self, team='A', qty=10, sacks='1.00'):
        return self.g.post(SESSIONS, {
            'team': team, 'flour_sacks_used': sacks,
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }, format='json')

    def _a_continues_then_handover(self):
        """A produit le jour J, poursuit après minuit (J+1), est clôturée à la relève de J+1."""
        with _now(13, 0):
            self._assign('A')
            self.assertEqual(self._produce('A').status_code, 201)
        with _now(0, 10, d=J1):
            self.assertTrue(self.g.get(SHIFT).data['auto_closed'])
        with _now(12, 40, d=J1):
            self.assertTrue(self.g.get(SHIFT).data['auto_closed'])


class RedesignatedSameTeamTests(_Base):
    def test_declare_after_redesignation_reopens_single_session(self):
        self._a_continues_then_handover()
        closed = ProductionSession.objects.get(node=self.node, team='A', date=J1)
        self.assertTrue(closed.is_closed)
        with _now(12, 45, d=J1):
            self._assign('A')
            r = self._produce('A', 20)
            self.assertEqual(r.status_code, 201, r.data)
            # une seule session A pour J+1, rouverte, avec la nouvelle fournée
            sessions = ProductionSession.objects.filter(node=self.node, team='A', date=J1)
            self.assertEqual(sessions.count(), 1)
            s = sessions.get()
            self.assertFalse(s.is_closed)
            self.assertIsNone(s.closed_at)
            self.assertEqual(s.total_breads, 20)
            # pas de reste « fantôme » de l'ancienne clôture dans la session
            self.assertFalse(BreadDisposal.objects.filter(
                session=s, disposal_type=BreadDisposal.DisposalType.REMAINING).exists())
            # la session rouverte n'est pas immédiatement re-clôturée par la détection de relève
            self.assertFalse(self.g.get(SHIFT).data.get('auto_closed', False))
            s.refresh_from_db()
            self.assertFalse(s.is_closed)
        self.assertTrue(ActivityLog.objects.filter(action="Réouverture Production").exists())

    def test_opening_confirmation_after_redesignation(self):
        self._a_continues_then_handover()
        with _now(12, 45, d=J1):
            self._assign('A')
            r = self.g.post(OPENING, {'lines': [{'bread_price': self.bp.pk, 'qty': 7}]}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            s = ProductionSession.objects.get(node=self.node, team='A', date=J1)
            self.assertFalse(s.is_closed)
            self.assertEqual(ProductionSession.objects.filter(node=self.node, date=J1).count(), 1)

    def test_reclose_overwrites_snapshot_not_double_counted(self):
        self._a_continues_then_handover()
        before = DailyBreadStockSnapshot.objects.filter(node=self.node, date=J1, team='A').count()
        with _now(12, 45, d=J1):
            self._assign('A')
            self.assertEqual(self._produce('A', 20).status_code, 201)
            sid = ProductionSession.objects.get(node=self.node, team='A', date=J1).pk
            r = self.g.post(f'{SESSIONS}{sid}/close/', {'remaining': [{'bread_price': self.bp.pk, 'quantity': 5}]}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
        snaps = DailyBreadStockSnapshot.objects.filter(node=self.node, date=J1, team='A', bread_price=self.bp)
        self.assertEqual(snaps.count(), 1)
        self.assertEqual(snaps.get().qty_at_close, 5)
        self.assertLessEqual(before, 1)
        rem = BreadDisposal.objects.filter(
            session_id=sid, bread_price=self.bp, disposal_type=BreadDisposal.DisposalType.REMAINING)
        self.assertEqual(rem.count(), 1)
        self.assertEqual(rem.get().quantity, 5)

    def test_voluntary_close_in_current_period_still_refused(self):
        """BUG-093 intact : clôture volontaire DANS la période en cours = pas de réouverture."""
        with _now(13, 0):
            self._assign('A')
            self.assertEqual(self._produce('A').status_code, 201)
            sid = ProductionSession.objects.get(node=self.node, team='A', date=J).pk
            self.assertEqual(self.g.post(f'{SESSIONS}{sid}/close/').status_code, 200)
            r = self._produce('A', 5)
            self.assertEqual(r.status_code, 400)
            self.assertIn('clôturée', str(r.data))

    def test_other_team_cannot_reopen(self):
        self._a_continues_then_handover()
        with _now(12, 45, d=J1):
            self._assign('B')
            r = self._produce('A', 5)
            self.assertEqual(r.status_code, 400)
            s = ProductionSession.objects.get(node=self.node, team='A', date=J1)
            self.assertTrue(s.is_closed)


class TwoTeamsSameDayConsolidatedTests(_Base):
    def test_theoretical_manquant_excedent_and_consolidated_report(self):
        # Équipe A : 1 sac (200 000) -> 300 pains de 500 = 150 000 : manquant 50 000.
        with _now(9, 0):
            self._assign('A')
            self.assertEqual(self._produce('A', 300).status_code, 201)
        # Équipe B après la relève : 1 sac -> 500 pains = 250 000 : excédent 50 000.
        with _now(12, 40):
            self.assertTrue(self.g.get(SHIFT).data['auto_closed'])
            self._assign('B')
            self.assertEqual(self._produce('B', 500).status_code, 201)
        a = ProductionSession.objects.get(node=self.node, team='A', date=J)
        b = ProductionSession.objects.get(node=self.node, team='B', date=J)
        self.assertEqual((a.theoretical_yield, a.total_fc_produced, a.yield_gap), (200000, 150000, -50000))
        self.assertEqual((b.theoretical_yield, b.total_fc_produced, b.yield_gap), (200000, 250000, 50000))
        with _now(13, 0):
            r = self.g.get('/api/production/daily-closure/', {'date': str(J)})
            self.assertEqual(r.status_code, 200, r.data)
            cat = {c['bread_price']: c for c in r.data['categories']}[self.bp.pk]
            # un seul rapport consolidé : somme des deux équipes (pas de doublon)
            self.assertEqual(cat['produit']['quantity'], 800)
            self.assertEqual(ProductionSession.objects.filter(node=self.node, date=J).count(), 2)
