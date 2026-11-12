from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import SyncableModel, Node, BreadPrice


class ProductionSession(SyncableModel):
    """
    Daily production declaration per bakery per team shift.
    Tracks flour input vs bread output to compute yield gap.
    """

    class Team(models.TextChoices):
        A = 'A', _('Équipe A')
        B = 'B', _('Équipe B')

    node  = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='production_sessions', verbose_name=_("Boulangerie"))
    team  = models.CharField(max_length=1, choices=Team.choices, verbose_name=_("Équipe"))
    date  = models.DateField(verbose_name=_("Date de production"))
    declared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='production_sessions',
        verbose_name=_("Déclaré par")
    )

    # Inputs
    flour_sacks_used = models.DecimalField(
        max_digits=8, decimal_places=2, default='0.00',
        verbose_name=_("Sacs de farine utilisés (50 kg)")
    )

    # Outputs — bread by price category
    breads_300  = models.PositiveIntegerField(default=0, verbose_name=_("Pains 300 FC"))
    breads_400  = models.PositiveIntegerField(default=0, verbose_name=_("Pains 400 FC"))
    breads_500  = models.PositiveIntegerField(default=0, verbose_name=_("Pains 500 FC"))
    breads_1000 = models.PositiveIntegerField(default=0, verbose_name=_("Pains 1000 FC"))
    total_breads = models.PositiveIntegerField(default=0, verbose_name=_("Total pains produits"))

    # Yield analysis (now in FC — 1 sac = sac_value_fc)
    total_fc_produced = models.PositiveIntegerField(default=0, verbose_name=_("Valeur FC produite"))
    theoretical_yield = models.PositiveIntegerField(default=0, verbose_name=_("Rendement théorique FC"))
    yield_gap         = models.IntegerField(default=0, verbose_name=_("Écart FC (réel - théorique)"))
    # BUG-038 : valeur du sac (FC) figée au moment de la déclaration initiale.
    # Toujours réutilisée pour recalculer theoretical_yield/yield_gap sur une
    # édition ultérieure (ex: ajout d'une note) — ne jamais relire la valeur
    # courante de Node.sac_value_fc/Config, qui peut avoir changé depuis.
    sac_value_fc_used = models.PositiveIntegerField(
        default=200000, verbose_name=_("Valeur du sac utilisée (figée à la déclaration, FC)")
    )

    is_closed = models.BooleanField(default=False, verbose_name=_("Session clôturée"))
    # BUG-093 : horodatage de la clôture (action `close`), et snapshot figé du
    # recoupement automatique (produit/vendu/soldé-déclassé-invendu-gratuit/
    # NV/écart) au moment précis de la clôture — pour qu'une consultation
    # ultérieure de l'historique ne dépende jamais d'un recalcul qui pourrait
    # dériver si des ventes/dispositions sont enregistrées après coup sur le
    # même nœud/date (ex: l'autre équipe clôture plus tard).
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Clôturée le"))
    closure_summary = models.JSONField(null=True, blank=True, verbose_name=_("Détail du recoupement à la clôture"))
    notes     = models.TextField(blank=True, default='', verbose_name=_("Commentaires"))

    class Meta:
        verbose_name = _("Session de Production")
        verbose_name_plural = _("Sessions de Production")
        ordering = ['-date', 'node__code']
        unique_together = [['node', 'team', 'date']]

    def __str__(self):
        return f"{self.node.code} | Équipe {self.team} | {self.date}"

    def compute_totals(self, sac_value_fc: int = None):
        """
        Monetary rendement: 1 sac = sac_value_fc FC.
        total_fc_produced  = Σ(qty × unit_price) across all lines.
        theoretical_yield  = sacks × sac_value_fc.
        yield_gap          = total_fc - theoretical (positive = surplus, negative = manquant).
        Old breads_* fields are synced from lines for backward compat.

        BUG-038 : si `sac_value_fc` n'est pas fourni, on réutilise la valeur
        déjà figée sur `self.sac_value_fc_used` (déclaration initiale) plutôt
        que de retomber sur une valeur par défaut arbitraire — l'historique
        d'une fournée ne doit jamais être recalculé avec une valeur de sac
        différente de celle en vigueur au moment de sa déclaration.

        BUG-142 (remarque.md — confirmation du stock de départ alimente la
        fournée du jour) : les pains issus d'un reste d'hier confirmé
        (`ProductionSessionLine.source == CARRYOVER`, BUG-133/136) ne
        consomment aucune farine (ce n'est pas une nouvelle production) et
        doivent donc être EXCLUS du calcul de rendement — `total_fc_produced`
        (et donc `yield_gap`/l'alerte « Manquant de Rendement ») ne somme
        QUE les lignes `source == DECLARED` (vraie fournée). `total_breads`
        et les champs legacy `breads_300/400/500/1000` restent, eux,
        calculés sur TOUTES les lignes (DECLARED + CARRYOVER) : c'est le
        total réel de pains disponibles ce jour pour cette équipe qu'on
        affiche dans « Production & Stocks », pas seulement la part
        produite.
        """
        if sac_value_fc is not None:
            self.sac_value_fc_used = sac_value_fc
        lines = list(self.lines.select_related('bread_price').all())
        declared_lines = [l for l in lines if l.source == ProductionSessionLine.Source.DECLARED]
        total_fc = sum(line.quantity * line.bread_price.unit_price for line in declared_lines)
        self.total_breads      = sum(line.quantity for line in lines)
        self.total_fc_produced = total_fc
        # BUG-218 : calcul en Decimal (CLAUDE.md §4), arrondi explicite au franc
        # (demi supérieur) — l'ancien `int(float(...) * ...)` tronquait 1 FC
        # (1,13 sac x 210 000 = 237 299 au lieu de 237 300).
        from decimal import Decimal, ROUND_HALF_UP
        self.theoretical_yield = int(
            (Decimal(str(self.flour_sacks_used or 0)) * Decimal(str(self.sac_value_fc_used)))
            .quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        )
        self.yield_gap         = total_fc - self.theoretical_yield
        # sync legacy per-price fields (best-effort, by unit_price) — sommées
        # sur TOUTES les lignes (DECLARED + CARRYOVER), jamais écrasées entre
        # elles si deux lignes de sources différentes partagent le même
        # unit_price (BUG-142 : auparavant écrasement silencieux, inoffensif
        # tant qu'une seule ligne existait par bread_price/unit_price).
        price_map = {}
        for line in lines:
            price_map[line.bread_price.unit_price] = price_map.get(line.bread_price.unit_price, 0) + line.quantity
        self.breads_300  = price_map.get(300, 0)
        self.breads_400  = price_map.get(400, 0)
        self.breads_500  = price_map.get(500, 0)
        self.breads_1000 = price_map.get(1000, 0)


class ProductionSessionLine(models.Model):
    """
    One bread type produced during a session.
    Replaces the hardcoded breads_300/400/500/1000 fields with a flexible
    FK to BreadPrice, supporting any price tier defined in the admin.

    BUG-142 (remarque.md) : `source` distingue une ligne de VRAIE déclaration
    de fournée (`DECLARED`, défaut — consomme de la farine, compte dans le
    rendement, `ProductionSession.compute_totals()`) d'une ligne issue de la
    confirmation du stock de départ (`CARRYOVER` — reste d'hier, BUG-133/136,
    aucune farine consommée, exclue du calcul de rendement). Les deux
    sources peuvent coexister pour le même `(session, bread_price)` — d'où
    `unique_together` élargi à `source` plutôt que seulement
    `[session, bread_price]`.
    """

    class Source(models.TextChoices):
        DECLARED  = 'DECLARED',  _("Déclarée (vraie fournée)")
        CARRYOVER = 'CARRYOVER', _("Reste d'hier confirmé (BUG-133/136)")

    session     = models.ForeignKey(ProductionSession, on_delete=models.CASCADE, related_name='lines', verbose_name=_("Session"))
    bread_price = models.ForeignKey(BreadPrice, on_delete=models.PROTECT, verbose_name=_("Catégorie Pain"))
    quantity    = models.PositiveIntegerField(verbose_name=_("Quantité produite"))
    source      = models.CharField(
        max_length=10, choices=Source.choices, default=Source.DECLARED,
        verbose_name=_("Origine"),
    )

    class Meta:
        verbose_name = _("Ligne de Production")
        verbose_name_plural = _("Lignes de Production")
        unique_together = [['session', 'bread_price', 'source']]
        ordering = ['bread_price__unit_price']

    def __str__(self):
        return f"{self.session} — {self.bread_price.label} × {self.quantity}"

    @property
    def line_fc(self):
        return self.quantity * self.bread_price.unit_price


class BreadStock(models.Model):
    """
    Running bread inventory per bakery per price tier.
    Columns track the origin of breads so the UI can show produced vs received.
      qty_available = qty_produced + qty_received - qty_sent - qty_disposed + qty_adjusted
    Updated atomically via _adjust_bread_stock() on each business event.

    BUG-136 (docs/qa/REGISTRE_BUGS.md) : `qty_adjusted` capture le cumul des
    corrections MANUELLES du stock réel décidées par un gérant (actuellement
    uniquement via la confirmation « stock de départ du jour », BUG-133/134,
    `DailyOpeningConfirmationView.post()`), par opposition aux mouvements
    métier réels (`qty_produced`/`qty_received`/`qty_sent`/`qty_disposed`,
    qui restent inchangés — ne jamais réutiliser `qty_sent`/`qty_disposed`
    pour une correction manuelle, sémantique trompeuse). Signe retenu : un
    delta POSITIF signifie que le gérant a déclaré PLUS de pains que ce que
    le système calculait (excédent constaté) ; un delta NÉGATIF signifie
    moins (manquant constaté) — même convention que l'écart théorique vs
    déclaré de CLAUDE.md §5.4 (« Écart = valeur théorique − valeur produite
    déclarée → manquant ou excédent »), ici appliqué à la quantité physique
    disponible plutôt qu'à une valeur FC.
    """
    node        = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='bread_stocks', verbose_name=_("Boulangerie"))
    bread_price = models.ForeignKey(BreadPrice, on_delete=models.PROTECT, related_name='bread_stocks', verbose_name=_("Catégorie Pain"))
    qty_produced = models.IntegerField(default=0, verbose_name=_("Produits (propre production)"))
    qty_received = models.IntegerField(default=0, verbose_name=_("Reçus (transferts entrants confirmés)"))
    qty_sent     = models.IntegerField(default=0, verbose_name=_("Expédiés (transferts sortants confirmés)"))
    qty_disposed = models.IntegerField(default=0, verbose_name=_("Disposés (ventes/déchets/dons)"))
    qty_adjusted = models.IntegerField(default=0, verbose_name=_("Ajustements manuels (corrections gérant, BUG-136)"))

    class Meta:
        verbose_name = _("Stock Pains")
        verbose_name_plural = _("Stocks Pains")
        unique_together = [['node', 'bread_price']]
        ordering = ['node__code', 'bread_price__unit_price']

    def __str__(self):
        return f"{self.node.code} — {self.bread_price.label} : {self.qty_available} dispo"

    @property
    def qty_available(self):
        return self.qty_produced + self.qty_received - self.qty_sent - self.qty_disposed + self.qty_adjusted


def _adjust_bread_stock(node, bread_price, produced=0, received=0, sent=0, disposed=0, adjusted=0):
    """Atomically update BreadStock for a node/bread_price using F() expressions."""
    stock, _ = BreadStock.objects.get_or_create(node=node, bread_price=bread_price)
    updates = {}
    if produced: updates['qty_produced'] = models.F('qty_produced') + produced
    if received: updates['qty_received'] = models.F('qty_received') + received
    if sent:     updates['qty_sent']     = models.F('qty_sent')     + sent
    if disposed: updates['qty_disposed'] = models.F('qty_disposed') + disposed
    if adjusted: updates['qty_adjusted'] = models.F('qty_adjusted') + adjusted
    if updates:
        BreadStock.objects.filter(pk=stock.pk).update(**updates)


class DailyBreadStockSnapshot(models.Model):
    """
    BUG-118 (analyse data_kiese/EXTRAIT RAPPORT DE CLOTUREOCTOBRE 2026.xlsx,
    2026-11-01) : `BreadStock.qty_available` n'est qu'un solde COURANT
    cumulatif par nœud+catégorie — il n'existe aucune trace de ce qu'il
    valait à la fin d'une journée donnée. Le vrai rapport de clôture du
    client a pourtant, par boulangerie/jour/catégorie de pain, deux
    rubriques qui dépendent d'un historique quotidien :
      - RESTE DU JOUR  : solde de pains invendus restant à la fin du jour.
      - RESTE DU HIER/S : report (ajusté) de la veille.

    Extension BUG-118 (confirmée par le client le 2026-11-01) : dans le
    fichier réel (`data_kiese/DOC 01- RAPPORT  BOULANGERIES AOUT  2026.xlsx`,
    feuille ZADIM), `RESTE DU HIER` ne suit pas toujours
    `reste_du_hier(jour N) = −reste_du_jour(jour N-1)` — la valeur dépend de
    l'ÉQUIPE (A/B, CLAUDE.md §5.2) qui a clôturé en dernier. Chaque équipe a
    SON propre solde déclaré, reporté inchangé les jours où elle ne clôture
    pas. Ce modèle capture donc un instantané PAR ÉQUIPE.

    Important (à ne pas confondre) : `BreadStock.qty_available` reste un
    solde GLOBAL partagé par nœud+catégorie (un seul tas de pains physiques,
    peu importe l'équipe qui vend) — on n'y touche pas. Ce qui est tenu par
    équipe ici est une donnée DÉCLARATIVE distincte : ce que CETTE équipe
    rapporte comme « stock restant à vendre » à SA propre clôture de
    session, indépendamment du stock physique global agrégé. La source de
    cette quantité est la disposition `BreadDisposal` de type `REMAINING`
    rattachée à CETTE session précise (`session` FK) — ces dispositions ne
    modifient jamais `BreadStock` (voir `BreadDisposalViewSet.perform_create`)
    et représentent exactement ce que l'équipe déclare comme invendu/à
    reporter pour chaque catégorie de pain qu'elle a produite ce jour-là.
    Une catégorie produite par la session mais sans ligne `REMAINING`
    déclarée est considérée comme intégralement écoulée par cette équipe
    (0, pas d'absence de valeur).

    Formule RESTE DU HIER retenue (confirmée par le client) :
        reste_du_hier(nœud, catégorie, équipe T, jour N)
            = − reste_du_jour(nœud, catégorie, équipe T, dernier jour
                                antérieur à N pour lequel l'équipe T a
                                clôturé)
            = 0 si l'équipe T n'a encore jamais clôturé avant N pour cette
              boulangerie/catégorie (première journée d'activité de
              l'équipe).
    """

    node         = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='daily_bread_stock_snapshots', verbose_name=_("Boulangerie"))
    bread_price  = models.ForeignKey(BreadPrice, on_delete=models.PROTECT, related_name='daily_bread_stock_snapshots', verbose_name=_("Catégorie Pain"))
    date         = models.DateField(verbose_name=_("Date de clôture"))
    team         = models.CharField(
        max_length=1, choices=ProductionSession.Team.choices,
        verbose_name=_("Équipe"),
        help_text=_("Équipe ayant déclaré ce solde à sa clôture (CLAUDE.md §5.2)"),
    )
    qty_at_close = models.IntegerField(verbose_name=_("Solde déclaré à la clôture (RESTE DU JOUR)"))
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Instantané Quotidien de Stock Pains")
        verbose_name_plural = _("Instantanés Quotidiens de Stock Pains")
        unique_together = [['node', 'bread_price', 'date', 'team']]
        ordering = ['node__code', 'bread_price__unit_price', '-date', 'team']

    def __str__(self):
        return f"{self.node.code} | Éq.{self.team} | {self.bread_price.label} | {self.date} : {self.qty_at_close}"

    @classmethod
    def reste_du_jour(cls, node, bread_price, date, team):
        """Solde déclaré par `team` restant à la fin de `date`, ou None si pas encore clôturé par cette équipe."""
        snap = cls.objects.filter(node=node, bread_price=bread_price, date=date, team=team).first()
        return snap.qty_at_close if snap else None

    @classmethod
    def reste_du_hier(cls, node, bread_price, date, team):
        """
        Report (négatif) du dernier RESTE DU JOUR antérieur à `date` déclaré
        par cette même équipe (pas forcément la veille calendaire : une
        équipe qui n'a pas travaillé un jour donné reporte son solde
        inchangé jusqu'à sa prochaine clôture). 0 si cette équipe n'a
        encore jamais clôturé avant `date` pour ce nœud/catégorie.
        """
        previous = (
            cls.objects
            .filter(node=node, bread_price=bread_price, date__lt=date, team=team)
            .order_by('-date')
            .first()
        )
        if previous is None:
            return 0
        return -previous.qty_at_close

    @classmethod
    def last_snapshot_before(cls, node, bread_price, date):
        """
        BUG-161 (B4, rotation) : dernier instantané du nœud pour cette
        catégorie STRICTEMENT avant la journée `date`, TOUTES ÉQUIPES
        CONFONDUES (le reste de l'équipe A devient le départ de l'équipe B),
        ou None. Lecture seule ; hors rotation, `reste_du_hier` (par équipe)
        reste la seule source utilisée.
        """
        return (
            cls.objects
            .filter(node=node, bread_price=bread_price, date__lt=date)
            .order_by('-date', '-updated_at', '-pk')
            .first()
        )

    @classmethod
    def last_snapshot_upto(cls, node, bread_price, date):
        """
        BUG-247 : dernier instantané du nœud pour cette catégorie jusqu'à la
        date `date` INCLUSE, toutes équipes confondues (reste de l'équipe
        sortante d'une relève en milieu de journée calendaire), ou None.
        """
        return (
            cls.objects
            .filter(node=node, bread_price=bread_price, date__lte=date)
            .order_by('-date', '-updated_at', '-pk')
            .first()
        )

    @classmethod
    def reste_du_hier_chained(cls, node, bread_price, date):
        """Convention de `reste_du_hier` (négatif) sur le chaînage inter-équipes."""
        previous = cls.last_snapshot_before(node, bread_price, date)
        if previous is None:
            return 0
        return -previous.qty_at_close

    @classmethod
    def record_snapshot(cls, session):
        """
        Capture (upsert) le solde DÉCLARÉ par l'équipe de `session` (une
        `ProductionSession`), pour chaque catégorie de pain concernée par
        CETTE session (produite et/ou avec un reste déclaré), daté de
        `session.date`.

        La quantité déclarée par catégorie = somme des `BreadDisposal` de
        type `REMAINING` rattachés à CETTE session pour cette catégorie
        (« stock restant à vendre » saisi par l'équipe à sa clôture — ne
        touche jamais `BreadStock`, voir `BreadDisposalViewSet`). Une
        catégorie produite par la session sans ligne `REMAINING` associée
        est considérée écoulée par cette équipe (0).

        Appelé à la clôture d'une session de production (voir `close()`).
        Le upsert est naturellement borné à (node, bread_price, date, team)
        de CETTE session : il ne peut jamais écraser le snapshot d'une
        autre équipe clôturant le même jour.
        """
        remaining_qs = session.disposals.filter(
            disposal_type=BreadDisposal.DisposalType.REMAINING,
        )
        remaining_by_bp = {}
        for disposal in remaining_qs.select_related('bread_price'):
            remaining_by_bp[disposal.bread_price_id] = (
                remaining_by_bp.get(disposal.bread_price_id, 0) + disposal.quantity
            )

        bread_price_ids = set(
            session.lines.values_list('bread_price_id', flat=True)
        ) | set(remaining_by_bp.keys())

        for bread_price_id in bread_price_ids:
            cls.objects.update_or_create(
                node=session.node, bread_price_id=bread_price_id,
                date=session.date, team=session.team,
                defaults={'qty_at_close': remaining_by_bp.get(bread_price_id, 0)},
            )


class DailyOpeningConfirmation(models.Model):
    """
    BUG-133 (docs/qa/REGISTRE_BUGS.md ; demande client reformulée par le
    coordinateur, suite de remarque.md l.396 / BUG-130/131) : à sa première
    connexion de la journée, le gérant doit voir une boîte modale qui
    propose, par catégorie de pain, le stock PHYSIQUE actuellement
    disponible (`BreadStock.qty_available` — ce qui reste après déduction
    des ventes déjà confirmées, CLAUDE.md §5.2/§5.4) comme point de départ
    « RESTE DU HIER » de la journée. Il peut modifier ces nombres ou les
    valider tels quels — la validation devient la valeur OFFICIELLE du
    « RESTE DU HIER » utilisée pour démarrer la journée dans le rapport de
    clôture journalier (BUG-120, `_build_daily_closure_report`).

    Point de conception 1 — « première connexion du jour » sans login par
    équipe : un seul compte GERANT couvre aujourd'hui les équipes A et B
    (`User.team` reste vide pour ce rôle), donc l'équipe ne peut pas être
    déduite de l'heure de connexion ni de `Node.active_team_at()`
    (BUG-130/131 — pensé pour un AUTRE usage : déterminer qui travaille MAINTENANT,
    pas pour quelle équipe confirmer un stock de départ). L'équipe est donc
    choisie EXPLICITEMENT par le gérant DANS la boîte modale elle-même (voir
    `DailyOpeningConfirmationView`), jamais déduite silencieusement. La
    détection de « première connexion » elle-même n'est pas un événement de
    session : c'est simplement l'ABSENCE d'une ligne (node, team, date=
    aujourd'hui) qui signale au frontend qu'il doit encore proposer la
    boîte modale pour CETTE équipe ; une fois la ligne créée, la question ne
    se repose plus ce jour-là pour cette équipe, quel que soit le nombre de
    reconnexions ultérieures (persistant côté serveur, pas un simple drapeau
    de session local qui disparaîtrait à la déconnexion).

    Point de conception 2 — ne jamais corrompre l'historique : ce modèle est
    volontairement DISTINCT de `DailyBreadStockSnapshot` (BUG-118, VÉRIFIÉ) —
    il ne le modifie ni ne le remplace jamais. `DailyBreadStockSnapshot`
    reste l'unique source de vérité des clôtures PASSÉES (solde déclaré par
    une équipe à SA clôture de session, `qty_at_close`/`reste_du_jour`/
    `reste_du_hier`, formule négative confirmée par le client). Ce nouveau
    modèle n'intervient qu'en SURCOUCHE, au niveau de l'agrégation du
    rapport (`_build_daily_closure_report`) : quand une confirmation existe
    pour (node, team, date), sa valeur devient `reste_du_hier` pour cette
    équipe/catégorie/jour, prioritaire sur le calcul auto-dérivé de
    `DailyBreadStockSnapshot.reste_du_hier()` — qui continue, lui, à
    s'appliquer EXACTEMENT comme avant pour tout jour/équipe sans
    confirmation explicite (rétro-compatibilité totale).

    Choix de signe (BUG-135, correction du choix initial de BUG-133/134) :
    `qty_confirmed` reste stocké ici tel que saisi/validé par le gérant dans
    la boîte modale, un nombre naturellement POSITIF (stock physique
    réellement disponible — c'est intuitif pour l'UI et volontaire, aucun
    changement). En revanche `DailyBreadStockSnapshot.reste_du_hier()`
    produit un `reste_du_hier` NÉGATIF par construction (confirmé par le
    client pour BUG-118, « − reste_du_jour de la veille »), et ce
    `reste_du_hier` négatif alimente directement `facture_mvm_interne`/
    `total_du_jour` (BUG-120, déjà vérifiés formule à formule contre les
    Excel réels du client). Utiliser `qty_confirmed` sans le néger dans
    l'agrégation du rapport inversait donc le signe pour les jours/équipes
    confirmés et faussait ces totaux déjà vérifiés — ce n'était PAS un
    changement de convention voulu mais une erreur d'agrégation (trouvée par
    le coordinateur en relisant le code). `_build_daily_closure_report`
    applique donc désormais `-qty_confirmed` au moment de construire
    `reste_du_hier_by_team`, pour retrouver la même convention de signe que
    le calcul auto-dérivé — sans jamais toucher au stockage positif de
    `qty_confirmed` ni à l'affichage de la boîte modale (BUG-134, intact).
    """

    node = models.ForeignKey(
        Node, on_delete=models.PROTECT, related_name='daily_opening_confirmations',
        verbose_name=_("Boulangerie"),
    )
    team = models.CharField(
        max_length=1, choices=ProductionSession.Team.choices,
        verbose_name=_("Équipe"),
        help_text=_("Équipe pour laquelle ce stock de départ est confirmé — choisie explicitement dans la boîte modale, jamais déduite de l'heure."),
    )
    date = models.DateField(verbose_name=_("Date de la journée confirmée"))
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='daily_opening_confirmations', verbose_name=_("Confirmé par"),
    )
    confirmed_at = models.DateTimeField(auto_now=True, verbose_name=_("Confirmé le"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Confirmation du Stock de Départ")
        verbose_name_plural = _("Confirmations du Stock de Départ")
        unique_together = [['node', 'team', 'date']]
        ordering = ['-date', 'node__code', 'team']

    def __str__(self):
        return f"{self.node.code} | Éq.{self.team} | {self.date} : confirmé"


class DailyTeamAssignment(models.Model):
    """
    BUG-161 (B2) : équipe de service (A ou B) désignée MANUELLEMENT pour une
    PÉRIODE DE SERVICE « de relève à relève » (`core.workday.business_date`).
    BUG-247 (décision client 2026-11-12) : `work_date` n'est PAS la date de
    travail (calendaire, minuit à minuit) mais la date LOCALE de la relève qui
    ouvre la période ; une même date calendaire peut donc relever de deux
    désignations (équipe sortante avant la relève, entrante après).
    Décision client : pas d'alternance automatique ; tant qu'aucune équipe
    n'est désignée pour la journée courante, la facturation est bloquée (si
    `Node.team_rotation_enabled`). Une ligne par (boulangerie, journée) ;
    changer l'équipe d'une journée déjà désignée met la ligne à jour
    (correction journalisée par la vue).

    Même convention que `DailyOpeningConfirmation`/`DailyBreadStockSnapshot` :
    modèle local non synchronisable (pas de SyncableModel), supprimé par la
    réinitialisation superuser (`core/reset.py`).
    """

    node = models.ForeignKey(
        Node, on_delete=models.PROTECT, related_name='daily_team_assignments',
        verbose_name=_("Boulangerie"),
    )
    work_date = models.DateField(verbose_name=_("Journée de travail"))
    team = models.CharField(
        max_length=1, choices=ProductionSession.Team.choices,
        verbose_name=_("Équipe de service"),
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='daily_team_assignments', verbose_name=_("Désignée par"),
    )
    assigned_at = models.DateTimeField(auto_now=True, verbose_name=_("Désignée le"))

    class Meta:
        verbose_name = _("Désignation de l'équipe de service")
        verbose_name_plural = _("Désignations de l'équipe de service")
        unique_together = [['node', 'work_date']]
        ordering = ['-work_date', 'node__code']

    def __str__(self):
        return f"{self.node.code} | {self.work_date} : équipe {self.team}"


class DailyOpeningConfirmationLine(models.Model):
    """Quantité confirmée (RESTE DU HIER officiel) pour une catégorie de pain donnée."""

    confirmation = models.ForeignKey(
        DailyOpeningConfirmation, on_delete=models.CASCADE, related_name='lines',
        verbose_name=_("Confirmation"),
    )
    bread_price = models.ForeignKey(
        BreadPrice, on_delete=models.PROTECT, verbose_name=_("Catégorie Pain"),
    )
    qty_confirmed = models.IntegerField(verbose_name=_("Quantité confirmée (RESTE DU HIER officiel)"))

    class Meta:
        verbose_name = _("Ligne de Confirmation du Stock de Départ")
        verbose_name_plural = _("Lignes de Confirmation du Stock de Départ")
        unique_together = [['confirmation', 'bread_price']]
        ordering = ['bread_price__unit_price']

    def __str__(self):
        return f"{self.confirmation} — {self.bread_price.label} : {self.qty_confirmed}"


class ConsumableType(models.Model):
    """
    Open-ended, admin-managed list of consumable types (§3.2 — farine, sel,
    levure, huile...). Unlike a fixed enum, la Direction peut ajouter de
    nouveaux consommables à tout moment depuis Configuration ; le champ
    ConsumableStock/ConsumableCount.consumable_type référence son "code" en
    texte libre (pas de FK) pour ne jamais bloquer un mouvement existant si
    un type est supprimé.
    """
    code = models.CharField(
        max_length=10, unique=True,
        verbose_name=_("Code"),
        help_text=_("Identifiant court unique, ex: FLOUR, SUCRE")
    )
    label = models.CharField(max_length=100, verbose_name=_("Libellé"))
    unit  = models.CharField(max_length=20, blank=True, default='', verbose_name=_("Unité"))
    is_active = models.BooleanField(default=True, verbose_name=_("Actif"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Type de Consommable")
        verbose_name_plural = _("Types de Consommables")
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.label}"


class ConsumableStock(SyncableModel):
    """Current stock level for a consumable at a given bakery."""

    node            = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='consumable_stocks', verbose_name=_("Boulangerie"))
    consumable_type = models.CharField(max_length=10, verbose_name=_("Consommable"), help_text=_("Code d'un ConsumableType (Configuration)"))
    quantity        = models.DecimalField(max_digits=10, decimal_places=3, default='0.000', verbose_name=_("Quantité en stock"))
    unit            = models.CharField(max_length=20, blank=True, default='', verbose_name=_("Unité"))
    # BUG-123 (Q-005) : coût unitaire moyen pondéré (CUMP), recalculé à chaque
    # entrée (`ConsumableMovement.ENTRY`) et utilisé pour valoriser chaque
    # sortie (`ConsumableMovement.EXIT`) au moment où elle est enregistrée —
    # c'est ce coût qui permet de valoriser la consommation réelle en
    # production (Compte de Résultat, `finance/views.py`).
    average_unit_cost = models.DecimalField(
        max_digits=14, decimal_places=4, default='0.0000',
        verbose_name=_("Coût unitaire moyen pondéré (FC)"),
    )

    class Meta:
        verbose_name = _("Stock Consommable")
        verbose_name_plural = _("Stocks Consommables")
        unique_together = [['node', 'consumable_type']]
        ordering = ['node__code', 'consumable_type']

    def __str__(self):
        return f"{self.node.code} — {self.consumable_type} : {self.quantity} {self.unit}"


class ConsumableMovement(SyncableModel):
    """Each entry or exit of a consumable (supply or production usage)."""

    class MovementType(models.TextChoices):
        ENTRY = 'ENTRY', _('Entrée (Approvisionnement)')
        EXIT  = 'EXIT',  _('Sortie (Production)')

    node            = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='consumable_movements', verbose_name=_("Boulangerie"))
    stock           = models.ForeignKey(ConsumableStock, on_delete=models.PROTECT, related_name='movements', verbose_name=_("Stock lié"))
    session         = models.ForeignKey(ProductionSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='consumable_movements', verbose_name=_("Session de production"))
    SUPPLIER_CHOICES = [
        ('MIDEMA', 'MIDEMA'),
        ('GMK',    'GMK'),
        ('DVS',    'DVS'),
        ('LOCAL',  _('Achat local')),
    ]

    movement_type   = models.CharField(max_length=10, choices=MovementType.choices, verbose_name=_("Type de mouvement"))
    quantity        = models.DecimalField(max_digits=10, decimal_places=3, verbose_name=_("Quantité"))
    unit_price      = models.DecimalField(max_digits=14, decimal_places=2, default='0.00', blank=True, verbose_name=_("Prix d'achat unitaire (FC)"))
    supplier        = models.CharField(max_length=10, choices=SUPPLIER_CHOICES, blank=True, default='', verbose_name=_("Fournisseur"))
    description     = models.CharField(max_length=255, blank=True, default='', verbose_name=_("Description"))
    recorded_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='consumable_movements', verbose_name=_("Enregistré par")
    )

    class Meta:
        verbose_name = _("Mouvement Consommable")
        verbose_name_plural = _("Mouvements Consommables")
        ordering = ['-created_at']
        # BUG-066 : `FinancialYearViewSet.comparative()` (finance/views.py)
        # filtre `ConsumableMovement.objects.filter(created_at__year=year,
        # movement_type='ENTRY')` (puis `stock__consumable_type=...`) pour
        # calculer le coût des approvisionnements (COGS) — sur un volume de
        # charge (24 000 factures/8 nœuds), ce filtre sans index dédié
        # scannait la table complète à chaque appel.
        indexes = [
            models.Index(fields=['movement_type', 'created_at'], name='prod_consmove_type_crea_idx'),
        ]

    def __str__(self):
        sign = '+' if self.movement_type == self.MovementType.ENTRY else '-'
        return f"{sign}{self.quantity} {self.stock.consumable_type} @ {self.node.code}"

    def save(self, *args, **kwargs):
        from decimal import Decimal
        from django.db import transaction

        # self.quantity peut arriver comme str/float/int si l'appelant ne
        # l'a pas déjà passé en Decimal (ex: payload JSON brut d'une
        # fournée) — on le normalise avant toute comparaison/arithmétique.
        if not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))

        is_new = self._state.adding

        if is_new and self.movement_type == self.MovementType.EXIT:
            # BUG-143 (demande client directe, 2026-11-10, prioritaire sur
            # tout document de référence antérieur — CLAUDE.md §1) : ANNULE
            # le refus posé par BUG-041. Une sortie de consommable ne doit
            # plus JAMAIS bloquer l'enregistrement d'une fournée, même si le
            # stock disponible est nul ou insuffisant (cas réel constaté :
            # base réinitialisée, aucun stock de consommable encore saisi) —
            # le stock est désormais autorisé à devenir négatif, exactement
            # comme `BreadStock.qty_available` l'est déjà (choix produit
            # différent documenté par remarque.md l.196). On ne refuse plus
            # rien ici ; on se contente de signaler le passage en négatif par
            # une notification (même pattern que le manquant de rendement
            # `yield_gap < 0` dans `production/views.py::perform_create`),
            # sans bloquer quoi que ce soit.
            with transaction.atomic():
                stock = type(self.stock).objects.select_for_update().get(pk=self.stock_id)
                resulting_quantity = stock.quantity - self.quantity
                # BUG-123 (Q-005) : une sortie n'a pas de « prix d'achat » qui
                # lui soit propre — elle est valorisée au Coût Unitaire Moyen
                # Pondéré (CUMP) du stock au moment de la sortie, comme
                # `InvoiceLine.save()` fige `unit_price` depuis `BreadPrice` :
                # on ignore toute valeur transmise par l'appelant pour rester
                # cohérent (même règle quel que soit le point d'entrée).
                self.unit_price = stock.average_unit_cost
                super().save(*args, **kwargs)
                # BUG-217 : `stock.quantity` devient une expression F() après
                # cette écriture ; on garde la quantité disponible AVANT sortie
                # (valeur lue sous verrou) pour le message de notification.
                available_before = stock.quantity
                stock.quantity = models.F('quantity') - self.quantity
                stock.save(update_fields=['quantity'])
                if resulting_quantity < 0:
                    from core.utils import create_notification
                    create_notification(
                        title=f"Stock négatif — {self.stock.consumable_type} {self.node.code}",
                        message=(
                            f"Sortie de {self.quantity} {self.stock.consumable_type} à "
                            f"{self.node.code} alors que {available_before} seulement "
                            f"étai(en)t disponible(s) : stock désormais à {resulting_quantity} "
                            f"(BUG-143, sortie autorisée en négatif sur demande client)."
                        ),
                        severity='WARNING', node_origin=self.node.code,
                    )
            return

        if is_new and self.movement_type == self.MovementType.ENTRY:
            with transaction.atomic():
                stock = type(self.stock).objects.select_for_update().get(pk=self.stock_id)
                if not isinstance(self.unit_price, Decimal):
                    self.unit_price = Decimal(str(self.unit_price or '0'))
                old_qty  = Decimal(str(stock.quantity))
                old_avg  = Decimal(str(stock.average_unit_cost))
                new_qty  = old_qty + self.quantity
                # BUG-123 (Q-005) : coût unitaire moyen pondéré (CUMP), mis à
                # jour à chaque approvisionnement, pour pouvoir valoriser la
                # consommation réelle (sorties) au Compte de Résultat plutôt
                # que les achats du mois.
                if new_qty > 0:
                    new_avg = ((old_qty * old_avg) + (self.quantity * self.unit_price)) / new_qty
                else:
                    new_avg = self.unit_price
                super().save(*args, **kwargs)
                stock.quantity = new_qty
                stock.average_unit_cost = new_avg
                stock.save(update_fields=['quantity', 'average_unit_cost'])
            return

        # BUG-222 : modification d'un mouvement existant. Auparavant la quantité
        # ENTIÈRE était ré-ajoutée au stock (double comptage). On applique
        # désormais le DELTA : on contre-passe l'effet de l'ancienne version
        # (lue sous verrou) puis on applique celui de la nouvelle, sur le bon
        # stock si celui-ci a changé — le tout dans une transaction.
        with transaction.atomic():
            old = type(self).objects.select_for_update().get(pk=self.pk)
            stock_ids = sorted({old.stock_id, self.stock_id}, key=str)
            list(ConsumableStock.objects.select_for_update().filter(pk__in=stock_ids))
            ConsumableStock.objects.filter(pk=old.stock_id).update(
                quantity=models.F('quantity') - old._signed_effect(),
            )
            super().save(*args, **kwargs)
            ConsumableStock.objects.filter(pk=self.stock_id).update(
                quantity=models.F('quantity') + self._signed_effect(),
            )

    def _signed_effect(self):
        """Effet du mouvement sur le stock : +quantité (ENTRY) ou −quantité (EXIT)."""
        from decimal import Decimal
        qty = self.quantity if isinstance(self.quantity, Decimal) else Decimal(str(self.quantity))
        return qty if self.movement_type == self.MovementType.ENTRY else -qty

    def delete(self, *args, **kwargs):
        # BUG-222 : supprimer un mouvement inverse son effet sur le stock
        # (registre et stock restent cohérents), de façon atomique.
        from django.db import transaction
        with transaction.atomic():
            old = type(self).objects.select_for_update().get(pk=self.pk)
            ConsumableStock.objects.select_for_update().filter(pk=old.stock_id).first()
            ConsumableStock.objects.filter(pk=old.stock_id).update(
                quantity=models.F('quantity') - old._signed_effect(),
            )
            return super().delete(*args, **kwargs)


class ConsumableCount(models.Model):
    """Physical inventory count for a consumable at a given bakery (§3.2 inventaire)."""
    node              = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='consumable_counts', verbose_name=_("Boulangerie"))
    consumable_type   = models.CharField(max_length=10, verbose_name=_("Consommable"), help_text=_("Code d'un ConsumableType (Configuration)"))
    count_date        = models.DateField(verbose_name=_("Date de comptage"))
    system_quantity   = models.DecimalField(max_digits=10, decimal_places=3, verbose_name=_("Qté Système"))
    physical_quantity = models.DecimalField(max_digits=10, decimal_places=3, verbose_name=_("Qté Physique Constatée"))
    gap               = models.DecimalField(max_digits=10, decimal_places=3, verbose_name=_("Écart (physique − système)"))
    counted_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='consumable_counts', verbose_name=_("Compté par")
    )
    notes             = models.TextField(blank=True, default='', verbose_name=_("Notes"))
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Comptage Physique")
        verbose_name_plural = _("Comptages Physiques")
        ordering = ['-count_date', 'node__code']

    def __str__(self):
        return f"{self.node.code} | {self.consumable_type} | {self.count_date} | gap={self.gap}"


class BreadTransfer(SyncableModel):
    """
    Inter-bakery bread transfer with double-validation protocol.
    Stock effect is mirrored: -qty at source, +qty at destination.
    """

    class TransferStatus(models.TextChoices):
        PENDING   = 'PENDING',   _('En attente de réception')
        RESPONDED = 'RESPONDED', _('Réceptionné — en attente de confirmation')
        CONFIRMED = 'CONFIRMED', _('Confirmé')
        DISPUTED  = 'DISPUTED',  _('Litige (Écart détecté)')
        CANCELLED = 'CANCELLED', _('Annulé')

    from_node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='transfers_out', verbose_name=_("Boulangerie source"))
    to_node   = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='transfers_in',  verbose_name=_("Boulangerie destination"))
    # Legacy single-category fields — kept nullable for backward compat; use lines[] for new transfers
    bread_price       = models.ForeignKey(BreadPrice, on_delete=models.PROTECT, null=True, blank=True, verbose_name=_("Catégorie Pain (legacy)"))
    quantity_sent     = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Quantité envoyée (legacy)"))
    quantity_received = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Quantité reçue"))
    transfer_status   = models.CharField(max_length=15, choices=TransferStatus.choices, default=TransferStatus.PENDING, verbose_name=_("Statut"))
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='transfers_initiated', verbose_name=_("Initié par")
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='transfers_confirmed', verbose_name=_("Confirmé par")
    )
    notes = models.TextField(blank=True, default='', verbose_name=_("Notes"))

    class Meta:
        verbose_name = _("Transfert Inter-Boulangeries")
        verbose_name_plural = _("Transferts Inter-Boulangeries")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.from_node.code} → {self.to_node.code}"

    @property
    def total_sent(self):
        return sum(line.quantity_sent for line in self.lines.all())

    @property
    def total_received(self):
        return sum(line.quantity_received or 0 for line in self.lines.all())

    @property
    def quantity_gap(self):
        return self.total_sent - self.total_received


class BreadTransferLine(models.Model):
    """One bread category line within a BreadTransfer."""
    transfer    = models.ForeignKey(BreadTransfer, on_delete=models.CASCADE, related_name='lines', verbose_name=_("Transfert"))
    bread_price = models.ForeignKey(BreadPrice, on_delete=models.PROTECT, verbose_name=_("Catégorie Pain"))
    quantity_sent     = models.PositiveIntegerField(verbose_name=_("Quantité envoyée"))
    quantity_received = models.PositiveIntegerField(null=True, blank=True, verbose_name=_("Quantité reçue"))

    class Meta:
        verbose_name = _("Ligne de Transfert")
        verbose_name_plural = _("Lignes de Transfert")
        unique_together = [['transfer', 'bread_price']]
        ordering = ['bread_price__unit_price']

    def __str__(self):
        return f"{self.transfer} | {self.bread_price.label} × {self.quantity_sent}"

    @property
    def quantity_gap(self):
        if self.quantity_received is None:
            return None
        return self.quantity_sent - self.quantity_received


class BreadDisposal(SyncableModel):
    """
    Tracks the fate of unsold or off-spec breads per session:
    discounted sales, declassed, unsold (loss), free distributions, remaining.
    """

    class DisposalType(models.TextChoices):
        SOLD_DISCOUNT = 'SOLD_DISCOUNT', _('Vendu à prix forfaitaire (soldé)')
        DECLASSED     = 'DECLASSED',     _('Déclassé (pain non conforme)')
        UNSOLD        = 'UNSOLD',        _('Invendu (Perte sèche)')
        FREE_DIST     = 'FREE_DIST',     _('Sortie gratuite (Don / Personnel)')
        REMAINING     = 'REMAINING',     _('Stock restant à vendre')

    node          = models.ForeignKey(Node, on_delete=models.PROTECT, related_name='bread_disposals', verbose_name=_("Boulangerie"))
    session       = models.ForeignKey(ProductionSession, on_delete=models.CASCADE, related_name='disposals', verbose_name=_("Session de Production"))
    bread_price   = models.ForeignKey(BreadPrice, on_delete=models.PROTECT, verbose_name=_("Catégorie Pain"))
    disposal_type = models.CharField(max_length=20, choices=DisposalType.choices, verbose_name=_("Type"))
    # BUG-158 (instruction client, 2026-11-10 : « enregistre le stock même s'il
    # est négatif à la clôture automatique ») : `IntegerField` et non plus
    # `PositiveIntegerField`, car un « reste du jour » (type REMAINING) reprend
    # le stock physique, qui peut être négatif. Le négatif reste interdit pour
    # tous les autres types : contrainte base ci-dessous + validation du
    # serializer.
    quantity      = models.IntegerField(verbose_name=_("Quantité"))
    unit_price_sold = models.PositiveIntegerField(default=0, verbose_name=_("Prix de vente unitaire (FC)"), help_text=_("Pour les ventes forfaitaires uniquement"))
    total_value   = models.DecimalField(max_digits=12, decimal_places=2, default='0.00', verbose_name=_("Valeur totale (FC)"))
    notes         = models.CharField(max_length=255, blank=True, default='', verbose_name=_("Notes"))

    class Meta:
        verbose_name = _("Disposition Pain")
        verbose_name_plural = _("Dispositions Pains")
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0) | models.Q(disposal_type='REMAINING'),
                name='breaddisposal_negative_qty_only_remaining',
            ),
        ]

    def __str__(self):
        return f"{self.node.code} | {self.get_disposal_type_display()} | {self.quantity} × {self.bread_price.label}"

    def save(self, *args, **kwargs):
        self.total_value = self.quantity * self.unit_price_sold
        super().save(*args, **kwargs)
