from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum, DecimalField, ExpressionWrapper, F
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from core.models import Config, Node, BreadPrice
from core.permissions import IsGerant, IsHeadquarters, IsFacturier
from core.utils import log_activity, create_notification
from core.workday import (
    work_date_for, work_time_info, current_team, team_for_work_date, team_at_day_start,
    business_date, workday_bounds, delivered_on_work_date_filter,
)
from .models import ProductionSession, ProductionSessionLine, BreadStock, ConsumableType, ConsumableStock, ConsumableMovement, ConsumableCount, BreadTransfer, BreadTransferLine, BreadDisposal, DailyBreadStockSnapshot, DailyOpeningConfirmation, DailyOpeningConfirmationLine, DailyTeamAssignment, _adjust_bread_stock
from .serializers import (
    ProductionSessionSerializer, BreadStockSerializer, ConsumableTypeSerializer, ConsumableStockSerializer,
    ConsumableMovementSerializer, ConsumableCountSerializer, BreadTransferSerializer, BreadDisposalSerializer,
)

_SESSION_COMPUTED_FIELDS = [
    'total_breads', 'total_fc_produced', 'theoretical_yield', 'yield_gap',
    'breads_300', 'breads_400', 'breads_500', 'breads_1000', 'sac_value_fc_used',
]


def _body_not_object_response(request):
    """
    BUG-194 : garde commune des vues qui lisent `request.data.get(...)` sans
    passer par un serializer. Un corps JSON qui n'est pas un objet (liste,
    chaîne, nombre) provoquait un `AttributeError` (HTTP 500) ; on répond 400.
    Retourne None si le corps est exploitable (dict ou QueryDict).
    """
    if hasattr(request.data, 'get'):
        return None
    return Response(
        {'detail': "Corps de requête invalide : un objet JSON est attendu."},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _strict_int(value, label, minimum=0):
    """
    BUG-224 : entier strict (int ou chaîne d'entier ; ni booléen, ni décimal
    fractionnaire) ≥ `minimum` et plafonné à la capacité de la colonne ; sinon
    400 en français (`{"detail": ...}`) au lieu d'un 500.
    """
    n = None
    if isinstance(value, bool) or value is None:
        n = None
    elif isinstance(value, int):
        n = value
    elif isinstance(value, float) and value.is_integer():
        n = int(value)
    elif isinstance(value, str):
        s = value.strip()
        if s.lstrip('-').isdigit():
            n = int(s)
    if n is None:
        raise ValidationError({'detail': f"Valeur invalide pour {label} : un nombre entier est attendu."})
    if n < minimum:
        raise ValidationError({'detail': (
            f"Valeur invalide pour {label} : doit être supérieure ou égale à {minimum}."
        )})
    if n > 2_000_000_000:
        raise ValidationError({'detail': f"Valeur trop grande pour {label}."})
    return n


def _safe_parse_date(value):
    """
    BUG-225 : `parse_date` renvoie None pour un format non conforme mais LÈVE
    `ValueError` pour une date de bon format et impossible (« 2026-13-45 »).
    Retourne la date, ou None dans les deux cas (l'appelant répond 400).
    """
    try:
        return parse_date(value)
    except (ValueError, TypeError):
        return None


_INVALID_DATE_DETAIL = "Date invalide — format attendu AAAA-MM-JJ."


def _effective_sac_value(node, config):
    """
    Valeur théorique par sac de farine (FC) à utiliser pour une boulangerie :
    celle de la Succursale (Node.sac_value_fc) si elle est renseignée et non
    nulle, sinon la valeur par défaut de la Configuration globale.
    """
    if node.sac_value_fc:
        return int(node.sac_value_fc)
    return config.sac_value_fc


_CONSUMABLE_QTY_Q = Decimal('0.001')
_CONSUMABLE_QTY_MAX = Decimal('9999999.999')


def _parse_consumables_used(raw, node):
    """
    BUG-219 : valide et normalise le champ `consumables_used` d'une
    déclaration de fournée AVANT toute écriture. Attendu : liste (ou absent)
    d'objets `{consumable_type: <code>, quantity: <nombre>}`. Toute anomalie
    (corps non liste, élément non objet, type de consommable inconnu,
    quantité non numérique / non finie / hors limites) → 400 en français.
    Les quantités nulles ou négatives restent ignorées (comportement
    historique : rien à déduire). Retourne une liste de dicts normalisés
    (`quantity` en `Decimal`, 3 décimales).
    """
    from decimal import InvalidOperation

    if raw in (None, ''):
        return []
    if not isinstance(raw, list):
        raise ValidationError({'detail': "« consumables_used » invalide : une liste est attendue."})
    known = set(ConsumableType.objects.values_list('code', flat=True))
    known |= set(ConsumableStock.objects.filter(node=node).values_list('consumable_type', flat=True))
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError({'detail': "« consumables_used » invalide : chaque élément doit être un objet {consumable_type, quantity}."})
        code = item.get('consumable_type')
        if not isinstance(code, str) or not code.strip():
            raise ValidationError({'detail': "« consumables_used » invalide : consumable_type requis."})
        code = code.strip()
        if code not in known:
            raise ValidationError({'detail': f"« consumables_used » invalide : consommable inconnu « {code} »."})
        raw_qty = item.get('quantity', 0)
        if isinstance(raw_qty, bool) or raw_qty is None or isinstance(raw_qty, (list, dict)):
            raise ValidationError({'detail': f"« consumables_used » invalide : quantité non numérique pour {code}."})
        try:
            qty = Decimal(str(raw_qty).strip() or '0')
        except InvalidOperation:
            raise ValidationError({'detail': f"« consumables_used » invalide : quantité non numérique pour {code}."})
        if not qty.is_finite():
            raise ValidationError({'detail': f"« consumables_used » invalide : quantité non finie pour {code}."})
        if qty > _CONSUMABLE_QTY_MAX:
            raise ValidationError({'detail': f"« consumables_used » invalide : quantité trop grande pour {code}."})
        out.append({
            'consumable_type': code,
            'quantity': qty.quantize(_CONSUMABLE_QTY_Q, rounding=ROUND_HALF_UP) if qty > 0 else qty,
        })
    return out


def _record_consumable_exits(session, user, extra_consumables=None):
    """
    Create ConsumableMovement EXIT records for all consumables used in a session.
    - Flour is auto-derived from session.flour_sacks_used.
    - extra_consumables: list of {consumable_type, quantity} dicts for salt/yeast/oil.
    Each creation triggers ConsumableMovement.save() which decrements ConsumableStock
    (BUG-143, annule BUG-041 : la sortie n'est plus jamais refusée si elle dépasse le
    stock disponible — le stock devient négatif, signalé par une notification).

    Retourne la liste des (consumable_type, quantity) effectivement traités,
    pour que l'appelant puisse en déduire l'alerte de surconsommation (BUG-040).
    """
    from django.db import transaction
    node = session.node
    desc = f"Fournée Éq.{session.team} {session.date}"
    entries = [('FLOUR', session.flour_sacks_used)]
    if extra_consumables:
        # `extra_consumables` est déjà validé/normalisé par
        # `_parse_consumables_used` (BUG-219) : quantités `Decimal` finies.
        for cu in extra_consumables:
            ct  = cu.get('consumable_type', '')
            qty = cu.get('quantity', 0)
            if ct and Decimal(str(qty or 0)) > 0:
                entries.append((ct, qty))
    processed = []
    with transaction.atomic():
        for ct, qty in entries:
            if not qty or Decimal(str(qty)) <= 0:
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


# BUG-155 (remarque.md l.414) : délai de grâce après l'heure de fin de
# créneau d'une équipe (`Node.team_a_end_time`/`team_b_end_time`) avant
# clôture forcée automatique si la fournée n'a toujours pas été clôturée
# manuellement. Choix documenté dans le ticket plutôt que redemandé au
# client : 30 minutes, assez pour laisser un gérant/facturier présent
# répondre à la modale de validation (BUG-156) sans bloquer indéfiniment la
# fournée si personne ne valide.
SHIFT_END_GRACE_MINUTES = 30


def _current_bread_stocks(node):
    """
    BUG-155 : lignes `BreadStock` courantes pour `node`, mêmes catégories et
    même tri que le cas « live » de `BreadStockByDateView` — source unique
    du reste physique suggéré/forcé à la fin de créneau.
    """
    return list(
        BreadStock.objects.select_related('bread_price')
        .filter(node=node)
        .order_by('bread_price__unit_price')
    )


def _remaining_suggestions(stocks):
    """Reste suggéré par catégorie (BUG-158 : valeur réelle, y compris négative)."""
    return [
        {
            'bread_price': bs.bread_price_id,
            'label': str(bs.bread_price),
            'quantity_suggested': bs.qty_available,
        }
        for bs in stocks
    ]


def _force_close_session(session, stocks, node, user):
    """
    BUG-155/158/165 : clôture forcée automatique d'une session au stock
    physique courant. Partagée par la détection A/B (hors rotation) et par la
    détection de relève (BUG-161 B5). Retourne False si une requête
    concurrente a déjà clôturé la session (rien n'est fait : ni notification
    ni log, pas de revendication de la clôture).
    """
    # BUG-158 (instruction client, 2026-11-10) : le reste du jour est
    # enregistré tel quel, y compris négatif (sorties au-delà du disponible).
    # Une notification WARNING signale chaque catégorie négative — `BreadStock`
    # n'est pas corrigé ici.
    remaining_entries = [(bs.bread_price_id, bs.qty_available) for bs in stocks]
    negative_stocks = [bs for bs in stocks if bs.qty_available < 0]
    with transaction.atomic():
        # BUG-165 : relecture verrouillée.
        locked = ProductionSession.objects.select_for_update().get(pk=session.pk)
        if locked.is_closed:
            return False
        session = locked
        _close_production_session(session, remaining_entries, user)
        if negative_stocks:
            details = ", ".join(f"{bs.bread_price} ({bs.qty_available})" for bs in negative_stocks)
            create_notification(
                title=f"Stock de pain négatif à la clôture automatique — {node.code}",
                message=(
                    f"Session Éq.{session.team} du {session.date} clôturée "
                    f"automatiquement : stock physique négatif pour {details}. "
                    f"Le reste du jour a été enregistré avec cette valeur négative ; "
                    f"le stock n'a pas été corrigé, écart à investiguer."
                ),
                severity='WARNING', node_origin=node.code,
            )
    return True


def _reopen_session_for_redesignated_team(session, node, user):
    """
    BUG-278 (décision coordinateur, conforme au client : « l'équipe en place
    peut décider de poursuivre les travaux ») : la session d'un jour calendaire
    est unique par (équipe, date). Si cette équipe a été clôturée à la relève
    (ou automatiquement) puis est DÉSIGNÉE de nouveau pour la période en
    cours, la session close du jour est ROUVERTE pour la nouvelle période
    (pas de second rapport : le rapport reste un par boulangerie et date).

    Réouverture licite uniquement si : rotation activée, session close, date
    = jour calendaire courant, équipe = équipe désignée pour la période en
    cours, et session née AVANT le début de cette période (une session
    clôturée volontairement DANS la période en cours reste refusée, BUG-093).
    Effets : `is_closed=False`, `closed_at`/`closure_summary` vidés,
    `created_at` ramené à maintenant (la session appartient à la nouvelle
    période : elle n'est plus « échue » pour la détection de relève), lignes
    `REMAINING` de l'ancienne clôture supprimées (le reste sera redéclaré à la
    prochaine clôture ; l'instantané `DailyBreadStockSnapshot` est écrasé par
    upsert à cette clôture — jamais additionné). Journalisé. Appelée dans une
    transaction, session verrouillée. Retourne True si rouverte.
    """
    if not (node.team_rotation_enabled and session.is_closed):
        return False
    from core.workday import shift_period_start
    now = timezone.now()
    if (
        session.date != work_date_for(node, now)
        or session.team != current_team(node, now)
        or session.created_at >= shift_period_start(node, now)
    ):
        return False
    removed, _ = BreadDisposal.objects.filter(
        session=session, disposal_type=BreadDisposal.DisposalType.REMAINING,
    ).delete()
    ProductionSession.objects.filter(pk=session.pk).update(
        is_closed=False, closed_at=None, closure_summary=None, created_at=now,
    )
    session.refresh_from_db()
    log_activity(
        user, "Réouverture Production",
        f"{node.code} Éq.{session.team} {session.date} : session rouverte (équipe "
        f"redésignée pour la nouvelle période, {removed} ligne(s) de reste supprimée(s)).",
        node_origin=node.code,
    )
    return True


def _close_leftover_session(session, user):
    """
    BUG-190 : clôture silencieuse d'une session « restante » (même journée de
    travail qu'une session déjà clôturée avec son snapshot) : pas de reste
    déclaré, pas de snapshot. Retourne False si déjà clôturée entre-temps.
    """
    with transaction.atomic():
        locked = ProductionSession.objects.select_for_update().get(pk=session.pk)
        if locked.is_closed:
            return False
        _close_production_session(locked, [], user, record_snapshot=False)
    return True


def _close_production_session(session, remaining_entries, request_user, record_snapshot=True):
    """
    BUG-093/BUG-152/BUG-155 : cœur de la clôture d'une fournée, factorisé
    pour être partagé À L'IDENTIQUE par l'action `close()` (clôture
    volontaire, `remaining` éventuellement fourni par l'utilisateur) et
    `shift_end_status()` (clôture forcée automatique à la fin de créneau,
    `remaining` calculé depuis le stock physique courant). Reprend
    exactement la logique déjà vérifiée sous BUG-093/BUG-152 (transaction
    atomique, recoupement production/ventes/dispositions, reliquat NV,
    anomalie, upsert des lignes `BreadDisposal` REMAINING, snapshot,
    notification, `log_activity`). Ne doit JAMAIS être dupliquée — toute
    évolution de la logique de clôture doit passer par cette fonction
    unique.

    `remaining_entries` : liste de tuples `(bread_price_id, quantity:int)`
    déjà validés par l'appelant (quantité entière — négative admise depuis
    BUG-158 —, catégorie existante).
    Suppose que l'appelant a déjà vérifié `session.is_closed` est False.

    Retourne le résumé du recoupement (`result`, `nv_breads`, `is_anomaly`) ;
    ne construit pas de `Response` — cela reste la responsabilité de
    l'appelant, dont le contrat de réponse diffère (`close()` renvoie le
    serializer de la session, `shift_end_status()` un contrat plus simple).
    """
    sessions_qs, disposals_qs, invoices_qs = _build_reconciliation_querysets(
        user=request_user, node_id=session.node_id, date=str(session.date),
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

    with transaction.atomic():
        session.is_closed = True
        session.closed_at = timezone.now()
        session.closure_summary = summary
        session.save(update_fields=['is_closed', 'closed_at', 'closure_summary'])

        for bp_id, qty_int in remaining_entries:
            existing = BreadDisposal.objects.filter(
                session=session, bread_price_id=bp_id,
                disposal_type=BreadDisposal.DisposalType.REMAINING,
            )
            keep = existing.first()
            existing.exclude(pk=getattr(keep, 'pk', None)).delete()
            if keep:
                keep.quantity = qty_int
                keep.node = session.node
                keep.node_origin = session.node.code
                keep.save(update_fields=['quantity', 'node', 'node_origin', 'total_value', 'updated_at'])
            else:
                BreadDisposal.objects.create(
                    session=session, bread_price_id=bp_id,
                    disposal_type=BreadDisposal.DisposalType.REMAINING,
                    node=session.node, node_origin=session.node.code,
                    quantity=qty_int,
                )

        # BUG-190 : `record_snapshot=False` pour une session « restante » d'une
        # journée dont le reste a déjà été enregistré par une autre session
        # (désignation corrigée en rotation) : aucun second reste, donc rien
        # de perdu ni de compté deux fois.
        if record_snapshot:
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
        request_user, "Clôture Production",
        f"{session.node.code} Éq.{session.team} {session.date} clôturée : "
        f"produit {result['production_declared']['breads']}, vendu "
        f"{result['sales']['breads']}, disposé {result['returns']['breads']}, "
        f"NV {nv_breads}" + (" (anomalie)" if is_anomaly else "") + ".",
        node_origin=session.node_origin,
    )

    return {'result': result, 'nv_breads': nv_breads, 'is_anomaly': is_anomaly}


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
        if self.action == 'shift_end_status':
            # BUG-155 : lecture (et clôture forcée automatique, en
            # évaluation paresseuse) déclenchée par le polling frontend
            # (BUG-156) depuis N'IMPORTE QUEL rôle connecté à la boulangerie
            # — pas seulement un gérant, contrairement à `close()` (clôture
            # VOLONTAIRE, réservée à `IsGerant`) : un facturier resté seul
            # après l'heure de fin de créneau doit, lui aussi, voir la
            # modale forcée s'ouvrir, ou déclencher la clôture forcée.
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

    def create(self, request, *args, **kwargs):
        """
        BUG-161 (B3) : en mode rotation (`Node.team_rotation_enabled`), `date`
        et `team` absents du payload sont complétés côté serveur par la
        journée de travail courante et l'équipe de service désignée
        (`core.workday`). Un payload explicite est conservé tel quel ; hors
        rotation (ou sans équipe désignée) le comportement est inchangé
        (champs obligatoires).
        """
        data = self._with_workday_defaults(request)
        if isinstance(data, Response):
            return data  # BUG-192 : refus (400 équipe non désignée / 403 sans désignation)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def _with_workday_defaults(self, request):
        data = request.data
        if not hasattr(data, 'get') or not hasattr(data, 'copy'):
            return data
        user = request.user
        if not user.can_access_all_nodes:
            node = user.node
        else:
            node_ref = data.get('node')
            node = None
            if node_ref not in (None, ''):
                try:
                    node = Node.objects.filter(pk=node_ref).first()
                except (TypeError, ValueError, DjangoValidationError):
                    node = None
            node = node or user.node
        if node is None or not node.team_rotation_enabled:
            return data
        current_wd = work_date_for(node)

        # BUG-192 : en rotation, une fournée de la journée de travail COURANTE
        # ne peut être déclarée que pour l'équipe désignée (même règle que
        # `opening-confirmation`, B4). Une date explicite passée/future (saisie
        # rétroactive) reste inchangée.
        raw_date = data.get('date')
        if raw_date in (None, ''):
            target_date = current_wd
        else:
            try:
                target_date = parse_date(str(raw_date))
            except ValueError:
                target_date = None
        if target_date == current_wd:
            designated = current_team(node)
            if designated is None:
                return Response(
                    {'detail': "Désignez l'équipe de service du jour avant de déclarer une fournée.",
                     'code': 'TEAM_NOT_ASSIGNED'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            requested_team = data.get('team')
            if requested_team not in (None, '') and requested_team != designated:
                return Response(
                    {'detail': (
                        f"En rotation d'équipes, la fournée est déclarée pour l'équipe de "
                        f"service du jour (équipe {designated})."
                    )},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        patched = data.copy()
        if not data.get('date'):
            patched['date'] = current_wd.isoformat()
        if not data.get('team'):
            service_team = current_team(node)
            if service_team:
                patched['team'] = service_team
        return patched

    def perform_create(self, serializer):
        # BUG-219 : toute la déclaration (session, lignes, stock de pains,
        # sorties de consommables, notifications) est atomique — une erreur
        # n'en laisse AUCUNE trace (un rejeu ne double plus la production).
        with transaction.atomic():
            self._perform_create_locked(serializer)

    def _perform_create_locked(self, serializer):
        """
        BUG-142 (remarque.md) : une déclaration supplémentaire de fournée le
        même jour pour la même équipe (node, team, date) ne doit plus être
        rejetée (ancien comportement : `IntegrityError` sur
        `unique_together` → 400) — elle s'AJOUTE désormais à la session du
        jour existante : les lignes `DECLARED` sont incrémentées catégorie
        par catégorie (ou créées si la catégorie n'avait encore aucune
        quantité ce jour) et `flour_sacks_used` s'additionne. `sac_value_fc_
        used` (BUG-038) n'est JAMAIS réécrit sur un ajout — il reste figé à
        la toute première déclaration du jour pour ce (node, team), qu'elle
        soit une vraie déclaration ou une session déjà créée par la
        confirmation du stock de départ (BUG-133/136, voir
        `_sync_carryover_session_lines`). Une session déjà clôturée
        (`is_closed=True`, BUG-093) refuse tout ajout, sans contourner la
        clôture — même message qu'avant pour une session clôturée.
        """
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

        # BUG-219 : `consumables_used` est validé AVANT toute écriture.
        extra_consumables = _parse_consumables_used(self.request.data.get('consumables_used'), node)

        team = serializer.validated_data.get('team')
        date = serializer.validated_data.get('date')
        lines_data = serializer.validated_data.get('lines') or []
        flour_add = serializer.validated_data.get('flour_sacks_used')

        new_declared_lines = []
        with transaction.atomic():
            existing = ProductionSession.objects.select_for_update().filter(
                node=node, team=team, date=date,
            ).first()

            if existing is not None:
                if existing.is_closed and _reopen_session_for_redesignated_team(existing, node, user):
                    existing = ProductionSession.objects.select_for_update().get(pk=existing.pk)
                if existing.is_closed:
                    raise ValidationError({
                        'detail': (
                            f"Session de production clôturée pour l'Équipe {team} le {date} "
                            f"à la boulangerie {node.code} — déclaration impossible."
                        )
                    })
                session = existing
                if flour_add:
                    session.flour_sacks_used = session.flour_sacks_used + flour_add
                    session.save(update_fields=['flour_sacks_used'])
                for line_data in lines_data:
                    qty = line_data.get('quantity', 0)
                    if qty <= 0:
                        continue
                    bread_price = line_data['bread_price']
                    existing_line = session.lines.filter(
                        bread_price=bread_price, source=ProductionSessionLine.Source.DECLARED,
                    ).first()
                    if existing_line:
                        ProductionSessionLine.objects.filter(pk=existing_line.pk).update(
                            quantity=F('quantity') + qty,
                        )
                    else:
                        ProductionSessionLine.objects.create(
                            session=session, bread_price=bread_price, quantity=qty,
                            source=ProductionSessionLine.Source.DECLARED,
                        )
                    new_declared_lines.append((bread_price, qty))
                # BUG-038 : ne JAMAIS relire _effective_sac_value() sur un
                # ajout — on réutilise la valeur déjà figée sur la session.
                session.compute_totals(session.sac_value_fc_used)
            else:
                try:
                    session = ProductionSession.objects.create(
                        node=node, team=team, date=date,
                        declared_by=user, node_origin=node.code,
                        flour_sacks_used=flour_add if flour_add else '0.00',
                        notes=serializer.validated_data.get('notes', ''),
                    )
                except IntegrityError:
                    raise ValidationError(
                        f"Une session existe déjà pour l'Équipe {team} le {date} à la boulangerie {node.code}."
                    )
                for line_data in lines_data:
                    qty = line_data.get('quantity', 0)
                    if qty > 0:
                        ProductionSessionLine.objects.create(
                            session=session, bread_price=line_data['bread_price'], quantity=qty,
                            source=ProductionSessionLine.Source.DECLARED,
                        )
                        new_declared_lines.append((line_data['bread_price'], qty))
                session.compute_totals(_effective_sac_value(node, config))

            session.save(update_fields=_SESSION_COMPUTED_FIELDS)

        serializer.instance = session

        for bread_price, qty in new_declared_lines:
            _adjust_bread_stock(session.node, bread_price, produced=qty)

        # BUG-143 (annule BUG-041, demande client directe 2026-11-10) :
        # `ConsumableMovement.save()` n'empêche plus jamais une sortie pour
        # cause de stock insuffisant — elle n'est désormais plus censée lever
        # de `ValidationError` pour cette raison (le stock peut devenir
        # négatif). Le `try/except` est conservé par prudence pour toute
        # AUTRE erreur de validation du modèle (non liée au stock), mais ne
        # traduit plus jamais un refus pour stock insuffisant en 400.
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            processed_entries = _record_consumable_exits(
                session, user,
                extra_consumables=extra_consumables,
            )
        except DjangoValidationError as exc:
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
        # Snapshot old DECLARED lines BEFORE serializer.save() wipes them
        # (BUG-142 : seules les lignes DECLARED sont réaffectées par
        # `ProductionSessionSerializer.update()` — les lignes CARRYOVER,
        # BUG-133/136, ne sont ni touchées ici ni réajustées sur
        # `BreadStock`, déjà géré une fois par la confirmation elle-même).
        old_lines = {
            line.bread_price_id: (line.bread_price, line.quantity)
            for line in serializer.instance.lines.filter(
                source=ProductionSessionLine.Source.DECLARED,
            ).select_related('bread_price').all()
        }
        user = self.request.user
        old_flour = Decimal(str(serializer.instance.flour_sacks_used or 0))
        if not user.can_access_all_nodes:
            # BUG-056 : un non-HQ ne peut jamais réaffecter une session
            # existante à une autre boulangerie via `node` dans le payload —
            # on impose le nœud déjà présent sur l'instance (qui est déjà
            # filtrée par get_queryset() sur user.node pour ce profil).
            session = serializer.save(node=serializer.instance.node, node_origin=serializer.instance.node.code)
        else:
            session = serializer.save()
        # BUG-220 : modifier `flour_sacks_used` régularise le stock de farine
        # par un mouvement de sortie du DELTA (positif : farine consommée en
        # plus ; négatif : sortie négative = farine restituée, acceptée comme
        # tout mouvement négatif — décision client BUG-216). Aucun mouvement
        # « entrée » fictif : l'approvisionnement (finance) reste intact.
        # `consumables_used` n'est pas pris en compte en PATCH (comportement
        # inchangé : seul le déclaratif initial alimente sel/levure/huile).
        new_flour = Decimal(str(session.flour_sacks_used or 0))
        delta_flour = new_flour - old_flour
        if delta_flour != 0:
            flour_stock = ConsumableStock.objects.filter(node=session.node, consumable_type='FLOUR').first()
            if flour_stock is not None:
                ConsumableMovement.objects.create(
                    # `session` volontairement non renseigné : ces mouvements
                    # ne doivent pas fausser la moyenne historique de
                    # surconsommation (`_check_overconsumption`).
                    node=session.node, stock=flour_stock,
                    movement_type=ConsumableMovement.MovementType.EXIT,
                    quantity=delta_flour,
                    description=f"Régularisation fournée Éq.{session.team} {session.date} ({old_flour} → {new_flour} sacs)",
                    recorded_by=user, node_origin=session.node.code,
                )
                log_activity(
                    user, "Régularisation Farine Fournée",
                    f"{session.node.code} Éq.{session.team} {session.date} : sacs {old_flour} → {new_flour} "
                    f"(mouvement de farine {delta_flour:+}).",
                    node_origin=session.node.code,
                )
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
        for line in session.lines.filter(
            source=ProductionSessionLine.Source.DECLARED,
        ).select_related('bread_price').all():
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

        # BUG-225 : une date impossible (« 2026-13-45 ») ou non conforme → 400.
        for raw in (date, date_from, date_to):
            if raw and _safe_parse_date(raw) is None:
                return Response({'detail': _INVALID_DATE_DETAIL}, status=status.HTTP_400_BAD_REQUEST)

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

        BUG-152 (remarque.md, après l.408 — « les restes des pains en stock
        [...] doivent aller dans la clôture journalière reste du jour selon
        la catégorie ») : le corps de la requête peut fournir, en option,
        `remaining` : `[{"bread_price": <id>, "quantity": <entier, négatif admis — BUG-158>}, ...]`
        pour déclarer le « RESTE DU JOUR » par catégorie EN MÊME TEMPS que la
        clôture, en un seul geste, au lieu d'exiger un passage préalable par
        le formulaire séparé `BreadDisposalViewSet` (type `REMAINING`).
        - Si `remaining` est absent du corps : comportement strictement
          inchangé — `record_snapshot()` lit les `BreadDisposal REMAINING`
          déjà déclarés séparément, comme avant ce ticket.
        - Si `remaining` est fourni : une entrée invalide (quantité non
          entière, catégorie absente ou introuvable) → 400, RIEN n'est
          appliqué (session non clôturée, aucune disposition créée). Une
          quantité négative est acceptée depuis BUG-158 (instruction client).
          Sinon, pour chaque catégorie fournie, la ligne `REMAINING` de
          CETTE session pour cette catégorie est créée ou REMPLACÉE
          (idempotent — un nouvel appel avec les mêmes valeurs ne duplique
          rien ; une catégorie déjà déclarée séparément au préalable est
          écrasée par la valeur fournie ici, décision la plus prévisible
          pour l'utilisateur qui vient de les saisir à l'écran de clôture).
          Ces lignes `REMAINING` sont créées dans la MÊME transaction que le
          reste de la clôture, AVANT l'appel à `record_snapshot()`. Elles ne
          perturbent jamais le calcul d'écart ci-dessus : `disposals_qs`
          (`_build_reconciliation_querysets`) exclut explicitement le type
          `REMAINING`, et le calcul d'écart a déjà été fait plus haut, sur la
          base des dispositions existant AVANT cet appel.
        """
        session = self.get_object()
        if session.is_closed:
            return Response(
                {'detail': "Session de production déjà clôturée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bad_body = _body_not_object_response(request)
        if bad_body is not None:
            return bad_body
        remaining_payload = request.data.get('remaining')
        remaining_entries = []
        if remaining_payload is not None:
            if not isinstance(remaining_payload, list):
                return Response(
                    {'detail': "« remaining » doit être une liste."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            for entry in remaining_payload:
                bp_id = entry.get('bread_price') if isinstance(entry, dict) else None
                qty   = entry.get('quantity') if isinstance(entry, dict) else None
                try:
                    qty_int = int(qty)
                except (TypeError, ValueError):
                    return Response(
                        {'detail': "« remaining » : quantité invalide."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not bp_id:
                    return Response(
                        {'detail': "« remaining » : catégorie de pain (bread_price) requise."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # BUG-158 (instruction client, 2026-11-10) : une quantité
                # négative est acceptée — le reste du jour reprend le stock
                # physique, qui peut être négatif (l'ancien refus HTTP 400 de
                # BUG-152 est levé).
                remaining_entries.append((bp_id, qty_int))

            bp_ids = {bp_id for bp_id, _ in remaining_entries}
            found_bp = set(BreadPrice.objects.filter(pk__in=bp_ids).values_list('pk', flat=True))
            missing = bp_ids - found_bp
            if missing:
                return Response(
                    {'detail': f"« remaining » : catégorie de pain introuvable ({', '.join(str(m) for m in missing)})."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # BUG-155 : le cœur de la clôture (recoupement, transaction, upsert
        # REMAINING, snapshot, notification d'anomalie, log_activity) est
        # désormais factorisé dans `_close_production_session`, partagée à
        # l'identique avec la clôture forcée automatique de
        # `shift_end_status()` — comportement RIGOUREUSEMENT inchangé pour
        # cet appel volontaire (remaining fourni ou non par l'utilisateur).
        _close_production_session(session, remaining_entries, request.user)

        return Response(ProductionSessionSerializer(session).data)

    @action(detail=False, methods=['get'], url_path='shift-end-status')
    def shift_end_status(self, request):
        """
        BUG-155 (remarque.md l.414) : détection — et, le cas échéant,
        clôture forcée automatique — du dépassement de l'heure de fin de
        créneau d'une équipe (`Node.team_a_end_time`/`team_b_end_time`)
        sans clôture manuelle de sa `ProductionSession` du jour.

        `GET /api/production/sessions/shift-end-status/?node=<code ou pk>`

        Pas d'infra de tâches planifiées dans ce projet (ni Celery, ni
        APScheduler, ni cron, confirmé) : la détection se fait par
        évaluation PARESSEUSE, déclenchée par cet appel lui-même (le
        frontend, BUG-156, l'appelle au même rythme que le polling des
        notifications déjà en place) — pas par un job serveur autonome.

        Permissions/isolation par nœud : identique à
        `BreadStockByDateView`/`DailyClosureReportView` — un non-HQ ignore
        tout `node` reçu et n'est jamais évalué que sur le sien ; un HQ doit
        préciser `node` explicitement.

        Pour chaque équipe (A puis B, dans cet ordre — une seule équipe à la
        fois est signalée par appel, les créneaux A/B ne se chevauchent
        jamais, CLAUDE.md §5.2) dont l'heure de fin de créneau est déjà
        passée aujourd'hui :
        - Session déjà close, ou absente pour cette équipe/jour (rien à
          clôturer) → équipe ignorée, passe à la suivante.
        - Dépassement < `SHIFT_END_GRACE_MINUTES` (30 min) → PAS de clôture ;
          `{"team": "A"|"B", "session": <id>, "pending_validation": true,
          "remaining": [{"bread_price": id, "label": ..., "quantity_suggested":
          <BreadStock.qty_available actuel, y compris négatif — BUG-158>}, ...],
          "auto_closed": false}`
          pour que le frontend ouvre la modale de validation forcée
          (BUG-156), pré-remplie depuis le stock physique.
        - Dépassement >= `SHIFT_END_GRACE_MINUTES` → clôture forcée
          automatique via `_close_production_session` (même logique EXACTE
          que `close()`, remaining = quantités physiques actuelles, y compris
          négatives, avec notification WARNING dans ce cas — BUG-158) ;
          `{"pending_validation": false, "auto_closed": true, "team": "A"|"B"}`.

        Si aucune équipe n'est dans ce cas (aucun créneau dépassé, ou toutes
        les sessions concernées déjà closes/absentes) : `{"pending_validation": false}`.
        """
        from datetime import datetime, timedelta

        user = request.user
        node_param = request.query_params.get('node')
        if not user.can_access_all_nodes:
            if not user.node_id:
                return Response({'pending_validation': False})
            node = user.node
        else:
            if not node_param:
                return Response(
                    {'detail': "Le paramètre `node` (code ou identifiant) est requis."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            node = _resolve_node(node_param)
            if node is None:
                return Response(
                    {'detail': f"Boulangerie « {node_param} » introuvable."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        now = timezone.localtime()
        today = now.date()
        current_time = now.time()
        # BUG-161 (B3) : date de travail et heure serveur pour le frontend
        # (additif ; la détection de fin de créneau reste celle de B5).
        # Uniquement en mode rotation : hors rotation, la réponse reste
        # strictement identique à l'existante (contrat figé par les tests
        # BUG-155/158 qui comparent le corps exact).
        time_info = work_time_info(node) if node.team_rotation_enabled else {}

        if node.team_rotation_enabled:
            return self._handover_shift_end_response(node, user, now, time_info)

        # BUG-226 : on examine aussi les sessions NON CLÔTURÉES des jours
        # antérieurs (la fin de créneau de leur jour est forcément dépassée),
        # de la plus ancienne à la plus récente (équipe A avant B), avec le
        # même délai de grâce et la même clôture forcée que pour aujourd'hui.
        # Pour le jour courant, l'ordre (A puis B) et les conditions sont
        # inchangés (BUG-155/158/165).
        end_times = {'A': node.team_a_end_time, 'B': node.team_b_end_time}
        open_sessions = list(
            ProductionSession.objects
            .filter(node=node, is_closed=False, date__lte=today, team__in=[t for t, e in end_times.items() if e is not None])
            .order_by('date', 'team')
        )
        for session in open_sessions:
            team = session.team
            end_time = end_times[team]
            if session.date == today and current_time < end_time:
                continue

            end_dt = timezone.make_aware(
                datetime.combine(session.date, end_time), timezone.get_current_timezone(),
            )
            elapsed = now - end_dt

            stocks = _current_bread_stocks(node)

            if elapsed >= timedelta(minutes=SHIFT_END_GRACE_MINUTES):
                if not _force_close_session(session, stocks, node, user):
                    continue
                return Response({'pending_validation': False, 'auto_closed': True, 'team': team, **time_info})

            return Response({
                'team': team,
                'session': session.pk,
                'pending_validation': True,
                'remaining': _remaining_suggestions(stocks),
                'auto_closed': False,
                **time_info,
            })

        return Response({'pending_validation': False, **time_info})

    @staticmethod
    def _handover_shift_end_response(node, user, now, time_info):
        """
        BUG-161 / BUG-247 (décision client 2026-11-12) : en rotation, la fin
        de service d'une équipe est l'heure de RELÈVE (`Node.handover_time`),
        mais la date de travail reste le JOUR CALENDAIRE (minuit à minuit).
        Deux cas, une session traitée par appel (la plus ancienne d'abord) :

        1. Session ouverte d'une PÉRIODE DE SERVICE ÉCHUE (créée avant le début
           de la période en cours, ou datée avant sa date de période) : clôture
           à la relève — validation par l'équipe sortante pendant le délai de
           grâce (`SHIFT_END_GRACE_MINUTES`), puis clôture forcée (mêmes
           règles et même fonction que hors rotation, BUG-155/158/165). Le
           reste de l'équipe sortante devient le départ de l'équipe entrante.
        2. Session ouverte de la période EN COURS mais datée d'un jour
           calendaire passé (l'équipe a travaillé à cheval sur minuit) :
           clôture silencieuse au passage de minuit (stock physique courant),
           pour que chaque jour calendaire ait son propre reste du jour ; la
           prochaine fournée créera la session du nouveau jour.

        `work_date` = date de la session concernée (la date calendaire
        courante si rien à faire) ; `current_work_date` = date calendaire du
        serveur.
        """
        from datetime import timedelta
        from core.workday import shift_period_start

        local_now = timezone.localtime(now)
        today = local_now.date()
        period_start = shift_period_start(node, now)
        current_period = business_date(node, now)
        base = {'server_now': time_info['server_now'], 'current_work_date': today.isoformat()}

        open_sessions = list(
            ProductionSession.objects
            .filter(node=node, is_closed=False, date__lte=today)
            .order_by('date', 'team')
        )
        # Pour une même date, l'équipe désignée pour la période de la session
        # d'abord ; les autres sont des sessions « restantes » (BUG-190).
        designated_by_pk = {s.pk: current_team(node, s.created_at) for s in open_sessions}
        open_sessions.sort(key=lambda s: (s.date, 0 if s.team == designated_by_pk[s.pk] else 1, s.team))
        for session in open_sessions:
            stale = session.created_at < period_start or session.date < current_period
            info = {**base, 'work_date': session.date.isoformat()}
            stocks = _current_bread_stocks(node)

            if stale:
                designated = designated_by_pk[session.pk]
                if (
                    designated and session.team != designated
                    and ProductionSession.objects.filter(
                        node=node, date=session.date, team=designated,
                    ).exists()
                ):
                    # BUG-190 : désignation corrigée après une fournée — la
                    # session de l'autre équipe est « restante » : clôture
                    # silencieuse, sans second reste (jamais compté deux fois).
                    if _close_leftover_session(session, user):
                        return Response({'pending_validation': False, 'auto_closed': True, 'team': session.team, **info})
                    continue
                # Relève qui a mis fin à la période de cette session (au plus
                # tard : début de la période en cours).
                handover_dt = min(period_start, workday_bounds(node, session.date)[1])
                if now - handover_dt >= timedelta(minutes=SHIFT_END_GRACE_MINUTES):
                    if not _force_close_session(session, stocks, node, user):
                        continue
                    return Response({'pending_validation': False, 'auto_closed': True, 'team': session.team, **info})
                return Response({
                    'team': session.team,
                    'session': session.pk,
                    'pending_validation': True,
                    'remaining': _remaining_suggestions(stocks),
                    'auto_closed': False,
                    **info,
                })

            if session.date < today:
                # Passage de minuit sans relève : clôture silencieuse du jour écoulé
                # (reste du jour calendaire) ET ouverture de la session du jour
                # courant pour la même équipe, afin que la relève de midi ait une
                # session à valider (restes de l'équipe sortante = départ de
                # l'entrante) et que les ventes de la matinée y soient rattachées.
                if not _force_close_session(session, stocks, node, user):
                    continue
                ProductionSession.objects.get_or_create(
                    node=node, team=session.team, date=today,
                    defaults={
                        'declared_by': user, 'node_origin': node.code,
                        'sac_value_fc_used': session.sac_value_fc_used,
                    },
                )
                return Response({'pending_validation': False, 'auto_closed': True, 'team': session.team, **info})

        return Response({'pending_validation': False, 'work_date': today.isoformat(), **base})


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

    def get_permissions(self):
        # BUG-251 : lecture pour tout authentifié (périmètre du nœud) ;
        # écriture réservée au gérant et supérieurs. Les quantités ne
        # bougent que par `ConsumableMovement` (champ `quantity` en lecture seule).
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsGerant()]

    def perform_create(self, serializer):
        user = self.request.user
        if not user.can_access_all_nodes:
            serializer.save(node=user.node, node_origin=user.node.code)
        else:
            node = serializer.validated_data.get('node') or user.node
            serializer.save(node=node, node_origin=node.code if node else 'CLOUD')

    def perform_update(self, serializer):
        user = self.request.user
        if not user.can_access_all_nodes:
            serializer.validated_data.pop('node', None)
        serializer.save()

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
            # BUG-143 (annule BUG-041) : ConsumableMovement.save() ne refuse
            # plus une sortie qui dépasserait le stock disponible (le stock
            # devient négatif, signalé par notification). Ce `try/except`
            # est conservé pour toute AUTRE `ValidationError` du modèle,
            # traduite en 400 propre plutôt que de laisser remonter une
            # erreur serveur.
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

        # BUG-224 : toutes les entrées sont validées AVANT la moindre écriture.
        if not user.node_id:
            raise ValidationError({'detail': (
                "Votre compte n'est rattaché à aucune boulangerie : une demande de pains "
                "doit être faite depuis une boulangerie."
            )})
        if serializer.validated_data.get('from_node') == user.node:
            raise ValidationError({'detail': "Une boulangerie ne peut pas demander des pains à elle-même."})
        raw_data = self.request.data
        raw_lines = raw_data.get('lines') if hasattr(raw_data, 'get') else None
        if not isinstance(raw_lines, list) or not raw_lines:
            raise ValidationError({'detail': "Au moins une ligne (catégorie de pain et quantité) est requise."})
        wanted = {}
        for ld in raw_lines:
            if not isinstance(ld, dict):
                raise ValidationError({'detail': "Chaque ligne doit être un objet {bread_price, quantity_sent}."})
            bp_id = ld.get('bread_price')
            try:
                bp = BP.objects.get(pk=bp_id)
            except (BP.DoesNotExist, TypeError, ValueError, DjangoValidationError):
                raise ValidationError({'detail': f"Catégorie de pain introuvable ({bp_id})."})
            qty = _strict_int(ld.get('quantity_sent'), f"quantité envoyée ({bp.label})", minimum=1)
            wanted[bp.pk] = (bp, wanted.get(bp.pk, (bp, 0))[1] + qty)

        with transaction.atomic():
            transfer = serializer.save(
                initiated_by=user,
                to_node=user.node,  # requester is always the caller's own node
                node_origin=user.node.code,
            )
            for bp, qty in wanted.values():
                BreadTransferLine.objects.create(transfer=transfer, bread_price=bp, quantity_sent=qty)
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

        bad_body = _body_not_object_response(request)
        if bad_body is not None:
            return bad_body
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

        # BUG-224 : validation de toutes les quantités avant la moindre écriture.
        if not isinstance(lines_data, list):
            return Response({'detail': "`lines` doit être une liste."}, status=status.HTTP_400_BAD_REQUEST)
        parsed = []
        for ld in lines_data:
            if not isinstance(ld, dict):
                return Response({'detail': "Chaque ligne doit être un objet {bread_price, quantity_sent}."},
                                status=status.HTTP_400_BAD_REQUEST)
            parsed.append((ld.get('bread_price'), _strict_int(ld.get('quantity_sent', 0), "quantité envoyée")))

        with transaction.atomic():
            # Relecture verrouillée : deux réponses simultanées ne doivent pas
            # déduire deux fois le stock de l'émetteur.
            locked = BreadTransfer.objects.select_for_update().get(pk=transfer.pk)
            if locked.transfer_status != BreadTransfer.TransferStatus.PENDING:
                return Response(
                    {'detail': f"Transfert déjà au statut « {locked.get_transfer_status_display()} »."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            for bp_id, qty_send in parsed:
                try:
                    line = transfer.lines.get(bread_price_id=bp_id)
                except (BreadTransferLine.DoesNotExist, ValueError, TypeError):
                    continue
                line.quantity_sent = qty_send  # B confirms/adjusts the quantity they'll send
                line.save(update_fields=['quantity_sent'])

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
        # BUG-223 : un transfert en litige (DISPUTED) peut être RE-VALIDÉ par
        # le récepteur (recomptage) ; le stock est alors régularisé du DELTA
        # entre l'ancienne et la nouvelle quantité reçue (jamais recrédité en
        # entier). Si le recomptage égale l'envoyé, le litige est levé.
        confirmable = (BreadTransfer.TransferStatus.RESPONDED, BreadTransfer.TransferStatus.DISPUTED)
        if transfer.transfer_status not in confirmable:
            return Response(
                {'detail': f"Le transfert doit être au statut 'Réceptionné' pour être confirmé (statut : {transfer.get_transfer_status_display()})."},
                status=status.HTTP_400_BAD_REQUEST
            )

        bad_body = _body_not_object_response(request)
        if bad_body is not None:
            return bad_body
        lines_data = request.data.get('lines', [])
        if not lines_data:
            return Response({'detail': '`lines` est requis.'}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-224 : validation de toutes les quantités avant la moindre écriture.
        if not isinstance(lines_data, list):
            return Response({'detail': "`lines` doit être une liste."}, status=status.HTTP_400_BAD_REQUEST)
        parsed = []
        for ld in lines_data:
            if not isinstance(ld, dict):
                return Response({'detail': "Chaque ligne doit être un objet {bread_price, quantity_received}."},
                                status=status.HTTP_400_BAD_REQUEST)
            parsed.append((ld.get('bread_price'), _strict_int(ld.get('quantity_received', 0), "quantité reçue")))

        has_dispute = False
        with transaction.atomic():
            # Relecture verrouillée : une double validation simultanée ne doit
            # pas créditer deux fois le stock du récepteur.
            locked = BreadTransfer.objects.select_for_update().get(pk=transfer.pk)
            if locked.transfer_status not in confirmable:
                return Response(
                    {'detail': f"Le transfert doit être au statut 'Réceptionné' pour être confirmé (statut : {locked.get_transfer_status_display()})."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            for bp_id, qty_received in parsed:
                try:
                    line = transfer.lines.get(bread_price_id=bp_id)
                except (BreadTransferLine.DoesNotExist, ValueError, TypeError):
                    continue
                previous = line.quantity_received or 0
                line.quantity_received = qty_received
                line.save(update_fields=['quantity_received'])
                if qty_received != previous:
                    _adjust_bread_stock(transfer.to_node, line.bread_price, received=qty_received - previous)
            has_dispute = any(
                l.quantity_received is not None and l.quantity_received != l.quantity_sent
                for l in transfer.lines.all()
            )
            # Statut posé dans la même transaction que le crédit du stock.
            transfer.transfer_status = (
                BreadTransfer.TransferStatus.DISPUTED if has_dispute else BreadTransfer.TransferStatus.CONFIRMED
            )
            transfer.confirmed_by = request.user
            transfer.save(update_fields=['transfer_status', 'confirmed_by', 'updated_at'])

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

    RESOLUTIONS = ('ALIGN_ON_RECEIVED', 'ALIGN_ON_SENT')

    @action(detail=True, methods=['post'])
    def resolve_dispute(self, request, pk=None):
        """
        BUG-223 (CLAUDE.md §5.4 : écart → alerte et blocage de la clôture, puis
        déblocage à la résolution) : résolution d'un transfert en litige
        (`DISPUTED`) par la DIRECTION/le siège ou le gérant de la boulangerie
        ÉMETTRICE — jamais par le récepteur qui a déclaré l'écart.

        `POST /api/production/transfers/<id>/resolve_dispute/`
        `{"resolution": "ALIGN_ON_RECEIVED" | "ALIGN_ON_SENT", "reason": "<motif>"}`

        - `ALIGN_ON_RECEIVED` : la quantité reçue fait foi — l'envoi est
          corrigé sur le reçu (l'émetteur récupère, ou se voit débiter, la
          différence en stock).
        - `ALIGN_ON_SENT` : la quantité envoyée fait foi — la réception est
          corrigée sur l'envoi (le récepteur est crédité, ou débité, de la
          différence).
        Dans les deux cas la somme des stocks du groupe redevient nulle, les
        lignes ne présentent plus d'écart (ce qui lève le blocage de clôture
        du récepteur, `treasury._unresolved_incoming_transfer_gap`), le
        transfert passe à `CONFIRMED`, l'opération est journalisée avec le
        détail avant/après et le motif, et une notification INFO informe les
        deux boulangeries. Le motif est obligatoire.
        """
        transfer = self.get_object()
        # Seuls le siège/la direction et le gérant de la boulangerie émettrice.
        self._check_node_involved(request, transfer.from_node_id)

        bad_body = _body_not_object_response(request)
        if bad_body is not None:
            return bad_body
        resolution = request.data.get('resolution')
        reason = request.data.get('reason')
        if resolution not in self.RESOLUTIONS:
            return Response(
                {'detail': "« resolution » doit être « ALIGN_ON_RECEIVED » (le reçu fait foi) "
                           "ou « ALIGN_ON_SENT » (l'envoyé fait foi)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(reason, str) or not reason.strip():
            return Response({'detail': "Le motif de la résolution (« reason ») est obligatoire."},
                            status=status.HTTP_400_BAD_REQUEST)
        reason = reason.strip()[:500]

        with transaction.atomic():
            locked = BreadTransfer.objects.select_for_update().get(pk=transfer.pk)
            if locked.transfer_status != BreadTransfer.TransferStatus.DISPUTED:
                return Response(
                    {'detail': f"Seul un transfert en litige peut être résolu (statut : {locked.get_transfer_status_display()})."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            before = []
            for line in transfer.lines.select_related('bread_price').select_for_update():
                if line.quantity_received is None or line.quantity_received == line.quantity_sent:
                    continue
                sent, received = line.quantity_sent, line.quantity_received
                before.append(f"{line.bread_price.label}: envoyé {sent}, reçu {received}")
                if resolution == 'ALIGN_ON_RECEIVED':
                    # L'émetteur avait en réalité envoyé `received` : on lui restitue (ou débite) la différence.
                    _adjust_bread_stock(transfer.from_node, line.bread_price, sent=received - sent)
                    line.quantity_sent = received
                    line.save(update_fields=['quantity_sent'])
                else:
                    # Le récepteur a reçu `sent` : on le crédite (ou débite) de la différence.
                    _adjust_bread_stock(transfer.to_node, line.bread_price, received=sent - received)
                    line.quantity_received = sent
                    line.save(update_fields=['quantity_received'])
            label = 'reçu fait foi' if resolution == 'ALIGN_ON_RECEIVED' else 'envoyé fait foi'
            stamp = timezone.localtime().strftime('%d/%m/%Y %H:%M')
            transfer.notes = (
                (transfer.notes + '\n' if transfer.notes else '')
                + f"[Litige résolu le {stamp} par {request.user} — {label}] {reason} "
                + f"(écart initial : {'; '.join(before) or 'aucun'})"
            )
            transfer.transfer_status = BreadTransfer.TransferStatus.CONFIRMED
            transfer.save(update_fields=['transfer_status', 'notes', 'updated_at'])

        details = '; '.join(before) or 'aucun écart restant'
        for code in {transfer.from_node.code, transfer.to_node.code}:
            create_notification(
                title=f"Litige Transfert résolu — {transfer.from_node.code}→{transfer.to_node.code}",
                message=f"Résolu ({label}) : {reason}. Écart initial : {details}.",
                severity='INFO', node_origin=code,
            )
        log_activity(
            request.user, "Résolution Litige Transfert",
            f"Transfert {transfer.from_node.code}→{transfer.to_node.code} : {label}. "
            f"Écart initial : {details}. Motif : {reason}",
            node_origin=transfer.from_node.code,
        )
        return Response(BreadTransferSerializer(transfer).data)

    def perform_update(self, serializer):
        # BUG-223 : un transfert qui a déjà eu un effet sur les stocks
        # (réponse, réception, litige) n'est plus modifiable directement.
        if serializer.instance.transfer_status != BreadTransfer.TransferStatus.PENDING:
            raise ValidationError({'detail': (
                "Ce transfert a déjà un effet sur les stocks : il n'est plus modifiable "
                "(utilisez la résolution de litige le cas échéant)."
            )})
        serializer.save()

    def perform_destroy(self, instance):
        # BUG-223 : supprimer un transfert répondu/confirmé/en litige laissait
        # le stock du groupe déséquilibré et levait le blocage de clôture sans
        # résolution. Seuls les transferts sans effet de stock (en attente,
        # annulés) sont supprimables.
        if instance.transfer_status in (
            BreadTransfer.TransferStatus.RESPONDED,
            BreadTransfer.TransferStatus.CONFIRMED,
            BreadTransfer.TransferStatus.DISPUTED,
        ):
            raise ValidationError({'detail': (
                "Ce transfert a déjà un effet sur les stocks : il ne peut pas être supprimé."
            )})
        instance.delete()


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


class BreadStockByDateView(APIView):
    """
    BUG-144 (remarque.md, ligne ajoutée après l.396 ; coordinateur, 2026-11-10) :
    `BreadStockViewSet` (`GET /api/production/bread-stocks/`) ne renvoie que
    le solde COURANT cumulatif par catégorie (`BreadStock.qty_available`) —
    aucune manière de consulter ce que le stock de pains valait à une date
    PASSÉE. Ce nouvel endpoint de LECTURE SEULE comble ce manque pour que le
    frontend (ticket BUG-145, `dev-frontend`, séparé) puisse ajouter un
    sélecteur de date aux sections « Stock Pains Actuel »/« Stock Pains du
    Jour » et « Historique des Fournées » de Production & Stocks.

    `GET /api/production/bread-stocks/by-date/?node=<code ou pk>&date=<AAAA-MM-JJ, optionnel>`

    Permissions : `IsAuthenticated`, comme `BreadStockViewSet` (lecture
    seule, tous rôles authentifiés) ; isolation par nœud identique à
    `DailyClosureReportView`/`_opening_confirmation_resolve_node`
    (BUG-022/025/056/120/133) : un non-HQ (`not user.can_access_all_nodes`)
    ne voit jamais que son propre nœud — toute valeur `node` reçue dans la
    requête est IGNORÉE, jamais une fuite ; un HQ doit préciser `node`
    explicitement.

    Règles selon `date` :
      - Omise, ou égale à aujourd'hui → `source: "live"` — catégories =
        `BreadStock.qty_available` COURANT pour ce nœud, un enregistrement
        par catégorie déjà suivie (mêmes lignes que `BreadStockViewSet`
        filtré sur ce nœud). Comportement RIGOUREUSEMENT identique à
        l'existant pour ce cas (non-régression explicite demandée par le
        ticket) : aucune catégorie ajoutée ou retirée par rapport à ce que
        `BreadStockViewSet` renvoie déjà pour ce nœud.
      - Strictement dans le passé → `source: "snapshot"` — catégories
        reconstituées à partir de `DailyBreadStockSnapshot` (BUG-118/120/135,
        déjà vérifié) : pour chaque catégorie ayant au moins une ligne
        (node, bread_price, date) côté équipe A OU B, `qty_available` = somme
        de `qty_at_close` sur les deux équipes — une équipe SANS ligne ce
        jour-là compte pour 0 (convention déjà documentée sur
        `DailyBreadStockSnapshot`, pas une absence de valeur). Une catégorie
        sans AUCUNE ligne ce jour-là (ni A ni B n'ont clôturé) est absente de
        la réponse — même convention que le cas « live », qui ne renvoie que
        les catégories ayant une ligne `BreadStock` effective pour ce nœud.
      - Dans le futur → 400, `{"detail": "..."}` en français. Volontairement
        SANS passer par `core.utils.validate_requested_date` : cet utilitaire
        conditionne aussi le refus d'une date PASSÉE à
        `Config.allow_backdated_sales`, une règle d'ÉCRITURE (BUG-083) sans
        rapport avec la simple LECTURE d'un historique déjà enregistré — un
        gérant doit pouvoir consulter n'importe quel jour passé que la saisie
        de ventes passées soit activée ou non. Seul le refus du futur
        (universel, même esprit que BUG-128/`CalendarPicker.tsx`) est repris
        ici.

    Contrat de réponse, volontairement identique dans les deux cas pour que
    le frontend ait un seul format à consommer :
        {
          "node": <pk>, "node_display": "<code> — <nom>",
          "date": "AAAA-MM-JJ", "source": "live" | "snapshot",
          "categories": [
            {"bread_price": <pk>, "bread_price_display": "<label>",
             "unit_price": <int>, "qty_available": <int>},
            ...
          ]
        }
    Contrat détaillé (mise à jour, exemples complets) :
    `docs/qa/rapports/dev-backend-2026-11-10-bug144-stock-pains-par-jour.md`.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils.dateparse import parse_date

        user = request.user
        node_param = request.query_params.get('node')
        if not user.can_access_all_nodes:
            if not user.node_id:
                return Response(
                    {'detail': "Compte non assigné à une boulangerie."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            node = user.node
        else:
            if not node_param:
                return Response(
                    {'detail': "Le paramètre `node` (code ou identifiant) est requis."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            node = _resolve_node(node_param)
            if node is None:
                return Response(
                    {'detail': f"Boulangerie « {node_param} » introuvable."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # BUG-161 (B3) : « aujourd'hui » = date de travail du nœud (date locale
        # hors rotation, relève à relève en mode rotation).
        today = work_date_for(node)
        date_str = request.query_params.get('date')
        if date_str:
            requested_date = _safe_parse_date(date_str)
            if requested_date is None:
                return Response(
                    {'detail': "Date invalide — format attendu AAAA-MM-JJ."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            requested_date = today

        if requested_date > today:
            return Response(
                {
                    'detail': (
                        f"La date demandée ({requested_date}) ne peut pas être "
                        f"dans le futur (aujourd'hui : {today})."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if requested_date == today:
            source = 'live'
            categories = [
                {
                    'bread_price': bs.bread_price_id,
                    'bread_price_display': str(bs.bread_price),
                    'unit_price': bs.bread_price.unit_price,
                    'qty_available': bs.qty_available,
                }
                for bs in (
                    BreadStock.objects
                    .select_related('bread_price')
                    .filter(node=node)
                    .order_by('bread_price__unit_price')
                )
            ]
        else:
            source = 'snapshot'
            totals, bp_by_id = {}, {}
            snapshots = (
                DailyBreadStockSnapshot.objects
                .select_related('bread_price')
                .filter(node=node, date=requested_date)
            )
            for snap in snapshots:
                totals[snap.bread_price_id] = totals.get(snap.bread_price_id, 0) + snap.qty_at_close
                bp_by_id[snap.bread_price_id] = snap.bread_price
            categories = [
                {
                    'bread_price': bp_id,
                    'bread_price_display': str(bp_by_id[bp_id]),
                    'unit_price': bp_by_id[bp_id].unit_price,
                    'qty_available': totals[bp_id],
                }
                for bp_id in sorted(bp_by_id, key=lambda i: bp_by_id[i].unit_price)
            ]

        return Response({
            'node': node.pk,
            'node_display': str(node),
            'date': requested_date.isoformat(),
            'source': source,
            'categories': categories,
            **work_time_info(node),
        })


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
        # BUG-221 : régularise `BreadStock.qty_disposed` — on contre-passe
        # l'effet de l'ancienne version puis on applique celui de la nouvelle
        # (seuls les types ≠ REMAINING touchent le stock), dans une transaction.
        with transaction.atomic():
            old_node, old_bp = instance.node, instance.bread_price
            old_type, old_qty = instance.disposal_type, instance.quantity
            disposal = serializer.save()
            if old_type != BreadDisposal.DisposalType.REMAINING:
                _adjust_bread_stock(old_node, old_bp, disposed=-old_qty)
            if disposal.disposal_type != BreadDisposal.DisposalType.REMAINING:
                _adjust_bread_stock(disposal.node, disposal.bread_price, disposed=disposal.quantity)
            if (old_type, old_qty, old_bp.pk) != (disposal.disposal_type, disposal.quantity, disposal.bread_price_id):
                log_activity(
                    self.request.user, "Modification Disposition Pain",
                    f"{disposal.node.code} : disposition {old_type} {old_qty}×{old_bp.label} "
                    f"→ {disposal.disposal_type} {disposal.quantity}×{disposal.bread_price.label}.",
                    node_origin=disposal.node.code,
                )

    def perform_destroy(self, instance):
        # BUG-221 : les pains d'une disposition supprimée retournent au stock.
        with transaction.atomic():
            node, bp = instance.node, instance.bread_price
            dtype, qty = instance.disposal_type, instance.quantity
            instance.delete()
            if dtype != BreadDisposal.DisposalType.REMAINING:
                _adjust_bread_stock(node, bp, disposed=-qty)
            log_activity(
                self.request.user, "Suppression Disposition Pain",
                f"{node.code} : disposition {dtype} {qty}×{bp.label} supprimée "
                f"(pains remis en stock).",
                node_origin=node.code,
            )


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


def _build_daily_closure_report(node, report_date=None):
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
    if report_date is None:
        # BUG-161 (B3) : par défaut, la journée de travail courante du nœud.
        report_date = work_date_for(node)

    sessions_qs = ProductionSession.objects.filter(node=node, date=report_date)
    sacs_produits = sessions_qs.aggregate(t=Sum('flour_sacks_used'))['t'] or Decimal('0.00')
    net_produit_fc = Decimal(sessions_qs.aggregate(t=Sum('total_fc_produced'))['t'] or 0)
    ecart_production_fc = sessions_qs.aggregate(t=Sum('yield_gap'))['t'] or 0
    total_breads_produced = sessions_qs.aggregate(t=Sum('total_breads'))['t'] or 0

    # BUG-142 : exclut les lignes CARRYOVER (reste d'hier confirmé,
    # BUG-133/136) — ce rapport (« produit » par catégorie, déjà vérifié
    # formule à formule contre les Excel réels, BUG-120) ne doit afficher
    # que la vraie production (lignes DECLARED), jamais le reste d'hier
    # (qui est déjà représenté séparément via `reste_du_hier`/`reste_du_jour`
    # ci-dessous) — sous peine de faire apparaître deux fois la même
    # quantité sous deux rubriques différentes du même rapport.
    produced_by_bp = dict(
        ProductionSessionLine.objects.filter(
            session__in=sessions_qs, source=ProductionSessionLine.Source.DECLARED,
        )
        .values('bread_price_id').annotate(qty=Sum('quantity'))
        .values_list('bread_price_id', 'qty')
    )

    node_codes = set(Node.objects.values_list('code', flat=True))

    base_invoices = Invoice.objects.filter(
        node=node, status=Invoice.Status.DELIVERED,
        # BUG-286 : date de vente = date de LIVRAISON (BUG-275), comme
        # daily_summary, bread_summary et le rapport facturier.
        **delivered_on_work_date_filter(node, report_date),
        is_debt_repayment=False,
    )

    # FACTURE/JR : ventes normales (ni soldées, ni ajustements, ni « non
    # servi », ni facture de mouvement interne codée par un code boulangerie
    # — ces trois dernières ont chacune leur propre rubrique ci-dessous).
    # BUG-177 : les `RG` sortent aussi de FACTURE/JR (colonne « Régularisation »,
    # pas de double comptage).
    normal_invoices = base_invoices.filter(is_adjustment=False, is_soldee=False) \
        .exclude(special_code__in=[Invoice.SpecialCode.NS, Invoice.SpecialCode.RG]) \
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
    # BUG-185 : une RG (ou NS) n'est JAMAIS une vente, quelles que soient ses
    # cases (`is_soldee`, `commission_exempt`) : exclue d'ici, comptée une
    # seule fois en « Régularisation » (prix pleins).
    soldee_invoices = base_invoices.filter(is_adjustment=False, is_soldee=True) \
        .exclude(special_code__in=[Invoice.SpecialCode.NS, Invoice.SpecialCode.RG])
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
    # BUG-177 : + factures `RG` (quantités POSITIVES, rattrapage d'un non-servi
    # antérieur, K6!L13), livrées comme les ventes, valorisées aux prix pleins.
    rg_invoices = base_invoices.filter(is_adjustment=False, special_code=Invoice.SpecialCode.RG)
    # BUG-185 : une RG est TOUJOURS valorisée à prix plein, même si la case
    # « soldée » est cochée (les lignes sont alors figées à 75 % : on relit
    # alors le prix du catalogue).
    for line in InvoiceLine.objects.filter(invoice__in=rg_invoices).select_related('invoice', 'bread_price'):
        entry = regularisation_by_bp.setdefault(line.bread_price_id, {'qty': 0, 'fc': Decimal('0.00')})
        entry['qty'] += line.quantity or 0
        entry['fc'] += (
            Decimal(line.quantity) * Decimal(line.bread_price.unit_price)
            if line.invoice.is_soldee else Decimal(line.line_total)
        )

    # NON SERVI/S (BUG-177) : factures `NS` du jour, PENDING et DELIVERED
    # (jamais CANCELLED) — une NS reste PENDING par définition. Montant =
    # Σ order_total (lignes aux prix pleins), quantités en information ;
    # contribution NÉGATIVE au total (K6!L12 -> L21), voir `mvm_interne_fc`.
    ns_invoices = Invoice.objects.filter(
        node=node, invoice_date=report_date, special_code=Invoice.SpecialCode.NS,
        is_debt_repayment=False, is_adjustment=False,
    ).exclude(status=Invoice.Status.CANCELLED)
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
            # BUG-193 : journée de travail (rotation) ; hors rotation = `__date` inchangé.
            **delivered_on_work_date_filter(node, report_date, 'transfer__updated_at'),
        ).values('bread_price_id').annotate(qty=Sum('quantity_sent')).values_list('bread_price_id', 'qty')
    )
    appro_recu_by_bp = dict(
        BreadTransferLine.objects.filter(
            transfer__to_node=node,
            transfer__transfer_status=BreadTransfer.TransferStatus.CONFIRMED,
            **delivered_on_work_date_filter(node, report_date, 'transfer__updated_at'),
        ).values('bread_price_id').annotate(qty=Sum('quantity_received')).values_list('bread_price_id', 'qty')
    )

    team_choices = [c[0] for c in ProductionSession.Team.choices]

    # BUG-161 (B4) : équipe de service de `report_date` (rotation seulement) :
    # désignation, sinon équipe de la session du jour, sinon de la
    # confirmation du stock de départ, sinon aucune (reste du hier à 0).
    rotation = bool(getattr(node, 'team_rotation_enabled', False))
    day_team = None
    if rotation:
        day_team = (
            team_at_day_start(node, report_date)
            or sessions_qs.order_by('team').values_list('team', flat=True).first()
            or DailyOpeningConfirmation.objects.filter(node=node, date=report_date)
            .order_by('team').values_list('team', flat=True).first()
        )

    # BUG-133 : si le gérant a explicitement confirmé le stock de départ
    # (RESTE DU HIER) pour (node, équipe, report_date) via la boîte modale
    # de première connexion, cette valeur DÉCLARÉE devient prioritaire sur
    # le calcul auto-dérivé de `DailyBreadStockSnapshot.reste_du_hier()`
    # pour cette équipe/catégorie/jour précis — sans jamais toucher
    # `DailyBreadStockSnapshot` lui-même (BUG-118, VÉRIFIÉ, laissé intact).
    # Absence de confirmation pour ce jour/équipe = comportement auto-dérivé
    # strictement inchangé (rétro-compatibilité totale).
    confirmed_reste_du_hier_by_team_bp = {}
    handover_confirmations = []
    # BUG-247 : reste de FIN DE JOURNÉE (rotation) = dernier reste déclaré de la
    # date, une fois TOUTES les sessions de la date clôturées ; tant qu'une
    # session est ouverte, le reste du jour n'est pas connu (0, comme avant).
    day_is_complete = not (
        rotation and ProductionSession.objects.filter(node=node, date=report_date, is_closed=False).exists()
    )
    for confirmation in DailyOpeningConfirmation.objects.filter(
        node=node, date=report_date,
    ).prefetch_related('lines'):
        # BUG-247 : en rotation, un seul rapport par jour calendaire ; seule la
        # confirmation de l'équipe de début de journée est le « reste du hier »
        # du rapport. Celle de l'équipe entrante à la relève (restes de
        # l'équipe sortante) est un transfert interne, jamais additionné.
        if rotation and day_team is not None and confirmation.team != day_team:
            # L'ÉCART entre ce qu'elle a trouvé et le reste déclaré par l'équipe
            # sortante (ajustement de stock tracé) est porté au départ de la
            # journée plus bas, pour que l'identité du rapport tienne.
            handover_confirmations.append((
                confirmation.confirmed_at,
                {line.bread_price_id: line.qty_confirmed for line in confirmation.lines.all()},
            ))
            continue
        for line in confirmation.lines.all():
            confirmed_reste_du_hier_by_team_bp[(confirmation.team, line.bread_price_id)] = line.qty_confirmed
    confirmed_bp_ids_any_team = {bp_id for (_team, bp_id) in confirmed_reste_du_hier_by_team_bp}

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
        # BUG-135 : `DailyOpeningConfirmationLine.qty_confirmed` est stocké
        # POSITIF à dessein (stock physique réel saisi/validé par le gérant
        # dans la boîte modale, CLAUDE.md §5.4/BUG-133/134 — ne pas toucher
        # à ce stockage). Mais `DailyBreadStockSnapshot.reste_du_hier()`
        # (BUG-118, VÉRIFIÉ, formule-vérifiée contre l'Excel réel) suit la
        # convention INVERSE : `reste_du_hier = -reste_du_jour(veille)`,
        # négative par construction. `facture_mvm_interne`/`total_du_jour`
        # (BUG-120, déjà vérifiés formule à formule contre les Excel réels)
        # dépendent de `reste_du_hier_fc` calculé ci-dessous à partir de ce
        # dict : une valeur confirmée non négée y introduirait un signe
        # inversé par rapport à un jour équivalent non confirmé, cassant la
        # cohérence du total cumulé (trouvé par le coordinateur en relisant
        # le code après BUG-133/134). On applique donc ici — et seulement
        # ici, à l'agrégation du rapport — la même convention de signe que
        # le calcul auto-dérivé, pour que `reste_du_hier_by_team` (exposé
        # tel quel au frontend, `ClotureJournaliere.tsx`) reste cohérent en
        # signe entre jours confirmés et jours non confirmés.
        def _auto_reste_du_hier(team):
            if not rotation:
                return DailyBreadStockSnapshot.reste_du_hier(node, bp, report_date, team)
            # BUG-161 (B4) : en rotation, le départ d'une journée est le
            # dernier reste du nœud TOUTES ÉQUIPES CONFONDUES (A -> B -> A),
            # porté par la seule équipe de service du jour (sinon doublon
            # dans la somme `reste_du_hier_fc`). Jamais écrit : lecture seule.
            if team != day_team:
                return 0
            # BUG-191 : une seule source par journée de travail. Si le stock de
            # départ de cette catégorie a été confirmé par une équipe (celle
            # désignée au moment de la confirmation, éventuellement corrigée
            # depuis), la valeur confirmée fait foi : le chaînage automatique
            # ne la double pas sur l'équipe désignée aujourd'hui.
            if bp_id in confirmed_bp_ids_any_team:
                return 0
            return DailyBreadStockSnapshot.reste_du_hier_chained(node, bp, report_date)

        reste_du_hier_by_team = {
            team: (
                -confirmed_reste_du_hier_by_team_bp[(team, bp_id)]
                if (team, bp_id) in confirmed_reste_du_hier_by_team_bp
                else _auto_reste_du_hier(team)
            )
            for team in team_choices
        }
        if rotation and day_team is not None and handover_confirmations:
            # BUG-247 : écart de stock constaté par l'équipe entrante à la
            # relève (confirmé - dernier reste déclaré avant la confirmation),
            # ajouté au départ de la journée (identité du rapport préservée).
            handover_adjust = 0
            for confirmed_at, qty_by_bp in handover_confirmations:
                if bp_id not in qty_by_bp:
                    continue
                before = (
                    DailyBreadStockSnapshot.objects
                    .filter(node=node, bread_price=bp, date__lte=report_date, updated_at__lte=confirmed_at)
                    .order_by('-date', '-updated_at', '-pk').first()
                )
                handover_adjust += qty_by_bp[bp_id] - (before.qty_at_close if before else 0)
            if handover_adjust:
                reste_du_hier_by_team[day_team] = (reste_du_hier_by_team.get(day_team) or 0) - handover_adjust
        if rotation:
            # BUG-247 : un seul rapport par jour calendaire, partagé par les deux
            # équipes. Le reste de FIN DE JOURNÉE est le dernier reste déclaré
            # de la date (toutes équipes) : celui de l'équipe sortante à la
            # relève est le départ de l'équipe entrante, jamais additionné.
            last_snap = (
                DailyBreadStockSnapshot.objects
                .filter(node=node, bread_price=bp, date=report_date)
                .order_by('-updated_at', '-pk').first()
            ) if day_is_complete else None
            reste_du_jour_fin = last_snap.qty_at_close if last_snap else None
            reste_du_jour_fc = _m(Decimal(reste_du_jour_fin or 0) * catalog_price)
        else:
            reste_du_jour_fin = None
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
            - non_servi_fc + reg_fc  # BUG-177 : NS retranchée (signe du classeur)
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
            **({'reste_du_jour_fin_journee': reste_du_jour_fin} if rotation else {}),
            'reste_du_hier': reste_du_hier_by_team,
            'appro_effectue': {'quantity': appro_effectue_qty, 'fc': str(appro_effectue_fc)},
            'appro_recu':     {'quantity': appro_recu_qty, 'fc': str(appro_recu_fc)},
            # `fc` = montant POSITIF affiché ; `fc_signe` = contribution
            # réelle aux totaux (négative, K6!L12).
            'non_servi': {
                'quantity': ns.get('qty') or 0, 'fc': str(non_servi_fc),
                'fc_signe': str(-non_servi_fc) if non_servi_fc else '0.00',
            },
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
        # BUG-177 : NS exclue (pas une commande servie) ; RG incluse via `reg`.
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
        node=node, status=Invoice.Status.DELIVERED,
        **delivered_on_work_date_filter(node, report_date),  # BUG-286
    ).exclude(special_code=Invoice.SpecialCode.NS).aggregate(  # BUG-177 : NS n'est pas une commande
        commande=Sum('order_total'), paye=Sum('payment_amount'))
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
    # BUG-186 : convention = répartition de la production DÉCLARÉE (lignes
    # DECLARED, colonne « produit »). Le dénominateur est la somme de ces
    # mêmes quantités (et non `total_breads_produced`, qui inclut les lignes
    # CARRYOVER du stock de départ, BUG-142) : la répartition somme à 100 %.
    declared_qty_total = sum(row['produit']['quantity'] or 0 for row in categories_payload)
    for row in categories_payload:
        qty = row['produit']['quantity']
        pct_qty = (
            (Decimal(qty) * Decimal('100') / Decimal(declared_qty_total))
            .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if qty and declared_qty_total else Decimal('0.00')
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
        **work_time_info(node),
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
        report_date = _safe_parse_date(date_str)
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


def _opening_confirmation_resolve_node(request, node_param):
    """
    Même règle que `DailyClosureReportView.get()`/`_resolve_node()` : un
    non-HQ n'agit jamais que sur sa propre boulangerie (toute valeur `node`
    reçue est ignorée, jamais une fuite — même motif que BUG-022/025/056) ;
    un HQ doit explicitement préciser `node`.
    Renvoie `(node, None)` ou `(None, Response(...))`.
    """
    user = request.user
    if not user.can_access_all_nodes:
        if not user.node_id:
            return None, Response(
                {'detail': "Compte non assigné à une boulangerie."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return user.node, None
    if not node_param:
        return None, Response(
            {'detail': "Le paramètre `node` (code ou identifiant) est requis."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    node = _resolve_node(node_param)
    if node is None:
        return None, Response(
            {'detail': f"Boulangerie « {node_param} » introuvable."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return node, None


def _sync_carryover_session_lines(node, team, date, user, parsed_lines, sac_value_fc):
    """
    BUG-142 (remarque.md) : la confirmation du stock de départ (BUG-133/136)
    doit créer OU compléter la `ProductionSession` du jour pour (node, team,
    date) avec des lignes `CARRYOVER` miroir de CETTE confirmation — pour
    qu'elle apparaisse comme une fournée de l'équipe dans « Production &
    Stocks ». Remplacement COMPLET des lignes CARRYOVER à chaque appel (la
    confirmation elle-même est idempotente/remplace intégralement ses
    propres lignes, BUG-136) — PAS additif, contrairement aux lignes
    DECLARED d'une vraie fournée (`ProductionSessionViewSet.perform_create`,
    cas A du même ticket), qui ne sont jamais touchées ici.

    Les lignes CARRYOVER ne déclenchent JAMAIS `_adjust_bread_stock` : le
    stock physique est déjà synchronisé une fois par l'appelant (BUG-136,
    `BreadStock.qty_adjusted`) — un appel supplémentaire ici compterait le
    stock en double.

    `sac_value_fc` n'est utilisé que si une NOUVELLE session est créée ici
    (aucune session DECLARED ou CARRYOVER préexistante ce jour pour cette
    équipe) — pour que la valeur du sac figée (BUG-038) soit la valeur
    effective de la boulangerie au moment de cette toute première ligne du
    jour, et non une valeur par défaut arbitraire, si une VRAIE fournée est
    déclarée plus tard dans la même session.

    Renvoie `(session, None)` ou `(None, Response(...))` si la session du
    jour est déjà clôturée (BUG-093) — ne contourne jamais une clôture.
    """
    session = ProductionSession.objects.select_for_update().filter(
        node=node, team=team, date=date,
    ).first()
    if session is not None and session.is_closed and _reopen_session_for_redesignated_team(session, node, user):
        session = ProductionSession.objects.select_for_update().get(pk=session.pk)
    if session is not None and session.is_closed:
        return None, Response(
            {
                'detail': (
                    f"Session de production clôturée pour l'Équipe {team} le {date} "
                    f"à la boulangerie {node.code} — confirmation du stock de départ impossible."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if session is None:
        session = ProductionSession.objects.create(
            node=node, team=team, date=date,
            declared_by=user, node_origin=node.code,
            sac_value_fc_used=sac_value_fc,
        )

    submitted_bp_ids = {bp_id for bp_id, qty in parsed_lines if qty > 0}
    session.lines.filter(
        source=ProductionSessionLine.Source.CARRYOVER,
    ).exclude(bread_price_id__in=submitted_bp_ids).delete()
    for bread_price_id, qty in parsed_lines:
        if qty <= 0:
            continue
        ProductionSessionLine.objects.update_or_create(
            session=session, bread_price_id=bread_price_id,
            source=ProductionSessionLine.Source.CARRYOVER,
            defaults={'quantity': qty},
        )

    # BUG-038 : ne jamais relire _effective_sac_value() si la session
    # existait déjà — réutilise la valeur déjà figée (vraie fournée
    # déclarée avant, ou précédent appel de cette même fonction).
    session.compute_totals(session.sac_value_fc_used)
    session.save(update_fields=_SESSION_COMPUTED_FIELDS)
    return session, None


class DailyOpeningConfirmationView(APIView):
    """
    BUG-133 (docs/qa/REGISTRE_BUGS.md) : boîte modale « stock de départ » —
    à sa première connexion de la journée (en pratique : tant qu'aucune
    confirmation n'existe pour node/équipe/aujourd'hui, le client a demandé
    que la boîte modale se réaffiche à CHAQUE changement de page du
    dashboard, pas seulement au login), le gérant doit pouvoir consulter le
    stock physique actuellement disponible par catégorie de pain
    (`BreadStock.qty_available`, déjà net des ventes confirmées —
    `sales/views.py` décrémente ce même solde via `_adjust_bread_stock(...,
    sent=...)` à chaque livraison), le modifier ou le valider tel quel, et
    que cette validation devienne la valeur officielle de « RESTE DU HIER »
    pour démarrer la journée (consommée par `_build_daily_closure_report`,
    BUG-120 — voir le docstring de `DailyOpeningConfirmation`).

    `GET /api/production/opening-confirmation/?node=<code>&date=<AAAA-MM-JJ, optionnel, défaut aujourd'hui>`
    Volontairement léger (deux requêtes filtrées simples, aucune agrégation
    lourde) pour être interrogé en toute sécurité à chaque changement de
    route du dashboard côté frontend, pas seulement au login — voir le
    sous-ticket `dev-frontend` lié. Renvoie, pour les DEUX équipes A et B à
    la fois (le choix de l'équipe à confirmer se fait dans la boîte modale
    elle-même, jamais déduit ici) :
      - `categories` : catégories actives avec la quantité PROPOSÉE
        (`qty_proposed` = `BreadStock.qty_available` courant).
      - `teams.<A|B>.confirmed` : `true` si une confirmation existe déjà
        pour cette équipe à cette date (le frontend n'affiche alors plus la
        boîte modale pour cette équipe) ; sinon `false`.

    `POST /api/production/opening-confirmation/`
    Corps : `{"node": <code, HQ seulement>, "team": "A"|"B",
    "date": "AAAA-MM-JJ" (optionnel, défaut aujourd'hui),
    "lines": [{"bread_price": <id>, "qty": <entier >= 0>}, ...]}`.
    Idempotent (upsert) : un gérant qui corrige une saisie avant d'avoir
    quitté la boîte modale peut soumettre plusieurs fois le même jour pour
    la même équipe — la dernière soumission remplace la précédente (même
    idiome `update_or_create` que `DailyBreadStockSnapshot.record_snapshot`,
    BUG-118, déjà vérifié), dans une unique transaction atomique couvrant
    toutes les catégories soumises ensemble (CLAUDE.md §4).

    BUG-136 (client, 2026-11-09) : cette validation synchronise TOUJOURS le
    stock physique réel (`BreadStock.qty_available`) sur la valeur
    confirmée, y compris en cas de validation telle que proposée (delta nul,
    no-op). L'écart entre la valeur confirmée et le `qty_available` courant
    au moment de la soumission est appliqué comme un ajustement manuel
    traçable (`BreadStock.qty_adjusted`, jamais `qty_sent`/`qty_disposed`,
    sémantique distincte — voir docstring du modèle), verrouillé via
    `select_for_update()` (CLAUDE.md §4) et journalisé via `log_activity`.
    Le delta est recalculé par rapport à l'état COURANT à chaque
    soumission : une resoumission/correction le même jour pour la même
    équipe n'applique jamais l'ajustement deux fois cumulativement.

    BUG-138 (client, tranché directement avec le coordinateur, 2026-11-09,
    remarque.md l.398 « le facturier peut aussi faire ça ») : le FACTURIER
    peut désormais consulter et soumettre cette confirmation au même titre
    que le GERANT (`IsFacturier` englobe déjà GERANT+ — voir
    `core/permissions.py`) — jamais sur un autre nœud que le sien
    (`_opening_confirmation_resolve_node` applique la même règle
    `can_access_all_nodes`/`user.node` pour les deux rôles, FACTURIER n'ayant
    pas accès multi-nœud, comme GERANT).

    BUG-139 (client, tranché directement avec le coordinateur, 2026-11-09,
    remarque.md l.398 « on le fait une fois le matin, [...] juste une fois
    au créneau d'ouverture (premier créneau) ») : UNE SEULE confirmation
    dans la journée — celle de l'équipe du créneau d'ouverture — doit
    suffire à faire disparaître la boîte modale, pas les deux équipes A ET
    B. Ceci ne change QUE le signal consommé par le frontend pour décider
    d'afficher la boîte modale ; le modèle `DailyOpeningConfirmation`
    (clé `[node, team, date]`) et `_build_daily_closure_report`/BUG-135
    (qui continuent, par équipe, à préférer la valeur confirmée de CETTE
    équipe si elle existe, sinon l'auto-dérivé BUG-118) restent inchangés.

    La réponse du GET porte donc, en plus de `teams.<A|B>.confirmed`
    (informatif, conservé pour compatibilité mais NE DOIT PLUS servir à
    décider d'afficher la boîte modale côté frontend) :
      - `opening_team` : `"A"` ou `"B"` — l'équipe du PREMIER créneau de la
        journée (`Node.opening_team()`, BUG-141), déterminée
        STRUCTURELLEMENT à partir des horaires configurés du nœud
        (`team_a_start_time`/`team_b_start_time`), **indépendamment de
        l'heure actuelle** ; `null` si le nœud n'a pas de créneaux
        configurés. Ne pas confondre avec `Node.active_team_at()` (BUG-130),
        utilisé ailleurs dans le code pour répondre à une question
        différente (« qui travaille EN CE MOMENT ? ») — ce n'est PAS la
        méthode utilisée ici : un gérant/facturier peut se connecter le
        soir, hors de tout créneau, pour rattraper une confirmation
        oubliée (remarque.md l.398), et doit malgré tout voir l'équipe du
        premier créneau (BUG-141).
      - `needs_confirmation` (booléen) : **seul signal que le frontend doit
        utiliser** pour décider d'afficher la boîte modale (BUG-139) :
          * `opening_team` déterminé (A ou B) → `needs_confirmation =
            not teams[opening_team].confirmed` (seule l'équipe du créneau
            d'ouverture doit avoir confirmé) ;
          * `opening_team` est `null` (nœud sans créneaux configurés, filet
            de sécurité) → `needs_confirmation = not teams.A.confirmed and
            not teams.B.confirmed` (UNE confirmation, A OU B, suffit).
    """
    permission_classes = [IsFacturier]

    def get(self, request):
        from django.utils.dateparse import parse_date

        node, err = _opening_confirmation_resolve_node(request, request.query_params.get('node'))
        if err is not None:
            return err

        date_str = request.query_params.get('date')
        if date_str:
            report_date = _safe_parse_date(date_str)
            if report_date is None:
                return Response(
                    {'detail': "Date invalide — format attendu AAAA-MM-JJ."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # BUG-161 (B3) : journée de travail courante du nœud (date locale
            # hors rotation).
            report_date = work_date_for(node)

        categories = list(BreadPrice.objects.filter(is_active=True).order_by('unit_price'))
        # `qty_available` est une propriété Python (produced+received-sent-
        # disposed), pas une colonne — on l'évalue en Python par ligne,
        # jamais via `values_list` (qui ne verrait que des colonnes brutes).
        proposed_by_bp = {
            bs.bread_price_id: bs.qty_available
            for bs in BreadStock.objects.filter(node=node, bread_price__in=categories)
        }
        rotation = node.team_rotation_enabled
        if rotation:
            # BUG-161 (B4) : chaînage inter-équipes — la quantité proposée est
            # le dernier reste déclaré à une clôture du nœud avant cette
            # journée, toutes équipes confondues (le reste de A = départ de B).
            # Sans instantané antérieur pour la catégorie : stock courant.
            for bp in categories:
                # BUG-247 : jusqu'à la date incluse — à la relève de midi, le
                # reste de l'équipe sortante (même date calendaire) est le
                # départ de l'équipe entrante.
                previous = DailyBreadStockSnapshot.last_snapshot_upto(node, bp, report_date)
                if previous is not None:
                    proposed_by_bp[bp.id] = previous.qty_at_close

        categories_payload = [
            {
                'bread_price': bp.id,
                'label': bp.label,
                'unit_price': bp.unit_price,
                'qty_proposed': proposed_by_bp.get(bp.id, 0),
            }
            for bp in categories
        ]

        confirmations_qs = DailyOpeningConfirmation.objects.filter(
            node=node, date=report_date,
        )
        if rotation and not date_str:
            # BUG-247 : une confirmation par PÉRIODE DE SERVICE (relève), pas
            # par jour calendaire : celle d'une période précédente (même date
            # calendaire ou veille) ne dispense pas l'équipe entrante.
            from core.workday import shift_period_start
            confirmations_qs = DailyOpeningConfirmation.objects.filter(
                node=node, confirmed_at__gte=shift_period_start(node),
            ).order_by('confirmed_at')
        confirmations_by_team = {
            confirmation.team: confirmation
            for confirmation in confirmations_qs.select_related('confirmed_by').prefetch_related('lines')
        }

        teams_payload = {}
        for team in ProductionSession.Team.values:
            confirmation = confirmations_by_team.get(team)
            if confirmation is None:
                teams_payload[team] = {
                    'confirmed': False, 'confirmed_at': None, 'confirmed_by': None, 'lines': None,
                }
            else:
                teams_payload[team] = {
                    'confirmed': True,
                    'confirmed_at': confirmation.confirmed_at,
                    'confirmed_by': (
                        confirmation.confirmed_by.get_full_name() or confirmation.confirmed_by.username
                        if confirmation.confirmed_by else None
                    ),
                    'lines': [
                        {'bread_price': line.bread_price_id, 'qty_confirmed': line.qty_confirmed}
                        for line in confirmation.lines.all()
                    ],
                }

        # BUG-139/BUG-141 : équipe du PREMIER créneau de la journée,
        # déterminée structurellement à partir des horaires configurés
        # (`None` si le nœud n'a pas de créneaux configurés, BUG-130/131) —
        # c'est elle, et elle seule, qui doit avoir confirmé pour que la
        # boîte modale disparaisse pour le reste de la journée, quelle que
        # soit l'heure à laquelle cette requête est faite (NE PAS utiliser
        # `active_team_at()` ici : il répond à une autre question, « qui
        # travaille EN CE MOMENT ? »).
        if rotation:
            # BUG-161 (B4) : une confirmation par JOURNÉE DE TRAVAIL, quelle
            # que soit l'équipe ; l'équipe concernée est l'équipe désignée
            # (plus de choix d'équipe dans la boîte). Sans désignation, la
            # désignation passe d'abord (pas de boîte de stock de départ).
            designated = team_at_day_start(node, report_date) if date_str else current_team(node)
            confirmed_any = any(t['confirmed'] for t in teams_payload.values())
            return Response({
                'node': node.code,
                'date': str(report_date),
                **work_time_info(node),
                'categories': categories_payload,
                'teams': teams_payload,
                'opening_team': designated,
                'team': designated,
                'rotation': True,
                'team_assignment_required': designated is None,
                'needs_confirmation': designated is not None and not confirmed_any,
            })

        opening_team = node.opening_team()
        if opening_team in teams_payload:
            needs_confirmation = not teams_payload[opening_team]['confirmed']
        else:
            # Filet de sécurité (nœud sans créneaux configurés) : une seule
            # confirmation, A OU B, suffit — ne jamais exiger les deux.
            needs_confirmation = not (
                teams_payload['A']['confirmed'] or teams_payload['B']['confirmed']
            )

        return Response({
            'node': node.code,
            'date': str(report_date),
            **work_time_info(node),
            'categories': categories_payload,
            'teams': teams_payload,
            'opening_team': opening_team,
            'needs_confirmation': needs_confirmation,
        })

    def post(self, request):
        from django.db import transaction
        from django.utils.dateparse import parse_date

        bad_body = _body_not_object_response(request)
        if bad_body is not None:
            return bad_body
        data = request.data
        node, err = _opening_confirmation_resolve_node(request, data.get('node'))
        if err is not None:
            return err

        team = data.get('team')
        valid_teams = ProductionSession.Team.values
        if not node.team_rotation_enabled and team not in valid_teams:
            return Response(
                {'detail': f"Le champ `team` doit être l'une des valeurs : {valid_teams}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        date_str = data.get('date')
        if date_str:
            confirmation_date = _safe_parse_date(date_str)
            if confirmation_date is None:
                return Response(
                    {'detail': "Date invalide — format attendu AAAA-MM-JJ."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            confirmation_date = work_date_for(node)

        # BUG-161 (B3, risque (e) de la conception) : en mode rotation, une
        # confirmation de stock de départ ne peut viser QUE la journée de
        # travail courante — jamais une journée passée (elle réécrirait un
        # stock/une fournée de départ déjà figés) ni une journée future.
        if node.team_rotation_enabled and confirmation_date != work_date_for(node):
            return Response(
                {'detail': (
                    f"En rotation d'équipes, le stock de départ ne peut être confirmé que pour "
                    f"la journée de travail courante ({work_date_for(node)})."
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if node.team_rotation_enabled:
            # BUG-161 (B4) : l'équipe est celle désignée pour la journée de
            # travail courante ; un `team` différent est refusé, absent toléré.
            designated = current_team(node)
            if designated is None:
                return Response(
                    {'detail': "Désignez l'équipe de service du jour avant de confirmer le stock de départ.",
                     'code': 'TEAM_NOT_ASSIGNED'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if team not in (None, '') and team != designated:
                return Response(
                    {'detail': (
                        f"En rotation d'équipes, le stock de départ est confirmé pour l'équipe de "
                        f"service du jour (équipe {designated})."
                    )},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            team = designated

        lines = data.get('lines')
        if not isinstance(lines, list) or not lines:
            return Response(
                {'detail': "Le champ `lines` (liste non vide de {bread_price, qty}) est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parsed_lines = []
        seen_bp_ids = set()
        for entry in lines:
            if not isinstance(entry, dict):
                return Response({'detail': "Chaque élément de `lines` doit être un objet."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                bread_price_id = int(entry.get('bread_price'))
                qty = int(entry.get('qty'))
            except (TypeError, ValueError):
                return Response(
                    {'detail': "Chaque ligne doit fournir `bread_price` et `qty` entiers."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # BUG-162 (décision client 2026-11-10 : « Enregistre le stock même
            # s'il est négatif ») : une quantité négative est acceptée et
            # enregistrée telle quelle (stock de départ, BreadStock.qty_adjusted).
            # Les valeurs non entières restent refusées ci-dessus
            # (int('1.5') lève ValueError ; un float JSON non entier est refusé
            # ci-dessous).
            raw_qty = entry.get('qty')
            if isinstance(raw_qty, bool) or (isinstance(raw_qty, float) and raw_qty != qty):
                return Response(
                    {'detail': "Chaque ligne doit fournir `bread_price` et `qty` entiers."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if bread_price_id in seen_bp_ids:
                return Response(
                    {'detail': "Catégorie de pain dupliquée dans `lines`."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            seen_bp_ids.add(bread_price_id)
            parsed_lines.append((bread_price_id, qty))

        bp_by_id = {
            bp.id: bp for bp in BreadPrice.objects.filter(id__in=seen_bp_ids)
        }
        missing_bp_ids = seen_bp_ids - set(bp_by_id.keys())
        if missing_bp_ids:
            return Response(
                {'detail': f"Catégorie(s) de pain introuvable(s) : {sorted(missing_bp_ids)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # BUG-136 : le client a confirmé que la validation de cette boîte
        # modale doit TOUJOURS synchroniser le stock physique réel
        # (`BreadStock.qty_available`) sur la valeur confirmée — y compris
        # quand le gérant valide le nombre proposé tel quel (delta nul,
        # no-op) et surtout quand il le corrige (ajustement traçable, à la
        # manière d'un écart manquant/excédent, CLAUDE.md §5.4). Le delta est
        # recalculé à chaque soumission par rapport à l'état COURANT de
        # `BreadStock` (pas par rapport à l'ancienne valeur confirmée
        # mémorisée) : une resoumission/correction le même jour n'applique
        # donc jamais l'ajustement deux fois cumulativement (idempotence).
        # BUG-142 (remarque.md) : la confirmation du stock de départ doit
        # créer/compléter la fournée du jour (lignes CARRYOVER) pour cette
        # équipe — refuse si cette session est déjà clôturée (BUG-093), sans
        # jamais contourner la clôture.
        config = Config.get_instance()
        stock_adjustments = []
        with transaction.atomic():
            carryover_session, carryover_err = _sync_carryover_session_lines(
                node, team, confirmation_date, request.user, parsed_lines,
                _effective_sac_value(node, config),
            )
            if carryover_err is not None:
                return carryover_err

            confirmation, _created = DailyOpeningConfirmation.objects.update_or_create(
                node=node, team=team, date=confirmation_date,
                defaults={'confirmed_by': request.user},
            )
            # Remplace intégralement les lignes de CETTE confirmation par la
            # soumission reçue (idempotent — un gérant qui resoumet après
            # correction ne doit jamais accumuler d'anciennes lignes
            # obsolètes pour une catégorie qu'il aurait retirée).
            confirmation.lines.exclude(bread_price_id__in=seen_bp_ids).delete()
            for bread_price_id, qty in parsed_lines:
                DailyOpeningConfirmationLine.objects.update_or_create(
                    confirmation=confirmation, bread_price_id=bread_price_id,
                    defaults={'qty_confirmed': qty},
                )

                # Verrouillage de la ligne de stock avant lecture (CLAUDE.md
                # §4) : jamais de mise à jour de solde sans
                # select_for_update() sur la ligne lue.
                stock, _ = BreadStock.objects.get_or_create(node=node, bread_price_id=bread_price_id)
                stock = BreadStock.objects.select_for_update().get(pk=stock.pk)
                before = stock.qty_available
                delta = qty - before
                if delta:
                    _adjust_bread_stock(node, bp_by_id[bread_price_id], adjusted=delta)
                    stock_adjustments.append({
                        'bread_price_id': bread_price_id,
                        'before': before, 'after': qty, 'delta': delta,
                    })

        log_activity(
            request.user, "Confirmation Stock de Départ",
            f"{node.code} Éq.{team} {confirmation_date} : stock de départ confirmé "
            f"({len(parsed_lines)} catégorie(s)).",
            node_origin=node.code,
        )
        log_activity(
            request.user, "Fournée Reste d'Hier (Confirmation)",
            f"{node.code} Éq.{team} {confirmation_date} : fournée du jour alimentée avec le "
            f"reste d'hier confirmé ({len(parsed_lines)} catégorie(s), session #{carryover_session.pk}, BUG-142).",
            node_origin=node.code,
        )
        for adj in stock_adjustments:
            label = bp_by_id[adj['bread_price_id']].label
            log_activity(
                request.user, "Ajustement Stock (Confirmation Stock de Départ)",
                f"{node.code} Éq.{team} {confirmation_date} — {label} : stock disponible "
                f"ajusté de {adj['before']} à {adj['after']} (delta {adj['delta']:+d}, "
                f"BUG-136).",
                node_origin=node.code,
            )

        return Response(
            {
                'detail': "Stock de départ confirmé.",
                'node': node.code, 'team': team, 'date': str(confirmation_date),
                **work_time_info(node),
                'stock_adjustments': stock_adjustments,
            },
            status=status.HTTP_200_OK,
        )


class TeamAssignmentView(APIView):
    """
    BUG-161 (B2) / BUG-247 : désignation MANUELLE de l'équipe de service de la
    PÉRIODE de service courante (de relève à relève, `core.workday`) ; la date
    de travail `work_date` renvoyée est le jour calendaire local, `shift_date`
    la date de la relève qui ouvre la période (clé de la désignation).

    `GET /api/production/team-assignment/?node=<code ou pk>` renvoie
    `{work_date, handover_time, team|null, suggested, assigned_by, server_now}`
    (`node` obligatoire pour un HQ ; ignoré pour un non-HQ, comme les autres
    vues de ce module).

    `POST` `{"node": …, "team": "A"|"B"}` : upsert pour la journée de travail
    COURANTE uniquement (le serveur la calcule ; toute `work_date`/`date`
    explicite différente est refusée en 400). Changer l'équipe d'une journée
    déjà désignée est permis (correction), journalisé avec l'ancienne valeur.
    Permissions : `IsFacturier` (FACTURIER, GERANT et supérieurs).
    """
    permission_classes = [IsFacturier]

    @staticmethod
    def _payload(node, now, assignment):
        from core.workday import shift_date, suggested_team

        return {
            # BUG-227 : même journée que les autres routes (`work_date_for` :
            # date calendaire hors rotation, journée de relève en rotation).
            'work_date': work_date_for(node, now).isoformat(),
            # BUG-247 : date de la PÉRIODE DE SERVICE (relève de début) à
            # laquelle la désignation est rattachée ; en rotation elle peut
            # précéder `work_date` (jour calendaire) avant l'heure de relève.
            'shift_date': shift_date(node, now).isoformat(),
            'handover_time': node.handover_time.strftime('%H:%M'),
            'team': assignment.team if assignment else None,
            'suggested': suggested_team(node, now),
            'assigned_by': (
                (assignment.assigned_by.get_full_name() or assignment.assigned_by.username)
                if assignment and assignment.assigned_by else None
            ),
            'server_now': now.isoformat(),
        }

    def get(self, request):
        from core.workday import shift_date

        node, err = _opening_confirmation_resolve_node(request, request.query_params.get('node'))
        if err is not None:
            return err
        now = timezone.now()
        assignment = (
            DailyTeamAssignment.objects.select_related('assigned_by')
            .filter(node=node, work_date=shift_date(node, now)).first()
        )
        return Response(self._payload(node, now, assignment))

    def post(self, request):
        from core.workday import shift_date, shift_period_start

        # BUG-187 : le corps doit être un objet JSON ; `node`/`team` de bon type.
        data = request.data
        if not hasattr(data, 'get'):
            return Response(
                {'detail': "Corps de requête invalide : un objet JSON est attendu."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        node_param = data.get('node')
        if node_param is not None and (
            isinstance(node_param, bool) or not isinstance(node_param, (str, int))
        ):
            return Response(
                {'detail': "Le champ `node` doit être un code ou un identifiant de boulangerie."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        team = data.get('team')
        if team is not None and not isinstance(team, str):
            return Response(
                {'detail': "L'équipe doit être « A » ou « B »."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        node, err = _opening_confirmation_resolve_node(request, node_param)
        if err is not None:
            return err
        if team not in ProductionSession.Team.values:
            return Response(
                {'detail': "L'équipe doit être « A » ou « B »."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        now = timezone.now()
        # BUG-227 : hors rotation, la désignation n'a aucun effet sur la
        # facturation ; elle reste acceptée (rétro-compatibilité) mais sur la
        # date CALENDAIRE (comme le reste de l'API), jamais sur la journée de
        # relève J-1 — plus de désignation « parasite » décalée au basculement.
        # BUG-247 : `work_date` (colonne) = date de la période de service ; le
        # jour calendaire reste la date de travail (accepté aussi en entrée).
        work_date = shift_date(node, now)
        calendar_today = work_date_for(node, now)
        for key in ('work_date', 'date'):
            requested = request.data.get(key)
            if requested not in (None, '') and str(requested) not in (
                work_date.isoformat(), calendar_today.isoformat(),
            ):
                return Response(
                    {'detail': (
                        "La désignation ne peut porter que sur la journée de travail "
                        f"courante ({work_date.isoformat()}), jamais une date passée ou future."
                    )},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():
            existing = (
                DailyTeamAssignment.objects.select_for_update()
                .filter(node=node, work_date=work_date).first()
            )
            # BUG-196 : en rotation, on ne désigne pas l'équipe d'une NOUVELLE
            # journée de travail tant que le reste d'une journée précédente
            # n'est pas confirmé/clôturé (clôture manuelle ou automatique
            # après le délai de grâce) : sinon le reste de la veille serait
            # amputé des ventes du lendemain. Corriger la désignation de la
            # journée COURANTE (`existing`) reste permis. Hors rotation :
            # inchangé.
            if (
                existing is None and node.team_rotation_enabled
                and ProductionSession.objects.filter(
                    Q(created_at__lt=shift_period_start(node, now)) | Q(date__lt=work_date),
                    node=node, is_closed=False,
                ).exists()
            ):
                return Response(
                    {'detail': (
                        "Confirmez d'abord le reste du jour précédent : la désignation de "
                        "l'équipe de service sera possible dès que la clôture de la journée "
                        "précédente aura été confirmée."
                    ), 'code': 'PREVIOUS_WORKDAY_OPEN'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if existing is None:
                try:
                    with transaction.atomic():
                        assignment = DailyTeamAssignment.objects.create(
                            node=node, work_date=work_date, team=team, assigned_by=request.user,
                        )
                    old_team = None
                except IntegrityError:
                    # Désignation concurrente : on retombe sur la mise à jour.
                    existing = DailyTeamAssignment.objects.select_for_update().get(
                        node=node, work_date=work_date,
                    )
            if existing is not None:
                old_team = existing.team
                existing.team = team
                existing.assigned_by = request.user
                existing.save(update_fields=['team', 'assigned_by', 'assigned_at'])
                assignment = existing

            if old_team is None:
                log_activity(
                    request.user, "Désignation équipe de service",
                    f"{node.code} — journée du {work_date.isoformat()} : équipe {team} désignée.",
                    node_origin=node.code,
                )
            elif old_team != team:
                log_activity(
                    request.user, "Changement équipe de service",
                    f"{node.code} — journée du {work_date.isoformat()} : équipe {old_team} remplacée par {team}.",
                    node_origin=node.code,
                )
        return Response(self._payload(node, now, assignment))
