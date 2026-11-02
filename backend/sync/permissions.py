from rest_framework.permissions import BasePermission

from .models import NodeAuthToken


class IsValidNodeToken(BasePermission):
    """
    Exige un `NodeAuthToken` valide (voir `sync.authentication.NodeTokenAuthentication`).
    N'accepte jamais un JWT utilisateur, même ADMIN — l'authentification de
    nœud est strictement distincte de l'authentification de personne
    (docs/architecture/SYNC.md §8).
    """

    def has_permission(self, request, view):
        return isinstance(getattr(request, 'auth', None), NodeAuthToken)
