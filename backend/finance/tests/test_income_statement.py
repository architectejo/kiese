"""
Tests de cohérence comptable — Compte de Résultat (`_income_statement_for_year`).

Mission auditeur-comptable (2026-10-22) : vérifier que le compte de résultat
calculé par `backend/finance/views.py` retombe bien sur les données saisies
(ventes livrées, approvisionnements consommables, dépenses locales,
commissions payées) et que l'exercice N-1 est correctement isolé.

Toutes les données sont fictives (CLAUDE.md §4 : jamais de données réelles
`data_kiese/` dans les fixtures de test).
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import BreadPrice, ExpenseCategory
from core.testing import make_node, make_client, make_user
from sales.models import Invoice, InvoiceLine
from treasury.models import LocalExpense
from production.models import ConsumableStock, ConsumableMovement
from commissions.models import CommissionPeriod, ClientCommission
from finance.views import _income_statement_for_year


def _current_year():
    return timezone.now().year


class IncomeStatementRevenueTests(TestCase):
    """Chiffre d'affaires = somme des lignes de factures LIVRÉES, par catégorie de pain."""

    def setUp(self):
        self.node = make_node(code='ZK1', name='Zone Test K1')
        self.client = make_client(self.node)
        # NB : la catégorie BreadPrice 'GRAND' est agrégée dans `revenue_500` par
        # `_income_statement_for_year` (MINI->300, MOYEN->400, GRAND->500, PREMIUM->1000).
        self.bp_moyen = BreadPrice.objects.create(category='GRAND', label='Pain 500 FC (test)', unit_price=500, is_active=True)

    def _make_invoice(self, status='DELIVERED', qty=10, unit_price=500):
        inv = Invoice.objects.create(
            node=self.node, client=self.client,
            status=status, order_total=Decimal(qty * unit_price), payment_amount=Decimal('0.00'),
        )
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bp_moyen, quantity=qty, unit_price=unit_price,
                                    line_total=Decimal(qty * unit_price))
        return inv

    def test_revenue_sums_only_delivered_invoices(self):
        self._make_invoice(status='DELIVERED', qty=10, unit_price=500)     # compte : 5 000
        self._make_invoice(status='PENDING', qty=100, unit_price=500)      # ignoré : facture non livrée
        self._make_invoice(status='CANCELLED', qty=100, unit_price=500)    # ignoré : facture annulée

        data = _income_statement_for_year(_current_year())
        self.assertEqual(data['revenue_500'], Decimal('5000'))
        self.assertEqual(data['total_revenue'], Decimal('5000'))

    def test_revenue_split_by_bread_category(self):
        bp_mini = BreadPrice.objects.create(category='MINI', label='Petit pain (test)', unit_price=200, is_active=True)
        self._make_invoice(status='DELIVERED', qty=4, unit_price=500)  # 2 000 en MOYEN
        inv2 = Invoice.objects.create(node=self.node, client=self.client, status='DELIVERED',
                                       order_total=Decimal('600.00'), payment_amount=Decimal('0.00'))
        InvoiceLine.objects.create(invoice=inv2, bread_price=bp_mini, quantity=3, unit_price=200, line_total=Decimal('600.00'))

        data = _income_statement_for_year(_current_year())
        self.assertEqual(data['revenue_300'], Decimal('600'))   # catégorie MINI mappée sur revenue_300
        self.assertEqual(data['revenue_500'], Decimal('2000'))  # catégorie MOYEN mappée sur revenue_500
        self.assertEqual(data['total_revenue'], Decimal('2600'))


class IncomeStatementCostsAndResultTests(TestCase):
    """Coûts matières (consommables achetés), dépenses locales, commissions payées, résultat net."""

    def setUp(self):
        self.node = make_node(code='ZK2', name='Zone Test K2')
        self.client = make_client(self.node)
        self.bp = BreadPrice.objects.create(category='MOYEN', label='Pain 500 FC (test)', unit_price=500, is_active=True)
        self.cat = ExpenseCategory.objects.create(code='TESTCAT', label='Catégorie de test')
        self.gerant = make_user(role='GERANT', node=self.node)

    def test_consumable_entry_cost_is_quantity_times_unit_price(self):
        stock = ConsumableStock.objects.create(node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'), unit='sac')
        ConsumableMovement.objects.create(
            node=self.node, stock=stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('200000.00'),
        )
        data = _income_statement_for_year(_current_year())
        self.assertEqual(data['cost_flour'], Decimal('2000000.00'))  # 10 sacs x 200 000 FC

    def test_local_expense_reduces_net_result(self):
        LocalExpense.objects.create(node=self.node, gerant=self.gerant, description='Test dépense',
                                     amount=Decimal('15000.00'), category=self.cat, date=timezone.now().date())
        data = _income_statement_for_year(_current_year())
        self.assertEqual(data['operational_expenses'], Decimal('15000.00'))
        # Aucun autre produit/charge : résultat net = 0 (CA) - 0 (matières) - 0 (CM) - 15000 (dépenses)
        self.assertEqual(data['net_result'], Decimal('-15000.00'))

    def test_only_paid_commissions_are_deducted_from_net_result(self):
        period = CommissionPeriod.objects.create(node=self.node, month=timezone.now().month, year=timezone.now().year)
        paid = ClientCommission(period=period, client=self.client, order_value=Decimal('100000.00'), commission_rate=Decimal('0.25'))
        paid.compute()
        paid.is_paid = True
        paid.save()
        unpaid = ClientCommission(period=period, client=make_client(self.node), order_value=Decimal('80000.00'), commission_rate=Decimal('0.25'))
        unpaid.compute()
        unpaid.save()  # is_paid=False par défaut

        data = _income_statement_for_year(_current_year())
        # Seule la commission payée (`paid`) doit être comptée comme charge.
        self.assertEqual(data['commissions_paid'], paid.net_payable)
        self.assertNotEqual(data['commissions_paid'], paid.net_payable + unpaid.net_payable)

    def test_net_result_formula_matches_revenue_minus_costs_minus_commissions_minus_expenses(self):
        # Revenu
        inv = Invoice.objects.create(node=self.node, client=self.client, status='DELIVERED',
                                      order_total=Decimal('100000.00'), payment_amount=Decimal('0.00'))
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=200, unit_price=500, line_total=Decimal('100000.00'))
        # Coût matière
        stock = ConsumableStock.objects.create(node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'), unit='sac')
        ConsumableMovement.objects.create(node=self.node, stock=stock, movement_type='ENTRY',
                                           quantity=Decimal('1.000'), unit_price=Decimal('30000.00'))
        # Dépense locale
        LocalExpense.objects.create(node=self.node, gerant=self.gerant, description='Test', amount=Decimal('5000.00'),
                                     category=self.cat, date=timezone.now().date())
        # Commission payée
        period = CommissionPeriod.objects.create(node=self.node, month=timezone.now().month, year=timezone.now().year)
        cc = ClientCommission(period=period, client=self.client, order_value=Decimal('100000.00'), commission_rate=Decimal('0.25'))
        cc.compute()
        cc.is_paid = True
        cc.save()

        data = _income_statement_for_year(_current_year())
        expected_gross_profit = data['total_revenue'] - (data['cost_flour'] + data['cost_yeast'] + data['cost_salt'] + data['cost_oil'])
        expected_net = expected_gross_profit - data['commissions_paid'] - data['operational_expenses']
        self.assertEqual(data['gross_profit'], expected_gross_profit)
        self.assertEqual(data['net_result'], expected_net)


class IncomeStatementPreviousYearIsolationTests(TestCase):
    """L'exercice N-1 doit être calculé isolément (pas de fuite entre années)."""

    def test_comparative_action_uses_distinct_dataset_per_year(self):
        node = make_node(code='ZK3', name='Zone Test K3')
        client = make_client(node)
        bp = BreadPrice.objects.create(category='MOYEN', label='Pain test N-1', unit_price=500, is_active=True)
        year = _current_year()

        inv = Invoice.objects.create(node=node, client=client, status='DELIVERED',
                                      order_total=Decimal('10000.00'), payment_amount=Decimal('0.00'))
        InvoiceLine.objects.create(invoice=inv, bread_price=bp, quantity=20, unit_price=500, line_total=Decimal('10000.00'))
        # `invoice_date` est `auto_now_add` : forcé à aujourd'hui. On le bascule
        # explicitement sur N-1 via `.update()` pour simuler une facture de l'an dernier,
        # sans passer par `save()` (qui réécrirait la date du jour).
        Invoice.objects.filter(pk=inv.pk).update(invoice_date=f'{year - 1}-06-15')

        data_now = _income_statement_for_year(year)
        data_prev = _income_statement_for_year(year - 1)
        self.assertEqual(data_now['total_revenue'], Decimal('0'))
        self.assertEqual(data_prev['total_revenue'], Decimal('10000'))
