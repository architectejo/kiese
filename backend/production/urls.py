from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ProductionSessionViewSet, BreadStockViewSet, ConsumableTypeViewSet, ConsumableStockViewSet,
    ConsumableMovementViewSet, ConsumableCountViewSet, BreadTransferViewSet, BreadDisposalViewSet,
    DailyClosureReportView, DailyOpeningConfirmationView, BreadStockByDateView,
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
    # BUG-133 : boîte modale « stock de départ » — avant le routeur, chemin
    # littéral, aucun conflit possible.
    path('opening-confirmation/', DailyOpeningConfirmationView.as_view(), name='daily-opening-confirmation'),
    # BUG-144 : stock de pains par date (live aujourd'hui / snapshot passé) —
    # chemin littéral SOUS le préfixe du routeur mais déclaré AVANT lui pour
    # qu'il ne soit jamais capturé par la route détail `bread-stocks/<pk>/`
    # du routeur (DRF router matcherait sinon `by-date` comme une PK invalide
    # avant d'atteindre cette vue si elle était déclarée après `include`).
    path('bread-stocks/by-date/', BreadStockByDateView.as_view(), name='bread-stock-by-date'),
    path('', include(router.urls)),
]
