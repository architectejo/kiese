from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import CommissionPeriodViewSet, ClientCommissionViewSet

router = DefaultRouter()
router.register(r'periods',     CommissionPeriodViewSet,  basename='commission-period')
router.register(r'commissions', ClientCommissionViewSet,  basename='client-commission')

urlpatterns = [
    path('', include(router.urls)),
]
