"""
Endpoints `/api/sync/*` — docs/architecture/SYNC.md §8.

Authentification par jeton de nœud (`NodeTokenAuthentication`), jamais par
JWT utilisateur, sauf `/api/sync/conflicts/` qui reste une route siège
classique (JWT + IsHeadquarters).
"""

import random
import time
import uuid

from django.db import IntegrityError, OperationalError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Node, Config, BreadPrice
from core.permissions import IsHeadquarters
from .authentication import NodeTokenAuthentication
from .exceptions import TransientSyncError
from .permissions import IsValidNodeToken
from .models import SyncBatchLog, SyncConflictLog
from .serializers import SyncConflictLogSerializer
from .services import process_push_batch

# BUG-062 : même motif que `sync.services._WRITE_MAX_RETRIES` /
# `sync.models.NodeAuthToken.authenticate()` — une fois l'authentification
# du nœud elle-même protégée, le rejeu concurrent d'un même `batch_id`
# (plusieurs tentatives quasi simultanées après coupure) peut encore heurter
# « database is locked » sous SQLite lors de l'écriture de `SyncBatchLog`
# (idempotence de lot, SYNC.md §3.3) ou de la mise à jour `Node.last_sync`.
# Toute la logique est relue depuis le début à chaque tentative (y compris
# le contrôle d'idempotence `existing_batch`), jamais une retentative
# partielle à l'intérieur d'une transaction déjà entamée.
_PUSH_MAX_RETRIES = 150


class HandshakeView(APIView):
    """
    Vérifie le jeton de nœud et renvoie l'état serveur minimal attendu par
    un poste desktop au démarrage de son service de synchronisation
    (SYNC.md §3.1/§8).
    """
    authentication_classes = [NodeTokenAuthentication]
    permission_classes = [IsValidNodeToken]

    def post(self, request):
        node = request.auth.node
        Node.objects.filter(pk=node.pk).update(last_sync=timezone.now())
        return Response({
            'node_code': node.code,
            'node_name': node.name,
            'server_time': timezone.now().isoformat(),
            'is_active': node.is_active,
        })


class PushView(APIView):
    """POST /api/sync/push/ — montée Local → Cloud (SYNC.md §3)."""
    authentication_classes = [NodeTokenAuthentication]
    permission_classes = [IsValidNodeToken]

    def post(self, request):
        last_exc = None
        for _attempt in range(_PUSH_MAX_RETRIES):
            try:
                return self._post_once(request)
            except OperationalError as exc:
                if 'locked' not in str(exc).lower():
                    raise
                last_exc = exc
                time.sleep(random.uniform(0.02, 0.12))
                continue
            except IntegrityError as exc:
                # Deux rejeux concurrents du MÊME `batch_id` peuvent passer
                # le contrôle d'idempotence (`existing_batch is None`) avant
                # que l'un des deux n'ait committé son `SyncBatchLog` — le
                # second heurte alors la contrainte `unique=True` sur
                # `batch_id` plutôt qu'un verrou. On retente : la prochaine
                # itération relit `existing_batch` depuis le début et
                # renvoie le résultat déjà archivé par le gagnant de la
                # course (comportement idempotent attendu, SYNC.md §3.3).
                if 'batch_id' not in str(exc).lower() and 'syncbatchlog' not in str(exc).lower():
                    raise
                last_exc = exc
                time.sleep(random.uniform(0.02, 0.12))
                continue
        # BUG-062 (réouverture) : budget de 150 tentatives épuisé malgré
        # tout (contention extrême) — `sync.services.process_push_batch`
        # ne convertit plus jamais ceci en résultat `REJECTED` archivé (voir
        # son commentaire). Ici non plus : on ne persiste AUCUN
        # `SyncBatchLog` pour ce `batch_id` (rien n'a été écrit avant ce
        # point dans `_post_once` qui puisse nécessiter un retour en
        # arrière) et on renvoie un 503 explicite — le nœud appelant doit
        # rejouer le MÊME `batch_id` plus tard ; ce rejeu retraitera pour de
        # bon l'enregistrement resté en échec (chaque gestionnaire de
        # `sync.services.PUSH_HANDLERS` est idempotent par construction, cf.
        # `_push_client`/`_push_invoice`/`_push_debt_movement`), sans jamais
        # retourner indéfiniment le même résultat figé.
        raise TransientSyncError() from last_exc

    def _post_once(self, request):
        node = request.auth.node
        batch_id_raw = request.data.get('batch_id')
        try:
            batch_id = uuid.UUID(str(batch_id_raw))
        except (TypeError, ValueError):
            return Response({'detail': "batch_id manquant ou invalide (UUID attendu)."}, status=status.HTTP_400_BAD_REQUEST)

        # Idempotence de lot (SYNC.md §3.3/§3.6) : un batch_id déjà traité
        # renvoie le résultat archivé sans ré-exécuter la logique métier.
        existing_batch = SyncBatchLog.objects.filter(batch_id=batch_id).first()
        if existing_batch is not None:
            return Response({'batch_id': str(batch_id), 'results': existing_batch.result, 'replayed': True})

        records_by_model = request.data.get('records') or {}
        if not isinstance(records_by_model, dict):
            return Response({'detail': "'records' doit être un objet {modèle: [enregistrements]}."}, status=status.HTTP_400_BAD_REQUEST)

        results = process_push_batch(node, records_by_model)

        any_rejected = any(
            r.get('status') == 'REJECTED'
            for model_results in results.values()
            for r in model_results
        )
        batch_status = SyncBatchLog.Status.PARTIAL if any_rejected else SyncBatchLog.Status.OK

        SyncBatchLog.objects.create(batch_id=batch_id, node=node, status=batch_status, result=results)
        Node.objects.filter(pk=node.pk).update(last_sync=timezone.now())

        return Response({'batch_id': str(batch_id), 'results': results, 'replayed': False})


def _parse_cursor(request, param_name):
    raw = request.query_params.get(param_name)
    if not raw:
        return None
    return parse_datetime(raw)


class PullView(APIView):
    """GET /api/sync/pull/ — descente Cloud → Local (SYNC.md §4)."""
    authentication_classes = [NodeTokenAuthentication]
    permission_classes = [IsValidNodeToken]

    def get(self, request):
        from django.db.models import Q
        from clients.models import Client

        node = request.auth.node
        now = timezone.now()

        since_config = _parse_cursor(request, 'since_config')
        since_client_debt = _parse_cursor(request, 'since_client_debt')

        payload = {'server_time': now.isoformat()}

        config = Config.get_instance()
        if since_config is None or config.updated_at > since_config:
            payload['config'] = {
                'default_commission_rate': str(config.default_commission_rate),
                'debt_ceiling': str(config.debt_ceiling),
                'best_client_threshold': config.best_client_threshold,
                'sac_value_fc': config.sac_value_fc,
                'degraded_sync_threshold_hours': config.degraded_sync_threshold_hours,
                'offline_credit_limit_ratio': str(config.offline_credit_limit_ratio),
                'updated_at': config.updated_at.isoformat(),
            }
        payload['since_config'] = now.isoformat()

        # BreadPrice n'a pas de champ `updated_at` exploitable pour un
        # curseur fin : table minuscule (4 catégories), renvoyée en entier
        # à chaque pull plutôt que de complexifier pour un gain nul.
        bp_qs = BreadPrice.objects.all()
        payload['bread_prices'] = [
            {'id': bp.pk, 'label': bp.label, 'unit_price': str(bp.unit_price)}
            for bp in bp_qs
        ]
        payload['since_breadprice'] = now.isoformat()

        # Clients pertinents pour ce nœud : les siens, ou tout client déjà
        # facturé par ce nœud ailleurs (SYNC.md §1.3) — leur `current_debt`
        # recalculé est ce qui doit redescendre, jamais une valeur figée.
        client_qs = Client.objects.filter(
            Q(node=node) | Q(invoices__node=node)
        ).distinct()
        if since_client_debt is not None:
            client_qs = client_qs.filter(updated_at__gt=since_client_debt)
        payload['clients'] = [
            {
                'id': str(c.id), 'code': c.code, 'current_debt': str(c.current_debt),
                'credit_limit': str(c.credit_limit), 'category': c.category,
                'updated_at': c.updated_at.isoformat(),
            }
            for c in client_qs
        ]
        payload['since_client_debt'] = now.isoformat()

        Node.objects.filter(pk=node.pk).update(last_sync=now)
        return Response(payload)


class StatusView(APIView):
    """
    GET /api/sync/status/ — vue minimale pour le bandeau desktop
    (SYNC.md §9). En V1, reflète l'état du nœud côté Cloud (dernier
    handshake, conflits non résolus) — pas une file d'attente locale
    (qui vit côté poste desktop, hors de ce dépôt backend).
    """
    authentication_classes = [NodeTokenAuthentication]
    permission_classes = [IsValidNodeToken]

    def get(self, request):
        node = request.auth.node
        unresolved_conflicts = SyncConflictLog.objects.filter(node=node, resolved_at__isnull=True).count()
        return Response({
            'node_code': node.code,
            'last_sync': node.last_sync.isoformat() if node.last_sync else None,
            'is_degraded': node.is_sync_degraded(),
            'unresolved_conflicts': unresolved_conflicts,
        })


class SyncConflictListView(generics.ListAPIView):
    """
    GET /api/sync/conflicts/ — consultation au siège (SYNC.md §5.2).
    Authentification JWT utilisateur classique (ADMIN/DIRECTION/COMPTABLE),
    PAS un jeton de nœud : c'est un écran humain, pas une route machine.
    """
    queryset = SyncConflictLog.objects.select_related('node', 'resolved_by').all()
    serializer_class = SyncConflictLogSerializer
    permission_classes = [IsHeadquarters]
