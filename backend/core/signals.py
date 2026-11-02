from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out

from .models import Config, BreadPrice, Node
from .utils import log_activity, create_notification

User = get_user_model()

# ─── Auth Signals ────────────────────────────────────────────────────

@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    log_activity(
        user=user,
        action="Connexion",
        description=f"L'agent {user.username} s'est connecté au système.",
        node_origin=user.node.code if user.node else 'CLOUD'
    )
    create_notification(
        title="Connexion Agent",
        message=f"L'agent {user.get_full_name()} ({user.get_role_display()}) s'est connecté.",
        severity="INFO",
        node_origin=user.node.code if user.node else 'CLOUD'
    )


@receiver(user_logged_out)
def on_user_logout(sender, request, user, **kwargs):
    if user:
        log_activity(
            user=user,
            action="Déconnexion",
            description=f"L'agent {user.username} s'est déconnecté.",
            node_origin=user.node.code if user.node else 'CLOUD'
        )


# ─── User Signals ────────────────────────────────────────────────────

@receiver(post_save, sender=User)
def on_user_save(sender, instance, created, **kwargs):
    action = "Création Agent" if created else "Modification Agent"
    desc = f"Agent {instance.username} ({instance.get_role_display()}) enregistré." if created else f"Profil de l'agent {instance.username} mis à jour."
    
    log_activity(
        user=None, # System action
        action=action,
        description=desc,
        node_origin=instance.node.code if instance.node else 'CLOUD'
    )


# ─── Config Signals ──────────────────────────────────────────────────

@receiver(post_save, sender=Config)
def on_config_save(sender, instance, created, **kwargs):
    log_activity(
        user=None,
        action="Modification Configuration",
        description=f"La configuration globale a été mise à jour. Taux com. par défaut: {instance.default_commission_rate}, Plafond dette: {instance.debt_ceiling} FC.",
        node_origin='CLOUD'
    )
    create_notification(
        title="Configuration mise à jour",
        message="La configuration de la caisse centrale et des seuils a été modifiée par la Direction.",
        severity="WARNING",
        node_origin='CLOUD'
    )


# ─── BreadPrice Signals ───────────────────────────────────────────────

@receiver(post_save, sender=BreadPrice)
def on_breadprice_save(sender, instance, created, **kwargs):
    action = "Création Tarif Pain" if created else "Modification Tarif Pain"
    desc = f"Nouveau format {instance.label} enregistré à {instance.unit_price} FC." if created else f"Tarif du format {instance.label} mis à jour à {instance.unit_price} FC."
    
    log_activity(
        user=None,
        action=action,
        description=desc,
        node_origin='CLOUD'
    )
    create_notification(
        title="Mise à jour Grille Tarifaire",
        message=f"Le tarif pour {instance.label} est désormais verrouillé à {instance.unit_price} FC.",
        severity="SUCCESS",
        node_origin='CLOUD'
    )


# ─── Node Signals ────────────────────────────────────────────────────

@receiver(post_save, sender=Node)
def on_node_save(sender, instance, created, **kwargs):
    action = "Création Boulangerie" if created else "Modification Boulangerie"
    desc = f"Nœud de boulangerie {instance.code} ({instance.name}) créé." if created else f"Informations du nœud {instance.code} modifiées."
    
    log_activity(
        user=None,
        action=action,
        description=desc,
        node_origin=instance.code
    )
