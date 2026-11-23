"""
Verrou de vente après l'heure de clôture (BUG-973, remarque.md l.464/488).

Règle : si `Node.block_sales_after_closure` est actif, que l'heure de clôture
(`Node.handover_time`, ex-« heure de relève ») du jour de travail courant est
atteinte et que la clôture de caisse du jour n'est pas validée par la
direction, les ventes de la boulangerie sont bloquées. Lecture seule.
"""
from core.workday import work_date_for, _local_instant, _at

SALES_BLOCKED_DETAIL = "Ventes bloquées : clôture du jour en attente de validation par la direction."


def closure_status(node, now=None):
    """Dict {closure_hour, blocked, reason, closure_date, validated, enabled}."""
    if node is None or getattr(node, 'code', None) == 'SIEGE':
        return {'closure_hour': None, 'blocked': False, 'reason': '', 'closure_date': None,
                'validated': False, 'enabled': False}
    from .models import CashClosure
    local = _local_instant(now)
    day = work_date_for(node, local)
    validated = CashClosure.objects.filter(node=node, date=day, is_validated=True).exists()
    enabled = bool(node.block_sales_after_closure)
    reached = local >= _at(day, node.handover_time)
    blocked = enabled and reached and not validated
    if blocked:
        reason = SALES_BLOCKED_DETAIL
    elif not enabled:
        reason = ''
    elif validated:
        reason = "Clôture du jour validée."
    else:
        reason = "Heure de clôture non atteinte."
    return {
        'closure_hour': node.handover_time.strftime('%H:%M'),
        'blocked': blocked, 'reason': reason, 'closure_date': day.isoformat(),
        'validated': validated, 'enabled': enabled,
    }


def sales_blocked_for(node, now=None):
    """Helper unique : True si les ventes de `node` sont bloquées à `now`."""
    return closure_status(node, now)['blocked']
