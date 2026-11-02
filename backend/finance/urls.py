from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import FinancialYearViewSet

router = DefaultRouter()
router.register(r'years', FinancialYearViewSet, basename='financial-year')

urlpatterns = [
    path('', include(router.urls)),
]
