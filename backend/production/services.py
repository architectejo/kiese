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
