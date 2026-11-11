"""
BUG-158 : `GET /api/production/sessions/shift-end-status/` (BUG-155) ne doit
plus planter (HTTP 500, `IntegrityError: CHECK constraint failed: quantity`)
quand le stock physique d'une catégorie (`BreadStock.qty_available`) est
négatif.

Règle retenue (instruction directe du client, 2026-11-10, qui remplace la
première décision « ramener à 0 ») : « Enregistre le stock même s'il est
négatif à la clôture automatique ».

  - clôture forcée (dépassement >= 30 min) : la clôture aboutit, la ligne
    `BreadDisposal` REMAINING porte la valeur négative réelle, le snapshot et
    le rapport de clôture la propagent, et une `SystemNotification` WARNING
    signale l'anomalie. `BreadStock` n'est PAS corrigé ;
  - en attente de validation (dépassement < 30 min) : `quantity_suggested`
    porte la valeur réelle, y compris négative ;
  - l'appel volontaire `close()` accepte une quantité `remaining` négative
    (sinon la modale pré-remplie ne pourrait pas être validée) ;
  - une quantité négative reste refusée pour tout autre type de disposition
    (API et contrainte base).

Données entièrement fictives.
"""
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
    ProductionSession, BreadDisposal, BreadStock, DailyBreadStockSnapshot,
)

SESSION_DATE = date(2026, 10, 14)
NOTIFICATION_TITLE_PREFIX = "Stock de pain négatif à la clôture automatique"


def _aware(hour, minute):
    return timezone.make_aware(
        datetime(SESSION_DATE.year, SESSION_DATE.month, SESSION_DATE.day, hour, minute),
        timezone.get_current_timezone(),
    )


class _ShiftEndBase(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.node.team_a_end_time = time(13, 0)
        self.node.save(update_fields=['team_a_end_time'])

        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp_500 = make_bread_price(category='MOYEN', label='Pain 500 FC B158', unit_price=500)
        self.bp_200 = make_bread_price(category='PETIT', label='Pain 200 FC B158', unit_price=200)

        self.client_api = APIClient()
        self.client_api.force_authenticate(self.gerant)

        resp = self.client_api.post('/api/production/sessions/', {
            'team': 'A', 'date': SESSION_DATE.isoformat(), 'flour_sacks_used': '2.00',
            'lines': [
                {'bread_price': self.bp_500.pk, 'quantity': 50},
                {'bread_price': self.bp_200.pk, 'quantity': 60},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.session_id = resp.data['id']

    def _make_500_negative(self):
        """Déclassement de 70 pains pour 50 produits : stock physique à -20."""
        resp = self.client_api.post('/api/production/disposals/', {
            'session': self.session_id, 'bread_price': self.bp_500.pk,
            'disposal_type': 'DECLASSED', 'quantity': 70,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp_500)
        self.assertEqual(stock.qty_available, -20, "Pré-requis : stock physique négatif.")

    def _status(self, mocked_now):
        with patch('django.utils.timezone.now', return_value=mocked_now):
            return self.client_api.get(
                '/api/production/sessions/shift-end-status/', {'node': self.node.code},
            )

    def _negative_stock_notifications(self):
        return SystemNotification.objects.filter(title__startswith=NOTIFICATION_TITLE_PREFIX)

    def _remaining_by_bread_price(self):
        return {
            d.bread_price_id: d.quantity
            for d in BreadDisposal.objects.filter(
                session_id=self.session_id,
                disposal_type=BreadDisposal.DisposalType.REMAINING,
            )
        }


class ForcedClosureNegativeStockTests(_ShiftEndBase):
    def test_forced_closure_records_negative_remaining_and_notifies(self):
        self._make_500_negative()

        resp = self._status(_aware(13, 40))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data, {'pending_validation': False, 'auto_closed': True, 'team': 'A'})

        session = ProductionSession.objects.get(pk=self.session_id)
        self.assertTrue(session.is_closed)
        self.assertIsNotNone(session.closed_at)

        remaining = self._remaining_by_bread_price()
        self.assertEqual(remaining.get(self.bp_500.pk), -20)
        self.assertEqual(remaining.get(self.bp_200.pk), 60)

        notifications = self._negative_stock_notifications()
        self.assertEqual(notifications.count(), 1)
        notification = notifications.get()
        self.assertEqual(notification.severity, 'WARNING')
        self.assertEqual(notification.node_origin, self.node.code)
        self.assertIn(self.node.code, notification.title)
        self.assertIn(str(self.bp_500), notification.message)
        self.assertIn('-20', notification.message)
        self.assertNotIn(
            str(self.bp_200), notification.message,
            "Seules les catégories au stock négatif doivent être citées.",
        )

    def test_negative_remaining_propagates_to_snapshot_and_reports(self):
        """Le reste négatif n'est ni tronqué ni ignoré par les lecteurs."""
        self._make_500_negative()
        resp = self._status(_aware(13, 40))
        self.assertEqual(resp.status_code, 200, resp.data)

        snapshots = {
            s.bread_price_id: s.qty_at_close
            for s in DailyBreadStockSnapshot.objects.filter(
                node=self.node, date=SESSION_DATE, team='A',
            )
        }
        self.assertEqual(snapshots, {self.bp_500.pk: -20, self.bp_200.pk: 60})

        # Rapport de clôture du jour : reste du jour négatif, valorisé en FC.
        resp = self.client_api.get(
            '/api/production/daily-closure/', {'date': SESSION_DATE.isoformat()},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        by_bp = {c['bread_price']: c for c in resp.data['categories']}
        self.assertEqual(by_bp[self.bp_500.pk]['reste_du_jour']['A'], -20)
        self.assertEqual(by_bp[self.bp_200.pk]['reste_du_jour']['A'], 60)
        # 500 FC : reste du jour -20 × 500 = -10 000 + déclassés 70 × 0 = 0.
        self.assertEqual(
            Decimal(by_bp[self.bp_500.pk]['facture_mvm_interne']['fc']), Decimal('-10000.00'),
        )

        # Rapport du lendemain : reste du hier = −reste du jour de la veille.
        next_day = SESSION_DATE + timedelta(days=1)
        resp = self.client_api.get(
            '/api/production/daily-closure/', {'date': next_day.isoformat()},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        by_bp = {c['bread_price']: c for c in resp.data['categories']}
        self.assertEqual(by_bp[self.bp_500.pk]['reste_du_hier']['A'], 20)
        self.assertEqual(by_bp[self.bp_200.pk]['reste_du_hier']['A'], -60)

        # Stock par jour (BUG-144), source snapshot pour un jour passé.
        resp = self.client_api.get(
            '/api/production/bread-stocks/by-date/', {'date': SESSION_DATE.isoformat()},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['source'], 'snapshot')
        qty = {c['bread_price']: c['qty_available'] for c in resp.data['categories']}
        self.assertEqual(qty, {self.bp_500.pk: -20, self.bp_200.pk: 60})

    def test_forced_closure_does_not_alter_bread_stock(self):
        self._make_500_negative()

        def snapshot():
            return {
                bs.bread_price_id: (
                    bs.qty_produced, bs.qty_received, bs.qty_sent,
                    bs.qty_disposed, bs.qty_adjusted, bs.qty_available,
                )
                for bs in BreadStock.objects.filter(node=self.node)
            }

        before = snapshot()

        resp = self._status(_aware(13, 40))
        self.assertEqual(resp.status_code, 200, resp.data)

        after = snapshot()
        self.assertEqual(after, before, "Le stock négatif est signalé, jamais corrigé.")
        self.assertEqual(after[self.bp_500.pk][-1], -20)

    def test_second_poll_after_forced_closure_is_idempotent(self):
        """Le polling suivant ne replante pas et ne duplique pas l'alerte."""
        self._make_500_negative()
        self._status(_aware(13, 40))

        resp = self._status(_aware(13, 41))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data, {'pending_validation': False})
        self.assertEqual(self._negative_stock_notifications().count(), 1)

    def test_forced_closure_without_negative_stock_creates_no_notification(self):
        resp = self._status(_aware(13, 40))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data.get('auto_closed'))

        remaining = self._remaining_by_bread_price()
        self.assertEqual(remaining.get(self.bp_500.pk), 50)
        self.assertEqual(remaining.get(self.bp_200.pk), 60)
        self.assertEqual(self._negative_stock_notifications().count(), 0)


class PendingValidationNegativeStockTests(_ShiftEndBase):
    def test_quantity_suggested_keeps_negative_value(self):
        self._make_500_negative()
        notifications_before = SystemNotification.objects.count()

        resp = self._status(_aware(13, 20))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['pending_validation'])
        self.assertFalse(resp.data['auto_closed'])

        suggested = {r['bread_price']: r['quantity_suggested'] for r in resp.data['remaining']}
        self.assertEqual(suggested.get(self.bp_500.pk), -20)
        self.assertEqual(suggested.get(self.bp_200.pk), 60)

        session = ProductionSession.objects.get(pk=self.session_id)
        self.assertFalse(session.is_closed)
        # Simple lecture répétée toutes les 10 s : aucune alerte en mode pending.
        self.assertEqual(SystemNotification.objects.count(), notifications_before)

    def test_suggested_values_are_accepted_by_voluntary_close(self):
        """Les valeurs pré-remplies (dont la négative) sont acceptées par `close()`."""
        self._make_500_negative()
        resp = self._status(_aware(13, 20))
        payload = [
            {'bread_price': r['bread_price'], 'quantity': r['quantity_suggested']}
            for r in resp.data['remaining']
        ]

        resp = self.client_api.post(
            f'/api/production/sessions/{self.session_id}/close/',
            {'remaining': payload}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(ProductionSession.objects.get(pk=self.session_id).is_closed)
        remaining = self._remaining_by_bread_price()
        self.assertEqual(remaining.get(self.bp_500.pk), -20)
        self.assertEqual(remaining.get(self.bp_200.pk), 60)
        snap = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp_500, date=SESSION_DATE, team='A',
        )
        self.assertEqual(snap.qty_at_close, -20)


class NegativeQuantityOnlyForRemainingTests(_ShiftEndBase):
    """Le négatif n'est ouvert QUE pour le type REMAINING."""

    def _post_disposal(self, disposal_type, quantity):
        return self.client_api.post('/api/production/disposals/', {
            'session': self.session_id, 'bread_price': self.bp_500.pk,
            'disposal_type': disposal_type, 'quantity': quantity,
        }, format='json')

    def test_api_rejects_negative_quantity_for_other_types(self):
        stock_before = BreadStock.objects.get(node=self.node, bread_price=self.bp_500).qty_available
        for disposal_type in ('DECLASSED', 'UNSOLD', 'FREE_DIST'):
            with self.subTest(disposal_type=disposal_type):
                resp = self._post_disposal(disposal_type, -5)
                self.assertEqual(resp.status_code, 400, resp.data)
                self.assertIn('quantity', resp.data)
        self.assertEqual(BreadDisposal.objects.filter(session_id=self.session_id).count(), 0)
        self.assertEqual(
            BreadStock.objects.get(node=self.node, bread_price=self.bp_500).qty_available,
            stock_before,
        )

    def test_api_accepts_negative_quantity_for_remaining(self):
        resp = self._post_disposal('REMAINING', -5)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['quantity'], -5)

    def test_api_rejects_retyping_a_negative_remaining_line(self):
        resp = self._post_disposal('REMAINING', -5)
        self.assertEqual(resp.status_code, 201, resp.data)

        resp = self.client_api.patch(
            f"/api/production/disposals/{resp.data['id']}/",
            {'disposal_type': 'DECLASSED'}, format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_database_constraint_rejects_negative_quantity_for_other_types(self):
        """Filet de sécurité hors API (synchronisation, admin, code interne)."""
        session = ProductionSession.objects.get(pk=self.session_id)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BreadDisposal.objects.create(
                    session=session, bread_price=self.bp_500, node=self.node,
                    node_origin=self.node.code,
                    disposal_type=BreadDisposal.DisposalType.UNSOLD, quantity=-1,
                )
