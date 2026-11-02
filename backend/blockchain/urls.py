from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import TamperAlertViewSet, BlockchainSnapshotViewSet

router = DefaultRouter()
router.register(r'alerts',    TamperAlertViewSet,      basename='tamper-alert')
router.register(r'snapshots', BlockchainSnapshotViewSet, basename='blockchain-snapshot')

urlpatterns = [
    path('', include(router.urls)),
]
