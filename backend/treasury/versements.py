"""
Section « Versement » visible de la direction centrale (remarque.md :
« Dans "Clôture & Caisse" la section "Versement" doit aussi être visible chez
les membres de la direction centrale »).

Le « Versement » d'une boulangerie, c'est sa clôture de caisse du jour
(billetage physique du gérant, écart, statut de confirmation). La liste
`/api/treasury/closures/` existe déjà mais ne montre QUE les boulangeries qui
ont déjà versé : la direction ne voit pas qui n'a pas encore versé, ni les
totaux. Cette action de LECTURE SEULE donne une ligne par boulangerie visible
pour une date, avec les totaux verticaux. Elle ne change en rien qui peut
valider/infirmer/verser au livre (Q-020 en attente du client).
"""
from decimal import Decimal

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

from core.models import Node
from core.workday import work_date_for
from kiese.node_guard import parse_date_param, resolve_node_param
from .models import CashClosure
from .serializers import CashClosureSerializer

BILL_FIELDS = ('bills_20000', 'bills_10000', 'bills_5000', 'bills_1000',
               'bills_500', 'bills_200', 'bills_100', 'bills_50')
MONEY_FIELDS = ('total_entries', 'total_expenses', 'net_cash', 'physical_cash_total', 'cash_gap')


def _status_of(closure):
    if closure is None:
        return 'NON_VERSE'
    if closure.is_validated:
        return 'VALIDE'
    if closure.is_rejected:
        return 'INFIRME'
    return 'EN_ATTENTE'


class VersementsRecapMixin:
    """À mélanger à `CashClosureViewSet` (permissions : lecture = IsGerant+)."""

    @action(detail=False, methods=['get'], url_path='versements')
    def versements(self, request):
        user = request.user
        node_raw = request.query_params.get('node')
        date_raw = request.query_params.get('date')

        target_date = None
        if date_raw:
            target_date, err = parse_date_param(date_raw)
            if err:
                return Response({'detail': err}, status=status.HTTP_400_BAD_REQUEST)

        # Périmètre : siège/direction = toutes les boulangeries ; gérant = la sienne.
        if user.can_access_all_nodes:
            nodes = Node.objects.all()
        elif user.node_id:
            nodes = Node.objects.filter(pk=user.node_id)
        else:
            nodes = Node.objects.none()
        if node_raw not in (None, ''):
            node, bad = resolve_node_param(node_raw)
            if bad is not None:
                return bad
            if not nodes.filter(pk=node.pk).exists():
                return Response(
                    {'detail': "Vous n'êtes pas autorisé à consulter les versements de cette boulangerie."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            nodes = nodes.filter(pk=node.pk)
        nodes = list(nodes.order_by('code'))

        # Sans date : le jour de travail courant (date locale calendaire).
        row_date = target_date or work_date_for(None)
        qs = (CashClosure.objects.filter(node__in=nodes, date=row_date)
              .select_related('node', 'gerant').prefetch_related('cashbook_entries'))
        by_node = {c.node_id: c for c in qs}

        zero = Decimal('0.00')
        totals = {f: zero for f in MONEY_FIELDS}
        totals_bills = {f: 0 for f in BILL_FIELDS}
        counts = {'NON_VERSE': 0, 'EN_ATTENTE': 0, 'VALIDE': 0, 'INFIRME': 0}
        results = []
        for n in nodes:
            c = by_node.get(n.pk)
            st = _status_of(c)
            counts[st] += 1
            row = {
                'node': n.pk, 'node_code': n.code, 'node_display': str(n),
                'date': row_date.isoformat(),
                'status': st,
                'closure': CashClosureSerializer(c).data if c is not None else None,
            }
            for f in MONEY_FIELDS:
                v = getattr(c, f) if c is not None else zero
                row[f] = str(v)
                totals[f] += v
            for f in BILL_FIELDS:
                totals_bills[f] += getattr(c, f) if c is not None else 0
            results.append(row)

        return Response({
            'date': row_date.isoformat(),
            'count': len(results),
            'results': results,
            'totals': {
                **{f: str(v) for f, v in totals.items()},
                'bills': totals_bills,
                'counts': counts,
                'versed_count': len(results) - counts['NON_VERSE'],
            },
        })
