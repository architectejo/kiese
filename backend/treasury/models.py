from django.conf import settings
from django.db import models
from django.db.models import F, Max
from django.utils.translation import gettext_lazy as _

from core.models import SyncableModel, Node


class LocalExpense(SyncableModel):

    node        = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='local_expenses', verbose_name=_("Boulangerie"))
    gerant      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='local_expenses', verbose_name=_("Gérant"))
    description = models.CharField(max_length=255, verbose_name=_("Description"))
    amount      = models.DecimalField(max_digits=14, decimal_places=2, verbose_name=_("Montant (FC)"))
    category    = models.ForeignKey('core.ExpenseCategory', on_delete=models.PROTECT, related_name='local_expenses', verbose_name=_("Catégorie"))
    date        = models.DateField(verbose_name=_("Date"))

    class Meta:
        verbose_name = _("Dépense Locale")
        verbose_name_plural = _("Dépenses Locales")
        ordering = ['-date', 'node__code']
        # BUG-066 : `FinancialYearViewSet.comparative()` (finance/views.py)
        # filtre `LocalExpense.objects.filter(date__year=year)` — sur un
        # volume de charge (24 000 factures/8 nœuds), aucun index sur `date`
        # ne couvrait ce filtre, forçant un scan complet de la table.
        indexes = [
            models.Index(fields=['date'], name='treas_localexp_date_idx'),
        ]

    def __str__(self):
        return f"{self.node.code} | {self.date} | {self.description} — {self.amount} FC"


class FacturierReport(SyncableModel):
    """Level-1 cashier shift report validated by the Gérant."""
    node       = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='facturier_reports', verbose_name=_("Boulangerie"))
    facturier  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='facturier_reports', verbose_name=_("Facturier"))
    team       = models.CharField(max_length=1, blank=True, default='', verbose_name=_("Équipe"))
    date       = models.DateField(verbose_name=_("Date"))

    total_cash_sales   = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total Ventes Cash (FC)"))
    total_credit_sales = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total Ventes Crédit (FC)"))
    theoretical_cash   = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Espèces Théoriques (FC)"))

    is_validated = models.BooleanField(default=False, verbose_name=_("Validé par le gérant"))
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='validated_facturier_reports',
        verbose_name=_("Validé par")
    )
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Date validation"))

    # BUG-033 (remarque.md l.142) : détail par catégorie de pain de la
    # vacation (nœud + équipe + date), calculé à partir de
    # `production.ProductionSession`/`ProductionSessionLine` et des lignes
    # de facture livrées — pas seulement les totaux cash/crédit/théorique.
    sacks_consumed = models.DecimalField(
        max_digits=8, decimal_places=2, default='0.00',
        verbose_name=_("Sacs de farine consommés (vacation)")
    )
    breads_produced_by_category = models.JSONField(
        default=dict, blank=True,
        verbose_name=_("Pains produits par catégorie"),
        help_text=_("Dictionnaire {libellé catégorie: quantité produite} pour la vacation.")
    )
    breads_sold_by_category = models.JSONField(
        default=dict, blank=True,
        verbose_name=_("Pains vendus par catégorie"),
        help_text=_("Dictionnaire {libellé catégorie: quantité vendue} pour la vacation.")
    )
    sacks_value_gap = models.DecimalField(
        max_digits=14, decimal_places=2, default='0.00',
        verbose_name=_("Écart valeur sacs / ventes (FC)"),
        help_text=_(
            "Valeur réalisée par la vente moins la valeur théorique des sacs "
            "consommés (sacs × valeur du sac, remarque.md l.142). Convention "
            "alignée sur production.ProductionSession.yield_gap : positif = "
            "excédent, négatif = manquant."
        )
    )

    class Meta:
        verbose_name = _("Rapport Facturier")
        verbose_name_plural = _("Rapports Facturiers")
        ordering = ['-date', 'node__code']
        unique_together = [['node', 'facturier', 'team', 'date']]

    def __str__(self):
        return f"{self.node.code} | Éq.{self.team} | {self.date} | Cash: {self.total_cash_sales} FC"


class CashClosure(SyncableModel):
    """Level-2 daily closure by bakery Gérant with bill denomination breakdown."""
    node   = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='cash_closures', verbose_name=_("Boulangerie"))
    gerant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='cash_closures', verbose_name=_("Gérant"))
    date   = models.DateField(verbose_name=_("Date de clôture"))

    total_entries  = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total Entrées Cash (FC)"))
    total_expenses = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total Dépenses (FC)"))
    net_cash       = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Caisse Nette (FC)"))

    # Physical bill counts
    bills_20000 = models.PositiveIntegerField(default=0, verbose_name=_("Billets 20 000 FC"))
    bills_10000 = models.PositiveIntegerField(default=0, verbose_name=_("Billets 10 000 FC"))
    bills_5000  = models.PositiveIntegerField(default=0, verbose_name=_("Billets 5 000 FC"))
    bills_1000  = models.PositiveIntegerField(default=0, verbose_name=_("Billets 1 000 FC"))
    bills_500   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 500 FC"))
    bills_200   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 200 FC"))
    bills_100   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 100 FC"))
    bills_50    = models.PositiveIntegerField(default=0, verbose_name=_("Billets 50 FC"))

    physical_cash_total = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total Espèces Physiques (FC)"))
    cash_gap            = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Écart de Caisse (FC)"))

    is_validated     = models.BooleanField(default=False, verbose_name=_("Validé"))
    is_rejected      = models.BooleanField(default=False, verbose_name=_("Infirmé"))
    rejection_reason = models.TextField(blank=True, default='', verbose_name=_("Motif de rejet"))
    notes            = models.TextField(blank=True, default='', verbose_name=_("Observations"))

    class Meta:
        verbose_name = _("Clôture de Caisse")
        verbose_name_plural = _("Clôtures de Caisse")
        ordering = ['-date', 'node__code']
        unique_together = [['node', 'date']]

    def __str__(self):
        return f"{self.node.code} | {self.date} | Net: {self.net_cash} FC"

    def compute_physical_cash(self):
        """Compute physical cash total from bill denominations and derive gap."""
        self.physical_cash_total = (
            self.bills_20000 * 20000 + self.bills_10000 * 10000 +
            self.bills_5000  * 5000  + self.bills_1000  * 1000  +
            self.bills_500   * 500   + self.bills_200   * 200   +
            self.bills_100   * 100   + self.bills_50    * 50
        )
        self.net_cash = self.total_entries - self.total_expenses
        self.cash_gap = self.physical_cash_total - self.net_cash
        return self.physical_cash_total


class DisbursementVoucher(SyncableModel):
    """
    Bordereau de versement — sortie de caisse au niveau Direction, financée
    par l'argent consolidé reçu de toutes les boulangeries. Le comptage des
    billets est saisi en positif (comme CashClosure) ; c'est son impact sur
    le Livre de Caisse qui est négatif (CashbookEntry.exit_amount).
    """
    date        = models.DateField(verbose_name=_("Date"))
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='disbursement_vouchers', verbose_name=_("Émis par"))
    motif       = models.CharField(max_length=255, verbose_name=_("Motif / Objet"))
    beneficiary = models.CharField(max_length=150, blank=True, default='', verbose_name=_("Bénéficiaire"))

    # Physical bill counts — same denomination pattern as CashClosure
    bills_20000 = models.PositiveIntegerField(default=0, verbose_name=_("Billets 20 000 FC"))
    bills_10000 = models.PositiveIntegerField(default=0, verbose_name=_("Billets 10 000 FC"))
    bills_5000  = models.PositiveIntegerField(default=0, verbose_name=_("Billets 5 000 FC"))
    bills_1000  = models.PositiveIntegerField(default=0, verbose_name=_("Billets 1 000 FC"))
    bills_500   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 500 FC"))
    bills_200   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 200 FC"))
    bills_100   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 100 FC"))
    bills_50    = models.PositiveIntegerField(default=0, verbose_name=_("Billets 50 FC"))

    physical_cash_total = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Montant Total (FC)"))
    piece_number         = models.CharField(max_length=30, blank=True, default='', verbose_name=_("N° Pièce"))

    class Meta:
        verbose_name = _("Bordereau de Versement")
        verbose_name_plural = _("Bordereaux de Versement")
        ordering = ['-date', '-created_at']

    def compute_physical_cash(self):
        self.physical_cash_total = (
            self.bills_20000 * 20000 + self.bills_10000 * 10000 +
            self.bills_5000  * 5000  + self.bills_1000  * 1000  +
            self.bills_500   * 500   + self.bills_200   * 200   +
            self.bills_100   * 100   + self.bills_50    * 50
        )
        return self.physical_cash_total

    def __str__(self):
        return f"{self.piece_number} | {self.date} | {self.motif} — {self.physical_cash_total} FC"


class JournalEntry(models.Model):
    """
    Livre de Caisse quotidien par boulangerie (§5.1.4).
    Distinct du CashbookEntry (grand livre HQ blockchain-linked).
    """
    IMPUT_CHOICES = [
        ('CA',        _('Recettes du jour (CA)')),
        ('PAY_BLG',   _('Paye boulangers')),
        ('RATION',    _('Ration boulangers')),
        ('LIVRAISON', _('Livraison inter-site')),
        ('EAU',       _('Eau')),
        ('APPRO',     _("Frais d'appro")),
        ('DEPOT',     _('Dépôt rapport direction')),
        ('TRANSPORT', _('Transport')),
        ('CREDIT',    _('Crédit personnel')),
        ('PRIME',     _('Prime personnel')),
        ('CARBURANT', _('Essence / Mazout')),
        ('ACHAT',     _('Achat matériel / fourniture')),
        ('AUTRE',     _('Autre')),
    ]

    node        = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='journal_entries', verbose_name=_("Boulangerie"))
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='journal_entries', verbose_name=_("Saisi par"))
    date        = models.DateField(verbose_name=_("Date"))
    imput       = models.CharField(max_length=12, choices=IMPUT_CHOICES, verbose_name=_("Imputation"))
    label       = models.CharField(max_length=200, blank=True, default='', verbose_name=_("Libellé"))
    entry_amount    = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Entrée (FC)"))
    exit_amount     = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Sortie (FC)"))
    running_balance = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Solde Courant (FC)"))
    month_carried   = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Report Mois Précédent (FC)"))
    created_at  = models.DateTimeField(auto_now_add=True)

    # BUG-091 (remarque.md l.384-385) : rapprochement de l'imputation
    # « Recettes du jour (CA) » avec la Clôture Niveau 2 (`CashClosure`) du
    # même (nœud, date), déjà calculée automatiquement à partir des factures
    # réelles (`FacturierReport.total_cash_sales`). Seule l'imputation `CA`
    # est concernée : les autres (PAY_BLG, RATION, ...) restent des saisies
    # manuelles légitimes et ces champs restent à leurs valeurs par défaut.
    # Décision du coordinateur : jamais de blocage — on informe seulement.
    reconciled_closure = models.ForeignKey(
        CashClosure, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='journal_entries',
        verbose_name=_("Clôture rapprochée (imputation CA)")
    )
    is_reconciled = models.BooleanField(
        default=False,
        verbose_name=_("Rapproché avec la Clôture (imputation CA)"),
        help_text=_(
            "Vrai si une CashClosure existait pour ce (nœud, date) au moment de la "
            "saisie de cette écriture CA. Faux = « non rapprochée avec la Clôture », "
            "y compris pour toute autre imputation que CA."
        )
    )
    reconciliation_gap = models.DecimalField(
        max_digits=14, decimal_places=2, default='0.00',
        verbose_name=_("Écart de rapprochement (CA) (FC)"),
        help_text=_(
            "entry_amount saisi − CashClosure.total_entries de la clôture rapprochée. "
            "Non nul = avertissement journalisé (SystemNotification), jamais un blocage."
        )
    )

    class Meta:
        verbose_name = _("Écriture Journal de Caisse")
        verbose_name_plural = _("Journal de Caisse")
        ordering = ['date', 'created_at']

    def __str__(self):
        return f"{self.node.code} | {self.date} | {self.get_imput_display()} — {self.entry_amount or self.exit_amount} FC"


class DailySavings(models.Model):
    """
    Épargne journalière par boulangerie (§5.1.5).
    savings_amount = daily_revenue × savings_rate
    """
    node           = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='daily_savings', verbose_name=_("Boulangerie"))
    recorded_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='daily_savings', verbose_name=_("Saisi par"))
    date           = models.DateField(verbose_name=_("Date"))
    flour_sacks    = models.DecimalField(max_digits=6, decimal_places=2, default='0.00', verbose_name=_("Sacs farine (PROD)"))
    daily_revenue  = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Revenu du jour (FC)"))
    savings_rate   = models.DecimalField(max_digits=5, decimal_places=4, default='0.1580', verbose_name=_("Taux épargne"))
    savings_amount = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Montant Épargne (FC)"))
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Épargne Journalière")
        verbose_name_plural = _("Épargnes Journalières")
        ordering = ['-date', 'node__code']
        unique_together = [['node', 'date']]

    def __str__(self):
        return f"{self.node.code} | {self.date} | {self.savings_amount} FC"


class CashbookEntry(SyncableModel):
    """
    Level-3 central cashbook (Livre de Caisse Direction).
    Immutable once written; protected by SHA-256 hash chain.
    """
    node            = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='cashbook_entries', verbose_name=_("Boulangerie origine"))
    date            = models.DateField(verbose_name=_("Date"))
    piece_number    = models.CharField(max_length=30, verbose_name=_("N° Pièce"))
    imputation      = models.CharField(max_length=30, blank=True, default='', verbose_name=_("Imputation comptable"))
    label           = models.CharField(max_length=255, verbose_name=_("Libellé"))
    entry_amount    = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Entrée (FC)"))
    exit_amount     = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Sortie (FC)"))
    running_balance = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Solde Cumulé (FC)"))
    # BUG-198 : PROTECT (et non SET_NULL) — `source_closure` est couvert par le
    # hash (BUG-003) : supprimer une clôture versée passait ce champ à NULL et
    # cassait la chaîne. Le livre de caisse doit être supprimé AVANT ses
    # clôtures (core/reset.py respecte déjà cet ordre).
    source_closure  = models.ForeignKey(
        CashClosure, on_delete=models.PROTECT,
        null=True, blank=True, related_name='cashbook_entries',
        verbose_name=_("Clôture source")
    )
    source_bordereau = models.ForeignKey(
        DisbursementVoucher, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='cashbook_entries',
        verbose_name=_("Bordereau source")
    )

    # Blockchain integrity fields
    block_hash    = models.CharField(max_length=64, blank=True, default='', verbose_name=_("Hash SHA-256"))
    # BUG-002 : previous_hash est unique en base. Deux écritures concurrentes
    # qui liraient le même "dernier solde" avant que l'une des deux ait
    # validé ne peuvent plus produire deux blocs enfants du même parent
    # (fourche de la chaîne) : la seconde insertion échoue avec une
    # IntegrityError, que la vue retente après relecture du nouveau dernier
    # solde (voir treasury/views.py::append_cashbook_entry). C'est une
    # garantie au niveau base de données, complémentaire au
    # select_for_update() (qui, seul, n'est pas fiable sous SQLite — voir
    # rapport ingenieur-blockchain-2026-10-22.md).
    previous_hash = models.CharField(max_length=64, blank=True, default='', unique=True, verbose_name=_("Hash Précédent"))
    is_tampered   = models.BooleanField(default=False, verbose_name=_("Altéré (Alerte Blockchain)"))

    # BUG-199 : rang de chaînage. Le chaînage (`previous_hash`) suit l'ordre
    # d'AJOUT ; l'ancien tri (date, created_at) pouvait en différer (versement
    # de la journée J après la journée J+1 d'une autre boulangerie) et
    # produisait une fausse falsification. `chain_seq` (monotone, unique) est
    # l'ordre de référence unique pour l'écriture, le solde précédent et la
    # vérification. Hors formule de hash (les chaînes existantes restent
    # valides). Rempli par `save()` ; backfill par la migration 0016.
    chain_seq = models.BigIntegerField(null=True, blank=True, unique=True, editable=False, verbose_name=_("Rang dans la chaîne"))

    # BUG-083 : écriture de correction (« ventes passées », CLAUDE.md §5.5 —
    # point non négociable : aucune `CashbookEntry` existante n'est jamais
    # modifiée ou supprimée). Une livraison rétroactive qui tombe sur un
    # jour dont la `CashClosure` est déjà validée ET déjà inscrite au Livre
    # de Caisse (donc verrouillée) produit une NOUVELLE écriture, datée du
    # jour réel de la saisie (jamais de la date rétroactive — voir
    # `treasury.services.record_backdated_correction`), explicitement
    # marquée ainsi et traçable jusqu'à la facture d'origine.
    #
    # `correction_reason`/`corrected_by`/`correction_source_invoice` ne sont
    # volontairement PAS couverts par `compute_cashbook_entry_hash`
    # (treasury/hashing.py) : texte/référence d'audit libre, même statut que
    # `node_origin`/`is_synced`/`created_at`/`updated_at` (hérités de
    # SyncableModel), déjà hors formule de hash.
    #
    # BUG-085 : `is_correction`, lui, EST couvert par la formule de hash
    # depuis `HASH_FORMAT_VERSION = 3` — c'est une classification comptable
    # binaire (« ceci est une correction, pas un mouvement d'origine »), pas
    # une simple métadonnée d'audit : la laisser hors formule permettait de
    # la falsifier directement en base sans casser la chaîne. Migration de
    # données associée : `0014_bug085_recompute_hash_is_correction` (même
    # schéma que `0007_recompute_cashbook_hash` pour BUG-001).
    is_correction = models.BooleanField(default=False, verbose_name=_("Écriture de correction"))
    correction_reason = models.TextField(blank=True, default='', verbose_name=_("Motif de la correction"))
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='cashbook_corrections',
        verbose_name=_("Corrigé par")
    )
    correction_source_invoice = models.ForeignKey(
        'sales.Invoice', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='cashbook_corrections',
        verbose_name=_("Facture d'origine de la correction")
    )

    class Meta:
        verbose_name = _("Écriture Livre de Caisse")
        verbose_name_plural = _("Livre de Caisse Direction")
        ordering = ['-date', '-created_at']
        # BUG-066 : `FinancialYearViewSet.comparative()` (finance/views.py),
        # via `_cashflow_for_year`/`_balance_sheet_for_year`, filtre
        # `CashbookEntry.objects.filter(date__year=year)` et fait
        # `order_by('-date', '-created_at').first()` sur toute la table —
        # sans index sur `date`, ces deux opérations scannaient la table
        # complète (24 000 factures/8 nœuds en charge).
        indexes = [
            models.Index(fields=['date', 'created_at'], name='treas_cashbook_date_crea_idx'),
        ]

    def __str__(self):
        return f"{self.piece_number} | {self.date} | {self.label} | {self.running_balance} FC"

    # Ordre de chaînage de référence (BUG-199). Les lignes sans rang (cas
    # théorique avant backfill) sont considérées comme les plus anciennes.
    @staticmethod
    def chain_order():
        return [F('chain_seq').asc(nulls_first=True), 'date', 'created_at', 'pk']

    @staticmethod
    def chain_order_desc():
        return [F('chain_seq').desc(nulls_last=True), '-date', '-created_at', '-pk']

    @classmethod
    def chain_queryset(cls):
        return cls.objects.order_by(*cls.chain_order())

    def save(self, *args, **kwargs):
        if self._state.adding and self.chain_seq is None:
            last = CashbookEntry.objects.aggregate(m=Max('chain_seq'))['m'] or 0
            self.chain_seq = last + 1
        super().save(*args, **kwargs)


class CashbookHead(models.Model):
    """BUG-240 : ancre de tête de chaîne du Livre de Caisse (ligne unique).

    Mise à jour par `append_cashbook_entry` dans la même transaction que
    l'écriture : dernier hash, nombre d'écritures, code du nœud de la dernière.
    Permet de détecter la suppression directe de la dernière écriture, que le
    chaînage seul ne voit pas. Donnée locale, non synchronisée.
    """
    last_hash = models.CharField(max_length=64, blank=True, default='')
    entry_count = models.PositiveIntegerField(default=0)
    last_node_code = models.CharField(max_length=20, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Ancre du Livre de Caisse")

    def __str__(self):
        return f"Tête de chaîne : {self.entry_count} écriture(s)"


class DirectionCashCount(models.Model):
    """
    BUG-119 (Chantier A, analyse `data_kiese/D1-4...xlsx` — Livre de Caisse
    Direction réel) : comptage physique des billets au niveau Direction,
    avec calcul d'écart physique/théorique — même logique que `CashClosure`
    (Niveau 2, par boulangerie), mais au niveau du Livre de Caisse Direction
    consolidé (`CashbookEntry`, Niveau 3, CLAUDE.md §5.5).

    Décision de conception (documentée dans
    docs/qa/rapports/ingenieur-blockchain-2026-11-01-chantier-a-ecart-direction.md) :
    modèle SÉPARÉ, non couvert par `treasury.hashing.compute_cashbook_entry_hash`
    et non lié à la chaîne de blocs elle-même. Un comptage physique de billets
    est un CONTRÔLE ANNEXE (il constate un état à un instant donné, comme un
    inventaire) — il n'altère et ne doit jamais pouvoir altérer le solde, le
    chaînage ou le contenu d'une `CashbookEntry` déjà écrite. Étendre
    `CashbookEntry` elle-même (nouveaux champs dans le payload de hash,
    `HASH_FORMAT_VERSION = 4`) aurait au contraire fait entrer une donnée de
    contrôle, potentiellement répétée/corrigée dans le temps pour un même
    jour, dans la définition même de l'intégrité d'un mouvement d'argent —
    ce que CLAUDE.md §5.5 ne demande pas (seul le *mouvement* comptable est
    protégé par le chaînage, pas son contrôle physique). C'est exactement le
    même raisonnement qui a déjà exclu `correction_reason`/`corrected_by`/
    `correction_source_invoice` de la formule de hash (BUG-083/085, voir
    `treasury/hashing.py`) : un texte/contrôle d'audit annexe n'entre pas
    dans le chaînage, seule une classification comptable qui changerait le
    SENS d'un mouvement existant (`is_correction`) y entre.

    Rattaché à une DATE (comptage consolidé Direction, pas par boulangerie)
    plutôt qu'à une `CashbookEntry` précise : le comptage porte sur le solde
    cumulé théorique du Livre de Caisse Direction tel qu'il se présentait à
    cette date (dernière écriture connue à cette date ou avant), pas sur un
    mouvement isolé. `reference_entry` est conservé à titre de traçabilité
    (quelle écriture a servi de référence théorique), mais `theoretical_balance`
    est aussi dupliqué en dur sur ce modèle : `CashbookEntry` n'est jamais
    supprimée en fonctionnement normal (règle non négociable), mais si
    `reference_entry` devenait néanmoins inaccessible (FK `SET_NULL`, ex.
    purge RGPD improbable), le comptage historique reste lisible et auditable
    sans dépendre de cette ligne.
    """
    date       = models.DateField(unique=True, verbose_name=_("Date du comptage"))
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='direction_cash_counts',
        verbose_name=_("Compté par")
    )

    # Physical bill counts — same denomination pattern as CashClosure/DisbursementVoucher
    bills_20000 = models.PositiveIntegerField(default=0, verbose_name=_("Billets 20 000 FC"))
    bills_10000 = models.PositiveIntegerField(default=0, verbose_name=_("Billets 10 000 FC"))
    bills_5000  = models.PositiveIntegerField(default=0, verbose_name=_("Billets 5 000 FC"))
    bills_1000  = models.PositiveIntegerField(default=0, verbose_name=_("Billets 1 000 FC"))
    bills_500   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 500 FC"))
    bills_200   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 200 FC"))
    bills_100   = models.PositiveIntegerField(default=0, verbose_name=_("Billets 100 FC"))
    bills_50    = models.PositiveIntegerField(default=0, verbose_name=_("Billets 50 FC"))

    physical_cash_total = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total Espèces Physiques (FC)"))

    # Référence théorique — solde cumulé du Livre de Caisse Direction à
    # cette date (dernière CashbookEntry connue à `date` ou avant).
    reference_entry = models.ForeignKey(
        CashbookEntry, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='direction_cash_counts',
        verbose_name=_("Écriture de référence (solde théorique)")
    )
    theoretical_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default='0.00',
        verbose_name=_("Solde théorique (FC)"),
        help_text=_(
            "Copie figée de reference_entry.running_balance au moment du "
            "comptage (0 si aucune CashbookEntry n'existe encore)."
        )
    )
    cash_gap = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Écart de Caisse Direction (FC)"))
    notes    = models.TextField(blank=True, default='', verbose_name=_("Observations"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Comptage Caisse Direction")
        verbose_name_plural = _("Comptages Caisse Direction")
        ordering = ['-date']

    def __str__(self):
        return f"Comptage Direction | {self.date} | Écart: {self.cash_gap} FC"

    def compute_physical_cash(self):
        """Compute physical cash total from bill denominations and derive gap."""
        self.physical_cash_total = (
            self.bills_20000 * 20000 + self.bills_10000 * 10000 +
            self.bills_5000  * 5000  + self.bills_1000  * 1000  +
            self.bills_500   * 500   + self.bills_200   * 200   +
            self.bills_100   * 100   + self.bills_50    * 50
        )
        self.cash_gap = self.physical_cash_total - self.theoretical_balance
        return self.physical_cash_total
