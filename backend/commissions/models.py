from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import SyncableModel, Node
from clients.models import Client


class CommissionPeriod(SyncableModel):
    """Monthly commission calculation period for one bakery."""
    node      = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='commission_periods', verbose_name=_("Boulangerie"))
    month     = models.PositiveSmallIntegerField(verbose_name=_("Mois (1-12)"))
    year      = models.PositiveIntegerField(verbose_name=_("Année"))
    is_closed = models.BooleanField(default=False, verbose_name=_("Période clôturée"))
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Date de clôture"))

    class Meta:
        verbose_name = _("Période de Commissions")
        verbose_name_plural = _("Périodes de Commissions")
        unique_together = [['node', 'month', 'year']]
        ordering = ['-year', '-month', 'node__code']

    def __str__(self):
        return f"{self.node.code} — {self.month:02d}/{self.year}"

    def close(self):
        self.is_closed = True
        self.closed_at = timezone.now()
        self.save(update_fields=['is_closed', 'closed_at'])


class ClientCommission(SyncableModel):
    """
    Commission calculation for one client in one period.

    Formula (§2.3 CDC):
        CM Brute   = order_value × commission_rate
        Deductions = debt + social + prints + other
        Net        = (CM Brute + annual_bonus) − Total Deductions
    """
    period = models.ForeignKey(CommissionPeriod, on_delete=models.CASCADE, related_name='commissions', verbose_name=_("Période"))
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='commissions', verbose_name=_("Client"))

    # Base
    total_breads    = models.PositiveIntegerField(default=0, verbose_name=_("Total pains livrés (période)"))
    order_value     = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Valeur Commande Pains (FC)"))
    commission_rate = models.DecimalField(max_digits=4,  decimal_places=2, default='0.25', verbose_name=_("Taux Commission"))

    # Calculated
    commission_gross = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("CM Brute (FC)"))

    # Deductions
    deduction_debt    = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Retenue Dette (FC)"))
    deduction_social  = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Retenue Sociale (FC)"))
    deduction_prints  = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Frais Imprimés (FC)"))
    deduction_other   = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Retenues Diverses (FC)"))
    deduction_carte   = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Retenue CARTE 1% (FC)"))
    deduction_remise  = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Remise 0.1% (FC)"))
    total_deductions  = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total Retenues (FC)"))

    # BUG-122 (Q-002) : report de dette entre périodes — si `net_payable` est
    # négatif (retenues > CM) à la clôture d'une période, le découvert N'EST
    # JAMAIS remis à zéro ni réclamé immédiatement : il est repris comme
    # déduction supplémentaire sur la commission du MÊME client à la période
    # suivante, cumulatif, même logique que BP_client (CLAUDE.md §5.2).
    # Recalculé automatiquement par `compute()` à partir de la commission la
    # plus récente du même client sur le même nœud, précédant la période
    # courante (peu importe un trou, cf. CLAUDE.md §5.2 appliqué par analogie :
    # jamais remis à zéro).
    carried_debt_in = models.DecimalField(
        max_digits=14, decimal_places=2, default='0.00',
        verbose_name=_("Dette report de la période précédente (FC)"),
    )

    # Intermediate net values
    net_ordi  = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("NET/ORDI (CM − BP)"))
    net_carte = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("NET/CARTE (NET/ORDI − CARTE)"))

    # Annual bonus (0.025 × total pains livrés)
    annual_bonus            = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Remise Annuelle (FC)"))
    annual_bonus_incorporated = models.BooleanField(default=False, verbose_name=_("Remise annuelle incorporée"))

    # Net
    net_payable = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Net à Payer (FC)"))

    # Manual override (DIRECTION/GERANT)
    manuel_adjustment = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name=_("Ajustement Manuel (FC)"))
    manuel_notes      = models.TextField(blank=True, default='', verbose_name=_("Observation Ajustement"))

    # Payment tracking
    is_paid  = models.BooleanField(default=False, verbose_name=_("Payé"))
    paid_at  = models.DateTimeField(null=True, blank=True, verbose_name=_("Date de paiement"))
    paid_by  = models.CharField(max_length=100, blank=True, default='', verbose_name=_("Payé par"))
    notes    = models.TextField(blank=True, default='', verbose_name=_("Notes"))

    class Meta:
        verbose_name = _("Commission Client")
        verbose_name_plural = _("Commissions Clients")
        unique_together = [['period', 'client']]
        ordering = ['period', 'client__last_name']
        # BUG-066 : `FinancialYearViewSet.comparative()` (finance/views.py)
        # filtre `ClientCommission.objects.filter(period__year=year,
        # is_paid=True)`. Le FK `period` est déjà indexé par Django, mais pas
        # en combinaison avec `is_paid` — sur un volume de charge (24 000
        # factures/8 nœuds), ce filtre scannait la table complète.
        indexes = [
            models.Index(fields=['period', 'is_paid'], name='comm_clico_period_paid_idx'),
        ]

    def __str__(self):
        return f"{self.client.code} | {self.period} | Net : {self.net_payable} FC"

    def compute(self, annual_bonus_rate: float = 0.025):
        """
        Recalculate all commission fields from inputs.
        Operands are cast through Decimal(str(x)) because freshly-instantiated
        (unsaved-then-reused) instances carry Django's raw string field
        defaults (e.g. '0.00') rather than Decimal — direct arithmetic on
        those raises/concatenates instead of computing.

        Formula — alignée sur la pratique réelle constatée dans les classeurs
        Excel d'août 2026 (BUG-058, décision client du 2026-10-23, M. NDUNGA
        NSAYI PIERRE) : CARTE reste déduite du Net à Payer, mais REMISE
        (0,1 % du CM) ne l'est plus — elle est calculée et affichée (colonne
        présente dans les 3 classeurs vérifiés) mais jamais soustraite dans
        la formule NET A PAYER de ces classeurs. Ne pas confondre avec la
        remise annuelle de fidélité (`annual_bonus`, 0,025 × volume livré,
        CLAUDE.md §5.1/§5.3), mécanisme distinct qui reste incorporable à la
        liquidation.
            NET/ORDI  = commission_gross - deduction_debt
            CARTE     = commission_gross × 1%
            NET/CARTE = NET/ORDI - CARTE
            REMISE    = commission_gross × 0.1%  (calculée, affichée, NON déduite)
            NET_PAYABLE = NET/CARTE - social - prints - other - carried_debt_in
                          (or manuel_adjustment if set — le report n'est alors
                          PAS réappliqué : un ajustement manuel de la DIRECTION
                          est une décision explicite qui prévaut)

        BUG-122 (Q-002) : `carried_debt_in` est recalculé à chaque appel à
        partir de la commission la plus récente du même client sur le même
        nœud précédant strictement cette période (peu importe un éventuel
        trou de génération) : si son `net_payable` était négatif, la valeur
        absolue est reprise ici comme déduction supplémentaire — jamais
        remise à 0, jamais réclamée immédiatement au client (CLAUDE.md §5.2,
        même principe que BP_client appliqué par analogie).
        """
        order_value      = Decimal(str(self.order_value))
        commission_rate  = Decimal(str(self.commission_rate))
        deduction_debt   = Decimal(str(self.deduction_debt))
        deduction_social = Decimal(str(self.deduction_social))
        deduction_prints = Decimal(str(self.deduction_prints))
        deduction_other  = Decimal(str(self.deduction_other))

        self.commission_gross = order_value * commission_rate
        self.annual_bonus     = Decimal(str(self.total_breads)) * Decimal(str(annual_bonus_rate))

        self.deduction_carte  = round(self.commission_gross * Decimal('0.01'), 2)
        self.deduction_remise = round(self.commission_gross * Decimal('0.001'), 2)

        self.net_ordi  = self.commission_gross - deduction_debt
        self.net_carte = self.net_ordi - self.deduction_carte

        self.carried_debt_in = self._compute_carried_debt_in()
        carried_debt_in = Decimal(str(self.carried_debt_in))

        # BUG-058 : REMISE est calculée et affichée (`deduction_remise`,
        # conservée ci-dessus pour l'affichage) mais n'est plus déduite du
        # Net à Payer — ni dans `total_deductions`, ni dans `net_payable` —
        # conformément à la formule réelle des classeurs Excel d'août 2026
        # (décision client 2026-10-23). CARTE reste déduite.
        self.total_deductions = (
            deduction_debt + deduction_social + deduction_prints + deduction_other
            + self.deduction_carte + carried_debt_in
        )

        bonus = self.annual_bonus if self.annual_bonus_incorporated else Decimal('0')
        if self.manuel_adjustment is not None:
            self.net_payable = Decimal(str(self.manuel_adjustment)) + bonus
        else:
            self.net_payable = (
                self.net_carte - deduction_social - deduction_prints - deduction_other
                - carried_debt_in
                + bonus
            )

    def _compute_carried_debt_in(self) -> Decimal:
        """
        BUG-122 (Q-002) : montant de dette de commission reporté depuis la
        période précédente (même client, même nœud), jamais remis à zéro.
        Ignoré tant que `client_id`/`period_id` ne sont pas encore renseignés
        (instance en cours de construction hors contexte réel).
        """
        if not self.client_id or not self.period_id:
            return Decimal('0.00')
        current_year, current_month = self.period.year, self.period.month
        previous = (
            ClientCommission.objects
            .filter(client_id=self.client_id, period__node_id=self.period.node_id)
            .filter(
                models.Q(period__year__lt=current_year)
                | models.Q(period__year=current_year, period__month__lt=current_month)
            )
            .order_by('-period__year', '-period__month')
            .first()
        )
        if previous is None:
            return Decimal('0.00')
        previous_net = Decimal(str(previous.net_payable))
        if previous_net < 0:
            return -previous_net
        return Decimal('0.00')

    def mark_paid(self, paid_by: str = ''):
        self.is_paid = True
        self.paid_at = timezone.now()
        self.paid_by = paid_by
        self.save(update_fields=['is_paid', 'paid_at', 'paid_by'])
