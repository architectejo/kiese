import csv
import datetime
from decimal import Decimal
from django.db.models import Sum, Count, Q, F, ExpressionWrapper, DecimalField as DjDecimalField
from django.http import StreamingHttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsHeadquarters
from treasury.views import _validate_month_year
from .models import FinancialYear
from .serializers import FinancialYearSerializer


def _income_statement_for_year(year: int) -> dict:
    """Compute income statement from real data for a given year.

    BUG-066 : chaque agrégat par catégorie/type était auparavant calculé par
    un `.aggregate()` séparé (4 requêtes pour le revenu, 4 pour le COGS), ce
    qui rescanne 4 fois la même jointure `InvoiceLine ⋈ Invoice` (resp.
    `ConsumableMovement ⋈ ConsumableStock`) filtrée par année — mesuré comme
    le facteur dominant de la lenteur de `FinancialYearViewSet.comparative()`
    (testeur-charge, 921-1025 ms, 24 000 factures/8 nœuds/10 jours). Un seul
    `.aggregate()` avec plusieurs `Sum(..., filter=Q(...))` produit UNE seule
    requête SQL (SUM(CASE WHEN ...) côte à côte) au lieu de 4 — même résultat,
    4x moins de scans.
    """
    from sales.models import Invoice, InvoiceLine
    from commissions.models import ClientCommission
    from treasury.models import LocalExpense, CashbookEntry

    # Revenue by bread category — une seule requête (4 Sum conditionnels)
    lines_qs = InvoiceLine.objects.filter(
        invoice__invoice_date__year=year,
        invoice__status='DELIVERED'
    )
    revenue_agg = lines_qs.aggregate(
        revenue_300=Sum('line_total', filter=Q(bread_price__category='MINI')),
        revenue_400=Sum('line_total', filter=Q(bread_price__category='MOYEN')),
        revenue_500=Sum('line_total', filter=Q(bread_price__category='GRAND')),
        revenue_1000=Sum('line_total', filter=Q(bread_price__category='PREMIUM')),
    )
    revenue_300  = revenue_agg['revenue_300']  or Decimal('0')
    revenue_400  = revenue_agg['revenue_400']  or Decimal('0')
    revenue_500  = revenue_agg['revenue_500']  or Decimal('0')
    revenue_1000 = revenue_agg['revenue_1000'] or Decimal('0')
    total_revenue = revenue_300 + revenue_400 + revenue_500 + revenue_1000

    # COGS : coût de la CONSOMMATION RÉELLE en production (mouvements EXIT),
    # pas des achats du mois (ENTRY) — décision du client (Q-005,
    # docs/qa/QUESTIONS_CLIENT.md, 2026-11-02, BUG-058/ECART_CADRE_COMPTABLE.md
    # §[D]). Chaque sortie est valorisée au Coût Unitaire Moyen Pondéré (CUMP)
    # du consommable au moment de la sortie (`ConsumableMovement.unit_price`,
    # figé par `ConsumableMovement.save()` — BUG-123) : même formule
    # `quantity × unit_price` qu'avant, seul le type de mouvement change —
    # une seule requête (4 Sum conditionnels), toujours couverte par l'index
    # `prod_consmove_type_crea_idx` (movement_type, created_at), donc sans
    # régression de performance (BUG-064/066/070).
    from production.models import ConsumableMovement
    _line_cost = ExpressionWrapper(F('quantity') * F('unit_price'), output_field=DjDecimalField(max_digits=14, decimal_places=2))
    exit_qs = ConsumableMovement.objects.filter(created_at__year=year, movement_type='EXIT').annotate(line_cost=_line_cost)
    cost_agg = exit_qs.aggregate(
        cost_flour=Sum('line_cost', filter=Q(stock__consumable_type='FLOUR')),
        cost_yeast=Sum('line_cost', filter=Q(stock__consumable_type='YEAST')),
        cost_salt=Sum('line_cost', filter=Q(stock__consumable_type='SALT')),
        cost_oil=Sum('line_cost', filter=Q(stock__consumable_type='OIL')),
    )
    cost_flour = cost_agg['cost_flour'] or Decimal('0')
    cost_yeast = cost_agg['cost_yeast'] or Decimal('0')
    cost_salt  = cost_agg['cost_salt']  or Decimal('0')
    cost_oil   = cost_agg['cost_oil']   or Decimal('0')

    # Local expenses
    expenses = LocalExpense.objects.filter(date__year=year).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    # Commissions paid
    commissions_paid = ClientCommission.objects.filter(
        period__year=year, is_paid=True
    ).aggregate(t=Sum('net_payable'))['t'] or Decimal('0')

    gross_profit = total_revenue - (cost_flour + cost_yeast + cost_salt + cost_oil)
    net_result   = gross_profit - commissions_paid - expenses

    return {
        'year': year,
        'revenue_300': revenue_300,
        'revenue_400': revenue_400,
        'revenue_500': revenue_500,
        'revenue_1000': revenue_1000,
        'total_revenue': total_revenue,
        'cost_flour': cost_flour,
        'cost_yeast': cost_yeast,
        'cost_salt': cost_salt,
        'cost_oil': cost_oil,
        'gross_profit': gross_profit,
        'commissions_paid': commissions_paid,
        'operational_expenses': expenses,
        'net_result': net_result,
    }


def _cashflow_for_year(year: int) -> dict:
    """
    BUG-066 : `total_in`/`total_out` étaient calculés par deux `.aggregate()`
    séparés (2 requêtes identiques sur le même queryset) — fusionnés en un
    seul appel (1 requête, 2 `Sum` côte à côte).
    """
    from treasury.models import CashbookEntry
    entries = CashbookEntry.objects.filter(date__year=year)
    totals = entries.aggregate(total_in=Sum('entry_amount'), total_out=Sum('exit_amount'))
    total_in  = totals['total_in']  or Decimal('0')
    total_out = totals['total_out'] or Decimal('0')
    net = total_in - total_out
    last = entries.order_by('-date', '-created_at').first()
    return {
        'year': year,
        'total_entries': total_in,
        'total_exits': total_out,
        'net_cashflow': net,
        'closing_balance': last.running_balance if last else Decimal('0'),
    }


def _balance_sheet_for_year(year: int) -> dict:
    from clients.models import Client
    from treasury.models import CashbookEntry
    from production.models import ConsumableStock

    # Receivables (outstanding client debt)
    total_receivables = Client.objects.filter(is_active=True).aggregate(
        t=Sum('current_debt')
    )['t'] or Decimal('0')

    # Cash position
    last_entry = CashbookEntry.objects.order_by('-date', '-created_at').first()
    cash = last_entry.running_balance if last_entry else Decimal('0')

    return {
        'year': year,
        'receivables': total_receivables,
        'cash_position': cash,
        'total_assets': total_receivables + cash,
    }


class FinancialYearViewSet(viewsets.ModelViewSet):
    queryset = FinancialYear.objects.all()
    serializer_class = FinancialYearSerializer

    def get_permissions(self):
        # BUG-101 : tous les états financiers consolidés du groupe (aucun filtre par
        # `node` possible, agrégation globale) exigent IsHeadquarters, comme le Livre
        # de Caisse (BUG-026). `summary`/`doc1_report`/`doc1_export` déclarent
        # `permission_classes=[IsAuthenticated]` sur leur `@action`, mais cette
        # surcharge de `get_permissions()` les ignore déjà et retombe ici — donc
        # IsHeadquarters s'applique uniformément à toutes les actions du ViewSet.
        return [IsHeadquarters()]

    @action(detail=True, methods=['get'])
    def income_statement(self, request, pk=None):
        fy = self.get_object()
        data = _income_statement_for_year(fy.year)
        # Comparative with previous year
        prev = _income_statement_for_year(fy.year - 1)
        data['previous_year'] = prev
        if prev['total_revenue'] > 0:
            data['revenue_growth_pct'] = round(
                float((data['total_revenue'] - prev['total_revenue']) / prev['total_revenue'] * 100), 2
            )
        else:
            data['revenue_growth_pct'] = None
        return Response(data)

    @action(detail=True, methods=['get'])
    def cashflow(self, request, pk=None):
        fy = self.get_object()
        data = _cashflow_for_year(fy.year)
        data['previous_year'] = _cashflow_for_year(fy.year - 1)
        return Response(data)

    @action(detail=True, methods=['get'])
    def balance_sheet(self, request, pk=None):
        fy = self.get_object()
        data = _balance_sheet_for_year(fy.year)
        data['previous_year'] = _balance_sheet_for_year(fy.year - 1)
        return Response(data)

    @action(detail=True, methods=['get'])
    def comparative(self, request, pk=None):
        """All four statements for N and N-1 in one call."""
        fy = self.get_object()
        return Response({
            'income_statement': _income_statement_for_year(fy.year),
            'income_statement_prev': _income_statement_for_year(fy.year - 1),
            'cashflow': _cashflow_for_year(fy.year),
            'cashflow_prev': _cashflow_for_year(fy.year - 1),
            'balance_sheet': _balance_sheet_for_year(fy.year),
            'balance_sheet_prev': _balance_sheet_for_year(fy.year - 1),
        })

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def summary(self, request):
        """Monthly CM summary per node for a given year: commandes/CM/net by period.

        BUG-070 : auparavant, une boucle Python sur chaque `CommissionPeriod`
        exécutait 2 requêtes séparées (`.aggregate()` puis `.count()`) par
        période (194 requêtes mesurées pour 96 périodes). Remplacé par une
        seule requête groupée `.values('period').annotate(...)` sur l'ensemble
        des `ClientCommission` des périodes concernées, dont les résultats
        sont ensuite réassociés en mémoire aux `CommissionPeriod` déjà
        chargés — même résultat, nombre de requêtes indépendant du nombre de
        périodes.
        """
        from commissions.models import CommissionPeriod, ClientCommission
        year_param = request.query_params.get('year')
        # BUG-117 : même défaut que BUG-114/115 — `int()` direct sur un
        # paramètre de requête non numérique (ex. year='abc') levait une
        # `ValueError` non rattrapée → 500. `_validate_month_year` accepte
        # `month=None` (aucun filtre mois demandé) et ne valide alors que
        # `year`, bornes 2000-2100 incluses — réutilisée ici sans dupliquer
        # la logique de validation.
        error = _validate_month_year(None, year_param)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
        year = int(year_param) if year_param is not None else datetime.date.today().year
        node_id = request.query_params.get('node')
        qs = CommissionPeriod.objects.filter(year=year).select_related('node')
        if node_id:
            qs = qs.filter(node_id=node_id)
        periods = list(qs.order_by('month', 'node__code'))

        agg_rows = ClientCommission.objects.filter(period__in=periods).values('period').annotate(
            total_orders=Sum('order_value'),
            total_cm=Sum('commission_gross'),
            total_net=Sum('net_payable'),
            total_debt=Sum('deduction_debt'),
            client_count=Count('id'),
        )
        agg_by_period = {row['period']: row for row in agg_rows}

        result = []
        for period in periods:
            agg = agg_by_period.get(period.id, {})
            result.append({
                'node':         str(period.node_id),
                'node_code':    period.node.code,
                'node_name':    period.node.name,
                'month':        period.month,
                'year':         period.year,
                'period_id':    str(period.id),
                'is_closed':    period.is_closed,
                'client_count': agg.get('client_count') or 0,
                'total_orders': str(agg.get('total_orders') or 0),
                'total_cm':     str(agg.get('total_cm')     or 0),
                'total_net':    str(agg.get('total_net')     or 0),
                'total_debt':   str(agg.get('total_debt')    or 0),
            })
        return Response(result)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def doc1_report(self, request):
        """DOC 1: monthly aggregate per client for node/month/year (one row per client)."""
        from sales.models import Invoice
        from commissions.models import ClientCommission, CommissionPeriod
        from decimal import Decimal
        node_id = request.query_params.get('node')
        month   = request.query_params.get('month')
        year    = request.query_params.get('year')
        if not all([node_id, month, year]):
            return Response({'detail': 'node, month et year sont requis.'}, status=status.HTTP_400_BAD_REQUEST)
        # BUG-115 : même défaut que BUG-114/BUG-115 (treasury) — valider
        # avant tout `invoice_date__month=`/`invoice_date__year=` pour
        # éviter une `ValueError` → 500 (ex. year='abc' ou year=20000).
        error = _validate_month_year(month, year)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        invoices = (
            Invoice.objects
            .filter(node_id=node_id, status='DELIVERED', invoice_date__month=month, invoice_date__year=year)
            .select_related('client')
            .prefetch_related('lines__bread_price')
            .order_by('client__last_name', 'invoice_date')
        )
        try:
            period = CommissionPeriod.objects.get(node_id=node_id, month=month, year=year)
            cm_map = {str(cc.client_id): cc for cc in ClientCommission.objects.filter(period=period)}
        except CommissionPeriod.DoesNotExist:
            cm_map = {}

        # Aggregate by client
        client_agg: dict = {}
        for inv in invoices:
            cid = str(inv.client_id)
            if cid not in client_agg:
                client_agg[cid] = {
                    'client': inv.client,
                    'qty_200': 0, 'qty_300': 0, 'qty_500': 0, 'qty_1000': 0,
                    'invoice_total': Decimal('0'),
                    'payment_amount': Decimal('0'),
                    'debt_after': Decimal('0'),  # last invoice BP
                    'last_date': inv.invoice_date,
                }
            agg = client_agg[cid]
            for line in inv.lines.all():
                up = int(line.bread_price.unit_price) if line.bread_price else 0
                if up in (200, 300, 500, 1000):
                    agg[f'qty_{up}'] += line.quantity
            agg['invoice_total']  += inv.order_total
            agg['payment_amount'] += inv.payment_amount
            # Keep the most recent debt_after as end-of-month BP
            if inv.invoice_date >= agg['last_date']:
                agg['debt_after'] = inv.debt_after
                agg['last_date']  = inv.invoice_date

        result = []
        for cid, agg in client_agg.items():
            cc = cm_map.get(cid)
            client = agg['client']
            result.append({
                'client_code':     client.code,
                'client_name':     client.full_name,
                'qty_200':         agg['qty_200'],
                'qty_300':         agg['qty_300'],
                'qty_500':         agg['qty_500'],
                'qty_1000':        agg['qty_1000'],
                'invoice_total':   str(agg['invoice_total']),
                'payment_amount':  str(agg['payment_amount']),
                'debt_after':      str(agg['debt_after']),
                'commission_rate': str(cc.commission_rate if cc else client.commission_rate),
                'cm_amount':       str(cc.commission_gross if cc else 0),
            })
        # Sort by client name
        result.sort(key=lambda r: r['client_name'])
        return Response(result)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated], url_path='doc1_export')
    def doc1_export(self, request):
        """DOC 1 CSV export: monthly aggregate per client (UTF-8 BOM for Excel)."""
        from sales.models import Invoice
        from commissions.models import ClientCommission, CommissionPeriod
        from decimal import Decimal
        node_id = request.query_params.get('node')
        month   = request.query_params.get('month')
        year    = request.query_params.get('year')
        if not all([node_id, month, year]):
            return Response({'detail': 'node, month et year sont requis.'}, status=status.HTTP_400_BAD_REQUEST)
        # BUG-115 : même défaut que BUG-114/BUG-115 (treasury) — valider
        # avant tout `invoice_date__month=`/`invoice_date__year=` pour
        # éviter une `ValueError` → 500 (ex. year='abc' ou year=20000).
        error = _validate_month_year(month, year)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        invoices = (
            Invoice.objects
            .filter(node_id=node_id, status='DELIVERED', invoice_date__month=month, invoice_date__year=year)
            .select_related('client')
            .prefetch_related('lines__bread_price')
            .order_by('client__last_name', 'invoice_date')
        )
        try:
            period = CommissionPeriod.objects.get(node_id=node_id, month=month, year=year)
            cm_map = {str(cc.client_id): cc for cc in ClientCommission.objects.filter(period=period)}
        except CommissionPeriod.DoesNotExist:
            cm_map = {}

        # Aggregate by client
        client_agg: dict = {}
        for inv in invoices:
            cid = str(inv.client_id)
            if cid not in client_agg:
                client_agg[cid] = {
                    'client': inv.client,
                    'qty_200': 0, 'qty_300': 0, 'qty_500': 0, 'qty_1000': 0,
                    'invoice_total': Decimal('0'),
                    'payment_amount': Decimal('0'),
                    'debt_after': Decimal('0'),
                    'last_date': inv.invoice_date,
                }
            agg = client_agg[cid]
            for line in inv.lines.all():
                up = int(line.bread_price.unit_price) if line.bread_price else 0
                if up in (200, 300, 500, 1000):
                    agg[f'qty_{up}'] += line.quantity
            agg['invoice_total']  += inv.order_total
            agg['payment_amount'] += inv.payment_amount
            if inv.invoice_date >= agg['last_date']:
                agg['debt_after'] = inv.debt_after
                agg['last_date']  = inv.invoice_date

        rows_sorted = sorted(client_agg.values(), key=lambda a: a['client'].full_name)

        header = ['CODE', 'CLIENT', 'QTÉ 200', 'QTÉ 300', 'QTÉ 500', 'QTÉ 1000',
                  'COMMANDE (FC)', 'PAIEMENT (FC)', 'BP FIN MOIS (FC)', 'TAUX CM', 'CM (FC)']

        def _rows():
            yield header
            for agg in rows_sorted:
                cid = str(agg['client'].id)
                cc  = cm_map.get(cid)
                yield [
                    agg['client'].code,
                    agg['client'].full_name,
                    agg['qty_200'], agg['qty_300'], agg['qty_500'], agg['qty_1000'],
                    str(agg['invoice_total']),
                    str(agg['payment_amount']),
                    str(agg['debt_after']),
                    str(cc.commission_rate if cc else agg['client'].commission_rate),
                    str(cc.commission_gross if cc else 0),
                ]

        class _Echo:
            def write(self, value): return value

        writer = csv.writer(_Echo())
        response = StreamingHttpResponse(
            (writer.writerow(row) for row in _rows()),
            content_type='text/csv; charset=utf-8-sig',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="DOC1_{year}_{str(month).zfill(2)}.csv"'
        )
        return response
