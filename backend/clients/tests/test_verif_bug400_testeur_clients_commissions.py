"""Vérification indépendante BUG-400 (testeur-clients-commissions) : historique client."""
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_client
from sales.models import Invoice

S = Invoice.Status
MONEY = r'^-?\d+\.\d{2}$'


class VerifHistoryBug400(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', name='K1 - TABORA')
        self.k3 = make_node(code='K3', name='K3 - ATHENEE')
        self.cl = make_client(self.k1, first_name='VERIF', last_name='Hist')
        self.seq = 0

    def api(self, role='GERANT', node=None):
        a = APIClient()
        a.force_authenticate(user=make_user(role=role, node=node or self.k1))
        return a

    def url(self, cl=None):
        return f'/api/clients/clients/{(cl or self.cl).id}/history/'

    def inv(self, d, order='0', pay='0', before='0', after='0', status=S.DELIVERED, at=None, **kw):
        self.seq += 1
        if at is None:
            at = timezone.make_aware(datetime.combine(d, time(8, 0)) + timedelta(minutes=self.seq))
        return Invoice.objects.create(
            node=self.k1, client=self.cl, invoice_date=d, status=status, delivered_at=at,
            order_total=Decimal(order), payment_amount=Decimal(pay),
            debt_before=Decimal(before), debt_after=Decimal(after), **kw)

    def get(self, month=None, **kw):
        return self.api(**kw).get(self.url(), {'month': month} if month is not None else {})

    # ---- mois limites
    def test_december_and_january_boundaries(self):
        self.inv(date(2025, 12, 31), '1000', '0', '0', '1000')
        self.inv(date(2026, 1, 1), '2000', '0', '1000', '3000')
        dec = self.get('2025-12').json()
        jan = self.get('2026-01').json()
        self.assertEqual([o['order_value'] for o in dec['operations']], ['1000.00'])
        self.assertEqual([o['order_value'] for o in jan['operations']], ['2000.00'])
        self.assertEqual(jan['totals']['bp_start'], '1000.00')
        self.assertIn('2025-12', jan['available_months'])
        self.assertIn('2026-01', jan['available_months'])

    def test_limit_months_accepted(self):
        for m in ('2000-01', '2000-12', '9999-12'):
            self.assertEqual(self.get(m).status_code, 200, m)

    def test_future_month_empty_200(self):
        r = self.get('2099-06')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['operations'], [])
        self.assertIsNone(r.json()['totals']['bp_end'])

    def test_malformed_month_never_500(self):
        for bad in ('2026-1', '26-01', '2026/01', ' ', '2026-01-01', '-2026-01', '0000-01',
                    '２０２６-０１', '2026-ab', 'null', '2026-01\n', '2026-99'):
            r = self.get(bad)
            self.assertIn(r.status_code, (200, 400), repr(bad))

    def test_empty_month_param_means_current(self):
        r = self.api().get(self.url() + '?month=')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['month'], timezone.localdate().strftime('%Y-%m'))

    # ---- 404 / rôles
    def test_unknown_uuid_404(self):
        self.assertEqual(self.api().get(f'/api/clients/clients/{uuid.uuid4()}/history/').status_code, 404)

    def test_non_uuid_id_not_500(self):
        r = self.api().get('/api/clients/clients/pas-un-uuid/history/')
        self.assertIn(r.status_code, (400, 404))

    def test_other_node_404_for_gerant_and_not_leaked(self):
        other = make_client(self.k3, first_name='AUTRE', last_name='Noeud')
        r = self.api('GERANT').get(self.url(other))
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('Noeud', r.content.decode())

    def test_roles(self):
        for role, code in (('GERANT', 200), ('COMPTABLE', 200), ('DIRECTION', 200), ('ADMIN', 200),
                           ('FACTURIER', 403), ('LIVREUR', 403)):
            self.assertEqual(self.get(role=role).status_code, code, role)
        self.assertEqual(APIClient().get(self.url()).status_code, 401)

    def test_facturier_other_node_still_403(self):
        other = make_client(self.k3, last_name='Autre')
        self.assertEqual(self.api('FACTURIER').get(self.url(other)).status_code, 403)

    def test_post_not_allowed(self):
        self.assertEqual(self.api().post(self.url(), {}).status_code, 405)

    # ---- statuts exclus des totaux
    def test_non_delivered_excluded_from_totals_but_listed(self):
        d = date(2026, 5, 10)
        self.inv(d, '10000', '3000', '0', '7000')
        self.inv(d, '99999', '99999', '7000', '7000', status=S.NOT_SERVED)
        self.inv(d, '88888', '0', '7000', '95888', status=S.PENDING)
        self.inv(d, '77777', '0', '7000', '84777', status=S.CANCELLED)
        j = self.get('2026-05').json()
        t = j['totals']
        self.assertEqual(t['operations_count'], 4)
        self.assertEqual(t['delivered_count'], 1)
        self.assertEqual(t['total_orders'], '10000.00')
        self.assertEqual(t['total_payments'], '3000.00')
        self.assertEqual(t['bp_start'], '0.00')
        self.assertEqual(t['bp_end'], '7000.00')
        self.assertEqual({o['status'] for o in j['operations']},
                         {'DELIVERED', 'NOT_SERVED', 'PENDING', 'CANCELLED'})

    def test_only_non_delivered_gives_zero_totals_and_null_bp(self):
        self.inv(date(2026, 5, 10), '500', '0', '0', '500', status=S.PENDING)
        t = self.get('2026-05').json()['totals']
        self.assertEqual(t['total_orders'], '0.00')
        self.assertIsNone(t['bp_start'])
        self.assertIsNone(t['bp_end'])

    # ---- types
    def test_types_and_bp_coherence(self):
        d = date(2026, 6, 5)
        self.inv(d, '10000', '4000', '0', '6000')                              # achat
        self.inv(d, '0', '2500', '6000', '3500')                               # depot
        self.inv(d, '0', '-1000', '3500', '4500', motif='RETRAIT_EPARGNE')     # retrait
        self.inv(d, '0', '1500', '4500', '3000', is_debt_repayment=True)       # remboursement
        j = self.get('2026-06').json()
        self.assertEqual([o['type'] for o in j['operations']],
                         ['ACHAT', 'DEPOT', 'RETRAIT', 'REMBOURSEMENT'])
        t = j['totals']
        self.assertEqual(t['total_orders'], '10000.00')
        self.assertEqual(t['total_payments'], '8000.00')
        self.assertEqual(t['total_withdrawals'], '1000.00')
        self.assertEqual(t['net_balance_change'], '3000.00')
        self.assertEqual(Decimal(t['bp_end']) - Decimal(t['bp_start']), Decimal(t['net_balance_change']))

    def test_refund_not_counted_as_order(self):
        self.inv(date(2026, 6, 5), '0', '1000', '5000', '4000', is_debt_repayment=True)
        t = self.get('2026-06').json()['totals']
        self.assertEqual(t['total_orders'], '0.00')
        self.assertEqual(t['total_payments'], '1000.00')

    def test_negative_bp_savings_client(self):
        self.inv(date(2026, 6, 5), '0', '5000', '0', '-5000')
        t = self.get('2026-06').json()['totals']
        self.assertEqual(t['bp_end'], '-5000.00')
        self.assertEqual(t['net_balance_change'], '-5000.00')

    def test_adjustment_type(self):
        self.inv(date(2026, 6, 5), '100', '0', '0', '100', is_adjustment=True)
        self.assertEqual(self.get('2026-06').json()['operations'][0]['type'], 'AJUSTEMENT')

    # ---- décimaux
    def test_decimal_two_places_exact(self):
        self.inv(date(2026, 6, 5), '1000.10', '0.20', '0', '999.90')
        self.inv(date(2026, 6, 5), '2000.20', '0.10', '999.90', '3000.00')
        j = self.get('2026-06').json()
        t = j['totals']
        self.assertEqual(t['total_orders'], '3000.30')
        self.assertEqual(t['total_payments'], '0.30')
        for k in ('total_orders', 'total_payments', 'total_withdrawals', 'net_balance_change', 'bp_start', 'bp_end'):
            self.assertRegex(t[k], MONEY, k)
        for o in j['operations']:
            for k in ('order_value', 'payment', 'bp_before', 'bp_after'):
                self.assertIsInstance(o[k], str)
                self.assertRegex(o[k], MONEY)

    # ---- tri
    def test_sort_oldest_first_and_stable(self):
        a = self.inv(date(2026, 7, 2), '1')
        b = self.inv(date(2026, 7, 1), '2')
        t = timezone.make_aware(datetime(2026, 7, 3, 9, 0))
        c = self.inv(date(2026, 7, 3), '3', at=t)
        d = self.inv(date(2026, 7, 3), '4', at=t)
        ids1 = [o['id'] for o in self.get('2026-07').json()['operations']]
        ids2 = [o['id'] for o in self.get('2026-07').json()['operations']]
        self.assertEqual(ids1, ids2)
        self.assertEqual(ids1[:2], [str(b.id), str(a.id)])
        self.assertEqual(set(ids1[2:]), {str(c.id), str(d.id)})

    # ---- fuseau horaire
    def test_month_boundary_follows_invoice_date_not_utc(self):
        late = timezone.make_aware(datetime(2026, 3, 31, 23, 50))
        early = timezone.make_aware(datetime(2026, 4, 1, 0, 10))
        self.inv(date(2026, 3, 31), '1000', '0', '0', '1000', at=late)
        self.inv(date(2026, 4, 1), '2000', '0', '1000', '3000', at=early)
        mar = self.get('2026-03').json()
        apr = self.get('2026-04').json()
        self.assertEqual([o['order_value'] for o in mar['operations']], ['1000.00'])
        self.assertEqual([o['order_value'] for o in apr['operations']], ['2000.00'])
        self.assertEqual(apr['operations'][0]['date'], '2026-04-01')

    def test_available_months_sorted_desc_unique_contains_current(self):
        self.inv(date(2026, 1, 31))
        self.inv(date(2026, 1, 1))
        self.inv(date(2025, 12, 31))
        am = self.get('2026-01').json()['available_months']
        self.assertEqual(am, sorted(set(am), reverse=True))
        self.assertIn(timezone.localdate().strftime('%Y-%m'), am)
        self.assertEqual(am.count('2026-01'), 1)

    def test_other_clients_invoices_not_mixed(self):
        other = make_client(self.k1, last_name='Voisin')
        Invoice.objects.create(node=self.k1, client=other, invoice_date=date(2026, 8, 1), status=S.DELIVERED,
                               order_total=Decimal('777'), payment_amount=0, debt_before=0, debt_after=777)
        j = self.get('2026-08').json()
        self.assertEqual(j['operations'], [])
        self.assertNotIn('2026-08', j['available_months'])

    # ---- requêtes
    def test_query_count_constant(self):
        d = date(2026, 9, 1)
        for _ in range(3):
            self.inv(d, '100')
        api = self.api()
        api.get(self.url(), {'month': '2026-09'})
        with CaptureQueriesContext(connection) as small:
            api.get(self.url(), {'month': '2026-09'})
        for _ in range(30):
            self.inv(d, '100')
        with CaptureQueriesContext(connection) as big:
            r = api.get(self.url(), {'month': '2026-09'})
        self.assertEqual(len(r.json()['operations']), 33)
        self.assertEqual(len(small), len(big), 'N+1 detecte')
        self.assertLessEqual(len(big), 8)
