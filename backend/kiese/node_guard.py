"""Garde « compte sans boulangerie » (BUG-362), hors de core/."""
from rest_framework.exceptions import PermissionDenied

from core.mixins import is_node_less_non_hq


class NoNodeGuardMixin:
    """Compte non-siège SANS boulangerie : toute écriture refusée (403 en français).
    La lecture est vidée par les `get_queryset` (`.none()`)."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        user = request.user
        if (request.method not in ('GET', 'HEAD', 'OPTIONS') and user.is_authenticated
                and is_node_less_non_hq(user)):
            raise PermissionDenied("Votre compte n'est rattaché à aucune boulangerie : action impossible.")
