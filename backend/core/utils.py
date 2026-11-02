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


def validate_requested_date(requested_date, config, *, field_label: str):
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

    Retourne un message d'erreur (str) si la date est invalide, sinon `None`.
    """
    today = timezone.localdate()
    if requested_date > today:
        return f"{field_label} ne peut pas être une date future ({requested_date} > {today})."
    if requested_date != today and not config.allow_backdated_sales:
        return (
            f"{field_label} antérieure à aujourd'hui refusée : la saisie de ventes "
            "passées est désactivée (Config.allow_backdated_sales)."
        )
    return None
