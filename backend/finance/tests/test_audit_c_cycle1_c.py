"""
Audit comptable, cycle test 1, partie C (finance / trésorerie / blockchain) — 2026-11-22.

Un mois d'activité FICTIVE sur 2 boulangeries (jamais `data_kiese/`) est rejoué
par l'API (factures, livraisons, rapports facturier, dépenses locales, clôtures
avec billetage, validation, versement au livre de caisse), plus consommables et
commissions par l'ORM/API, puis les états de `finance/views.py` sont recoupés
avec des chiffres calculés À LA MAIN (voir le bloc « Scénario »).

Les écarts constatés sont portés par des tests `@expectedFailure` (BUG-800 à
BUG-809) qui doivent PASSER quand le code sera corrigé ; les comportements
discutables mais non spécifiés sont verrouillés par des tests de
caractérisation (statut À CLARIFIER, docs/qa/QUESTIONS_CLIENT.md).

Scénario (prix : MINI 300, GRAND 500, PREMIUM 1000 ; CM 25 % ; plafond 500 000) :

  K1  J1  a1 client A 10xGRAND = 5000, cash 5000
          a2 client B 20xMINI  = 6000, verse 2000 -> BP B = 4000
          a3 client C VENTE SOLDE 10xGRAND a 75 % = 3750, verse 3000 (manquant 750)
          cash 10000, dépense 1500, net 8500 (5000+3x1000+500), écart 0
      J2  b1 client B 10xMINI = 3000, verse 7000 -> BP B = 0
          b2 client A  4xGRAND = 2000, verse 0 -> BP A = 2000
          cash 7000, dépense 1000, net 6000, écart 0
      J3  c1 client A 6xMINI = 1800, cash 1800 (BP A reste 2000)
          cash 1800, dépense 500, net 1300 ; compté 1250 -> écart -50
  K2  J1  client E 8xGRAND = 4000 cash ; client F 5xMINI = 1500, verse 500 (BP F = 1000)
          cash 4500, dépense 0, net 4500
      J2  client E 2xPREMIUM = 2000 cash ; dépense 300 ; net 1700

  Chiffre d'affaires : GRAND 10 750 + 4 000 = 14 750 ; MINI 10 800 + 1 500 = 12 300 ;
                       PREMIUM 2 000 ; total 29 050
  Cash 25 300 ; dépenses 3 300 ; net des clôtures 22 000 ; créances 3 000
  Contrôle : CA - cash = 3 750 = créances 3 000 + manquant de la vente soldée 750
  Farine (CUMP, reste de N-1 : 9 sacs a 4000) : K1 +10 a 4000 +10 a 4200 -> CUMP
                  118000/29 = 4068,9655, sortie 3 -> 12 206,8965 ; K2 5 a 4400, sortie 2 -> 8 800 ;
                  SIEGE exclu (BUG-386) ; coût 21 006,8965
  Commissions (mois) : A 8800x25 % = 2200 - dette 2000 = net 200 ; B 9000 -> 2250 ;
                       E 6000 -> 1500 ; F 1500 -> 375 - dette 1000 = -625 (non payable) ;
                       C soldée exclue ; payées : A, B, E = 3 950 ; CM brute totale 6 325
  Résultat : 29 050 - 21 006,8965 - 3 950 - 3 300 = 793,1035
  Livre de caisse : N-1 : 1 600 ; N : 1 600 + 22 000 = 23 600
  N-1 : vente 4xGRAND = 2000 cash, dépense 400, net 1600, farine sortie 1 sac a 4000
"""
import re
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import BreadPrice, Config, ExpenseCategory, Node
from core.testing import make_node, make_user, make_bread_price, make_client
from clients.models import Client
from commissions.models import ClientCommission
from finance.models import FinancialYear
from finance.views import _income_statement_for_year, _balance_sheet_for_year, _cashflow_for_year
from production.models import ConsumableMovement, ConsumableStock
from sales.models import Invoice
from treasury.hashing import verify_cashbook_chain
from treasury.models import CashbookEntry, CashClosure, FacturierReport

MONEY_RE = re.compile(r'^-?\d+(\.\d+)?$')


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _dates():
    """J1..J3 = 10, 11, 12 du mois précédent (même mois, jamais futur, indépendant de l'horloge)."""
    first = timezone.localdate().replace(day=1)
    prev = first - timedelta(days=1)
    return [prev.replace(day=d) for d in (10, 11, 12)]


def _bills(**kw):
    base = {f'bills_{v}': 0 for v in (20000, 10000, 5000, 1000, 500, 200, 100, 50)}
    base.update({f'bills_{k}': n for k, n in kw.items()})
    return base


class _Base(TestCase):
    """Fabriques communes (aucune donnée réelle)."""

    @classmethod
    def _bootstrap(cls):
        cfg = Config.get_instance()
        cfg.allow_backdated_sales = True
        cfg.save(update_fields=['allow_backdated_sales'])
        cls.k1 = make_node(code='AK1', name='Audit K1', sac_value_fc=D('200000'))
        cls.k2 = make_node(code='AK2', name='Audit K2', sac_value_fc=D('200000'))
        cls.bp_mini = make_bread_price('MINI', 'Pain 300 FC', 300)
        cls.bp_grand = make_bread_price('GRAND', 'Pain 500 FC', 500)
        cls.bp_prem = make_bread_price('PREMIUM', 'Pain 1000 FC', 1000)
        cls.cat, _ = ExpenseCategory.objects.get_or_create(code='AUD', defaults={'label': 'Audit'})
        cls.hq = make_user('ADMIN', username='aud_admin')
        cls.direction = make_user('DIRECTION', username='aud_direction')
        cls.comptable = make_user('COMPTABLE', username='aud_comptable')
        cls.g1 = make_user('GERANT', node=cls.k1, username='aud_g1')
        cls.g2 = make_user('GERANT', node=cls.k2, username='aud_g2')
        cls.f1 = make_user('FACTURIER', node=cls.k1, team='A', username='aud_f1')
        cls.f2 = make_user('FACTURIER', node=cls.k2, team='A', username='aud_f2')

    # -- saisie par l'API --------------------------------------------------
    @staticmethod
    def sale(fact_user, client, lines, pay, ptype, day, soldee=False, code=''):
        api = _api(fact_user)
        payload = {
            'client': str(client.pk), 'payment_type': ptype, 'payment_amount': str(pay),
            'special_code': code, 'invoice_date': str(day), 'is_soldee': soldee,
            'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines],
        }
        r = api.post('/api/sales/invoices/', payload, format='json')
        assert r.status_code == 201, r.data
        d = api.post(f"/api/sales/invoices/{r.data['id']}/deliver/", {'delivered_at': str(day)}, format='json')
        assert d.status_code == 200, d.data
        return r.data['id']

    @classmethod
    def expense(cls, gerant, amount, day):
        r = _api(gerant).post('/api/treasury/expenses/', {
            'description': 'Dépense test', 'amount': str(amount), 'category': cls.cat.pk, 'date': str(day),
        }, format='json')
        assert r.status_code == 201, r.data

    @classmethod
    def close_and_push(cls, gerant, day, bills):
        """Rapport facturier -> clôture avec billetage -> confirmation -> versement au livre."""
        g = _api(gerant)
        r = g.post('/api/treasury/reports/generate/', {'date': str(day)}, format='json')
        assert r.status_code == 200, r.data
        c = g.post('/api/treasury/closures/', {'date': str(day), **bills}, format='json')
        assert c.status_code == 201, c.data
        hq = _api(cls.comptable)
        v = hq.post(f"/api/treasury/closures/{c.data['id']}/validate/", {}, format='json')
        assert v.status_code == 200, v.data
        p = hq.post(f"/api/treasury/closures/{c.data['id']}/push_to_cashbook/", {}, format='json')
        assert p.status_code == 201, p.data
        return c.data

    @staticmethod
    def stock_move(node, ctype, mtype, qty, price, when, unit=''):
        st, _ = ConsumableStock.objects.get_or_create(node=node, consumable_type=ctype, defaults={'unit': unit})
        mv = ConsumableMovement.objects.create(node=node, stock=st, movement_type=mtype,
                                               quantity=D(str(qty)), unit_price=D(str(price)))
        ts = timezone.make_aware(datetime(when.year, when.month, when.day, 8, 0, 0))
        ConsumableMovement.objects.filter(pk=mv.pk).update(created_at=ts)
        return mv

    def fin(self, path, user=None, year=None):
        year = year or self.year
        fy, _ = FinancialYear.objects.get_or_create(year=year)
        r = _api(user or self.direction).get(f'/api/finance/years/{fy.pk}/{path}/')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r.content))
        return r.data

    def fin_json(self, path, year=None):
        """Corps JSON réellement transmis (les Decimal sont rendus en chaînes)."""
        import json
        fy, _ = FinancialYear.objects.get_or_create(year=year or self.year)
        r = _api(self.direction).get(f'/api/finance/years/{fy.pk}/{path}/')
        return json.loads(r.content)


class MonthScenarioTests(_Base):
    """Un mois fictif complet, recoupé à la main (voir docstring du module)."""

    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        d1, d2, d3 = _dates()
        cls.d1, cls.d2, cls.d3 = d1, d2, d3
        cls.year = d1.year
        prev_day = date(cls.year - 1, 12, 20)

        a, b, c = (make_client(cls.k1, credit_limit=D('500000'), last_name=n) for n in ('Aa', 'Bb', 'Cc'))
        e, f = (make_client(cls.k2, credit_limit=D('500000'), last_name=n) for n in ('Ee', 'Ff'))
        cls.client_ids = {'A': a.pk, 'B': b.pk, 'C': c.pk, 'E': e.pk, 'F': f.pk}

        # --- exercice N-1 (saisi en premier : chaîne du livre dans l'ordre chronologique)
        cls.sale(cls.f1, a, [(cls.bp_grand, 4)], 2000, 'CASH', prev_day)
        cls.expense(cls.g1, 400, prev_day)
        cls.stock_move(cls.k1, 'FLOUR', 'ENTRY', 10, 4000, prev_day)
        cls.stock_move(cls.k1, 'FLOUR', 'EXIT', 1, 0, prev_day)
        cls.close_and_push(cls.g1, prev_day, _bills(**{'1000': 1, '500': 1, '100': 1}))

        # --- exercice N, K1
        cls.sale(cls.f1, a, [(cls.bp_grand, 10)], 5000, 'CASH', d1)
        cls.sale(cls.f1, b, [(cls.bp_mini, 20)], 2000, 'CREDIT', d1)
        cls.sale(cls.f1, c, [(cls.bp_grand, 10)], 3000, 'CASH', d1, soldee=True)
        cls.expense(cls.g1, 1500, d1)
        cls.close_and_push(cls.g1, d1, _bills(**{'5000': 1, '1000': 3, '500': 1}))
        cls.sale(cls.f1, b, [(cls.bp_mini, 10)], 7000, 'CASH', d2)
        cls.sale(cls.f1, a, [(cls.bp_grand, 4)], 0, 'CREDIT', d2)
        cls.expense(cls.g1, 1000, d2)
        cls.close_and_push(cls.g1, d2, _bills(**{'5000': 1, '1000': 1}))
        cls.sale(cls.f1, a, [(cls.bp_mini, 6)], 1800, 'CASH', d3)
        cls.expense(cls.g1, 500, d3)
        cls.close_and_push(cls.g1, d3, _bills(**{'1000': 1, '200': 1, '50': 1}))  # 1250 : écart -50
        # --- exercice N, K2
        cls.sale(cls.f2, e, [(cls.bp_grand, 8)], 4000, 'CASH', d1)
        cls.sale(cls.f2, f, [(cls.bp_mini, 5)], 500, 'CREDIT', d1)
        cls.close_and_push(cls.g2, d1, _bills(**{'1000': 4, '500': 1}))
        cls.sale(cls.f2, e, [(cls.bp_prem, 2)], 2000, 'CASH', d2)
        cls.expense(cls.g2, 300, d2)
        cls.close_and_push(cls.g2, d2, _bills(**{'1000': 1, '200': 3, '100': 1}))

        # --- consommables (farine) : CUMP 4100 puis sorties
        siege, _ = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siège'})
        cls.stock_move(cls.k1, 'FLOUR', 'ENTRY', 10, 4000, d1)
        cls.stock_move(cls.k1, 'FLOUR', 'ENTRY', 10, 4200, d1)
        cls.stock_move(cls.k1, 'FLOUR', 'EXIT', 3, 0, d2)
        cls.stock_move(cls.k2, 'FLOUR', 'ENTRY', 5, 4400, d1)
        cls.stock_move(cls.k2, 'FLOUR', 'EXIT', 2, 0, d2)
        cls.stock_move(siege, 'FLOUR', 'ENTRY', 5, 4000, d1)
        cls.stock_move(siege, 'FLOUR', 'EXIT', 1, 0, d2)  # transfert interne : hors coût

        # --- commissions du mois puis paiement de A, B, E
        hq = _api(cls.direction)
        for node in (cls.k1, cls.k2):
            r = hq.post('/api/commissions/periods/generate/',
                        {'node': node.pk, 'month': d1.month, 'year': d1.year}, format='json')
            assert r.status_code == 201, r.data
        for last in ('Aa', 'Bb', 'Ee'):
            cm = ClientCommission.objects.get(client__last_name=last, period__year=d1.year)
            assert hq.post(f'/api/commissions/commissions/{cm.pk}/mark_paid/', {}, format='json').status_code == 200

    def setUp(self):
        self.year = self.d1.year

    # ---------------------------------------------------------------- ventes
    def test_01_client_balances_hand_computed(self):
        debts = {k: Client.objects.get(pk=v).current_debt for k, v in self.client_ids.items()}
        self.assertEqual(debts, {'A': D('2000'), 'B': D('0'), 'C': D('0'), 'E': D('0'), 'F': D('1000')})

    def test_02_revenue_by_category_and_total(self):
        d = self.fin('income_statement')
        self.assertEqual(D(d['revenue_500']), D('14750'))   # GRAND (vente soldée a 75 % incluse)
        self.assertEqual(D(d['revenue_300']), D('12300'))   # MINI
        self.assertEqual(D(d['revenue_1000']), D('2000'))   # PREMIUM
        self.assertEqual(D(d['revenue_400']), D('0'))
        self.assertEqual(D(d['total_revenue']), D('29050'))

    def test_03_cogs_is_real_consumption_at_cump_and_excludes_siege(self):
        d = self.fin('income_statement')
        self.assertEqual(D(d['cost_flour']), D('21006.90'))
        self.assertEqual(D(d['cost_yeast']) + D(d['cost_salt']) + D(d['cost_oil']), D('0'))
        self.assertEqual(D(d['gross_profit']), D('29050') - D('21006.90'))

    def test_04_expenses_and_net_result_chain(self):
        d = self.fin('income_statement')
        self.assertEqual(D(d['operational_expenses']), D('3300'))
        self.assertEqual(D(d['commissions_paid']), D('3950'))
        self.assertEqual(D(d['net_result']), D('793.10'))
        # cohérence interne : résultat = CA - coûts matière - commissions - dépenses
        costs = sum(D(d[k]) for k in ('cost_flour', 'cost_yeast', 'cost_salt', 'cost_oil'))
        self.assertEqual(D(d['net_result']), D(d['total_revenue']) - costs - D(d['commissions_paid']) - D(d['operational_expenses']))
        self.assertEqual(D(d['total_revenue']), sum(D(d[k]) for k in ('revenue_300', 'revenue_400', 'revenue_500', 'revenue_1000')))

    def test_05_commission_amounts_hand_computed(self):
        cm = {c.client.last_name: c for c in ClientCommission.objects.filter(period__year=self.year)}
        self.assertEqual(set(cm), {'Aa', 'Bb', 'Ee', 'Ff'})  # C (vente soldée) exclue
        self.assertEqual((cm['Aa'].order_value, cm['Aa'].commission_gross, cm['Aa'].net_payable), (D('8800'), D('2200'), D('200')))
        self.assertEqual((cm['Bb'].order_value, cm['Bb'].commission_gross, cm['Bb'].net_payable), (D('9000'), D('2250'), D('2250')))
        self.assertEqual((cm['Ee'].order_value, cm['Ee'].commission_gross, cm['Ee'].net_payable), (D('6000'), D('1500'), D('1500')))
        self.assertEqual((cm['Ff'].order_value, cm['Ff'].commission_gross, cm['Ff'].net_payable), (D('1500'), D('375'), D('-625')))
        self.assertEqual(sum(c.commission_gross for c in cm.values()), D('6325'))

    # ------------------------------------------------------------- trésorerie
    def test_06_facturier_reports_cash_and_credit(self):
        k1 = FacturierReport.objects.filter(node=self.k1, date__year=self.year)
        k2 = FacturierReport.objects.filter(node=self.k2, date__year=self.year)
        self.assertEqual(sum(r.total_cash_sales for r in k1), D('18800'))
        self.assertEqual(sum(r.total_cash_sales for r in k2), D('6500'))
        # crédit : a2 4000 + b2 2000 + F 1000 ; la vente soldée n'est jamais un crédit
        self.assertEqual(sum(r.total_credit_sales for r in k1) + sum(r.total_credit_sales for r in k2), D('7000'))

    def test_07_closures_net_cash_and_gap_journalised(self):
        closures = CashClosure.objects.filter(date__year=self.year)
        nets = {(c.node.code, c.date): c.net_cash for c in closures}
        self.assertEqual(nets, {
            ('AK1', self.d1): D('8500'), ('AK1', self.d2): D('6000'), ('AK1', self.d3): D('1300'),
            ('AK2', self.d1): D('4500'), ('AK2', self.d2): D('1700'),
        })
        self.assertEqual(sum(c.net_cash for c in closures), D('22000'))
        gaps = {(c.node.code, c.date): c.cash_gap for c in closures if c.cash_gap != 0}
        self.assertEqual(gaps, {('AK1', self.d3): D('-50')})
        self.assertEqual(sum(c.physical_cash_total for c in closures), D('21950'))

    def test_08_cashbook_equals_sum_of_closures_and_chain_is_valid(self):
        entries = list(CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()))[::-1]
        self.assertEqual(len(entries), 6)  # 1 (N-1) + 5 (N)
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(last.running_balance, D('23600'))
        in_year = CashbookEntry.objects.filter(date__year=self.year)
        self.assertEqual(sum(e.entry_amount - e.exit_amount for e in in_year), D('22000'))
        # soldes cumulés : chaque ligne = précédente + entrée - sortie
        bal = D('0')
        for e in entries:
            bal += e.entry_amount - e.exit_amount
            self.assertEqual(e.running_balance, bal)
        self.assertTrue(all(ok for _, _, ok in verify_cashbook_chain(entries)))

    def test_09_cashbook_holds_theoretical_cash_not_counted_cash(self):
        """Caractérisation (À CLARIFIER, Q-C1) : le livre reçoit `net_cash` (théorique) ;
        l'écart physique -50 n'y apparaît pas (journalisé seulement sur la clôture)."""
        e = CashbookEntry.objects.get(node=self.k1, date=self.d3)
        self.assertEqual(e.entry_amount, D('1300'))
        self.assertEqual(CashClosure.objects.get(node=self.k1, date=self.d3).physical_cash_total, D('1250'))

    def test_10_cashflow_statement_matches_cashbook(self):
        cf = self.fin('cashflow')
        self.assertEqual(D(cf['total_entries']), D('22000'))
        self.assertEqual(D(cf['total_exits']), D('0'))
        self.assertEqual(D(cf['net_cashflow']), D('22000'))
        self.assertEqual(D(cf['closing_balance']), D('23600'))
        prev = cf['previous_year']
        self.assertEqual((D(prev['total_entries']), D(prev['net_cashflow']), D(prev['closing_balance'])),
                         (D('1600'), D('1600'), D('1600')))
        # variation de trésorerie : clôture N = clôture N-1 + flux net N
        self.assertEqual(D(cf['closing_balance']), D(prev['closing_balance']) + D(cf['net_cashflow']))

    def test_11_revenue_minus_cash_equals_receivables_plus_soldee_shortfall(self):
        d = self.fin('income_statement')
        cash_in = sum(r.total_cash_sales for r in FacturierReport.objects.filter(date__year=self.year))
        receivables = sum(c.current_debt for c in Client.objects.all())
        self.assertEqual(D(d['total_revenue']) - cash_in, receivables + D('750'))
        self.assertEqual(D(d['total_revenue']) - cash_in, D('3750'))

    # ------------------------------------------------------------------ bilan
    def test_12_balance_sheet_current_year(self):
        b = self.fin('balance_sheet')
        self.assertEqual(D(b['receivables']), D('3000'))
        self.assertEqual(D(b['cash_position']), D('23600'))
        self.assertEqual(D(b['total_assets']), D('26600'))
        self.assertEqual(set(b) - {'previous_year'}, {'year', 'receivables', 'cash_position', 'total_assets'})

    def test_13_BUG_800_balance_sheet_previous_year_is_isolated(self):
        """BUG-800 : le bilan N-1 relit la caisse et les créances ACTUELLES."""
        b = self.fin('balance_sheet')
        prev = b['previous_year']
        self.assertEqual(D(prev['cash_position']), D('1600'))   # solde du livre au 31/12/N-1
        self.assertEqual(D(prev['receivables']), D('0'))        # aucune dette client fin N-1
        self.assertEqual(D(prev['total_assets']), D('1600'))

    def test_14_BUG_800_balance_sheet_empty_year_is_zero(self):
        """BUG-800 : un exercice sans aucune donnée (N-2 ici) doit donner un bilan nul."""
        b = self.fin('balance_sheet', year=self.year - 1)
        prev = b['previous_year']       # N-2 : aucune écriture ni vente
        self.assertEqual(D(prev['cash_position']), D('0'))
        self.assertEqual(D(prev['total_assets']), D('0'))

    # ------------------------------------------------------- exercice N-1 / vide
    def test_15_previous_year_income_statement_isolated(self):
        d = self.fin('income_statement')
        p = d['previous_year']
        self.assertEqual(D(p['revenue_500']), D('2000'))
        self.assertEqual(D(p['total_revenue']), D('2000'))
        self.assertEqual(D(p['operational_expenses']), D('400'))
        self.assertEqual(D(p['cost_flour']), D('4000'))
        self.assertEqual(D(p['commissions_paid']), D('0'))
        self.assertEqual(D(p['net_result']), D('2000') - D('4000') - D('400'))
        # croissance : (29050 - 2000) / 2000 x 100
        self.assertEqual(d['revenue_growth_pct'], 1352.5)

    def test_16_empty_previous_year_is_zero_not_error(self):
        d = self.fin('income_statement', year=self.year - 1)   # N-2 vide
        p = d['previous_year']
        self.assertTrue(all(D(str(v)) == 0 for k, v in p.items() if k != 'year'))
        self.assertIsNone(d['revenue_growth_pct'])
        cf = self.fin('cashflow', year=self.year - 1)['previous_year']
        self.assertEqual((D(cf['total_entries']), D(cf['net_cashflow']), D(cf['closing_balance'])), (D(0), D(0), D(0)))

    def test_17_comparative_equals_individual_endpoints(self):
        comp = self.fin('comparative')
        ind = self.fin('income_statement')
        prev = ind.pop('previous_year'); ind.pop('revenue_growth_pct')
        self.assertEqual(comp['income_statement'], ind)
        self.assertEqual(comp['income_statement_prev'], prev)
        cf = self.fin('cashflow')
        self.assertEqual(comp['cashflow']['closing_balance'], cf['closing_balance'])
        self.assertEqual(comp['cashflow_prev'], cf['previous_year'])

    # ----------------------------------------------------------------- Decimal
    def test_18_money_in_json_is_exact_to_four_decimals(self):
        for blob in (self.fin_json('income_statement'), self.fin_json('cashflow'), self.fin_json('balance_sheet')):
            for key, val in blob.items():
                if key in ('previous_year', 'year', 'revenue_growth_pct'):
                    continue
                dec = D(str(val))
                self.assertEqual(dec, dec.quantize(D('0.0001')), f'{key}={val}')

    def test_18a_BUG_807_money_in_json_is_a_string_not_a_float(self):
        """BUG-807 : les 3 états sont des `dict` de Decimal rendus par l'encodeur DRF en nombres JSON
        (float) : `12300.0`, contrairement a `summary` (chaînes) et au contrat « argent = Decimal »."""
        for blob in (self.fin_json('income_statement'), self.fin_json('cashflow'), self.fin_json('balance_sheet')):
            for key, val in blob.items():
                if key in ('previous_year', 'year', 'revenue_growth_pct'):
                    continue
                self.assertIsInstance(val, str, f'{key}={val!r}')

    def test_18b_BUG_806_income_statement_amounts_are_rounded_to_the_franc_cent(self):
        """BUG-806 : coût matière / résultat renvoyés avec 4 décimales (CUMP x quantité) sans `quantize`
        (CLAUDE.md §4) : 21006.8965 et 793.1035 FC ; la somme des lignes arrondies à 2 décimales
        ne retombe plus sur le total affiché."""
        d = self.fin_json('income_statement')
        for key in ('cost_flour', 'gross_profit', 'net_result'):
            self.assertEqual(D(d[key]), D(d[key]).quantize(D('0.01')), f'{key}={d[key]}')

    # ---------------------------------------------------- isolation des gérants
    def test_19_manager_and_staff_cannot_read_consolidated_statements(self):
        fy, _ = FinancialYear.objects.get_or_create(year=self.year)
        for user in (self.g1, self.g2, self.f1):
            api = _api(user)
            for path in ('income_statement', 'cashflow', 'balance_sheet', 'comparative'):
                r = api.get(f'/api/finance/years/{fy.pk}/{path}/')
                self.assertEqual(r.status_code, 403, (user.role, path))
                r = api.get(f'/api/finance/years/{fy.pk}/{path}/?node={self.k2.pk}')
                self.assertEqual(r.status_code, 403, (user.role, path, 'node'))
            self.assertEqual(api.get('/api/finance/years/').status_code, 403)
            self.assertEqual(api.get(f'/api/treasury/cashbook/').status_code, 403)

    def test_20_manager_sees_only_own_bakery_in_treasury_and_commissions(self):
        g1 = _api(self.g1)
        closures = g1.get('/api/treasury/closures/').data
        rows = closures['results'] if isinstance(closures, dict) else closures
        self.assertEqual({r['node'] for r in rows}, {self.k1.pk})
        self.assertEqual(len(rows), 4)  # 3 en N + 1 en N-1
        exp = g1.get('/api/treasury/expenses/').data
        exp = exp['results'] if isinstance(exp, dict) else exp
        self.assertEqual({e['node'] for e in exp}, {self.k1.pk})
        self.assertEqual(sum(D(e['amount']) for e in exp), D('3400'))  # 1500+1000+500+400
        # `?node=` forgé vers K2 : aucune donnée K2
        forged = g1.get(f'/api/treasury/closures/?node={self.k2.pk}')
        data = forged.data['results'] if isinstance(forged.data, dict) else forged.data
        self.assertTrue(all(r['node'] == self.k1.pk for r in data))
        comm = g1.get('/api/commissions/commissions/').data
        comm = comm['results'] if isinstance(comm, dict) else comm
        self.assertEqual(len(comm), 2)  # K1 : A et B (C = vente soldée, exclue) ; rien de K2


class RevenueRulesTests(_Base):
    """Règles de reconnaissance du chiffre d'affaires hors scénario principal."""

    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.d1 = _dates()[0]
        cls.year = cls.d1.year
        cls.a = make_client(cls.k1, credit_limit=D('500000'), last_name='Aa')

    def setUp(self):
        self.year = self.d1.year

    def _rev(self):
        return _income_statement_for_year(self.year)['total_revenue']

    def test_negative_adjustment_reduces_revenue_BUG_801(self):
        """BUG-801 : une facture d'ajustement (sign -1) porte des lignes POSITIVES ; le CA les additionne."""
        inv = self.sale(self.f1, self.a, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.assertEqual(self._rev(), D('5000'))
        adj = _api(self.g1).post(f'/api/sales/invoices/{inv}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 2}],
        }, format='json')
        self.assertEqual(adj.status_code, 201, adj.data)
        self.assertEqual(self._rev(), D('4000'))   # 5000 - 2 x 500

    def test_regularisation_is_not_revenue_BUG_802(self):
        """BUG-802 : une RG n'est pas une vente (BUG-178, CLAUDE.md §5.1) ; exclue du cash, comptée au CA."""
        self.sale(self.f1, self.a, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        inv = Invoice.objects.get(special_code='RG')
        self.assertEqual(inv.status, 'DELIVERED')
        self.assertEqual(self._rev(), D('0'))

    def test_cash_sale_not_yet_banked_is_in_revenue_but_in_no_asset_BUG_809(self):
        """Caractérisation (À CLARIFIER, BUG-809) : le bilan ne lit que le livre direction ; l'espèces d'une
        vente livrée, tant que la clôture n'est pas versée, n'est ni caisse ni créance."""
        self.sale(self.f1, self.a, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.assertEqual(self._rev(), D('5000'))
        b = _balance_sheet_for_year(self.year)
        self.assertEqual((b['cash_position'], b['receivables'], b['total_assets']), (D('0'), D('0'), D('0')))

    def test_refund_without_lines_is_not_revenue(self):
        self.sale(self.f1, self.a, [(self.bp_grand, 10)], 0, 'CREDIT', self.d1)
        before = self._rev()
        r = _api(self.f1).post('/api/sales/invoices/', {
            'client': str(self.a.pk), 'payment_type': 'CASH', 'payment_amount': '1000',
            'invoice_date': str(self.d1), 'is_debt_repayment': True, 'lines': [],
        }, format='json')
        self.assertIn(r.status_code, (201, 400), r.data)
        self.assertEqual(self._rev(), before)

    def test_pending_and_cancelled_invoices_not_revenue(self):
        api = _api(self.f1)
        r = api.post('/api/sales/invoices/', {
            'client': str(self.a.pk), 'payment_type': 'CREDIT', 'payment_amount': '0', 'invoice_date': str(self.d1),
            'lines': [{'bread_price': self.bp_grand.pk, 'quantity': 3}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self._rev(), D('0'))
        api2 = _api(self.g1)
        self.assertEqual(api2.post(f"/api/sales/invoices/{r.data['id']}/cancel/", {}, format='json').status_code, 200)
        self.assertEqual(self._rev(), D('0'))


class ConsumableValuationTests(_Base):
    """Valorisation du coût matière (CUMP) sans arrondi parasite."""

    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.d1 = _dates()[0]
        cls.year = cls.d1.year

    def test_flour_cump_exact_when_prices_are_round(self):
        self.stock_move(self.k1, 'FLOUR', 'ENTRY', 10, 4000, self.d1)
        self.stock_move(self.k1, 'FLOUR', 'ENTRY', 10, 4200, self.d1)
        self.stock_move(self.k1, 'FLOUR', 'EXIT', '2.5', 0, self.d1)
        self.assertEqual(_income_statement_for_year(self.year)['cost_flour'], D('10250.0000'))

    def test_salt_cump_computed_on_four_decimals(self):
        self.stock_move(self.k1, 'SALT', 'ENTRY', 3000, '1.40', self.d1, 'g')
        self.stock_move(self.k1, 'SALT', 'ENTRY', 1000, '1.55', self.d1, 'g')
        self.assertEqual(ConsumableStock.objects.get(node=self.k1, consumable_type='SALT').average_unit_cost, D('1.4375'))

    def test_exit_unit_price_column_keeps_the_cump_precision_BUG_803(self):
        """BUG-803 : le CUMP (4 décimales) est figé dans `ConsumableMovement.unit_price`, colonne a
        2 décimales. SQLite (tests, postes desktop) ne tronque pas, PostgreSQL (cloud) arrondit a
        l'écriture : sel 3000 g a 1,40 + 1000 g a 1,55, CUMP 1,4375, sortie de 4000 g = 5 750 FC
        sur le poste, 5 760 FC sur le cloud (1,44). Les deux moteurs divergent."""
        mv_prec = ConsumableMovement._meta.get_field('unit_price').decimal_places
        cump_prec = ConsumableStock._meta.get_field('average_unit_cost').decimal_places
        self.assertGreaterEqual(mv_prec, cump_prec)


class ReceivablesRulesTests(_Base):
    """Caractérisation du poste « créances » du bilan (À CLARIFIER, BUG-804)."""

    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.year = _dates()[0].year

    def test_inactive_client_debt_is_ignored_in_receivables(self):
        make_client(self.k1, current_debt=D('10000'))
        gone = make_client(self.k1, current_debt=D('7000'))
        Client.objects.filter(pk=gone.pk).update(is_active=False)
        self.assertEqual(_balance_sheet_for_year(self.year)['receivables'], D('10000'))  # 7000 dus, non comptés

    def test_credit_balance_of_savings_client_reduces_receivables(self):
        make_client(self.k1, current_debt=D('10000'))
        make_client(self.k1, current_debt=D('-4000'))   # client épargne : dette de l'ETS envers lui
        self.assertEqual(_balance_sheet_for_year(self.year)['receivables'], D('6000'))  # net, pas de passif


class CommissionAccountingTests(_Base):
    """Caractérisation de la charge « commissions » (À CLARIFIER, BUG-805)."""

    @classmethod
    def setUpTestData(cls):
        cls._bootstrap()
        cls.d1 = _dates()[0]
        cls.year = cls.d1.year
        a = make_client(cls.k1, credit_limit=D('500000'), last_name='Aa', current_debt=D('2000'))
        cls.a = a
        cls.sale(cls.f1, a, [(cls.bp_grand, 10)], 5000, 'CASH', cls.d1)   # BP reste 2000
        hq = _api(cls.direction)
        hq.post('/api/commissions/periods/generate/', {'node': cls.k1.pk, 'month': cls.d1.month, 'year': cls.year}, format='json')
        cls.cm = ClientCommission.objects.get(client=a)

    def test_paid_commission_charge_is_net_after_retenues(self):
        self.assertEqual((self.cm.commission_gross, self.cm.deduction_debt, self.cm.net_payable), (D('1250'), D('2000'), D('-750')))

    def test_charge_recognised_only_when_paid_and_at_net(self):
        # CM 1250, retenue dette 400 -> net 850 payé : le compte de résultat charge 850 (pas 1250)
        ClientCommission.objects.filter(pk=self.cm.pk).update(deduction_debt=D('400'))
        cm = ClientCommission.objects.get(pk=self.cm.pk)
        cm.compute(); cm.save()
        self.assertEqual(cm.net_payable, D('850'))
        self.assertEqual(_income_statement_for_year(self.year)['commissions_paid'], D('0'))   # non payée : aucune charge
        r = _api(self.direction).post(f'/api/commissions/commissions/{cm.pk}/mark_paid/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(_income_statement_for_year(self.year)['commissions_paid'], D('850'))
        # la retenue de dette (400) ne diminue pas la créance client ; le paiement n'écrit pas dans le livre
        self.assertEqual(Client.objects.get(pk=self.a.pk).current_debt, D('2000'))
        self.assertEqual(CashbookEntry.objects.count(), 0)
