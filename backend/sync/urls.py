from django.urls import path

from . import views
from .desktop_status import LocalSyncStatusView

urlpatterns = [
    path('handshake/', views.HandshakeView.as_view(), name='sync-handshake'),
    path('push/', views.PushView.as_view(), name='sync-push'),
    path('pull/', views.PullView.as_view(), name='sync-pull'),
    path('status/', views.StatusView.as_view(), name='sync-status'),
    path('conflicts/', views.SyncConflictListView.as_view(), name='sync-conflicts'),
    # Ajouté par packaging-desktop (DESKTOP.md §9/SYNC.md §9) : bandeau de
    # synchronisation local, authentification JWT humaine, distincte de
    # `status/` ci-dessus (jeton de nœud, côté Cloud). Voir desktop_status.py.
    path('local-status/', LocalSyncStatusView.as_view(), name='sync-local-status'),
]
