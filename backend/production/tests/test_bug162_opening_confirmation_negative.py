"""
BUG-162 puis BUG-317 : `POST /api/production/opening-confirmation/`.

BUG-162 (2026-11-10) acceptait les quantités négatives. BUG-317 (remarque.md
l.441 : « Ne plus accepter des négatifs sur Stock de départ de la relève »)
inverse la règle : tout négatif, non entier, NaN/inf, texte, booléen ou valeur
démesurée est refusé en 400 {"detail": ...} ; 0 reste accepté.
Données entièrement fictives.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmation,
    DailyOpeningConfirmationLine, _adjust_bread_stock,
)

DAY = '2026-11-09'
URL = '/api/production/opening-confirmation/'


class OpeningConfirmationNoNegativeTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 B317', unit_price=500)
        self.bp1000 = make_bread_price(category='GRAND', label='Pain 1000 B317', unit_price=1000)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        _adjust_bread_stock(self.node, self.bp500, produced=20)

    def _post(self, lines, team='A'):
        return self.api.post(URL, {'team': team, 'date': DAY, 'lines': lines}, format='json')

    def test_negative_refused_in_french_and_nothing_written(self):
        resp = self._post([
            {'bread_price': self.bp1000.pk, 'qty': 5},
            {'bread_price': self.bp500.pk, 'qty': -7},
        ])
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data['detail'], "Le stock de départ ne peut pas être négatif.")
        self.assertFalse(DailyOpeningConfirmation.objects.exists())
        self.assertFalse(DailyOpeningConfirmationLine.objects.exists())
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_adjusted, 0)
        self.assertEqual(stock.qty_available, 20)

    def test_invalid_values_refused(self):
        for bad in (-1, -0.5, 1.5, '1.5', '-3', 'abc', '', None, True, False,
                    'NaN', 'Infinity', '-Infinity', 'inf', 1e30, 10 ** 12, '99999999999'):
            resp = self._post([{'bread_price': self.bp500.pk, 'qty': bad}])
            self.assertEqual(resp.status_code, 400, (bad, resp.data))
            self.assertIn('detail', resp.data)
        self.assertFalse(DailyOpeningConfirmation.objects.exists())
        self.assertEqual(
            BreadStock.objects.get(node=self.node, bread_price=self.bp500).qty_adjusted, 0)

    def test_zero_and_positive_accepted(self):
        resp = self._post([
            {'bread_price': self.bp500.pk, 'qty': 0},
            {'bread_price': self.bp1000.pk, 'qty': '4'},
        ])
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(DailyOpeningConfirmationLine.objects.get(bread_price=self.bp500).qty_confirmed, 0)
        self.assertEqual(DailyOpeningConfirmationLine.objects.get(bread_price=self.bp1000).qty_confirmed, 4)

    def test_previous_confirmation_untouched_by_refused_resubmission(self):
        self.assertEqual(self._post([{'bread_price': self.bp500.pk, 'qty': 12}]).status_code, 200)
        self.assertEqual(self._post([{'bread_price': self.bp500.pk, 'qty': -2}]).status_code, 400)
        self.assertEqual(DailyOpeningConfirmationLine.objects.get(bread_price=self.bp500).qty_confirmed, 12)

    def test_previous_day_snapshot_untouched(self):
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp500, date=datetime.date(2026, 11, 8),
            team='A', qty_at_close=12,
        )
        self._post([{'bread_price': self.bp500.pk, 'qty': 7}])
        self.assertEqual(
            list(DailyBreadStockSnapshot.objects.values_list('date', 'team', 'qty_at_close')),
            [(datetime.date(2026, 11, 8), 'A', 12)],
        )

    def test_unknown_category_rejected(self):
        resp = self._post([{'bread_price': 999999, 'qty': 1}])
        self.assertEqual(resp.status_code, 400)

    def test_other_write_methods_not_allowed(self):
        for method in (self.api.put, self.api.patch, self.api.delete):
            resp = method(URL, {'lines': [{'bread_price': self.bp500.pk, 'qty': -1}]}, format='json')
            self.assertEqual(resp.status_code, 405)
