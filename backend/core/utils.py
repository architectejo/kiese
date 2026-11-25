from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import ActivityLog, SystemNotification

User = get_user_model()

def log_activity(user, action, description, node_origin='CLOUD'):
    """
    Log a system action into the database.
    """
    user_display = ""
    if user:
        if hasattr(user, 'get_full_name'):
            user_display = user.get_full_name()
        else:
            user_display = str(user)
            
    return ActivityLog.objects.create(
        user=user if isinstance(user, User) else None,
        user_display=user_display,
        action=action,
        description=description,
        node_origin=node_origin
    )

def create_notification(title, message, severity='INFO', node_origin='CLOUD'):
    """
    Generate a system warning/notification alarm.
    """
    return SystemNotification.objects.create(
        title=title,
        message=message,
        severity=severity,
        node_origin=node_origin
    )


def validate_requested_date(requested_date, config, *, field_label: str, node=None,
                            allow_previous_day: bool = False):
    """
    BUG-083 (« ventes passées », remarque.md l.360) : règle serveur commune à
    toute date métier librement saisissable dans un payload — `invoice_date`/
    `delivered_at` (facturation, `sales/views.py`) et `date` de clôture de
    caisse (BUG-086, trésorerie, `treasury/views.py`).

    Déplacée depuis `sales/views.py::_validate_requested_date` (BUG-086) pour
    être partagée sans faire dépendre `treasury` de `sales` (ou l'inverse) —
    `core` est déjà une dépendance commune aux deux apps.

    - Une date future est TOUJOURS refusée, quel que soit le réglage.
    - Une date passée n'est acceptée que si `Config.allow_backdated_sales`
      est actif (sinon le comportement par défaut — refus — reste strictement
      celui d'avant ce ticket).

    BUG-161 (B3) : « aujourd'hui » = la date de travail du nœud
    (`core.workday.work_date_for`) : date locale hors rotation (comportement
    historique), journée de relève à relève en mode rotation — une date
    « future » est alors une date postérieure à la journée de travail
    courante. `node=None` : date locale.

    BUG-1130 (journée de midi à midi) : `allow_previous_day=True` accepte aussi la
    journée comptable qui vient de SE TERMINER (jour de travail - 1), même sans
    `allow_backdated_sales` : c'est la clôture normale de la journée, qui a lieu
    après la bascule de midi (sans cela, le verrou de vente après clôture et la
    clôture de la veille se bloqueraient mutuellement).

    Retourne un message d'erreur (str) si la date est invalide, sinon `None`.
    """
    from datetime import timedelta
    from .workday import work_date_for

    today = work_date_for(node)
    if requested_date > today:
        return f"{field_label} ne peut pas être une date future ({requested_date} > {today})."
    if allow_previous_day and requested_date == today - timedelta(days=1):
        return None
    if requested_date != today and not config.allow_backdated_sales:
        return (
            f"{field_label} antérieure à aujourd'hui refusée : la saisie de ventes "
            "passées est désactivée (Config.allow_backdated_sales)."
        )
    return None
