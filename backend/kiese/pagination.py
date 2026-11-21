"""Pagination à ordre total déterministe (BUG-172).

Un `ORDER BY` non unique (ex. `client__last_name`) n'a pas d'ordre garanti
entre deux requêtes `LIMIT/OFFSET` sur PostgreSQL : des lignes ex æquo peuvent
être sautées ou doublées d'une page à l'autre. Ce paginateur ajoute `pk` en
dernier critère (sans changer l'ordre d'affichage primaire) pour tout
queryset paginé, quel que soit le viewset ou le paramètre `?ordering=`.
"""
from rest_framework.pagination import PageNumberPagination

_UNIQUE_KEYS = {'pk', '-pk', 'id', '-id'}


def with_unique_tiebreak(queryset):
    """Retourne `queryset` dont l'ordre se termine par un critère unique."""
    if not hasattr(queryset, 'query') or queryset.query.is_sliced:
        return queryset
    ordering = list(queryset.query.order_by or queryset.model._meta.ordering or [])
    pk_name = queryset.model._meta.pk.name
    unique = _UNIQUE_KEYS | {pk_name, '-' + pk_name}
    if any(isinstance(o, str) and o in unique for o in ordering):
        return queryset
    return queryset.order_by(*ordering, 'pk')


class DeterministicPageNumberPagination(PageNumberPagination):
    # BUG-333 : PAGE_SIZE_QUERY_PARAM / MAX_PAGE_SIZE ne sont pas des réglages
    # DRF ; ils se déclarent sur la classe de pagination.
    page_size_query_param = 'page_size'
    max_page_size = 500

    def paginate_queryset(self, queryset, request, view=None):
        return super().paginate_queryset(with_unique_tiebreak(queryset), request, view)
