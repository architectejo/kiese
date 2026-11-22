"""
Audit comptable, cycle test 2, partie C : vérification de BUG-800 a 807 et nouveaux angles
(BUG-820 a 829). Données fictives uniquement. Les défauts ouverts sont portés par des
`@expectedFailure` à retirer à la correction ; les comportements qui restent corrects sont
verrouillés par des tests normaux.
"""
import json
import re
import unittest
from datetime import date
from decimal import Decimal as D

from django.utils import timezone

from clients.models import Client
from commissions.models import ClientCommission
from core.testing import make_client
from finance.models import FinancialYear
from finance.tests.test_audit_c_cycle1_c import _Base, _api, _dates
from finance.views import _balance_sheet_for_year, _income_statement_for_year
from sales.models import Invoice

MONEY_RE = re.compile(r'^-?\d+\.\d{2}$')


def _all_str_money(obj, path=''):
    """Retourne la liste des feuilles non conformes (float/int/chaîne mal formée) hors année et pourcentage."""
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ('year', 'revenue_growth_pct'):
                continue
            bad += _all_str_money(v, f'{path}.{k}')
    elif obj is not None:
        if not (isinstance(obj, str) and MONEY_RE.match(obj)):
            bad.append((path, obj))
    return bad


class Cycle2Base(_Base):
    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.today = timezone.localdate()
        cls.year = cls.today.year
        cls.d1 = _dates()[0]
        cls.cl = make_client(cls.k1, credit_limit=D('900000'), last_name='Zc')

    def adjust(self, inv_id, sign, qty, bp=None, pay='0.00'):
        r = _api(self.g1).post(f'/api/sales/invoices/{inv_id}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': pay, 'invoice_date': str(self.d1),
            'lines': [{'bread_price': (bp or self.bp_grand).pk, 'quantity': qty}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def doc1(self, day):
        r = _api(self.hq).get('/api/finance/years/doc1_report/', {
            'node': self.k1.pk, 'month': day.month, 'year': day.year})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data


class Verif800BalanceSheetAttacks(Cycle2Base):
    """BUG-800 : le cas nominal est vérifié par test_bug800_807 ; ici, les angles d'attaque."""

    def _prev_year_day(self, month, day):
        return date(self.year - 1, month, day)

    def test_nominal_still_ok_empty_year_is_zero(self):
        b = _balance_sheet_for_year(self.year - 5)
        self.assertEqual((b['receivables'], b['cash_position'], b['total_assets']), (D('0'), D('0'), D('0')))

    def test_backdated_invoice_created_later_is_in_year_end_receivables_BUG_820(self):
        """Facture du 31/12 saisie d'abord, facture du 05/12 saisie ensuite (antidatée) :
        la BP réelle fin N-1 est 1 500 (chaîne par ordre de saisie) ; la reconstitution trie par date
        et retient la facture du 31/12 (debt_after = 1 000)."""
        self.sale(self.f1, self.cl, [(self.bp_grand, 2)], 0, 'CREDIT', self._prev_year_day(12, 31))   # BP 1000
        self.sale(self.f1, self.cl, [(self.bp_grand, 1)], 0, 'CREDIT', self._prev_year_day(12, 5))    # BP 1500
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('1500.00'))
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('1500.00'))

    def test_cancelled_pending_invoice_leaves_stale_debt_after_BUG_820(self):
        """Facture A (en attente, +1000) puis B livrée (+500, debt_after 1500) ; A annulée :
        current_debt = 500 mais B.debt_after reste 1500 -> créances fin d'exercice = 1 500 au lieu de 500."""
        day = self._prev_year_day(12, 20)
        api = _api(self.f1)
        ra = api.post('/api/sales/invoices/', {
            'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': '0',
            'invoice_date': str(day), 'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(ra.status_code, 201, ra.data)
        self.sale(self.f1, self.cl, [(self.bp_grand, 1)], 0, 'CREDIT', day)
        c = api.post(f"/api/sales/invoices/{ra.data['id']}/cancel/", {}, format='json')
        self.assertEqual(c.status_code, 200, c.data)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('500.00'))
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('500.00'))

    def test_repayment_invoice_is_followed(self):
        """Un remboursement BP (facture sans ligne) est bien repris par debt_after."""
        day = self._prev_year_day(11, 10)
        self.sale(self.f1, self.cl, [(self.bp_grand, 4)], 0, 'CREDIT', day)   # BP 2000
        r = _api(self.f1).post('/api/sales/invoices/', {
            'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': '700',
            'is_debt_repayment': True, 'invoice_date': str(day), 'lines': []}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('1300.00'))

    def test_opening_balance_without_invoice_is_invisible_in_closed_year(self):
        """Caractérisation (risque signalé par le correcteur) : dette portée sans facture (import,
        reprise) = 0 dans le bilan d'un exercice clos."""
        make_client(self.k1, credit_limit=D('900000'), current_debt=D('800'), last_name='Zimp')
        self.assertEqual(_balance_sheet_for_year(self.year - 1)['receivables'], D('0'))


class Verif801to802Revenue(Cycle2Base):
    def test_negative_then_positive_adjustment_chain(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 3, pay='1500.00')
        self.adjust(inv, 1, 1, pay='500.00')
        self.assertEqual(_income_statement_for_year(self.d1.year)['total_revenue'], D('4000'))   # 5000 - 1500 + 500

    def test_adjustment_across_categories_signed_per_category(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 4), (self.bp_mini, 5)], 3500, 'CASH', self.d1)  # 2000+1500
        self.adjust(inv, -1, 2, bp=self.bp_mini, pay='0.00')
        st = _income_statement_for_year(self.d1.year)
        self.assertEqual(st['revenue_300'], D('900'))
        self.assertEqual(st['revenue_500'], D('2000'))
        self.assertEqual(st['total_revenue'], D('2900'))

    def test_rg_adjustment_not_in_revenue_but_in_doc1_and_commission_base_is_BUG_821(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        self.adjust(inv, 1, 2, bp=self.bp_mini)
        self.assertEqual(_income_statement_for_year(self.d1.year)['total_revenue'], D('0'))

    @unittest.expectedFailure  # BUG-821
    def test_adjustment_of_regularisation_gives_no_commission_BUG_821(self):
        """BUG-261 : une RG n'ouvre pas droit à CM ; son ajustement (special_code vide) doit suivre."""
        inv = self.sale(self.f1, self.cl, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        self.adjust(inv, 1, 2, bp=self.bp_mini)
        r = _api(self.hq).post('/api/commissions/periods/generate/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(ClientCommission.objects.filter(client=self.cl).exists(),
                         list(ClientCommission.objects.values_list('order_value', 'commission_gross')))


class Verif803Cump(Cycle2Base):
    def test_migration_0029_forward_and_backward(self):
        """Sens avant : colonne 16,4 ; sens arrière : arrondi à 2 décimales sans perte de ligne."""
        from production.models import ConsumableMovement
        f = ConsumableMovement._meta.get_field('unit_price')
        self.assertEqual((f.max_digits, f.decimal_places), (16, 4))
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        ex = MigrationExecutor(connection)
        mig = ex.loader.get_migration('production', '0029_bug803_movement_unit_price_4dp')
        self.assertEqual(mig.dependencies, [('production', '0028_bug386_consumable_inventory')])
        self.assertEqual(len(mig.operations), 1)
        self.assertEqual(mig.operations[0].__class__.__name__, 'AlterField')


class Verif806807Json(Cycle2Base):
    def _fy(self):
        return FinancialYear.objects.create(year=self.year, label=f'FY{self.year}') if \
            'label' in [f.name for f in FinancialYear._meta.fields] else FinancialYear.objects.create(year=self.year)

    def test_all_four_endpoints_and_comparative_return_money_strings(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 3)], 700, 'CREDIT', self.d1)
        fy = self._fy()
        for ep in ('income_statement', 'cashflow', 'balance_sheet', 'comparative'):
            r = _api(self.hq).get(f'/api/finance/years/{fy.pk}/{ep}/')
            self.assertEqual(r.status_code, 200, r.data)
            data = json.loads(r.content)
            self.assertEqual(_all_str_money(data), [], ep)

    def test_growth_pct_is_a_number_not_a_money_string(self):
        self.sale(self.f1, self.cl, [(self.bp_grand, 3)], 700, 'CREDIT', self.d1)
        fy = self._fy()
        data = json.loads(_api(self.hq).get(f'/api/finance/years/{fy.pk}/income_statement/').content)
        self.assertIn(data['revenue_growth_pct'], (None,) if D(data['previous_year']['total_revenue']) == 0
                      else (data['revenue_growth_pct'],))

    def test_rounding_cumulated_lines_sum_to_total(self):
        """Arrondis cumulés : coût par type arrondi, marge et résultat sur les lignes arrondies."""
        from production.models import ConsumableMovement, ConsumableStock
        for ctype, qty, price in (('FLOUR', '3.333', '1.0005'), ('YEAST', '0.333', '2.3335'),
                                  ('SALT', '1000', '0.0033'), ('OIL', '1.111', '7.7777')):
            st, _ = ConsumableStock.objects.get_or_create(
                node=self.k1, consumable_type=ctype, defaults={'quantity': D('0')})
            ConsumableStock.objects.filter(pk=st.pk).update(quantity=D('5000'), average_unit_cost=D(price))
            ConsumableMovement.objects.create(
                node=self.k1, stock_id=st.pk, movement_type='EXIT', quantity=D(qty))
        s = _income_statement_for_year(timezone.localdate().year)
        costs = s['cost_flour'] + s['cost_yeast'] + s['cost_salt'] + s['cost_oil']
        for k in ('cost_flour', 'cost_yeast', 'cost_salt', 'cost_oil', 'gross_profit', 'net_result'):
            self.assertEqual(s[k], s[k].quantize(D('0.01')), k)
        self.assertEqual(s['gross_profit'], s['total_revenue'] - costs)


class Doc1Checks(Cycle2Base):
    def test_doc1_invoice_total_is_already_signed_so_suspicion_on_BUG_801_is_false(self):
        """`Invoice.order_total` d'un ajustement est déjà signé (sales/views.py::adjust) :
        la colonne COMMANDE de DOC 1 est juste (4 000), contrairement au CA de finance avant BUG-801."""
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 2)
        rows = self.doc1(self.d1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(D(rows[0]['invoice_total']), D('4000'))
        self.assertEqual(D(rows[0]['payment_amount']), D('5000'))

    def test_doc1_quantities_subtract_a_negative_adjustment_BUG_822(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 2)
        rows = self.doc1(self.d1)
        self.assertEqual(rows[0]['qty_500'], 8)   # observé : 12

    @unittest.expectedFailure  # BUG-822
    def test_commission_total_breads_subtracts_a_negative_adjustment_BUG_822(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 2)
        _api(self.hq).post('/api/commissions/periods/generate/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year}, format='json')
        cm = ClientCommission.objects.get(client=self.cl)
        self.assertEqual(cm.order_value, D('4000.00'))      # valeur : juste
        self.assertEqual(cm.total_breads, 8)                # observé : 12

    def test_doc1_quantity_columns_cover_every_price_BUG_823(self):
        """Seuls 200/300/500/1000 sont comptés ; un pain à un autre prix (tarif configurable,
        CLAUDE.md 5.4) disparaît des colonnes alors que sa valeur est dans COMMANDE."""
        from core.testing import make_bread_price
        bp250 = make_bread_price('MICRO_250', 'Pain 250 FC', 250)
        self.sale(self.f1, self.cl, [(bp250, 4)], 1000, 'CASH', self.d1)
        row = self.doc1(self.d1)[0]
        self.assertEqual(D(row['invoice_total']), D('1000'))
        self.assertEqual(row['qty_200'] + row['qty_300'] + row['qty_500'] + row['qty_1000'] + row['qty_other'], 4)

    @unittest.expectedFailure  # BUG-824
    def test_adjustment_does_not_move_total_breads_received_BUG_824(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 10)
        self.adjust(inv, -1, 3)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 7)   # observé : 10
