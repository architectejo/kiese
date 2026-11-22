"""BUG-743 : recherche insensible à la casse ET aux accents, y compris sous SQLite.

SQLite (nœuds desktop) ne replie la casse qu'en ASCII : « élodie » ne trouvait
pas « Élodie ». On enregistre une fonction SQL `KIESE_FOLD` (minuscule sans
accents) et on compare des valeurs repliées des deux côtés. Sur les autres
moteurs, comportement inchangé (Lower / icontains).
"""
import unicodedata

from django.db import connection
from django.db.models import CharField, Func, Q
from django.db.models.functions import Lower
from rest_framework import filters


def fold(value):
    """Minuscule sans accents (NFD sans marques combinantes, casefold)."""
    if value is None:
        return None
    text = unicodedata.normalize('NFD', str(value))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return unicodedata.normalize('NFC', text).casefold()


def register_sqlite_functions(sender=None, connection=None, **kwargs):
    """Signal `connection_created` : déclare KIESE_FOLD sur chaque connexion SQLite."""
    if connection is not None and connection.vendor == 'sqlite':
        connection.connection.create_function('KIESE_FOLD', 1, fold, deterministic=True)


class Fold(Func):
    function = 'KIESE_FOLD'
    arity = 1
    output_field = CharField()


def is_sqlite():
    return connection.vendor == 'sqlite'


def fold_expr(expression):
    """Expression SQL repliée (casse + accents sous SQLite, Lower ailleurs)."""
    return Fold(expression) if is_sqlite() else Lower(expression)


def fold_term(term):
    return fold(term) if is_sqlite() else term.lower()


class AccentInsensitiveSearchFilter(filters.SearchFilter):
    """SearchFilter DRF : sous SQLite, comparaison sur valeurs repliées."""

    def filter_queryset(self, request, queryset, view):
        if not is_sqlite():
            return super().filter_queryset(request, queryset, view)
        search_fields = self.get_search_fields(view, request)
        terms = self.get_search_terms(request)
        if not search_fields or not terms:
            return queryset
        aliases = {}
        for i, field in enumerate(search_fields):
            field = field.lstrip('^=@$')
            aliases[field] = f'_fold_{i}'
        queryset = queryset.alias(**{alias: Fold(field) for field, alias in aliases.items()})
        for term in terms:
            needle = fold(term)
            cond = Q()
            for alias in aliases.values():
                cond |= Q(**{f'{alias}__contains': needle})
            queryset = queryset.filter(cond)
        return queryset
