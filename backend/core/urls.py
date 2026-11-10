"""
Core URL configuration.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

router = DefaultRouter()
router.register(r'nodes',         views.NodeViewSet,                basename='node')
router.register(r'users',         views.UserViewSet,                basename='user')
router.register(r'bread-prices',  views.BreadPriceViewSet,          basename='bread-price')
router.register(r'expense-categories', views.ExpenseCategoryViewSet, basename='expense-category')
router.register(r'activities',    views.ActivityLogViewSet,          basename='activity')
router.register(r'notifications', views.SystemNotificationViewSet,   basename='notification')
router.register(r'colis',         views.ColisDistributionViewSet,    basename='colis-distribution')

urlpatterns = [
    path('auth/login/', views.login_view, name='login'),
    # BUG-024 : le frontend (frontend/src/api/client.ts) appelle exactement
    # cette URL pour rafraîchir l'access token à son expiration. `TokenRefreshView`
    # de SimpleJWT applique nativement ROTATE_REFRESH_TOKENS/BLACKLIST_AFTER_ROTATION
    # (voir settings.py SIMPLE_JWT, BUG-006) : un refresh token blacklisté après
    # logout est bien rejeté par cette vue.
    path('auth/login/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/me/', views.me_view, name='me'),
    path('config/', views.ConfigView.as_view(), name='config'),
    # BUG-149 : réinitialisation globale des données (Superuser strict).
    path('reset-data/', views.reset_data_view, name='reset-data'),
    path('', include(router.urls)),
]
