"""
Verrou de vente après l'heure de clôture (BUG-973, remarque.md l.464/488).

Règle : si `Node.block_sales_after_closure` est actif et que la clôture de caisse
de la journée comptable qui vient de se terminer (midi à midi, BUG-1130) n'est
pas validée par la direction, les ventes de la boulangerie sont bloquées.
Lecture seule.
"""
from core.workday import work_date_for, _local_instant, closure_time_for

# BUG-1303 (décision client Q-020) : la direction OU le comptable valide la clôture.
SALES_BLOCKED_DETAIL = ("Ventes bloquées : clôture du jour en attente de validation "
                        "par la direction ou le comptable.")


def closure_status(node, now=None):
    """
    Dict {closure_hour, blocked, reason, closure_date, validated, enabled}.

    BUG-1130 (journée de midi à midi, Q-018) : la journée D court de D à
    l'heure de clôture à D+1 à la même heure. Quand l'heure de clôture est
    atteinte, la journée en cours commence et la journée PRÉCÉDENTE vient de
    se terminer : c'est sa clôture (`closure_date` = date de journée
    comptable de la journée terminée) que la direction doit valider ; tant
    qu'elle ne l'est pas, les ventes sont bloquées (si l'interrupteur est actif).
    """
    if node is None or getattr(node, 'code', None) == 'SIEGE':
        return {'closure_hour': None, 'blocked': False, 'reason': '', 'closure_date': None,
                'validated': False, 'enabled': False}
    from datetime import timedelta
    from .models import CashClosure
    local = _local_instant(now)
    day = work_date_for(node, local) - timedelta(days=1)
    validated = CashClosure.objects.filter(node=node, date=day, is_validated=True).exists()
    enabled = bool(node.block_sales_after_closure)
    blocked = enabled and not validated
    if blocked:
        reason = SALES_BLOCKED_DETAIL
    elif not enabled:
        reason = ''
    else:
        reason = "Clôture de la journée précédente validée."
    return {
        'closure_hour': closure_time_for(node).strftime('%H:%M'),
        'blocked': blocked, 'reason': reason, 'closure_date': day.isoformat(),
        'validated': validated, 'enabled': enabled,
    }


def sales_blocked_for(node, now=None):
    """Helper unique : True si les ventes de `node` sont bloquées à `now`."""
    return closure_status(node, now)['blocked']
