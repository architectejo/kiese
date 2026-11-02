"""
URL configuration for kiese project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Core API endpoints (auth, config, nodes, users)
    path('api/core/', include('core.urls')),
    
    # Other Apps API endpoints (to be linked as we build them)
    path('api/clients/', include('clients.urls')),
    path('api/sales/', include('sales.urls')),
    path('api/production/', include('production.urls')),
    path('api/treasury/', include('treasury.urls')),
    path('api/commissions/', include('commissions.urls')),
    path('api/finance/', include('finance.urls')),
    path('api/blockchain/', include('blockchain.urls')),
    path('api/sync/', include('sync.urls')),

    # API Schema & Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/docs/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

# Médias toujours servis par Django (WhiteNoise gère les fichiers statiques)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
