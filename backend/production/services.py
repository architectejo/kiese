from django.db import transaction
from django.db.models import F

from core.workday import work_date_for, current_team
from .models import ProductionSession, ProductionSessionLine, _adjust_bread_stock


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
    BUG-306 (remarque.md 2026-11-19) : à la livraison d'une vente, ajoute la
    quantité de chaque catégorie de pain à la fournée en cours (lignes
    DECLARED + stock `qty_produced`) et recalcule ses totaux : l'avancement
    (valeur livrée / objectif sacs x valeur du sac) progresse à chaque vente.

    Ignorées : factures sans ligne (remboursement), « Non Servi », ajustements
    (corrections de commande, hors périmètre). Atomique ; `F()` sur les
    quantités. Retourne la session mise à jour, ou None.
    """
    from sales.models import Invoice

    if invoice.is_debt_repayment or invoice.is_adjustment:
        return None
    if invoice.special_code == Invoice.SpecialCode.NS:
        return None
    lines = list(invoice.lines.select_related('bread_price'))
    if not lines:
        return None

    with transaction.atomic():
        session = find_open_batch_for_sale(invoice.node, invoice.delivered_at)
        if session is None:
            return None
        for line in lines:
            if line.quantity <= 0:
                continue
            updated = ProductionSessionLine.objects.filter(
                session=session, bread_price=line.bread_price,
                source=ProductionSessionLine.Source.DECLARED,
            ).update(quantity=F('quantity') + line.quantity)
            if not updated:
                ProductionSessionLine.objects.create(
                    session=session, bread_price=line.bread_price, quantity=line.quantity,
                    source=ProductionSessionLine.Source.DECLARED,
                )
            _adjust_bread_stock(session.node, line.bread_price, produced=line.quantity)
        session.compute_totals(session.sac_value_fc_used)
        session.save(update_fields=[
            'total_breads', 'total_fc_produced', 'theoretical_yield', 'yield_gap',
            'breads_300', 'breads_400', 'breads_500', 'breads_1000', 'sac_value_fc_used',
        ])
    return session
