from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import SyncableModel, Node, User


class TamperAlert(SyncableModel):
    """Recorded whenever an integrity check detects a broken hash chain."""

    class Severity(models.TextChoices):
        HIGH   = 'HIGH',   _('Critique')
        MEDIUM = 'MEDIUM', _('Modérée')
        LOW    = 'LOW',    _('Faible')

    node           = models.ForeignKey(Node, on_delete=models.CASCADE, related_name='tamper_alerts', verbose_name=_("Nœud"))
    detected_at    = models.DateTimeField(auto_now_add=True, verbose_name=_("Détecté le"))
    affected_model = models.CharField(max_length=100, verbose_name=_("Modèle affecté"))
    affected_id    = models.CharField(max_length=100, blank=True, verbose_name=_("ID affecté"))
    severity       = models.CharField(max_length=10, choices=Severity.choices, default=Severity.HIGH)
    description    = models.TextField(verbose_name=_("Description"))
    is_resolved    = models.BooleanField(default=False, verbose_name=_("Résolu"))
    resolved_by    = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='resolved_alerts',
        verbose_name=_("Résolu par")
    )
    resolved_at    = models.DateTimeField(null=True, blank=True, verbose_name=_("Résolu le"))

    class Meta:
        verbose_name = _("Alerte de Falsification")
        verbose_name_plural = _("Alertes de Falsification")
        ordering = ['-detected_at']

    def __str__(self):
        return f"[{self.severity}] {self.node} — {self.affected_model} @ {self.detected_at:%Y-%m-%d %H:%M}"


class BlockchainSnapshot(SyncableModel):
    """Daily snapshot of hash chain health for each node (created by integrity check)."""

    node             = models.ForeignKey(Node, on_delete=models.CASCADE, related_name='blockchain_snapshots')
    snapshot_date    = models.DateField(verbose_name=_("Date"))
    total_entries    = models.PositiveIntegerField(default=0, verbose_name=_("Entrées totales"))
    tampered_entries = models.PositiveIntegerField(default=0, verbose_name=_("Entrées falsifiées"))
    is_intact        = models.BooleanField(default=True, verbose_name=_("Chaîne intacte"))
    checked_by       = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='blockchain_checks'
    )

    class Meta:
        verbose_name = _("Instantané Blockchain")
        verbose_name_plural = _("Instantanés Blockchain")
        unique_together = [['node', 'snapshot_date']]
        ordering = ['-snapshot_date', 'node']

    def __str__(self):
        status = "OK" if self.is_intact else "COMPROMIS"
        return f"{self.node} {self.snapshot_date} — {status}"
