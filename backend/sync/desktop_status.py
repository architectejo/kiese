"""
`GET /api/sync/local-status/` — bandeau de synchronisation côté poste
desktop (SYNC.md §9, DESKTOP.md §9).

Distinct de `sync.views.StatusView` (`/api/sync/status/`) : cette dernière
est authentifiée par `NodeTokenAuthentication` (jeton de nœud — une
« machine », appelée par le Cloud ou par un autre nœud, jamais par un
navigateur humain) et reflète l'état connu **côté Cloud** pour un nœud.

Cette route-ci est authentifiée par JWT utilisateur classique (n'importe
quel rôle connecté sur ce poste peut la lire — c'est un simple indicateur
d'état, pas une donnée métier) et reflète l'état **local**, en mémoire dans
`sync.desktop_client`, mis à jour par la boucle de synchronisation du poste
elle-même. Un contexte sans backend desktop (web pur, Cloud direct) n'a pas
cette route montée côté frontend — le composant `SyncStatusBadge` traite
une erreur 404 ici comme `{mode: "CLOUD_DIRECT"}` (voir
docs/architecture/SYNC.md §9), sans qu'aucun appel réseau supplémentaire ne
soit nécessaire côté backend pour ce cas.

Note pour le coordinateur : SYNC.md §9 décrit ce comportement comme porté
par `/api/sync/status/` lui-même ; en pratique cette route existante exige
une authentification de nœud incompatible avec un appel depuis le
navigateur humain du poste. Route séparée ajoutée ici pour lever cette
contradiction sans toucher à la route Cloud existante — à confirmer/aligner
avec `architecte-sync` si une convention de nommage unique est préférée.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class LocalSyncStatusView(APIView):
    """Authentification JWT utilisateur classique (pas un jeton de nœud)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from .desktop_client import get_local_sync_state
        except ImportError:
            return Response({'mode': 'CLOUD_DIRECT'})

        state = get_local_sync_state()
        return Response({'mode': 'DESKTOP_NODE', **state})
