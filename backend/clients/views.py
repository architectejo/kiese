from decimal import Decimal
from django.db.models import ProtectedError, Case, When, Value, IntegerField
from django.db.models.functions import Lower, Concat
from core.mixins import NodeImmutableForNonHQMixin, is_node_less_non_hq
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from core.models import Config, Node
from core.permissions import IsGerant, IsHeadquarters, IsFacturier
from core.utils import log_activity, create_notification
from django.utils import timezone
from .models import Client, SocialContribution, SocialDistribution, SocialDistributionLine, _generate_client_code
from .imports import parse_client_excel, split_name
from .serializers import (
    ClientSerializer, ClientCreateSerializer,
    SocialContributionSerializer, SocialDistributionSerializer, SocialDistributionLineSerializer,
)


class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.select_related('node').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['node', 'category', 'is_active']
    search_fields    = ['code', 'first_name', 'last_name', 'phone']
    ordering_fields  = ['last_name', 'current_debt', 'total_breads_received', 'created_at']
    ordering         = ['last_name']

    def get_serializer_class(self):
        if self.action == 'create':
            return ClientCreateSerializer
        return ClientSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        if self.action in ('import_excel', 'bulk_move', 'bulk_delete'):
            return [IsHeadquarters()]
        if self.action == 'create':
            # BUG-089 : décision client (M. NDUNGA NSAYI PIERRE, 2026-10-30) —
            # un FACTURIER doit pouvoir créer un « Client Occasionnel » pour
            # une vente directe au comptant (CLAUDE.md §5.1, `Clients.tsx`
            # `triggerCasualSale`). On assouplit UNIQUEMENT `create` (même
            # pattern que `sales.views.InvoiceViewSet.get_permissions`, qui
            # autorise déjà `IsFacturier()` pour cette action). Toutes les
            # autres actions (update/partial_update/destroy/
            # recalculate_category/import_excel/bulk_move/bulk_delete)
            # restent réservées à GERANT+ : un facturier ne doit ni modifier
            # un plafond crédit (BUG-012), ni supprimer, ni déplacer un
            # client entre boulangeries.
            return [IsFacturier()]
        return [IsGerant()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if is_node_less_non_hq(user):
            # BUG-506 : compte lié à une boulangerie mais sans nœud = aucune donnée.
            return qs.none()
        if not user.can_access_all_nodes:
            # Facturiers and Livreurs see all nodes — a client from any bakery
            # may present at a different bakery and must be invoiced without issue.
            if user.role not in ('FACTURIER', 'LIVREUR'):
                qs = qs.filter(node=user.node)
        return qs

    def filter_queryset(self, queryset):
        # BUG-095 : le tri alphabétique par défaut (`ordering = ['last_name']`,
        # appliqué par `filters.OrderingFilter`) mélange, lors d'une recherche
        # prédictive (`?search=...`), les correspondances exactes/préfixe
        # avec les simples correspondances de sous-chaîne (ex. "kiese" ->
        # "Kiese" et "Makiese" apparaissent dans un ordre alphabétique
        # arbitraire). Décision du coordinateur : un tri par pertinence
        # (exact > préfixe > substring), PAS une restriction des résultats —
        # le filtre substring de `filters.SearchFilter` (ci-dessus,
        # `search_fields`) reste inchangé, seul l'ORDRE change, et uniquement
        # quand une recherche est en cours ET que l'utilisateur n'a pas
        # explicitement demandé un autre tri via `?ordering=`.
        queryset = super().filter_queryset(queryset)
        search = self.request.query_params.get('search')
        if search and not self.request.query_params.get('ordering'):
            queryset = self._order_by_relevance(queryset, search)
        return queryset

    @staticmethod
    def _order_by_relevance(queryset, search):
        term = search.strip().lower()
        if not term:
            return queryset
        queryset = queryset.annotate(
            _code_lower=Lower('code'),
            _first_lower=Lower('first_name'),
            _last_lower=Lower('last_name'),
            _full_name_lower=Lower(Concat('last_name', Value(' '), 'first_name')),
            _full_name_lower_rev=Lower(Concat('first_name', Value(' '), 'last_name')),
        )
        queryset = queryset.annotate(
            _search_rank=Case(
                # Niveau 0 : correspondance exacte (nom complet ou code).
                When(_code_lower=term, then=Value(0)),
                When(_full_name_lower=term, then=Value(0)),
                When(_full_name_lower_rev=term, then=Value(0)),
                When(_first_lower=term, then=Value(0)),
                When(_last_lower=term, then=Value(0)),
                # Niveau 1 : préfixe.
                When(_code_lower__startswith=term, then=Value(1)),
                When(_full_name_lower__startswith=term, then=Value(1)),
                When(_full_name_lower_rev__startswith=term, then=Value(1)),
                When(_first_lower__startswith=term, then=Value(1)),
                When(_last_lower__startswith=term, then=Value(1)),
                # Niveau 2 (défaut) : substring — comportement de recherche
                # prédictive existant, conservé tel quel.
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        return queryset.order_by('_search_rank', 'last_name', 'first_name')

    def perform_create(self, serializer):
        user = self.request.user
        if not user.can_access_all_nodes:
            # BUG-025 : un utilisateur non-HQ (ex. GERANT) ne doit jamais
            # pouvoir rattacher un nouveau client à une autre boulangerie en
            # forçant `node` dans le payload — on ignore toute valeur
            # envoyée et on impose systématiquement le nœud de l'utilisateur.
            node = user.node
        else:
            node = serializer.validated_data.get('node') or user.node
        if node is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"node": "Utilisateur non assigné à un nœud. Précisez le nœud."})
        extra = {}
        if not (user.is_superuser or user.role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT')):
            # BUG-250 : plafond de crédit et taux de commission réservés au
            # gérant et supérieurs (CLAUDE.md §5.1) : valeurs par défaut sinon.
            from decimal import Decimal
            extra['credit_limit'] = Decimal(str(Client._meta.get_field('credit_limit').get_default()))
            extra['commission_rate'] = Decimal(str(Client._meta.get_field('commission_rate').get_default()))
        client = serializer.save(
            node=node,
            node_origin=node.code,
            **extra,
        )
        log_activity(
            self.request.user,
            "Création Client",
            f"Nouveau client {client.code} — {client.full_name} enregistré à {client.node}.",
            node_origin=client.node_origin
        )

    def perform_update(self, serializer):
        user = self.request.user
        if not user.can_access_all_nodes:
            # BUG-025 (perform_update) : même motif que perform_create — un
            # GERANT non-HQ ne doit jamais pouvoir déplacer un client existant
            # vers une autre boulangerie en forgeant `node` dans le payload.
            # On ignore silencieusement toute valeur de `node` envoyée et on
            # réimpose le nœud actuel de l'utilisateur.
            serializer.validated_data.pop('node', None)
            client = serializer.save(node=user.node)
        else:
            client = serializer.save()
        client.refresh_category()
        client.save(update_fields=['category'])

    @action(detail=True, methods=['post'], permission_classes=[IsGerant])
    def recalculate_category(self, request, pk=None):
        """Force-recalculate the client's risk category from current figures."""
        client = self.get_object()
        config = Config.get_instance()
        old_cat = client.category
        client.refresh_category(config)
        client.save(update_fields=['category'])

        if client.category == Client.Category.RISK and old_cat != Client.Category.RISK:
            create_notification(
                title=f"Alerte Risque Client — {client.full_name}",
                message=(
                    f"Le client {client.code} {client.full_name} dépasse son plafond "
                    f"({client.credit_limit:,.0f} FC). Encours : {client.current_debt:,.0f} FC."
                ),
                severity='DANGER',
                node_origin=client.node.code
            )
        return Response(ClientSerializer(client).data)

    @action(detail=True, methods=['get'], permission_classes=[IsGerant])
    def history(self, request, pk=None):
        """BUG-400 : historique des opérations (achats, dépôts, retraits,
        remboursements) d'un client pour un mois (`?month=AAAA-MM`, défaut =
        mois courant), avec totaux et liste des mois navigables.
        Public = celui de la page Commissions (GERANT+) ; filtrage par nœud
        via get_queryset()."""
        import re
        from django.db.models.functions import TruncMonth
        from sales.models import Invoice

        client = self.get_object()
        today = timezone.localdate()
        raw = request.query_params.get('month')
        if raw in (None, ''):
            year, month = today.year, today.month
        else:
            m = re.fullmatch(r'(\d{4})-(\d{2})', raw.strip())
            if not m or not (1 <= int(m.group(2)) <= 12) or int(m.group(1)) < 2000:
                return Response(
                    {'detail': "Paramètre « month » invalide : format attendu AAAA-MM (ex. 2026-11)."},
                    status=400)
            year, month = int(m.group(1)), int(m.group(2))

        invoices = Invoice.objects.filter(client=client)
        qs = (invoices.filter(invoice_date__year=year, invoice_date__month=month)
              .select_related('node')
              .order_by('invoice_date', 'delivered_at', 'created_at', 'id'))

        zero = Decimal('0.00')
        q = Decimal('0.01')
        operations = []
        total_orders = total_payments = total_withdrawals = zero
        counted = 0
        bp_start = bp_end = None
        for inv in qs:
            order, pay = inv.order_total or zero, inv.payment_amount or zero
            if inv.is_debt_repayment:
                op_type, label = 'REMBOURSEMENT', 'Remboursement de BP'
            elif inv.is_adjustment:
                op_type, label = 'AJUSTEMENT', 'Ajustement de facture'
            elif pay < 0:
                op_type = 'RETRAIT'
                label = inv.get_motif_display() if inv.motif else 'Retrait'
            elif order == 0 and pay > 0:
                op_type, label = 'DEPOT', 'Dépôt / versement'
            else:
                op_type, label = 'ACHAT', 'Achat'
            when = inv.delivered_at or inv.created_at
            operations.append({
                'id': str(inv.id),
                'date': inv.invoice_date.isoformat(),
                'datetime': when.isoformat() if when else None,
                'type': op_type,
                'label': label,
                'receipt_number': inv.receipt_number,
                'status': inv.status,
                'team': inv.team,
                'node_code': inv.node.code if inv.node_id else '',
                'order_value': str(order.quantize(q)),
                'payment': str(pay.quantize(q)),
                'bp_before': str((inv.debt_before or zero).quantize(q)),
                'bp_after': str((inv.debt_after or zero).quantize(q)),
            })
            if inv.status == Invoice.Status.DELIVERED:
                counted += 1
                if not inv.is_debt_repayment:
                    total_orders += order
                if pay > 0:
                    total_payments += pay
                elif pay < 0:
                    total_withdrawals += -pay
                if bp_start is None:
                    bp_start = inv.debt_before or zero
                bp_end = inv.debt_after or zero

        months = {d.strftime('%Y-%m') for d in
                  invoices.annotate(_m=TruncMonth('invoice_date')).values_list('_m', flat=True).distinct() if d}
        months.add(today.strftime('%Y-%m'))
        return Response({
            'client': {
                'id': str(client.id), 'code': client.code, 'full_name': client.full_name,
                'node_code': client.node.code, 'current_debt': str(client.current_debt),
            },
            'month': f'{year:04d}-{month:02d}',
            'current_month': today.strftime('%Y-%m'),
            'available_months': sorted(months, reverse=True),
            'operations': operations,
            'totals': {
                'operations_count': len(operations),
                'delivered_count': counted,
                'total_orders': str(total_orders.quantize(q)),
                'total_payments': str(total_payments.quantize(q)),
                'total_withdrawals': str(total_withdrawals.quantize(q)),
                'net_balance_change': str((total_orders - total_payments + total_withdrawals).quantize(q)),
                'bp_start': str(bp_start.quantize(q)) if bp_start is not None else None,
                'bp_end': str(bp_end.quantize(q)) if bp_end is not None else None,
            },
        })

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def active_last_month(self, request):
        """Clients who placed at least one order in the last 30 days."""
        from datetime import date, timedelta
        from django.db.models import Count, Q
        cutoff = timezone.localdate() - timedelta(days=30)
        qs = self.get_queryset().annotate(
            recent_orders=Count('invoices', filter=Q(invoices__invoice_date__gte=cutoff))
        ).filter(recent_orders__gt=0)
        return Response({'count': qs.count()})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def risk_alerts(self, request):
        qs = self.get_queryset().filter(category=Client.Category.RISK)
        return Response(ClientSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def best_clients(self, request):
        qs = self.get_queryset().filter(category=Client.Category.BEST)
        return Response(ClientSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def bassins(self, request):
        """Classify clients of a node by monthly order volume into 5 BASSINS categories."""
        from commissions.models import CommissionPeriod, ClientCommission
        from django.db.models import Sum
        node_id = request.query_params.get('node')
        month   = request.query_params.get('month')
        year    = request.query_params.get('year')
        if not all([node_id, month, year]):
            return Response({'detail': 'node, month et year sont requis.'}, status=400)

        config = Config.get_instance()
        CATEGORIES = ['GRAND FORMAT', 'INTER G&M', 'INTER M&PT', 'MOYEN', 'PETIT']
        thresholds = {
            'GRAND FORMAT': float(config.bassin_grand),
            'INTER G&M':    float(config.bassin_inter_gm),
            'INTER M&PT':   float(config.bassin_inter_mpt),
            'MOYEN':        float(config.bassin_moyen),
        }

        def classify(order_value: float) -> str:
            for cat in CATEGORIES[:-1]:
                if order_value >= thresholds[cat]:
                    return cat
            return 'PETIT'

        try:
            period = CommissionPeriod.objects.get(node_id=node_id, month=month, year=year)
            commissions = list(
                ClientCommission.objects
                .filter(period=period)
                .select_related('client')
                .order_by('-order_value')
            )
        except CommissionPeriod.DoesNotExist:
            return Response({'detail': 'Aucune période CM pour ce filtre.', 'rows': [], 'categories': CATEGORIES, 'thresholds': thresholds}, status=200)

        rows = []
        for cc in commissions:
            ov = float(cc.order_value)
            rows.append({
                'client_code':  cc.client.code,
                'client_name':  cc.client.full_name,
                'order_value':  str(cc.order_value),
                'bp':           str(cc.deduction_debt),
                'cm':           str(cc.commission_gross),
                'net_payable':  str(cc.net_payable),
                'category':     classify(ov),
                'rank':         0,
            })

        # Assign rank within each category
        for cat in CATEGORIES:
            cat_rows = [r for r in rows if r['category'] == cat]
            for i, r in enumerate(cat_rows, 1):
                r['rank'] = i

        return Response({'categories': CATEGORIES, 'thresholds': thresholds, 'rows': rows})

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def import_excel(self, request):
        """
        Importe la liste des clients par boulangerie depuis le classeur Excel
        officiel (une feuille par boulangerie). Envoyer dry_run=true pour un
        aperçu (compte par boulangerie, sans rien enregistrer).
        """
        file = request.FILES.get('file')
        if not file:
            raise ValidationError({'file': "Fichier Excel requis."})
        dry_run = str(request.data.get('dry_run', '')).lower() in ('1', 'true', 'yes')

        try:
            parsed, skipped_sheets = parse_client_excel(file)
        except Exception as e:
            raise ValidationError({'file': f"Impossible de lire le fichier Excel : {e}"})

        nodes_by_code = {n.code: n for n in Node.objects.all()}
        report = []
        to_create = []
        unknown_nodes = []

        for node_code, names in parsed.items():
            node = nodes_by_code.get(node_code)
            if node is None:
                unknown_nodes.append(node_code)
                continue
            existing = {
                (f.strip().upper(), l.strip().upper())
                for f, l in Client.objects.filter(node=node).values_list('first_name', 'last_name')
            }
            new_count, dup_count = 0, 0
            for raw_name in names:
                first, last = split_name(raw_name)
                key = (first.upper(), last.upper())
                if key in existing:
                    dup_count += 1
                    continue
                existing.add(key)
                new_count += 1
                if not dry_run:
                    to_create.append((node, first, last))
            report.append({
                'node': node_code,
                'node_name': node.name,
                'total_in_file': len(names),
                'to_import': new_count,
                'already_existing': dup_count,
            })

        created = 0
        if not dry_run:
            for node, first, last in to_create:
                Client(node=node, first_name=first, last_name=last, node_origin=node.code).save()
                created += 1
            if created:
                log_activity(
                    request.user, "Import Clients (Excel)",
                    f"{created} client(s) importé(s) depuis {file.name}.",
                )

        return Response({
            'dry_run': dry_run,
            'created': created,
            'report': report,
            'skipped_sheets': skipped_sheets,
            'unknown_nodes': unknown_nodes,
        })

    @action(detail=False, methods=['post'])
    def bulk_move(self, request):
        """Move a set of clients to another bakery (Direction centrale uniquement).
        The code prefix reflects the bakery, so it's regenerated for the new node."""
        ids = request.data.get('ids') or []
        node_id = request.data.get('node')
        if not ids or not node_id:
            raise ValidationError({'detail': 'ids et node sont requis.'})
        try:
            new_node = Node.objects.get(pk=node_id)
        except Node.DoesNotExist:
            raise ValidationError({'node': 'Boulangerie introuvable.'})

        clients = list(Client.objects.filter(id__in=ids))
        moved = 0
        for client in clients:
            if client.node_id == new_node.id:
                continue
            client.node = new_node
            client.code = _generate_client_code(new_node.code)
            client.node_origin = new_node.code
            client.save(update_fields=['node', 'code', 'node_origin'])
            moved += 1
        log_activity(
            request.user, "Déplacement Clients",
            f"{moved} client(s) déplacé(s) vers {new_node.code} — {new_node.name}.",
        )
        return Response({'moved': moved, 'requested': len(ids)})

    @action(detail=False, methods=['post'])
    def bulk_delete(self, request):
        """Delete a set of clients (Direction centrale uniquement). Clients with
        protected relations (factures, commissions, distributions sociales) are
        skipped and reported instead of failing the whole batch."""
        ids = request.data.get('ids') or []
        if not ids:
            raise ValidationError({'detail': 'ids requis.'})

        clients = list(Client.objects.filter(id__in=ids))
        deleted, blocked = 0, []
        for client in clients:
            label = f"{client.code} — {client.full_name}"
            try:
                client.delete()
                deleted += 1
            except ProtectedError:
                blocked.append(label)
        if deleted:
            log_activity(
                request.user, "Suppression Clients",
                f"{deleted} client(s) supprimé(s).",
            )
        return Response({'deleted': deleted, 'blocked': blocked, 'requested': len(ids)})

    @action(detail=False, methods=['get'], permission_classes=[IsGerant])
    def deficit_report(self, request):
        """Clients whose current_debt exceeds their commission_gross in the latest period.

        BUG-521 : réservé au gérant et au-dessus (données de commissions, cf.
        BUG-253), borné au nœud de l'appelant ; `?node=` n'est honoré que pour
        le siège et doit être un entier valide."""
        from commissions.models import CommissionPeriod, ClientCommission
        from django.db.models import F
        user = request.user
        if is_node_less_non_hq(user):
            return Response([])
        period_qs = CommissionPeriod.objects.order_by('-year', '-month')
        if not user.can_access_all_nodes:
            period_qs = period_qs.filter(node_id=user.node_id)
        else:
            node_id = request.query_params.get('node')
            if node_id:
                try:
                    node_id = int(node_id)
                except (TypeError, ValueError):
                    raise ValidationError({'detail': "Paramètre « node » invalide : identifiant de boulangerie numérique attendu."})
                period_qs = period_qs.filter(node_id=node_id)
        latest_period = period_qs.first()
        if not latest_period:
            return Response([])
        commissions = (
            ClientCommission.objects
            .filter(period=latest_period, commission_gross__lt=F('client__current_debt'))
            .select_related('client')
            .order_by('-client__current_debt')
        )
        return Response([
            {
                'client_code':      cc.client.code,
                'client_name':      cc.client.full_name,
                'order_value':      str(cc.order_value),
                'commission_gross': str(cc.commission_gross),
                'current_debt':     str(cc.client.current_debt),
                'deficit':          str(cc.client.current_debt - cc.commission_gross),
                'period':           str(latest_period),
            }
            for cc in commissions
        ])


class SocialContributionViewSet(NodeImmutableForNonHQMixin, viewsets.ModelViewSet):
    serializer_class = SocialContributionSerializer
    permission_classes = [IsGerant]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'client', 'month', 'year', 'is_paid']
    ordering = ['year', 'month', 'client__last_name']

    def get_queryset(self):
        qs = SocialContribution.objects.select_related('client', 'node').all()
        user = self.request.user
        if is_node_less_non_hq(user):
            # BUG-506 : compte lié à une boulangerie mais sans nœud = aucune donnée.
            return qs.none()
        if not user.can_access_all_nodes:
            # BUG-022 : aucun filtrage par nœud auparavant.
            qs = qs.filter(node=user.node)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not user.can_access_all_nodes:
            # BUG-022 (écriture) : même motif que ClientViewSet (BUG-025) —
            # ne jamais lire `node` dans le payload pour un non-HQ.
            node = user.node
        else:
            node = serializer.validated_data.get('node') or user.node
        # BUG-249 : le client doit appartenir au nœud retenu.
        client = serializer.validated_data.get('client')
        if client is not None and client.node_id != node.pk:
            raise ValidationError({'client': "Ce client n'appartient pas à la boulangerie indiquée."})
        serializer.save(node=node)

    @action(detail=True, methods=['post'])
    def toggle_paid(self, request, pk=None):
        contrib = self.get_object()
        contrib.is_paid = not contrib.is_paid
        contrib.paid_at = timezone.now() if contrib.is_paid else None
        contrib.save(update_fields=['is_paid', 'paid_at'])
        return Response(SocialContributionSerializer(contrib).data)

    @action(detail=False, methods=['post'])
    def bulk_create_month(self, request):
        """Create SocialContribution records for all active clients of a node for a given month/year."""
        node_id = request.data.get('node')
        month   = request.data.get('month')
        year    = request.data.get('year')
        user = request.user
        if not user.can_access_all_nodes:
            # BUG-249 : le nœud est imposé pour un non-siège ; un `node`
            # étranger dans le corps est refusé.
            if node_id and str(node_id) != str(user.node_id):
                raise PermissionDenied("Vous ne pouvez créer des cotisations que pour votre boulangerie.")
            node_id = user.node_id
        if not all([node_id, month, year]):
            raise ValidationError({'detail': 'node, month et year sont requis.'})
        # BUG-256 : `cotisation_sociale` est un montant (DecimalField) -> `> 0`.
        clients = [c for c in Client.objects.filter(node_id=node_id, is_active=True).select_related('node')
                   if c.effective_cotisation_sociale > 0]  # BUG-289 : valeur effective
        created, skipped = 0, 0
        for client in clients:
            obj, is_new = SocialContribution.objects.get_or_create(
                client=client,
                node_id=node_id,
                month=month,
                year=year,
                defaults={'amount': request.data.get('amount') or client.effective_cotisation_sociale},
            )
            if is_new:
                created += 1
            else:
                skipped += 1
        return Response({'created': created, 'skipped': skipped})


class SocialDistributionViewSet(NodeImmutableForNonHQMixin, viewsets.ModelViewSet):
    serializer_class = SocialDistributionSerializer
    permission_classes = [IsGerant]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'year', 'is_closed']
    ordering = ['-year', 'node__code']

    def get_queryset(self):
        qs = SocialDistribution.objects.select_related('node').prefetch_related('lines__client').all()
        user = self.request.user
        if is_node_less_non_hq(user):
            # BUG-506 : compte lié à une boulangerie mais sans nœud = aucune donnée.
            return qs.none()
        if not user.can_access_all_nodes:
            # BUG-022 : aucun filtrage par nœud auparavant.
            qs = qs.filter(node=user.node)
        return qs

    @staticmethod
    def _can_set_tarif_and_close(user):
        # BUG-316 : TARIF fixé par la direction (adaptes.md [4.2]) ; la clôture,
        # irréversible, lui est réservée aussi. COMPTABLE et gérants exclus.
        return user.is_superuser or user.role in ('ADMIN', 'DIRECTION')

    def _check_direction_fields(self, serializer, current_tarif, current_closed):
        if self._can_set_tarif_and_close(self.request.user):
            return
        data = serializer.validated_data
        if ('tarif' in data and data['tarif'] != current_tarif) or            ('is_closed' in data and data['is_closed'] != current_closed):
            raise PermissionDenied(
                "Le tarif et la clôture d'une distribution sont réservés à la direction.")

    def perform_create(self, serializer):
        user = self.request.user
        extra = {}
        if not self._can_set_tarif_and_close(user):
            # BUG-316 : à la création, tarif et is_closed envoyés par un non-direction
            # sont ignorés (valeurs par défaut ; même politique que `node`, BUG-313).
            extra = {'tarif': Decimal(str(SocialDistribution._meta.get_field('tarif').get_default())),
                     'is_closed': False}
        if not user.can_access_all_nodes:
            # BUG-022 (écriture) : même motif que ClientViewSet (BUG-025) —
            # ne jamais lire `node` dans le payload pour un non-HQ.
            node = user.node
        else:
            node = serializer.validated_data.get('node') or user.node
        serializer.save(node=node, **extra)

    def perform_update(self, serializer):
        # BUG-313 : l'année d'une distribution clôturée est figée.
        instance = serializer.instance
        self._check_direction_fields(serializer, instance.tarif, instance.is_closed)
        new_year = serializer.validated_data.get('year')
        if instance.is_closed and new_year is not None and new_year != instance.year:
            raise ValidationError({'detail': "Distribution clôturée : l'année ne peut plus être modifiée."})
        distribution = serializer.save()
        if not distribution.is_closed:
            # BUG-295 : REMISE = INDICE × TARIF + MÉRITE ; un nouveau tarif
            # recalcule les lignes déjà créées (distribution non clôturée).
            for line in distribution.lines.select_related('distribution'):
                line.compute()
                line.save(update_fields=['remise', 'total_payer', 'updated_at'])

    @action(detail=True, methods=['post'])
    def refresh_indices(self, request, pk=None):
        """BUG-295 : recalcule INDICE (= nombre de mois de cotisation payés de
        l'année, boulangerie de la distribution) et TOTAL SOCIAL de chaque ligne
        d'une distribution non clôturée, puis REMISE = INDICE × TARIF et
        TOTAL À PAYER = TOTAL SOCIAL + REMISE + MÉRITE (MÉRITE saisi, conservé)."""
        from django.db.models import Sum
        distribution = self.get_object()
        if distribution.is_closed:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': 'Cette distribution est déjà clôturée.'})
        updated = 0
        for line in distribution.lines.select_related('distribution', 'client'):
            paid_qs = SocialContribution.objects.filter(
                client=line.client, node=distribution.node,
                year=distribution.year, is_paid=True,
            )
            line.indice = paid_qs.count()
            line.total_social = paid_qs.aggregate(total=Sum('amount'))['total'] or 0
            line.compute()
            line.save()
            updated += 1
        distribution.refresh_from_db()
        return Response({'updated': updated,
                         'distribution': SocialDistributionSerializer(distribution).data})

    @action(detail=True, methods=['post'])
    def auto_populate_lines(self, request, pk=None):
        """Auto-create distribution lines for all active cotisation_sociale clients,
        computing indice = count of paid contributions for this year and node."""
        distribution = self.get_object()
        if distribution.is_closed:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': 'Cette distribution est déjà clôturée.'})
        from django.db.models import Sum
        clients = [c for c in Client.objects.filter(node=distribution.node, is_active=True).select_related('node')
                   if c.effective_cotisation_sociale > 0]  # BUG-256 / BUG-289
        created, skipped = 0, 0
        for client in clients:
            paid_qs = SocialContribution.objects.filter(
                client=client, node=distribution.node,
                year=distribution.year, is_paid=True,
            )
            paid_count  = paid_qs.count()
            total_social = paid_qs.aggregate(total=Sum('amount'))['total'] or 0
            line, is_new = SocialDistributionLine.objects.get_or_create(
                distribution=distribution,
                client=client,
                defaults={'indice': paid_count, 'total_social': total_social},
            )
            if is_new:
                line.compute()
                line.save()
                created += 1
            else:
                skipped += 1
        distribution.refresh_from_db()
        return Response({'created': created, 'skipped': skipped,
                         'distribution': SocialDistributionSerializer(distribution).data})


class SocialDistributionLineViewSet(viewsets.ModelViewSet):
    serializer_class = SocialDistributionLineSerializer
    permission_classes = [IsGerant]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['distribution', 'client', 'position', 'form']

    def get_queryset(self):
        qs = SocialDistributionLine.objects.select_related('client', 'distribution__node').all()
        user = self.request.user
        if is_node_less_non_hq(user):
            # BUG-506 : compte lié à une boulangerie mais sans nœud = aucune donnée.
            return qs.none()
        if not user.can_access_all_nodes:
            # BUG-022 : aucun filtrage par nœud auparavant (via la distribution parente).
            qs = qs.filter(distribution__node=user.node)
        return qs

    def perform_create(self, serializer):
        line = serializer.save()
        line.compute()
        line.save()

    def perform_update(self, serializer):
        line = serializer.save()
        line.compute()
        line.save()
