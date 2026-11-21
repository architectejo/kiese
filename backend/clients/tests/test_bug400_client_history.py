"""BUG-400 : historique mensuel des opérations d'un client (modale Commissions / Clientèle)."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_client
from sales.models import Invoice


class ClientHistoryTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', name='K1 - TABORA')
        self.k3 = make_node(code='K3', name='K3 - ATHENEE')
        self.cl = make_client(self.k1, first_name='DEMO', last_name='Histo')
        self.today = timezone.localdate()
        self.prev = date(2026, 3, 10)

    def api(self, role='GERANT', node=None):
        a = APIClient()
        a.force_authenticate(user=make_user(role=role, node=node or self.k1))
        return a

    def inv(self, d, order, pay, before, after, **kw):
        # Horodatage explicite et croissant : sous Windows, deux créations successives
        # peuvent avoir le même created_at, ce qui rendrait l'ordre aléatoire.
        self._seq = getattr(self, '_seq', 0) + 1
        kw.setdefault('delivered_at', timezone.make_aware(datetime.combine(d, time(8, 0)) + timedelta(minutes=self._seq)))
        return Invoice.objects.create(
            node=self.k1, client=self.cl, invoice_date=d, status=kw.pop('status', Invoice.Status.DELIVERED),
            order_total=Decimal(order), payment_amount=Decimal(pay),
            debt_before=Decimal(before), debt_after=Decimal(after), **kw)

    def url(self, cl=None):
        return f'/api/clients/clients/{(cl or self.cl).id}/history/'

    def test_default_current_month_and_totals(self):
        self.inv(self.today, '10000', '4000', '0', '6000')
        self.inv(self.today, '0', '2000', '6000', '4000')          # dépôt
        self.inv(self.today, '0', '-1000', '4000', '5000', motif='RETRAIT_EPARGNE')
        self.inv(self.prev, '5000', '5000', '0', '0')
        r = self.api().get(self.url())
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['month'], self.today.strftime('%Y-%m'))
        self.assertEqual(len(d['operations']), 3)
        self.assertEqual({o['type'] for o in d['operations']}, {'ACHAT', 'DEPOT', 'RETRAIT'})
        t = d['totals']
        self.assertEqual(t['total_orders'], '10000.00')
        self.assertEqual(t['total_payments'], '6000.00')
        self.assertEqual(t['total_withdrawals'], '1000.00')
        self.assertEqual(t['bp_start'], '0.00')
        self.assertEqual(t['bp_end'], '5000.00')
        self.assertIn('2026-03', d['available_months'])
        self.assertEqual(d['available_months'][0], self.today.strftime('%Y-%m') if self.today >= self.prev else '2026-03')

    def test_past_month(self):
        self.inv(self.today, '10000', '0', '0', '10000')
        self.inv(self.prev, '5000', '5000', '0', '0')
        d = self.api().get(self.url(), {'month': '2026-03'}).json()
        self.assertEqual(len(d['operations']), 1)
        self.assertEqual(d['totals']['total_orders'], '5000.00')

    def test_invalid_month_is_400_french(self):
        for bad in ('2026-13', 'abc', '2026-1', '1999-05', '2026-00', "2026-11'; --"):
            r = self.api().get(self.url(), {'month': bad})
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('detail', r.json())

    def test_empty_month_ok(self):
        d = self.api().get(self.url(), {'month': '2020-01'}).json()
        self.assertEqual(d['operations'], [])
        self.assertIsNone(d['totals']['bp_start'])

    def test_order_is_deterministic(self):
        for i in range(4):
            self.inv(self.today, str(1000 * (i + 1)), '0', '0', '0')
        a = [o['id'] for o in self.api().get(self.url()).json()['operations']]
        b = [o['id'] for o in self.api().get(self.url()).json()['operations']]
        self.assertEqual(a, b)

    def test_permissions(self):
        self.assertEqual(self.api('FACTURIER').get(self.url()).status_code, 403)
        self.assertEqual(self.api('LIVREUR').get(self.url()).status_code, 403)
        self.assertEqual(self.api('COMPTABLE').get(self.url()).status_code, 200)
        self.assertEqual(self.api('DIRECTION').get(self.url()).status_code, 200)
        a = APIClient()
        self.assertIn(a.get(self.url()).status_code, (401, 403))

    def test_node_scoping(self):
        other = make_client(self.k3, first_name='DEMO', last_name='Autre')
        self.assertEqual(self.api('GERANT').get(self.url(other)).status_code, 404)
        self.assertEqual(self.api('DIRECTION').get(self.url(other)).status_code, 200)
