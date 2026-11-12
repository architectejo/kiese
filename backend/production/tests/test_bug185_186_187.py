"""
BUG-185 / BUG-186 / BUG-187 (dev-backend, 2026-11-11). Données fictives.

- BUG-185 : une RG n'est jamais une vente (même cochée « soldée »).
- BUG-186 : la répartition % par quantité somme à 100 % (production déclarée).
- BUG-187 : `team-assignment` refuse un corps non objet / de mauvais type (400).
"""
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client

CLOSURE = '/api/production/daily-closure/'
ASSIGN = '/api/production/team-assignment/'


class ClosureRgAndRepartitionTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user('GERANT', node=self.node)
        self.facturier = make_user('FACTURIER', node=self.node, team='A')
        self.bp300 = make_bread_price('B185_300', 'Pain 300 B185', 300)
        self.bp500 = make_bread_price('B185_500', 'Pain 500 B185', 500)
        self.cl = make_client(self.node, credit_limit=Decimal('900000.00'))
        self.g = APIClient(); self.g.force_authenticate(self.gerant)
        self.f = APIClient(); self.f.force_authenticate(self.facturier)
        self.today = timezone.localdate()

    def _session(self, team, lines, flour=1):
        r = self.g.post('/api/production/sessions/', {
            'team': team, 'date': str(self.today), 'flour_sacks_used': str(flour),
            'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def _rg(self, qty, **extra):
        p = {'payment_type': 'CASH', 'payment_amount': '0.00', 'special_code': 'RG',
             'client': str(self.cl.pk),
             'lines': [{'bread_price': self.bp300.pk, 'quantity': qty}]}
        p.update(extra)
        r = self.f.post('/api/sales/invoices/', p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        d = self.f.post(f"/api/sales/invoices/{r.data['id']}/deliver/")
        self.assertEqual(d.status_code, 200, d.data)

    def _report(self):
        r = self.g.get(CLOSURE, {'date': str(self.today)})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_rg_soldee_counted_once_at_full_price(self):
        self._session('A', [(self.bp300, 50)])
        self._rg(10, is_soldee=True)
        data = self._report()
        cat = {c['bread_price']: c for c in data['categories']}[self.bp300.pk]
        self.assertEqual(cat['vente_cash_soldee']['quantity'], 0)
        self.assertEqual(cat['vente_cash_soldee']['fc'], '0.00')
        self.assertEqual(cat['regularisation'], {'quantity': 10, 'fc': '3000.00'})
        self.assertEqual(Decimal(data['totals']['total_du_jour_fc']), Decimal('3000.00'))
        self.assertEqual(data['totals']['total_breads_billed'], 10)

    def test_rg_with_commission_exempt_same_as_plain_rg(self):
        self._session('A', [(self.bp300, 50)])
        self._rg(10, commission_exempt=True)
        data = self._report()
        self.assertEqual(Decimal(data['totals']['total_du_jour_fc']), Decimal('3000.00'))

    def test_rg_plain_unchanged(self):
        self._session('A', [(self.bp300, 50)])
        self._rg(10)
        self.assertEqual(Decimal(self._report()['totals']['total_du_jour_fc']), Decimal('3000.00'))

    def test_repartition_sums_to_100_with_carryover(self):
        r = self.g.post('/api/production/opening-confirmation/', {
            'team': 'B', 'date': str(self.today),
            'lines': [{'bread_price': self.bp500.pk, 'qty': 8}],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self._session('A', [(self.bp300, 140), (self.bp500, 50)])
        t = self._report()['totals']
        self.assertEqual(sum(Decimal(x['pct']) for x in t['repartition_pct_par_quantite']),
                         Decimal('100.00'), t['repartition_pct_par_quantite'])
        by = {x['bread_price']: Decimal(x['pct']) for x in t['repartition_pct_par_quantite']}
        self.assertEqual(by[self.bp300.pk], Decimal('73.68'))
        self.assertEqual(by[self.bp500.pk], Decimal('26.32'))

    def test_repartition_without_production_is_zero(self):
        t = self._report()['totals']
        self.assertTrue(all(Decimal(x['pct']) == 0 for x in t['repartition_pct_par_quantite']))


class TeamAssignmentBodyTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.gerant = make_user('GERANT', node=self.node)
        self.api = APIClient(); self.api.force_authenticate(self.gerant)
        self.now = timezone.make_aware(datetime(2026, 11, 11, 13, 0))

    def test_invalid_bodies_return_400_with_detail(self):
        with patch('django.utils.timezone.now', return_value=self.now):
            for body in (['A'], 'A', 3, [], {'team': ['A']}, {'team': 1}, {'team': {}},
                         {'node': {}, 'team': 'A'}, {'node': ['K1'], 'team': 'A'}, {'node': True, 'team': 'A'}):
                r = self.api.post(ASSIGN, body, format='json')
                self.assertEqual(r.status_code, 400, (body, getattr(r, 'data', None)))
                self.assertIn('detail', r.data, body)

    def test_valid_body_still_works(self):
        with patch('django.utils.timezone.now', return_value=self.now):
            r = self.api.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['team'], 'B')
