"""
Vague 1 « base réelle » — testeur-tresorerie, 2026-11-12.

Non-régression des anomalies trouvées en exécutant le module Trésorerie de bout
en bout sur `backend/db.sqlite3` (boulangerie K3), plus le scénario de journée
complète (2 facturiers x 10 factures -> rapports -> dépenses -> clôture avec
billets -> confirmation -> versement -> solde et chaîne).

Les tests marqués `@expectedFailure` décrivent le comportement ATTENDU (CLAUDE.md
§5.5) et échouent tant que le ticket référencé n'est pas corrigé : le correctif
doit retirer le décorateur. Données entièrement fictives.
"""
import unittest
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import ExpenseCategory
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import (
    CashClosure, CashbookEntry, DailySavings, FacturierReport, JournalEntry,
    LocalExpense,
)


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _deliver(node, fac, team, client, bread, qty, payment_type, payment=None):
    inv = Invoice.objects.create(
        node=node, client=client, facturier=fac, team=team,
        status=Invoice.Status.PENDING, payment_type=payment_type,
        node_origin=node.code, debt_before=Decimal('0.00'),
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    inv.payment_amount = Decimal(payment) if payment is not None else (
        inv.order_total if payment_type == Invoice.PaymentType.CASH else Decimal('0')
    )
    inv.compute_debt_after()
    inv.save()
    inv.deliver(livreur=fac)
    return inv


class FullDayIntegrationTests(TestCase):
    """Journée complète K3 : A et B x 10 factures mixtes -> versement -> chaîne."""

    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_day')
        self.comptable = make_user('COMPTABLE', username='c_day')
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='fa_day')
        self.fb = make_user('FACTURIER', node=self.node, team='B', username='fb_day')
        self.client_obj = make_client(self.node)
        self.b200 = make_bread_price(category='MINI', label='Pain 200 FC', unit_price=200)
        self.b500 = make_bread_price(category='GRAND', label='Pain 500 FC', unit_price=500)
        self.cat = ExpenseCategory.objects.create(code='ZZ_DAY', label='ZZ jour')

    def test_full_day_cash_net_physical_gap_ledger_and_chain(self):
        exp_cash = {'A': Decimal('0'), 'B': Decimal('0')}
        exp_credit = {'A': Decimal('0'), 'B': Decimal('0')}
        for fac, team in ((self.fa, 'A'), (self.fb, 'B')):
            for i in range(10):
                bread = self.b200 if i % 2 == 0 else self.b500
                unit = Decimal(bread.unit_price)
                qty = i + 1
                total = unit * qty
                if i % 3 == 0:  # crédit, paiement partiel
                    pay = Decimal('100')
                    inv = _deliver(self.node, fac, team, self.client_obj, bread, qty, Invoice.PaymentType.CREDIT, pay)
                    exp_credit[team] += total - pay
                else:
                    pay = total
                    inv = _deliver(self.node, fac, team, self.client_obj, bread, qty, Invoice.PaymentType.CASH)
                exp_cash[team] += pay
        api = _api(self.gerant)
        gen = api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(gen.status_code, 200, gen.content)
        for team in ('A', 'B'):
            r = FacturierReport.objects.get(node=self.node, team=team)
            self.assertEqual(r.total_cash_sales, exp_cash[team])
            self.assertEqual(r.total_credit_sales, exp_credit[team])
            self.assertEqual(r.theoretical_cash, exp_cash[team])
        LocalExpense.objects.create(node=self.node, gerant=self.gerant, description='ZZ', amount=Decimal('1234'),
                                    category=self.cat, date=FacturierReport.objects.first().date)
        net = exp_cash['A'] + exp_cash['B'] - Decimal('1234')
        bills = {'bills_20000': 0, 'bills_10000': 0, 'bills_5000': 0, 'bills_1000': 0,
                 'bills_500': 0, 'bills_200': 0, 'bills_100': 0, 'bills_50': 0}
        # billetage proche du net (+50 FC d'excédent), Σ quantité x valeur vérifiée
        remaining = int(net) + 50
        for key, val in (('bills_20000', 20000), ('bills_10000', 10000), ('bills_5000', 5000),
                         ('bills_1000', 1000), ('bills_500', 500), ('bills_200', 200),
                         ('bills_100', 100), ('bills_50', 50)):
            bills[key], remaining = divmod(remaining, val)
        physical = sum(bills[k] * v for k, v in (
            ('bills_20000', 20000), ('bills_10000', 10000), ('bills_5000', 5000), ('bills_1000', 1000),
            ('bills_500', 500), ('bills_200', 200), ('bills_100', 100), ('bills_50', 50)))
        bills['date'] = str(FacturierReport.objects.first().date)
        resp = api.post('/api/treasury/closures/', bills, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        c = resp.json()
        self.assertEqual(Decimal(c['net_cash']), net)
        self.assertEqual(Decimal(c['physical_cash_total']), Decimal(physical))
        self.assertEqual(Decimal(c['cash_gap']), Decimal(physical) - net)
        # double clôture refusée
        self.assertEqual(api.post('/api/treasury/closures/', bills, format='json').status_code, 400)
        # comptable confirme puis verse
        capi = _api(self.comptable)
        self.assertEqual(capi.post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json').status_code, 200)
        push = capi.post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(push.status_code, 201, push.content)
        self.assertEqual(Decimal(push.json()['running_balance']), net)
        self.assertEqual(push.json()['piece_number'], f"VC-K3-{FacturierReport.objects.first().date:%Y%m%d}")
        # double versement refusé
        self.assertEqual(capi.post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json').status_code, 400)
        a = capi.get('/api/treasury/cashbook/integrity_check/').json()
        b = capi.post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        self.assertTrue(a['chain_valid'])
        self.assertTrue(b['all_intact'] if 'all_intact' in b else all(x['is_intact'] for x in b['results']))


class Bug200GerantSelfValidationTests(TestCase):
    """BUG-200 : `CashClosureViewSet.get_permissions` écrase les `permission_classes`
    des actions `validate`/`reject`/`push_to_cashbook` (IsHeadquarters) par `IsGerant`."""

    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_200')
        self.closure = CashClosure.objects.create(
            node=self.node, gerant=self.gerant, date=date(2026, 11, 9),
            total_entries=Decimal('1000'), total_expenses=Decimal('0'), net_cash=Decimal('1000'),
        )

    @unittest.expectedFailure  # BUG-200
    def test_gerant_cannot_validate_own_closure(self):
        r = _api(self.gerant).post(f'/api/treasury/closures/{self.closure.id}/validate/', {}, format='json')
        self.assertEqual(r.status_code, 403, r.content)

    @unittest.expectedFailure  # BUG-200
    def test_gerant_cannot_reject_own_closure(self):
        r = _api(self.gerant).post(f'/api/treasury/closures/{self.closure.id}/reject/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 403, r.content)

    @unittest.expectedFailure  # BUG-200
    def test_gerant_cannot_push_to_cashbook(self):
        CashClosure.objects.filter(pk=self.closure.pk).update(is_validated=True)
        r = _api(self.gerant).post(f'/api/treasury/closures/{self.closure.id}/push_to_cashbook/', {}, format='json')
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(CashbookEntry.objects.count(), 0)


class Bug201OversizedBillsTests(TestCase):
    """BUG-201 : billets démesurés -> 500 après commit d'une ligne illisible."""

    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_201')

    @unittest.expectedFailure  # BUG-201
    def test_oversized_bills_rejected_with_400_and_nothing_persisted(self):
        api = _api(self.gerant)
        api.raise_request_exception = False
        r = api.post('/api/treasury/closures/', {'date': str(date.today()), 'bills_10000': 99999999999}, format='json')
        self.assertEqual(r.status_code, 400, getattr(r, 'content', b'')[:200])
        self.assertEqual(CashClosure.objects.count(), 0)


class Bug202JournalMutabilityTests(TestCase):
    """BUG-202 : Journal de caisse modifiable/supprimable par tout authentifié, montants négatifs."""

    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_202')
        self.fac = make_user('FACTURIER', node=self.node, team='A', username='f_202')
        r = _api(self.gerant).post('/api/treasury/journal/', {
            'date': '2026-11-08', 'imput': 'LIVRAISON', 'label': 'x', 'entry_amount': '1000'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.entry_id = r.json()['id']

    @unittest.expectedFailure  # BUG-202
    def test_facturier_cannot_patch_journal_entry(self):
        r = _api(self.fac).patch(f'/api/treasury/journal/{self.entry_id}/', {'entry_amount': '99999'}, format='json')
        self.assertIn(r.status_code, (403, 405), r.content)

    @unittest.expectedFailure  # BUG-202
    def test_facturier_cannot_delete_journal_entry(self):
        r = _api(self.fac).delete(f'/api/treasury/journal/{self.entry_id}/')
        self.assertIn(r.status_code, (403, 405), r.content)

    @unittest.expectedFailure  # BUG-202
    def test_negative_exit_amount_rejected(self):
        r = _api(self.gerant).post('/api/treasury/journal/', {
            'date': '2026-11-08', 'imput': 'PAY_BLG', 'label': 'neg', 'exit_amount': '-5000'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_running_balance_progressive_baseline(self):
        api = _api(self.gerant)
        r = api.post('/api/treasury/journal/', {
            'date': '2026-11-08', 'imput': 'PAY_BLG', 'label': 'p', 'exit_amount': '400'}, format='json')
        self.assertEqual(Decimal(r.json()['running_balance']), Decimal('600.00'))


class Bug203ReportTamperTests(TestCase):
    """BUG-203 : totaux du rapport facturier (Niveau 1, calculés) modifiables par le gérant, même validé."""

    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_203')
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='f_203')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        _deliver(self.node, self.fa, 'A', self.client_obj, self.bread, 5, Invoice.PaymentType.CASH)
        self.api = _api(self.gerant)
        self.api.post('/api/treasury/reports/generate/', {}, format='json')
        self.report = FacturierReport.objects.get(node=self.node, team='A')

    @unittest.expectedFailure  # BUG-203
    def test_report_totals_are_read_only(self):
        r = self.api.patch(f'/api/treasury/reports/{self.report.id}/', {'total_cash_sales': '5.00'}, format='json')
        self.report.refresh_from_db()
        self.assertEqual(self.report.total_cash_sales, Decimal('1500.00'), r.content)

    @unittest.expectedFailure  # BUG-203
    def test_validated_report_is_frozen_against_patch(self):
        self.api.post(f'/api/treasury/reports/{self.report.id}/validate/')
        r = self.api.patch(f'/api/treasury/reports/{self.report.id}/', {'total_cash_sales': '7.00'}, format='json')
        self.assertIn(r.status_code, (400, 403, 405), r.content)


class Bug204CorrectionPieceNumberTests(TestCase):
    """BUG-204 : n° de pièce de correction (31 caractères) > max_length=30 (PostgreSQL : DataError)."""

    @unittest.expectedFailure  # BUG-204
    def test_correction_piece_number_fits_column(self):
        from treasury.services import record_backdated_correction

        node = make_node(code='K3', name='ATHENEE')
        gerant = make_user('GERANT', node=node, username='g_204')
        fac = make_user('FACTURIER', node=node, team='A', username='f_204')
        closure = CashClosure.objects.create(
            node=node, gerant=gerant, date=date(2026, 11, 9), is_validated=True,
            total_entries=Decimal('100'), net_cash=Decimal('100'))
        inv = _deliver(node, fac, 'A', make_client(node), make_bread_price(category='MINI', label='Pain 200 FC', unit_price=200),
                       1, Invoice.PaymentType.CASH)
        e1 = record_backdated_correction(closure, Decimal('50'), inv, acting_user=gerant)
        e2 = record_backdated_correction(closure, Decimal('20'), inv, acting_user=gerant)
        max_len = CashbookEntry._meta.get_field('piece_number').max_length
        self.assertLessEqual(len(e1.piece_number), max_len, e1.piece_number)
        self.assertNotEqual(e1.piece_number, e2.piece_number)


class Bug205NegativeExpenseTests(TestCase):
    """BUG-205 : dépense locale négative ou nulle acceptée (gonfle la caisse nette)."""

    def setUp(self):
        self.node = make_node(code='K3', name='ATHENEE')
        self.gerant = make_user('GERANT', node=self.node, username='g_205')
        self.cat = ExpenseCategory.objects.create(code='ZZ_205', label='ZZ')

    @unittest.expectedFailure  # BUG-205
    def test_negative_expense_rejected(self):
        r = _api(self.gerant).post('/api/treasury/expenses/', {
            'description': 'neg', 'amount': '-500', 'category': self.cat.id, 'date': '2026-11-09'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    @unittest.expectedFailure  # BUG-205
    def test_zero_expense_rejected(self):
        r = _api(self.gerant).post('/api/treasury/expenses/', {
            'description': 'zero', 'amount': '0', 'category': self.cat.id, 'date': '2026-11-09'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class Bug206SavingsTests(TestCase):
    """BUG-206 : épargne journalière — lecture/écriture inter-nœuds via ?node=, rôles et montants non contrôlés."""

    def setUp(self):
        self.k3 = make_node(code='K3', name='ATHENEE')
        self.k1 = make_node(code='K1', name='TABORA')
        self.g3 = make_user('GERANT', node=self.k3, username='g_206')
        self.livreur = make_user('LIVREUR', node=self.k3, team='', username='l_206')
        self.other = DailySavings.objects.create(
            node=self.k1, date=date(2026, 11, 8), flour_sacks=Decimal('1'),
            daily_revenue=Decimal('1000'), savings_rate=Decimal('0.1'), savings_amount=Decimal('100'))

    @unittest.expectedFailure  # BUG-206
    def test_gerant_cannot_read_other_node_savings_with_node_param(self):
        r = _api(self.g3).get('/api/treasury/savings/', {'node': self.k1.id})
        ids = [x['id'] for x in r.json().get('results', r.json())]
        self.assertNotIn(self.other.id, ids)

    @unittest.expectedFailure  # BUG-206
    def test_gerant_cannot_modify_other_node_savings_with_node_param(self):
        r = _api(self.g3).patch(f'/api/treasury/savings/{self.other.id}/?node={self.k1.id}', {'daily_revenue': '1'}, format='json')
        self.assertIn(r.status_code, (403, 404), r.content)

    @unittest.expectedFailure  # BUG-206
    def test_negative_revenue_or_absurd_rate_rejected(self):
        r = _api(self.g3).post('/api/treasury/savings/', {
            'date': '2026-11-07', 'flour_sacks': 1, 'daily_revenue': '-1000', 'savings_rate': '5'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    @unittest.expectedFailure  # BUG-206
    def test_livreur_cannot_create_savings(self):
        r = _api(self.livreur).post('/api/treasury/savings/', {
            'date': '2026-11-06', 'flour_sacks': 1, 'daily_revenue': '1000', 'savings_rate': '0.1'}, format='json')
        self.assertEqual(r.status_code, 403, r.content)


class Bug207PeriodSummaryFloatTests(TestCase):
    """BUG-207 : `period_summary` renvoie des montants en nombres flottants JSON."""

    @unittest.expectedFailure  # BUG-207
    def test_period_summary_amounts_are_decimal_strings(self):
        from treasury.views import append_cashbook_entry

        node = make_node(code='K3', name='ATHENEE')
        append_cashbook_entry(node=node, date=date(2026, 11, 9), piece_number='VC-K3-20261109', imputation='7000',
                              label='x', entry_amount=Decimal('18400.50'), exit_amount=Decimal('0'), node_origin='K3')
        comptable = make_user('COMPTABLE', username='c_207')
        r = _api(comptable).get('/api/treasury/cashbook/period_summary/',
                                {'date_from': '2026-11-01', 'date_to': '2026-11-30'})
        row = r.json()[0]
        self.assertIsInstance(row['total_entries'], str, row)
