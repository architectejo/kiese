from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    LocalExpenseViewSet, FacturierReportViewSet,
    CashClosureViewSet, CashbookEntryViewSet, JournalEntryViewSet, DailySavingsViewSet,
    DisbursementVoucherViewSet, DirectionCashCountViewSet,
)

router = DefaultRouter()
router.register(r'expenses',  LocalExpenseViewSet,    basename='local-expense')
router.register(r'reports',   FacturierReportViewSet, basename='facturier-report')
router.register(r'closures',  CashClosureViewSet,     basename='cash-closure')
router.register(r'cashbook',  CashbookEntryViewSet,   basename='cashbook-entry')
router.register(r'journal',   JournalEntryViewSet,    basename='journal-entry')
router.register(r'savings',   DailySavingsViewSet,    basename='daily-savings')
router.register(r'vouchers',  DisbursementVoucherViewSet, basename='disbursement-voucher')
# BUG-119 : comptage physique de billets au niveau Direction (Niveau 3).
router.register(r'direction-cash-counts', DirectionCashCountViewSet, basename='direction-cash-count')

urlpatterns = [
    path('', include(router.urls)),
]
