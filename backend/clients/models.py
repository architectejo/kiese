import random
import time

from django.conf import settings
from django.db import models, transaction, IntegrityError, OperationalError
from django.utils.translation import gettext_lazy as _
from core.models import SyncableModel, Node

# BUG-017 : nombre maximal de nouvelles tentatives en cas de collision malgré
# la réservation (ex. un code déjà occupé par une valeur explicite, comme
# `test_explicit_code_is_not_overwritten`) — même principe que
# `treasury.views.append_cashbook_entry` (BUG-002).
#
# BUG-112 : sous SQLite, une forte concurrence (ex. 16 créations de clients
# simultanées) ne produit pas seulement des `IntegrityError` (collision de
# code) mais aussi des `OperationalError: database is locked` — le délai
# d'attente par défaut du pilote sqlite3 (`OPTIONS['timeout']`, voir
# `kiese/settings.py`) peut être dépassé même quand le verrou est tenu
# brièvement par une autre transaction. Ces deux exceptions sont désormais
# retentées avec le même compteur, exactement comme
# `treasury.views.append_cashbook_entry` (BUG-002) le fait déjà pour le
# livre de caisse — on garde un seul style de retry dans le projet.
_CODE_GENERATION_MAX_RETRIES = 10


class ClientCodeSequence(models.Model):
    """Compteur persistant de codes client par préfixe de boulangerie.

    BUG-017 : lire le dernier `Client.code` existant (max + 1) ne constitue
    pas une réservation — deux appels consécutifs sans qu'aucun `Client` ne
    soit encore enregistré entre les deux renvoient le même numéro. Ce
    compteur est incrémenté atomiquement (`select_for_update` +
    `transaction.atomic()`) à chaque appel de `_generate_client_code`, qu'un
    `Client` soit effectivement sauvegardé ensuite ou non : l'incrémentation
    elle-même est la réservation, comme un numéro de séquence SQL classique.
    """
    node_code   = models.CharField(max_length=10, primary_key=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Séquence Code Client")
        verbose_name_plural = _("Séquences Codes Clients")

    def __str__(self):
        return f"{self.node_code} → {self.last_number}"


def _generate_client_code(node_code: str) -> str:
    """Generate the next reserved, unique client code (ex: K1-0001, K2-0042).

    Réserve atomiquement le numéro suivant dans `ClientCodeSequence` pour ce
    préfixe (verrou `select_for_update` sur la ligne du compteur, dans une
    transaction) : deux appels concurrents — ou deux appels successifs sans
    sauvegarde entre eux — obtiennent toujours des numéros différents.
    Garde-fou supplémentaire : si le code obtenu est déjà pris par un
    `Client` existant (ex. code explicite assigné manuellement, cf.
    `test_explicit_code_is_not_overwritten`), on avance encore la séquence
    jusqu'à trouver un code réellement libre.
    """
    prefix = f"{node_code}-"
    with transaction.atomic():
        seq, _created = ClientCodeSequence.objects.select_for_update().get_or_create(
            node_code=node_code
        )
        num = seq.last_number + 1
        code = f"{prefix}{num:04d}"
        while Client.objects.filter(code=code).exists():
            num += 1
            code = f"{prefix}{num:04d}"
        seq.last_number = num
        seq.save(update_fields=['last_number'])
    return code


class Client(SyncableModel):

    class Category(models.TextChoices):
        NORMAL = 'NORMAL', _('Normal')
        BEST   = 'BEST',   _('Meilleur Client')
        RISK   = 'RISK',   _('Client à Risque')

    class ClientType(models.TextChoices):
        DETAILLANT = 'DETAILLANT', _('Détaillant')
        GROSSISTE  = 'GROSSISTE',  _('Grossiste')
        REVENDEUR  = 'REVENDEUR',  _('Revendeur')

    code = models.CharField(
        max_length=20, unique=True,
        verbose_name=_("Code Client"),
        help_text=_("Généré automatiquement (ex: K1-0001)")
    )
    first_name = models.CharField(max_length=100, verbose_name=_("Prénom"))
    last_name  = models.CharField(max_length=100, verbose_name=_("Nom"))
    phone   = models.CharField(max_length=25, blank=True, default='', verbose_name=_("Téléphone"))
    address = models.TextField(blank=True, default='', verbose_name=_("Adresse"))
    photo   = models.ImageField(
        upload_to='clients/photos/', blank=True, null=True,
        verbose_name=_("Photo d'identité")
    )
    node = models.ForeignKey(
        Node, on_delete=models.PROTECT,
        related_name='clients',
        verbose_name=_("Boulangerie de rattachement")
    )
    cotisation_sociale = models.DecimalField(
        max_digits=10, decimal_places=2, default='3000.00',
        verbose_name=_("Cotisation Sociale (FC)")
    )
    commission_rate = models.DecimalField(
        max_digits=4, decimal_places=2, default='0.25',
        verbose_name=_("Taux commission"),
        help_text=_("0.25 = 25%, 0.30 = 30%")
    )
    credit_limit = models.DecimalField(
        max_digits=14, decimal_places=2, default='50000.00',
        verbose_name=_("Plafond Crédit (FC)")
    )
    current_debt = models.DecimalField(
        max_digits=14, decimal_places=2, default='0.00',
        verbose_name=_("Dette courante (FC)")
    )
    total_breads_received = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Total pains livrés (cumulé)")
    )
    category = models.CharField(
        max_length=10, choices=Category.choices,
        default=Category.NORMAL,
        verbose_name=_("Catégorie")
    )
    client_type = models.CharField(
        max_length=15, choices=ClientType.choices,
        default=ClientType.DETAILLANT,
        verbose_name=_("Type de client")
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Actif"))
    notes     = models.TextField(blank=True, default='', verbose_name=_("Notes internes"))

    class Meta:
        verbose_name = _("Client")
        verbose_name_plural = _("Clients")
        ordering = ['node__code', 'last_name', 'first_name']

    def __str__(self):
        return f"[{self.code}] {self.last_name} {self.first_name}"

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name}"

    def save(self, *args, **kwargs):
        if self.code:
            super().save(*args, **kwargs)
            return
        # BUG-017 : génère puis sauvegarde dans une transaction verrouillée,
        # avec retry sur IntegrityError si une autre création concurrente a
        # pris le même code entre la lecture et l'écriture.
        # BUG-112 : retry aussi sur OperationalError ("database is locked",
        # SQLite sous forte concurrence) — sinon ces tentatives échouent
        # définitivement sans jamais révéler une vraie collision de code.
        last_exc = None
        for _attempt in range(_CODE_GENERATION_MAX_RETRIES):
            try:
                with transaction.atomic():
                    self.code = _generate_client_code(self.node.code if self.node_id else 'XX')
                    super().save(*args, **kwargs)
                    return
            except IntegrityError as exc:
                self.code = ''
                last_exc = exc
                continue
            except OperationalError as exc:
                if 'locked' not in str(exc).lower():
                    raise
                self.code = ''
                last_exc = exc
                time.sleep(random.uniform(0.01, 0.05))
                continue
        raise last_exc

    def refresh_category(self, config=None):
        """Reclassify client based on current debt vs per-client credit_limit."""
        from core.models import Config
        if config is None:
            config = Config.get_instance()
        if self.current_debt >= self.credit_limit:
            self.category = self.Category.RISK
        elif self.total_breads_received >= config.best_client_threshold:
            self.category = self.Category.BEST
        else:
            self.category = self.Category.NORMAL


class SocialContribution(SyncableModel):
    """Monthly social fund contribution per client (Caisse Sociale)."""
    client  = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='social_contributions', verbose_name=_("Client"))
    node    = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='social_contributions', verbose_name=_("Boulangerie"))
    month   = models.PositiveSmallIntegerField(verbose_name=_("Mois"))
    year    = models.PositiveSmallIntegerField(verbose_name=_("Année"))
    amount  = models.DecimalField(max_digits=10, decimal_places=2, default='3000.00', verbose_name=_("Cotisation (FC)"))
    is_paid = models.BooleanField(default=False, verbose_name=_("Payé"))
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Date de paiement"))

    class Meta:
        unique_together = [['client', 'month', 'year']]
        ordering = ['year', 'month', 'client__last_name']
        verbose_name = _("Cotisation Sociale")
        verbose_name_plural = _("Cotisations Sociales")

    def __str__(self):
        return f"{self.client.code} | {self.year}-{self.month:02d} | {'Payé' if self.is_paid else 'Impayé'}"


class SocialDistribution(SyncableModel):
    """Annual social fund distribution event per bakery."""
    node      = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='social_distributions', verbose_name=_("Boulangerie"))
    year      = models.PositiveSmallIntegerField(verbose_name=_("Année"))
    tarif     = models.DecimalField(max_digits=10, decimal_places=2, default='700.00', verbose_name=_("Tarif par indice (FC)"))
    is_closed = models.BooleanField(default=False, verbose_name=_("Clôturée"))
    # `created_at` fourni par `SyncableModel` (même sémantique : auto_now_add).

    class Meta:
        unique_together = [['node', 'year']]
        ordering = ['-year', 'node__code']
        verbose_name = _("Distribution Sociale Annuelle")
        verbose_name_plural = _("Distributions Sociales Annuelles")

    def __str__(self):
        return f"{self.node.code} | {self.year} | Tarif: {self.tarif} FC"


class SocialDistributionLine(SyncableModel):
    """Per-client line within a SocialDistribution."""
    POSITION_CHOICES = [('present', _('Présent')), ('absent', _('Absent'))]
    FORM_CHOICES     = [('especes', _('Espèces')), ('colis', _('Colis'))]

    distribution = models.ForeignKey(SocialDistribution, on_delete=models.CASCADE, related_name='lines', verbose_name=_("Distribution"))
    client       = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='social_distribution_lines', verbose_name=_("Client"))
    indice       = models.PositiveSmallIntegerField(default=0, verbose_name=_("Indice (mois cotisés)"))
    total_social = models.DecimalField(max_digits=10, decimal_places=2, default='0.00', verbose_name=_("Total cotisations (FC)"))
    remise       = models.DecimalField(max_digits=10, decimal_places=2, default='0.00', verbose_name=_("Remise (indice × tarif)"))
    merite       = models.DecimalField(max_digits=10, decimal_places=2, default='0.00', verbose_name=_("Mérite (FC)"))
    total_payer  = models.DecimalField(max_digits=10, decimal_places=2, default='0.00', verbose_name=_("Total à recevoir (FC)"))
    position     = models.CharField(max_length=10, choices=POSITION_CHOICES, default='present', verbose_name=_("Présence"))
    form         = models.CharField(max_length=10, choices=FORM_CHOICES, default='especes', verbose_name=_("Forme de paiement"))

    class Meta:
        unique_together = [['distribution', 'client']]
        ordering = ['client__last_name']
        verbose_name = _("Ligne Distribution Sociale")
        verbose_name_plural = _("Lignes Distribution Sociale")

    def __str__(self):
        return f"{self.distribution} | {self.client.code} | {self.total_payer} FC"

    def compute(self):
        # BUG-018 : les opérandes sont systématiquement convertis via
        # Decimal(str(x)) — une instance créée via get_or_create(defaults=...)
        # sans passer `merite` garde la valeur par défaut brute du champ
        # Django (chaîne '0.00'), pas un Decimal, tant qu'elle n'est pas
        # relue en base. Même motif que ClientCommission.compute().
        from decimal import Decimal
        tarif        = Decimal(str(self.distribution.tarif))
        total_social = Decimal(str(self.total_social))
        merite       = Decimal(str(self.merite))
        self.remise      = self.indice * tarif
        self.total_payer = total_social + self.remise + merite
