from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError
from django.db.models import Sum, DecimalField, ExpressionWrapper, F
from django.utils import timezone
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from core.models import Config, Node, BreadPrice
from core.permissions import IsGerant, IsHeadquarters
from core.utils import log_activity, create_notification
from .models import ProductionSession, ProductionSessionLine, BreadStock, ConsumableType, ConsumableStock, ConsumableMovement, ConsumableCount, BreadTransfer, BreadTransferLine, BreadDisposal, DailyBreadStockSnapshot, _adjust_bread_stock
from .serializers import (
    ProductionSessionSerializer, BreadStockSerializer, ConsumableTypeSerializer, ConsumableStockSerializer,
    ConsumableMovementSerializer, ConsumableCountSerializer, BreadTransferSerializer, BreadDisposalSerializer,
)

_SESSION_COMPUTED_FIELDS = [
    'total_breads', 'total_fc_produced', 'theoretical_yield', 'yield_gap',
    'breads_300', 'breads_400', 'breads_500', 'breads_1000', 'sac_value_fc_used',
]


def _effective_sac_value(node, config):
    """
    Valeur théorique par sac de farine (FC) à utiliser pour une boulangerie :
    celle de la Succursale (Node.sac_value_fc) si elle est renseignée et non
    nulle, sinon la valeur par défaut de la Configuration globale.
    """
    if node.sac_value_fc:
        return int(node.sac_value_fc)
    return config.sac_value_fc


def _record_consumable_exits(session, user, extra_consumables=None):
    """
    Create ConsumableMovement EXIT records for all consumables used in a session.
    - Flour is auto-derived from session.flour_sacks_used.
    - extra_consumables: list of {consumable_type, quantity} dicts for salt/yeast/oil.
    Each creation triggers ConsumableMovement.save() which decrements ConsumableStock
    (BUG-041 : refuse — ValidationError — si la sortie dépasse le stock disponible).

    Retourne la liste des (consumable_type, quantity) effectivement traités,
    pour que l'appelant puisse en déduire l'alerte de surconsommation (BUG-040).
    """
    from django.db import transaction
    node = session.node
    desc = f"Fournée Éq.{session.team} {session.date}"
    entries = [('FLOUR', session.flour_sacks_used)]
    if extra_consumables:
        for cu in extra_consumables:
            ct  = cu.get('consumable_type', '')
            qty = cu.get('quantity', 0)
            if ct and float(qty or 0) > 0:
                entries.append((ct, qty))
    processed = []
    with transaction.atomic():
        for ct, qty in entries:
            if not qty or float(qty) <= 0:
                continue
            stock = ConsumableStock.objects.filter(node=node, consumable_type=ct).first()
            if stock:
                ConsumableMovement.objects.create(
                    node=node, stock=stock, session=session,
                    movement_type=ConsumableMovement.MovementType.EXIT,
                    quantity=qty, description=desc,
                    recorded_by=user, node_origin=node.code,
                )
                processed.append((ct, qty))
    return processed


# BUG-040 : au-delà de ce facteur par rapport à la moyenne historique de
# consommation par sac (pour ce consommable, cette boulangerie), on considère
# qu'il s'agit d'une surconsommation à signaler. Choix documenté : ×2 — assez
# large pour ne pas déclencher sur la variabilité normale d'une fournée, mais
# détecte un écart manifeste (le scénario de référence CLAUDE.md est de l'ordre
# de ×10). Nécessite au moins une fournée de référence pour ce consommable,
# sinon il n'y a pas de moyenne à comparer et aucune alerte n'est levée.
_OVERCONSUMPTION_FACTOR = 2


def _check_overconsumption(session, processed_entries):
    from decimal import Decimal, InvalidOperation
    sacks = Decimal(str(session.flour_sacks_used or 0))
    if sacks <= 0:
        return
    node = session.node
    for ct, qty in processed_entries:
        try:
            qty_dec = Decimal(str(qty))
        except InvalidOperation:
            continue
        if qty_dec <= 0:
            continue
        current_ratio = qty_dec / sacks

        history = ConsumableMovement.objects.filter(
            node=node, stock__consumable_type=ct,
            movement_type=ConsumableMovement.MovementType.EXIT,
            session__isnull=False,
        ).exclude(session=session).select_related('session')

        total_qty   = Decimal('0')
        total_sacks = Decimal('0')
        for m in history:
            s = m.session
            if s and s.flour_sacks_used:
                total_qty   += m.quantity
                total_sacks += Decimal(str(s.flour_sacks_used))

        if total_sacks <= 0:
            continue  # aucune fournée de référence pour ce consommable

        average_ratio = total_qty / total_sacks
        if average_ratio > 0 and current_ratio > average_ratio * _OVERCONSUMPTION_FACTOR:
            create_notification(
                title=f"Surconsommation {ct} — {node.code}",
                message=(
                    f"Session Éq.{session.team} du {session.date} : {qty_dec} {ct} pour "
                    f"{sacks} sac(s) ({current_ratio:.3f}/sac), soit plus de {_OVERCONSUMPTION_FACTOR}× "
                    f"la moyenne historique ({average_ratio:.3f}/sac)."
                ),
                severity='WARNING', node_origin=node.code,
            )


def _build_reconciliation_querysets(user, node_id=None, date=None, date_from=None, date_to=None):
    """
    BUG-093 : factorise les filtres partagés par l'action `reconciliation`
    (lecture seule, période libre) et l'action `close` (un jour/nœud donné)
    pour ne jamais faire diverger les deux calculs. Mêmes règles qu'avant
    (BUG-043) : filtrage par `user.node` pour un non-HQ, sinon par `node_id`
    si fourni ; `date` seule ou plage `date_from`/`date_to`.
    """
    from sales.models import Invoice

    sessions_qs = ProductionSession.objects.all()
    disposals_qs = BreadDisposal.objects.exclude(disposal_type=BreadDisposal.DisposalType.REMAINING)
    invoices_qs = Invoice.objects.filter(status=Invoice.Status.DELIVERED)

    if not user.can_access_all_nodes and user.node_id:
        sessions_qs  = sessions_qs.filter(node=user.node)
        disposals_qs = disposals_qs.filter(node=user.node)
        invoices_qs  = invoices_qs.filter(node=user.node)
    elif node_id:
        sessions_qs  = sessions_qs.filter(node_id=node_id)
        disposals_qs = disposals_qs.filter(node_id=node_id)
        invoices_qs  = invoices_qs.filter(node_id=node_id)

    if date:
        sessions_qs  = sessions_qs.filter(date=date)
        disposals_qs = disposals_qs.filter(session__date=date)
        invoices_qs  = invoices_qs.filter(invoice_date=date)
    else:
        if date_from:
            sessions_qs  = sessions_qs.filter(date__gte=date_from)
            disposals_qs = disposals_qs.filter(session__date__gte=date_from)
            invoices_qs  = invoices_qs.filter(invoice_date__gte=date_from)
        if date_to:
            sessions_qs  = sessions_qs.filter(date__lte=date_to)
            disposals_qs = disposals_qs.filter(session__date__lte=date_to)
            invoices_qs  = invoices_qs.filter(invoice_date__lte=date_to)

    return sessions_qs, disposals_qs, invoices_qs


def _compute_reconciliation(sessions_qs, disposals_qs, invoices_qs):
    """
    BUG-093/BUG-043 : écart = production déclarée − (ventes + retours), en
    pains et en FC. Logique de calcul isolée (sans filtrage) pour être
    partagée à l'identique par `reconciliation` (lecture seule) et `close`
    (clôture), sans jamais être dupliquée.
    """
    from sales.models import InvoiceLine

    produced_breads = sessions_qs.aggregate(t=Sum('total_breads'))['t'] or 0
    produced_fc     = sessions_qs.aggregate(t=Sum('total_fc_produced'))['t'] or 0

    sold_lines   = InvoiceLine.objects.filter(invoice__in=invoices_qs)
    sold_breads  = sold_lines.aggregate(t=Sum('quantity'))['t'] or 0
    sold_fc      = sold_lines.aggregate(t=Sum('line_total'))['t'] or 0

    returned_breads = disposals_qs.aggregate(t=Sum('quantity'))['t'] or 0
    returned_fc     = disposals_qs.aggregate(t=Sum('total_value'))['t'] or 0

    gap_breads = produced_breads - (sold_breads + returned_breads)
    gap_fc     = produced_fc - (sold_fc + returned_fc)

    return {
        'production_declared':  {'breads': produced_breads, 'fc': str(produced_fc)},
        'sales':                {'breads': sold_breads, 'fc': str(sold_fc)},
        'returns':              {'breads': returned_breads, 'fc': str(returned_fc)},
        'gap':                  {'breads': gap_breads, 'fc': str(gap_fc)},
    }


class ProductionSessionViewSet(viewsets.ModelViewSet):
    queryset = ProductionSession.objects.select_related('node', 'declared_by').all()
    serializer_class = ProductionSessionSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'team', 'date', 'is_closed']
    ordering_fields  = ['date', 'created_at']
    ordering         = ['-date']

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsGerant()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        params = self.request.query_params
        if params.get('date_from'):
            qs = qs.filter(date__gte=params['date_from'])
        if params.get('date_to'):
            qs = qs.filter(date__lte=params['date_to'])
        return qs

    def perform_create(self, serializer):
        config = Config.get_instance()
        user   = self.request.user
        if not user.can_access_all_nodes:
            # BUG-056 : comme pour ConsumableMovementViewSet (BUG-022) et
            # ClientViewSet (BUG-025), on ignore toute valeur de `node`
            # envoyée dans le payload pour un non-HQ — un GERANT ne doit
            # jamais pouvoir déclarer une fournée pour une autre boulangerie.
            node = user.node
        else:
            node = serializer.validated_data.get('node') or user.node
        if node is None:
            raise ValidationError({'node': 'Compte non assigné à une boulangerie. Précisez le nœud.'})
        try:
            session = serializer.save(
                declared_by=user,
                node=node,
                node_origin=node.code,
            )
        except IntegrityError:
            team = serializer.validated_data.get('team', '?')
            date = serializer.validated_data.get('date', '?')
            raise ValidationError(
                f"Une session existe déjà pour l'Équipe {team} le {date} à la boulangerie {node.code}."
            )
        session.compute_totals(_effective_sac_value(node, config))
        session.save(update_fields=_SESSION_COMPUTED_FIELDS)

        for line in session.lines.select_related('bread_price').all():
            _adjust_bread_stock(session.node, line.bread_price, produced=line.quantity)

        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            processed_entries = _record_consumable_exits(
                session, user,
                extra_consumables=self.request.data.get('consumables_used', []),
            )
        except DjangoValidationError as exc:
            # BUG-041 : une sortie de consommable dépassant le stock
            # disponible est refusée — traduite en 400 propre.
            raise ValidationError({'detail': exc.messages[0] if hasattr(exc, 'messages') else str(exc)})

        _check_overconsumption(session, processed_entries)

        if session.yield_gap < 0:
            create_notification(
                title=f"Manquant de Rendement — {session.node.code}",
                message=(
                    f"Session Éq.{session.team} du {session.date} : "
                    f"manquant de {abs(session.yield_gap):,} FC "
                    f"(Théorique : {session.theoretical_yield:,} FC, "
                    f"Réel : {session.total_fc_produced:,} FC)."
                ),
                severity='WARNING', node_origin=session.node.code
            )
        log_activity(
            self.request.user, "Déclaration Production",
            f"{session.node.code} Éq.{session.team} {session.date} : "
            f"{session.flour_sacks_used} sacs → {session.total_breads} pains "
            f"({session.total_fc_produced:,} FC).",
            node_origin=session.node_origin
        )

    def perform_update(self, serializer):
        # BUG-093 : une session clôturée (action `close`) est figée — même
        # logique que `CashClosure.perform_update` (treasury/views.py,
        # BUG-034) : une fois le recoupement automatique validé, la laisser
        # divergente créerait un trou d'audit sur la production déclarée.
        if serializer.instance.is_closed:
            raise ValidationError({
                'detail': "Session de production clôturée — modification impossible."
            })
        # Snapshot old lines BEFORE serializer.save() wipes them
        old_lines = {
            line.bread_price_id: (line.bread_price, line.quantity)
            for line in serializer.instance.lines.select_related('bread_price').all()
        }
        user = self.request.user
        if not user.can_access_all_nodes:
            # BUG-056 : un non-HQ ne peut jamais réaffecter une session
            # existante à une autre boulangerie via `node` dans le payload —
            # on impose le nœud déjà présent sur l'instance (qui est déjà
            # filtrée par get_queryset() sur user.node pour ce profil).
            session = serializer.save(node=serializer.instance.node, node_origin=serializer.instance.node.code)
        else:
            session = serializer.save()
        # BUG-038 : ne JAMAIS relire _effective_sac_value() ici — une édition
        # ultérieure (même sans rapport avec la valeur du sac) ne doit pas
        # faire glisser l'historique vers la valeur du sac courante. On
        # réutilise la valeur figée à la déclaration initiale
        # (session.sac_value_fc_used), déjà conservée en base.
        session.compute_totals(session.sac_value_fc_used)
        session.save(update_fields=_SESSION_COMPUTED_FIELDS)
        # Reverse old, apply new (delta keeps stock accurate on edits)
        for bp_id, (bp, old_qty) in old_lines.items():
            _adjust_bread_stock(session.node, bp, produced=-old_qty)
        for line in session.lines.select_related('bread_price').all():
            _adjust_bread_stock(session.node, line.bread_price, produced=line.quantity)

    @action(detail=False, methods=['get'])
    def reconciliation(self, request):
        """
        BUG-043 : écart = production déclarée − (ventes + retours), en pains
        et en FC, pour une boulangerie et une période données (CLAUDE.md
        §5.4). Filtres : `node` (requis sauf HQ qui liste tout), et soit
        `date` seule, soit `date_from`/`date_to`.

        BUG-093 : lecture seule, toujours disponible (y compris après
        clôture d'une session) — la logique de calcul est partagée avec
        l'action `close` via `_build_reconciliation_querysets`/
        `_compute_reconciliation` pour ne jamais diverger entre les deux.
        """
        from sales.models import Invoice

        params   = request.query_params
        node_id  = params.get('node')
        date     = params.get('date')
        date_from = params.get('date_from')
        date_to   = params.get('date_to')

        sessions_qs, disposals_qs, invoices_qs = _build_reconciliation_querysets(
            user=request.user, node_id=node_id, date=date, date_from=date_from, date_to=date_to,
        )
        result = _compute_reconciliation(sessions_qs, disposals_qs, invoices_qs)

        user = request.user
        return Response({
            'node': node_id or (user.node.pk if user.node_id else None),
            'date': date, 'date_from': date_from, 'date_to': date_to,
            **result,
        })

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """
        BUG-093 (remarque.md, section Clôture, point 2) : clôture d'une
        fournée. Le gérant continue de saisir manuellement les sacs de
        farine et le total de pains sortis du four par catégorie (`lines`,
        inchangé) ; tout le reste devient automatique à la clôture :
        - Ventes réelles : `InvoiceLine` des factures `DELIVERED` du jour
          pour ce nœud (même logique que l'action `reconciliation`).
        - Dispositions : `BreadDisposal` (soldés/déclassés/invendus/dons) du
          jour pour ce nœud, hors `REMAINING` (même logique).
        - Reliquat NV (non vendu, à reporter) = produit − vendu − disposé,
          s'il est positif. S'il est négatif (plus vendu/disposé que
          déclaré produit), c'est une anomalie à signaler — la clôture
          n'est PAS bloquée pour autant (décision du coordinateur : on
          signale, on ne bloque pas silencieusement).
        - Fige `is_closed=True` et `closed_at` ; la session devient alors
          non modifiable (voir `perform_update`). Un snapshot du
          recoupement est conservé dans `closure_summary` pour ne jamais
          dépendre d'un recalcul qui pourrait dériver plus tard (ex. l'autre
          équipe clôture après coup le même jour/nœud).
        """
        session = self.get_object()
        if session.is_closed:
            return Response(
                {'detail': "Session de production déjà clôturée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sessions_qs, disposals_qs, invoices_qs = _build_reconciliation_querysets(
            user=request.user, node_id=session.node_id, date=str(session.date),
        )
        result = _compute_reconciliation(sessions_qs, disposals_qs, invoices_qs)

        reliquat_breads = result['gap']['breads']
        is_anomaly = reliquat_breads < 0
        nv_breads = reliquat_breads if reliquat_breads > 0 else 0

        summary = {
            **result,
            'nv': {'breads': nv_breads},
            'anomaly': is_anomaly,
        }

        session.is_closed = True
        session.closed_at = timezone.now()
        session.closure_summary = summary
        session.save(update_fields=['is_closed', 'closed_at', 'closure_summary'])

        # BUG-118 (extension équipe, confirmée par le client le 2026-11-01) :
        # capture l'instantané du solde DÉCLARÉ par CETTE équipe (RESTE DU
        # JOUR), par catégorie de pain, pour le nœud/date/équipe de cette
        # session. Borné par équipe : ne peut jamais écraser le snapshot
        # d'une autre équipe clôturant le même jour (voir
        # DailyBreadStockSnapshot.record_snapshot docstring).
        DailyBreadStockSnapshot.record_snapshot(session)

        if is_anomaly:
            create_notification(
                title=f"Anomalie Clôture Production — {session.node.code}",
                message=(
                    f"Session Éq.{session.team} du {session.date} : ventes/dispositions "
                    f"({result['sales']['breads'] + result['returns']['breads']} pains) "
                    f"dépassent la production déclarée ({result['production_declared']['breads']} "
                    f"pains) — écart de {abs(reliquat_breads)} pain(s) à investiguer."
                ),
                severity='DANGER', node_origin=session.node.code,
            )

        log_activity(
            request.user, "Clôture Production",
            f"{session.node.code} Éq.{session.team} {session.date} clôturée : "
            f"produit {result['production_declared']['breads']}, vendu "
            f"{result['sales']['breads']}, disposé {result['returns']['breads']}, "
            f"NV {nv_breads}" + (" (anomalie)" if is_anomaly else "") + ".",
            node_origin=session.node_origin,
        )

        return Response(ProductionSessionSerializer(session).data)


class ConsumableTypeViewSet(viewsets.ModelViewSet):
    """Admin-managed list of consumable types (Configuration). Open-ended —
    la Direction peut en ajouter de nouveaux, ils apparaissent automatiquement
    dans "Stocks Consommables" (compte de stock auto-créé au prochain accès)."""
    queryset = ConsumableType.objects.all()
    serializer_class = ConsumableTypeSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsHeadquarters()]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if ConsumableStock.objects.filter(consumable_type=instance.code).exclude(quantity=0).exists():
            return Response(
                {'detail': "Impossible de supprimer : des stocks non nuls existent encore pour ce consommable. Désactivez-le plutôt."},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)


class ConsumableStockViewSet(viewsets.ModelViewSet):
    queryset = ConsumableStock.objects.select_related('node').all()
    serializer_class = ConsumableStockSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['node', 'consumable_type']
    permission_classes = [IsAuthenticated]

    def _ensure_stock_accounts(self):
        """
        Auto-crée les comptes de stock manquants pour chaque ConsumableType
        actif, pour les boulangeries concernées par cette requête — sinon un
        type ajouté en Configuration n'apparaît jamais dans "Stocks
        Consommables" tant qu'aucun compte n'existe (ex: pour un utilisateur
        Direction qui filtre par boulangerie via ?node=, ou qui liste toutes
        les boulangeries d'un coup).
        """
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            target_nodes = [user.node]
        else:
            node_param = self.request.query_params.get('node')
            if node_param:
                try:
                    target_nodes = list(Node.objects.filter(pk=node_param))
                except (ValueError, TypeError):
                    target_nodes = []
            else:
                target_nodes = list(Node.objects.filter(is_active=True))
        if not target_nodes:
            return
        active_types = list(ConsumableType.objects.filter(is_active=True))
        if not active_types:
            return
        existing = set(
            ConsumableStock.objects.filter(node__in=target_nodes)
            .values_list('node_id', 'consumable_type')
        )
        to_create = [
            ConsumableStock(node=n, consumable_type=ct.code, unit=ct.unit, node_origin=n.code)
            for n in target_nodes for ct in active_types
            if (n.id, ct.code) not in existing
        ]
        if to_create:
            ConsumableStock.objects.bulk_create(to_create, ignore_conflicts=True)

    def get_queryset(self):
        self._ensure_stock_accounts()
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        return qs


class ConsumableMovementViewSet(viewsets.ModelViewSet):
    queryset = ConsumableMovement.objects.select_related('node', 'stock', 'session', 'recorded_by').all()
    serializer_class = ConsumableMovementSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'movement_type', 'stock']
    ordering         = ['-created_at']
    permission_classes = [IsGerant]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            # BUG-022 : aucun filtrage par nœud auparavant.
            qs = qs.filter(node=user.node)
        return qs

    def perform_create(self, serializer):
        from django.core.exceptions import ValidationError as DjangoValidationError
        user = self.request.user
        if not user.can_access_all_nodes:
            # BUG-022 (écriture) : `serializer.validated_data.get('node')`
            # donnait la priorité au payload — un GERANT non-HQ pouvait
            # modifier un stock d'une autre boulangerie en forgeant `node`.
            # On ignore toute valeur envoyée et on impose le nœud de
            # l'utilisateur, comme pour ClientViewSet (BUG-025).
            node = user.node
        else:
            node = serializer.validated_data.get('node') or user.node
            if node is None:
                stock = serializer.validated_data.get('stock')
                if stock:
                    node = stock.node
        try:
            serializer.save(
                recorded_by=user,
                node=node,
                node_origin=node.code if node else 'CLOUD',
            )
        except DjangoValidationError as exc:
            # BUG-041 : ConsumableMovement.save() refuse une sortie qui
            # dépasserait le stock disponible — on la traduit en 400 propre
            # plutôt que de laisser remonter une erreur serveur.
            raise ValidationError({'detail': exc.messages[0] if hasattr(exc, 'messages') else str(exc)})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def flour_history(self, request):
        """ENTRY movements for FLOUR, annotated with total_cost."""
        params  = request.query_params
        node_id = params.get('node')
        month   = params.get('month')
        year    = params.get('year')

        qs = ConsumableMovement.objects.filter(
            movement_type=ConsumableMovement.MovementType.ENTRY,
            stock__consumable_type='FLOUR',
        ).select_related('node', 'stock', 'recorded_by').order_by('-created_at')

        if node_id:
            qs = qs.filter(node_id=node_id)
        elif not request.user.can_access_all_nodes and request.user.node_id:
            qs = qs.filter(node=request.user.node)
        if month:
            qs = qs.filter(created_at__month=month)
        if year:
            qs = qs.filter(created_at__year=year)

        from decimal import Decimal
        return Response([
            {
                'id':          m.id,
                'date':        m.created_at.strftime('%Y-%m-%d'),
                'node':        m.node.code,
                'supplier':    m.supplier,
                'quantity':    str(m.quantity),
                'unit_price':  str(m.unit_price),
                'total_cost':  str(m.quantity * (m.unit_price or Decimal('0'))),
                'description': m.description,
            }
            for m in qs
        ])


class ConsumableCountViewSet(viewsets.ModelViewSet):
    """Physical inventory counts per bakery per consumable."""
    queryset = ConsumableCount.objects.select_related('node', 'counted_by').all()
    serializer_class = ConsumableCountSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'consumable_type', 'count_date']
    ordering         = ['-count_date', '-created_at']
    permission_classes = [IsGerant]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        node = user.node
        if user.can_access_all_nodes:
            node_id = self.request.data.get('node')
            if node_id:
                try:
                    node = Node.objects.get(pk=node_id)
                except Node.DoesNotExist:
                    pass
        if not node:
            raise ValidationError({'node': 'Boulangerie requise.'})

        consumable_type = serializer.validated_data['consumable_type']
        physical_qty    = serializer.validated_data['physical_quantity']

        stock = ConsumableStock.objects.filter(node=node, consumable_type=consumable_type).first()
        system_qty = stock.quantity if stock else 0

        serializer.save(
            node=node,
            counted_by=user,
            system_quantity=system_qty,
            gap=physical_qty - system_qty,
        )


class BreadTransferViewSet(viewsets.ModelViewSet):
    queryset = BreadTransfer.objects.select_related(
        'from_node', 'to_node', 'bread_price', 'initiated_by', 'confirmed_by'
    ).all()
    serializer_class = BreadTransferSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['from_node', 'to_node', 'transfer_status']
    ordering         = ['-created_at']

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsGerant()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            # BUG-023 : un transfert implique toujours deux boulangeries
            # (from_node/to_node) — un gérant ne doit voir que les transferts
            # où la sienne est impliquée, pas ceux entre deux autres nœuds.
            from django.db.models import Q
            qs = qs.filter(Q(from_node=user.node) | Q(to_node=user.node))
        return qs

    def _check_node_involved(self, request, *allowed_nodes):
        """BUG-023 : refuse l'accès si l'utilisateur n'appartient à aucune
        des boulangeries concernées par le transfert (sauf siège/HQ)."""
        user = request.user
        if user.can_access_all_nodes:
            return
        if user.node_id and any(node_id == user.node_id for node_id in allowed_nodes):
            return
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied(
            "Vous n'êtes pas autorisé à agir sur un transfert qui ne concerne pas votre boulangerie."
        )

    def perform_create(self, serializer):
        """
        A (to_node) requests bread FROM B (from_node).
        to_node  = user's own node (the requester).
        from_node = the bakery A is requesting stock from (sent in payload).
        No stock change at creation — it's just a request.
        """
        from core.models import BreadPrice as BP
        user = self.request.user
        transfer = serializer.save(
            initiated_by=user,
            to_node=user.node,  # requester is always the caller's own node
            node_origin=user.node.code if user.node else 'CLOUD',
        )
        lines_data = self.request.data.get('lines', [])
        for ld in lines_data:
            bp_id = ld.get('bread_price')
            qty   = int(ld.get('quantity_sent', 0))
            if bp_id and qty > 0:
                try:
                    bp = BP.objects.get(pk=bp_id)
                    BreadTransferLine.objects.create(
                        transfer=transfer, bread_price=bp, quantity_sent=qty,
                    )
                except BP.DoesNotExist:
                    pass
        lines = transfer.lines.select_related('bread_price').all()
        summary = ', '.join(f"{l.quantity_sent}×{l.bread_price.label}" for l in lines) or '—'
        create_notification(
            title=f"Demande de Pains — {transfer.from_node.code}",
            message=(
                f"La boulangerie {transfer.to_node.code} vous demande {summary}. "
                f"Veuillez répondre à cette demande (accepter ou refuser)."
            ),
            severity='INFO', node_origin=transfer.from_node.code
        )

    @action(detail=True, methods=['post'])
    def respond_to_request(self, request, pk=None):
        """
        Supplying bakery (from_node = B) responds to the request:
        - approved=True  → B fills quantities they'll send → B's stock deducted → status RESPONDED
        - approved=False → B rejects → status CANCELLED
        """
        transfer = self.get_object()
        # BUG-023 : seule la boulangerie fournisseuse (from_node) peut
        # répondre à la demande — pas le demandeur lui-même (to_node), même
        # si get_queryset() le laisse voir le transfert.
        self._check_node_involved(request, transfer.from_node_id)
        if transfer.transfer_status != BreadTransfer.TransferStatus.PENDING:
            return Response(
                {'detail': f"Transfert déjà au statut « {transfer.get_transfer_status_display()} »."},
                status=status.HTTP_400_BAD_REQUEST
            )

        approved = bool(request.data.get('approved', True))

        if not approved:
            transfer.transfer_status = BreadTransfer.TransferStatus.CANCELLED
            transfer.save(update_fields=['transfer_status'])
            create_notification(
                title=f"Demande Refusée — {transfer.to_node.code}",
                message=f"La boulangerie {transfer.from_node.code} n'a pas le stock disponible pour votre demande.",
                severity='WARNING', node_origin=transfer.to_node.code
            )
            log_activity(
                request.user, "Refus Demande Transfert",
                f"{transfer.from_node.code} a refusé la demande de {transfer.to_node.code}.",
                node_origin=transfer.from_node.code
            )
            return Response(BreadTransferSerializer(transfer).data)

        lines_data = request.data.get('lines', [])
        if not lines_data:
            return Response({'detail': '`lines` est requis pour une réponse positive.'}, status=status.HTTP_400_BAD_REQUEST)

        for ld in lines_data:
            bp_id    = ld.get('bread_price')
            qty_send = int(ld.get('quantity_sent', 0))
            try:
                line = transfer.lines.get(bread_price_id=bp_id)
                line.quantity_sent = qty_send  # B confirms/adjusts the quantity they'll send
                line.save(update_fields=['quantity_sent'])
            except BreadTransferLine.DoesNotExist:
                continue

        # Deduct B's stock now that bread physically leaves
        for line in transfer.lines.select_related('bread_price').all():
            if line.quantity_sent > 0:
                _adjust_bread_stock(transfer.from_node, line.bread_price, sent=line.quantity_sent)

        transfer.transfer_status = BreadTransfer.TransferStatus.RESPONDED
        transfer.save(update_fields=['transfer_status'])

        lines = transfer.lines.select_related('bread_price').all()
        summary = ', '.join(f"{l.quantity_sent}×{l.bread_price.label}" for l in lines) or '—'
        create_notification(
            title=f"Pains Envoyés — {transfer.to_node.code}",
            message=(
                f"La boulangerie {transfer.from_node.code} vous envoie {summary}. "
                f"Veuillez confirmer la réception."
            ),
            severity='INFO', node_origin=transfer.to_node.code
        )
        log_activity(
            request.user, "Réponse Positive Transfert",
            f"{transfer.from_node.code} envoie {summary} à {transfer.to_node.code}.",
            node_origin=transfer.from_node.code
        )
        return Response(BreadTransferSerializer(transfer).data)

    @action(detail=True, methods=['post'])
    def confirm_reception(self, request, pk=None):
        """
        Requesting bakery (to_node = A) confirms what they actually received.
        Credits A's stock. Status → CONFIRMED or DISPUTED.
        """
        transfer = self.get_object()
        # BUG-023 : seule la boulangerie destinataire (to_node) peut
        # confirmer la réception — pas l'émettrice (from_node) elle-même.
        self._check_node_involved(request, transfer.to_node_id)
        if transfer.transfer_status != BreadTransfer.TransferStatus.RESPONDED:
            return Response(
                {'detail': f"Le transfert doit être au statut 'Réceptionné' pour être confirmé (statut : {transfer.get_transfer_status_display()})."},
                status=status.HTTP_400_BAD_REQUEST
            )

        lines_data = request.data.get('lines', [])
        if not lines_data:
            return Response({'detail': '`lines` est requis.'}, status=status.HTTP_400_BAD_REQUEST)

        has_dispute = False
        for ld in lines_data:
            bp_id        = ld.get('bread_price')
            qty_received = int(ld.get('quantity_received', 0))
            try:
                line = transfer.lines.get(bread_price_id=bp_id)
                line.quantity_received = qty_received
                line.save(update_fields=['quantity_received'])
            except BreadTransferLine.DoesNotExist:
                continue
            _adjust_bread_stock(transfer.to_node, line.bread_price, received=qty_received)
            if qty_received != line.quantity_sent:
                has_dispute = True

        transfer.confirmed_by = request.user
        if has_dispute:
            transfer.transfer_status = BreadTransfer.TransferStatus.DISPUTED
            details = '; '.join(
                f"{l.bread_price.label}: envoyé {l.quantity_sent}→reçu {l.quantity_received or 0}"
                for l in transfer.lines.select_related('bread_price').all()
            )
            create_notification(
                title=f"Litige Transfert — {transfer.from_node.code}→{transfer.to_node.code}",
                message=f"Écart détecté. {details}.",
                severity='DANGER', node_origin='CLOUD'
            )
        else:
            transfer.transfer_status = BreadTransfer.TransferStatus.CONFIRMED
        # BUG-120 : `updated_at` (auto_now) doit être persisté ici — le
        # rapport de clôture consolidé (`DailyClosureReportView`) filtre les
        # transferts « confirmés ce jour » sur cette colonne (aucune autre
        # date de confirmation n'existe sur ce modèle). Sans l'ajouter à
        # `update_fields`, Django calcule bien la valeur en mémoire mais ne
        # la persiste jamais (update_fields explicite = seules ces colonnes
        # sont écrites en base), laissant `updated_at` figé à la création du
        # transfert (étape `respond_to_request`) au lieu de sa confirmation.
        transfer.save(update_fields=['transfer_status', 'confirmed_by', 'updated_at'])

        log_activity(
            request.user, "Réception Confirmée",
            f"Transfert {transfer.from_node.code}→{transfer.to_node.code} réceptionné par {request.user}.",
            node_origin=transfer.to_node.code
        )
        return Response(BreadTransferSerializer(transfer).data)


class BreadStockViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only bread inventory per bakery. Updated by production/transfer/disposal events."""
    queryset = BreadStock.objects.select_related('node', 'bread_price').all()
    serializer_class = BreadStockSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['node', 'bread_price']
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        return qs


class BreadDisposalViewSet(viewsets.ModelViewSet):
    queryset = BreadDisposal.objects.select_related('node', 'session', 'bread_price').all()
    serializer_class = BreadDisposalSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'session', 'disposal_type', 'bread_price']
    ordering         = ['-created_at']
    permission_classes = [IsGerant]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        return qs

    def perform_create(self, serializer):
        # BUG-092 : la vente soldée (CLAUDE.md §5.1, prix à 75 %) passe
        # désormais exclusivement par la facturation (`sales.Invoice.is_soldee`,
        # qui rattache la vente à un client, calcule le prix réduit et la
        # perte) — plus par ce type de `BreadDisposal`, qui n'avait ni client,
        # ni prix catalogue de référence, ni calcul de perte. On bloque donc
        # uniquement la CRÉATION de nouvelles entrées `SOLD_DISCOUNT` ; les
        # entrées historiques restent lisibles et modifiables normalement
        # (aucune suppression, aucun changement de lecture).
        if serializer.validated_data.get('disposal_type') == BreadDisposal.DisposalType.SOLD_DISCOUNT:
            raise ValidationError({
                'disposal_type': (
                    "Le pain soldé ne se saisit plus depuis Production — utilisez la "
                    "vente soldée (case « Vente Soldée ») dans Facturation/Gestion "
                    "Clientèle, qui applique le prix réduit à 75 % et calcule la perte."
                )
            })
        user = self.request.user
        node = user.node
        if not node:
            raise ValidationError({'node': 'Utilisateur sans boulangerie assignée.'})
        disposal = serializer.save(node=node, node_origin=node.code)
        # REMAINING breads are not disposed — they stay in stock and roll into the next batch
        if disposal.disposal_type != BreadDisposal.DisposalType.REMAINING:
            _adjust_bread_stock(disposal.node, disposal.bread_price, disposed=disposal.quantity)

    def perform_update(self, serializer):
        # BUG-106 : perform_create bloque la création d'un `SOLD_DISCOUNT`
        # (BUG-092), mais un PATCH/PUT d'une entrée existante (ex. créée en
        # DECLASSED) vers `disposal_type=SOLD_DISCOUNT` contournait entièrement
        # la règle. On n'interdit que la TRANSITION vers SOLD_DISCOUNT — une
        # entrée déjà SOLD_DISCOUNT (historique) reste modifiable sur ses
        # autres champs sans déclencher ce garde-fou.
        instance = serializer.instance
        new_type = serializer.validated_data.get('disposal_type', instance.disposal_type)
        if (
            new_type == BreadDisposal.DisposalType.SOLD_DISCOUNT
            and instance.disposal_type != BreadDisposal.DisposalType.SOLD_DISCOUNT
        ):
            raise ValidationError({
                'disposal_type': (
                    "Le pain soldé ne se saisit plus depuis Production — utilisez la "
                    "vente soldée (case « Vente Soldée ») dans Facturation/Gestion "
                    "Clientèle, qui applique le prix réduit à 75 % et calcule la perte."
                )
            })
        serializer.save()


_MONEY_Q = Decimal('0.01')


def _m(value):
    """
    BUG-120 : normalise un total agrégé (Decimal, int, ou None si aucune
    ligne pour l'agrégat) en `Decimal` à 2 décimales, arrondi au franc
    conformément à CLAUDE.md §4 (ROUND_HALF_UP, jamais de float sur un
    montant).
    """
    d = value if value is not None else Decimal('0')
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return d.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)


def _resolve_node(node_param):
    """
    BUG-120 : `node` dans la requête peut être le code boulangerie (ex. 'K1',
    conforme à l'URL de la mission `?node=<code>`) ou sa clé primaire
    numérique (cohérence avec le reste de l'API — `filterset_fields=['node', ...]`
    partout ailleurs dans ce module attend une PK). On essaie la PK d'abord
    si la valeur est numérique, sinon le code (insensible à la casse).
    """
    if not node_param:
        return None
    try:
        return Node.objects.filter(pk=int(node_param)).first()
    except (TypeError, ValueError):
        pass
    return Node.objects.filter(code__iexact=str(node_param)).first()


def _build_daily_closure_report(node, report_date):
    """
    BUG-120 : construit le rapport de clôture journalier consolidé pour
    `node`/`report_date`, décomposé par catégorie de pain (CLAUDE.md §5.4),
    en réunissant :
      - Production déclarée (`ProductionSession`/`ProductionSessionLine`).
      - Facturation normale, vente soldée/cash, non-servi, régularisation et
        facture de mouvement interne (`sales.Invoice`/`InvoiceLine`) livrées
        ce jour pour ce nœud.
      - Reste du jour / reste du hier par équipe (`DailyBreadStockSnapshot`,
        Chantier B, VÉRIFIÉ).
      - Dispositions (`BreadDisposal`, hors REMAINING qui alimente déjà le
        snapshot ci-dessus).
      - Transferts inter-boulangeries confirmés ce jour (`BreadTransfer`/
        `BreadTransferLine`).
    Choix de conception documentés dans le ticket BUG-120 et le rapport
    d'agent associé (contrat d'API, formules des totaux, ambiguïtés
    résiduelles signalées explicitement plutôt que tranchées seul).
    """
    from sales.models import Invoice, InvoiceLine

    config = Config.get_instance()

    sessions_qs = ProductionSession.objects.filter(node=node, date=report_date)
    sacs_produits = sessions_qs.aggregate(t=Sum('flour_sacks_used'))['t'] or Decimal('0.00')
    net_produit_fc = Decimal(sessions_qs.aggregate(t=Sum('total_fc_produced'))['t'] or 0)
    ecart_production_fc = sessions_qs.aggregate(t=Sum('yield_gap'))['t'] or 0
    total_breads_produced = sessions_qs.aggregate(t=Sum('total_breads'))['t'] or 0

    produced_by_bp = dict(
        ProductionSessionLine.objects.filter(session__in=sessions_qs)
        .values('bread_price_id').annotate(qty=Sum('quantity'))
        .values_list('bread_price_id', 'qty')
    )

    node_codes = set(Node.objects.values_list('code', flat=True))

    base_invoices = Invoice.objects.filter(
        node=node, invoice_date=report_date, status=Invoice.Status.DELIVERED,
        is_debt_repayment=False,
    )

    # FACTURE/JR : ventes normales (ni soldées, ni ajustements, ni « non
    # servi », ni facture de mouvement interne codée par un code boulangerie
    # — ces trois dernières ont chacune leur propre rubrique ci-dessous).
    normal_invoices = base_invoices.filter(is_adjustment=False, is_soldee=False) \
        .exclude(special_code=Invoice.SpecialCode.NS) \
        .exclude(special_code__in=node_codes)
    normal_by_bp = {
        row['bread_price_id']: row for row in
        InvoiceLine.objects.filter(invoice__in=normal_invoices).values('bread_price_id').annotate(
            qty=Sum('quantity'),
            fc=Sum('line_total'),
            # COMMISSION/JR (CLAUDE.md §5.3) : CM brute = valeur commande ×
            # taux — le taux est porté par la facture (`Invoice.commission_rate`),
            # jamais par la ligne ; on le multiplie donc ligne par ligne via
            # une expression SQL plutôt qu'un simple Sum('line_total') × taux
            # global, pour rester exact si plusieurs factures aux taux
            # différents tombent le même jour/nœud/catégorie.
            cm=Sum(ExpressionWrapper(
                F('line_total') * F('invoice__commission_rate'),
                output_field=DecimalField(max_digits=18, decimal_places=4),
            )),
        )
    }

    # VENTE CASH/VENTE SOLDE (CLAUDE.md §5.1 : prix à 75 %, CM = 0).
    soldee_invoices = base_invoices.filter(is_adjustment=False, is_soldee=True)
    soldee_by_bp = {
        row['bread_price_id']: row for row in
        InvoiceLine.objects.filter(invoice__in=soldee_invoices)
        .values('bread_price_id').annotate(qty=Sum('quantity'), fc=Sum('line_total'))
    }
    soldee_loss_by_bp = {}
    for line in InvoiceLine.objects.filter(invoice__in=soldee_invoices).select_related('bread_price'):
        soldee_loss_by_bp[line.bread_price_id] = soldee_loss_by_bp.get(line.bread_price_id, Decimal('0.00')) + line.loss

    # REGULARISATION : factures d'ajustement (BUG-097), signées par
    # `adjustment_sign` au niveau de la facture entière (les lignes portent
    # toujours une quantité positive — la magnitude du changement).
    adjustment_invoices = base_invoices.filter(is_adjustment=True).prefetch_related('lines')
    regularisation_by_bp = {}
    for inv in adjustment_invoices:
        sign = inv.adjustment_sign or 1
        for line in inv.lines.all():
            entry = regularisation_by_bp.setdefault(line.bread_price_id, {'qty': 0, 'fc': Decimal('0.00')})
            entry['qty'] += sign * line.quantity
            entry['fc'] += sign * line.line_total

    # NON SERVI/S : facture au code spécial NS — par construction sans ligne
    # réelle en général, mais agrégée comme les autres par sécurité (aucune
    # hypothèse imposée sur son contenu).
    ns_invoices = base_invoices.filter(special_code=Invoice.SpecialCode.NS)
    ns_by_bp = {
        row['bread_price_id']: row for row in
        InvoiceLine.objects.filter(invoice__in=ns_invoices)
        .values('bread_price_id').annotate(qty=Sum('quantity'), fc=Sum('line_total'))
    }

    # NON VENDU(NV)/DECLASSES/EXCEDENT GRATUIT : dispositions du jour, hors
    # REMAINING (qui alimente déjà `DailyBreadStockSnapshot`, Chantier B).
    disposals_qs = BreadDisposal.objects.filter(
        node=node, session__date=report_date,
    ).exclude(disposal_type=BreadDisposal.DisposalType.REMAINING)
    disposals_by_bp_type = {}
    for row in disposals_qs.values('bread_price_id', 'disposal_type').annotate(
        qty=Sum('quantity'), fc=Sum('total_value'),
    ):
        disposals_by_bp_type.setdefault(row['bread_price_id'], {})[row['disposal_type']] = {
            'quantity': row['qty'] or 0, 'fc': str(_m(row['fc'])),
        }

    # APPRO EFFECTUE/APPRO RECU : transferts CONFIRMÉS ce jour (`updated_at`
    # — voir correctif BUG-120 sur `confirm_reception`, qui persiste
    # désormais cette colonne au moment de la confirmation).
    appro_effectue_by_bp = dict(
        BreadTransferLine.objects.filter(
            transfer__from_node=node,
            transfer__transfer_status=BreadTransfer.TransferStatus.CONFIRMED,
            transfer__updated_at__date=report_date,
        ).values('bread_price_id').annotate(qty=Sum('quantity_sent')).values_list('bread_price_id', 'qty')
    )
    appro_recu_by_bp = dict(
        BreadTransferLine.objects.filter(
            transfer__to_node=node,
            transfer__transfer_status=BreadTransfer.TransferStatus.CONFIRMED,
            transfer__updated_at__date=report_date,
        ).values('bread_price_id').annotate(qty=Sum('quantity_received')).values_list('bread_price_id', 'qty')
    )

    team_choices = [c[0] for c in ProductionSession.Team.choices]

    category_ids = (
        set(BreadPrice.objects.filter(is_active=True).values_list('id', flat=True))
        | set(produced_by_bp) | set(normal_by_bp) | set(soldee_by_bp)
        | set(regularisation_by_bp) | set(ns_by_bp)
        | set(disposals_by_bp_type) | set(appro_effectue_by_bp) | set(appro_recu_by_bp)
    )
    categories_by_id = {bp.id: bp for bp in BreadPrice.objects.filter(id__in=category_ids)}

    categories_payload = []
    total_facture_fc = Decimal('0.00')
    total_commission_fc = Decimal('0.00')
    total_mvm_interne_fc = Decimal('0.00')
    total_produced_value_fc = Decimal('0.00')
    total_breads_billed = 0

    for bp_id in sorted(category_ids, key=lambda i: categories_by_id[i].unit_price if i in categories_by_id else 0):
        bp = categories_by_id.get(bp_id)
        if bp is None:
            continue  # catégorie supprimée depuis — ignorée du rapport, jamais une erreur serveur
        normal = normal_by_bp.get(bp_id, {})
        soldee = soldee_by_bp.get(bp_id, {})
        reg    = regularisation_by_bp.get(bp_id, {'qty': 0, 'fc': Decimal('0.00')})
        ns     = ns_by_bp.get(bp_id, {})
        disp   = disposals_by_bp_type.get(bp_id, {})

        facture_fc = _m(normal.get('fc'))
        commission_fc = _m(normal.get('cm'))
        soldee_fc = _m(soldee.get('fc'))
        reg_fc = _m(reg['fc'])
        non_servi_fc = _m(ns.get('fc'))

        catalog_price = Decimal(bp.unit_price)
        reste_du_jour_by_team = {
            team: DailyBreadStockSnapshot.reste_du_jour(node, bp, report_date, team)
            for team in team_choices
        }
        reste_du_hier_by_team = {
            team: DailyBreadStockSnapshot.reste_du_hier(node, bp, report_date, team)
            for team in team_choices
        }
        reste_du_jour_fc = _m(sum(Decimal(v or 0) for v in reste_du_jour_by_team.values()) * catalog_price)
        reste_du_hier_fc = _m(sum(Decimal(v or 0) for v in reste_du_hier_by_team.values()) * catalog_price)

        appro_effectue_qty = appro_effectue_by_bp.get(bp_id, 0)
        appro_recu_qty = appro_recu_by_bp.get(bp_id, 0)
        appro_effectue_fc = _m(Decimal(appro_effectue_qty) * catalog_price)
        appro_recu_fc = _m(Decimal(appro_recu_qty) * catalog_price)

        non_vendu_entry = disp.get(BreadDisposal.DisposalType.UNSOLD, {'quantity': 0, 'fc': '0.00'})
        declasses_entry = disp.get(BreadDisposal.DisposalType.DECLASSED, {'quantity': 0, 'fc': '0.00'})
        sorties_gratuites_entry = disp.get(BreadDisposal.DisposalType.FREE_DIST, {'quantity': 0, 'fc': '0.00'})

        # FACTURE MVM INTERNE (Q-006, réponse client 2026-11-02 — preuve
        # audit `K6!L21 = SUM(L8:L20)`) : ce n'est PAS une facture séparée
        # portant un code boulangerie (interprétation initiale invalidée,
        # voir fiche BUG-120) mais la SOMME des rubriques ci-dessous, déjà
        # calculées séparément par ce même endpoint, toutes exprimées en FC.
        # EXCÉDENT/MANQUANT par catégorie n'ont aucune donnée source dans le
        # modèle actuel (audit point 2 : l'écart théorique/réel n'existe
        # qu'au niveau global de la session — `ProductionSession.yield_gap`,
        # jamais décomposé par catégorie) — traités comme 0, documenté dans
        # le registre, à ne pas confondre avec une omission silencieuse.
        mvm_interne_fc = _m(
            reste_du_jour_fc + reste_du_hier_fc
            + appro_effectue_fc + appro_recu_fc
            + non_servi_fc + reg_fc
            + soldee_fc  # VENTE CASH + VENTE SOLDE : un seul bucket existant (is_soldee)
            + _m(non_vendu_entry['fc']) + _m(declasses_entry['fc'])
            # EXCEDENT PAINS + MANQUANT PAINS : non modélisés par catégorie (0)
        )

        produced_qty = produced_by_bp.get(bp_id, 0)
        produced_value_fc = _m(Decimal(produced_qty) * catalog_price)

        categories_payload.append({
            'bread_price': bp.id,
            'label': bp.label,
            'unit_price': bp.unit_price,
            'produit': {'quantity': produced_qty, 'fc': str(produced_value_fc)},
            'facture_jr': {'quantity': normal.get('qty') or 0, 'fc': str(facture_fc)},
            'commission_jr': {'fc': str(commission_fc)},
            'reste_du_jour': reste_du_jour_by_team,
            'reste_du_hier': reste_du_hier_by_team,
            'appro_effectue': {'quantity': appro_effectue_qty, 'fc': str(appro_effectue_fc)},
            'appro_recu':     {'quantity': appro_recu_qty, 'fc': str(appro_recu_fc)},
            'non_servi': {'quantity': ns.get('qty') or 0, 'fc': str(non_servi_fc)},
            'regularisation': {'quantity': reg['qty'], 'fc': str(reg_fc)},
            'vente_cash_soldee': {
                'quantity': soldee.get('qty') or 0, 'fc': str(soldee_fc),
                'perte_fc': str(_m(soldee_loss_by_bp.get(bp_id))),
            },
            'facture_mvm_interne': {'fc': str(mvm_interne_fc)},
            'non_vendu_nv':       {'quantity': non_vendu_entry['quantity'], 'fc': non_vendu_entry['fc']},
            'declasses':          {'quantity': declasses_entry['quantity'], 'fc': declasses_entry['fc']},
            'sorties_gratuites':  {'quantity': sorties_gratuites_entry['quantity'], 'fc': sorties_gratuites_entry['fc']},
        })

        total_facture_fc += facture_fc
        total_commission_fc += commission_fc
        total_mvm_interne_fc += mvm_interne_fc
        total_produced_value_fc += produced_value_fc
        total_breads_billed += (normal.get('qty') or 0) + (soldee.get('qty') or 0) + reg['qty']

    # TOTAL DU JOUR (Q-006, réponse client) : facturation normale aux
    # clients + le sous-total FACTURE MVM INTERNE ci-dessus — preuve audit
    # `K6!L132 = L128(facturation clients) + L21(FACTURE MVM INTERNE)`.
    # Exclut toujours les remboursements BP (`is_debt_repayment`, ce n'est
    # pas une vente, CLAUDE.md §5.2), déjà hors de `base_invoices`.
    total_du_jour_fc = total_facture_fc + total_mvm_interne_fc
    # ECART/FACTURE (Q-007.1, réponse client 2026-11-02) : « commandes,
    # paiements sur commande » — valeur commandée du jour moins paiements
    # reçus sur ces commandes, toutes factures livrées ce jour pour ce
    # nœud (régularisations/ventes soldées incluses, remboursements exclus
    # car `order_total`/`payment_amount` y sont toujours nuls par
    # construction — ce n'est jamais une commande, CLAUDE.md §5.2).
    ecart_facture_agg = Invoice.objects.filter(
        node=node, invoice_date=report_date, status=Invoice.Status.DELIVERED,
    ).aggregate(commande=Sum('order_total'), paye=Sum('payment_amount'))
    ecart_facture_fc = _m(ecart_facture_agg['commande']) - _m(ecart_facture_agg['paye'])
    moyenne_produit_par_sac_fc = (
        (net_produit_fc / sacs_produits).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
        if sacs_produits > 0 else None
    )
    # Tarif vente (Q-007.2, réponse client 2026-11-02) : « saisi par vous par
    # boulangerie » — valeur FIXE déjà existante (`Node.sac_value_fc`, ou la
    # valeur par défaut de `Config` si le nœud n'en a pas — même règle que
    # `_effective_sac_value`, BUG déjà traité pour « Valeur Théorique par Sac
    # de Farine »), JAMAIS une moyenne recalculée à partir des ventes du
    # jour.
    tarif_vente_fc = Decimal(_effective_sac_value(node, config))

    # Répartition de pains EN % (Q-007.3, réponse client 2026-11-02) : « fait
    # les deux » — les deux variantes sont exposées, le choix d'affichage
    # revient au frontend (futur sélecteur côté gérant), jamais tranché ici.
    repartition_pct_par_quantite = []
    repartition_pct_par_valeur = []
    for row in categories_payload:
        qty = row['produit']['quantity']
        pct_qty = (
            (Decimal(qty) * Decimal('100') / Decimal(total_breads_produced))
            .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if qty and total_breads_produced else Decimal('0.00')
        )
        repartition_pct_par_quantite.append({'bread_price': row['bread_price'], 'label': row['label'], 'pct': str(pct_qty)})

        value_fc = Decimal(row['produit']['fc'])
        pct_val = (
            (value_fc * Decimal('100') / total_produced_value_fc)
            .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if value_fc and total_produced_value_fc else Decimal('0.00')
        )
        repartition_pct_par_valeur.append({'bread_price': row['bread_price'], 'label': row['label'], 'pct': str(pct_val)})

    return {
        'node': node.code,
        'date': str(report_date),
        'categories': categories_payload,
        'totals': {
            'total_du_jour_fc': str(_m(total_du_jour_fc)),
            'net_produit_fc': str(_m(net_produit_fc)),
            'ecart_facture_fc': str(ecart_facture_fc),
            # BUG-120 : `Sum('flour_sacks_used')` sous SQLite peut renvoyer un
            # `Decimal` dont la précision affichée varie selon les valeurs
            # additionnées (ex. "3" plutôt que "3.00") — toujours figer 2
            # décimales en sortie, comme le champ source
            # (`ProductionSession.flour_sacks_used`, `decimal_places=2`).
            'nombre_sacs_produits': str(sacs_produits.quantize(Decimal('0.01'))),
            'moyenne_produit_par_sac_fc': str(moyenne_produit_par_sac_fc) if moyenne_produit_par_sac_fc is not None else None,
            'tarif_vente_fc': str(tarif_vente_fc),
            'ecart_production_fc': str(ecart_production_fc),
            'total_breads_produced': total_breads_produced,
            'total_breads_billed': total_breads_billed,
            'repartition_pct_par_quantite': repartition_pct_par_quantite,
            'repartition_pct_par_valeur': repartition_pct_par_valeur,
        },
    }


class DailyClosureReportView(APIView):
    """
    BUG-120 (docs/qa/REGISTRE_BUGS.md) : rapport de clôture journalier
    CONSOLIDÉ, par boulangerie et par jour, décomposé par catégorie de pain
    — réunit en un seul document ce qui est aujourd'hui éclaté entre
    Production, Ventes/Clients et Clôture & Caisse (CLAUDE.md, mission
    Chantier C, 2026-11-02). Lecture seule, aucun effet de bord, aucune
    écriture — ne touche jamais `treasury/` (Chantier D séparé sur
    `FacturierReport`, BUG-033).

    `GET /api/production/daily-closure/?node=<code ou pk>&date=<AAAA-MM-JJ>`

    Contrat de réponse détaillé dans
    `docs/qa/rapports/dev-backend-2026-11-02-chantier-c-cloture-consolidee.md`.
    """
    permission_classes = [IsGerant]

    def get(self, request):
        user = request.user
        params = request.query_params
        date_str = params.get('date')
        if not date_str:
            return Response({'detail': "Le paramètre `date` (AAAA-MM-JJ) est requis."}, status=status.HTTP_400_BAD_REQUEST)

        from django.utils.dateparse import parse_date
        report_date = parse_date(date_str)
        if report_date is None:
            return Response({'detail': "Date invalide — format attendu AAAA-MM-JJ."}, status=status.HTTP_400_BAD_REQUEST)

        node_param = params.get('node')
        if not user.can_access_all_nodes:
            # BUG-120 : un GERANT (non-HQ) ne consulte jamais que sa propre
            # boulangerie — même motif que `get_queryset()` partout ailleurs
            # dans ce module ; toute valeur de `node` dans la requête qui ne
            # correspond pas à la sienne est silencieusement ignorée (jamais
            # une fuite vers une autre boulangerie).
            if not user.node_id:
                return Response({'detail': "Compte non assigné à une boulangerie."}, status=status.HTTP_400_BAD_REQUEST)
            node = user.node
        else:
            if not node_param:
                return Response({'detail': "Le paramètre `node` (code ou identifiant) est requis."}, status=status.HTTP_400_BAD_REQUEST)
            node = _resolve_node(node_param)
            if node is None:
                return Response({'detail': f"Boulangerie « {node_param} » introuvable."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_build_daily_closure_report(node, report_date))
