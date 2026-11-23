"""Lot I-3 : statistiques mensuelles de la farine (feuille « ENTREE FARINE » du client).

GET /api/production/consumables/flour-month-stats/?month=AAAA-MM[&node=<id|code>]

Regles de calcul (a faire confirmer par le client, voir BUG-1110) :
* consommation = somme de `ProductionSession.flour_sacks_used` par boulangerie et par
  `date` de la fournee (fournees ouvertes ET cloturees : le jour indique `open_sessions`) ;
* entrees = mouvements ENTRY de farine du stock direction (noeud SIEGE) ; date = jour
  local de creation ; PT = quantite x PU ; PU du jour = PT du jour / quantite du jour ;
* solde courant = solde initial + entrees cumulees - consommation cumulee (regle des
  formules du fichier : N(j) = N(j-1) + entree(j) - total(j)). Le fichier code le solde
  initial en dur ; ici il est reconstitue : stock reel direction aujourd'hui moins le solde
  signe des mouvements du noeud SIEGE crees depuis le 1er du mois ;
* moyenne par jour = total / nombre de jours ou la colonne a une consommation > 0
  (`average_per_calendar_day` donne aussi la regle du fichier : total / jours du mois) ;
* ecart du mois : le fichier le calcule contre un « Tot passe » saisi a la main ;
  aucune valeur de reference n'existe dans l'application : omis.
Aucun float : Decimal, serialise en chaine a 2 decimales.
"""
import calendar
import datetime
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Node
from kiese.node_guard import resolve_node_param

from .models import ConsumableMovement, ConsumableStock, ProductionSession

SIEGE_CODE = 'SIEGE'
Q2 = Decimal('0.01')
ZERO = Decimal('0')
_MONTH_RE = re.compile(r'([0-9]{4})-([0-9]{2})')
MAX_MONTHS_AHEAD = 12


class IsHeadquartersOrGerant(BasePermission):
    message = "Réservé à la direction, au comptable et aux gérants."

    def has_permission(self, request, view):
        u = request.user
        return bool(u.is_authenticated and (u.is_superuser or u.role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT')))


def _bad(message):
    return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)


def _q(value):
    return str(value.quantize(Q2, rounding=ROUND_HALF_UP))


def parse_month(raw):
    """AAAA-MM strict (chiffres ASCII, annee 2000-2200, mois 1-12, pas plus de 12 mois dans le futur).
    Retourne ((annee, mois), None) ou (None, message FR)."""
    msg = "Paramètre « month » invalide : format attendu AAAA-MM (ex. 2026-11)."
    if not isinstance(raw, str):
        return None, msg
    m = _MONTH_RE.fullmatch(raw)
    if not m:
        return None, msg
    year, month = int(m.group(1)), int(m.group(2))
    if not 2000 <= year <= 2200 or not 1 <= month <= 12:
        return None, msg
    today = timezone.localdate()
    if (year * 12 + month) > (today.year * 12 + today.month + MAX_MONTHS_AHEAD):
        return None, "Mois trop éloigné dans le futur."
    return (year, month), None


class FlourMonthStatsView(APIView):
    permission_classes = [IsHeadquartersOrGerant]

    def get(self, request):
        ym, error = parse_month(request.query_params.get('month'))
        if error:
            return _bad(error)
        body, resp = build_month_stats(request.user, ym[0], ym[1], request.query_params.get('node'))
        return resp if resp is not None else Response(body)


def build_month_stats(user, year, month, raw_node):
    """Calcul pur (lot I-4 : reutilise par l'export Excel) : retourne (corps JSON, None) ou
    (None, Response d'erreur). `raw_node` = valeur brute de `?node=` (ignoree pour un gerant)."""
    if True:
        ndays = calendar.monthrange(year, month)[1]
        first = datetime.date(year, month, 1)
        last = datetime.date(year, month, ndays)
        bakeries = Node.objects.filter(is_active=True).exclude(code=SIEGE_CODE).order_by('code')
        hq = user.can_access_all_nodes
        if hq:
            if raw_node not in (None, ''):
                node, resp = resolve_node_param(raw_node)
                if resp is not None:
                    return None, resp
                if node.code == SIEGE_CODE or not node.is_active:
                    return None, _bad("Boulangerie inactive ou non valide pour cette statistique.")
                bakeries = bakeries.filter(pk=node.pk)
        else:
            # Gérant : sa boulangerie seulement, paramètre node ignoré ; sans boulangerie : rien.
            bakeries = bakeries.filter(pk=user.node_id) if user.node_id else bakeries.none()
        bakeries = list(bakeries.values('id', 'code', 'name'))
        ids = [b['id'] for b in bakeries]

        # Consommation : un seul aggregat par (boulangerie, jour).
        cons = defaultdict(lambda: ZERO)
        open_days = defaultdict(int)
        for row in (ProductionSession.objects.filter(node_id__in=ids, date__gte=first, date__lte=last)
                    .values('node_id', 'date', 'is_closed').annotate(total=Sum('flour_sacks_used'))):
            cons[(row['node_id'], row['date'])] += row['total'] or ZERO
            if not row['is_closed']:
                open_days[row['date']] += 1

        # Achats et solde : stock de la direction, visible des seuls profils siège.
        entries_q, entries_pt = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
        initial = None
        if hq:
            siege = Node.objects.filter(code=SIEGE_CODE).values_list('pk', flat=True).first()
            tz = timezone.get_current_timezone()
            start = datetime.datetime.combine(first, datetime.time.min, tzinfo=tz)
            end = datetime.datetime.combine(last + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
            initial = ZERO
            if siege is not None:
                base = ConsumableMovement.objects.filter(node_id=siege, stock__consumable_type='FLOUR')
                for qty, price, created in (base.filter(
                        movement_type='ENTRY', created_at__gte=start, created_at__lt=end)
                        .values_list('quantity', 'unit_price', 'created_at')):
                    day = timezone.localtime(created).date()
                    entries_q[day] += qty
                    entries_pt[day] += qty * (price or ZERO)
                current = ConsumableStock.objects.filter(
                    node_id=siege, consumable_type='FLOUR').values_list('quantity', flat=True).first() or ZERO
                since = {r['movement_type']: r['t'] or ZERO for r in base.filter(created_at__gte=start)
                         .values('movement_type').annotate(t=Sum('quantity'))}
                initial = current - (since.get('ENTRY', ZERO) - since.get('EXIT', ZERO))

        rows = []
        totals = defaultdict(lambda: ZERO)
        active_days = defaultdict(int)
        balance = initial
        for d in range(1, ndays + 1):
            day = datetime.date(year, month, d)
            per = {}
            day_total = ZERO
            for b in bakeries:
                v = cons.get((b['id'], day), ZERO)
                per[b['code']] = v
                day_total += v
                totals[b['code']] += v
                if v > 0:
                    active_days[b['code']] += 1
            totals['_total'] += day_total
            if day_total > 0:
                active_days['_total'] += 1
            row = {
                'date': day.isoformat(),
                'consumption': {code: _q(v) for code, v in per.items()},
                'total': _q(day_total),
                'open_sessions': open_days.get(day, 0),
            }
            if hq:
                eq, ept = entries_q.get(day, ZERO), entries_pt.get(day, ZERO)
                balance = balance + eq - day_total
                row.update({
                    'entry_quantity': _q(eq),
                    'unit_price': _q(ept / eq) if eq > 0 else None,
                    'total_price': _q(ept),
                    'balance': _q(balance),
                })
            rows.append(row)

        codes = [b['code'] for b in bakeries]
        summary = {
            'total': {**{c: _q(totals[c]) for c in codes}, 'total': _q(totals['_total'])},
            'average_per_day': {**{c: _q(totals[c] / active_days[c]) if active_days[c] else _q(ZERO) for c in codes},
                                'total': _q(totals['_total'] / active_days['_total']) if active_days['_total'] else _q(ZERO)},
            'average_per_calendar_day': {**{c: _q(totals[c] / ndays) for c in codes},
                                         'total': _q(totals['_total'] / ndays)},
            'active_days': {**{c: active_days[c] for c in codes}, 'total': active_days['_total']},
        }
        body = {
            'month': f'{year:04d}-{month:02d}',
            'days_in_month': ndays,
            'bakeries': [{'code': b['code'], 'name': b['name']} for b in bakeries],
            'rows': rows,
            'summary': summary,
            'direction_visible': hq,
            'notes': ["Écart du mois non calculé : aucune valeur de référence (« Tot passé ») n'existe dans l'application.",
                      "Colonne « vente » du fichier non reprise : à préciser avec le client."],
        }
        if hq:
            qty_total = sum(entries_q.values(), ZERO)
            pt_total = sum(entries_pt.values(), ZERO)
            body['purchases'] = {
                'quantity': _q(qty_total), 'total_price': _q(pt_total),
                'average_unit_price': _q(pt_total / qty_total) if qty_total > 0 else None,
            }
            body['opening_balance'] = _q(initial)
            body['closing_balance'] = rows[-1]['balance']
        return body, None
