"""
Logique de promotion d'une clôture validée vers le Livre de Caisse Direction.

Extrait de `CashClosureViewSet.push_to_cashbook` pour être réutilisable
depuis le module de synchronisation (`sync.views`) : docs/architecture/SYNC.md
§0 — « le Livre de Caisse Direction reste une table exclusivement Cloud,
alimentée uniquement par le Cloud lui-même, à partir des clôtures remontées
depuis les nœuds ». Un nœud local ne pousse jamais de `CashbookEntry` ; il
pousse une `CashClosure` validée, et c'est le Cloud qui appelle cette même
fonction, que la clôture ait été saisie directement en ligne (via l'action
DRF `push_to_cashbook`) ou reçue par `/api/sync/push/`.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from core.models import Config
from core.utils import log_activity, create_notification
from .models import LocalExpense, FacturierReport, CashClosure, CashbookEntry
from .views import append_cashbook_entry  # fonction unique d'écriture (BUG-002)


class ClosureAlreadyPromotedError(Exception):
    """La clôture est déjà inscrite au Livre de Caisse Direction."""


class ClosureNotValidatedError(Exception):
    """La clôture doit être validée avant d'être inscrite au Livre de Caisse Direction."""


def promote_closure_to_cashbook(closure, acting_user=None, node_origin_override=None):
    """
    Inscrit une `CashClosure` validée au Livre de Caisse Direction (une
    seule fois). Lève `ValidationError` si la clôture n'est pas validée ou
    est déjà inscrite — l'appelant HTTP (`CashClosureViewSet.push_to_cashbook`)
    comme l'appelant de synchronisation (`sync.views`) traduisent cette
    exception en réponse appropriée (400 pour l'un, enregistrement
    `REJECTED` pour l'autre).
    """
    if not closure.is_validated:
        raise ClosureNotValidatedError(
            "La clôture doit être validée avant d'être inscrite au livre de caisse."
        )
    if closure.cashbook_entries.exists():
        raise ClosureAlreadyPromotedError(
            "Cette clôture est déjà inscrite au livre de caisse."
        )

    # Re-aggregate in case reports were generated after closure creation
    fresh_entries = FacturierReport.objects.filter(
        node=closure.node, date=closure.date
    ).aggregate(s=Sum('total_cash_sales'))['s'] or 0
    fresh_expenses = LocalExpense.objects.filter(
        node=closure.node, date=closure.date
    ).aggregate(s=Sum('amount'))['s'] or 0
    if fresh_entries != closure.total_entries or fresh_expenses != closure.total_expenses:
        closure.total_entries = fresh_entries
        closure.total_expenses = fresh_expenses
        closure.compute_physical_cash()
        closure.save(update_fields=['total_entries', 'total_expenses', 'net_cash', 'physical_cash_total', 'cash_gap'])

    piece = f"VC-{closure.node.code}-{closure.date.strftime('%Y%m%d')}"
    entry = append_cashbook_entry(
        node=closure.node,
        date=closure.date,
        piece_number=piece,
        imputation='7000',
        label=f"Versement Journalier {closure.node.code} {closure.node.name}",
        entry_amount=closure.net_cash if closure.net_cash >= 0 else Decimal('0'),
        exit_amount=abs(closure.net_cash) if closure.net_cash < 0 else Decimal('0'),
        source_closure=closure,
        node_origin=node_origin_override or closure.node.code,
    )

    log_activity(
        acting_user, "Écriture Livre de Caisse",
        f"Clôture {closure.node.code} {closure.date} inscrite au grand livre — Solde: {entry.running_balance:,.0f} FC.",
        node_origin='CLOUD'
    )
    return entry


def regenerate_facturier_reports(node, target_date):
    """
    (Ré)génère le(s) `FacturierReport` Niveau 1 pour `node`/`target_date` à
    partir des factures livrées ce jour-là.

    Extrait de `FacturierReportViewSet.generate` (logique inchangée) pour
    être réutilisable par le mécanisme de correction d'une livraison
    rétroactive (BUG-083, `handle_retroactive_delivery` ci-dessous) — c'est
    la même régénération explicite qu'un gérant déclencherait manuellement
    après avoir traité une facture additionnelle sur une vacation déjà
    rapportée (BUG-036), simplement déclenchée automatiquement côté serveur
    au lieu d'exiger une action manuelle en plus.

    Retourne la liste des `FacturierReport` créés/mis à jour (vide si aucune
    facture livrée ce jour-là).
    """
    from sales.models import Invoice, InvoiceLine
    from production.models import ProductionSession, ProductionSessionLine

    # BUG-178 : une régularisation (RG) n'est pas une vente (ni paiement, ni
    # dette, CM 0 — BUG-177) et un non-servi (NS) n'est jamais livré : ni
    # l'un ni l'autre ne doit compter dans le cash, le crédit, la valeur
    # vendue ni le détail par catégorie du rapport facturier.
    invoices = Invoice.objects.filter(
        node=node,
        delivered_at__date=target_date,
        status=Invoice.Status.DELIVERED,
    ).exclude(
        special_code__in=[Invoice.SpecialCode.RG, Invoice.SpecialCode.NS],
    ).select_related('facturier')

    if not invoices.exists():
        return []

    groups = defaultdict(lambda: {
        'facturier': None, 'team': '',
        'total_cash': Decimal('0'), 'total_credit': Decimal('0'),
    })
    for inv in invoices:
        key = (inv.facturier_id, inv.team)
        groups[key]['facturier'] = inv.facturier
        groups[key]['team'] = inv.team
        groups[key]['total_cash'] += inv.payment_amount
        credit = inv.order_total - inv.payment_amount
        groups[key]['total_credit'] += credit if credit > 0 else Decimal('0')

    teams_involved = {team for (_, team) in groups.keys()}
    team_detail = {}
    sac_value = Decimal(str(node.sac_value_fc)) if node.sac_value_fc else Decimal(str(Config.get_instance().sac_value_fc))
    for team in teams_involved:
        team_invoices = [inv for inv in invoices if inv.team == team]
        sold_by_category = defaultdict(int)
        for line in InvoiceLine.objects.filter(invoice__in=team_invoices).select_related('bread_price'):
            sold_by_category[line.bread_price.label] += line.quantity

        sessions = ProductionSession.objects.filter(node=node, team=team, date=target_date)
        sacks_consumed = sessions.aggregate(s=Sum('flour_sacks_used'))['s'] or Decimal('0')
        produced_by_category = defaultdict(int)
        for sline in ProductionSessionLine.objects.filter(session__in=sessions).select_related('bread_price'):
            produced_by_category[sline.bread_price.label] += sline.quantity

        theoretical_value = sacks_consumed * sac_value
        realized_value = sum((inv.order_total for inv in team_invoices), Decimal('0'))
        team_detail[team] = {
            'sacks_consumed': sacks_consumed,
            'breads_produced_by_category': dict(produced_by_category),
            'breads_sold_by_category': dict(sold_by_category),
            'sacks_value_gap': realized_value - theoretical_value,
        }

    created_reports = []
    for (_, team), data in groups.items():
        detail = team_detail.get(team, {})
        report, _ = FacturierReport.objects.update_or_create(
            node=node,
            facturier=data['facturier'],
            team=team,
            date=target_date,
            defaults={
                'total_cash_sales': data['total_cash'],
                'total_credit_sales': data['total_credit'],
                'theoretical_cash': data['total_cash'],
                'sacks_consumed': detail.get('sacks_consumed', Decimal('0')),
                'breads_produced_by_category': detail.get('breads_produced_by_category', {}),
                'breads_sold_by_category': detail.get('breads_sold_by_category', {}),
                'sacks_value_gap': detail.get('sacks_value_gap', Decimal('0')),
                'node_origin': node.code,
            },
        )
        created_reports.append(report)
    return created_reports


def handle_retroactive_delivery(invoice, node, team, delivery_date, acting_user=None):
    """
    BUG-083 (« ventes passées », décision client §4 — point non négociable) :
    appelé APRÈS COMMIT (voir `treasury.signals`) quand une livraison
    rétroactive (`delivered_at` antérieur à aujourd'hui) cible une vacation
    (node + team + delivery_date) pour laquelle un `FacturierReport` existe
    déjà — le signal `block_delivery_on_already_reported_vacation` (BUG-036)
    ne bloque plus ce cas quand `Config.allow_backdated_sales=True`, mais ne
    fait rien d'autre lui-même : c'est cette fonction qui répare la chaîne de
    rapports en aval, sans jamais toucher à une écriture déjà versée au
    Livre de Caisse Direction.

    Étapes :
    1. Régénère le `FacturierReport` Niveau 1 de la vacation concernée (ses
       totaux reflètent maintenant la facture ajoutée après coup).
    2. Si une `CashClosure` Niveau 2 existe pour ce jour :
       - si elle n'est PAS encore validée : met simplement à jour ses
         totaux (rien n'a encore été figé/poussé au Livre de Caisse).
       - si elle EST validée : la « réouvre » conceptuellement (ses totaux
         affichés sont recalculés) et, si elle a déjà été poussée au Livre
         de Caisse (donc verrouillée), appelle `record_backdated_correction`
         pour ajouter une écriture de correction plutôt que de modifier
         quoi que ce soit d'existant.
    3. Notifie la Direction/le Comptable dans tous les cas où une correction
       a été nécessaire sur un jour déjà clôturé/validé.
    """
    regenerate_facturier_reports(node, delivery_date)

    try:
        closure = CashClosure.objects.get(node=node, date=delivery_date)
    except CashClosure.DoesNotExist:
        return None

    fresh_entries = FacturierReport.objects.filter(
        node=node, date=delivery_date
    ).aggregate(s=Sum('total_cash_sales'))['s'] or Decimal('0')
    fresh_expenses = LocalExpense.objects.filter(
        node=node, date=delivery_date
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    if not closure.is_validated:
        # Rien n'a encore été figé : une simple remise à jour des totaux
        # suffit, le gérant verra les bons chiffres à la validation.
        closure.total_entries = fresh_entries
        closure.total_expenses = fresh_expenses
        closure.compute_physical_cash()
        closure.save(update_fields=['total_entries', 'total_expenses', 'net_cash', 'physical_cash_total', 'cash_gap'])
        return None

    already_promoted = closure.cashbook_entries.filter(is_correction=False).exists()
    if not already_promoted:
        # Validée mais jamais poussée au Livre de Caisse (immuable) : on peut
        # encore corriger directement les totaux de la clôture elle-même,
        # aucune CashbookEntry n'existe encore pour cette clôture.
        closure.total_entries = fresh_entries
        closure.total_expenses = fresh_expenses
        closure.compute_physical_cash()
        closure.save(update_fields=['total_entries', 'total_expenses', 'net_cash', 'physical_cash_total', 'cash_gap'])
        create_notification(
            title=f"Vente rétroactive — clôture validée recalculée ({node.code})",
            message=(
                f"Facture {invoice.receipt_number} livrée rétroactivement le {delivery_date} "
                f"({node.code}) : la clôture validée de ce jour a été recalculée "
                "(pas encore inscrite au Livre de Caisse, aucune correction nécessaire)."
            ),
            severity='WARNING', node_origin=node.code,
        )
        return None

    # Clôture validée ET déjà inscrite au Livre de Caisse (verrouillée) :
    # on ne touche JAMAIS à l'écriture déjà versée — le delta est calculé
    # PAR RAPPORT à `closure.net_cash` tel qu'il était au moment du push
    # (avant toute mise à jour ci-dessous).
    fresh_net_cash = fresh_entries - fresh_expenses
    delta = fresh_net_cash - closure.net_cash
    if delta == 0:
        return None

    entry = record_backdated_correction(
        closure=closure, delta=delta, invoice=invoice, acting_user=acting_user,
    )

    # « Réouverture conceptuelle » (décision client §4) : les totaux
    # AFFICHÉS de la clôture sont recalculés pour refléter la réalité (y
    # compris la vente ajoutée) — seule la `CashbookEntry` déjà versée reste
    # intouchée ; l'écart entre les deux est exactement la nouvelle écriture
    # de correction ci-dessus, jamais perdu ni masqué.
    closure.total_entries  = fresh_entries
    closure.total_expenses = fresh_expenses
    closure.compute_physical_cash()
    note = (
        f"[Réouverture rétroactive {timezone.localdate()}] Facture {invoice.receipt_number} "
        f"ajoutée après coup — totaux recalculés, écart {delta:+,.2f} FC versé en correction "
        f"({entry.piece_number})."
    )
    closure.notes = f"{closure.notes}\n{note}" if closure.notes else note
    closure.save(update_fields=[
        'total_entries', 'total_expenses', 'net_cash', 'physical_cash_total', 'cash_gap', 'notes',
    ])

    return entry


def record_backdated_correction(closure, delta, invoice, acting_user=None):
    """
    Ajoute une écriture de correction au Livre de Caisse Direction pour une
    `CashClosure` déjà validée ET déjà inscrite (verrouillée), SANS jamais
    modifier ou supprimer l'écriture d'origine déjà versée (BUG-083, point
    non négociable).

    Datée du jour RÉEL de la saisie (`timezone.localdate()`), jamais de la
    date rétroactive de la clôture corrigée : la chaîne de hash est
    construite par ordre d'ajout (`_get_last_balance`, treasury/views.py) —
    une écriture « datée dans le passé » casserait l'ordre de vérification
    (date, created_at) de `verify_cashbook_chain` par rapport à son
    `previous_hash` réel (le dernier bloc au moment de l'ajout, forcément
    plus récent). La date d'origine de la clôture corrigée reste traçable
    via `correction_reason`/`correction_source_invoice`/`source_closure`.
    """
    today = timezone.localdate()
    piece = f"CORR-{closure.node.code}-{closure.date.strftime('%Y%m%d')}-{today.strftime('%Y%m%d%H%M%S')}"
    reason = (
        f"Correction suite à vente rétroactive : facture {invoice.receipt_number} "
        f"({invoice.invoice_date}) livrée/ajoutée après la clôture déjà validée et "
        f"inscrite du {closure.date} ({closure.node.code}). Écart recalculé : {delta:+,.2f} FC."
    )
    entry = append_cashbook_entry(
        node=closure.node,
        date=today,
        piece_number=piece,
        imputation='7000-CORR',
        label=f"Correction rétroactive — Clôture {closure.node.code} {closure.date}",
        entry_amount=delta if delta > 0 else Decimal('0'),
        exit_amount=abs(delta) if delta < 0 else Decimal('0'),
        source_closure=closure,
        node_origin=closure.node.code,
        is_correction=True,
        correction_reason=reason,
        corrected_by=acting_user,
        correction_source_invoice=invoice,
    )

    create_notification(
        title=f"Correction Livre de Caisse — {closure.node.code}",
        message=(
            f"Clôture déjà validée du {closure.date} ({closure.node.code}) corrigée par une "
            f"NOUVELLE écriture ({entry.piece_number}, {delta:+,.2f} FC) suite à la facture "
            f"rétroactive {invoice.receipt_number}. Aucune écriture existante n'a été modifiée."
        ),
        severity='DANGER', node_origin=closure.node.code,
    )
    log_activity(
        acting_user, "Correction Livre de Caisse (vente rétroactive)",
        reason + f" Nouvelle écriture {entry.piece_number} — solde {entry.running_balance:,.0f} FC.",
        node_origin=closure.node.code,
    )
    return entry
