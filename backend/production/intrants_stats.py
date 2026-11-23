"""Lot I-1 (BUG-1060) : statistiques JOURNALIERES des intrants (farine, levure, huile, sel).

GET /api/production/intrants-stats/?date=AAAA-MM-JJ&type=FLOUR|YEAST|OIL|SALT[&node=<id|code>]

Reproduit, pour un jour et un intrant, le tableau du client (fichier « STATISQUES NOVEMBRE 2026
LOGICIEL ») : une ligne par boulangerie active, une ligne D1 (stock de la direction = noeud
technique SIEGE), une ligne TOTAUX. Colonnes : stock initial, entree, sortie, total avant
production, consommation du jour, solde comptable, reference production (sacs de farine du jour),
indice de consommation, reste declare (inventaire physique du jour), ecart.

Reutilise les donnees existantes (aucun nouveau modele) : `ConsumableStock` (stock courant),
`ConsumableMovement` (entrees/sorties), `ProductionSession` (sacs), `ConsumableInventory` +
`ConsumableCount` (reste declare). Tout est en `Decimal`, arrondi a l'ecriture (3 decimales pour les
quantites, 4 pour l'indice) ; jamais de `float`.

Definitions (jour J, noeud N, intrant T) :
- date effective d'un mouvement = date de la fournee s'il est rattache a une fournee, sinon jour
  local de son horodatage ;
- stock initial = stock courant moins l'effet net des mouvements dont la date effective est >= J ;
- entree = somme des ENTRY de J ; sortie = somme des EXIT de J NON rattaches a une fournee
  (envois de la direction, sorties manuelles) ;
- consommation = sacs declares (`flour_sacks_used`) des fournees de J pour la farine, sinon
  somme des EXIT rattaches a une fournee de J (`consumables_used`) ;
- total avant production = initial + entree - sortie ; solde comptable = total - consommation ;
- reference production = somme de `flour_sacks_used` des fournees de J ;
- indice = consommation / reference production (None si reference = 0, jamais de division par zero) ;
- reste declare = quantite physique de l'inventaire du jour (None si absent) ;
- ecart = reste declare - solde comptable (None si non declare : jamais l'oppose du solde).

HYPOTHESES (questions client Q-044 a Q-050 en attente, NON tranchees ici) : formule
`initial + entree - sortie` pour tous les intrants (le tableur de l'huile ecrit `entree x sortie`),
unites actuelles de l'application (farine en sacs, levure en paquets, huile en litres, sel en
grammes ; la conversion sacs/boites `Bte/U` du sel n'est pas appliquee), signe de l'ecart =
declare - comptable, colonne « ok » du sel ignoree, ligne TOTAUX = boulangeries + D1 (ecart et
reste declare totalises sur les seules lignes declarees). Ces hypotheses sont renvoyees dans le JSON.
"""
import re
from datetime import date as date_cls
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Node
from core.mixins import is_node_less_non_hq
from kiese.node_guard import resolve_node_param

from .models import (ConsumableCount, ConsumableInventory, ConsumableMovement, ConsumableStock,
                     ConsumableType, ProductionSession)

SIEGE_CODE = 'SIEGE'
ZERO = Decimal('0')
Q3 = Decimal('0.001')
Q4 = Decimal('0.0001')

# Intrants geres. SALT et OIL : structure seulement (regles ambigues, voir hypotheses).
SUPPORTED_TYPES = {
    'FLOUR': ('Farine', 'sacs'),
    'YEAST': ('Levure', 'paquets'),
    'OIL': ('Huile', 'litres'),
    'SALT': ('Sel', 'g'),
}

HYPOTHESES = [
    "Total avant production = stock initial + entrée − sortie pour tous les intrants (huile comprise : "
    "la formule « entrée × sortie » du tableur n'est pas reprise).",
    "Unités de l'application : farine en sacs, levure en paquets, huile en litres, sel en grammes "
    "(la conversion sacs/boîtes « Bte/U » du sel n'est pas appliquée).",
    "Écart = reste déclaré − solde comptable ; vide (null) si le reste n'est pas déclaré.",
    "La colonne « ok » du tableur n'est pas reprise.",
    "Indice de consommation = consommation ÷ sacs de farine utilisés le même jour ; vide (null) "
    "si aucun sac n'a été utilisé.",
    "La ligne TOTAUX additionne les boulangeries affichées et D1 ; le reste déclaré et l'écart "
    "totalisent uniquement les lignes déclarées.",
]

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _q3(value):
    return None if value is None else str(value.quantize(Q3))


def _error(message, code=400):
    return Response({'detail': message}, status=code)


class CanReadIntrantsStats(BasePermission):
    """ADMIN, DIRECTION, COMPTABLE (toutes boulangeries + D1) et GERANT (sa boulangerie)."""
    message = "Statistiques des intrants réservées à la direction, au comptable et au gérant."

    def has_permission(self, request, view):
        u = request.user
        return bool(u.is_authenticated and (
            u.is_superuser or u.role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT')))


def parse_day(raw):
    """AAAA-MM-JJ strict (ASCII), annee 2000-2100. Retourne (date, None) ou (None, message)."""
    if raw is None:
        return timezone.localdate(), None
    bad = "Paramètre « date » invalide — format attendu AAAA-MM-JJ."
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        return None, bad
    try:
        day = date_cls.fromisoformat(raw)
    except ValueError:
        return None, bad
    if not 2000 <= day.year <= 2100:
        return None, "Paramètre « date » hors limites (années 2000 à 2100)."
    return day, None


def compute_rows(day, code, nodes):
    """Calcule une ligne par noeud de `nodes` (liste de Node). Retourne une liste de dicts
    de Decimal / None (non arrondis)."""
    node_ids = [n.pk for n in nodes]
    stocks = dict(ConsumableStock.objects.filter(
        consumable_type=code, node_id__in=node_ids).values_list('node_id', 'quantity'))

    entry = {i: ZERO for i in node_ids}
    exit_free = {i: ZERO for i in node_ids}
    exit_session = {i: ZERO for i in node_ids}
    net_from_day = {i: ZERO for i in node_ids}
    movements = ConsumableMovement.objects.filter(
        stock__consumable_type=code, node_id__in=node_ids,
    ).filter(
        Q(session__isnull=True, created_at__date__gte=day)
        | Q(session__isnull=False, session__date__gte=day)
    ).values('node_id', 'movement_type', 'quantity', 'created_at', 'session_id', 'session__date')
    for m in movements:
        eff = m['session__date'] if m['session_id'] else timezone.localtime(m['created_at']).date()
        if eff < day:
            continue
        qty = m['quantity']
        is_entry = m['movement_type'] == ConsumableMovement.MovementType.ENTRY
        net_from_day[m['node_id']] += qty if is_entry else -qty
        if eff != day:
            continue
        if is_entry:
            entry[m['node_id']] += qty
        elif m['session_id']:
            exit_session[m['node_id']] += qty
        else:
            exit_free[m['node_id']] += qty

    sacks = {i: ZERO for i in node_ids}
    for nid, used in ProductionSession.objects.filter(
            date=day, node_id__in=node_ids).values_list('node_id', 'flour_sacks_used'):
        sacks[nid] += used

    declared = {}
    for nid, qty in ConsumableCount.objects.filter(
            inventory__inventory_date=day, inventory__node_id__in=node_ids,
            consumable_type=code).order_by('inventory__updated_at', 'pk').values_list(
            'inventory__node_id', 'physical_quantity'):
        declared[nid] = qty  # le dernier ecrase les precedents

    rows = []
    for n in nodes:
        i = n.pk
        initial = stocks.get(i, ZERO) - net_from_day[i]
        consumption = sacks[i] if code == 'FLOUR' else exit_session[i]
        rows.append(_build(initial, entry[i], exit_free[i], consumption, sacks[i], declared.get(i)))
    return rows


def _build(initial, entry, exit_, consumption, reference, declared):
    total = initial + entry - exit_
    balance = total - consumption
    return {
        'initial': initial, 'entry': entry, 'exit': exit_,
        'total_before_production': total, 'consumption': consumption, 'balance': balance,
        'production_reference': reference,
        'consumption_index': (consumption / reference) if reference > 0 else None,
        'declared_remaining': declared,
        'gap': (declared - balance) if declared is not None else None,
    }


def _serialize(row, **ident):
    out = dict(ident)
    for key in ('initial', 'entry', 'exit', 'total_before_production', 'consumption', 'balance',
                'production_reference', 'declared_remaining', 'gap'):
        out[key] = _q3(row[key])
    idx = row['consumption_index']
    out['consumption_index'] = None if idx is None else str(idx.quantize(Q4))
    return out


def _totals(rows):
    def s(key):
        return sum((r[key] for r in rows), ZERO)
    decl = [r['declared_remaining'] for r in rows if r['declared_remaining'] is not None]
    gaps = [r['gap'] for r in rows if r['gap'] is not None]
    t = _build(s('initial'), s('entry'), s('exit'), s('consumption'), s('production_reference'),
               sum(decl, ZERO) if decl else None)
    t['gap'] = sum(gaps, ZERO) if gaps else None
    return t


class IntrantsStatsView(APIView):
    """GET /api/production/intrants-stats/ : tableau journalier d'un intrant (lot I-1)."""
    permission_classes = [CanReadIntrantsStats]

    def get(self, request):
        user = request.user
        if is_node_less_non_hq(user):
            return _error("Votre compte n'est rattaché à aucune boulangerie : action impossible.", 403)

        code = request.query_params.get('type')
        if code is None or code.strip().upper() not in SUPPORTED_TYPES:
            return _error("Paramètre « type » invalide — valeurs : FLOUR, YEAST, OIL, SALT.")
        code = code.strip().upper()
        day, msg = parse_day(request.query_params.get('date'))
        if msg:
            return _error(msg)

        all_nodes = user.can_access_all_nodes
        bakeries = Node.objects.filter(is_active=True).exclude(code=SIEGE_CODE).order_by('code')
        node_raw = request.query_params.get('node')
        show_direction = all_nodes
        if node_raw not in (None, ''):
            node, resp = resolve_node_param(node_raw)
            if resp is not None:
                return resp
            if node.code == SIEGE_CODE or not node.is_active or (
                    not all_nodes and node.pk != user.node_id):
                return _error("Boulangerie introuvable.", 404)
            bakeries = bakeries.filter(pk=node.pk)
            show_direction = False
        elif not all_nodes:
            bakeries = bakeries.filter(pk=user.node_id)
        bakeries = list(bakeries)

        siege = Node.objects.filter(code=SIEGE_CODE).first() if show_direction else None
        nodes = bakeries + ([siege] if siege else [])
        computed = compute_rows(day, code, nodes) if nodes else []

        rows = []
        for n, r in zip(nodes, computed):
            rows.append(_serialize(r, node=n.pk, code='D1' if n.code == SIEGE_CODE else n.code,
                                   name=n.name, is_direction=n.code == SIEGE_CODE))
        label, unit = SUPPORTED_TYPES[code]
        ctype = ConsumableType.objects.filter(code=code).first()
        if ctype is not None:
            label, unit = ctype.label, ctype.unit or unit
        return Response({
            'date': day.isoformat(), 'type': code, 'label': label, 'unit': unit,
            'hypotheses': HYPOTHESES,
            'rows': rows,
            'totals': _serialize(_totals(computed), node=None, code='TOTAUX', name='TOTAUX',
                                 is_direction=False),
        })
