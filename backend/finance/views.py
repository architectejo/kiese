import csv
import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import (
    Sum, Count, Q, F, ExpressionWrapper, Case, When, Value, IntegerField,
    DecimalField as DjDecimalField,
)
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsHeadquarters
from kiese.node_guard import resolve_node_param
from treasury.views import _validate_month_year
from .models import FinancialYear
from .serializers import FinancialYearSerializer


_CENT = Decimal('0.01')


def _money(value) -> Decimal:
    """BUG-806 : arrondi comptable explicite (2 décimales, demi vers le haut)."""
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _money_json(data):
    """BUG-807 : montants rendus en chaînes décimales (comme `summary`), jamais en float JSON.

    Récursif (`previous_year`) ; les entiers (année) et le pourcentage de croissance
    (ratio, pas un montant) sont laissés tels quels.
    """
    if isinstance(data, dict):
        return {k: _money_json(v) for k, v in data.items()}
    if isinstance(data, Decimal):
        return str(_money(data))
    return data


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
    # BUG-802 : une régularisation (RG), ou l'ajustement d'une RG, n'est pas une vente
    # (BUG-178, CLAUDE.md 5.1).
    # BUG-801 : les lignes d'une facture d'ajustement portent la MAGNITUDE (quantités
    # positives) ; le signe est celui de `invoice.adjustment_sign` (BUG-097).
    _signed_total = ExpressionWrapper(
        F('line_total') * Case(
            When(invoice__is_adjustment=True, invoice__adjustment_sign=-1, then=Value(-1)),
            default=Value(1), output_field=IntegerField(),
        ),
        output_field=DjDecimalField(max_digits=16, decimal_places=2),
    )
    lines_qs = InvoiceLine.objects.filter(
        invoice__invoice_date__year=year,
        invoice__status='DELIVERED'
    ).exclude(
        Q(invoice__special_code='RG') | Q(invoice__adjusts__special_code='RG')
    ).annotate(signed_total=_signed_total)
    revenue_agg = lines_qs.aggregate(
        revenue_300=Sum('signed_total', filter=Q(bread_price__category='MINI')),
        revenue_400=Sum('signed_total', filter=Q(bread_price__category='MOYEN')),
        revenue_500=Sum('signed_total', filter=Q(bread_price__category='GRAND')),
        revenue_1000=Sum('signed_total', filter=Q(bread_price__category='PREMIUM')),
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
    _line_cost = ExpressionWrapper(F('quantity') * F('unit_price'), output_field=DjDecimalField(max_digits=20, decimal_places=4))
    # BUG-386 : les sorties du stock direction (nœud SIEGE, envoi vers les boulangeries)
    # sont des transferts internes, pas une consommation : exclues du coût.
    exit_qs = ConsumableMovement.objects.filter(created_at__year=year, movement_type='EXIT').exclude(node__code='SIEGE').annotate(line_cost=_line_cost)
    cost_agg = exit_qs.aggregate(
        cost_flour=Sum('line_cost', filter=Q(stock__consumable_type='FLOUR')),
        cost_yeast=Sum('line_cost', filter=Q(stock__consumable_type='YEAST')),
        cost_salt=Sum('line_cost', filter=Q(stock__consumable_type='SALT')),
        cost_oil=Sum('line_cost', filter=Q(stock__consumable_type='OIL')),
    )
    # BUG-806 : coûts matière (CUMP x quantité, 4+ décimales) arrondis à l'écriture
    # comptable ; les totaux sont calculés sur les lignes arrondies (elles somment).
    cost_flour = _money(cost_agg['cost_flour'] or Decimal('0'))
    cost_yeast = _money(cost_agg['cost_yeast'] or Decimal('0'))
    cost_salt  = _money(cost_agg['cost_salt']  or Decimal('0'))
    cost_oil   = _money(cost_agg['cost_oil']   or Decimal('0'))

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
    last = entries.order_by(*CashbookEntry.chain_order_desc()).first()
    return {
        'year': year,
        'total_entries': total_in,
        'total_exits': total_out,
        'net_cashflow': net,
        'closing_balance': last.running_balance if last else Decimal('0'),
    }


def _doc1_add_quantities(agg, inv):
    """BUG-822/823 : quantités DOC 1 signées (ajustement négatif = pains repris) ; un prix
    hors 200/300/500/1000 est totalisé dans `qty_other` (aucune perte)."""
    sign = -1 if (inv.is_adjustment and inv.adjustment_sign == -1) else 1
    for line in inv.lines.all():
        up = int(line.bread_price.unit_price) if line.bread_price else 0
        key = f'qty_{up}' if up in (200, 300, 500, 1000) else 'qty_other'
        agg[key] += sign * line.quantity


def _csv_safe(value):
    """BUG-853 : neutralise l'injection de formule (Excel/LibreOffice) dans une cellule texte."""
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value


def _doc1_aggregate(node_id, month, year):
    """Agrégat DOC 1 par client (partagé par `doc1_report` et `doc1_export`).

    BUG-851 : une vente à CLIENT DIVERS (sans client) forme une ligne « CLIENT DIVERS ».
    BUG-854 : « BP fin mois » = BP d'ouverture non tracée par facture + somme des `debt_delta`
    des factures non annulées datées <= fin du mois (méthode BUG-820), donc indépendante de
    l'ordre de saisie. BP d'ouverture = `current_debt` - somme de tous les `debt_delta` (dette
    importée / reprise sans facture). Limite : une variation de `current_debt` sans facture
    (ex. retenue hors facture) est traitée comme ouverture."""
    import calendar
    from decimal import Decimal
    from sales.models import Invoice
    from commissions.models import ClientCommission, CommissionPeriod

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

    client_agg: dict = {}
    for inv in invoices:
        cid = str(inv.client_id) if inv.client_id else 'DIVERS'
        if cid not in client_agg:
            client_agg[cid] = {
                'client': inv.client, 'client_id': inv.client_id,
                'code': inv.client.code if inv.client_id else '',
                'name': inv.client.full_name if inv.client_id else 'CLIENT DIVERS',
                'qty_200': 0, 'qty_300': 0, 'qty_500': 0, 'qty_1000': 0, 'qty_other': 0,
                'invoice_total': Decimal('0'),
                'payment_amount': Decimal('0'),
                'debt_after': Decimal('0'),
            }
        agg = client_agg[cid]
        _doc1_add_quantities(agg, inv)
        agg['invoice_total']  += inv.order_total
        agg['payment_amount'] += inv.payment_amount

    client_ids = [a['client_id'] for a in client_agg.values() if a['client_id']]
    if client_ids:
        month_end = datetime.date(int(year), int(month), calendar.monthrange(int(year), int(month))[1])
        totals_all, totals_end = {}, {}
        qs = (Invoice.objects.filter(client_id__in=client_ids).exclude(status='CANCELLED')
              .select_related('adjusts'))
        for inv in qs.iterator():
            d = inv.debt_delta
            totals_all[inv.client_id] = totals_all.get(inv.client_id, Decimal('0')) + d
            if inv.invoice_date <= month_end:
                totals_end[inv.client_id] = totals_end.get(inv.client_id, Decimal('0')) + d
        for agg in client_agg.values():
            c = agg['client']
            if c is None:
                continue
            opening = c.current_debt - totals_all.get(c.pk, Decimal('0'))
            agg['debt_after'] = opening + totals_end.get(c.pk, Decimal('0'))
    return client_agg, cm_map


def _balance_sheet_for_year(year: int) -> dict:
    from clients.models import Client
    from treasury.models import CashbookEntry
    from production.models import ConsumableStock

    from sales.models import Invoice

    # BUG-800 : bilan arrêté au 31/12 de l'exercice demandé. Exercice en cours (ou futur) :
    # situation actuelle ; exercice clos : situation reconstituée à cette date.
    year_end = datetime.date(year, 12, 31)
    is_past_year = year < timezone.localdate().year

    # Receivables (outstanding client debt)
    if is_past_year:
        # BUG-820 : BP à la clôture = somme des variations de BP (`debt_delta`) des factures
        # non annulées datées <= fin d'exercice (BUG-850 : une facture « Non servi » reste comptée,
        # son `debt_delta` vaut `-versement conservé`, comme `current_debt`). Contrairement à `debt_after` de
        # la « dernière facture », cette somme ne dépend ni de l'ordre de saisie (facture
        # antidatée) ni d'une annulation survenue après coup. Limite documentée : une dette
        # portée sans facture (import, reprise) n'apparaît pas dans un exercice clos.
        last_debt = {}
        qs = (Invoice.objects
              .filter(invoice_date__lte=year_end, client__is_active=True)
              .exclude(status='CANCELLED')
              .select_related('adjusts', 'client'))
        for inv in qs.iterator():
            last_debt[inv.client_id] = last_debt.get(inv.client_id, Decimal('0')) + inv.debt_delta
        total_receivables = sum(last_debt.values(), Decimal('0'))
    else:
        total_receivables = Client.objects.filter(is_active=True).aggregate(
            t=Sum('current_debt')
        )['t'] or Decimal('0')

    # Cash position : solde du livre à la dernière écriture datée <= fin d'exercice
    last_entry = (CashbookEntry.objects.filter(date__lte=year_end)
                  .order_by(*CashbookEntry.chain_order_desc()).first())
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
        return Response(_money_json(data))

    @action(detail=True, methods=['get'])
    def cashflow(self, request, pk=None):
        fy = self.get_object()
        data = _cashflow_for_year(fy.year)
        data['previous_year'] = _cashflow_for_year(fy.year - 1)
        return Response(_money_json(data))

    @action(detail=True, methods=['get'])
    def balance_sheet(self, request, pk=None):
        fy = self.get_object()
        data = _balance_sheet_for_year(fy.year)
        data['previous_year'] = _balance_sheet_for_year(fy.year - 1)
        return Response(_money_json(data))

    @action(detail=True, methods=['get'])
    def comparative(self, request, pk=None):
        """All four statements for N and N-1 in one call."""
        fy = self.get_object()
        return Response(_money_json({
            'income_statement': _income_statement_for_year(fy.year),
            'income_statement_prev': _income_statement_for_year(fy.year - 1),
            'cashflow': _cashflow_for_year(fy.year),
            'cashflow_prev': _cashflow_for_year(fy.year - 1),
            'balance_sheet': _balance_sheet_for_year(fy.year),
            'balance_sheet_prev': _balance_sheet_for_year(fy.year - 1),
        }))

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
        year = int(year_param) if year_param is not None else timezone.localdate().year
        node_id = request.query_params.get('node')
        if node_id:
            node, err = resolve_node_param(node_id)  # BUG-528 : inconnu -> 400
            if err is not None:
                return err
            node_id = node.pk
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
        node, err = resolve_node_param(node_id)  # BUG-528 : inconnu -> 400
        if err is not None:
            return err
        node_id = node.pk

        client_agg, cm_map = _doc1_aggregate(node_id, month, year)

        result = []
        for cid, agg in client_agg.items():
            cc = cm_map.get(cid)
            client = agg['client']
            result.append({
                'client_code':     agg['code'],
                'client_name':     agg['name'],
                'qty_200':         agg['qty_200'],
                'qty_300':         agg['qty_300'],
                'qty_500':         agg['qty_500'],
                'qty_1000':        agg['qty_1000'],
                'qty_other':       agg['qty_other'],
                'invoice_total':   str(agg['invoice_total']),
                'payment_amount':  str(agg['payment_amount']),
                'debt_after':      str(agg['debt_after']),
                'commission_rate': str(cc.commission_rate if cc else (client.commission_rate if client else 0)),
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
        node, err = resolve_node_param(node_id)  # BUG-528 : inconnu -> 400
        if err is not None:
            return err
        node_id = node.pk

        client_agg, cm_map = _doc1_aggregate(node_id, month, year)

        rows_sorted = sorted(client_agg.values(), key=lambda a: a['name'])

        header = ['CODE', 'CLIENT', 'QTÉ 200', 'QTÉ 300', 'QTÉ 500', 'QTÉ 1000', 'QTÉ AUTRES',
                  'COMMANDE (FC)', 'PAIEMENT (FC)', 'BP FIN MOIS (FC)', 'TAUX CM', 'CM (FC)']

        def _rows():
            yield header
            for agg in rows_sorted:
                cc  = cm_map.get(str(agg['client_id'])) if agg['client_id'] else None
                yield [
                    _csv_safe(agg['code']),
                    _csv_safe(agg['name']),
                    agg['qty_200'], agg['qty_300'], agg['qty_500'], agg['qty_1000'], agg['qty_other'],
                    str(agg['invoice_total']),
                    str(agg['payment_amount']),
                    str(agg['debt_after']),
                    str(cc.commission_rate if cc else (agg['client'].commission_rate if agg['client'] else 0)),
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
