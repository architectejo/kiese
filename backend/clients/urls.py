from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ClientViewSet,
    SocialContributionViewSet, SocialDistributionViewSet, SocialDistributionLineViewSet,
)

router = DefaultRouter()
router.register(r'clients',              ClientViewSet,                basename='client')
router.register(r'contributions',        SocialContributionViewSet,    basename='social-contribution')
router.register(r'distributions',        SocialDistributionViewSet,    basename='social-distribution')
router.register(r'distribution-lines',   SocialDistributionLineViewSet, basename='social-distribution-line')

urlpatterns = [
    path('', include(router.urls)),
]
