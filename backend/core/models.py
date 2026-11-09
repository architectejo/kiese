"""
Core models — User, Node (Bakery), and global Config for ETS. KIESE.

All synchronizable models inherit from SyncableModel which provides
UUIDv4 primary keys and node_origin tracking to prevent ID collisions
in the future distributed/offline architecture.
"""

import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


# ─── Abstract Base for Synchronizable Entities ──────────────────────

class SyncableModel(models.Model):
    """
    Abstract base providing UUID primary key + node origin tracking.
    All business models that will eventually sync between nodes
    must inherit from this class.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Identifiant unique")
    )
    node_origin = models.CharField(
        max_length=10,
        default='CLOUD',
        verbose_name=_("Nœud d'origine"),
        help_text=_("Code du nœud ayant créé cet enregistrement (ex: K1, K2, CLOUD)")
    )
    is_synced = models.BooleanField(
        default=True,
        verbose_name=_("Synchronisé"),
        help_text=_("Indique si cet enregistrement a été synchronisé avec le Cloud")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Créé le"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Modifié le"))

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """
        Marque automatiquement l'enregistrement comme non synchronisé dès
        qu'il est créé ou modifié localement (docs/architecture/SYNC.md §7.1,
        CLAUDE.md §8 « Marquage is_synced=False à chaque création/modification
        locale »).

        Règles :
        - Un enregistrement dont le nœud d'origine est 'CLOUD' (créé/modifié
          directement au siège, ou objet descendu du Cloud puis ré-enregistré
          tel quel côté nœud) n'a rien à remonter : on ne le marque jamais
          `is_synced=False` pour ce seul fait.
        - Le traitement d'un lot `push` côté Cloud (sync.views) doit pouvoir
          accepter un enregistrement venant d'un nœud local SANS le remarquer
          `is_synced=False` juste parce qu'on vient de l'enregistrer au Cloud
          — il passe `_sync_bypass=True` explicitement dans ce cas précis.
        - Si l'appelant restreint l'écriture via `update_fields`, on ajoute
          `is_synced` à la liste pour que la nouvelle valeur soit réellement
          persistée (sinon Django ignore silencieusement les attributs hors
          de `update_fields`).
        """
        bypass = kwargs.pop('_sync_bypass', False)
        if not bypass and self.node_origin != 'CLOUD':
            self.is_synced = False
            update_fields = kwargs.get('update_fields')
            if update_fields is not None and 'is_synced' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['is_synced']
        super().save(*args, **kwargs)


# ─── Node (Bakery) ──────────────────────────────────────────────────

class Node(models.Model):
    """
    Represents a bakery (boulangerie) in the ETS. KIESE network.
    Each node is a physical point of sale and production.
    """

    class NodeCode(models.TextChoices):
        K1 = 'K1', _('K1 - TABORA')
        K2 = 'K2', _('K2 - COQ')
        K3 = 'K3', _('K3 - ATHENEE')
        K4 = 'K4', _('K4 - LOMA')
        K5 = 'K5', _('K5 - MPIANGU')
        K6 = 'K6', _('K6 - ZADIM')
        B1 = 'B1', _('B1 - KUMBI')
        B2 = 'B2', _('B2 - MPETE')

    code = models.CharField(
        max_length=5,
        unique=True,
        verbose_name=_("Code boulangerie"),
        help_text=_("Ex: K1, B2, K7... — libre, doit rester unique")
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_("Nom de la boulangerie")
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name=_("Adresse")
    )
    sac_value_fc = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name=_("Valeur théorique sac farine (FC)"),
        help_text=_("Valeur FC attendue par sac 50 kg pour cette boulangerie")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_("Indique si cette boulangerie est opérationnelle")
    )
    last_sync = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Dernière synchronisation")
    )
    team_a_start_time = models.TimeField(
        null=True, blank=True,
        verbose_name=_("Équipe A — heure de début"),
        help_text=_("Ex: 06:00. Laisser vide si le créneau n'est pas encore déclaré.")
    )
    team_a_end_time = models.TimeField(
        null=True, blank=True,
        verbose_name=_("Équipe A — heure de fin"),
        help_text=_("Ex: 13:00.")
    )
    team_b_start_time = models.TimeField(
        null=True, blank=True,
        verbose_name=_("Équipe B — heure de début"),
        help_text=_("Ex: 13:00.")
    )
    team_b_end_time = models.TimeField(
        null=True, blank=True,
        verbose_name=_("Équipe B — heure de fin"),
        help_text=_("Ex: 20:00.")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Boulangerie (Nœud)")
        verbose_name_plural = _("Boulangeries (Nœuds)")
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def active_team_at(self, when=None):
        """
        Retourne 'A', 'B' ou None selon l'heure donnée (par défaut l'heure
        courante) et les créneaux déclarés pour cette boulangerie.

        Hypothèse volontaire (remarque.md l.396, BUG-129) : un créneau
        d'équipe ne traverse JAMAIS minuit (ex. 06:00-13:00, 13:00-20:00).
        Aucune donnée réelle de `data_kiese/` ni aucun document de référence
        (CLAUDE.md §5.2 : « Équipes : A et B uniquement, pas de jour/nuit »)
        ne mentionne une équipe de nuit à cheval sur deux jours civils. Si
        cette hypothèse s'avère fausse pour une boulangerie donnée, le
        chantier BUG-130 (détermination automatique de l'équipe active devra
        la retravailler explicitement — ne pas la contourner silencieusement
        ici.

        Accepte un `datetime`, un `time`, ou None (= heure courante selon le
        fuseau du projet). Un créneau non déclaré (`None`) ne correspond
        jamais à l'heure testée. En cas de chevauchement entre A et B
        (configuration incohérente), l'équipe A est retournée en priorité.
        """
        from datetime import datetime as _datetime, time as _time
        from django.utils import timezone as _timezone

        if when is None:
            when = _timezone.localtime().time()
        elif isinstance(when, _datetime):
            when = _timezone.localtime(when).time() if _timezone.is_aware(when) else when.time()
        elif not isinstance(when, _time):
            raise TypeError("active_team_at() attend un datetime, un time ou None")

        def _in_range(t, start, end):
            if start is None or end is None:
                return False
            if start <= end:
                return start <= t < end
            # Créneau traversant minuit : non attendu (voir docstring),
            # mais géré sans planter si jamais configuré ainsi.
            return t >= start or t < end

        if _in_range(when, self.team_a_start_time, self.team_a_end_time):
            return 'A'
        if _in_range(when, self.team_b_start_time, self.team_b_end_time):
            return 'B'
        return None

    def is_sync_degraded(self, threshold_hours=None):
        """
        True si ce nœud n'a pas réussi de synchronisation Cloud récente
        (docs/architecture/SYNC.md §6 point H2, tranché par le client le
        2026-10-22 : réduire le plafond de crédit effectif à 80 % du plafond
        nominal pendant le mode hors-ligne prolongé).

        `last_sync` est renseigné par `sync.views` à chaque `handshake`/
        `push`/`pull` réussi pour ce nœud. Un nœud qui ne s'est **jamais**
        synchronisé (`last_sync` NULL) n'est PAS considéré dégradé par
        défaut : avant que la synchronisation (ou le poste desktop) ne soit
        réellement déployée, tous les nœuds parlent en direct et en continu
        à ce même serveur (le monolithe actuel joue à la fois le rôle de
        Cloud et de nœud local) — les traiter comme « hors-ligne depuis
        toujours » romprait silencieusement le comportement actuel du
        contrôle de plafond de crédit (CLAUDE.md §5.2) pour tout le monde.
        Seul un nœud qui a DÉJÀ synchronisé au moins une fois, puis a cessé
        de le faire au-delà du seuil, est considéré dégradé.
        """
        from django.utils import timezone
        if threshold_hours is None:
            threshold_hours = Config.get_instance().degraded_sync_threshold_hours
        if self.last_sync is None:
            return False
        return (timezone.now() - self.last_sync).total_seconds() > threshold_hours * 3600


# ─── Custom User ────────────────────────────────────────────────────

class User(AbstractUser):
    """
    Custom user with role-based access control and node assignment.
    Each user is tied to a specific bakery node (except ADMIN/DIRECTION).

    Note sync multi-nœuds : pour garder le même mot de passe entre un nœud
    local et le cloud après synchronisation, ne jamais transporter de mot de
    passe en clair. Le champ "password" hérité (AbstractUser) contient déjà
    un hash salé (PBKDF2) : le synchroniser tel quel (assigner directement
    user.password = hash_recu puis user.save()) reproduit le même mot de
    passe côté récepteur sans jamais l'exposer.
    """

    class Role(models.TextChoices):
        ADMIN = 'ADMIN', _('Administrateur Système')
        DIRECTION = 'DIRECTION', _('Direction Générale')
        COMPTABLE = 'COMPTABLE', _('Comptable')
        GERANT = 'GERANT', _('Gérant de Boulangerie')
        FACTURIER = 'FACTURIER', _('Facturier')
        LIVREUR = 'LIVREUR', _('Livreur')

    class Team(models.TextChoices):
        A = 'A', _('Équipe A')
        B = 'B', _('Équipe B')

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.FACTURIER,
        verbose_name=_("Rôle")
    )
    team = models.CharField(
        max_length=1,
        choices=Team.choices,
        blank=True,
        default='',
        verbose_name=_("Équipe"),
        help_text=_("Équipe A ou B pour les facturiers et livreurs")
    )
    node = models.ForeignKey(
        Node,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        verbose_name=_("Boulangerie assignée"),
        help_text=_("Boulangerie à laquelle l'utilisateur est affecté")
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name=_("Téléphone")
    )
    photo = models.ImageField(
        upload_to='users/photos/',
        blank=True,
        null=True,
        verbose_name=_("Photo de profil")
    )

    class Meta:
        verbose_name = _("Utilisateur")
        verbose_name_plural = _("Utilisateurs")
        ordering = ['role', 'last_name', 'first_name']

    def __str__(self):
        return f"{self.get_full_name()} ({self.get_role_display()})"

    @property
    def is_headquarters(self):
        """Returns True if user has HQ-level access (ADMIN, DIRECTION, COMPTABLE, or superuser)."""
        return self.is_superuser or self.role in (self.Role.ADMIN, self.Role.DIRECTION, self.Role.COMPTABLE)

    @property
    def can_access_all_nodes(self):
        """Returns True if user can view data across all bakeries."""
        return self.is_superuser or self.role in (self.Role.ADMIN, self.Role.DIRECTION, self.Role.COMPTABLE)


# ─── Global Configuration ───────────────────────────────────────────

class Config(models.Model):
    """
    Singleton configuration model controlling global platform behavior.
    Only one instance should exist (enforced at app level).
    """
    on_line = models.BooleanField(
        default=True,
        verbose_name=_("Site web public visible"),
        help_text=_(
            "Si True: le site web vitrine est visible au public. "
            "Si False: redirection automatique vers la page de login du Dashboard."
        )
    )

    # ── Business parameters ──
    default_commission_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0.25,
        verbose_name=_("Taux de commission par défaut"),
        help_text=_("Ex: 0.25 pour 25%, 0.30 pour 30%")
    )
    debt_ceiling = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=500000,
        verbose_name=_("Plafond de dette client (FC)"),
        help_text=_("Au-delà de ce montant, le client est classé 'à risque'")
    )
    best_client_threshold = models.PositiveIntegerField(
        default=1000,
        verbose_name=_("Seuil Meilleur Client (nombre de pains)"),
        help_text=_("Volume d'achat cumulé au-delà duquel un client est 'Meilleur Client'")
    )
    social_deduction_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0.00,
        verbose_name=_("Taux cotisation sociale"),
    )
    print_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name=_("Frais d'imprimés (FC)"),
    )
    annual_bonus_rate = models.DecimalField(
        max_digits=5,
        decimal_places=3,
        default=0.025,
        verbose_name=_("Taux remise annuelle"),
        help_text=_("Ex: 0.025 pour 2.5% du volume total de pains livrés")
    )

    # ── Production yield standard (monetary) ──
    sac_value_fc = models.PositiveIntegerField(
        default=200000,
        verbose_name=_("Valeur théorique d'un sac de farine (FC)"),
        help_text=_("Montant FC attendu par sac 50 kg. Ex: 200 000 FC = 200 pains à 1000 FC ou 400 pains à 500 FC.")
    )
    savings_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default='0.1580',
        verbose_name=_("Taux épargne journalière"),
        help_text=_("Ex: 0.1580 = 15,80% du CA journalier")
    )

    # ── BASSINS — volume thresholds (FC/month) ──
    bassin_grand = models.DecimalField(
        max_digits=14, decimal_places=2, default='5000000.00',
        verbose_name=_("Seuil Grand Format (FC)"),
    )
    bassin_inter_gm = models.DecimalField(
        max_digits=14, decimal_places=2, default='3000000.00',
        verbose_name=_("Seuil Inter G&M (FC)"),
    )
    bassin_inter_mpt = models.DecimalField(
        max_digits=14, decimal_places=2, default='1500000.00',
        verbose_name=_("Seuil Inter M&PT (FC)"),
    )
    bassin_moyen = models.DecimalField(
        max_digits=14, decimal_places=2, default='500000.00',
        verbose_name=_("Seuil Moyen (FC)"),
    )

    # kept for backward compat — no longer used in compute_totals
    flour_yield_standard = models.PositiveIntegerField(
        default=300,
        verbose_name=_("Rendement standard (pains par sac) — obsolète"),
    )

    # ── Synchronisation (docs/architecture/SYNC.md) ──
    degraded_sync_threshold_hours = models.PositiveIntegerField(
        default=24,
        verbose_name=_("Seuil (heures) avant mode dégradé"),
        help_text=_(
            "Au-delà de ce délai sans synchronisation Cloud réussie, un nœud "
            "local est considéré en mode dégradé : voir offline_credit_limit_ratio."
        )
    )
    offline_credit_limit_ratio = models.DecimalField(
        max_digits=3, decimal_places=2, default='0.80',
        verbose_name=_("Ratio plafond crédit en mode hors-ligne prolongé"),
        help_text=_(
            "Décision client du 2026-10-22 (SYNC.md §6, H2) : 0.80 = le plafond "
            "de crédit local effectif d'un client est réduit à 80% du plafond "
            "nominal tant que son nœud est en mode dégradé (voir Node.is_sync_degraded)."
        )
    )

    # ── BUG-083 : ventes passées (remarque.md l.360) ──
    allow_backdated_sales = models.BooleanField(
        default=False,
        verbose_name=_("Autoriser la saisie de ventes passées"),
        help_text=_(
            "Décision client du 2026-10-29 (BUG-083) : si True, un facturier/"
            "livreur peut choisir une date antérieure à aujourd'hui pour "
            "`invoice_date` et/ou `delivered_at`. Jamais de date future, "
            "quel que soit ce réglage. Modifiable uniquement par "
            "ADMIN/DIRECTION (voir core.views.ConfigView)."
        )
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Configuration Globale")
        verbose_name_plural = _("Configuration Globale")

    def save(self, *args, **kwargs):
        """Enforce singleton pattern — only one Config instance allowed."""
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of the singleton config."""
        pass

    @classmethod
    def get_instance(cls):
        """
        Get or create the singleton Config instance.

        `refresh_from_db()` après une création : les valeurs par défaut
        littérales (ex. `default='0.80'`) restent de simples chaînes sur
        l'instance Python tant qu'elles n'ont pas fait un aller-retour par
        la base (seule la lecture via le moteur SQL les convertit via
        `DecimalField.from_db_value`) — sans ce rafraîchissement, un calcul
        du type `client.credit_limit * config.offline_credit_limit_ratio`
        plante avec `TypeError` sur la toute première requête qui crée le
        singleton (ex. premier test, premier déploiement).
        """
        obj, created = cls.objects.get_or_create(pk=1)
        if created:
            obj.refresh_from_db()
        return obj

    def __str__(self):
        status = "EN LIGNE" if self.on_line else "DASHBOARD UNIQUEMENT"
        return f"Configuration Globale — {status}"


# ─── COLIS Distribution ─────────────────────────────────────────────

class ColisDistribution(models.Model):
    """Annual allocation of goods (rice, meat, cash) to bakery staff."""
    node              = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='colis_distributions', verbose_name=_("Boulangerie"))
    year              = models.PositiveSmallIntegerField(verbose_name=_("Année"))
    beneficiary_label = models.CharField(max_length=100, verbose_name=_("Bénéficiaire"))
    rice_sacks        = models.DecimalField(max_digits=6,  decimal_places=2, default='0.00', verbose_name=_("Sacs de riz"))
    rice_value        = models.DecimalField(max_digits=12, decimal_places=2, default='0.00', verbose_name=_("Valeur riz (FC)"))
    meat_kg           = models.DecimalField(max_digits=7,  decimal_places=2, default='0.00', verbose_name=_("Viande (kg)"))
    meat_value        = models.DecimalField(max_digits=12, decimal_places=2, default='0.00', verbose_name=_("Valeur viande (FC)"))
    cash_amount       = models.DecimalField(max_digits=12, decimal_places=2, default='0.00', verbose_name=_("Espèces (FC)"))
    total_value       = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', verbose_name=_("Total (FC)"))
    notes             = models.TextField(blank=True, default='', verbose_name=_("Notes"))
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Distribution COLIS Personnel")
        verbose_name_plural = _("Distributions COLIS Personnel")
        ordering = ['node__code', 'beneficiary_label']

    def __str__(self):
        return f"{self.node.code} — {self.beneficiary_label} ({self.year})"

    def compute_total(self):
        from decimal import Decimal
        self.total_value = (
            (self.rice_value  or Decimal('0')) +
            (self.meat_value  or Decimal('0')) +
            (self.cash_amount or Decimal('0'))
        )


# ─── Bread Price Grid ────────────────────────────────────────────────

class BreadPrice(models.Model):
    """
    Bread price categories. Locked by default (only ADMIN/DIRECTION can
    modify prices via BreadPriceViewSet).

    BUG-039 : `category` n'est plus un `TextChoices` figé à 4 valeurs
    (MINI/MOYEN/GRAND/PREMIUM) avec `unique=True` — CLAUDE.md §5.4 exige que
    les catégories de pains soient configurables (ex. ajout d'un "pain de
    200 FC"). C'est désormais un champ texte libre, même pattern que
    `ExpenseCategory`/`ConsumableType` (identifiant court choisi librement par
    la Direction). `unique=True` est retiré volontairement : la catégorie
    n'est plus la clé d'unicité d'un tarif (plusieurs lignes pourraient à
    terme partager un même identifiant de catégorie pour des variantes de
    prix) — c'est `unit_price`/`label` qui distinguent les tarifs à l'usage.
    Les 4 valeurs historiques (MINI/MOYEN/GRAND/PREMIUM) restent inchangées
    en base, elles ne sont simplement plus imposées par une énumération.
    """

    category = models.CharField(
        max_length=30,
        verbose_name=_("Catégorie"),
        help_text=_("Identifiant court libre, ex: MINI, MOYEN, GRAND, PREMIUM, MICRO_200"),
    )
    label = models.CharField(
        max_length=50,
        verbose_name=_("Libellé"),
        help_text=_("Ex: Pain 300 FC")
    )
    unit_price = models.PositiveIntegerField(
        verbose_name=_("Prix unitaire (FC)")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Actif")
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Tarif Pain")
        verbose_name_plural = _("Grille Tarifaire Pains")
        ordering = ['unit_price']

    def __str__(self):
        return f"{self.label} — {self.unit_price} FC"


# ─── Local Expense Categories ────────────────────────────────────────

class ExpenseCategory(models.Model):
    """
    Open-ended, admin-managed list of local-expense categories (§5.1.2).
    Unlike BreadPrice's fixed 4-value enum, this is a free-form list —
    the comptable can add new categories at will from Configuration.
    """
    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("Code"),
        help_text=_("Identifiant court unique, ex: WOOD, TRANSPORT")
    )
    label = models.CharField(
        max_length=100,
        verbose_name=_("Libellé")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Actif")
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Catégorie de Dépense")
        verbose_name_plural = _("Catégories de Dépenses")
        ordering = ['label']

    def __str__(self):
        return self.label


# ─── Activity Log & System Notifications ────────────────────────────

class ActivityLog(models.Model):
    """
    Tracks administrative and terrain events/actions across the network.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
        verbose_name=_("Utilisateur")
    )
    user_display = models.CharField(max_length=150, blank=True, default='', verbose_name=_("Agent"))
    action = models.CharField(max_length=100, blank=True, default='', verbose_name=_("Action"))
    description = models.TextField(blank=True, default='', verbose_name=_("Description"))
    node_origin = models.CharField(max_length=10, default='CLOUD', verbose_name=_("Nœud"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Date & Heure"))

    class Meta:
        verbose_name = _("Journal d'activité")
        verbose_name_plural = _("Journaux d'activités")
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.node_origin}] {self.action} par {self.user_display or 'Système'} ({self.created_at})"


class SystemNotification(models.Model):
    """
    Urgent business notifications (e.g. client risk debt limits, blockchain audits).
    """
    class Severity(models.TextChoices):
        INFO = 'INFO', _('Information')
        SUCCESS = 'SUCCESS', _('Succès')
        WARNING = 'WARNING', _('Avertissement')
        DANGER = 'DANGER', _('Alerte Critique')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150, blank=True, default='', verbose_name=_("Titre"))
    message = models.TextField(blank=True, default='', verbose_name=_("Message"))
    severity = models.CharField(
        max_length=15,
        choices=Severity.choices,
        default=Severity.INFO,
        verbose_name=_("Gravité")
    )
    is_read = models.BooleanField(default=False, verbose_name=_("Lu"))
    node_origin = models.CharField(max_length=10, default='CLOUD', verbose_name=_("Nœud"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Date & Heure"))

    class Meta:
        verbose_name = _("Notification système")
        verbose_name_plural = _("Notifications système")
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity}] {self.title} - {self.is_read}"

