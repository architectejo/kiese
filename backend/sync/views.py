"""
Endpoints `/api/sync/*` — docs/architecture/SYNC.md §8.

Authentification par jeton de nœud (`NodeTokenAuthentication`), jamais par
JWT utilisateur, sauf `/api/sync/conflicts/` qui reste une route siège
classique (JWT + IsHeadquarters).
"""

import hashlib
import json
import random
import time
import uuid

from django.db import IntegrityError, OperationalError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics, status
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Node, Config, BreadPrice
from core.permissions import IsHeadquarters
from .authentication import NodeTokenAuthentication
from .exceptions import TransientSyncError
from .permissions import IsValidNodeToken
from .models import NodeOpenTransfers, SyncBatchLog, SyncConflictLog, TransferMirror, TransferPull
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


_MAX_OPEN_TRANSFERS = 1000


def _store_open_transfers(node, raw):
    """BUG-980 : mémorise les ids (UUID valides, bornés) des transferts non terminaux du poste.
    Champ absent (poste ancien) : rien n'est modifié ; valeur invalide : ignorée."""
    if raw is None or not isinstance(raw, list):
        return
    ids = []
    for item in raw[:_MAX_OPEN_TRANSFERS]:
        if isinstance(item, str) and len(item) <= 40:
            try:
                ids.append(str(uuid.UUID(item)))
            except (TypeError, ValueError):
                continue
    NodeOpenTransfers.objects.update_or_create(node=node, defaults={'transfer_ids': sorted(set(ids))})


_MAX_MIRRORS = 500


def _clean_mirror(raw):
    """{bread_price_id: [envoyé_déduit, reçu_crédité]} borné ; None si la forme est invalide."""
    if not isinstance(raw, dict) or len(raw) > 200:
        return None
    out = {}
    for bp, pair in raw.items():
        if (not isinstance(bp, str) or not bp.isascii() or not bp.isdigit() or len(bp) > 12
                or not isinstance(pair, (list, tuple)) or len(pair) != 2):
            return None
        vals = []
        for v in pair:
            if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 2_000_000_000:
                return None
            vals.append(v)
        out[str(int(bp))] = vals
    return out


def _store_mirrors(node, raw):
    """BUG-989/990 : mémorise le miroir de stock appliqué par le poste (état de ses lignes
    locales). Champ absent / invalide : rien n'est modifié. Un transfert étranger au nœud ou
    inconnu est ignoré. Appliqué seulement pour un lot NEUF (jamais sur un rejeu : un ancien
    lot ne doit pas ramener le marqueur en arrière)."""
    from django.db.models import Q

    from production.models import BreadTransfer
    if not isinstance(raw, dict):
        return
    cleaned = {}
    for key, value in list(raw.items())[:_MAX_MIRRORS]:
        try:
            tid = uuid.UUID(key) if isinstance(key, str) and len(key) <= 40 else None
        except (TypeError, ValueError):
            tid = None
        mirror = _clean_mirror(value)
        if tid is not None and mirror is not None:
            cleaned[tid] = mirror
    if not cleaned:
        return
    mine_qs = BreadTransfer.objects.filter(pk__in=list(cleaned)).filter(
        Q(from_node=node) | Q(to_node=node)).prefetch_related('lines')
    mine_objs = {t.pk: t for t in mine_qs}
    mine = set(mine_objs)
    _bump_peaks(node, mine_objs.values())
    pulled = dict(TransferPull.objects.filter(node=node, transfer_id__in=list(mine)).values_list(
        'transfer_id', 'pulled_at'))
    bounds = {}
    for tid, t in mine_objs.items():
        for bp, pair in _effective_line_bounds(t).items():
            bounds[(tid, bp)] = pair
    for tid, mirror in cleaned.items():
        if tid not in mine:
            continue
        existing = TransferMirror.objects.filter(node=node, transfer_id=tid).first()
        old = dict(existing.applied) if existing is not None else {}
        peak = existing.peak if existing is not None and isinstance(existing.peak, dict) else {}
        # BUG-1000 : un poste qui n'a pas encore tiré la dernière modification du transfert (résolution
        # au siège) peut légitimement pousser un marqueur au-dessus de la borne actuelle, jusqu'à la
        # plus haute valeur historique connue du cloud.
        stale = (mine_objs[tid].transfer_status != 'PENDING'
                 and (tid not in pulled or pulled[tid] < mine_objs[tid].updated_at))
        merged = dict(old)
        rejected = []
        for bp, (sent, recv) in mirror.items():
            bound = bounds.get((tid, bp))
            upper = bound
            if bound is not None and stale:
                hp = peak.get(bp)
                if isinstance(hp, (list, tuple)) and len(hp) == 2:
                    upper = (max(bound[0], hp[0]), max(bound[1], hp[1]))
            if bound is None or sent > upper[0] or recv > upper[1]:
                # BUG-997 : marqueur hors borne (ou ligne inconnue du cloud) : ignoré.
                rejected.append(bp)
                continue
            prev = old.get(bp)
            if prev is not None and len(prev) == 2 and prev[0] <= bound[0] and prev[1] <= bound[1]:
                # Monotone, sauf rétablissement : l'ancien marqueur dépasse la borne actuelle
                # (ex. résolution d'écart ayant réduit la ligne cloud) -> la valeur du poste prévaut.
                sent, recv = max(sent, prev[0]), max(recv, prev[1])
            merged[bp] = [sent, recv]
        if rejected:
            conflict, created = SyncConflictLog.objects.get_or_create(
                node=node, model_label='sync.TransferMirror', object_id=str(tid)[:40],
                conflict_type='MIRROR_OUT_OF_BOUNDS', resolved_at=None,
                defaults={'detail': "Marqueur de miroir ignoré (hors borne des lignes du cloud) "
                                    f"pour les catégories {', '.join(sorted(rejected))}."})
            if not created:
                SyncConflictLog.objects.filter(pk=conflict.pk).update(occurrences=conflict.occurrences + 1)
        if merged != old:
            TransferMirror.objects.update_or_create(node=node, transfer_id=tid, defaults={'applied': merged})


def _effective_line_bounds(transfer):
    """{bread_price_id: (envoyé_déduit_max, reçu_max)} d'un transfert (lignes préchargées).
    BUG-1002 : tant que le transfert est en attente (PENDING) ou annulé, rien n'est déduit
    chez l'émettrice : borne d'envoi = 0."""
    deducted = transfer.transfer_status in ('RESPONDED', 'DISPUTED', 'CONFIRMED')
    return {
        str(l.bread_price_id): ((l.quantity_sent or 0) if deducted else 0, l.quantity_received or 0)
        for l in transfer.lines.all()
    }


def _bump_peaks(node, transfers):
    """BUG-1000 : retient pour (nœud, transfert) la plus haute borne [envoyé, reçu] vue par le cloud."""
    for t in transfers:
        cur = _effective_line_bounds(t)
        if not cur:
            continue
        row = TransferMirror.objects.filter(node=node, transfer_id=t.pk).first()
        peak = dict(row.peak) if row is not None and isinstance(row.peak, dict) else {}
        new = dict(peak)
        for bp, (s, r) in cur.items():
            hp = peak.get(bp) or [0, 0]
            new[bp] = [max(hp[0], s), max(hp[1], r)]
        if new != peak or row is None:
            TransferMirror.objects.update_or_create(node=node, transfer_id=t.pk, defaults={'peak': new})


def _clamped_mirror(applied, transfer):
    """BUG-1001 : marqueur descendu borné aux quantités actuelles des lignes cloud
    (la somme du groupe reste nulle pour un poste réinstallé après une résolution)."""
    lines = {str(l.bread_price_id): l for l in transfer.lines.all()}
    out = {}
    for bp, pair in applied.items():
        l = lines.get(bp)
        if l is None or not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        out[bp] = [min(pair[0], l.quantity_sent or 0), min(pair[1], l.quantity_received or 0)]
    return out


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
        data = request.data
        if not isinstance(data, dict):
            return Response({'detail': "Corps de requête invalide : un objet JSON est attendu."}, status=status.HTTP_400_BAD_REQUEST)
        batch_id_raw = data.get('batch_id')
        if not isinstance(batch_id_raw, str):
            return Response({'detail': "batch_id manquant ou invalide (UUID attendu)."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            batch_id = uuid.UUID(batch_id_raw)
        except (TypeError, ValueError):
            return Response({'detail': "batch_id manquant ou invalide (UUID attendu)."}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-980 : transferts non terminaux connus du poste (hors empreinte du lot ;
        # mise à jour idempotente, y compris sur un lot rejoué).
        _store_open_transfers(node, data.get('open_transfers'))

        records_by_model = data.get('records') or {}
        if not isinstance(records_by_model, dict):
            return Response({'detail': "'records' doit être un objet {modèle: [enregistrements]}."}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-726 : empreinte du contenu du lot (déterministe).
        fingerprint = hashlib.sha256(
            json.dumps(records_by_model, sort_keys=True, default=str, ensure_ascii=False).encode('utf-8')
        ).hexdigest()

        # Idempotence de lot (SYNC.md §3.3/§3.6) : un batch_id déjà traité PAR
        # CE NŒUD renvoie le résultat archivé sans ré-exécuter la logique
        # métier. Le journal est indexé sur (nœud, batch_id) : le lot d'un
        # autre nœud n'est jamais visible (BUG-726). Même batch_id avec un
        # contenu différent = conflit explicite, jamais avalé en silence.
        existing_batch = SyncBatchLog.objects.filter(node=node, batch_id=batch_id).first()
        if existing_batch is not None:
            if existing_batch.fingerprint and existing_batch.fingerprint != fingerprint:
                return Response(
                    {'detail': "Ce batch_id a déjà été utilisé avec un contenu différent : "
                               "générez un nouveau batch_id pour ce lot."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response({'batch_id': str(batch_id), 'results': existing_batch.result, 'replayed': True})

        results = process_push_batch(node, records_by_model)
        _store_mirrors(node, data.get('mirrors'))

        any_rejected = any(
            r.get('status') == 'REJECTED'
            for model_results in results.values()
            for r in model_results
        )
        batch_status = SyncBatchLog.Status.PARTIAL if any_rejected else SyncBatchLog.Status.OK

        SyncBatchLog.objects.create(
            batch_id=batch_id, node=node, status=batch_status, result=results, fingerprint=fingerprint,
        )
        Node.objects.filter(pk=node.pk).update(last_sync=timezone.now())

        return Response({'batch_id': str(batch_id), 'results': results, 'replayed': False})


def _parse_cursor(request, param_name, allow_future=False):
    raw = request.query_params.get(param_name)
    if not raw:
        return None
    # BUG-781 : curseur illisible ou hors plage = 400 explicite, jamais un 500.
    try:
        parsed = parse_datetime(raw) if len(raw) <= 64 else None
    except ValueError:
        parsed = None
    if parsed is None:
        raise ParseError(f"Paramètre « {param_name} » invalide : date/heure ISO 8601 attendue.")
    if timezone.is_naive(parsed):
        try:
            parsed = timezone.make_aware(parsed)
        except (ValueError, OverflowError):
            raise ParseError(f"Paramètre « {param_name} » invalide : date/heure hors plage.")
    # BUG-785 : curseur dans le futur (Cloud restauré, horloge déréglée) =
    # traité comme absent (pull complet), jamais « 0 client à jamais ».
    # BUG-1008 : sauf page de pagination (client_after_id) dont le curseur est l'updated_at d'une
    # vraie ligne, légèrement dans le futur en cas de décalage d'horloge (tolérance 1 h) : la rejeter
    # ferait reboucler sur la page 1. Un curseur très lointain reste traité comme absent.
    from datetime import timedelta
    # BUG-1010 : `allow_future` peut etre un datetime plafond (plus grand updated_at reel des clients) :
    # un curseur de page n'est jamais au-dela d'une ligne existante, meme si l'horloge Cloud derive de > 1 h.
    limit = timezone.now() + (timedelta(hours=1) if allow_future else timedelta(0))
    if allow_future is not True and hasattr(allow_future, 'isoformat') and allow_future > limit:
        limit = allow_future
    if parsed > limit:
        return None
    return parsed


# BUG-998 : taille maximale de la liste de clients par réponse de pull (`has_more` au-delà).
PULL_CLIENT_PAGE_SIZE = 5000


def _parse_after_id(raw):
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw)[:64])
    except (TypeError, ValueError):
        raise ParseError("Paramètre « client_after_id » invalide : UUID attendu.")


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
        ceiling = bool(request.query_params.get('client_after_id'))
        if ceiling:
            from django.db.models import Max
            from clients.models import Client as _C
            ceiling = _C.objects.aggregate(m=Max('updated_at'))['m'] or True
        since_client_debt = _parse_cursor(request, 'since_client_debt', allow_future=ceiling)

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
        # BUG-998 (CLAUDE.md 5.1) : un poste de boulangerie reçoit les clients ACTIFS de TOUTES
        # les boulangeries (un facturier recherche et facture hors ligne les clients des autres) ;
        # le nœud SIEGE garde le périmètre restreint (jamais le catalogue complet). Seules les
        # colonnes d'identité/plafond/dette du client descendent : ni factures ni mouvements.
        from sales.models import Invoice
        scope = Q(node=node) | Q(pk__in=Invoice.objects.filter(node=node).values('client_id'))
        if node.code != 'SIEGE':
            scope |= Q(is_active=True)
        # BUG-999 : au pull incrémentiel (pas au pull complet ni aux pages suivantes d'une marche
        # initiale), un client d'un autre nœud devenu INACTIF depuis le curseur redescend pour être
        # désactivé localement ; le curseur `updated_at` filtre ci-dessous. Jamais au pull initial.
        # BUG-1008 : le périmètre vaut pour TOUTES les pages d'un pull à curseur (pages 2+ incluses,
        # elles portent `client_after_id`). Sur une marche initiale, une page 2+ peut donc livrer
        # un inactif d'un autre nœud : le poste l'ignore s'il ne le connaît pas (jamais créé).
        if node.code != 'SIEGE' and since_client_debt is not None:
            scope |= Q(is_active=False)
        client_qs = Client.objects.filter(scope).select_related('node')
        # Curseur composite (updated_at, id) : pagination stable même à égalité d'horodatage.
        after_id = _parse_after_id(request.query_params.get('client_after_id'))
        if since_client_debt is not None:
            cond = Q(updated_at__gt=since_client_debt)
            if after_id is not None:
                cond |= Q(updated_at=since_client_debt, id__gt=after_id)
            client_qs = client_qs.filter(cond)
        client_qs = client_qs.order_by('updated_at', 'id')
        client_rows = list(client_qs[:PULL_CLIENT_PAGE_SIZE + 1])
        has_more = len(client_rows) > PULL_CLIENT_PAGE_SIZE
        client_rows = client_rows[:PULL_CLIENT_PAGE_SIZE]
        payload['clients'] = [
            {
                'id': str(c.id), 'code': c.code, 'current_debt': str(c.current_debt),
                'credit_limit': str(c.credit_limit), 'category': c.category,
                'first_name': c.first_name, 'last_name': c.last_name,
                'phone': c.phone, 'address': c.address,
                'updated_at': c.updated_at.isoformat(),
                # BUG-994 : de quoi créer le client sur un poste neuf (additif, cloud ancien = absent).
                'node': c.node.code, 'node_origin': c.node_origin,
                'commission_rate': str(c.commission_rate),
                'cotisation_sociale': str(c.cotisation_sociale) if c.cotisation_sociale is not None else None,
                'client_type': c.client_type, 'notes': c.notes,
                'total_breads_received': c.total_breads_received,
                'is_active': c.is_active,  # BUG-999 (additif)
            }
            for c in client_rows
        ]
        if has_more:
            # Page suivante : curseur = dernier client renvoyé (un poste ancien qui ignore
            # `has_more` reprend simplement au cycle suivant, sans rien perdre d'important).
            last = client_rows[-1]
            payload['since_client_debt'] = last.updated_at.isoformat()
            payload['client_after_id'] = str(last.id)
        else:
            payload['since_client_debt'] = now.isoformat()
        payload['has_more'] = has_more

        # BUG-964 (SYNC.md §5.3) : les transferts dont ce poste est émettrice OU
        # réceptrice (+ lignes) redescendent, pour que la réceptrice voie et valide
        # un envoi d'une autre boulangerie. Les transferts terminés depuis plus de
        # 30 jours ne sont plus renvoyés. Pas de curseur : lot petit, application idempotente.
        from datetime import timedelta
        from production.models import BreadTransfer
        recent = now - timedelta(days=30)
        # BUG-980 : un transfert terminé depuis > 30 jours reste descendu tant que le poste
        # déclare (push `open_transfers`) en avoir encore une copie non terminale.
        state = NodeOpenTransfers.objects.filter(node=node).first()
        open_ids = list(state.transfer_ids) if state else []
        terminal = ('CONFIRMED', 'CANCELLED')
        transfers_qs = BreadTransfer.objects.filter(
            Q(from_node=node) | Q(to_node=node)
        ).exclude(
            Q(transfer_status__in=terminal, updated_at__lt=recent) & ~Q(pk__in=open_ids),
        ).select_related('from_node', 'to_node').prefetch_related('lines')
        transfers, transfer_lines = [], []
        for t in transfers_qs:
            transfers.append({
                'id': str(t.id), 'from_node': t.from_node.code, 'to_node': t.to_node.code,
                'bread_price': t.bread_price_id, 'quantity_sent': t.quantity_sent,
                'quantity_received': t.quantity_received, 'transfer_status': t.transfer_status,
                'flow': t.flow, 'notes': t.notes, 'node_origin': t.node_origin,
                'updated_at': t.updated_at.isoformat(),
            })
            for l in t.lines.all():
                transfer_lines.append({
                    'transfer': str(t.id), 'bread_price': l.bread_price_id,
                    'quantity_sent': l.quantity_sent, 'quantity_received': l.quantity_received,
                })
        # BUG-983 : état des clôtures DU POSTE UNIQUEMENT (confirmée / infirmée + motif / versée),
        # pour que le gérant sache qu'il doit recompter. Lecture seule : aucun montant.
        from treasury.models import CashClosure
        payload['closures'] = [
            {'id': str(c.id), 'date': c.date.isoformat(), 'is_validated': c.is_validated,
             'is_rejected': c.is_rejected, 'rejection_reason': c.rejection_reason,
             'is_paid': c.cashbook_entries.exists()}
            for c in CashClosure.objects.filter(node=node, date__gte=(now - timedelta(days=60)).date())
        ]
        payload['transfers'] = transfers
        payload['transfer_lines'] = transfer_lines
        # BUG-989/990 : marqueur « miroir déjà appliqué par CE poste » pour les transferts
        # descendus ({} = cloud récent, aucun marqueur ; clé absente = cloud ancien).
        _bump_peaks(node, list(transfers_qs))
        by_id = {t.id: t for t in transfers_qs}
        payload['mirrors'] = {
            str(m.transfer_id): _clamped_mirror(m.applied, by_id[m.transfer_id])
            for m in TransferMirror.objects.filter(node=node, transfer_id__in=list(by_id))
            if m.applied
        }
        # BUG-975/976 : identité du poste pour que l'application locale sache s'il est
        # émettrice ou réceptrice (effets de stock miroir, alertes).
        payload['node_code'] = node.code
        delivered_terminal = {t['id'] for t in transfers if t['transfer_status'] in terminal}
        if state and delivered_terminal & set(open_ids):
            state.transfer_ids = sorted(set(open_ids) - delivered_terminal)
            state.save(update_fields=['transfer_ids', 'updated_at'])

        # BUG-1007 : pull abouti -> horodatage par transfert livré (critère « poste en retard »).
        for tid in by_id:
            TransferPull.objects.update_or_create(node=node, transfer_id=tid, defaults={'pulled_at': now})
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
