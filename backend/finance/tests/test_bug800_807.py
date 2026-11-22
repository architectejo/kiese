"""
Non-régression BUG-800, 801, 802, 803, 806, 807 (audit comptable, cycle test 1, partie C).
Données fictives uniquement. Ces tests échouaient avant les corrections.
"""
import json
from datetime import date, datetime
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

from core.testing import make_client
from finance.models import FinancialYear
from finance.views import _balance_sheet_for_year, _income_statement_for_year
from production.models import ConsumableMovement, ConsumableStock
from sales.models import Invoice
from treasury.models import CashbookEntry
from finance.tests.test_audit_c_cycle1_c import _Base, _api, _dates


class RevenueFixesTests(_Base):
    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.d1 = _dates()[0]
        cls.year = cls.d1.year
        cls.a = make_client(
            cls.k1, credit_limit=D('500000'), last_name='Aa')

    def _rev(self):
        return _income_statement_for_year(self.year)['total_revenue']

    def test_bug801_negative_adjustment_reduces_revenue(self):
        inv = self.sale(self.f1, self.a, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        adj = _api(self.g1).post(f'/api/sales/invoices/{inv}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 2}],
        }, format='json')
        self.assertEqual(adj.status_code, 201, adj.data)
        self.assertEqual(self._rev(), D('4000'))

    def test_bug801_positive_adjustment_increases_revenue(self):
        inv = self.sale(self.f1, self.a, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        adj = _api(self.g1).post(f'/api/sales/invoices/{inv}/adjust/', {
            'adjustment_sign': 1, 'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 2}],
        }, format='json')
        self.assertEqual(adj.status_code, 201, adj.data)
        self.assertEqual(self._rev(), D('6000'))

    def test_bug802_regularisation_is_not_revenue(self):
        self.sale(self.f1, self.a, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        self.assertEqual(Invoice.objects.get(special_code='RG').status, 'DELIVERED')
        self.assertEqual(self._rev(), D('0'))
        self.sale(self.f1, self.a, [(self.bp_grand, 2)], 1000, 'CASH', self.d1)
        self.assertEqual(self._rev(), D('1000'))   # une vente normale reste comptée


class BalanceSheetYearTests(_Base):
    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.year = timezone.localdate().year
        cls.client_a = make_client(
            cls.k1, credit_limit=D('500000'), last_name='Aa')
        prev_day = date(cls.year - 1, 12, 20)
        cls.sale(cls.f1, cls.client_a, [(cls.bp_grand, 4)], 500, 'CREDIT', prev_day)   # BP fin N-1 = 1500
        cls.close_and_push(cls.g1, prev_day, cls._b())
        cls.sale(cls.f1, cls.client_a, [(cls.bp_grand, 2)], 0, 'CREDIT', timezone.localdate())  # BP = 2500

    @classmethod
    def _b(cls):
        from finance.tests.test_audit_c_cycle1_c import _bills
        return _bills(**{'500': 1})

    def test_bug800_past_year_uses_year_end_position(self):
        prev = _balance_sheet_for_year(self.year - 1)
        self.assertEqual(prev['receivables'], D('1500.00'))
        self.assertEqual(prev['cash_position'], D('500'))
        self.assertEqual(prev['total_assets'], D('2000'))
        cur = _balance_sheet_for_year(self.year)
        self.assertEqual(cur['receivables'], D('2500'))

    def test_bug800_empty_year_is_zero(self):
        old = _balance_sheet_for_year(self.year - 2)
        self.assertEqual((old['receivables'], old['cash_position'], old['total_assets']), (D('0'), D('0'), D('0')))

    def test_bug800_cash_ignores_later_entries(self):
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['cash_position'], last.running_balance)


class ConsumableCostTests(_Base):
    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.d1 = _dates()[0]
        cls.year = cls.d1.year

    def test_bug803_exit_keeps_cump_four_decimals(self):
        self.stock_move(self.k1, 'SALT', 'ENTRY', 3000, '1.40', self.d1, 'g')
        self.stock_move(self.k1, 'SALT', 'ENTRY', 1000, '1.55', self.d1, 'g')
        mv = self.stock_move(self.k1, 'SALT', 'EXIT', 4000, 0, self.d1)
        mv.refresh_from_db()
        self.assertEqual(mv.unit_price, D('1.4375'))
        self.assertEqual(ConsumableMovement._meta.get_field('unit_price').decimal_places, 4)
        self.assertEqual(_income_statement_for_year(self.year)['cost_salt'], D('5750.00'))

    def test_bug806_costs_and_results_are_rounded_to_the_cent(self):
        self.stock_move(self.k1, 'FLOUR', 'ENTRY', 10, 4000, self.d1)
        self.stock_move(self.k1, 'FLOUR', 'ENTRY', 19, 4200, self.d1)
        self.stock_move(self.k1, 'FLOUR', 'EXIT', 3, 0, self.d1)   # CUMP 4131,0345 x 3 = 12393,1034
        d = _income_statement_for_year(self.year)
        for key in ('cost_flour', 'gross_profit', 'net_result'):
            self.assertEqual(d[key], d[key].quantize(D('0.01')), key)
        self.assertEqual(d['cost_flour'], D('12393.10'))
        costs = d['cost_flour'] + d['cost_yeast'] + d['cost_salt'] + d['cost_oil']
        self.assertEqual(d['gross_profit'], d['total_revenue'] - costs)


class JsonStringTests(_Base):
    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.year = _dates()[0].year

    def test_bug807_states_render_decimal_strings(self):
        fy, _ = FinancialYear.objects.get_or_create(year=self.year)
        for path in ('income_statement', 'cashflow', 'balance_sheet', 'comparative'):
            r = _api(self.direction).get(f'/api/finance/years/{fy.pk}/{path}/')
            self.assertEqual(r.status_code, 200)
            blob = json.loads(r.content)

            def check(node):
                for key, val in node.items():
                    if isinstance(val, dict):
                        check(val)
                    elif key not in ('year', 'revenue_growth_pct'):
                        self.assertIsInstance(val, str, f'{path}.{key}={val!r}')
                        self.assertEqual(D(val), D(val).quantize(D('0.01')))
            check(blob)
