from datetime import date

from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import Node
from core.permissions import IsHeadquarters
from treasury.hashing import verify_cashbook_chain, check_cashbook_head
from .models import TamperAlert, BlockchainSnapshot
from .serializers import TamperAlertSerializer, BlockchainSnapshotSerializer

# BUG-001 : la boucle de vérification locale (hashlib.sha256 d'une
# concaténation f-string, différente de la formule JSON de `treasury`) a été
# supprimée. On utilise désormais `treasury.hashing.verify_cashbook_chain`,
# la même fonction que `treasury.views.CashbookEntryViewSet.integrity_check`.
#
# Important : le Livre de Caisse Direction est UNE SEULE chaîne globale
# (voir `treasury.views.append_cashbook_entry` / `_get_last_balance`, qui ne
# filtrent jamais par nœud) — chaque écriture est chaînée à la précédente
# toutes boulangeries confondues, pas dans une chaîne séparée par nœud.
# Vérifier uniquement le sous-ensemble d'un nœud en reconstruisant un
# chaînage local à partir du génésis (comme le faisait l'ancien code) ne
# peut donc jamais correspondre au `block_hash` réellement écrit, même avec
# une formule de hash identique, dès qu'un nœud n'est pas le tout premier
# contributeur de la chaîne. On vérifie donc la chaîne complète une seule
# fois, puis on ventile le résultat par nœud pour le reporting.


def _verify_full_chain():
    """Vérifie la chaîne globale du Livre de Caisse une seule fois.

    Retourne la liste ``(entry, expected_hash, is_valid)`` dans l'ordre du
    chaînage (voir `verify_cashbook_chain`).
    """
    from treasury.models import CashbookEntry

    entries = list(CashbookEntry.chain_queryset().select_related('node'))
    return verify_cashbook_chain(entries)


def _check_head():
    """BUG-240 : anomalie d'ancre de tête de chaîne (None si OK) et code du
    nœud de la dernière écriture enregistrée."""
    from treasury.models import CashbookEntry, CashbookHead

    head = CashbookHead.objects.first()
    entries = list(CashbookEntry.chain_queryset().only('block_hash'))
    problem = check_cashbook_head(entries, head)
    return problem, (head.last_node_code if head else '')


def _verify_chain_for_node(node, chain_results=None, head_problem=None) -> dict:
    """Stats d'intégrité pour un nœud, à partir du résultat de la chaîne
    globale (calculé une fois par `_verify_full_chain`, et réutilisable pour
    plusieurs nœuds dans `run_check` afin d'éviter de reparcourir la chaîne
    une fois par boulangerie).
    """
    if chain_results is None:
        chain_results = _verify_full_chain()

    total = 0
    tampered_ids = []
    for entry, _expected, is_valid in chain_results:
        if entry.node_id != node.id:
            continue
        total += 1
        if not is_valid:
            tampered_ids.append(str(entry.id))
            if not entry.is_tampered:
                entry.is_tampered = True
                entry.save(update_fields=['is_tampered'])

    return {
        'node_id':         node.id,
        'node_name':       node.name,
        'total_entries':   total,
        'tampered_count':  len(tampered_ids),
        'tampered_ids':    tampered_ids,
        'head_problem':    head_problem or '',
        'is_intact':       len(tampered_ids) == 0 and not head_problem,
    }


class TamperAlertViewSet(viewsets.ModelViewSet):
    queryset = TamperAlert.objects.all()
    serializer_class = TamperAlertSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'resolve'):
            return [IsHeadquarters()]
        return [IsHeadquarters()]

    def get_queryset(self):
        qs = super().get_queryset()
        node_id = self.request.query_params.get('node')
        if node_id:
            qs = qs.filter(node_id=node_id)
        resolved = self.request.query_params.get('resolved')
        if resolved is not None:
            qs = qs.filter(is_resolved=resolved.lower() == 'true')
        return qs

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        alert = self.get_object()
        if alert.is_resolved:
            return Response({'detail': 'Alerte déjà résolue.'}, status=status.HTTP_400_BAD_REQUEST)
        alert.is_resolved = True
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.save(update_fields=['is_resolved', 'resolved_by', 'resolved_at'])
        return Response(TamperAlertSerializer(alert).data)


class BlockchainSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BlockchainSnapshot.objects.all()
    serializer_class = BlockchainSnapshotSerializer
    permission_classes = [IsHeadquarters]

    def get_queryset(self):
        qs = super().get_queryset()
        node_id = self.request.query_params.get('node')
        if node_id:
            qs = qs.filter(node_id=node_id)
        return qs

    @action(detail=False, methods=['post'])
    def run_check(self, request):
        """
        Run integrity check on all nodes (or a specific node via ?node=id).
        Creates a BlockchainSnapshot and TamperAlert records for violations.
        """
        node_id = request.data.get('node') or request.query_params.get('node')
        nodes = Node.objects.filter(pk=node_id) if node_id else Node.objects.all()

        chain_results = _verify_full_chain()
        head_problem, head_node_code = _check_head()
        node_list = list(nodes)
        # L'anomalie de tête est imputée au nœud de la dernière écriture
        # connue (repli : premier nœud contrôlé).
        head_node = next((n for n in node_list if n.code == head_node_code), None)
        if head_problem and head_node is None and node_list:
            head_node = node_list[0]

        results = []
        for node in node_list:
            stats = _verify_chain_for_node(
                node, chain_results=chain_results,
                head_problem=head_problem if node is head_node else None,
            )

            # Persist snapshot
            snapshot, _ = BlockchainSnapshot.objects.update_or_create(
                node=node,
                snapshot_date=timezone.localdate(),
                defaults={
                    'total_entries':    stats['total_entries'],
                    'tampered_entries': stats['tampered_count'],
                    'is_intact':        stats['is_intact'],
                    'checked_by':       request.user,
                }
            )

            # Create tamper alert if chain broken
            if not stats['is_intact']:
                TamperAlert.objects.create(
                    node=node,
                    affected_model='CashbookEntry',
                    affected_id=', '.join(stats['tampered_ids'][:10]),
                    severity=TamperAlert.Severity.HIGH,
                    description=(
                        f"{stats['tampered_count']} écriture(s) falsifiée(s) détectée(s) "
                        f"sur le nœud {node.name}. IDs: {', '.join(stats['tampered_ids'][:5])}"
                        + (f" {stats['head_problem']}" if stats['head_problem'] else '')
                    ),
                )
                # Notify HQ admin.
                #
                # Correction (découverte pendant le travail sur BUG-001) :
                # cet appel utilisait `notification_type=` et `target_roles=`,
                # deux paramètres qui n'existent pas dans la signature de
                # `create_notification(title, message, severity='INFO',
                # node_origin='CLOUD')` (core/utils.py) — chaque détection
                # réelle de falsification faisait donc planter `run_check`
                # avec un `TypeError` avant de pouvoir répondre à l'appelant,
                # alors que c'est précisément le chemin d'alerte ADMIN/
                # DIRECTION que le cahier des charges et CLAUDE.md §6 exigent.
                # `create_notification` ne sait pas aujourd'hui cibler des
                # rôles précis (toutes les notifications sont visibles par
                # tous, comme ailleurs dans `treasury`/`sales`) : ajouter un
                # vrai ciblage par rôle dépasse le périmètre BUG-001/002/003
                # et est signalé au coordinateur dans le rapport plutôt que
                # tranché ici.
                from core.utils import create_notification
                create_notification(
                    title=f"ALERTE BLOCKCHAIN — {node.name}",
                    message=(
                        f"La chaîne de hachage du Livre de Caisse du nœud {node.name} "
                        f"est compromise ({stats['tampered_count']} entrée(s) falsifiée(s))."
                    ),
                    severity='DANGER',
                    node_origin=node.code,
                )

            results.append(stats)

        return Response({
            'checked_nodes': len(results),
            'check_date':    timezone.localdate(),
            'results':       results,
            'all_intact':    all(r['is_intact'] for r in results),
        })

    @action(detail=False, methods=['get'])
    def global_status(self, request):
        """Summary of latest snapshot per node."""
        from django.db.models import Max

        latest_dates = BlockchainSnapshot.objects.values('node').annotate(latest=Max('snapshot_date'))
        summaries = []
        for row in latest_dates:
            snap = BlockchainSnapshot.objects.filter(node_id=row['node'], snapshot_date=row['latest']).first()
            if snap:
                summaries.append(BlockchainSnapshotSerializer(snap).data)

        open_alerts = TamperAlert.objects.filter(is_resolved=False).count()
        return Response({
            'open_alerts':      open_alerts,
            'nodes_checked':    len(summaries),
            'all_intact':       all(s['is_intact'] for s in summaries),
            'node_snapshots':   summaries,
        })
