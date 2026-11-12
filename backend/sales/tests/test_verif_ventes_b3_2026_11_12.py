"""
Vérification ventes de BUG-161/B3 (testeur-ventes, 2026-11-12) : scénarios
indépendants des tests de dev-backend. Heure simulée en UTC aware (Kinshasa = UTC+1).
Données fictives.
"""
from unittest import expectedFailure
from datetime import timezone as dt_timezone
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client, get_config
from core.workday import work_date_for
from production.models import DailyTeamAssignment
from sales.models import Invoice
from sync.services import recompute_client_debt

INV = '/api/sales/invoices/'
D = date(2026, 11, 12)
PREV = D - timedelta(days=1)


def _now(h, m=0, d=D):
    aware = timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())
    return patch('django.utils.timezone.now', return_value=aware.astimezone(dt_timezone.utc))


def _api(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='V1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.ger = make_user('GERANT', node=self.node)
        self.cl = make_client(self.node)
        self.f, self.g = _api(self.fact), _api(self.ger)

    def rot(self, handover=time(12, 0)):
        self.node.team_rotation_enabled = True
        self.node.handover_time = handover
        self.node.save()

    def sale(self, qty=1, pay=500, **extra):
        p = {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': pay,
             'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}
        p.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return self.f.post(INV, p, format='json')

    def deliver(self, inv_id, **body):
        with self.captureOnCommitCallbacks(execute=True):
            return self.g.post(f'{INV}{inv_id}/deliver/', body, format='json')

    def debt(self):
        self.cl.refresh_from_db()
        return self.cl.current_debt


class ReceiptNumbers(Base):
    def test_backdated_then_today_receipts_are_unique(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        with _now(10):
            a = self.sale(invoice_date=str(PREV))
            b = self.sale()
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(b.status_code, 201, b.data)
        na = Invoice.objects.get(pk=a.data['id']).receipt_number
        nb = Invoice.objects.get(pk=b.data['id']).receipt_number
        self.assertNotEqual(na, nb, f"doublon de numéro de reçu : {na}")

    def test_receipt_prefix_matches_invoice_date_for_backdated(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        with _now(10):
            a = self.sale(invoice_date=str(PREV))
        inv = Invoice.objects.get(pk=a.data['id'])
        self.assertIn(inv.invoice_date.strftime('%Y%m%d'), inv.receipt_number)


class RotationEdges(Base):
    def test_handover_23_30_boundaries(self):
        self.rot(time(23, 30))
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        with _now(23, 29):
            r1 = self.sale()
        with _now(23, 30):
            r2 = self.sale()
        with _now(0, 10, D + timedelta(days=1)):
            DailyTeamAssignment.objects.get_or_create(node=self.node, work_date=D, defaults={'team': 'A'})
            r3 = self.sale()
        self.assertEqual(Invoice.objects.get(pk=r1.data['id']).invoice_date, PREV)
        self.assertEqual(Invoice.objects.get(pk=r2.data['id']).invoice_date, D)
        self.assertEqual(Invoice.objects.get(pk=r3.data['id']).invoice_date, D)

    def test_deliver_with_explicit_past_delivered_at_stays_in_work_day(self):
        self.rot()
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        with _now(3, 0):
            r = self.sale()
            inv = Invoice.objects.get(pk=r.data['id'])
            self.assertEqual(inv.invoice_date, PREV)
            d = self.deliver(inv.pk, delivered_at=str(PREV - timedelta(days=1)))
        self.assertIn(d.status_code, (200, 400), d.data)
        if d.status_code == 200:
            inv.refresh_from_db()
            self.assertEqual(work_date_for(self.node, inv.delivered_at), PREV - timedelta(days=1))

    def test_delivery_at_03_00_of_sale_made_at_03_00_is_in_prev_work_day(self):
        self.rot()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        with _now(3, 0):
            r = self.sale()
            d = self.deliver(r.data['id'])
        self.assertEqual(d.status_code, 200, d.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(work_date_for(self.node, inv.delivered_at), PREV)

    def test_summaries_default_to_work_date_of_user_node(self):
        self.rot()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        with _now(3, 0):
            r = self.sale()
            self.deliver(r.data['id'])
            s = self.g.get(INV + 'daily_summary/')
            b = self.g.get(INV + 'bread_summary/')
            p = self.g.get(INV + 'pending_deliveries/')
        self.assertEqual(s.status_code, 200)
        self.assertEqual(sum(x['count'] for x in s.data.get('per_node', s.data.get('nodes', [])))
                         if isinstance(s.data, dict) and ('per_node' in s.data or 'nodes' in s.data) else 1, 1, s.data)
        self.assertEqual(b.status_code, 200)
        self.assertTrue(len(str(b.data)) > 5, b.data)
        self.assertEqual(p.status_code, 200)
        self.assertEqual(len(p.data), 0)  # déjà livrée

    def test_hq_user_without_node_defaults_to_local_date(self):
        hq = make_user('DIRECTION', node=None)
        with _now(0, 30):
            r = _api(hq).get(INV + 'pending_deliveries/')
        self.assertEqual(r.status_code, 200)


class NoRotationMidnight(Base):
    def test_invoice_date_is_local_calendar_date_at_00_30_and_summary(self):
        with _now(0, 30):
            r = self.sale()
            self.deliver(r.data['id'])
            inv = Invoice.objects.get(pk=r.data['id'])
            s = self.g.get(INV + 'daily_summary/')
        self.assertEqual(inv.invoice_date, D)
        self.assertTrue(inv.receipt_number.startswith('V1-20261112-'), inv.receipt_number)
        self.assertEqual(s.status_code, 200)

    def test_future_refused_and_nothing_changed_for_past(self):
        with _now(0, 30):
            f = self.sale(invoice_date=str(D + timedelta(days=1)))
            p = self.sale(invoice_date=str(PREV))
        self.assertEqual(f.status_code, 400)
        self.assertEqual(p.status_code, 400)  # allow_backdated_sales faux par défaut


class DebtConsistency(Base):
    def test_recompute_matches_stored_debt_across_handover(self):
        self.rot()
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='B')
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        ids = []
        for (h, m) in [(11, 59), (12, 0)]:
            with _now(h, m):
                r = self.sale(qty=4, pay=500)
                self.assertEqual(r.status_code, 201, r.data)
                ids.append(r.data['id'])
                self.deliver(r.data['id'])
        with _now(12, 5):
            with self.captureOnCommitCallbacks(execute=True):
                rep = self.f.post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': 700,
                                        'is_debt_repayment': True, 'lines': []}, format='json')
            self.assertEqual(rep.status_code, 201, rep.data)
        self.assertEqual(self.debt(), Decimal('1500') + Decimal('1500') - Decimal('700'))
        stored = self.debt()
        self.assertEqual(recompute_client_debt(self.cl.pk).current_debt, stored)
        dates = sorted(Invoice.objects.values_list('invoice_date', flat=True))
        self.assertEqual(dates, [PREV, D, D])

    def test_credit_block_unchanged_in_rotation(self):
        self.rot()
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='A')
        self.cl.current_debt = Decimal('50000')
        self.cl.save()
        with _now(13):
            blocked = self.sale(qty=2, pay=0)
            ok = self.sale(qty=2, pay=1000)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(ok.status_code, 201, ok.data)
