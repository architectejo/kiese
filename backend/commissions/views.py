from decimal import Decimal

from django.db.models import F, Q, Sum
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from core.models import Config, Node
from core.permissions import IsHeadquarters, IsGerant, IsDirection
from core.utils import log_activity
from sales.models import Invoice
from .models import CommissionPeriod, ClientCommission
from .serializers import CommissionPeriodSerializer, ClientCommissionSerializer


class CommissionPeriodViewSet(viewsets.ModelViewSet):
    queryset = CommissionPeriod.objects.select_related('node').all()
    serializer_class = CommissionPeriodSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'month', 'year', 'is_closed']
    ordering         = ['-year', '-month']

    def get_permissions(self):
        # BUG-253 : lecture réservée au gérant et au-dessus.
        if self.action in ('list', 'retrieve'):
            return [IsGerant()]
        return [IsHeadquarters()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        return qs

    def destroy(self, request, *args, **kwargs):
        # BUG-263 : l'historique de paie d'une période clôturée (ou contenant
        # des commissions payées) ne se supprime pas.
        period = self.get_object()
        if period.is_closed:
            return Response({'detail': 'Une période clôturée ne peut pas être supprimée.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if ClientCommission.objects.filter(period=period, is_paid=True).exists():
            return Response({'detail': 'Cette période contient des commissions payées : suppression impossible.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['get'], permission_classes=[IsGerant])
    def history(self, request):
        """Last N commission periods for a node with aggregates (total CM, net, paid)."""
        node_id = request.query_params.get('node')
        n = min(int(request.query_params.get('months', 12)), 36)
        qs = self.get_queryset()
        if node_id:
            qs = qs.filter(node_id=node_id)
        periods = list(qs.order_by('-year', '-month')[:n])
        result = []
        for p in periods:
            agg = ClientCommission.objects.filter(period=p).aggregate(
                total_orders=Sum('order_value'),
                total_cm=Sum('commission_gross'),
                total_net=Sum('net_payable'),
                total_paid=Sum('net_payable', filter=Q(is_paid=True)),
            )
            inv_agg = Invoice.objects.filter(
                node=p.node, status=Invoice.Status.DELIVERED,
                invoice_date__month=p.month, invoice_date__year=p.year,
            ).aggregate(total_payments=Sum('payment_amount'))
            result.append({
                'id':             str(p.id),
                'node':           str(p.node_id),
                'node_code':      p.node.code,
                'node_name':      p.node.name,
                'month':          p.month,
                'year':           p.year,
                'is_closed':      p.is_closed,
                'client_count':   ClientCommission.objects.filter(period=p).count(),
                'total_orders':   str(agg['total_orders']   or 0),
                'total_cm':       str(agg['total_cm']       or 0),
                'total_net':      str(agg['total_net']       or 0),
                'total_paid':     str(agg['total_paid']      or 0),
                'total_payments': str(inv_agg['total_payments'] or 0),
            })
        return Response(result)

    @action(detail=False, methods=['post'], permission_classes=[IsHeadquarters])
    def generate(self, request):
        """
        Auto-generate a commission period for node/month/year, then create or
        refresh one ClientCommission row per client with DELIVERED invoices
        in that period (order_value/total_breads aggregated from invoice lines).
        Deduction fields (debt/social/prints/other) default to 0 and stay
        editable afterwards — they are not derivable from invoice data alone.
        """
        node_id = request.data.get('node')
        month   = request.data.get('month')
        year    = request.data.get('year')
        if not all([node_id, month, year]):
            return Response({'detail': '`node`, `month` et `year` sont requis.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            node = Node.objects.get(pk=node_id)
        except Node.DoesNotExist:
            return Response({'detail': 'Boulangerie introuvable.'}, status=status.HTTP_400_BAD_REQUEST)

        period, _ = CommissionPeriod.objects.get_or_create(node=node, month=month, year=year)
        if period.is_closed:
            return Response({'detail': 'Cette période est déjà clôturée.'}, status=status.HTTP_400_BAD_REQUEST)

        invoices = Invoice.objects.filter(
            node=node, status=Invoice.Status.DELIVERED,
            invoice_date__month=month, invoice_date__year=year,
            # BUG-019 : les ventes occasionnelles (`client=None`, CLAUDE.md
            # §5.1/remarque.md l.134) n'ont pas de client auquel attribuer
            # une commission — elles sont exclues du calcul par client, pas
            # seulement ignorées silencieusement plus loin.
            client__isnull=False,
            # BUG-020 : les ventes VENTE SOLDE/VENTE CASH doivent avoir
            # CM = 0 (CLAUDE.md §5.1) — leur valeur ne doit même pas entrer
            # dans la base de calcul de la commission (`order_value`).
            is_soldee=False,
            # BUG-052 : idem pour une facture normale explicitement exonérée
            # de commission (`Invoice.commission_exempt`) — même traitement
            # que `is_soldee` pour ce calcul agrégé par client (elle n'a pas
            # vocation à générer de CM, donc sa valeur ne doit pas non plus
            # gonfler `order_value`). Sans impact sur la BP/`current_debt` du
            # client, qui sont gérées ailleurs (sales/views.py), pas ici.
            commission_exempt=False,
            # BUG-261 : une régularisation (RG) ou une facture à taux 0 n'ouvre
            # pas droit à CM : exclue de la base (sinon CM au taux du client).
        ).exclude(special_code='RG').exclude(commission_rate=0).select_related('client').prefetch_related('lines')

        by_client = {}
        # BUG-267 : un remboursement/dépôt n'est pas une vente (pas de base de CM).
        invoices = invoices.filter(is_debt_repayment=False)
        for inv in invoices:
            agg = by_client.setdefault(inv.client_id, {'client': inv.client, 'order_value': 0, 'total_breads': 0})
            agg['order_value']  += inv.order_total
            agg['total_breads'] += sum(line.quantity for line in inv.lines.all())

        # BUG-267 : client épargne (commande = 0, BP créditrice) : aucune commission,
        # son épargne n'est jamais restituée comme net à payer.
        by_client = {cid: a for cid, a in by_client.items() if a['order_value'] > 0}

        config = Config.get_instance()
        for client_id, agg in by_client.items():
            client = agg['client']
            # Pre-compute gross to derive social deduction
            cotisation = Decimal(str(client.cotisation_sociale))

            commission, created = ClientCommission.objects.get_or_create(
                period=period, client_id=client_id,
                defaults={
                    'total_breads': agg['total_breads'],
                    'order_value': agg['order_value'],
                    'commission_rate': client.commission_rate,
                    'deduction_debt': max(Decimal('0'), Decimal(str(client.current_debt))),
                    'deduction_social': cotisation,
                    'deduction_prints': config.print_fee,
                    'node_origin': node.code,
                }
            )
            if not created:
                # BUG-264 : une commission payée n'est jamais recalculée ; sinon
                # seuls les champs dérivés des factures sont rafraîchis (les
                # retenues saisies à la main sont conservées).
                if commission.is_paid:
                    continue
                commission.total_breads     = agg['total_breads']
                commission.order_value      = agg['order_value']
                commission.commission_rate  = client.commission_rate
            commission.compute(float(config.annual_bonus_rate))
            commission.save()

        log_activity(
            request.user, "Génération Commissions CM",
            f"Période {period} générée — {len(by_client)} client(s) traité(s).",
            node_origin=node.code
        )
        return Response({
            'period': CommissionPeriodSerializer(period).data,
            'generated': len(by_client),
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], permission_classes=[IsHeadquarters])
    def close_period(self, request, pk=None):
        period = self.get_object()
        if period.is_closed:
            return Response({'detail': 'Cette période est déjà clôturée.'}, status=status.HTTP_400_BAD_REQUEST)
        period.close()
        log_activity(
            request.user, "Clôture Période CM",
            f"Période {period} clôturée.",
            node_origin=period.node.code
        )
        return Response(CommissionPeriodSerializer(period).data)


class ClientCommissionViewSet(viewsets.ModelViewSet):
    queryset = ClientCommission.objects.select_related('period__node', 'client').all()
    serializer_class = ClientCommissionSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['period', 'period__node', 'client', 'is_paid', 'annual_bonus_incorporated']
    search_fields    = ['client__first_name', 'client__last_name', 'client__code']
    # BUG-172 : `pk` en dernier critère -> ordre total (pagination déterministe).
    ordering         = ['client__last_name', 'pk']

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsGerant()]
        if self.action in ('mark_paid', 'set_manuel'):
            # BUG-265 : réservés à ADMIN/DIRECTION (ne pas écraser IsDirection).
            return [IsDirection()]
        return [IsHeadquarters()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(period__node=user.node)
        return qs

    @staticmethod
    def _locked_response(commission):
        # BUG-263 : commission payée ou période clôturée = immuable.
        if commission.is_paid:
            return Response({'detail': 'Commission payée : modification impossible.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if commission.period.is_closed:
            return Response({'detail': 'Période clôturée : modification impossible.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return None

    def update(self, request, *args, **kwargs):
        locked = self._locked_response(self.get_object())
        if locked is not None:
            return locked
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        locked = self._locked_response(self.get_object())
        if locked is not None:
            return locked
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        config = Config.get_instance()
        commission = serializer.save(
            node_origin=self.request.user.node.code if self.request.user.node else 'CLOUD',
        )
        commission.compute(float(config.annual_bonus_rate))
        commission.save(update_fields=[
            'commission_gross', 'annual_bonus',
            'deduction_carte', 'deduction_remise', 'total_deductions', 'carried_debt_in',
            'net_ordi', 'net_carte', 'net_payable',
        ])

    def perform_update(self, serializer):
        config = Config.get_instance()
        commission = serializer.save()
        commission.compute(float(config.annual_bonus_rate))
        commission.save(update_fields=[
            'commission_gross', 'annual_bonus',
            'deduction_carte', 'deduction_remise', 'total_deductions', 'carried_debt_in',
            'net_ordi', 'net_carte', 'net_payable',
        ])

    @action(detail=True, methods=['post'], permission_classes=[IsDirection])
    def mark_paid(self, request, pk=None):
        commission = self.get_object()
        if commission.is_paid:
            return Response({'detail': 'Commission déjà marquée comme payée.'}, status=status.HTTP_400_BAD_REQUEST)
        # BUG-266 : un net négatif est reporté comme dette, il ne se « paie » pas.
        if Decimal(str(commission.net_payable)) < 0:
            return Response(
                {'detail': 'Net à payer négatif : paiement impossible, le solde est reporté comme dette sur la période suivante.'},
                status=status.HTTP_400_BAD_REQUEST)
        paid_by = request.data.get('paid_by', request.user.get_full_name())
        commission.mark_paid(paid_by)
        log_activity(
            request.user, "Paiement Commission",
            f"Commission de {commission.client.full_name} ({commission.period}) payée : {commission.net_payable} FC.",
            node_origin=commission.period.node.code
        )
        return Response(ClientCommissionSerializer(commission).data)

    @action(detail=True, methods=['patch'], permission_classes=[IsDirection])
    def set_manuel(self, request, pk=None):
        """Override net_payable with a manual adjustment (DIRECTION only)."""
        commission = self.get_object()
        locked = self._locked_response(commission)
        if locked is not None:
            return locked
        config = Config.get_instance()
        adj = request.data.get('manuel_adjustment')
        notes = request.data.get('manuel_notes', '')
        if adj is None:
            # Clear the manual override
            commission.manuel_adjustment = None
            commission.manuel_notes = ''
        else:
            try:
                from decimal import Decimal as D
                commission.manuel_adjustment = D(str(adj))
            except Exception:
                return Response({'detail': 'Valeur invalide pour manuel_adjustment.'}, status=status.HTTP_400_BAD_REQUEST)
            commission.manuel_notes = notes
        commission.compute(float(config.annual_bonus_rate))
        commission.save(update_fields=[
            'commission_gross', 'annual_bonus',
            'deduction_carte', 'deduction_remise', 'total_deductions', 'carried_debt_in',
            'net_ordi', 'net_carte', 'net_payable',
            'manuel_adjustment', 'manuel_notes',
        ])
        log_activity(
            request.user, "Ajustement Manuel CM",
            f"Commission {commission.client.full_name} ({commission.period}) — ajustement : {commission.manuel_adjustment} FC.",
            node_origin=commission.period.node.code
        )
        return Response(ClientCommissionSerializer(commission).data)

    @action(detail=False, methods=['get'], permission_classes=[IsGerant])
    def payroll_listing(self, request):
        """Return unpaid commissions for a given period (for the pay register)."""
        period_id = request.query_params.get('period')
        if not period_id:
            return Response({'detail': '`period` query param est requis.'}, status=status.HTTP_400_BAD_REQUEST)
        qs = self.get_queryset().filter(period=period_id)
        return Response(ClientCommissionSerializer(qs, many=True).data)
