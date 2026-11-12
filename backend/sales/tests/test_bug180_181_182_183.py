"""
BUG-180 (RG hors plafond/déficit du mois), BUG-181 (`adjust` sur NS/RG),
BUG-182 (équipe désignée sur `adjust`), BUG-183 (équipe d'une vente
rétroactive = équipe de sa propre journée). Données fictives.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import BreadStock, DailyTeamAssignment
from sales.models import Invoice
from sync.services import recompute_client_debt

INV = '/api/sales/invoices/'
D = date(2026, 11, 11)


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _at(d, h):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, 0), timezone.get_current_timezone())


class Base(TestCase):
    def setUp(self):
        self.node = make_node()
        self.bp = make_bread_price('B180_500', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.ger = make_user('GERANT', node=self.node, team='A')
        self.cl = make_client(self.node, credit_limit=Decimal('50000.00'))
        self.f, self.g = _api(self.fact), _api(self.ger)

    def post(self, code='', ptype='CASH', pay=0, qty=4, **extra):
        payload = {'payment_type': ptype, 'payment_amount': pay, 'special_code': code,
                   'client': str(self.cl.pk), 'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}
        payload.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return self.f.post(INV, payload, format='json')

    def adjust(self, inv_id, sign, qty, pay=0):
        with self.captureOnCommitCallbacks(execute=True):
            return self.g.post(f'{INV}{inv_id}/adjust/', {
                'adjustment_sign': sign, 'payment_amount': pay,
                'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}, format='json')

    def debt(self):
        self.cl.refresh_from_db()
        return self.cl.current_debt

    def sent(self):
        return sum(BreadStock.objects.filter(node=self.node, bread_price=self.bp)
                   .values_list('qty_sent', flat=True))


class Bug180Rg(Base):
    def test_rg_created_for_client_over_ceiling(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=Decimal('60000'))
        r = self.post('RG', qty=2)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(), Decimal('60000'))

    def test_normal_sale_still_blocked_over_ceiling(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=Decimal('60000'))
        self.assertEqual(self.post('', 'CREDIT', qty=2).status_code, 403)

    def test_delivered_rg_does_not_feed_monthly_deficit(self):
        r = self.post('RG', qty=160)  # 80 000 FC
        self.assertEqual(self.f.post(f"{INV}{r.data['id']}/deliver/").status_code, 200)
        nxt = self.post('', 'CREDIT', qty=2)
        self.assertEqual(nxt.status_code, 201, nxt.data)

    def test_normal_big_credit_sale_still_blocks_next(self):
        r = self.post('', 'CREDIT', qty=160)  # BP 80 000 >= plafond
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.post('', 'CREDIT', qty=1).status_code, 403)


class Bug181Adjust(Base):
    def test_adjust_ns_cash_no_stock_no_debt(self):
        r = self.post('NS', 'CASH', qty=4)
        a = self.adjust(r.data['id'], -1, 2)
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(self.sent(), 0)
        self.assertEqual(self.debt(), Decimal('0'))
        self.assertEqual(Invoice.objects.get(pk=a.data['id']).debt_after, Decimal('0'))
        self.assertEqual(self.debt(), recompute_client_debt(self.cl.pk).current_debt)

    def test_adjust_ns_cash_payment_ignored(self):
        r = self.post('NS', 'CASH', qty=4)
        a = self.adjust(r.data['id'], 1, 2, pay=700)
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(Invoice.objects.get(pk=a.data['id']).payment_amount, Decimal('0'))
        self.assertEqual(self.debt(), Decimal('0'))

    def test_adjust_ns_credit_debt_follows_and_matches_recompute_no_stock(self):
        r = self.post('NS', 'CREDIT', qty=4)  # dette 2 000
        self.assertEqual(self.debt(), Decimal('2000'))
        a = self.adjust(r.data['id'], -1, 2)
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(self.debt(), Decimal('1000'))
        self.assertEqual(self.sent(), 0)
        self.assertEqual(self.debt(), recompute_client_debt(self.cl.pk).current_debt)

    def test_adjust_rg_creates_no_debt_but_moves_stock(self):
        r = self.post('RG', qty=4)
        self.assertEqual(self.sent(), 4)
        a = self.adjust(r.data['id'], 1, 2, pay=300)
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(self.debt(), Decimal('0'))
        self.assertEqual(Invoice.objects.get(pk=a.data['id']).payment_amount, Decimal('0'))
        self.assertEqual(self.sent(), 6)
        self.assertEqual(self.debt(), recompute_client_debt(self.cl.pk).current_debt)

    def test_adjust_normal_sale_unchanged(self):
        r = self.post('', 'CASH', pay=2000, qty=4)
        a = self.adjust(r.data['id'], 1, 2)
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(self.debt(), Decimal('1000'))
        self.assertEqual(self.sent(), 6)


class TeamBase(Base):
    def now(self):
        return patch('django.utils.timezone.now', return_value=_at(D, 13))

    def enable(self):
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])


class Bug182AdjustTeam(TeamBase):
    def test_adjust_takes_designated_team(self):
        r = self.post('', 'CASH', pay=2000)
        self.enable()
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='B')
        with self.now():
            a = self.adjust(r.data['id'], 1, 1)
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(Invoice.objects.get(pk=a.data['id']).team, 'B')

    def test_adjust_fallback_user_team_without_assignment(self):
        r = self.post('', 'CASH', pay=2000)
        self.enable()
        with self.now():
            a = self.adjust(r.data['id'], 1, 1)
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(Invoice.objects.get(pk=a.data['id']).team, 'A')


class Bug183BackdatedTeam(TeamBase):
    def setUp(self):
        super().setUp()
        cfg = Config.get_instance()
        cfg.allow_backdated_sales = True
        cfg.save()
        self.enable()
        self.yesterday = D - timedelta(days=1)

    def test_backdated_takes_team_of_its_own_day(self):
        DailyTeamAssignment.objects.create(node=self.node, work_date=self.yesterday, team='B')
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        with self.now():
            r = self.post('', 'CASH', pay=2000, invoice_date=str(self.yesterday))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).team, 'B')

    def test_backdated_without_assignment_falls_back_and_not_blocked(self):
        with self.now():
            r = self.post('', 'CASH', pay=2000, invoice_date=str(self.yesterday))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).team, 'A')

    def test_today_sale_still_blocked_without_assignment(self):
        with self.now():
            r = self.post('', 'CASH', pay=2000)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data.get('code'), 'TEAM_NOT_ASSIGNED')
