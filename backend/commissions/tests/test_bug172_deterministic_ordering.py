"""BUG-172 : ordre total déterministe pour toute liste paginée (volet backend).

Un tri non unique (ex. `client__last_name`) peut sauter ou doubler des lignes
entre deux pages sur PostgreSQL. Garantie : l'ordre effectif se termine par
un critère unique, sans changer l'ordre d'affichage primaire.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from clients.views import ClientViewSet
from commissions.models import ClientCommission, CommissionPeriod
from commissions.views import ClientCommissionViewSet, CommissionPeriodViewSet
from core.testing import make_node, make_user, make_client
from core.views import ActivityLogViewSet, NodeViewSet, SystemNotificationViewSet
from kiese.pagination import with_unique_tiebreak
from production.views import (
    BreadDisposalViewSet, BreadStockViewSet, BreadTransferViewSet,
    ConsumableCountViewSet, ConsumableMovementViewSet, ProductionSessionViewSet,
)
from sales.views import InvoiceViewSet
from treasury.views import (
    CashbookEntryViewSet, CashClosureViewSet, DailySavingsViewSet,
    DirectionCashCountViewSet, DisbursementVoucherViewSet, FacturierReportViewSet,
    JournalEntryViewSet, LocalExpenseViewSet,
)
from blockchain.views import BlockchainSnapshotViewSet, TamperAlertViewSet

UNIQUE = {'pk', '-pk', 'id', '-id'}

ALL_VIEWSETS = [
    ClientCommissionViewSet, CommissionPeriodViewSet, ClientViewSet,
    ActivityLogViewSet, NodeViewSet, SystemNotificationViewSet,
    BreadDisposalViewSet, BreadStockViewSet, BreadTransferViewSet,
    ConsumableCountViewSet, ConsumableMovementViewSet, ProductionSessionViewSet,
    InvoiceViewSet, CashbookEntryViewSet, CashClosureViewSet, DailySavingsViewSet,
    DirectionCashCountViewSet, DisbursementVoucherViewSet, FacturierReportViewSet,
    JournalEntryViewSet, LocalExpenseViewSet, BlockchainSnapshotViewSet,
    TamperAlertViewSet,
]


def _effective_ordering(qs):
    return list(qs.query.order_by)


class EffectiveOrderingEndsWithUniqueKeyTests(TestCase):
    def test_every_paginated_viewset_ordering_ends_with_unique_key(self):
        for vs in ALL_VIEWSETS:
            with self.subTest(viewset=vs.__name__):
                ordered = with_unique_tiebreak(vs.queryset.all())
                order = _effective_ordering(ordered)
                self.assertTrue(order, f'{vs.__name__} : queryset non ordonné')
                last = order[-1]
                self.assertIn(last if isinstance(last, str) else None, UNIQUE | {'pk'})

    def test_commission_viewset_declares_pk_last(self):
        self.assertEqual(ClientCommissionViewSet.ordering[-1], 'pk')
        self.assertEqual(ClientCommissionViewSet.ordering[0], 'client__last_name')

    def test_primary_order_unchanged(self):
        qs = with_unique_tiebreak(CashbookEntryViewSet.queryset.all().order_by('-date', '-created_at'))
        self.assertEqual(_effective_ordering(qs), ['-date', '-created_at', 'pk'])
        qs = with_unique_tiebreak(ProductionSessionViewSet.queryset.order_by('-date'))
        self.assertEqual(_effective_ordering(qs), ['-date', 'pk'])

    def test_existing_unique_key_not_duplicated(self):
        qs = with_unique_tiebreak(ClientCommission.objects.order_by('client__last_name', 'pk'))
        self.assertEqual(_effective_ordering(qs), ['client__last_name', 'pk'])


class _PaginationBase:
    def setUp(self):
        self.node = make_node(code='ZORD1')
        self.user = make_user(role='ADMIN', node=None)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def _walk(self, url, page_size=2):
        ids, page = [], 1
        while True:
            resp = self.api.get(url, {'page': page, 'page_size': page_size})
            self.assertEqual(resp.status_code, 200, resp.content)
            ids += [str(r['id']) for r in resp.data['results']]
            if not resp.data.get('next'):
                return ids
            page += 1

    def test_commissions_same_last_name_all_pages(self):
        period = CommissionPeriod.objects.create(node=self.node, month=5, year=2026)
        expected = set()
        for i in range(7):
            c = make_client(self.node, last_name='Identique')
            cm = ClientCommission.objects.create(period=period, client=c)
            expected.add(str(cm.pk))
        ids = self._walk('/api/commissions/commissions/')
        self.assertEqual(len(ids), 7)
        self.assertEqual(set(ids), expected)

    def test_clients_same_last_name_all_pages(self):
        expected = {str(make_client(self.node, last_name='Meme', first_name='Prenom').pk)
                    for _ in range(7)}
        ids = self._walk('/api/clients/clients/')
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), expected)

    def test_clients_custom_ordering_param_all_pages(self):
        expected = {str(make_client(self.node, last_name='Meme').pk) for _ in range(5)}
        ids = self._walk('/api/clients/clients/?ordering=-current_debt')
        self.assertEqual(set(ids), expected)
        self.assertEqual(len(ids), 5)


class CommissionsClientsPaginationTests(_PaginationBase, TestCase):
    pass


class TreasuryPaginationBug176Tests(_PaginationBase, TestCase):
    """BUG-176 : dépenses, rapports, clôtures, épargne : même date, parcours complet."""

    def _nodes(self, n=5):
        return [make_node(code=f'ZT{i}') for i in range(n)]

    def _check(self, url, objs):
        ids = self._walk(url)
        self.assertEqual(len(ids), len(objs))
        self.assertEqual(set(ids), {str(o.pk) for o in objs})

    def test_local_expenses_same_date(self):
        from core.models import ExpenseCategory
        from treasury.models import LocalExpense
        cat = ExpenseCategory.objects.create(code='CB176', label='CatBug176')
        objs = [LocalExpense.objects.create(node=self.node, description=f'd{i}', amount=Decimal('10'),
                                            category=cat, date='2026-05-01') for i in range(7)]
        self._check('/api/treasury/expenses/', objs)

    def test_reports_closures_savings_same_date(self):
        from treasury.models import FacturierReport, CashClosure, DailySavings
        nodes = self._nodes()
        self._check('/api/treasury/reports/',
                    [FacturierReport.objects.create(node=n, date='2026-05-01') for n in nodes])
        self._check('/api/treasury/closures/',
                    [CashClosure.objects.create(node=n, date='2026-05-01') for n in nodes])
        self._check('/api/treasury/savings/',
                    [DailySavings.objects.create(node=n, date='2026-05-01') for n in nodes])

    def test_treasury_viewsets_declare_unique_last(self):
        for vs in (LocalExpenseViewSet, FacturierReportViewSet, CashClosureViewSet,
                   DailySavingsViewSet, CashbookEntryViewSet, DisbursementVoucherViewSet,
                   DirectionCashCountViewSet, JournalEntryViewSet):
            with self.subTest(vs=vs.__name__):
                self.assertIn(vs.ordering[-1], ('pk', '-pk'))
        self.assertEqual(CashbookEntryViewSet.ordering[:2], ['-date', '-created_at'])
