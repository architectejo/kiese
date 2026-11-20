"""
BUG-303 / BUG-304 / BUG-306 (remarque.md 2026-11-19, lignes 431-437).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price
from core.workday import work_date_for
from production.models import (
    ProductionSession, ProductionSessionLine, BreadStock, BreadDisposal, DailyBreadStockSnapshot,
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
        self.api = _api(self.gerant)
        self.fapi = _api(self.facturier)
        self.today = work_date_for(self.node)

    def _declare_sacs(self, sacs='2.00', team='A'):
        return self.api.post('/api/production/sessions/', {
            'team': team, 'date': str(self.today), 'flour_sacks_used': sacs,
        }, format='json')

    def _sell_and_deliver(self, qty, who=None):
        r = self.fapi.post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': str(qty * 500),
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        d = (who or self.fapi).post(f"/api/sales/invoices/{r.data['id']}/deliver/")
        self.assertEqual(d.status_code, 200, d.data)


class Bug303NegativeClosureTests(_Base):
    def test_negative_remaining_refused_in_french_and_nothing_applied(self):
        r = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 50}],
        }, format='json')
        sid = r.data['id']
        c = self.api.post(f'/api/production/sessions/{sid}/close/',
                          {'remaining': [{'bread_price': self.bp.pk, 'quantity': -1}]}, format='json')
        self.assertEqual(c.status_code, 400)
        self.assertIn('négative', c.data['detail'])
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)
        ok = self.api.post(f'/api/production/sessions/{sid}/close/',
                           {'remaining': [{'bread_price': self.bp.pk, 'quantity': 0}]}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)


class Bug309FractionalRemainingTests(_Base):
    def test_fractional_or_nonnumeric_remaining_refused_not_truncated(self):
        r = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 50}],
        }, format='json')
        sid = r.data['id']
        for bad in (-0.5, 0.5, '2.5', 'NaN', 'Infinity', True):
            c = self.api.post(f'/api/production/sessions/{sid}/close/',
                              {'remaining': [{'bread_price': self.bp.pk, 'quantity': bad}]}, format='json')
            self.assertEqual(c.status_code, 400, (bad, c.data))
            self.assertIn('detail', c.data)
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)


class Bug306BatchInProgressTests(_Base):
    def test_declare_by_sacs_only_exposes_objective_and_progress(self):
        r = self._declare_sacs('2.00')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['auto_track'])
        self.assertTrue(r.data['is_in_progress'])
        self.assertEqual(r.data['objective_fc'], 420000)
        self.assertEqual(r.data['progress_value_fc'], 0)
        self.assertEqual(r.data['progress_pct'], '0.00')
        self.assertFalse(SystemNotification.objects.filter(title__startswith='Manquant de Rendement').exists())

    def test_delivery_increments_progress_only(self):
        # BUG-319 (changement de spécification voulu, remarque.md l.445) : la
        # livraison ne produit plus de pains (ni lignes DECLARED, ni
        # qty_produced) ; seule la valeur livrée avance la barre.
        sid = self._declare_sacs('2.00').data['id']
        self._sell_and_deliver(100)
        s = ProductionSession.objects.get(pk=sid)
        self.assertFalse(s.lines.filter(source='DECLARED').exists())
        self.assertEqual(s.total_fc_produced, 0)
        self.assertEqual(s.delivered_value_fc, 50000)
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_produced, 0)
        got = self.api.get(f'/api/production/sessions/{sid}/').data
        self.assertEqual(got['progress_value_fc'], 50000)
        self.assertEqual(got['progress_pct'], '11.90')
        self._sell_and_deliver(50, who=_api(make_user('LIVREUR', node=self.node)))
        self.assertEqual(ProductionSession.objects.get(pk=sid).delivered_value_fc, 75000)

    def test_pending_invoice_does_not_increment(self):
        sid = self._declare_sacs().data['id']
        self.fapi.post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': '5000',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 10}],
        }, format='json')
        self.assertFalse(ProductionSession.objects.get(pk=sid).lines.exists())

    def test_sacs_can_be_increased_by_post_and_patch(self):
        sid = self._declare_sacs('2.00').data['id']
        r = self._declare_sacs('1.00')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['id'], sid)
        self.assertEqual(r.data['objective_fc'], 630000)
        p = self.api.patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': '4.00'}, format='json')
        self.assertEqual(p.status_code, 200, p.data)
        self.assertEqual(p.data['objective_fc'], 840000)

    def test_classic_session_is_not_incremented(self):
        r = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 30}],
        }, format='json')
        self.assertFalse(r.data['auto_track'])
        self._sell_and_deliver(10)
        s = ProductionSession.objects.get(pk=r.data['id'])
        self.assertEqual(s.lines.get(bread_price=self.bp).quantity, 30)

    def test_closed_batch_is_not_incremented(self):
        sid = self._declare_sacs().data['id']
        ProductionSession.objects.filter(pk=sid).update(is_closed=True)
        self._sell_and_deliver(10)
        self.assertFalse(ProductionSessionLine.objects.filter(session_id=sid).exists())

    def test_other_node_batch_not_touched(self):
        other = make_node(code='K2', sac_value_fc=Decimal('210000'))
        s = ProductionSession.objects.create(
            node=other, team='A', date=self.today, flour_sacks_used=Decimal('1'), auto_track=True,
        )
        self._sell_and_deliver(10)
        self.assertFalse(s.lines.exists())


class Bug304DayLevelRestesTests(_Base):
    def _closed(self, date, team, remaining):
        s = ProductionSession.objects.create(
            node=self.node, team=team, date=date, flour_sacks_used=Decimal('1'),
        )
        ProductionSessionLine.objects.create(session=s, bread_price=self.bp, quantity=20)
        BreadDisposal.objects.create(
            session=s, bread_price=self.bp, disposal_type='REMAINING', quantity=remaining,
            node=self.node, node_origin='K1',
        )
        DailyBreadStockSnapshot.record_snapshot(s)
        return s

    def _cat(self, date):
        r = self.api.get('/api/production/daily-closure/', {'node': 'K1', 'date': str(date)})
        self.assertEqual(r.status_code, 200, r.data)
        return next(c for c in r.data['categories'] if c['bread_price'] == self.bp.pk), r.data

    def test_reste_hier_and_jour_are_day_level_not_team_level(self):
        yesterday = self.today - timedelta(days=1)
        self._closed(yesterday, 'A', 10)
        self._closed(yesterday, 'B', 5)   # B clôture en dernier : reste de fin de journée
        self._closed(self.today, 'A', 7)
        cat, data = self._cat(self.today)
        self.assertEqual(cat['reste_du_hier_jour'], -5)   # pas -15 (somme des équipes)
        self.assertEqual(cat['reste_du_jour_jour'], 7)
        self.assertEqual(data['totals']['reste_du_hier_jour_fc'], '-2500.00')
        self.assertEqual(data['totals']['reste_du_jour_jour_fc'], '3500.00')
        self.assertIn('A', cat['reste_du_hier'])   # champs par équipe conservés

    def test_no_snapshot_gives_none_and_zero(self):
        cat, _ = self._cat(self.today)
        self.assertEqual(cat['reste_du_hier_jour'], 0)
        self.assertIsNone(cat['reste_du_jour_jour'])
