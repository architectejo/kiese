from django.db import transaction
from django.db.models import F, Sum

from core.workday import work_date_for, current_team, delivered_on_work_date_filter
from .models import (
    ProductionSession, ProductionSessionLine, BreadDisposal, BreadTransfer,
    BreadTransferLine, DailyBreadStockSnapshot, DailyOpeningConfirmation,
)


def find_open_batch_for_sale(node, instant=None):
    """
    BUG-306 : fournée « en cours » (ouverte, `auto_track`) de l'équipe en
    service pour la journée de travail de `instant`. Sans rotation, la plus
    récente fournée ouverte de la journée. À appeler dans une transaction
    (verrou `select_for_update`). Retourne None s'il n'y en a pas.
    """
    qs = ProductionSession.objects.select_for_update().filter(
        node=node, date=work_date_for(node, instant), is_closed=False, auto_track=True,
    )
    if getattr(node, 'team_rotation_enabled', False):
        team = current_team(node, instant)
        if team is not None:
            qs = qs.filter(team=team)
    return qs.order_by('-created_at').first()


def apply_delivered_invoice_to_open_batch(invoice):
    """
    BUG-306 / BUG-319 (remarque.md l.437 et l.445) : à la livraison d'une
    vente, fait progresser la VALEUR livrée de la fournée en cours (barre
    d'avancement : valeur livrée / objectif sacs x valeur du sac).

    BUG-319 : cette fonction n'écrit PLUS ni `qty_produced`, ni lignes
    DECLARED : « Stock Pains du Jour » ne compte que les pains VENDUS ; le
    « produit » par catégorie est DÉRIVÉ à la clôture (vendus + restes, voir
    `compute_day_production`). Seul `ProductionSession.delivered_value_fc`
    (valeur au prix catalogue des pains livrés) est incrémenté, via `F()`.

    Ignorées : factures sans ligne (remboursement), « Non Servi », ajustements
    (corrections de commande, hors périmètre). Atomique. Retourne la session
    mise à jour, ou None.
    """
    from sales.models import Invoice

    if invoice.is_debt_repayment or invoice.is_adjustment:
        return None
    if invoice.special_code == Invoice.SpecialCode.NS:
        return None
    lines = list(invoice.lines.select_related('bread_price'))
    if not lines:
        return None

    value = sum(
        line.quantity * line.bread_price.unit_price for line in lines if line.quantity > 0
    )
    if value <= 0:
        return None

    with transaction.atomic():
        session = find_open_batch_for_sale(invoice.node, invoice.delivered_at)
        if session is None:
            return None
        ProductionSession.objects.filter(pk=session.pk).update(
            delivered_value_fc=F('delivered_value_fc') + value,
        )
        session.refresh_from_db(fields=['delivered_value_fc'])
    return session


# ---------------------------------------------------------------------------
# BUG-319 : production DÉRIVÉE à la clôture (remarque.md l.445)
# ---------------------------------------------------------------------------

def day_sessions(node, work_date):
    return ProductionSession.objects.filter(node=node, date=work_date)


def day_is_closed(node, work_date):
    """Journée clôturée = au moins une fournée et AUCUNE encore ouverte."""
    qs = day_sessions(node, work_date)
    return qs.exists() and not qs.filter(is_closed=False).exists()


def day_uses_derived_production(node, work_date):
    """Vrai si une fournée « par sacs » (auto_track) existe pour la journée."""
    return day_sessions(node, work_date).filter(auto_track=True).exists()


def sold_by_bread_price(node, work_date):
    """
    Pains VENDUS (livrés) par catégorie pour la journée de travail : factures
    `DELIVERED` livrées ce jour, hors « Non servi » (statut NOT_SERVED ou code
    NS), remboursement et ajustement. Quantités servies (livraison partielle).
    """
    from sales.models import Invoice, InvoiceLine

    qs = (
        InvoiceLine.objects.filter(
            invoice__node=node, invoice__status=Invoice.Status.DELIVERED,
            invoice__is_debt_repayment=False, invoice__is_adjustment=False,
            **delivered_on_work_date_filter(node, work_date, 'invoice__delivered_at'),
        )
        .exclude(invoice__special_code=Invoice.SpecialCode.NS)
        .values('bread_price_id').annotate(qty=Sum('quantity'))
    )
    return {row['bread_price_id']: row['qty'] or 0 for row in qs}


def remaining_by_bread_price(node, work_date):
    """
    Reste du jour par catégorie (déclaré à la clôture) : dernier instantané de
    la journée, toutes équipes confondues (BUG-304 : indépendant des équipes).
    """
    out = {}
    for snap in DailyBreadStockSnapshot.objects.filter(node=node, date=work_date).order_by('updated_at', 'pk'):
        out[snap.bread_price_id] = snap.qty_at_close
    return out


def opening_by_bread_price(node, work_date, bread_price_ids):
    """
    Reste d'hier (positif) par catégorie : stock de départ confirmé le plus tôt
    de la journée, sinon dernier reste déclaré avant la journée, sinon 0.
    """
    out = {}
    for conf in (
        DailyOpeningConfirmation.objects.filter(node=node, date=work_date)
        .order_by('confirmed_at').prefetch_related('lines')
    ):
        for line in conf.lines.all():
            out.setdefault(line.bread_price_id, line.qty_confirmed)
    for bp_id in bread_price_ids:
        if bp_id in out:
            continue
        previous = DailyBreadStockSnapshot.objects.filter(
            node=node, bread_price_id=bp_id, date__lt=work_date,
        ).order_by('-date', '-updated_at', '-pk').first()
        out[bp_id] = previous.qty_at_close if previous else 0
    return out


def disposed_by_bread_price(node, work_date):
    """Soldés / déclassés / invendus / sorties gratuites du jour (hors REMAINING)."""
    qs = (
        BreadDisposal.objects.filter(node=node, session__date=work_date)
        .exclude(disposal_type=BreadDisposal.DisposalType.REMAINING)
        .values('bread_price_id').annotate(qty=Sum('quantity'))
    )
    return {row['bread_price_id']: row['qty'] or 0 for row in qs}


def transfers_by_bread_price(node, work_date):
    """(envoyés, reçus) par catégorie : transferts CONFIRMÉS ce jour de travail."""
    sent = dict(
        BreadTransferLine.objects.filter(
            transfer__from_node=node,
            transfer__transfer_status=BreadTransfer.TransferStatus.CONFIRMED,
            **delivered_on_work_date_filter(node, work_date, 'transfer__updated_at'),
        ).values('bread_price_id').annotate(qty=Sum('quantity_sent')).values_list('bread_price_id', 'qty')
    )
    received = dict(
        BreadTransferLine.objects.filter(
            transfer__to_node=node,
            transfer__transfer_status=BreadTransfer.TransferStatus.CONFIRMED,
            **delivered_on_work_date_filter(node, work_date, 'transfer__updated_at'),
        ).values('bread_price_id').annotate(qty=Sum('quantity_received')).values_list('bread_price_id', 'qty')
    )
    return (
        {k: v or 0 for k, v in sent.items()},
        {k: v or 0 for k, v in received.items()},
    )


def day_stock_movements(node, work_date):
    """
    BUG-1070 / BUG-1071 : colonnes AFFICHAGE de « Stock Pains du Jour », par
    catégorie, indépendantes de la clôture (aucun effet sur `compute_day_production`) :
      - `opening`  : stock de départ CONFIRMÉ par le gérant ce jour (le plus tôt
        de la journée) ; absent si aucune confirmation ;
      - `sent`     : pains ENVOYÉS par transfert par ce nœud (envoi direct et
        réponse à une demande ; statuts RESPONDED, CONFIRMED, DISPUTED : le stock
        a réellement quitté la boulangerie) — rien d'autre (ni ventes, ni
        soldés, ni ajustements) ;
      - `received` : pains REÇUS par transfert confirmé ou en litige (quantité reçue, stock crédité).
    Le jour d'un transfert est la date locale de sa dernière mise à jour.
    Retourne `(opening, sent, received)` : trois dicts `{bread_price_id: int}`.
    """
    opening = {}
    for conf in (
        DailyOpeningConfirmation.objects.filter(node=node, date=work_date)
        .order_by('confirmed_at').prefetch_related('lines')
    ):
        for line in conf.lines.all():
            opening.setdefault(line.bread_price_id, line.qty_confirmed)
    day = delivered_on_work_date_filter(node, work_date, 'transfer__updated_at')
    T = BreadTransfer.TransferStatus
    sent = {
        r['bread_price_id']: r['qty'] or 0
        for r in BreadTransferLine.objects.filter(
            transfer__from_node=node,
            transfer__transfer_status__in=[T.RESPONDED, T.CONFIRMED, T.DISPUTED], **day,
        ).values('bread_price_id').annotate(qty=Sum('quantity_sent'))
    }
    received = {
        r['bread_price_id']: r['qty'] or 0
        for r in BreadTransferLine.objects.filter(
            transfer__to_node=node, transfer__transfer_status__in=[T.CONFIRMED, T.DISPUTED], **day,
        ).values('bread_price_id').annotate(qty=Sum('quantity_received'))
    }
    return opening, sent, received


def compute_day_production(node, work_date, assume_closed=False):
    """
    BUG-319 : synthèse du jour par catégorie. Retourne
    `{'closed': bool, 'derived': bool, 'by_bp': {bp_id: {...}}}` ; chaque entrée :
    `sold`, `remaining` (None tant que non clôturé), `opening`, `disposed`,
    `sent`, `received`, `produced` (None tant que non clôturé).

    Formule (hypothèses par défaut du registre, à confirmer par le client) :
        produit = vendus + reste du jour                        (règle client)
                  - reste d'hier                       (R1 : stock de départ)
                  + soldés/déclassés/invendus/gratuits (R5)
                  + transferts envoyés - transferts reçus   (R2)
    Valeur brute : peut être négative si les déclarations sont incohérentes
    (pains disparus) ; l'appelant décide de l'affichage. Jour sans fournée par
    sacs (flux historique, lignes DECLARED saisies) : « produit » = lignes
    DECLARED réellement saisies.
    """
    derived = day_uses_derived_production(node, work_date)
    closed = assume_closed or day_is_closed(node, work_date)
    sold = sold_by_bread_price(node, work_date)

    by_bp = {}
    if not closed:
        for bp_id, qty in sold.items():
            by_bp[bp_id] = {
                'sold': qty, 'remaining': None, 'opening': None, 'disposed': None,
                'sent': None, 'received': None, 'produced': None,
            }
        return {'closed': False, 'derived': derived, 'by_bp': by_bp}

    remaining = remaining_by_bread_price(node, work_date)
    disposed = disposed_by_bread_price(node, work_date)
    sent, received = transfers_by_bread_price(node, work_date)
    manual = dict(
        ProductionSessionLine.objects.filter(
            session__node=node, session__date=work_date,
            source=ProductionSessionLine.Source.DECLARED,
        ).values('bread_price_id').annotate(qty=Sum('quantity')).values_list('bread_price_id', 'qty')
    )
    ids = set(sold) | set(remaining) | set(disposed) | set(sent) | set(received)
    if not derived:
        ids |= set(manual)
    opening = opening_by_bread_price(node, work_date, ids) if derived else {}
    for bp_id in ids:
        if derived:
            produced = (
                sold.get(bp_id, 0) + remaining.get(bp_id, 0) - opening.get(bp_id, 0)
                + disposed.get(bp_id, 0) + sent.get(bp_id, 0) - received.get(bp_id, 0)
            )
        else:
            produced = manual.get(bp_id, 0)
        by_bp[bp_id] = {
            'sold': sold.get(bp_id, 0),
            'remaining': remaining.get(bp_id, 0),   # R4 : pas de reste déclaré = 0
            'opening': opening.get(bp_id, 0) if derived else None,
            'disposed': disposed.get(bp_id, 0),
            'sent': sent.get(bp_id, 0),
            'received': received.get(bp_id, 0),
            'produced': produced,
        }
    return {'closed': True, 'derived': derived, 'by_bp': by_bp}


def finalize_derived_production(session):
    """
    BUG-319 (c) : à la clôture d'une fournée « par sacs », calcule la production
    dérivée de la JOURNÉE et l'écart `sacs x valeur_sac - valeur produite`.
    Les totaux du jour sont portés par la fournée clôturée EN DERNIER (les autres
    fournées `auto_track` de la journée sont remises à 0, jamais de double
    comptage dans les sommes du rapport) :
      - `total_fc_produced` = valeur (prix catalogue) du produit dérivé (>= 0) ;
      - `total_breads` = pains disponibles du jour = reste d'hier confirmé (lignes
        CARRYOVER) + produit dérivé (>= 0) + pains reçus ;
      - `yield_gap` = valeur produite - somme des rendements théoriques des
        fournées `auto_track` du jour (négatif = manquant, positif = excédent).
    Retourne le dict `compute_day_production` (clôture supposée). À appeler
    dans la transaction de clôture, après l'enregistrement des restes.
    """
    from core.models import BreadPrice

    data = compute_day_production(session.node, session.date, assume_closed=True)
    prices = dict(BreadPrice.objects.filter(pk__in=data['by_bp'].keys()).values_list('pk', 'unit_price'))
    produced_qty = sum(max(0, row['produced']) for row in data['by_bp'].values())
    produced_fc = sum(
        max(0, row['produced']) * prices.get(bp_id, 0) for bp_id, row in data['by_bp'].items()
    )
    received_qty = sum(row['received'] for row in data['by_bp'].values())

    auto_sessions = list(
        ProductionSession.objects.select_for_update()
        .filter(node=session.node, date=session.date, auto_track=True)
    )
    theoretical_day = sum(s.theoretical_yield for s in auto_sessions)
    for s in auto_sessions:
        carry = s.lines.filter(source=ProductionSessionLine.Source.CARRYOVER).aggregate(t=Sum('quantity'))['t'] or 0
        if s.pk == session.pk:
            s.total_fc_produced = produced_fc
            s.total_breads = carry + produced_qty + received_qty
            s.yield_gap = produced_fc - theoretical_day
        elif s.is_closed:
            s.total_fc_produced = 0
            s.total_breads = carry
            s.yield_gap = 0
        else:
            continue
        s.save(update_fields=['total_fc_produced', 'total_breads', 'yield_gap'])
        if s.pk == session.pk:
            session.total_fc_produced = s.total_fc_produced
            session.total_breads = s.total_breads
            session.yield_gap = s.yield_gap
    data['theoretical_day'] = theoretical_day
    data['produced_qty'] = produced_qty
    data['produced_fc'] = produced_fc
    return data


# ---------------------------------------------------------------------------
# BUG-1074 (remarque.md l.516, plan A-4) : clôture automatique de la fournée
# ---------------------------------------------------------------------------

def _auto_close_notify(node, day, title_prefix, message, severity):
    """Notification dédupliquée : une seule par boulangerie, jour et motif tant qu'elle n'est pas lue."""
    from core.models import SystemNotification
    from core.utils import create_notification

    title = f"{title_prefix} — {node.code} {day}"
    if SystemNotification.objects.filter(title=title, node_origin=node.code, is_read=False).exists():
        return None
    return create_notification(title=title, message=message, severity=severity, node_origin=node.code)


def auto_close_day(node, day, now=None, user=None, grace_minutes=None, require_switch=True):
    """
    BUG-1074 : clôture automatique des fournées encore ouvertes de la journée
    `day` de `node`, une fois l'heure de clôture (`Node.handover_time`) passée.
    IDEMPOTENTE (une session close n'est jamais retouchée, les notifications sont
    dédupliquées). Aucun service d'arrière-plan : appelée paresseusement
    (`shift-end-status`) et par la commande `auto_close_sessions`.

    Même effet que l'action `close` (`_close_production_session`) sans saisie :
      - le reste du jour de chaque catégorie = stock physique courant, comme la
        clôture forcée de fin de créneau (BUG-155/158 ; plafonné à 0 pour une
        fournée par sacs) ; AUCUN prix n'est saisi ni inventé ;
      - AUCUNE saisie du gérant n'est écrasée : un reste (`REMAINING`) déjà
        saisi sur la session, ou déjà déclaré ce jour par une autre équipe
        (instantané du jour), est conservé tel quel ;
      - la réconciliation (NV, déclassés, sorties gratuites) saisie par le gérant
        reste en base (`BreadDisposal`) et s'affiche dans la clôture journalière ;
        une notification demande de la compléter si elle est vide.
    Hypothèses prudentes (documentées, à valider par le client, Q-053) :
      - délai de grâce `SHIFT_END_GRACE_MINUTES` (30 min) après l'heure de
        clôture, pour laisser la modale du gérant s'afficher (BUG-156) ;
      - ne pas clôturer une fournée dont la journée n'a AUCUNE livraison, ni une
        fournée à ZÉRO sac (par sacs) / sans production déclarée : signalées par
        notification, laissées ouvertes ;
      - active seulement si la boulangerie a activé le mécanisme d'heure de
        clôture (`block_sales_after_closure`, l'interrupteur par boulangerie de
        BUG-973), sinon l'heure de relève par défaut (12:00) clôturerait des
        boulangeries qui ne l'ont pas configurée (`require_switch=False` pour passer outre) ;
      - BUG-1130 : la journée `day` (midi à midi) se termine à l'heure de clôture du
        lendemain ; toutes ses fournées ouvertes sont alors concernées.
    Retourne `{'due': bool, 'closed': [pk], 'skipped': [{'session','team','reason'}]}`.
    """
    from datetime import timedelta
    from sales.models import Invoice
    from core.utils import log_activity
    from core.workday import business_day_bounds, work_date_for as _work_date_for, _local_instant
    from .views import (  # import local : views importe ce module
        SHIFT_END_GRACE_MINUTES, _close_production_session, _current_bread_stocks, _suggested_qty,
    )

    result = {'due': False, 'closed': [], 'skipped': []}
    if node is None or getattr(node, 'code', None) == 'SIEGE':
        return result
    if require_switch and not node.block_sales_after_closure:
        return result
    local_now = _local_instant(now)
    # BUG-1130 (journée de midi à midi) : la journée `day` se termine à l'heure de
    # clôture du lendemain ; ce n'est qu'alors que ses fournées ouvertes sont dues.
    if day > _work_date_for(node, local_now):
        return result
    closure_at = business_day_bounds(node, day)[1]
    grace = SHIFT_END_GRACE_MINUTES if grace_minutes is None else grace_minutes
    if local_now < closure_at + timedelta(minutes=grace):
        return result
    result['due'] = True

    candidates = list(
        ProductionSession.objects.filter(node=node, date=day, is_closed=False).order_by('team', 'created_at')
    )
    if not candidates:
        return result

    has_delivery = Invoice.objects.filter(
        node=node, status=Invoice.Status.DELIVERED, is_debt_repayment=False,
        **delivered_on_work_date_filter(node, day),
    ).exists()

    closed_sessions = []
    for session in candidates:
        if not has_delivery:
            reason = "aucune livraison ce jour"
        elif session.auto_track and not session.flour_sacks_used:
            reason = "fournée à zéro sac"
        elif not session.auto_track and not session.lines.exists():
            reason = "aucune production déclarée"
        else:
            reason = None
        if reason:
            result['skipped'].append({'session': session.pk, 'team': session.team, 'reason': reason})
            continue

        with transaction.atomic():
            locked = ProductionSession.objects.select_for_update().get(pk=session.pk)
            if locked.is_closed:
                continue  # clôturée entre-temps (gérant ou requête concurrente)
            # Restes déjà déclarés ce jour par une AUTRE session : jamais écrasés.
            other_declared = set(
                DailyBreadStockSnapshot.objects.filter(node=node, date=day)
                .exclude(team=locked.team).values_list('bread_price_id', flat=True)
            ) | set(
                BreadDisposal.objects.filter(
                    node=node, session__date=day, disposal_type=BreadDisposal.DisposalType.REMAINING,
                ).exclude(session=locked).values_list('bread_price_id', flat=True)
            )
            own_declared = set(
                locked.disposals.filter(disposal_type=BreadDisposal.DisposalType.REMAINING)
                .values_list('bread_price_id', flat=True)
            )
            stocks = _current_bread_stocks(node)
            entries = [
                (bs.bread_price_id, _suggested_qty(bs, locked)) for bs in stocks
                if bs.bread_price_id not in other_declared and bs.bread_price_id not in own_declared
            ]
            entry_ids = {e[0] for e in entries}
            negatives = [
                bs for bs in stocks
                if bs.bread_price_id in entry_ids and _suggested_qty(bs, locked) < 0
            ]
            _close_production_session(
                locked, entries, user, record_snapshot=True, snapshot_exclude=other_declared,
            )
            log_activity(
                user, AUTO_CLOSE_ACTION,
                f"{node.code} Éq.{locked.team} {day} : fournée clôturée automatiquement à "
                f"l'heure de clôture ({node.handover_time.strftime('%H:%M')}).",
                node_origin=node.code,
            )
            if negatives:
                _auto_close_notify(
                    node, day, "Stock de pain négatif à la clôture automatique",
                    "Reste du jour enregistré avec une valeur négative pour "
                    + ", ".join(f"{bs.bread_price} ({bs.qty_available})" for bs in negatives)
                    + " ; le stock n'a pas été corrigé, écart à investiguer.",
                    'WARNING',
                )
        result['closed'].append(locked.pk)
        closed_sessions.append(locked)

    if closed_sessions:
        reconciled = BreadDisposal.objects.filter(node=node, session__date=day).exclude(
            disposal_type=BreadDisposal.DisposalType.REMAINING,
        ).exists()
        _auto_close_notify(
            node, day, "Fournée clôturée automatiquement",
            f"{len(closed_sessions)} fournée(s) du {day} clôturée(s) automatiquement à l'heure de "
            f"clôture." + ("" if reconciled else
                " La réconciliation des pains (Non vendu, Déclassés, Sorties gratuites) n'est pas "
                "renseignée : le gérant doit la compléter pour la Clôture journalière."),
            'INFO' if reconciled else 'WARNING',
        )
    if result['skipped']:
        details = "; ".join(f"Éq.{s['team']} : {s['reason']}" for s in result['skipped'])
        _auto_close_notify(
            node, day, "Fournée non clôturée automatiquement",
            f"Fournée(s) du {day} laissée(s) ouverte(s) ({details}) : à vérifier et clôturer par le gérant.",
            'WARNING',
        )
    return result


AUTO_CLOSE_ACTION = "Clôture automatique de la fournée"


def summarize_auto_closed(results):
    """BUG-1120 : `{jour: résultat auto_close_day}` -> `[{'date','teams','sessions'}]` (clôturés seulement)."""
    out = []
    for day, res in sorted(results.items()):
        if not res.get('closed'):
            continue
        sessions = list(ProductionSession.objects.filter(pk__in=res['closed']).order_by('team'))
        out.append({
            'date': day.isoformat(),
            'teams': sorted({s.team for s in sessions}),
            'sessions': [s.pk for s in sessions],
        })
    return out


def is_day_auto_closed(node, day):
    """BUG-1120 : une fournée de `day` a-t-elle été clôturée par `auto_close_day` ?
    S'appuie sur le journal d'activité déjà écrit (description « <code> Éq.<X> <jour> : ... »),
    donc persistant même si la notification a été lue."""
    from core.models import ActivityLog

    return ActivityLog.objects.filter(
        action=AUTO_CLOSE_ACTION, node_origin=node.code,
        description__startswith=f"{node.code} Éq.", description__contains=f" {day} :",
    ).exists()


def auto_close_due_days(node, now=None, user=None, **kwargs):
    """Applique `auto_close_day` à chaque jour (<= aujourd'hui) ayant encore une fournée ouverte."""
    from core.workday import work_date_for as _work_date_for

    today = _work_date_for(node, now)  # BUG-1130 : journée comptable de midi à midi
    days = sorted(set(
        ProductionSession.objects.filter(node=node, is_closed=False, date__lte=today)
        .values_list('date', flat=True)
    ))
    return {d: auto_close_day(node, d, now=now, user=user, **kwargs) for d in days}


# ---------------------------------------------------------------------------
# Q-021 (réponse client 2026-11-24) : personne à l'heure de clôture -> direction avertie
# ---------------------------------------------------------------------------

UNATTENDED_CLOSURE_TITLE = "Clôture sans personne connectée"
UNATTENDED_CLOSURE_ACTION = "Alerte clôture sans personne connectée"


def _node_staff_present_since(node, since):
    """Vrai si un agent de la boulangerie (rôle non-siège) a été actif depuis `since` :
    action journalisée ou connexion (`last_login`)."""
    from core.models import ActivityLog, User

    if ActivityLog.objects.filter(user__node=node, created_at__gte=since).exists():
        return True
    return User.objects.filter(node=node, is_active=True, last_login__gte=since).exists()


def notify_direction_if_unattended_closure(node, now=None):
    """
    Q-021 : à l'heure de clôture (`Node.handover_time`, rotation de 24 h), si personne de la
    boulangerie n'a été actif depuis cet instant et que la clôture de la période écoulée n'est pas
    validée, la direction ET le comptable (rôles siège) reçoivent UNE notification
    (`create_notification`, visible de tout le siège puisque filtrée par `node_origin`).

    IDEMPOTENTE : une seule notification par boulangerie et par période (clé = instant de
    clôture), même lue ou supprimée du côté lu ; aucun doublon quels que soient le nombre
    d'appels, la commande `auto_close_sessions` et `shift-end-status` partageant cette fonction.
    Sans effet : nœud SIEGE/inactif/hors rotation, heure non atteinte, clôture déjà validée.
    Retourne la notification créée ou `None`.
    """
    from datetime import date
    from core.models import SystemNotification
    from core.utils import create_notification, log_activity
    from core.workday import shift_period_start, _local_instant
    from treasury.closure_lock import closure_status
    from treasury.models import CashClosure

    if node is None or getattr(node, 'code', None) == 'SIEGE' or not node.is_active:
        return None
    if not node.team_rotation_enabled:
        return None
    local_now = _local_instant(now)
    closure_at = shift_period_start(node, local_now)  # dernier instant de clôture/relève atteint
    if local_now < closure_at:
        return None
    # Journée comptable qui vient de s'achever = celle dont la direction doit valider la clôture
    # (même source que le verrou de vente, `closure_lock.closure_status`, BUG-973/BUG-1130).
    ended_day = date.fromisoformat(closure_status(node, closure_at)['closure_date'])
    if CashClosure.objects.filter(node=node, date=ended_day, is_validated=True).exists():
        return None
    if _node_staff_present_since(node, closure_at):
        return None

    title = f"{UNATTENDED_CLOSURE_TITLE} — {node.code} {closure_at.strftime('%Y-%m-%d %H:%M')}"
    with transaction.atomic():
        if SystemNotification.objects.filter(title=title, node_origin=node.code).exists():
            return None
        notification = create_notification(
            title=title,
            message=(
                f"{node.code} : l'heure de clôture ({closure_at.strftime('%H:%M')}) est passée et personne de la "
                f"boulangerie n'est connecté ni actif. La clôture du {ended_day} et la relève des équipes "
                "attendent la boulangerie ; la direction et le comptable valident ensuite la clôture."
            ),
            severity='WARNING', node_origin=node.code,
        )
        log_activity(
            None, UNATTENDED_CLOSURE_ACTION,
            f"{node.code} : clôture de {closure_at.strftime('%H:%M')} ({ended_day}) sans personne connectée, direction avertie.",
            node_origin=node.code,
        )
    return notification
