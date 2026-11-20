"""
BUG-319 (remarque.md l.445) : « Stock Pains du Jour » ne compte que les pains
VENDUS pendant la journée ; à la clôture, produit = vendus + restes (hypothèses
par défaut R1 à R5 du registre). BUG-322 : bornes avant tout int().
"""
import importlib
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price
from core.workday import work_date_for
from production.models import (
    BreadDisposal, BreadStock, BreadTransfer, BreadTransferLine, DailyOpeningConfirmation,
    DailyOpeningConfirmationLine, ProductionSession, ProductionSessionLine,
)


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', sac_value_fc=Decimal('210000'))
        self.gerant = make_user('GERANT', node=self.node)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.bp2 = make_bread_price('GRAND', 'Pain 1000 FC', 1000)
        self.api = _api(self.gerant)
        self.fapi = _api(self.facturier)
        self.today = work_date_for(self.node)

    def declare_sacs(self, sacs='2.00', team='A'):
        r = self.api.post('/api/production/sessions/', {
            'team': team, 'date': str(self.today), 'flour_sacks_used': sacs,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def create_invoice(self, qty, bp=None):
        bp = bp or self.bp
        r = self.fapi.post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': str(qty * bp.unit_price),
            'lines': [{'bread_price': bp.pk, 'quantity': qty}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def sell(self, qty, bp=None):
        iid = self.create_invoice(qty, bp)
        d = self.fapi.post(f'/api/sales/invoices/{iid}/deliver/')
        self.assertEqual(d.status_code, 200, d.data)
        return iid

    def by_date(self, date=None):
        params = {'node': 'K1'}
        if date:
            params['date'] = str(date)
        r = self.api.get('/api/production/bread-stocks/by-date/', params)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def cat(self, data, bp=None):
        bp = bp or self.bp
        return next(c for c in data['categories'] if c['bread_price'] == bp.pk)

    def close(self, sid, remaining):
        r = self.api.post(f'/api/production/sessions/{sid}/close/', {
            'remaining': [{'bread_price': b.pk, 'quantity': q} for b, q in remaining],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data


class SoldOnlyDuringTheDayTests(_Base):
    def test_delivery_writes_no_production_but_progress_follows_sales(self):
        sid = self.declare_sacs('2.00')
        self.sell(100)
        s = ProductionSession.objects.get(pk=sid)
        self.assertFalse(s.lines.filter(source='DECLARED').exists())
        self.assertEqual(s.total_fc_produced, 0)
        self.assertEqual(s.yield_gap, 0)  # pas d'écart avant clôture
        self.assertEqual(s.delivered_value_fc, 50000)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_produced, 0)
        got = self.api.get(f'/api/production/sessions/{sid}/').data
        self.assertEqual(got['objective_fc'], 420000)
        self.assertEqual(got['progress_value_fc'], 50000)
        self.assertEqual(got['progress_pct'], '11.90')

    def test_by_date_and_bread_stocks_expose_sold_only_before_closure(self):
        self.declare_sacs()
        self.sell(100)
        data = self.by_date()
        self.assertFalse(data['closed'])
        c = self.cat(data)
        self.assertEqual(c['sold_qty'], 100)
        self.assertIsNone(c['remaining_qty'])
        self.assertIsNone(c['produced_total'])
        self.assertFalse(c['closed'])
        self.assertIn('qty_available', c)  # rétro-compatibilité
        for key in ('bread_price', 'bread_price_display', 'unit_price'):
            self.assertIn(key, c)
        rows = self.api.get('/api/production/bread-stocks/', {'node': self.node.pk}).data
        rows = rows['results'] if isinstance(rows, dict) else rows
        row = next(r for r in rows if r['bread_price'] == self.bp.pk)
        self.assertEqual(row['sold_qty'], 100)
        self.assertIsNone(row['remaining_qty'])
        self.assertIsNone(row['produced_total'])
        self.assertFalse(row['closed'])

    def test_pending_not_served_and_adjustment_excluded_from_sold(self):
        self.declare_sacs()
        iid = self.create_invoice(10)
        self.assertEqual(self.api.get('/api/production/bread-stocks/by-date/', {'node': 'K1'}).data['categories'][0]['sold_qty'], 0)
        r = self.fapi.post(f'/api/sales/invoices/{iid}/mark-not-served/', {'reason': 'x'}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        self.sell(7)
        c = self.cat(self.by_date())
        self.assertEqual(c['sold_qty'], 7)  # la facture NOT_SERVED n'est jamais comptée


class ClosureDerivedProductionTests(_Base):
    def test_total_produced_is_sold_plus_remaining_and_gap_on_sacs(self):
        sid = self.declare_sacs('2.00')
        self.sell(100)
        self.close(sid, [(self.bp, 30)])
        data = self.by_date()
        self.assertTrue(data['closed'])
        c = self.cat(data)
        self.assertEqual((c['sold_qty'], c['remaining_qty'], c['produced_total'], c['closed']),
                         (100, 30, 130, True))
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.total_fc_produced, 65000)
        self.assertEqual(s.yield_gap, 65000 - 420000)  # manquant
        self.assertEqual(s.closure_summary['production_derivee']['ecart_fc'], 65000 - 420000)
        self.assertTrue(SystemNotification.objects.filter(title__startswith='Manquant de Rendement').exists())

    def test_excess_when_value_produced_exceeds_sacs(self):
        sid = self.declare_sacs('0.10')  # 21 000 FC théoriques
        self.sell(100)
        self.close(sid, [(self.bp, 0)])  # R4 : reste 0 autorisé
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.yield_gap, 50000 - 21000)
        self.assertEqual(self.cat(self.by_date())['produced_total'], 100)

    def test_no_remaining_declared_counts_as_zero(self):
        sid = self.declare_sacs()
        self.sell(40)
        self.close(sid, [])
        c = self.cat(self.by_date())
        self.assertEqual((c['remaining_qty'], c['produced_total']), (0, 40))

    def test_yesterday_remaining_removed_from_produced_r1(self):
        sid = self.declare_sacs()
        conf = DailyOpeningConfirmation.objects.create(node=self.node, team='A', date=self.today, confirmed_by=self.gerant)
        DailyOpeningConfirmationLine.objects.create(confirmation=conf, bread_price=self.bp, qty_confirmed=20)
        self.sell(100)
        self.close(sid, [(self.bp, 10)])
        # 100 vendus + 10 restes - 20 d'hier = 90
        self.assertEqual(self.cat(self.by_date())['produced_total'], 90)

    def test_disposals_added_r5(self):
        sid = self.declare_sacs()
        self.sell(100)
        s = ProductionSession.objects.get(pk=sid)
        for t, q in (('UNSOLD', 5), ('DECLASSED', 3), ('FREE_DIST', 2), ('SOLD_DISCOUNT', 4)):
            BreadDisposal.objects.create(
                session=s, bread_price=self.bp, disposal_type=t, quantity=q,
                node=self.node, node_origin='K1',
            )
        self.close(sid, [(self.bp, 10)])
        self.assertEqual(self.cat(self.by_date())['produced_total'], 100 + 10 + 14)

    def test_transfers_sent_counted_received_not_r2(self):
        other = make_node(code='K2')
        sid = self.declare_sacs()
        self.sell(100)
        out = BreadTransfer.objects.create(
            from_node=self.node, to_node=other, transfer_status='CONFIRMED', initiated_by=self.gerant,
        )
        BreadTransferLine.objects.create(transfer=out, bread_price=self.bp, quantity_sent=8, quantity_received=8)
        inc = BreadTransfer.objects.create(
            from_node=other, to_node=self.node, transfer_status='CONFIRMED', initiated_by=self.gerant,
        )
        BreadTransferLine.objects.create(transfer=inc, bread_price=self.bp, quantity_sent=6, quantity_received=6)
        self.close(sid, [(self.bp, 10)])
        # 100 + 10 + 8 envoyés - 6 reçus
        self.assertEqual(self.cat(self.by_date())['produced_total'], 112)

    def test_daily_closure_report_aligned(self):
        sid = self.declare_sacs()
        self.sell(100)
        rep = self.api.get('/api/production/daily-closure/', {'node': 'K1', 'date': str(self.today)}).data
        c = next(x for x in rep['categories'] if x['bread_price'] == self.bp.pk)
        self.assertEqual(c['vendu_jour']['quantity'], 100)
        self.assertEqual(c['produit']['quantity'], 0)  # pas de production avant clôture
        self.assertTrue(c['produit_derive']['derived'])
        self.assertFalse(c['produit_derive']['closed'])
        self.close(sid, [(self.bp, 30)])
        rep = self.api.get('/api/production/daily-closure/', {'node': 'K1', 'date': str(self.today)}).data
        c = next(x for x in rep['categories'] if x['bread_price'] == self.bp.pk)
        self.assertEqual(c['produit']['quantity'], 130)
        self.assertEqual(c['produit']['fc'], '65000.00')
        self.assertTrue(c['produit_derive']['closed'])
        self.assertEqual(rep['totals']['ecart_production_fc'], str(65000 - 420000))

    def test_snapshot_written_for_sold_category_without_remaining(self):
        from production.models import DailyBreadStockSnapshot
        sid = self.declare_sacs()
        self.sell(10, self.bp2)
        self.close(sid, [])
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, bread_price=self.bp2, date=self.today)
        self.assertEqual(snap.qty_at_close, 0)

    def test_classic_session_unchanged(self):
        r = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 300}],
        }, format='json')
        self.assertFalse(r.data['auto_track'])
        self.sell(10)
        self.close(r.data['id'], [(self.bp, 20)])
        c = self.cat(self.by_date())
        self.assertEqual(c['produced_total'], 300)  # lignes DECLARED réellement saisies
        self.assertEqual(c['sold_qty'], 10)


class DataMigrationTests(_Base):
    def test_open_auto_batches_are_reclassified(self):
        s = ProductionSession.objects.create(
            node=self.node, team='A', date=self.today, flour_sacks_used=Decimal('2'), auto_track=True,
            total_fc_produced=50000, yield_gap=-370000, total_breads=100,
        )
        ProductionSessionLine.objects.create(session=s, bread_price=self.bp, quantity=100, source='DECLARED')
        ProductionSessionLine.objects.create(session=s, bread_price=self.bp, quantity=15, source='CARRYOVER')
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_produced=100)
        closed = ProductionSession.objects.create(
            node=self.node, team='B', date=self.today, flour_sacks_used=Decimal('1'), auto_track=True, is_closed=True,
        )
        ProductionSessionLine.objects.create(session=closed, bread_price=self.bp, quantity=9, source='DECLARED')
        mod = importlib.import_module('production.migrations.0026_bug319_reprise_fournees_en_cours')
        mod.reprise_fournees_en_cours(django_apps, None)
        s.refresh_from_db()
        self.assertEqual(s.delivered_value_fc, 50000)
        self.assertEqual((s.total_fc_produced, s.yield_gap, s.total_breads), (0, 0, 15))
        self.assertFalse(s.lines.filter(source='DECLARED').exists())
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_produced, 0)
        self.assertTrue(closed.lines.filter(source='DECLARED').exists())  # clôturée : intacte


class Bug322BoundsBeforeIntTests(_Base):
    def _confirm(self, qty):
        return self.api.post('/api/production/opening-confirmation/', {
            'node': 'K1', 'team': 'A', 'date': str(self.today),
            'lines': [{'bread_price': self.bp.pk, 'qty': qty}],
        }, format='json')

    def test_huge_exponents_refused_fast_everywhere(self):
        import time
        for bad in ('1E+999999', '-1E+999999', '1e+99999999999', '9' * 5000):
            t = time.time()
            r = self._confirm(bad)
            self.assertEqual(r.status_code, 400, (bad[:20], r.data))
            self.assertLess(time.time() - t, 1.0)
        sid = self.declare_sacs()
        for bad in ('1E+999999', '-1E+999999', '9' * 5000):
            t = time.time()
            r = self.api.post(f'/api/production/sessions/{sid}/close/', {
                'remaining': [{'bread_price': self.bp.pk, 'quantity': bad}],
            }, format='json')
            self.assertEqual(r.status_code, 400, (bad[:20], r.data))
            self.assertLess(time.time() - t, 1.0)
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)

    def test_bounds_inclusive(self):
        self.assertEqual(self._confirm('2000000000').status_code, 200)
        self.assertEqual(self._confirm('2000000001').status_code, 400)
        self.assertEqual(self._confirm('-1').status_code, 400)
