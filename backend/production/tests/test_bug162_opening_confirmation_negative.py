"""
BUG-162 : `POST /api/production/opening-confirmation/` accepte une quantité
NÉGATIVE (décision client 2026-11-10 : « Enregistre le stock même s'il est
négatif »). Valeurs non entières et catégories inconnues restent refusées.
Données entièrement fictives.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmationLine,
    ProductionSession, ProductionSessionLine, _adjust_bread_stock,
)
from production.views import _build_daily_closure_report

DAY = '2026-11-09'
DAY_DATE = datetime.date(2026, 11, 9)
URL = '/api/production/opening-confirmation/'


class OpeningConfirmationNegativeTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 B162', unit_price=500)
        self.bp1000 = make_bread_price(category='GRAND', label='Pain 1000 B162', unit_price=1000)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        _adjust_bread_stock(self.node, self.bp500, produced=20)

    def _post(self, lines, team='A'):
        return self.api.post(URL, {'team': team, 'date': DAY, 'lines': lines}, format='json')

    def test_negative_quantity_accepted_and_stored_as_is(self):
        resp = self._post([{'bread_price': self.bp500.pk, 'qty': -7}])
        self.assertEqual(resp.status_code, 200, resp.data)
        line = DailyOpeningConfirmationLine.objects.get(bread_price=self.bp500)
        self.assertEqual(line.qty_confirmed, -7)

    def test_qty_adjusted_and_stock_follow_negative_value(self):
        resp = self._post([{'bread_price': self.bp500.pk, 'qty': -7}])
        self.assertEqual(resp.status_code, 200, resp.data)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_adjusted, -27)  # -7 - 20
        self.assertEqual(stock.qty_available, -7)
        self.assertEqual(resp.data['stock_adjustments'], [
            {'bread_price_id': self.bp500.pk, 'before': 20, 'after': -7, 'delta': -27},
        ])
        # Resoumission identique : idempotent, pas de double ajustement.
        self._post([{'bread_price': self.bp500.pk, 'qty': -7}])
        stock.refresh_from_db()
        self.assertEqual(stock.qty_adjusted, -27)

    def test_no_negative_carryover_line_created(self):
        resp = self._post([
            {'bread_price': self.bp500.pk, 'qty': -7},
            {'bread_price': self.bp1000.pk, 'qty': 5},
        ])
        self.assertEqual(resp.status_code, 200, resp.data)
        session = ProductionSession.objects.get(node=self.node, team='A', date=DAY_DATE)
        carry = ProductionSessionLine.objects.filter(
            session=session, source=ProductionSessionLine.Source.CARRYOVER,
        )
        self.assertFalse(carry.filter(quantity__lt=0).exists())
        self.assertFalse(carry.filter(bread_price=self.bp500).exists())
        self.assertEqual(carry.get(bread_price=self.bp1000).quantity, 5)

        # Une ligne CARRYOVER positive préexistante est retirée si la valeur devient négative.
        self._post([{'bread_price': self.bp1000.pk, 'qty': -3}])
        self.assertFalse(ProductionSessionLine.objects.filter(
            session=session, source=ProductionSessionLine.Source.CARRYOVER,
        ).exists())

    def test_closure_report_reste_du_hier_positive_sign_no_double_count(self):
        self._post([{'bread_price': self.bp500.pk, 'qty': -7}])
        report = _build_daily_closure_report(self.node, DAY_DATE)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row['reste_du_hier']['A'], 7)  # convention -qty_confirmed
        self.assertEqual(row['reste_du_hier']['B'], 0)
        # Resoumission : même valeur, pas de cumul.
        self._post([{'bread_price': self.bp500.pk, 'qty': -7}])
        report2 = _build_daily_closure_report(self.node, DAY_DATE)
        row2 = next(c for c in report2['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row2['reste_du_hier']['A'], 7)
        self.assertEqual(row2['facture_mvm_interne'], row['facture_mvm_interne'])

    def test_previous_day_snapshot_untouched(self):
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp500, date=datetime.date(2026, 11, 8),
            team='A', qty_at_close=12,
        )
        self._post([{'bread_price': self.bp500.pk, 'qty': -7}])
        self.assertEqual(
            list(DailyBreadStockSnapshot.objects.values_list('date', 'team', 'qty_at_close')),
            [(datetime.date(2026, 11, 8), 'A', 12)],
        )

    def test_non_integer_quantities_rejected(self):
        for bad in (1.5, '1.5', 'abc', None, True):
            resp = self._post([{'bread_price': self.bp500.pk, 'qty': bad}])
            self.assertEqual(resp.status_code, 400, (bad, resp.data))
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_adjusted, 0)

    def test_unknown_category_rejected(self):
        resp = self._post([{'bread_price': 999999, 'qty': -1}])
        self.assertEqual(resp.status_code, 400)
