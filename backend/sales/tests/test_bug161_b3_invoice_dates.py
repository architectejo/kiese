"""
BUG-161 (B3) / BUG-189 : dates des factures = date de travail du nœud
(`core.workday.work_date_for`) : date locale hors rotation (jamais la date UTC
ni celle du système), journée de relève à relève en rotation.
"""
from datetime import timezone as dt_timezone
from datetime import date, datetime, time
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client, get_config
from core.workday import work_date_for
from production.models import DailyTeamAssignment
from sales.models import Invoice
from sales.views import _combine_date_with_now_time

D = date(2026, 11, 12)
PREV = date(2026, 11, 11)
OLDER = date(2026, 11, 10)
INV = '/api/sales/invoices/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    # Comme `timezone.now()` réel : datetime aware en UTC (BUG-189 : `.date()` = date UTC).
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.gerant = make_user('GERANT', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api(self.fact)

    def _rotation(self, handover=time(12, 0)):
        self.node.team_rotation_enabled = True
        self.node.handover_time = handover
        self.node.save()

    def _sale(self, **extra):
        payload = {
            'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': 500,
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        payload.update(extra)
        return self.api.post(INV, payload, format='json')

    def _repay(self, **extra):
        payload = {
            'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': 100,
            'is_debt_repayment': True, 'lines': [],
        }
        payload.update(extra)
        return self.api.post(INV, payload, format='json')


class NoRotationEquivalenceTests(_Base):
    def test_invoice_date_and_receipt_use_local_date_at_00_30(self):
        with _now(0, 30):
            r = self._sale()
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.invoice_date, D)
        self.assertTrue(inv.receipt_number.startswith('K1-20261112-'), inv.receipt_number)

    def test_invoice_date_at_noon_unchanged(self):
        with _now(12, 0):
            r = self._sale()
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.invoice_date, D)
        self.assertTrue(inv.receipt_number.startswith('K1-20261112-0001'))

    def test_future_date_refused_and_today_accepted_at_00_30(self):
        with _now(0, 30):
            self.assertEqual(self._sale(invoice_date='2026-11-13').status_code, 400)
            self.assertEqual(self._sale(invoice_date='2026-11-12').status_code, 201)

    def test_past_date_refused_without_backdating_setting(self):
        with _now(0, 30):
            r = self._sale(invoice_date='2026-11-11')
        self.assertEqual(r.status_code, 400)

    def test_repayment_not_backdated_at_00_30(self):
        with _now(0, 30), patch('sales.views._warn_if_commission_period_locked') as warn:
            r = self._repay()
        self.assertEqual(r.status_code, 201, r.data)
        warn.assert_not_called()

    def test_pending_deliveries_default_date_is_local_date(self):
        with _now(0, 30):
            r = self._sale()
            self.assertEqual(r.status_code, 201)
            resp = _api(self.gerant).get(INV + 'pending_deliveries/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

    def test_daily_summary_default_date_is_local_date(self):
        with _now(0, 30):
            r = self._sale()
            Invoice.objects.filter(pk=r.data['id']).update(status=Invoice.Status.DELIVERED)
            resp = _api(self.gerant).get(INV + 'daily_summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data and resp.data[0]['total'] == 500)


class RotationDatesTests(_Base):
    def setUp(self):
        super().setUp()
        self._rotation()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')

    def test_sale_at_03_00_carries_previous_work_date(self):
        with _now(3, 0):
            r = self._sale()
        self.assertEqual(r.status_code, 201, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.invoice_date, PREV)
        self.assertEqual(inv.team, 'B')
        self.assertTrue(inv.receipt_number.startswith('K1-20261111-'), inv.receipt_number)

    def test_sale_at_12_00_sharp_carries_current_date(self):
        with _now(12, 0):
            r = self._sale()
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.invoice_date, D)
        self.assertEqual(inv.team, 'A')

    def test_sale_at_11_59_still_previous_work_date(self):
        with _now(11, 59):
            r = self._sale()
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).invoice_date, PREV)

    def test_calendar_date_after_midnight_is_future_in_rotation(self):
        # 03:00 le 12/11 : la journée de travail est le 11/11 ; le 12/11 est « futur ».
        with _now(3, 0):
            r = self._sale(invoice_date='2026-11-12')
        self.assertEqual(r.status_code, 400)
        self.assertIn('future', r.data['detail'])

    def test_current_work_date_accepted_without_backdating_setting(self):
        with _now(3, 0):
            r = self._sale(invoice_date='2026-11-11')
        self.assertEqual(r.status_code, 201, r.data)

    def test_current_work_date_is_not_backdated(self):
        with _now(3, 0), patch('sales.views._warn_if_commission_period_locked') as warn:
            r = self._repay(invoice_date='2026-11-11')
        self.assertEqual(r.status_code, 201, r.data)
        warn.assert_not_called()

    def test_previous_work_date_is_backdated(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        with _now(3, 0), patch('sales.views._warn_if_commission_period_locked') as warn:
            r = self._repay(invoice_date='2026-11-10')
        self.assertEqual(r.status_code, 201, r.data)
        warn.assert_called_once()

    def test_backdated_delivered_at_stays_inside_target_work_date(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        with _now(3, 0):
            r = self._repay(invoice_date='2026-11-10')
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(work_date_for(self.node, inv.delivered_at), OLDER)

    def test_combine_date_with_now_time_rotation(self):
        with _now(3, 0):
            self.assertEqual(_combine_date_with_now_time(PREV, self.node), _at(D, 3, 0))
            moved = _combine_date_with_now_time(OLDER, self.node)
            self.assertEqual(work_date_for(self.node, moved), OLDER)
        with _now(15, 0):
            moved = _combine_date_with_now_time(PREV, self.node)
            self.assertEqual(work_date_for(self.node, moved), PREV)
            self.assertEqual(_combine_date_with_now_time(D, self.node), _at(D, 15, 0))

    def test_combine_date_with_now_time_without_rotation_unchanged(self):
        plain = make_node(code='K9')
        with _now(3, 0):
            self.assertEqual(_combine_date_with_now_time(D, plain), _at(D, 3, 0))
            self.assertEqual(_combine_date_with_now_time(D), _at(D, 3, 0))
            self.assertEqual(_combine_date_with_now_time(PREV), _at(PREV, 3, 0))

    def test_pending_deliveries_lists_current_work_date(self):
        with _now(3, 0):
            r = self._sale()
            self.assertEqual(r.status_code, 201, r.data)
            resp = _api(self.gerant).get(INV + 'pending_deliveries/')
        self.assertEqual(len(resp.data), 1)

    def test_adjust_takes_current_work_date(self):
        with _now(3, 0):
            r = self._sale()
            inv = Invoice.objects.get(pk=r.data['id'])
            _api(self.gerant).post(f'{INV}{inv.pk}/deliver/', {}, format='json')
            adj = _api(self.gerant).post(f'{INV}{inv.pk}/adjust/', {
                'adjustment_sign': 1, 'payment_amount': 0,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
            }, format='json')
        self.assertEqual(adj.status_code, 201, adj.data)
        adjustment = Invoice.objects.get(pk=adj.data['id'])
        self.assertEqual(adjustment.invoice_date, PREV)
        self.assertTrue(adjustment.receipt_number.startswith('K1-20261111-'))
