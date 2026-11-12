"""
BUG-161 (B2) : la facturation est bloquée tant que l'équipe de service du
jour n'est pas désignée, si `Node.team_rotation_enabled`. Sans le drapeau,
comportement historique inchangé.
"""
from datetime import date, datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import DailyTeamAssignment
from sales.models import Invoice

D = date(2026, 11, 11)
NEXT = date(2026, 11, 12)
INVOICES = '/api/sales/invoices/'
ASSIGN = '/api/production/team-assignment/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m))


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class TeamBlockingTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node, team='A')
        self.client_obj = make_client(self.node)
        self.api = _api(self.facturier)

    def _enable(self):
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])

    def _sale(self):
        return self.api.post(INVOICES, {
            'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': 500,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }, format='json')

    def _repay(self):
        return self.api.post(INVOICES, {
            'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': 100,
            'is_debt_repayment': True, 'lines': [],
        }, format='json')

    def test_flag_defaults_to_false(self):
        self.assertFalse(self.node.team_rotation_enabled)

    def test_blocked_when_flag_on_and_no_assignment(self):
        self._enable()
        with _now(13):
            for call in (self._sale, self._repay):
                r = call()
                self.assertEqual(r.status_code, 403, r.data)
                self.assertEqual(r.data['detail'], "Désignez l'équipe de service du jour avant de facturer.")
                self.assertEqual(r.data['code'], 'TEAM_NOT_ASSIGNED')
        self.assertFalse(Invoice.objects.exists())

    def test_passes_after_assignment_and_invoice_takes_assigned_team(self):
        self._enable()
        with _now(13):
            r = _api(make_user('GERANT', node=self.node)).post(ASSIGN, {'team': 'B'}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            r = self._sale()
            self.assertEqual(r.status_code, 201, r.data)
            r2 = self._repay()
            self.assertEqual(r2.status_code, 201, r2.data)
        # le facturier est de l'équipe A, mais l'équipe de service est B
        self.assertEqual(set(Invoice.objects.values_list('team', flat=True)), {'B'})

    def test_blocked_again_after_handover_until_new_assignment(self):
        self._enable()
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        with _now(11, 59, NEXT):
            self.assertEqual(self._sale().status_code, 201)
        with _now(12, 0, NEXT):
            self.assertEqual(self._sale().status_code, 403)

    def test_unchanged_without_flag(self):
        with _now(13):
            r = self._sale()
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(self._repay().status_code, 201)
        self.assertEqual(set(Invoice.objects.values_list('team', flat=True)), {'A'})

    def test_flag_is_per_node(self):
        self._enable()
        other = make_node(code='K2')
        other_fact = make_user('FACTURIER', node=other, team='B')
        with _now(13):
            r = _api(other_fact).post(INVOICES, {
                'payment_type': 'CASH', 'payment_amount': 500,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
            }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get().team, 'B')

    def test_flag_writable_by_direction_only(self):
        direction = make_user('DIRECTION', node=None)
        r = _api(direction).patch(f'/api/core/nodes/{self.node.pk}/', {'team_rotation_enabled': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['team_rotation_enabled'])
        gerant = make_user('GERANT', node=self.node)
        r = _api(gerant).patch(f'/api/core/nodes/{self.node.pk}/', {'team_rotation_enabled': False}, format='json')
        self.assertEqual(r.status_code, 403)
        self.node.refresh_from_db()
        self.assertTrue(self.node.team_rotation_enabled)
