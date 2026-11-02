from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ProductionSessionViewSet, BreadStockViewSet, ConsumableTypeViewSet, ConsumableStockViewSet,
    ConsumableMovementViewSet, ConsumableCountViewSet, BreadTransferViewSet, BreadDisposalViewSet,
    DailyClosureReportView,
)

router = DefaultRouter()
router.register(r'sessions',    ProductionSessionViewSet,  basename='production-session')
router.register(r'bread-stocks', BreadStockViewSet,        basename='bread-stock')
router.register(r'consumable-types', ConsumableTypeViewSet, basename='consumable-type')
router.register(r'stocks',      ConsumableStockViewSet,    basename='consumable-stock')
router.register(r'movements',   ConsumableMovementViewSet, basename='consumable-movement')
router.register(r'counts',      ConsumableCountViewSet,    basename='consumable-count')
router.register(r'transfers',   BreadTransferViewSet,      basename='bread-transfer')
router.register(r'disposals',   BreadDisposalViewSet,      basename='bread-disposal')

urlpatterns = [
    # BUG-120 : rapport de clôture journalier consolidé — avant le routeur
    # (chemin littéral, aucun conflit possible avec les routes du routeur).
    path('daily-closure/', DailyClosureReportView.as_view(), name='daily-closure-report'),
    path('', include(router.urls)),
]
