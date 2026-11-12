from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import SyncableModel, Node, BreadPrice
from clients.models import Client

# BUG-092/BUG-096 : CLAUDE.md §5.1 impose « VENTE SOLDE et VENTE CASH (prix à
# 75 %, CM = 0) ». Jamais implémenté — `InvoiceLine.save()` figeait toujours
# le prix plein du catalogue, quel que soit `Invoice.is_soldee`. Taux unique,
# appliqué en Decimal (jamais de float sur un montant, CLAUDE.md §4).
SOLDEE_PRICE_RATIO = Decimal('0.75')


class Invoice(SyncableModel):

    class Status(models.TextChoices):
        PENDING   = 'PENDING',   _('En attente de livraison')
        DELIVERED = 'DELIVERED', _('Livré')
        CANCELLED = 'CANCELLED', _('Annulé')

    class PaymentType(models.TextChoices):
        CASH   = 'CASH',   _('Comptant')
        CREDIT = 'CREDIT', _('Crédit')

    class SpecialCode(models.TextChoices):
        NONE = '',   _('—')
        NV   = 'NV', _('Nouveau client')
        RG   = 'RG', _('Régularisation')
        NS   = 'NS', _('Non Servi')

    node      = models.ForeignKey(Node,   on_delete=models.PROTECT, related_name='invoices', verbose_name=_("Boulangerie"))
    client    = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='invoices', null=True, blank=True, verbose_name=_("Client"))
    facturier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='invoices_as_facturier',
        verbose_name=_("Facturier")
    )
    livreur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='invoices_as_livreur',
        verbose_name=_("Livreur")
    )
    team = models.CharField(max_length=1, blank=True, default='', verbose_name=_("Équipe"))

    status       = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING, verbose_name=_("Statut"))
    payment_type = models.CharField(max_length=10, choices=PaymentType.choices, default=PaymentType.CASH, verbose_name=_("Mode de paiement"))

    # Balance de Paiement (BP)
    debt_before     = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Balance Antérieure (FC)"))
    order_total     = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Valeur Commande (FC)"))
    payment_amount  = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Versement du Jour (FC)"))
    debt_after      = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Nouvelle Balance (FC)"))
    commission_rate = models.DecimalField(max_digits=4,  decimal_places=2, default='0.25',  verbose_name=_("Taux Commission"))
    is_soldee       = models.BooleanField(default=False, verbose_name=_("Vente Soldée"))
    # BUG-052 : remarque.md l.190 demande une case « vente sans commission de
    # 25 % » DISTINCTE de « Vente Soldée » — sur une facture NORMALE (prix
    # catalogue plein, BP suivie normalement), on veut pouvoir forcer CM=0
    # sans appliquer la remise de prix à 75 % ni geler `debt_after`
    # (contrairement à `is_soldee`, voir `compute_debt_after()` ci-dessous et
    # `InvoiceLine.save()` : ce champ n'y est volontairement PAS testé).
    # Indépendant de `is_soldee` — les deux booléens sont combinables sans
    # incohérence de calcul (si `is_soldee=True`, la CM est déjà à 0 par ce
    # chemin ; `commission_exempt=True` en plus ne change rien de plus).
    commission_exempt = models.BooleanField(default=False, verbose_name=_("Exonérée de commission (CM=0)"))

    special_code       = models.CharField(max_length=2, choices=SpecialCode.choices, blank=True, default='', verbose_name=_("Code Spécial (NV/RG/NS)"))
    is_debt_repayment  = models.BooleanField(default=False, verbose_name=_("Remboursement BP"))

    # BUG-083 : `auto_now_add` retiré — la saisie d'une date antérieure
    # (« ventes passées », remarque.md l.360) exige que `invoice_date` soit
    # un champ éditable. `default=timezone.localdate` préserve le
    # comportement par défaut (date du jour) pour tout appelant qui ne
    # fournit pas explicitement de date — voir `InvoiceViewSet._create_once`
    # pour la validation serveur (jamais de date future ; date antérieure
    # exige `Config.allow_backdated_sales=True`).
    invoice_date = models.DateField(default=timezone.localdate, verbose_name=_("Date"))
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Date livraison"))

    receipt_number = models.CharField(max_length=30, blank=True, default='', verbose_name=_("N° Reçu"))

    # BUG-097 : correction/annulation d'une commande déjà enregistrée via
    # une nouvelle facture liée, « grande trace », jamais une mutation de
    # l'originale (remarque.md, « Réclamation des agents du client »,
    # point 4 ; décision coordinateur 2026-10-30). Précédents architecturaux
    # repris à l'identique : `sync.models.DebtMovement` (écriture additive
    # immuable) et `treasury.CashbookEntry.is_correction` (correction =
    # nouvelle écriture liée, jamais de mutation).
    #
    # `InvoiceLine.quantity` reste un `PositiveIntegerField` (aucune
    # migration de schéma risquée sur une table déjà en production) : les
    # lignes d'une facture d'ajustement portent la MAGNITUDE du changement
    # (quantités positives), et c'est `adjustment_sign` au niveau de la
    # facture entière qui porte le signe de l'opération, appliqué à
    # `order_total`/`payment_amount` (voir `InvoiceViewSet.adjust`).
    adjusts = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='adjustments', verbose_name=_("Facture d'origine (ajustement)")
    )
    is_adjustment = models.BooleanField(default=False, verbose_name=_("Facture d'ajustement"))
    adjustment_sign = models.SmallIntegerField(
        null=True, blank=True,
        choices=[(1, _('Augmentation')), (-1, _('Diminution'))],
        verbose_name=_("Signe de l'ajustement"),
    )

    class Meta:
        verbose_name = _("Facture")
        verbose_name_plural = _("Factures")
        ordering = ['-created_at']
        # BUG-064 : aucun index sur les colonnes effectivement filtrées —
        # `InvoiceViewSet.get_queryset()` (filterset_fields = node, status,
        # payment_type, invoice_date, client ; ordering par défaut
        # `-created_at`) et `finance.views` (`node_id + status +
        # invoice_date__month/year`, `invoice__invoice_date__year` via
        # `InvoiceLine`) dépassaient déjà l'objectif de référence de 500 ms
        # dès ~24 000 factures (testeur-charge, scénario volumétrie).
        # Composite sur (node, status, invoice_date) : couvre le filtre le
        # plus sélectif/fréquent (liste par boulangerie+statut+jour, et les
        # agrégats `finance.views` qui filtrent exactement ces 3 colonnes).
        # Index simple sur `created_at` : couvre le tri par défaut de la
        # liste non filtrée (`COUNT(*)` + `ORDER BY created_at` sur toute la
        # table).
        indexes = [
            models.Index(fields=['node', 'status', 'invoice_date'], name='sales_inv_node_stat_date_idx'),
            models.Index(fields=['created_at'], name='sales_inv_created_at_idx'),
        ]

    def __str__(self):
        client_label = str(self.client) if self.client_id else 'CLIENT DIVERS'
        return f"{self.receipt_number or str(self.id)[:8]} — {client_label} [{self.status}]"

    def compute_order_total(self):
        self.order_total = sum(
            line.line_total for line in self.lines.all()
        )
        return self.order_total

    @property
    def total_loss(self):
        """
        BUG-092 : perte = (prix catalogue − prix réellement facturé) × quantité,
        sommée sur toutes les lignes de la facture. Nulle pour une vente non
        soldée (prix facturé == prix catalogue). Calculée à la volée — jamais
        stockée — pour toujours refléter l'état réel des lignes.
        """
        total = Decimal('0.00')
        for line in self.lines.all():
            total += line.loss
        return total

    @property
    def debt_delta(self):
        """Variation de la BP (dette client) portée par cette facture.

        Source unique pour `create`, `cancel`, `cleanup_expired` et
        `compute_debt_after` (BUG-177) :
        - vente soldée : 0 (manquant passé en perte) ;
        - NS (non servi) : jamais de pains remis ; le client « peut décider
          de garder une dette » -> CREDIT : `order_total - payment_amount`,
          CASH : 0 ;
        - RG (régularisation) : 0 (comme le classeur : CM 0, ni paiement ni
          dette) ;
        - sinon : `order_total - payment_amount`.

        BUG-181 : une facture d'AJUSTEMENT (BUG-097) suit la nature de la
        facture d'origine (son propre `special_code` est vide) : ajustement
        d'une NS CASH ou d'une RG -> 0 ; NS CREDIT -> `order_total - paiement`
        (valeurs signées de l'ajustement).
        """
        code = self.special_code
        if self.is_adjustment and self.adjusts_id:
            code = self.adjusts.special_code
        if self.is_soldee:
            return Decimal('0.00')
        if code == self.SpecialCode.NS:
            if self.payment_type == self.PaymentType.CREDIT:
                return self.order_total - self.payment_amount
            return Decimal('0.00')
        if code == self.SpecialCode.RG:
            return Decimal('0.00')
        return self.order_total - self.payment_amount

    def compute_debt_after(self):
        self.debt_after = self.debt_before + self.debt_delta
        return self.debt_after

    def deliver(self, livreur, delivered_at=None):
        """Confirm physical delivery: stamp timestamp, update bread count.
        current_debt was already applied at invoice creation — do NOT overwrite it here.

        BUG-053 : la mise à jour du compteur de pains du client et
        `self.save()` (qui peut être bloqué par le signal `pre_save` de
        BUG-036 — vacation déjà rapportée) doivent réussir ou échouer
        ensemble. Sans `transaction.atomic()`, une livraison refusée
        laissait une mise à jour fantôme et durable du client alors
        qu'aucune livraison n'avait réellement eu lieu.

        BUG-083 : `delivered_at` optionnel — permet à `InvoiceViewSet.deliver`
        de confirmer une livraison à une date/heure antérieure (« ventes
        passées »), déjà validée côté vue (jamais de date future, jamais sans
        `Config.allow_backdated_sales=True`). Par défaut (`None`), comportement
        inchangé : horodatage réel de l'appel.
        """
        with transaction.atomic():
            self.livreur      = livreur
            self.status       = self.Status.DELIVERED
            self.delivered_at = delivered_at or timezone.now()

            if self.client_id:
                client = self.client
                client.total_breads_received += self.lines.aggregate(
                    total=models.Sum('quantity')
                )['total'] or 0
                client.refresh_category()
                client.save(update_fields=['total_breads_received', 'category'])
            self.save()


class InvoiceLine(models.Model):
    invoice    = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines', verbose_name=_("Facture"))
    bread_price = models.ForeignKey(BreadPrice, on_delete=models.PROTECT, verbose_name=_("Catégorie Pain"))
    quantity   = models.PositiveIntegerField(default=0, verbose_name=_("Quantité"))
    unit_price = models.PositiveIntegerField(default=0,  verbose_name=_("Prix Unitaire (FC)"))
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total Ligne (FC)"))

    class Meta:
        verbose_name = _("Ligne de Facture")
        verbose_name_plural = _("Lignes de Facture")

    def __str__(self):
        return f"{self.bread_price.label} × {self.quantity} = {self.line_total} FC"

    def save(self, *args, **kwargs):
        catalog_price = self.bread_price.unit_price
        if self.invoice.is_soldee:
            # BUG-092/BUG-096 : prix réduit à 75 % du catalogue pour une
            # VENTE SOLDE/VENTE CASH (CLAUDE.md §5.1). `unit_price` reste un
            # `PositiveIntegerField` (FC = montants entiers, cf. convention du
            # reste de l'app) — on calcule en Decimal puis on arrondit au
            # franc le plus proche (ROUND_HALF_UP) juste avant stockage.
            self.unit_price = int(
                (Decimal(catalog_price) * SOLDEE_PRICE_RATIO).quantize(
                    Decimal('1'), rounding=ROUND_HALF_UP
                )
            )
        else:
            self.unit_price = catalog_price
        self.line_total = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    @property
    def loss(self):
        """BUG-092 : perte générée par cette ligne par rapport au prix catalogue."""
        catalog_price = self.bread_price.unit_price
        return Decimal(catalog_price - self.unit_price) * self.quantity
