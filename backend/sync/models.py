"""
Modèles de synchronisation Local ↔ Cloud — docs/architecture/SYNC.md.

Périmètre V1 (voir SYNC.md §11) :
- `DebtMovement` : journal additif immuable de mouvements de dette client
  (§2.2 du document). `Client.current_debt` est recalculé à partir de la
  somme de ces mouvements — jamais transporté/écrasé comme une valeur figée.
- `NodeAuthToken` : jeton de nœud (cahierDesCharges.md §6.3.1), distinct des
  JWT utilisateur, assigné depuis le siège (menu Nœuds).
- `SyncBatchLog` : journal des lots `push` déjà traités, pour l'idempotence
  d'un lot entier (rejeu après coupure avant réception de l'accusé).
- `SyncConflictLog` : conflits détectés, consultables/résolubles au siège.

`sync.OutboxBatch` (file d'attente locale côté poste desktop, SYNC.md §7.1)
n'est volontairement PAS implémenté ici : il vit côté client (Electron /
backend desktop packagé), hors du périmètre de ce dépôt backend Cloud.
"""

import hashlib
import random
import secrets
import time
import uuid

from django.conf import settings
from django.db import OperationalError, models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import SyncableModel, Node

# BUG-062 : même motif que `sync.services._WRITE_MAX_RETRIES` /
# `treasury.views._APPEND_MAX_RETRIES` — sous SQLite, la mise à jour
# `last_used_at` peut heurter "database is locked" dès 2 requêtes
# `/api/sync/*` strictement simultanées sur le même nœud, AVANT même
# d'atteindre la logique métier (déjà protégée) de `sync.services`. Non
# rattrapée, cette erreur remonterait comme un 500 brut au point
# d'authentification, qui ne fait pourtant qu'une mise à jour informative.
_AUTH_WRITE_MAX_RETRIES = 150


class DebtMovement(SyncableModel):
    """
    Mouvement de dette client — ligne immuable et additive.
    `Client.current_debt` = somme(DebtMovement.amount) pour ce client
    (voir sync.services.recompute_client_debt). Jamais mis à jour après
    création : toute correction se fait par un nouveau mouvement
    (kind=ADJUSTMENT), jamais par modification d'un mouvement existant.
    """

    class Kind(models.TextChoices):
        ORDER      = 'ORDER',      _('Commande à crédit')
        REPAYMENT  = 'REPAYMENT',  _('Remboursement BP')
        ADJUSTMENT = 'ADJUSTMENT', _('Ajustement (annulation, régularisation)')

    client = models.ForeignKey(
        'clients.Client', on_delete=models.PROTECT,
        related_name='debt_movements', verbose_name=_("Client")
    )
    invoice = models.ForeignKey(
        'sales.Invoice', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='debt_movements', verbose_name=_("Facture d'origine")
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name=_("Montant signé (FC)"),
        help_text=_("Positif = augmente la dette, négatif = la réduit.")
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, verbose_name=_("Type"))
    note = models.CharField(max_length=255, blank=True, default='', verbose_name=_("Note"))

    class Meta:
        verbose_name = _("Mouvement de dette client")
        verbose_name_plural = _("Mouvements de dette client")
        ordering = ['client', 'created_at']

    def __str__(self):
        return f"{self.client.code} | {self.get_kind_display()} | {self.amount} FC"


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


class NodeAuthToken(models.Model):
    """
    Jeton de nœud (cahierDesCharges.md §6.3.1) : authentifie une
    *machine* (le backend d'une boulangerie/poste desktop) sur les routes
    `/api/sync/*`, jamais un utilisateur. Distinct du JWT utilisateur.

    Le jeton en clair n'est **jamais** stocké ni journalisé : seul son hash
    SHA-256 est conservé (même principe qu'un token GitHub/API classique).
    Affiché une seule fois à sa création (voir `issue_for_node`).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.OneToOneField(
        Node, on_delete=models.CASCADE,
        related_name='auth_token', verbose_name=_("Boulangerie (nœud)")
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False, verbose_name=_("Empreinte du jeton"))
    issued_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Émis le"))
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='issued_node_tokens',
        verbose_name=_("Émis par")
    )
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Révoqué le"))
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Dernière utilisation"))

    class Meta:
        verbose_name = _("Jeton de nœud")
        verbose_name_plural = _("Jetons de nœud")
        ordering = ['node__code']

    def __str__(self):
        state = "révoqué" if self.revoked_at else "actif"
        return f"Jeton {self.node.code} ({state})"

    @property
    def is_active(self):
        return self.revoked_at is None

    @classmethod
    def issue_for_node(cls, node, issued_by=None):
        """
        Génère un nouveau jeton en clair pour ce nœud (révoque l'ancien s'il
        existe — un seul jeton actif par nœud à la fois) et renvoie
        (instance, jeton_en_clair). Le jeton en clair n'est renvoyé qu'une
        seule fois : à appeler uniquement depuis l'écran « Nœuds » du siège.
        """
        cls.objects.filter(node=node, revoked_at__isnull=True).update(revoked_at=timezone.now())
        raw_token = secrets.token_urlsafe(48)
        instance = cls.objects.create(
            node=node, token_hash=_hash_token(raw_token), issued_by=issued_by
        )
        return instance, raw_token

    @classmethod
    def authenticate(cls, raw_token):
        """Renvoie le NodeAuthToken actif correspondant, ou None."""
        if not raw_token:
            return None
        # BUG-062 : sous SQLite (pas de WAL ici), une transaction d'écriture
        # en cours sur une AUTRE connexion (ex. `/api/sync/push/` en train
        # d'écrire `DebtMovement`/`SyncBatchLog`) bloque aussi les LECTURES
        # tant qu'elle n'a pas commité — pas seulement les écritures. La
        # retentative doit donc couvrir la lecture du jeton elle-même, pas
        # seulement la mise à jour de `last_used_at` qui suit.
        last_exc = None
        token = None
        for _attempt in range(_AUTH_WRITE_MAX_RETRIES):
            try:
                token = cls.objects.select_related('node').get(
                    token_hash=_hash_token(raw_token), revoked_at__isnull=True
                )
                break
            except cls.DoesNotExist:
                return None
            except OperationalError as exc:
                last_exc = exc
                time.sleep(random.uniform(0.01, 0.08))
        else:
            # BUG-062 (réouverture) : jeton illisible après épuisement des
            # tentatives — c'est un échec TRANSITOIRE d'infrastructure
            # (verrou SQLite), jamais une preuve que le jeton est invalide.
            # Renvoyer `None` ici (comme avant correction) fait répondre
            # 401 « non authentifié » à l'appelant — indistinguable d'un
            # vrai jeton révoqué/erroné, ce qui a été observé en pratique
            # sous charge combinée (testeur-charge, 2026-10-23 :
            # `[401, 200, 200, ...]` sur un rejeu par ailleurs valide).
            # On signale ceci comme un cas distinct (`TransientSyncError`,
            # 503) : le nœud appelant sait alors qu'il doit réessayer,
            # plutôt que de croire son jeton révoqué.
            import logging
            logging.getLogger(__name__).warning(
                "NodeAuthToken.authenticate() : échec de la lecture du "
                "jeton après %s tentatives : %s", _AUTH_WRITE_MAX_RETRIES, last_exc,
            )
            from .exceptions import TransientSyncError
            raise TransientSyncError() from last_exc

        last_exc = None
        for _attempt in range(_AUTH_WRITE_MAX_RETRIES):
            try:
                with transaction.atomic():
                    cls.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
                break
            except OperationalError as exc:
                last_exc = exc
                time.sleep(random.uniform(0.01, 0.08))
        else:
            # `last_used_at` est purement informatif (SYNC.md) : on ne
            # bloque jamais l'authentification pour autant, mais on ne
            # masque pas non plus l'échec silencieusement — signalé au
            # journal applicatif sans faire remonter d'exception.
            import logging
            logging.getLogger(__name__).warning(
                "NodeAuthToken.authenticate() : échec de la mise à jour de "
                "last_used_at après %s tentatives (nœud %s) : %s",
                _AUTH_WRITE_MAX_RETRIES, token.node_id, last_exc,
            )
        return token

    def revoke(self):
        self.revoked_at = timezone.now()
        self.save(update_fields=['revoked_at'])


class SyncBatchLog(models.Model):
    """
    Journal des lots `push` déjà traités par le Cloud (idempotence de lot,
    SYNC.md §3.3/§3.6) : un `batch_id` rejoué après coupure renvoie le
    résultat déjà calculé sans ré-exécuter la logique métier.
    """

    class Status(models.TextChoices):
        OK      = 'OK',      _('Traité intégralement')
        PARTIAL = 'PARTIAL', _('Traité partiellement (rejets)')
        ERROR   = 'ERROR',   _('Erreur')

    batch_id = models.UUIDField(unique=True, verbose_name=_("Identifiant du lot"))
    node = models.ForeignKey(
        Node, on_delete=models.PROTECT, related_name='sync_batches', verbose_name=_("Nœud émetteur")
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OK, verbose_name=_("Statut"))
    result = models.JSONField(default=dict, verbose_name=_("Résultat (par enregistrement)"))
    received_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Reçu le"))

    class Meta:
        verbose_name = _("Journal de lot de synchronisation")
        verbose_name_plural = _("Journaux de lots de synchronisation")
        ordering = ['-received_at']

    def __str__(self):
        return f"{self.node.code} | {self.batch_id} | {self.status}"


class SyncConflictLog(models.Model):
    """
    Conflit ou rejet persistant détecté pendant la synchronisation
    (SYNC.md §5.2), consultable et résoluble manuellement au siège.
    """
    node = models.ForeignKey(
        Node, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sync_conflicts', verbose_name=_("Nœud concerné")
    )
    model_label = models.CharField(max_length=100, verbose_name=_("Modèle"))
    object_id = models.CharField(max_length=40, verbose_name=_("Identifiant de l'objet"))
    conflict_type = models.CharField(max_length=50, verbose_name=_("Type de conflit"))
    detail = models.TextField(blank=True, default='', verbose_name=_("Détail"))
    detected_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Détecté le"))
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Résolu le"))
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='resolved_sync_conflicts',
        verbose_name=_("Résolu par")
    )
    resolution_note = models.TextField(blank=True, default='', verbose_name=_("Note de résolution"))

    class Meta:
        verbose_name = _("Conflit de synchronisation")
        verbose_name_plural = _("Conflits de synchronisation")
        ordering = ['-detected_at']

    def __str__(self):
        return f"{self.model_label}#{self.object_id} — {self.conflict_type}"

    @property
    def is_resolved(self):
        return self.resolved_at is not None
