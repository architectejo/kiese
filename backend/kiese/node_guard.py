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


# --- Paramètres de requête illisibles : 400 en français, jamais 500 (BUG-526 à 529) ---

def resolve_node_param(raw):
    """`?node=` (clé primaire ou code boulangerie, casse indifférente).
    Retourne (Node, None) ou (None, Response 400 `{"detail": ...}`)."""
    from rest_framework import status
    from rest_framework.response import Response
    from core.models import Node

    def _invalid():
        return None, Response({'detail': f"Boulangerie « {str(raw)[:40]} » introuvable."},
                              status=status.HTTP_400_BAD_REQUEST)

    # BUG-541 : un booléen JSON (int(True) == 1), un flottant (tronqué par int()),
    # une liste ou un objet ne sont jamais un identifiant de boulangerie.
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return _invalid()
    text = str(raw).strip()
    if len(text) > 40:
        return _invalid()
    node = None
    if text.isascii() and text.isdigit():
        value = int(text)
        if value < 1 or value > 2147483647:
            return _invalid()
        node = Node.objects.filter(pk=value).first()
    elif isinstance(raw, int):
        return _invalid()  # entier négatif
    else:
        node = Node.objects.filter(code__iexact=text).first()
    if node is None:
        return _invalid()
    return node, None


def parse_date_param(raw, name='date'):
    """Date ISO AAAA-MM-JJ. Retourne (date, None) ou (None, message d'erreur)."""
    import datetime
    try:
        return datetime.date.fromisoformat(str(raw)), None
    except ValueError:
        return None, f"Paramètre « {name} » invalide — format attendu AAAA-MM-JJ."


def month_year_error(month, year):
    """Message d'erreur (str) si `month` (1-12) ou `year` (2000-2100) est illisible
    ou hors bornes, sinon None. Chaque paramètre peut être None."""
    if month not in (None, ''):
        try:
            m = int(month)
        except (TypeError, ValueError):
            return "Le paramètre « month » doit être un entier (1-12)."
        if not 1 <= m <= 12:
            return "Le paramètre « month » doit être compris entre 1 et 12."
    if year not in (None, ''):
        try:
            y = int(year)
        except (TypeError, ValueError):
            return "Le paramètre « year » doit être un entier."
        if not 2000 <= y <= 2100:
            return "Le paramètre « year » doit être compris entre 2000 et 2100."
    return None
