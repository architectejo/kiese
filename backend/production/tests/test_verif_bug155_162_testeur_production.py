"""
Vérification indépendante (testeur-production, 2026-11-11) du lot BUG-155 /
BUG-158 / BUG-162 (reste de pain NÉGATIF enregistré tel quel).

Angles couverts (indépendants des suites des développeurs) :
  1. Chaîne de bout en bout d'un reste négatif : produire 50, sortir 70
     (DECLASSED) -> clôture automatique -> REMAINING = -20 -> snapshot ->
     rapport de Clôture Journalière -> stock de départ du lendemain pour
     l'autre équipe (opening-confirmation) avec une valeur négative ;
     la clôture de la veille ne bouge JAMAIS après confirmation du départ.
  2. Contrainte BUG-158 : négatif refusé hors REMAINING (serializer + base,
     y compris `QuerySet.update()` qui contourne `save()`), totaux de valeur
     et de pertes non faussés par un REMAINING négatif.
  3. Idempotence / atomicité de `shift_end_status` : un second appel, ou un
     appel « concurrent » (entrelacement simulé), ne crée ni deux clôtures
     ni deux notifications ; isolation par nœud.
Données entièrement fictives (`core.testing`).
"""
import unittest
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadDisposal, BreadStock, DailyBreadStockSnapshot,
    DailyOpeningConfirmationLine, ProductionSession, ProductionSessionLine,
)
from production.views import _build_daily_closure_report

DAY = date(2026, 10, 12)
NEXT_DAY = DAY + timedelta(days=1)
STATUS_URL = '/api/production/sessions/shift-end-status/'
OPENING_URL = '/api/production/opening-confirmation/'


def _aware(d, hour, minute):
    return timezone.make_aware(
        datetime(d.year, d.month, d.day, hour, minute), timezone.get_current_timezone(),
    )


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.node.team_a_end_time = time(13, 0)
        self.node.save(update_fields=['team_a_end_time'])
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC TV1', unit_price=500)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

        resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': DAY.isoformat(), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 50}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.session_id = resp.data['id']

    def _declass(self, qty, dtype='DECLASSED'):
        return self.api.post('/api/production/disposals/', {
            'session': self.session_id, 'bread_price': self.bp.pk,
            'disposal_type': dtype, 'quantity': qty,
        }, format='json')

    def _auto_close(self, api=None, at=(13, 40)):
        with patch('django.utils.timezone.now', return_value=_aware(DAY, *at)):
            return (api or self.api).get(STATUS_URL, {'node': self.node.code})


class NegativeRemainingEndToEndTests(_Base):
    def setUp(self):
        super().setUp()
        self.assertEqual(self._declass(70).status_code, 201)
        resp = self._auto_close()
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['auto_closed'])

    def _snapshot(self):
        return list(DailyBreadStockSnapshot.objects.values_list('date', 'team', 'bread_price', 'qty_at_close'))

    def _row(self, d):
        report = _build_daily_closure_report(self.node, d)
        return next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)

    def test_remaining_snapshot_and_report_for_the_day(self):
        rem = BreadDisposal.objects.get(session_id=self.session_id, disposal_type='REMAINING')
        self.assertEqual(rem.quantity, -20)
        self.assertEqual(rem.total_value, 0)  # quantity * unit_price_sold(0)
        self.assertEqual(self._snapshot(), [(DAY, 'A', self.bp.pk, -20)])
        row = self._row(DAY)
        self.assertEqual(row['reste_du_jour']['A'], -20)
        self.assertIsNone(row['reste_du_jour']['B'])
        self.assertEqual(row['reste_du_hier']['A'], 0)
        # la production du jour reste 50 (reste négatif jamais compté comme production)
        self.assertEqual(row['produit']['quantity'], 50)
        # la déclassification de 70 est dans la rubrique « déclassés », pas dans REMAINING
        self.assertEqual(row['declasses']['quantity'], 70)
        self.assertEqual(row['non_vendu_nv']['quantity'], 0)
        # reste_du_jour_fc = -20 * 500 intervient dans la FACTURE MVM INTERNE
        self.assertEqual(Decimal(row['facture_mvm_interne']['fc']), Decimal('-10000.00'))

    def test_one_negative_notification_and_stock_untouched(self):
        notes = SystemNotification.objects.filter(title__startswith='Stock de pain négatif')
        self.assertEqual(notes.count(), 1)
        self.assertEqual(notes.first().severity, 'WARNING')
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, -20)
        self.assertEqual(stock.qty_adjusted, 0)

    def test_opening_confirmation_next_day_other_team_keeps_yesterday_frozen(self):
        snap_before = self._snapshot()
        rem_before = list(BreadDisposal.objects.filter(session_id=self.session_id)
                          .values_list('id', 'disposal_type', 'quantity'))
        row_before = self._row(DAY)
        session_before = ProductionSession.objects.get(pk=self.session_id)

        # Stock de départ de B le lendemain : on confirme la valeur négative proposée (-20).
        get = self.api.get(OPENING_URL, {'date': NEXT_DAY.isoformat()})
        self.assertEqual(get.status_code, 200)
        proposed = next(c for c in get.data['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(proposed['qty_proposed'], -20)

        resp = self.api.post(OPENING_URL, {
            'team': 'B', 'date': NEXT_DAY.isoformat(),
            'lines': [{'bread_price': self.bp.pk, 'qty': proposed['qty_proposed']}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        line = DailyOpeningConfirmationLine.objects.get(bread_price=self.bp)
        self.assertEqual(line.qty_confirmed, -20)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_adjusted, 0)      # validé tel que proposé : delta nul
        self.assertEqual(stock.qty_available, -20)

        # Correction du gérant : -25 -> delta -5, puis resoumission idempotente.
        for _ in range(2):
            resp = self.api.post(OPENING_URL, {
                'team': 'B', 'date': NEXT_DAY.isoformat(),
                'lines': [{'bread_price': self.bp.pk, 'qty': -25}],
            }, format='json')
            self.assertEqual(resp.status_code, 200, resp.data)
        stock.refresh_from_db()
        self.assertEqual(stock.qty_adjusted, -5)
        self.assertEqual(stock.qty_available, -25)

        # Aucune ligne de fournée CARRYOVER négative (ni positive) pour B.
        self.assertFalse(ProductionSessionLine.objects.filter(
            source=ProductionSessionLine.Source.CARRYOVER, quantity__lte=0).exists())
        self.assertFalse(ProductionSessionLine.objects.filter(
            session__team='B', bread_price=self.bp,
            source=ProductionSessionLine.Source.CARRYOVER).exists())

        # La clôture de la veille est INCHANGÉE (snapshot, REMAINING, session, rapport).
        self.assertEqual(self._snapshot(), snap_before)
        self.assertEqual(
            list(BreadDisposal.objects.filter(session_id=self.session_id)
                 .values_list('id', 'disposal_type', 'quantity')), rem_before)
        session_after = ProductionSession.objects.get(pk=self.session_id)
        self.assertTrue(session_after.is_closed)
        self.assertEqual(session_after.closed_at, session_before.closed_at)
        self.assertEqual(session_after.closure_summary, session_before.closure_summary)
        self.assertEqual(self._row(DAY), row_before)

        # Rapport du lendemain : reste_du_hier de B = -(-25) = +25 (convention BUG-135),
        # sans cumul à la resoumission.
        row_next = self._row(NEXT_DAY)
        self.assertEqual(row_next['reste_du_hier']['B'], 25)

    def test_second_manual_close_is_refused_and_does_not_alter_remaining(self):
        resp = self.api.post(f'/api/production/sessions/{self.session_id}/close/',
                             {'remaining': [{'bread_price': self.bp.pk, 'quantity': 0}]}, format='json')
        self.assertGreaterEqual(resp.status_code, 400)
        rem = BreadDisposal.objects.get(session_id=self.session_id, disposal_type='REMAINING')
        self.assertEqual(rem.quantity, -20)


class NegativeConstraintTests(_Base):
    def test_serializer_refuses_negative_for_all_non_remaining_types(self):
        for dtype in ('UNSOLD', 'DECLASSED', 'FREE_DIST', 'SOLD_DISCOUNT'):
            resp = self._declass(-3, dtype)
            self.assertEqual(resp.status_code, 400, (dtype, resp.data))
        self.assertEqual(BreadDisposal.objects.count(), 0)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, 50)

    def test_serializer_accepts_negative_remaining_but_not_retyping_or_patching(self):
        resp = self._declass(-4, 'REMAINING')
        self.assertEqual(resp.status_code, 201, resp.data)
        did = resp.data['id']
        # re-typage d'un REMAINING négatif vers UNSOLD
        r = self.api.patch(f'/api/production/disposals/{did}/', {'disposal_type': 'UNSOLD'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        # PATCH quantité négative sur un UNSOLD positif
        ok = self._declass(5, 'UNSOLD')
        self.assertEqual(ok.status_code, 201)
        r = self.api.patch(f'/api/production/disposals/{ok.data["id"]}/', {'quantity': -1}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        r = self.api.put(f'/api/production/disposals/{ok.data["id"]}/', {
            'session': self.session_id, 'bread_price': self.bp.pk,
            'disposal_type': 'UNSOLD', 'quantity': -1}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        # REMAINING négatif ne modifie pas le stock physique
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_disposed, 5)

    def test_database_refuses_negative_non_remaining_even_via_orm_update(self):
        base = dict(node=self.node, session_id=self.session_id, bread_price=self.bp)
        for dtype in ('UNSOLD', 'DECLASSED', 'FREE_DIST', 'SOLD_DISCOUNT'):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    BreadDisposal.objects.create(disposal_type=dtype, quantity=-1, **base)
        # bulk_create contourne save()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BreadDisposal.objects.bulk_create(
                    [BreadDisposal(disposal_type='UNSOLD', quantity=-1, **base)])
        # update() d'un REMAINING négatif vers un autre type
        rem = BreadDisposal.objects.create(disposal_type='REMAINING', quantity=-9, **base)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BreadDisposal.objects.filter(pk=rem.pk).update(disposal_type='UNSOLD')
        # REMAINING négatif lui-même : autorisé
        rem.refresh_from_db()
        self.assertEqual(rem.quantity, -9)

    def test_negative_remaining_does_not_distort_reconciliation_or_loss_totals(self):
        self.assertEqual(self._declass(10, 'UNSOLD').status_code, 201)
        # ajoute un REMAINING négatif sur la même session
        self.assertEqual(self._declass(-30, 'REMAINING').status_code, 201)
        # rapport du jour : rubriques de pertes (NV, déclassés, gratuites) intactes
        report = _build_daily_closure_report(self.node, DAY)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(row['non_vendu_nv']['quantity'], 10)
        self.assertEqual(row['declasses']['quantity'], 0)
        self.assertEqual(row['sorties_gratuites']['quantity'], 0)
        # réconciliation (endpoint) : REMAINING exclu des retours
        resp = self.api.get('/api/production/sessions/reconciliation/',
                            {'node': self.node.code, 'date': DAY.isoformat()})
        if resp.status_code == 200:
            self.assertEqual(resp.data['returns']['breads'], 10)
        # stock inchangé par le REMAINING
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, 40)

    def test_readers_do_not_crash_with_negative_remaining(self):
        self.assertEqual(self._declass(-30, 'REMAINING').status_code, 201)
        for url in (
            '/api/production/disposals/', '/api/production/sessions/',
            '/api/production/bread-stocks/',
            f'/api/production/bread-stocks/by-date/?node={self.node.code}&date={DAY.isoformat()}',
            f'/api/production/daily-closure/?node={self.node.code}&date={DAY.isoformat()}',
        ):
            resp = self.api.get(url)
            self.assertLess(resp.status_code, 500, (url, resp.status_code))


class ShiftEndIdempotenceTests(_Base):
    def setUp(self):
        super().setUp()
        self.assertEqual(self._declass(70).status_code, 201)

    def test_consecutive_calls_create_one_closure_and_one_notification(self):
        first = self._auto_close()
        second = self._auto_close()
        third = self._auto_close(at=(14, 5))
        self.assertTrue(first.data['auto_closed'])
        self.assertEqual(second.data, {'pending_validation': False})
        self.assertEqual(third.data, {'pending_validation': False})
        self.assertEqual(SystemNotification.objects.filter(title__startswith='Stock de pain négatif').count(), 1)
        self.assertEqual(BreadDisposal.objects.filter(
            session_id=self.session_id, disposal_type='REMAINING').count(), 1)
        self.assertEqual(DailyBreadStockSnapshot.objects.count(), 1)

    def test_other_node_user_never_closes_this_node(self):
        other = make_node(sac_value_fc=Decimal('100000'))
        intruder = make_user(role='FACTURIER', node=other)
        c = APIClient()
        c.force_authenticate(intruder)
        resp = self._auto_close(api=c)
        self.assertEqual(resp.data, {'pending_validation': False})
        self.assertFalse(ProductionSession.objects.get(pk=self.session_id).is_closed)

    def test_interleaved_requests_create_a_single_notification_BUG_165(self):
        """
        BUG-165 : `shift_end_status` lit `session.is_closed` sans verrou
        (`select_for_update`, CLAUDE.md §4) et `_close_production_session` ne
        revérifie pas l'état dans sa transaction. Entrelacement simulé : la
        requête 2 s'exécute entièrement pendant que la requête 1 a déjà lu la
        session « non close » -> deux clôtures, deux notifications.
        """
        import production.views as v
        real = v._current_bread_stocks
        state = {'depth': 0}

        def interleaved(node):
            result = real(node)
            if state['depth'] == 0:
                state['depth'] = 1
                inner = self._auto_close()  # requête 2, complète
                self.assertTrue(inner.data.get('auto_closed'))
            return result

        with patch.object(v, '_current_bread_stocks', side_effect=interleaved):
            self._auto_close()
        self.assertEqual(
            SystemNotification.objects.filter(title__startswith='Stock de pain négatif').count(), 1)
