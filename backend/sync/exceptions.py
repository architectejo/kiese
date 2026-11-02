"""
Exception dédiée aux échecs **transitoires** d'infrastructure (verrou SQLite
épuisé après retentatives) rencontrés pendant le traitement d'un lot `push`
ou l'authentification d'un nœud — BUG-062 (réouverture).

Distincte d'un rejet métier (`_record_result(..., False, reason)`, données
invalides, conflit réel) : un échec transitoire ne doit JAMAIS être archivé
comme un résultat terminal/définitif (`SyncBatchLog`), ni traduit en un code
HTTP qui laisserait croire à un refus propre (401/403) ou à un succès
partiel définitif (200/PARTIAL). Le nœud appelant doit comprendre qu'il doit
rejouer le même lot plus tard — c'est le sens du code HTTP 503 utilisé par
`sync.views`.
"""

from rest_framework.exceptions import APIException
from rest_framework import status


class TransientSyncError(APIException):
    """
    Échec d'infrastructure transitoire (verrou SQLite épuisé après
    retentatives) — jamais un refus métier. Traduit systématiquement en
    HTTP 503, jamais en 401/403/200.
    """
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Service de synchronisation temporairement indisponible (contention base de données) — veuillez réessayer le même lot."
    default_code = 'sync_transient_unavailable'
