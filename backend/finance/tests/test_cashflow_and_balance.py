"""
Tests de cohérence comptable — Cash-Flow et Bilan (`_cashflow_for_year`,
`_balance_sheet_for_year`).

Mission auditeur-comptable (2026-10-22). Données fictives uniquement.

Constat documenté séparément (voir `docs/qa/ECART_CADRE_COMPTABLE.md`) :
`_balance_sheet_for_year` ne calcule qu'un côté (Actif = créances clients +
caisse) et ne produit ni Passif ni Capitaux Propres — il n'y a donc
structurellement aucune vérification possible de l'égalité Actif = Passif
avec le code actuel (pas de notion de compte/débit/crédit, pas de "Balance"
à proprement parler). Les tests ci-dessous caractérisent le comportement
réellement livré (ce qui est calculé, correctement, à partir des données
existantes) sans masquer cette limite : voir
`test_balance_sheet_has_no_liabilities_or_equity_side`.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.testing import make_node, make_client
from clients.models import Client
from treasury.models import CashbookEntry
from finance.views import _cashflow_for_year, _balance_sheet_for_year


def _current_year():
    return timezone.now().year


class CashflowCoherenceTests(TestCase):
    def setUp(self):
        self.node = make_node(code='ZF1', name='Zone Finance Test 1')

    def _make_entry(self, date, entry=Decimal('0.00'), exit_=Decimal('0.00'), running_balance=Decimal('0.00'), piece='P1'):
        # `previous_hash` est contraint `unique` en base (BUG-002) : on ne teste pas ici la
        # chaîne de hash elle-même (déjà couverte par ingenieur-blockchain/testeur-tresorerie),
        # seulement l'agrégation comptable — chaque écriture reçoit donc une valeur factice distincte.
        return CashbookEntry.objects.create(
            node=self.node, date=date, piece_number=piece, label='Mouvement test',
            entry_amount=entry, exit_amount=exit_, running_balance=running_balance,
            previous_hash=f'test-hash-{self.node.code}-{piece}',
        )

    def test_net_cashflow_is_total_entries_minus_total_exits(self):
        today = timezone.now().date()
        self._make_entry(today, entry=Decimal('100000.00'), running_balance=Decimal('100000.00'), piece='P1')
        self._make_entry(today, exit_=Decimal('30000.00'), running_balance=Decimal('70000.00'), piece='P2')
        self._make_entry(today, entry=Decimal('20000.00'), running_balance=Decimal('90000.00'), piece='P3')

        data = _cashflow_for_year(_current_year())
        self.assertEqual(data['total_entries'], Decimal('120000.00'))
        self.assertEqual(data['total_exits'], Decimal('30000.00'))
        self.assertEqual(data['net_cashflow'], data['total_entries'] - data['total_exits'])
        self.assertEqual(data['net_cashflow'], Decimal('90000.00'))

    def test_closing_balance_is_running_balance_of_last_entry_of_the_year(self):
        today = timezone.now().date()
        self._make_entry(today.replace(day=1), entry=Decimal('50000.00'), running_balance=Decimal('50000.00'), piece='P1')
        self._make_entry(today, entry=Decimal('10000.00'), running_balance=Decimal('60000.00'), piece='P2')

        data = _cashflow_for_year(_current_year())
        self.assertEqual(data['closing_balance'], Decimal('60000.00'))

    def test_no_entries_in_year_gives_zero_not_crash(self):
        data = _cashflow_for_year(_current_year() - 5)
        self.assertEqual(data['total_entries'], Decimal('0'))
        self.assertEqual(data['total_exits'], Decimal('0'))
        self.assertEqual(data['net_cashflow'], Decimal('0'))
        self.assertEqual(data['closing_balance'], Decimal('0'))


class BalanceSheetCoherenceTests(TestCase):
    def setUp(self):
        self.node = make_node(code='ZF2', name='Zone Finance Test 2')

    def test_receivables_sum_active_clients_current_debt_only(self):
        make_client(self.node, current_debt=Decimal('30000.00'))
        c2 = make_client(self.node, current_debt=Decimal('20000.00'))
        c2.is_active = False
        c2.save(update_fields=['is_active'])

        data = _balance_sheet_for_year(_current_year())
        self.assertEqual(data['receivables'], Decimal('30000.00'))  # le client inactif est exclu

    def test_cash_position_is_latest_cashbook_running_balance(self):
        CashbookEntry.objects.create(node=self.node, date=timezone.now().date(), piece_number='P1',
                                      label='Test', entry_amount=Decimal('42000.00'), exit_amount=Decimal('0.00'),
                                      running_balance=Decimal('42000.00'), previous_hash='test-hash-cash-position')
        data = _balance_sheet_for_year(_current_year())
        self.assertEqual(data['cash_position'], Decimal('42000.00'))

    def test_total_assets_is_receivables_plus_cash(self):
        make_client(self.node, current_debt=Decimal('15000.00'))
        CashbookEntry.objects.create(node=self.node, date=timezone.now().date(), piece_number='P1',
                                      label='Test', entry_amount=Decimal('5000.00'), exit_amount=Decimal('0.00'),
                                      running_balance=Decimal('5000.00'), previous_hash='test-hash-total-assets')
        data = _balance_sheet_for_year(_current_year())
        self.assertEqual(data['total_assets'], Decimal('20000.00'))

    def test_balance_sheet_has_no_liabilities_or_equity_side(self):
        """
        Caractérisation (pas un bug applicatif isolé) : la structure actuelle
        du bilan n'expose que l'Actif. Il n'existe aucune clé Passif/Capitaux
        Propres dans le dictionnaire retourné, donc aucune égalité
        Actif = Passif n'est vérifiable avec le code actuel. Document de
        décision client : docs/qa/ECART_CADRE_COMPTABLE.md.
        """
        data = _balance_sheet_for_year(_current_year())
        self.assertNotIn('liabilities', data)
        self.assertNotIn('equity', data)
        self.assertNotIn('total_liabilities_and_equity', data)
