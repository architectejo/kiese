import random
import time
from datetime import date as _date_cls
from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Q, Sum, Count
from django.db.models.functions import Greatest
from django.utils import timezone
from rest_framework import viewsets, status, filters, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from core.mixins import is_node_less_non_hq
from kiese.node_guard import NoNodeGuardMixin, parse_date_param
from core.models import Node, BreadPrice, Config
from core.permissions import IsFacturier, IsLivreur, IsGerant, IsFacturierOrLivreur
from core.utils import log_activity, create_notification, validate_requested_date as _validate_requested_date
from core.workday import work_date_for
from clients.models import Client
from production.models import _adjust_bread_stock
from sync.models import DebtMovement
from .models import Invoice, InvoiceLine, SOLDEE_PRICE_RATIO
from .services import (
    InvoiceStateError, deliver_invoice, mark_not_served, expire_pending_invoices, expiry_cutoff,
)
from .serializers import InvoiceSerializer, InvoiceCreateSerializer, InvoiceAdjustSerializer


# BUG-062 : même motif que `treasury.views.append_cashbook_entry`
# (`_APPEND_MAX_RETRIES`) et `clients.models._generate_client_code`
# (BUG-017) — sous SQLite, 2 écritures strictement simultanées sur
# `sales_invoice` déclenchent systématiquement `OperationalError`
# ("database table is locked"), non pertinent sur PostgreSQL en
# production (verrouillage de ligne) mais nécessaire ici pour que les
# facturiers concurrents se mettent en file plutôt que d'échouer.
# Chaque facture implique plusieurs écritures (facture, lignes, mise à jour
# du stock, mise à jour F() de la dette client, agrégats de période) dans la
# MÊME transaction — une fenêtre de contention bien plus large qu'un simple
# `append_cashbook_entry` (une seule ligne). Un nombre de tentatives plus
# généreux est nécessaire pour absorber un pic réaliste (plusieurs
# facturiers par boulangerie, plusieurs boulangeries à la fois).
_INVOICE_CREATE_MAX_RETRIES = 200


# BUG-650 : retentative bornée sur « database is locked / table is locked »
# (SQLite, nœud desktop). Chaque tentative rejoue l'action dans sa propre
# transaction atomique ; toute autre erreur (métier ou SQL) est propagée.
_ACTION_LOCK_MAX_RETRIES = 100


def _retry_on_lock(fn):
    last_exc = None
    for _attempt in range(_ACTION_LOCK_MAX_RETRIES):
        try:
            return fn()
        except OperationalError as exc:
            if 'locked' not in str(exc).lower():
                raise
            last_exc = exc
            time.sleep(random.uniform(0.02, 0.15))
    raise last_exc


class BoundedSearchFilter(filters.SearchFilter):
    """BUG-645 : borne nombre et longueur des termes (SQLite : LIKE trop complexe -> 500)."""
    MAX_TERMS = 5
    MAX_TERM_LENGTH = 100

    def get_search_terms(self, request):
        terms = super().get_search_terms(request)
        return [t[:self.MAX_TERM_LENGTH] for t in terms[:self.MAX_TERMS]]


def _lock_client(pk):
    """BUG-640 : verrouille la ligne client (PostgreSQL) puis la relit. Même motif que le
    verrou de `Node` dans `_make_receipt_number` : verrou sur une requête d'identifiants,
    lecture ordinaire ensuite (le Meta.ordering de Client joint core_node)."""
    list(Client.objects.select_for_update(of=('self',)).order_by().filter(pk=pk).values_list('pk', flat=True))
    return Client.objects.get(pk=pk)


def _effective_credit_limit(client, node, config):
    """
    Plafond de crédit effectivement opposable à ce client sur ce nœud.

    Décision client du 2026-10-22 (docs/architecture/SYNC.md §6, point H2,
    tranchée — ne plus considérer comme un point ouvert) : tant qu'un nœud
    n'a pas synchronisé depuis `config.degraded_sync_threshold_hours`, le
    plafond local effectif est réduit à `config.offline_credit_limit_ratio`
    (80 % par défaut) du plafond nominal du client, en plus de la
    notification a posteriori déjà envoyée au siège en cas de dépassement
    réel détecté après coup. Objectif : réduire — pas éliminer, c'est
    impossible sans arrêter de facturer — le risque qu'un même client
    dépasse son plafond réel en étant servi par deux boulangeries
    hors-ligne simultanément.
    """
    if node.is_sync_degraded(config.degraded_sync_threshold_hours):
        return (client.credit_limit * config.offline_credit_limit_ratio).quantize(Decimal('1'))
    return client.credit_limit


# BUG-086 : `_validate_requested_date` déplacée vers
# `core.utils.validate_requested_date` pour être partagée avec
# `treasury/views.py` (clôture de caisse datée) sans coupler `treasury` à
# `sales`. Ré-importée ici sous son nom historique pour ne toucher aucun des
# appels existants plus bas dans ce fichier.


def _combine_date_with_now_time(target_date, node=None):
    """
    Construit un `datetime` aware pour `target_date`, en conservant l'heure
    courante (plutôt que minuit) — utilisé pour `delivered_at` quand une
    date antérieure est choisie mais qu'aucune heure de livraison explicite
    n'est fournie (BUG-083). Si `target_date` est aujourd'hui, équivalent à
    `timezone.now()`.

    BUG-247 (décision client 2026-11-12) : la date est le JOUR CALENDAIRE
    local, avec ou sans rotation d'équipes.
    """
    # Décision client 2026-11-12 : jour calendaire local, avec ou sans
    # rotation d'équipes (`node` n'influe plus sur le résultat).
    from datetime import datetime
    now = timezone.localtime(timezone.now())
    if target_date == now.date():
        return timezone.now()
    combined = datetime.combine(target_date, now.time())
    return timezone.make_aware(combined, now.tzinfo)


def _strict_whole_number(raw, maximum):
    """BUG-6NN : entier strict >= 0 et <= `maximum`, ou None. Refuse booléen, flottant
    (NaN, Infinity, 1e400, 1.5, 2.0), liste/objet, chaîne non décimale ou géante :
    jamais de troncature silencieuse ni d'OverflowError (500)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        n = raw
    elif isinstance(raw, str) and len(raw.strip()) <= 20 and raw.strip().isascii() and raw.strip().isdigit():
        n = int(raw.strip())
    else:
        return None
    return n if 0 <= n <= maximum else None


_MAX_DB_ID = 2_147_483_647


def _default_work_date(user):
    """
    BUG-161 (B3) : date de travail par défaut des listes (« du jour ») = celle
    du nœud de l'utilisateur ; sans nœud (HQ) : date locale. Remplace
    `date.today()` (fuseau du système, BUG-189).
    """
    node = user.node if getattr(user, 'node_id', None) else None
    return work_date_for(node)


def _make_receipt_number(node_code: str, receipt_date=None) -> str:
    """
    Numéro de reçu `<code>-<AAAAMMJJ>-<NNNN>`. `receipt_date` = `invoice_date`
    de la facture (BUG-197 : préfixe ET compteur portent sur le MÊME jour, y
    compris pour une vente rétroactive) ; défaut : date locale (jamais
    `date.today()`, BUG-189). Format inchangé.

    Unicité (BUG-197) : le compteur est `nombre de factures du (nœud, jour) + 1`,
    puis on avance tant que le numéro existe déjà (numéros hérités d'avant le
    correctif dont le préfixe ne suivait pas `invoice_date`). La concurrence
    reste couverte comme avant : appel dans la transaction de création
    (verrou d'écriture SQLite + retentative BUG-062) ; sur un SGBD à verrous
    de lignes, on verrouille en plus la ligne du nœud.
    """
    receipt_date = receipt_date or timezone.localdate()
    if transaction.get_connection().in_atomic_block:
        list(Node.objects.select_for_update().filter(code=node_code).values_list('pk', flat=True))
    count = Invoice.objects.filter(node__code=node_code, invoice_date=receipt_date).count() + 1
    prefix = f"{node_code}-{receipt_date.strftime('%Y%m%d')}-"
    while Invoice.objects.filter(receipt_number=f"{prefix}{count:04d}").exists():
        count += 1
    return f"{prefix}{count:04d}"


def _record_debt_movement_after_commit(client, amount, kind, node_origin, invoice, note):
    """
    Planifie l'écriture du `DebtMovement` (trace additive pour la future
    synchronisation, SYNC.md §2.2) APRÈS que la transaction de création de
    facture ait réellement validé — jamais à l'intérieur de celle-ci.

    Pourquoi : la facture, ses lignes, le déstockage et la mise à jour
    `Client.current_debt` via `F()` sont déjà, ensemble, une transaction
    SQLite assez chargée sous forte concurrence (10 facturiers simultanés sur
    le même client — voir `sales.tests.test_invoices.ConcurrentInvoiceBPTests`,
    déjà flaky sous SQLite avant tout ajout de ce ticket : vérifié en isolant
    expérimentalement cette écriture, voir rapport d'agent). Ajouter
    l'écriture d'un modèle supplémentaire À L'INTÉRIEUR de cette même
    transaction, avec ses propres retentatives, allongerait la durée pendant
    laquelle ses verrous restent tenus sans aucun bénéfice — `transaction.on_commit`
    exécute ce mouvement dans sa propre petite transaction, une fois que la
    transaction principale a déjà relâché tous ses verrous, pour ne jamais
    ajouter de contention à ce chemin déjà sensible. Sans effet sur
    PostgreSQL en production (verrouillage de ligne, pas de verrou fichier
    global) ; sans effet non plus dans les tests `TestCase` classiques
    (transaction jamais validée, délibérément annulée en fin de test) — seul
    `TransactionTestCase` ou un vrai serveur exécutent réellement ce
    callback, ce qui est le comportement attendu.
    """
    def _write():
        from sync.services import record_debt_movement
        record_debt_movement(client, amount, kind, node_origin=node_origin, invoice=invoice, note=note)
    transaction.on_commit(_write)


def _warn_if_commission_period_locked(invoice, client):
    """
    BUG-083, décision client §3 : si la facture (rétroactive) tombe dans une
    `CommissionPeriod` déjà `is_closed`, ou si ce client y a déjà une
    `ClientCommission.is_paid=True`, avertit la Direction/le Comptable au
    lieu de recalculer silencieusement une commission déjà verrouillée ou
    payée. Jamais de blocage, jamais de recalcul automatique ici — seul un
    utilisateur habilité peut régénérer explicitement la période concernée
    (`CommissionPeriodViewSet.generate`) si souhaité.
    """
    from commissions.models import CommissionPeriod, ClientCommission

    period = CommissionPeriod.objects.filter(
        node=invoice.node, month=invoice.invoice_date.month, year=invoice.invoice_date.year,
    ).first()
    if period is None:
        return

    already_paid = period.is_closed and ClientCommission.objects.filter(
        period=period, client=client, is_paid=True
    ).exists()

    if period.is_closed:
        create_notification(
            title=f"Vente rétroactive dans une période close — {client.full_name}",
            message=(
                f"Facture {invoice.receipt_number} datée du {invoice.invoice_date} ajoutée "
                f"après la clôture de la période de commission {period.month:02d}/{period.year} "
                f"({invoice.node.code})."
                + (" Cette commission a déjà été PAYÉE — elle ne sera PAS recalculée "
                   "automatiquement." if already_paid else
                   " Régénérez manuellement cette période si vous souhaitez que la commission "
                   "en tienne compte.")
            ),
            severity='DANGER' if already_paid else 'WARNING',
            node_origin=invoice.node.code,
        )
        log_activity(
            invoice.facturier, "Vente rétroactive — période CM close",
            f"Facture {invoice.receipt_number} ({invoice.invoice_date}) dans la période "
            f"{period.month:02d}/{period.year} déjà close{' et payée' if already_paid else ''}.",
            node_origin=invoice.node.code,
        )


class InvoiceViewSet(
    NoNodeGuardMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    # BUG-215 : pas de `update`/`destroy` génériques — une facture est
    # immuable (« grande trace » BUG-097) ; toute correction passe par les
    # actions métier `cancel` / `adjust` (et `deliver`). Seule exception
    # (BUG-233) : `partial_update` = PATCH de `commission_exempt` UNIQUEMENT.
    queryset = Invoice.objects.select_related(
        'node', 'client', 'facturier', 'livreur'
    ).prefetch_related('lines__bread_price').all()
    serializer_class = InvoiceSerializer
    filter_backends  = [DjangoFilterBackend, BoundedSearchFilter, filters.OrderingFilter]
    filterset_fields = ['node', 'status', 'payment_type', 'invoice_date', 'client', 'adjusts', 'is_adjustment']
    search_fields    = ['receipt_number', 'client__first_name', 'client__last_name', 'client__code']
    ordering_fields  = ['invoice_date', 'order_total', 'created_at']
    ordering         = ['-created_at']

    def get_permissions(self):
        # BUG-031 : les `@action(permission_classes=...)` déclarées sur `cancel`,
        # `cleanup_expired`, etc. sont ignorées par DRF si `get_permissions()` est
        # surchargée sans en tenir compte — DRF appelle bien `get_permissions()`,
        # pas les kwargs du décorateur, pour construire la liste effective de
        # permissions. On respecte donc en priorité la permission déclarée sur
        # l'action elle-même (`self.action_map` / l'attribut posé par `@action`),
        # et on ne retombe sur les permissions "historiques" ci-dessous que pour
        # les actions qui n'en déclarent pas explicitement.
        # NB : `@action(..., permission_classes=[...])` ne pose PAS un attribut
        # `permission_classes` directement sur la fonction décorée — DRF range
        # ce kwarg dans `func.kwargs['permission_classes']` (voir
        # rest_framework.decorators.action), que le routeur réinjecte ensuite
        # comme attribut d'INSTANCE (`self.permission_classes`) via
        # `ViewSetMixin.as_view` au moment de construire la vue pour CETTE
        # action précise. On lit donc `func.kwargs`, pas un faux attribut
        # `permission_classes` sur la fonction elle-même.
        action_func = getattr(self, self.action, None) if self.action else None
        action_kwargs = getattr(action_func, 'kwargs', None) or {}
        action_permission_classes = action_kwargs.get('permission_classes')
        if action_permission_classes is not None:
            return [perm() for perm in action_permission_classes]
        if self.action == 'create':
            return [IsFacturier()]
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsGerant()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        elif is_node_less_non_hq(user):
            qs = qs.none()  # compte sans boulangerie : rien (BUG-36x)
        return qs

    # BUG-233 : liste blanche STRICTE des champs modifiables par PATCH
    # (BUG-052 : « vente sans commission de 25 % », remarque.md l.190).
    _PATCHABLE_FIELDS = ('commission_exempt',)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        """
        BUG-233 : seul PATCH de `commission_exempt` est autorisé (GÉRANT et
        au-dessus, voir `get_permissions`). Tout autre champ -> 400 ; PUT et
        DELETE restent 405 (BUG-215, immuabilité BUG-097). Le taux de
        commission est recalculé : exonérée -> 0,00 ; sinon taux du client
        (BUG-210) sauf cas structurellement à 0 (vente soldée, sans client,
        NS/RG, remboursement). Aucun impact sur BP, stock ni totaux.
        """
        data = request.data
        if not hasattr(data, 'keys'):
            return Response({'detail': "Corps de requête invalide."}, status=status.HTTP_400_BAD_REQUEST)
        forbidden = sorted(k for k in data.keys() if k not in self._PATCHABLE_FIELDS)
        if forbidden:
            return Response(
                {'detail': (
                    "Une facture n'est pas modifiable directement (champ(s) refusé(s) : "
                    f"{', '.join(forbidden)}). Utilisez l'ajustement ou l'annulation."
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if 'commission_exempt' not in data:
            return Response({'detail': "Le champ commission_exempt est requis."}, status=status.HTTP_400_BAD_REQUEST)
        from rest_framework import serializers as drf_serializers
        try:
            new_value = drf_serializers.BooleanField().run_validation(data['commission_exempt'])
        except drf_serializers.ValidationError:
            return Response({'detail': "commission_exempt doit être un booléen."}, status=status.HTTP_400_BAD_REQUEST)

        invoice = self.get_object()
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status == Invoice.Status.CANCELLED:
            return Response({'detail': "Une facture annulée n'est plus modifiable."}, status=status.HTTP_400_BAD_REQUEST)
        old_rate = invoice.commission_rate
        if new_value:
            new_rate = Decimal('0.00')
        elif (
            invoice.is_soldee or invoice.client_id is None or invoice.is_debt_repayment
            or invoice.special_code in (Invoice.SpecialCode.NS, Invoice.SpecialCode.RG)
        ):
            new_rate = Decimal('0.00')
        else:
            config = Config.get_instance()
            client = invoice.client
            new_rate = client.commission_rate if client.commission_rate is not None else config.default_commission_rate
        if new_value != invoice.commission_exempt or new_rate != old_rate:
            invoice.commission_exempt = new_value
            invoice.commission_rate = new_rate
            invoice.save(update_fields=['commission_exempt', 'commission_rate', 'updated_at'])
            log_activity(
                request.user, "Facture — exonération de commission",
                f"Facture {invoice.receipt_number} : commission_exempt = {new_value} "
                f"(taux {old_rate} -> {new_rate}).",
                node_origin=invoice.node.code,
            )
            # BUG-672 : même avertissement que `adjust` / ventes rétroactives (BUG-083).
            if invoice.client_id and invoice.status == Invoice.Status.DELIVERED:
                _warn_if_commission_period_locked(invoice, invoice.client)
        return Response(InvoiceSerializer(invoice, context=self.get_serializer_context()).data)

    def _expire_visible(self):
        """BUG-318 : transition idempotente « expirée -> Non servi » à la lecture."""
        user = self.request.user
        node = user.node if (not user.can_access_all_nodes and user.node_id) else None
        expire_pending_invoices(node=node)

    def list(self, request, *args, **kwargs):
        self._expire_visible()
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """
        BUG-062 : retentative avec backoff aléatoire court sur
        `OperationalError` ("database table is locked" — contention SQLite
        minimale, reproductible à 100 % dès 2 facturiers simultanés). Chaque
        tentative relit l'état depuis le début (`_create_once`, y compris le
        numéro de reçu via `_make_receipt_number`) dans sa propre transaction
        atomique — jamais de retentative partielle à l'intérieur d'une
        transaction déjà entamée, même motif que
        `treasury.views.append_cashbook_entry` (BUG-002).
        """
        last_exc = None
        for _attempt in range(_INVOICE_CREATE_MAX_RETRIES):
            try:
                return self._create_once(request, *args, **kwargs)
            except OperationalError as exc:
                if 'locked' not in str(exc).lower():
                    raise
                last_exc = exc
                time.sleep(random.uniform(0.02, 0.15))
                continue
        raise last_exc

    @staticmethod
    def _credit_block_response(client, node, config, payment_amount, order_total_est, current_work_date):
        """Blocage de crédit (CLAUDE.md §5.2) : `BP_avant >= plafond` et
        `paiement < valeur_commande` -> 403 + notification ; même règle pour le
        déficit net du mois. BUG-290 : un paiement NÉGATIF (sortie de caisse)
        est toujours inférieur à la commande : il ne contourne jamais le blocage.
        Retourne une `Response` 403, ou None si la vente est autorisée."""
        effective_limit = _effective_credit_limit(client, node, config)
        if client.current_debt >= effective_limit and payment_amount < order_total_est:
            degraded_note = (
                f" (mode dégradé : plafond réduit à {config.offline_credit_limit_ratio:.0%} du plafond nominal {client.credit_limit:,.0f} FC car {node.code} n'a pas synchronisé récemment)"
                if effective_limit != client.credit_limit else ""
            )
            create_notification(
                title=f"Facturation bloquée — {client.full_name}",
                message=f"Balance {client.current_debt:,.0f} FC ≥ plafond {effective_limit:,.0f} FC pour {client.code}.{degraded_note}",
                severity='DANGER', node_origin=node.code
            )
            return Response(
                {'detail': f"Plafond de crédit atteint ({client.current_debt:,.0f} FC ≥ {effective_limit:,.0f} FC{degraded_note}). Réglez intégralement la commande ou remboursez la dette."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Déficit net de la période de commission en cours (mois courant) :
        # COM (valeur commandée) − PAYE (versé) − CM (commission gagnée sur COM).
        # Contrôle distinct du plafond de dette brute ci-dessus (les deux règles
        # sont actives — la commission du mois ne neutralise jamais le blocage
        # basé sur la dette brute). Le même plafond effectif (réduit en mode
        # dégradé, SYNC.md §6 H2) s'applique ici aussi.
        today_ = current_work_date
        # BUG-180 : les RG livrées n'entrent pas dans le déficit du mois.
        period_agg = Invoice.objects.filter(
            client=client, status=Invoice.Status.DELIVERED,
            invoice_date__year=today_.year, invoice_date__month=today_.month,
        ).exclude(special_code=Invoice.SpecialCode.RG).aggregate(com=Sum('order_total'), paye=Sum('payment_amount'))
        period_com  = period_agg['com'] or Decimal('0')
        period_paye = period_agg['paye'] or Decimal('0')
        period_cm   = period_com * client.commission_rate
        period_deficit = period_com - period_paye - period_cm

        if period_deficit >= effective_limit and payment_amount < order_total_est:
            create_notification(
                title=f"Déficit du mois — {client.full_name}",
                message=(
                    f"Déficit net du mois {period_deficit:,.0f} FC ≥ plafond {effective_limit:,.0f} FC pour {client.code} "
                    f"(Commandé {period_com:,.0f} − Versé {period_paye:,.0f} − Commission {period_cm:,.0f})."
                ),
                severity='DANGER', node_origin=node.code
            )
            return Response(
                {'detail': (
                    f"Déficit net du mois atteint ({period_deficit:,.0f} FC ≥ {effective_limit:,.0f} FC), "
                    f"commission déduite. Réglez le déficit avant de continuer à commander pour ce client."
                )},
                status=status.HTTP_403_FORBIDDEN
            )
        return None

    @transaction.atomic
    def _create_once(self, request, *args, **kwargs):
        """Create invoice with lines. Calculates BP and locks order_total."""
        serializer = InvoiceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            # BUG-208/209/210 : en plus des erreurs par champ, un `detail`
            # en français (convention API, CLAUDE.md §4).
            def _first_message(err):
                if isinstance(err, dict):
                    return _first_message(next(iter(err.values()), ''))
                if isinstance(err, (list, tuple)):
                    return _first_message(err[0]) if err else ''
                return str(err)
            body = dict(serializer.errors)
            body['detail'] = _first_message(serializer.errors) or "Données de facture invalides."
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        # BUG-030 : un utilisateur non-HQ (ex. FACTURIER) ne doit jamais pouvoir
        # choisir le nœud de la facture via le payload — sinon il peut usurper
        # une autre boulangerie et fausser son CA/sa clôture. Seul un
        # utilisateur HQ (can_access_all_nodes) peut légitimement préciser un
        # nœud différent du sien (ou n'en avoir aucun).
        if not request.user.can_access_all_nodes:
            node_id = getattr(request.user, 'node_id', None)
        else:
            node_id = data.get('node') or getattr(request.user, 'node_id', None)
        if not node_id:
            return Response({'detail': 'Nœud non spécifié et utilisateur sans nœud assigné.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            node = Node.objects.get(pk=node_id)
        except Node.DoesNotExist as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-161 (B2) : rotation d'équipes — si activée pour ce nœud, la
        # facturation (vente ET remboursement) est bloquée tant que l'équipe
        # de service de la journée de travail n'est pas désignée ; la facture
        # porte alors l'équipe désignée (pas `request.user.team`).
        # BUG-183 : une vente rétroactive (`invoice_date` passée) porte l'équipe
        # désignée pour SA journée de travail ; sans désignation, repli sur
        # `request.user.team` (jamais de blocage pour une vente passée).
        invoice_team = request.user.team
        if node.team_rotation_enabled:
            requested_date_raw = data.get('invoice_date')
            if requested_date_raw and requested_date_raw != work_date_for(node):
                # Décision 2026-11-12 : la date de la vente est calendaire ;
                # l'équipe est celle de service à l'heure (locale) de la
                # vente rétroactive, jour demandé + heure courante.
                from core.workday import current_team
                past_team = None
                try:
                    past_day = (
                        requested_date_raw if hasattr(requested_date_raw, 'year')
                        else _date_cls.fromisoformat(str(requested_date_raw))
                    )
                    past_team = current_team(node, _combine_date_with_now_time(past_day, node))
                except (ValueError, TypeError):
                    past_team = None
                if past_team:
                    invoice_team = past_team
            else:
                from core.workday import current_team
                service_team = current_team(node)
                if service_team is None:
                    return Response(
                        {'detail': "Désignez l'équipe de service du jour avant de facturer.",
                         'code': 'TEAM_NOT_ASSIGNED'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                invoice_team = service_team

        client = None
        client_id = data.get('client')
        if client_id:
            try:
                # BUG-640 : ligne client verrouillée (lecture de `current_debt` pour le
                # plafond, `debt_before`/`debt_after`) jusqu'à la fin de la transaction.
                client = _lock_client(client_id)
            except Client.DoesNotExist as e:
                return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        config = Config.get_instance()

        # BUG-083 (« ventes passées », remarque.md l.360) : date de facturation
        # optionnelle dans le payload. Comportement par défaut strictement
        # inchangé (date du jour) tant que ni `invoice_date` n'est fourni ni
        # différent d'aujourd'hui.
        # BUG-161 (B3) : date de travail du nœud (date locale hors rotation).
        current_work_date = work_date_for(node)
        requested_invoice_date = data.get('invoice_date') or current_work_date
        date_error = _validate_requested_date(
            requested_invoice_date, config, field_label="La date de facturation (invoice_date)", node=node,
        )
        if date_error:
            return Response({'detail': date_error}, status=status.HTTP_400_BAD_REQUEST)
        is_backdated_invoice = requested_invoice_date < current_work_date

        is_debt_repayment  = data.get('is_debt_repayment', False)
        is_soldee          = data.get('is_soldee', False)
        # BUG-052 : case « vente sans commission de 25 % », distincte de
        # « vente solde » (remarque.md l.190) — force CM=0 sur une facture
        # NORMALE (prix catalogue plein, BP suivie normalement). Volontairement
        # jamais lu par `InvoiceLine.save()` ni `Invoice.compute_debt_after()`.
        commission_exempt = data.get('commission_exempt', False)
        special_code       = data.get('special_code', '')
        motif              = data.get('motif', '')
        lines_data        = data.get('lines', [])

        if not is_debt_repayment and len(lines_data) == 0:
            return Response({'detail': 'Au moins une ligne de pain est requise.'}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-973 (remarque.md l.464/488) : après l'heure de clôture, plus de vente
        # tant que la direction n'a pas validé la clôture du jour. Ni les
        # remboursements BP ni les ventes rétroactives ne sont concernés.
        if not is_debt_repayment and not is_backdated_invoice:
            from treasury.closure_lock import sales_blocked_for, SALES_BLOCKED_DETAIL
            if sales_blocked_for(node):
                # BUG-987 : une seule notification par boulangerie et par jour tant qu'elle
                # n'est pas lue (un POS qui re-tente ne doit pas inonder le centre d'alertes).
                from core.models import SystemNotification
                blocked_title = f"Ventes bloquées — {node.code}"
                day_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
                if not SystemNotification.objects.filter(
                        title=blocked_title, node_origin=node.code, is_read=False,
                        created_at__gte=day_start).exists():
                    create_notification(
                        title=blocked_title,
                        message=f"Tentative de vente par {request.user.username} après l'heure de clôture, clôture du jour non validée.",
                        severity='WARNING', node_origin=node.code,
                    )
                return Response({'detail': SALES_BLOCKED_DETAIL}, status=status.HTTP_403_FORBIDDEN)

        # BUG-988 : une vente antidatée sur un jour dont la clôture est confirmée est refusée
        # (cohérent avec BUG-961 pour les dépenses) ; sur un jour non clôturé elle reste permise.
        if is_backdated_invoice and not is_debt_repayment:
            from treasury.models import CashClosure
            if CashClosure.objects.filter(node=node, date=requested_invoice_date, is_validated=True).exists():
                return Response(
                    {'detail': f"Vente refusée : la clôture du {requested_invoice_date} est déjà confirmée "
                               "par la direction, aucune vente ne peut plus y être ajoutée."},
                    status=status.HTTP_403_FORBIDDEN)

        payment_amount = data['payment_amount']

        # BUG-177 : NS (non servi) et RG (régularisation) — écritures de
        # classeur (K6!L12:L13), pas des ventes ordinaires.
        is_ns = special_code == Invoice.SpecialCode.NS and not is_debt_repayment
        is_rg = special_code == Invoice.SpecialCode.RG and not is_debt_repayment
        if is_rg or (is_ns and data['payment_type'] != Invoice.PaymentType.CREDIT):
            # RG : ni paiement ni dette. NS au comptant : rien n'a été remis,
            # aucune dette (seul NS à crédit conserve `order_total - paiement`).
            payment_amount = Decimal('0.00')

        # BUG-646 : un client désactivé ne peut plus être facturé (vente) ; un
        # versement/remboursement de sa dette reste accepté (la dette subsiste).
        if client is not None and not client.is_active and not is_debt_repayment:
            return Response(
                {'detail': "Ce client est désactivé : il ne peut plus être facturé."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if is_debt_repayment:
            # Pure repayment — no bread lines, no stock deduction, commission = 0
            if client is None:
                return Response({'detail': 'Un client doit être sélectionné pour un remboursement BP.'}, status=status.HTTP_400_BAD_REQUEST)
            # BUG-213 : un versement à 0 FC n'a aucun effet (ni BP ni caisse)
            # mais consommerait un numéro de reçu.
            # BUG-290 (décision client 2026-11-14) : un montant NÉGATIF est
            # accepté : sortie de caisse (retrait d'épargne, emprunt boulanger,
            # manquant d'équipe) ; BP après = BP avant - paiement (la BP augmente).
            if payment_amount == 0:
                return Response({'detail': 'Le montant du versement ne peut pas être nul (0 FC).'}, status=status.HTTP_400_BAD_REQUEST)
            if payment_amount < 0:
                # Une sortie de caisse ne contourne pas le blocage de crédit.
                blocked = self._credit_block_response(
                    client, node, config, payment_amount, Decimal('0'), current_work_date)
                if blocked is not None:
                    return blocked
            debt_before = client.current_debt
            invoice = Invoice.objects.create(
                node=node, client=client,
                facturier=request.user, team=invoice_team,
                payment_type='CASH',
                payment_amount=payment_amount,
                debt_before=debt_before,
                order_total=0,
                commission_rate='0.00',
                is_soldee=False,
                is_debt_repayment=True,
                special_code='',   # BUG-673 : un remboursement BP n'est ni NS ni RG
                motif=motif,
                node_origin=node.code,
                receipt_number=_make_receipt_number(node.code, requested_invoice_date),
                status=Invoice.Status.DELIVERED,
                invoice_date=requested_invoice_date,
                delivered_at=_combine_date_with_now_time(requested_invoice_date, node),
            )
            invoice.debt_after = debt_before - payment_amount
            invoice.save(update_fields=['debt_after', 'status', 'delivered_at'])
            if is_backdated_invoice:
                _warn_if_commission_period_locked(invoice, client)
            Client.objects.filter(pk=client.pk).update(current_debt=F('current_debt') - payment_amount)
            if payment_amount != 0:
                # Trace additive en parallèle (sync.services.record_debt_movement),
                # consommée par le Cloud lors d'une future synchronisation — ne
                # remplace jamais la mise à jour F() ci-dessus, voir docstring.
                _record_debt_movement_after_commit(
                    client, -payment_amount, DebtMovement.Kind.REPAYMENT,
                    node_origin=node.code, invoice=invoice,
                    note=f"Remboursement {invoice.receipt_number}",
                )
            client.refresh_from_db()
            client.refresh_category()
            client.save(update_fields=['category'])
            log_activity(
                request.user, "Remboursement BP",
                f"Remboursement {invoice.receipt_number} — {client.full_name} : {payment_amount} FC versé, BP {invoice.debt_after} FC."
                + (f" Motif : {invoice.get_motif_display()}." if motif else ""),
                node_origin=node.code
            )
            return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)

        # Standard invoice flow
        # BUG-063 : `bread_price` peut arriver en chaîne JSON (ex. "1") selon
        # le client HTTP — on normalise systématiquement en `int` AVANT toute
        # comparaison avec les clés de `bp_map` (elles-mêmes des `int`, car
        # `bp.pk` est un entier), sinon `'1' not in {1: ...}` est vrai en
        # Python même quand le `BreadPrice` existe réellement.
        try:
            bp_ids = [int(ld['bread_price']) for ld in lines_data]
        except (TypeError, ValueError):
            return Response({'detail': "Identifiant de pain invalide."}, status=status.HTTP_400_BAD_REQUEST)
        bp_map = {bp.pk: bp for bp in BreadPrice.objects.filter(pk__in=bp_ids)}
        missing = [i for i in bp_ids if i not in bp_map]
        if missing:
            return Response({'detail': f"BreadPrice(s) introuvable(s) : {missing}"}, status=status.HTTP_400_BAD_REQUEST)
        # BUG-646 : catégorie de pain désactivée -> non vendable.
        inactive = sorted({bp.label for bp in bp_map.values() if not bp.is_active})
        if inactive:
            return Response(
                {'detail': f"Catégorie(s) de pain désactivée(s) : {', '.join(inactive)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # BUG-092 : si la facture est soldée, `InvoiceLine.save()` facture
        # chaque ligne à 75 % du catalogue (CLAUDE.md §5.1) — l'estimation
        # utilisée ci-dessous pour le contrôle de plafond doit refléter ce
        # même prix réduit, sinon elle surestime systématiquement
        # `order_total` réel et peut bloquer à tort une vente soldée que le
        # client pourrait pourtant régler intégralement au prix réduit.
        def _effective_unit_price(bp):
            if is_soldee:
                return int((Decimal(bp.unit_price) * SOLDEE_PRICE_RATIO).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            return bp.unit_price
        order_total_est = sum(
            _effective_unit_price(bp_map[int(ld['bread_price'])]) * ld['quantity'] for ld in lines_data
        )

        # BUG-214 : une vente sans client (« CLIENT DIVERS ») est au comptant ;
        # aucune dette ne serait traçable. NS/RG (écritures de classeur) exclues.
        if client is None and not is_ns and not is_rg and (
            data['payment_type'] == Invoice.PaymentType.CREDIT or payment_amount < order_total_est
        ):
            return Response(
                {'detail': 'Une vente sans client doit être réglée au comptant : versez au moins la valeur de la commande ou sélectionnez un client.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # BUG-669 : sans client, le surplus versé est rendu (comme en livraison
        # partielle) : l'encaissement ne dépasse jamais la valeur de la commande.
        if client is None and not is_ns and not is_rg and payment_amount > order_total_est:
            payment_amount = Decimal(order_total_est)

        # Credit block applies only when a client is selected — jamais pour
        # une NS (BUG-177 : écriture de régularisation d'une commande déjà
        # prise, pas une nouvelle vente à crédit) ni pour une RG (BUG-180 :
        # sans paiement ni dette, elle compense un NS antérieur).
        if client is not None and not is_ns and not is_rg:
            blocked = self._credit_block_response(
                client, node, config, payment_amount, order_total_est, current_work_date)
            if blocked is not None:
                return blocked

        # BUG-028 : le serveur impose commission_rate=0 pour une vente soldée
        # (remarque.md l.186) ou une vente occasionnelle sans client
        # (remarque.md l.190) — jamais confiance dans la valeur envoyée par le
        # payload pour ces deux cas, même si le frontend oublie de l'envoyer.
        # BUG-052 : idem pour une facture normale explicitement exonérée de
        # commission (`commission_exempt`) — même durcissement côté serveur.
        if is_soldee or commission_exempt or client is None or is_ns or is_rg:
            comm_rate = Decimal('0.00')
        else:
            # BUG-210 : le taux vient de la configuration serveur (taux du
            # client), jamais du payload (déjà validé dans le serializer).
            comm_rate = client.commission_rate if client.commission_rate is not None else config.default_commission_rate
        debt_before = client.current_debt if client is not None else 0

        invoice = Invoice.objects.create(
            node=node, client=client,
            facturier=request.user, team=invoice_team,
            payment_type=data['payment_type'],
            payment_amount=payment_amount,
            debt_before=debt_before,
            commission_rate=comm_rate,
            is_soldee=is_soldee,
            commission_exempt=commission_exempt,
            is_debt_repayment=False,
            special_code=special_code,
            motif=motif,
            node_origin=node.code,
            receipt_number=_make_receipt_number(node.code, requested_invoice_date),
            invoice_date=requested_invoice_date,
        )

        for line_data in lines_data:
            bp = bp_map[int(line_data['bread_price'])]
            InvoiceLine.objects.create(invoice=invoice, bread_price=bp, quantity=line_data['quantity'])

        invoice.compute_order_total()
        invoice.compute_debt_after()
        invoice.save(update_fields=['order_total', 'debt_after'])

        # Deduct bread stock on sale creation (BUG-177 : jamais pour une NS —
        # les pains n'ont pas quitté la boulangerie).
        if not is_ns:
            for line in invoice.lines.select_related('bread_price').all():
                _adjust_bread_stock(node, line.bread_price, sent=line.quantity)

        # Apply debt only when a named client is involved (soldée = manquant
        # passé en perte ; NS/RG : voir `Invoice.debt_delta`)
        if client is not None:
            net_delta = invoice.debt_delta
            Client.objects.filter(pk=client.pk).update(current_debt=F('current_debt') + net_delta)
            if net_delta != 0:
                _record_debt_movement_after_commit(
                    client, net_delta, DebtMovement.Kind.ORDER,
                    node_origin=node.code, invoice=invoice,
                    note=f"Facture {invoice.receipt_number}",
                )
            client.refresh_from_db()
            client.refresh_category()
            client.save(update_fields=['category'])
            client_label = client.full_name
            if is_backdated_invoice:
                _warn_if_commission_period_locked(invoice, client)
        else:
            client_label = 'CLIENT DIVERS'

        log_activity(
            request.user, "Facturation POS",
            f"Facture {invoice.receipt_number} créée pour {client_label} — {invoice.order_total} FC.",
            node_origin=node.code
        )
        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _parse_served_lines(invoice, raw):
        """
        BUG-318 : valide `lines` = [{"id": <id ligne>, "quantity": <servi>}].
        Retourne (`{line_pk: servi}`, None) ou (None, message d'erreur 400).
        0 <= servi <= commandé, entiers ; lignes omises = servies en totalité.
        """
        if raw is None:
            return None, None
        if not isinstance(raw, list):
            return None, "« lines » doit être une liste de {id, quantity}."
        if invoice.is_adjustment:
            return None, "Une facture d'ajustement ne peut pas être livrée partiellement."
        current = {l.pk: l.quantity for l in invoice.lines.all()}
        served = {}
        for entry in raw:
            if not isinstance(entry, dict) or 'id' not in entry or 'quantity' not in entry:
                return None, "Chaque ligne doit contenir « id » et « quantity »."
            lid, qty = entry['id'], entry['quantity']
            if isinstance(lid, bool) or isinstance(qty, bool):
                return None, "Ligne ou quantité invalide."
            lid = _strict_whole_number(lid, _MAX_DB_ID)  # BUG-6NN : pas de float/NaN/inf/géant
            if lid is None:
                return None, "Identifiant de ligne invalide."
            if lid not in current:
                return None, f"La ligne {lid} n'appartient pas à cette facture."
            if lid in served:
                return None, f"La ligne {lid} est fournie plusieurs fois."
            # BUG-6NN : NaN / Infinity / 1e400 faisaient lever OverflowError/ValueError (500).
            if isinstance(qty, float):
                if qty != qty or qty in (float('inf'), float('-inf')) or qty != int(qty):
                    return None, "La quantité servie doit être un nombre entier."
                qty = int(qty)
            if isinstance(qty, int) and qty < 0:
                return None, "La quantité servie ne peut pas être négative."
            if isinstance(qty, str) and qty.strip().startswith('-') and qty.strip()[1:].isdigit():
                return None, "La quantité servie ne peut pas être négative."
            qty_int = _strict_whole_number(qty, 2_000_000_000)
            if qty_int is None:
                return None, "La quantité servie doit être un nombre entier."
            if qty_int > current[lid]:
                return None, (
                    f"La quantité servie ({qty_int}) ne peut pas dépasser la quantité commandée ({current[lid]})."
                )
            served[lid] = qty_int
        return served, None

    def _get_object_retry(self):
        # BUG-1001 : la résolution de l'objet (get_queryset + check_object_permissions) est
        # retentée sur verrou SQLite ; 404/403 restent propagés tels quels.
        return _retry_on_lock(self.get_object)

    @action(detail=True, methods=['post'], permission_classes=[IsFacturierOrLivreur])
    def deliver(self, request, pk=None):
        # BUG-650 : retentative bornée sur verrou SQLite (une transaction par tentative).
        return _retry_on_lock(lambda: self._deliver_once(request, pk))

    @transaction.atomic
    def _deliver_once(self, request, pk=None):
        """Facturier or livreur confirms physical delivery. Locks BP, updates client debt.

        BUG-318 : corps optionnel `{"lines": [{"id": <ligne>, "quantity": <servi>}]}`
        pour une livraison PARTIELLE (0 <= servi <= commandé). Valeur de commande,
        BP, stock et reçu suivent le servi ; le commandé initial est conservé
        (`initial_order_total`, `ordered_quantity`). Statut déjà NOT_SERVED -> 409.

        BUG-053 : la séquence est atomique (voir `sales.services.deliver_invoice`)."""
        invoice = self._get_object_retry()
        if invoice.special_code == Invoice.SpecialCode.NS:
            return Response(
                {'detail': "Une facture « Non Servi » ne peut pas être livrée : aucun pain n'a été remis."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if invoice.status == Invoice.Status.NOT_SERVED:
            return Response(
                {'detail': "Facture déjà non servie : elle ne peut plus être livrée."},
                status=status.HTTP_409_CONFLICT
            )
        if invoice.status != Invoice.Status.PENDING:
            return Response(
                {'detail': f"Facture déjà au statut « {invoice.get_status_display()} »."},
                status=status.HTTP_400_BAD_REQUEST
            )
        served, err = self._parse_served_lines(invoice, request.data.get('lines'))
        if err:
            return Response({'detail': err}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-083 (« ventes passées ») : `delivered_at` optionnel dans le
        # payload — une date (YYYY-MM-DD), pas un datetime complet, l'heure
        # réelle de la confirmation étant conservée (voir
        # `_combine_date_with_now_time`). Comportement par défaut (aucun
        # champ fourni) strictement inchangé : horodatage réel de l'appel.
        delivered_at_dt = None
        requested_delivery_date_raw = request.data.get('delivered_at')
        if requested_delivery_date_raw:
            from django.utils.dateparse import parse_date
            try:
                requested_delivery_date = parse_date(str(requested_delivery_date_raw)[:10])
            except ValueError:  # BUG-643 : date bien formée mais impossible (2026-02-30)
                requested_delivery_date = None
            if requested_delivery_date is None:
                return Response({'detail': "delivered_at invalide — format attendu AAAA-MM-JJ."}, status=status.HTTP_400_BAD_REQUEST)
            config = Config.get_instance()
            date_error = _validate_requested_date(
                requested_delivery_date, config, field_label="La date de livraison (delivered_at)",
                node=invoice.node,
            )
            if date_error:
                return Response({'detail': date_error}, status=status.HTTP_400_BAD_REQUEST)
            # BUG-668 : la livraison ne peut pas précéder la facture.
            if requested_delivery_date < invoice.invoice_date:
                return Response(
                    {'detail': "La date de livraison ne peut pas précéder la date de la facture "
                               f"({invoice.invoice_date.isoformat()})."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            delivered_at_dt = _combine_date_with_now_time(requested_delivery_date, invoice.node)

        try:
            invoice, _reduced = deliver_invoice(
                invoice.pk, request.user, served_quantities=served, delivered_at=delivered_at_dt,
            )
        except InvoiceStateError as exc:
            if exc.status_code == 409 and 'expiré' in exc.detail:
                mark_not_served(invoice.pk, None, auto=True)
            return Response({'detail': exc.detail}, status=exc.status_code)
        # BUG-306 : les pains livrés alimentent la fournée « en cours »
        # (déclarée par nombre de sacs) de l'équipe en service.
        from production.services import apply_delivered_invoice_to_open_batch
        batch = apply_delivered_invoice_to_open_batch(invoice)
        if batch is not None:
            log_activity(
                request.user, "Avancement Fournée",
                f"Facture {invoice.receipt_number} : fournée Éq.{batch.team} {batch.date} "
                f"à {batch.delivered_value_fc} / {batch.theoretical_yield} FC.",
                node_origin=invoice.node.code,
            )
        log_activity(
            request.user, "Livraison Confirmée",
            f"Facture {invoice.receipt_number} livrée — Nouvelle BP : {invoice.debt_after} FC.",
            node_origin=invoice.node.code
        )
        if invoice.client_id and invoice.client.category == Client.Category.RISK:
            create_notification(
                title=f"Alerte Crédit — {invoice.client.full_name}",
                message=(
                    f"Après livraison {invoice.receipt_number}, la dette de "
                    f"{invoice.client.full_name} atteint {invoice.debt_after:,.0f} FC."
                ),
                severity='DANGER', node_origin=invoice.node.code
            )
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=['post'], url_path='mark-not-served',
            permission_classes=[IsFacturierOrLivreur])
    def mark_not_served(self, request, pk=None):
        """
        BUG-318 : déclare une facture EN ATTENTE « Non servi » (corps optionnel
        `{"reason": "..."}`, 200 caractères max). Aucun pain ne sort du stock
        (la part déstockée à la création est restituée), valeur de commande
        annulée, BP rétablie ; le versement saisi est CONSERVÉ comme
        encaissement sur la BP (facture à commande 0). Statut terminal ; la
        ligne n'est jamais supprimée. Facture hors statut PENDING -> 409.
        """
        invoice = self._get_object_retry()  # filtre par nœud (404 hors périmètre)
        reason = request.data.get('reason', '')
        if reason is None:
            reason = ''
        if not isinstance(reason, str):
            return Response({'detail': "Le motif doit être un texte."}, status=status.HTTP_400_BAD_REQUEST)
        if len(reason.strip()) > 200:
            return Response({'detail': "Le motif ne peut pas dépasser 200 caractères."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            invoice = _retry_on_lock(lambda: mark_not_served(invoice.pk, request.user, reason=reason))
        except InvoiceStateError as exc:
            return Response({'detail': exc.detail}, status=exc.status_code)
        return Response(InvoiceSerializer(invoice, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], permission_classes=[IsFacturier])
    def cancel(self, request, pk=None):
        """Gérant or Facturier can cancel a PENDING order. Restores bread stock and reverses client debt."""
        invoice = self._get_object_retry()  # filtre par nœud (404 hors périmètre)
        return _retry_on_lock(lambda: self._cancel_once(request, invoice.pk))

    @transaction.atomic
    def _cancel_once(self, request, invoice_pk):
        # BUG-642 : facture verrouillée (comme `deliver_invoice`) : deux annulations
        # ou annulation + livraison simultanées ne restituent jamais deux fois.
        invoice = Invoice.objects.select_for_update(of=('self',)).select_related('node', 'client').get(pk=invoice_pk)
        if invoice.status == Invoice.Status.DELIVERED:
            return Response(
                {'detail': "Impossible d'annuler une facture déjà livrée."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # BUG-647 : seule une facture EN ATTENTE est annulable (NOT_SERVED est terminal).
        if invoice.status != Invoice.Status.PENDING:
            return Response(
                {'detail': f"Impossible d'annuler une facture au statut « {invoice.get_status_display()} »."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # BUG-648 : des ajustements liés ont déjà restitué/consommé une part ;
        # on ne restitue que le NET (originale + ajustements signés).
        adjustments = list(invoice.adjustments.filter(is_adjustment=True).prefetch_related('lines'))
        if invoice.client_id:
            client = _lock_client(invoice.client_id)
            net_delta = invoice.debt_delta + sum((a.debt_delta for a in adjustments), Decimal('0.00'))
            Client.objects.filter(pk=client.pk).update(current_debt=F('current_debt') - net_delta)
            if net_delta != 0:
                _record_debt_movement_after_commit(
                    client, -net_delta, DebtMovement.Kind.ADJUSTMENT,
                    node_origin=invoice.node.code, invoice=invoice,
                    note=f"Annulation {invoice.receipt_number}",
                )
        # Restitution du stock par catégorie (BUG-177 : une NS n'a jamais déstocké).
        if invoice.special_code != Invoice.SpecialCode.NS:
            net_by_bp = {}
            bps = {}
            for line in invoice.lines.select_related('bread_price').all():
                net_by_bp[line.bread_price_id] = net_by_bp.get(line.bread_price_id, 0) + line.quantity
                bps[line.bread_price_id] = line.bread_price
            for adj in adjustments:
                for line in adj.lines.all():
                    net_by_bp[line.bread_price_id] = (
                        net_by_bp.get(line.bread_price_id, 0) + adj.adjustment_sign * line.quantity
                    )
            for bp_id, qty in net_by_bp.items():
                if qty:
                    _adjust_bread_stock(invoice.node, bps[bp_id], sent=-qty)
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=['status'])
        # BUG-890 : les ajustements liés (créés LIVRÉS) sont neutralisés avec la mère
        # (leur part de BP/stock/compteur est déjà incluse dans le net restitué ci-dessus) :
        # ils n'apparaissent plus dans bread_summary / daily_summary.
        if adjustments:
            Invoice.objects.filter(pk__in=[a.pk for a in adjustments]).exclude(
                status=Invoice.Status.CANCELLED
            ).update(status=Invoice.Status.CANCELLED)
        if invoice.client_id:
            # BUG-665 : la BP vient d'être rétablie -> catégorie recalculée.
            client.refresh_from_db()
            client.refresh_category()
            client.save(update_fields=['category'])
        log_activity(
            request.user, "Annulation Facture",
            f"Facture {invoice.receipt_number} annulée — stock et BP restitués.",
            node_origin=invoice.node.code
        )
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=['post'], permission_classes=[IsGerant])
    def adjust(self, request, pk=None):
        """
        BUG-097 : corrige/annule une commande déjà enregistrée via une
        nouvelle facture liée (« grande trace »), jamais une mutation de
        l'originale — remarque.md, « Réclamation des agents du client »,
        point 4 ; décisions du coordinateur du 2026-10-30, voir
        docs/qa/REGISTRE_BUGS.md BUG-097.

        Réservé à GERANT et au-delà (jamais FACTURIER ni LIVREUR) — même
        niveau de permission que `cancel()` (BUG-031), la correction étant
        au moins aussi sensible qu'une annulation.

        Choix documentés (décisions coordinateur, à ne pas redevinera) :
        - `InvoiceLine.quantity` reste positif : les lignes de l'ajustement
          portent la MAGNITUDE du changement, `adjustment_sign` (+1/-1) porte
          le signe au niveau de la facture entière.
        - Stock : traité comme un retour/ajout physique de pain PAR DÉFAUT —
          `adjustment_sign=-1` restitue le stock (le pain revient),
          `adjustment_sign=+1` le décrémente comme une vente additionnelle.
          Pas de variante "sans retour physique" dans ce périmètre.
        - BP : la facture d'ajustement est traitée comme une nouvelle
          "mini-facture" liée — `order_total`/`payment_amount` portent le
          signe de l'opération, `debt_after` recalculé via la formule
          standard (`Invoice.compute_debt_after`).
        - Commission déjà clôturée : avertissement seul (jamais de blocage),
          via le mécanisme déjà existant `_warn_if_commission_period_locked`
          (BUG-083) — appelé systématiquement ici, pas seulement pour une
          date rétroactive, puisque corriger une période déjà close est
          précisément le scénario visé par ce ticket.
        """
        original = self._get_object_retry()  # filtre par nœud (404 hors périmètre)
        # BUG-663 : même retentative bornée que deliver/cancel (SQLite verrouillé).
        return _retry_on_lock(lambda: self._adjust_once(request, original.pk))

    def _adjust_once(self, request, original_pk):
        original = Invoice.objects.select_related('node', 'client').get(pk=original_pk)

        if original.status == Invoice.Status.CANCELLED:
            return Response(
                {'detail': "Impossible d'ajuster une facture annulée."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # BUG-649 : NOT_SERVED est terminal (commande 0) : un ajustement créerait une vente fantôme.
        if original.status == Invoice.Status.NOT_SERVED:
            return Response(
                {'detail': "Impossible d'ajuster une facture non servie."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if original.is_debt_repayment:
            return Response(
                {'detail': "Impossible d'ajuster un remboursement BP — ce n'est pas une commande."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if original.is_adjustment:
            return Response(
                {'detail': "Impossible d'ajuster une facture d'ajustement — ajustez toujours la facture d'origine."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = InvoiceAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        adjustment_sign = data['adjustment_sign']
        payment_magnitude = data['payment_amount']
        lines_data = data['lines']

        # BUG-6NN : id et quantité entiers stricts (pas de booléen, flottant, NaN/inf, géant) ;
        # quantité plafonnée comme à la création (MAX_LINE_QUANTITY).
        from .serializers import MAX_LINE_QUANTITY
        try:
            bp_ids = [_strict_whole_number(ld['bread_price'], _MAX_DB_ID) for ld in lines_data]
            quantities = [_strict_whole_number(ld['quantity'], MAX_LINE_QUANTITY) for ld in lines_data]
        except (TypeError, ValueError, KeyError):
            return Response({'detail': "Ligne d'ajustement invalide (bread_price/quantity)."}, status=status.HTTP_400_BAD_REQUEST)
        if any(b is None for b in bp_ids) or any(q is None for q in quantities):
            return Response({'detail': "Ligne d'ajustement invalide (bread_price/quantity)."}, status=status.HTTP_400_BAD_REQUEST)
        if any(q <= 0 for q in quantities):
            return Response({'detail': "Les quantités d'un ajustement doivent être strictement positives (le signe se règle via adjustment_sign)."}, status=status.HTTP_400_BAD_REQUEST)

        bp_map = {bp.pk: bp for bp in BreadPrice.objects.filter(pk__in=bp_ids)}
        missing = [i for i in bp_ids if i not in bp_map]
        if missing:
            return Response({'detail': f"BreadPrice(s) introuvable(s) : {missing}"}, status=status.HTTP_400_BAD_REQUEST)

        requested_qty_by_bp = {}
        for ld in lines_data:
            bp_id = int(ld['bread_price'])
            requested_qty_by_bp[bp_id] = requested_qty_by_bp.get(bp_id, 0) + int(ld['quantity'])

        config = Config.get_instance()
        current_work_date = work_date_for(original.node)
        requested_invoice_date = data.get('invoice_date') or current_work_date
        date_error = _validate_requested_date(
            requested_invoice_date, config, field_label="La date de l'ajustement (invoice_date)",
            node=original.node,
        )
        if date_error:
            return Response({'detail': date_error}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-988 : un ajustement (+) crée de la valeur ; refusé sur un jour dont la clôture est
        # confirmée (les ajustements (−) restent possibles : ils corrigent une erreur).
        if adjustment_sign == 1:
            from treasury.models import CashClosure
            if CashClosure.objects.filter(node=original.node, date=requested_invoice_date,
                                          is_validated=True).exists():
                return Response(
                    {'detail': f"Ajustement refusé : la clôture du {requested_invoice_date} est déjà confirmée "
                               "par la direction, aucune vente ne peut plus y être ajoutée."},
                    status=status.HTTP_403_FORBIDDEN)

        client = original.client
        # BUG-181 : nature de l'originale. NS : jamais de stock (rien n'a été
        # déstocké) ; NS CASH et RG : aucun paiement ni dette (comme à la
        # création). RG livrée : elle a déstocké, l'ajustement de pains
        # modifie donc le stock normalement.
        orig_is_ns = original.special_code == Invoice.SpecialCode.NS
        orig_is_rg = original.special_code == Invoice.SpecialCode.RG
        if orig_is_rg or (orig_is_ns and original.payment_type != Invoice.PaymentType.CREDIT):
            payment_magnitude = Decimal('0.00')
        # BUG-182 : équipe de service désignée si rotation active (jamais de
        # blocage ici), sinon équipe de l'utilisateur.
        adjust_team = request.user.team
        if original.node.team_rotation_enabled:
            from core.workday import current_team
            adjust_team = current_team(original.node) or adjust_team
        # BUG-052 : une facture d'ajustement reprend l'exonération de
        # commission de la facture d'origine, au même titre que `is_soldee`.
        comm_rate = (
            Decimal('0.00')
            if (original.is_soldee or original.commission_exempt or client is None)
            else client.commission_rate
        )

        with transaction.atomic():
            # BUG-661 : originale verrouillée AVANT les contrôles (ordre facture puis client,
            # comme `_cancel_once`) : statut et « net restant » lus sous verrou.
            original = Invoice.objects.select_for_update(of=('self',)).select_related('node', 'client').get(pk=original_pk)
            if original.status == Invoice.Status.CANCELLED:
                return Response({'detail': "Impossible d'ajuster une facture annulée."}, status=status.HTTP_400_BAD_REQUEST)
            if original.status == Invoice.Status.NOT_SERVED:
                return Response({'detail': "Impossible d'ajuster une facture non servie."}, status=status.HTTP_400_BAD_REQUEST)
            # Validation minimale (CLAUDE.md §4, décision coordinateur point 7) :
            # un ajustement négatif ne peut jamais retirer plus de pains, pour
            # une même catégorie, que ce qui reste net sur la facture d'origine
            # une fois les ajustements déjà appliqués pris en compte — sinon le
            # solde net de pains facturés pour cette catégorie deviendrait
            # négatif, ce qui n'a pas de sens métier (on ne peut pas reprendre
            # plus de pain qu'on en a vendu).
            if adjustment_sign == -1:
                original_qty_by_bp = {}
                for line in original.lines.all():
                    original_qty_by_bp[line.bread_price_id] = original_qty_by_bp.get(line.bread_price_id, 0) + line.quantity
                for adj in original.adjustments.filter(is_adjustment=True).exclude(status=Invoice.Status.CANCELLED).prefetch_related('lines'):
                    for line in adj.lines.all():
                        original_qty_by_bp[line.bread_price_id] = (
                            original_qty_by_bp.get(line.bread_price_id, 0) + adj.adjustment_sign * line.quantity
                        )
                for bp_id, requested_qty in requested_qty_by_bp.items():
                    remaining = original_qty_by_bp.get(bp_id, 0)
                    if requested_qty > remaining:
                        bp_label = bp_map[bp_id].label
                        return Response(
                            {'detail': (
                                f"Impossible de retirer {requested_qty} « {bp_label} » : il n'en reste que "
                                f"{remaining} net sur la facture {original.receipt_number} après les ajustements déjà enregistrés."
                            )},
                            status=status.HTTP_400_BAD_REQUEST
                        )


            if client is not None:
                # BUG-640 : `debt_before` lu sous verrou de la ligne client.
                client = _lock_client(client.pk)
            debt_before = client.current_debt if client is not None else 0

            adjustment = Invoice.objects.create(
                node=original.node, client=client,
                facturier=request.user, team=adjust_team,
                payment_type=original.payment_type,
                payment_amount=0,  # posé ensuite avec le signe, une fois les lignes créées
                debt_before=debt_before,
                commission_rate=comm_rate,
                is_soldee=original.is_soldee,
                commission_exempt=original.commission_exempt,
                is_debt_repayment=False,
                special_code='',
                node_origin=original.node.code,
                receipt_number=_make_receipt_number(original.node.code, requested_invoice_date),
                invoice_date=requested_invoice_date,
                adjusts=original,
                is_adjustment=True,
                adjustment_sign=adjustment_sign,
                status=Invoice.Status.DELIVERED,
                delivered_at=_combine_date_with_now_time(requested_invoice_date, original.node),
            )

            for ld in lines_data:
                bp = bp_map[int(ld['bread_price'])]
                InvoiceLine.objects.create(invoice=adjustment, bread_price=bp, quantity=int(ld['quantity']))

            magnitude_total = adjustment.compute_order_total()  # somme des line_total (toujours positive)
            adjustment.order_total = adjustment_sign * magnitude_total
            adjustment.payment_amount = adjustment_sign * payment_magnitude
            adjustment.compute_debt_after()
            adjustment.save(update_fields=['order_total', 'payment_amount', 'debt_after'])

            # Stock : retour physique par défaut (décision coordinateur point 2).
            # `adjustment_sign=-1` restitue le stock (sent négatif) ;
            # `adjustment_sign=+1` le décrémente comme une vente additionnelle.
            if not orig_is_ns:
                for line in adjustment.lines.select_related('bread_price').all():
                    _adjust_bread_stock(original.node, line.bread_price, sent=adjustment_sign * line.quantity)

            if client is not None:
                net_delta = adjustment.debt_delta
                Client.objects.filter(pk=client.pk).update(current_debt=F('current_debt') + net_delta)
                if net_delta != 0:
                    _record_debt_movement_after_commit(
                        client, net_delta, DebtMovement.Kind.ADJUSTMENT,
                        node_origin=original.node.code, invoice=adjustment,
                        note=f"Ajustement {adjustment.receipt_number} de la facture {original.receipt_number}",
                    )
                # BUG-824 : le compteur de pains livrés suit l'ajustement (signé),
                # sauf NS (aucun pain n'a été remis). Jamais négatif.
                # BUG-666 : facture encore EN ATTENTE -> rien n'est livré, le compteur sera
                # alimenté net des ajustements par `Invoice.deliver`.
                if not orig_is_ns and original.status == Invoice.Status.DELIVERED:
                    pains_delta = adjustment_sign * sum(l.quantity for l in adjustment.lines.all())
                    if pains_delta:
                        Client.objects.filter(pk=client.pk).update(
                            total_breads_received=Greatest(F('total_breads_received') + pains_delta, 0)
                        )
                client.refresh_from_db()
                client.refresh_category()
                client.save(update_fields=['category'])
                client_label = client.full_name
            else:
                client_label = 'CLIENT DIVERS'

            # BUG-083 : avertit (jamais ne bloque) si la période de commission
            # est déjà close — systématique ici, pas seulement en cas de date
            # rétroactive, puisque corriger une période close est le scénario
            # principal visé par ce ticket.
            if client is not None:
                _warn_if_commission_period_locked(adjustment, client)

            log_activity(
                request.user, "Ajustement Facture",
                (
                    f"Ajustement {adjustment.receipt_number} ({'+' if adjustment_sign > 0 else '−'}) "
                    f"de la facture {original.receipt_number} pour {client_label} — "
                    f"{adjustment.order_total} FC, versement {adjustment.payment_amount} FC."
                ),
                node_origin=original.node.code
            )

        return Response(InvoiceSerializer(adjustment).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], permission_classes=[IsGerant])  # BUG-284
    def cleanup_expired(self, request):
        """
        BUG-318 : les factures PENDING de plus de 12 h ne sont PLUS supprimées :
        elles passent en « Non servi » (motif « Expirée automatiquement »,
        BP et stock rétablis, trace conservée). Idempotent. La clé `deleted`
        est conservée (toujours 0) pour compatibilité ; `expired` = nombre
        de factures passées en « Non servi ».
        """
        user = request.user
        node = user.node if (not user.can_access_all_nodes and user.node_id) else None
        n = expire_pending_invoices(node=node)
        return Response({'expired': n, 'deleted': 0})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def pending_deliveries(self, request):
        """Livreur screen: all non-expired PENDING invoices of the node.

        BUG-274 : indépendant de la date du jour (une facture créée à 23:55
        reste listée après minuit) ; bornée par l'expiration de 12 h de
        `cleanup_expired`.
        """
        self._expire_visible()
        cutoff = expiry_cutoff()
        qs = self.get_queryset().filter(
            status=Invoice.Status.PENDING, created_at__gte=cutoff,
        ).exclude(special_code=Invoice.SpecialCode.NS)  # BUG-177 : NS jamais livrable
        return Response(InvoiceSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def daily_summary(self, request):
        """
        Cash collected vs credit extended for a given date (defaults to today).

        A single invoice can be partially paid (e.g. order 100 000 FC, payment
        55 000 FC): the CASH bucket must reflect the 55 000 FC actually
        collected and CREDIT the 45 000 FC newly owed — not the invoice's
        order_total dumped wholesale into whichever bucket matches its
        nominal payment_type, which used to hide any cash collected on a
        CREDIT invoice.
        """
        target_date = request.query_params.get('date') or str(_default_work_date(request.user))
        # BUG-527 : date illisible / impossible -> 400, jamais 500.
        _d, _err = parse_date_param(target_date, 'date')
        if _err:
            return Response({'detail': _err}, status=status.HTTP_400_BAD_REQUEST)
        # BUG-275 : date de référence d'une vente = date de LIVRAISON (jour
        # calendaire), comme bread_summary, le rapport facturier et la clôture.
        # BUG-670 : le versement CONSERVÉ d'une facture « Non servi » (BUG-318/320) est un
        # encaissement réel, daté du jour du « non servi » (commande 0 -> CREDIT négatif).
        qs = self.get_queryset().filter(
            Q(delivered_at__date=target_date, status=Invoice.Status.DELIVERED)
            | Q(not_served_at__date=target_date, status=Invoice.Status.NOT_SERVED, payment_amount__gt=0)
        )
        # Décote d'une VENTE SOLDE/CASH : jamais une créance, exclue du CREDIT
        # (cohérent avec debt_delta = 0 pour is_soldee).
        per_node = qs.values('node__code').annotate(
            cash=Sum('payment_amount'), order_value=Sum('order_total'), count=Count('id', filter=Q(status=Invoice.Status.DELIVERED)),
            solde_cash=Sum('payment_amount', filter=Q(is_soldee=True)),
            solde_value=Sum('order_total', filter=Q(is_soldee=True)),
            # BUG-287 : une RG a une variation de BP nulle (debt_delta = 0).
            rg_cash=Sum('payment_amount', filter=Q(special_code=Invoice.SpecialCode.RG, is_soldee=False)),
            rg_value=Sum('order_total', filter=Q(special_code=Invoice.SpecialCode.RG, is_soldee=False)),
        )
        summary = []
        for row in per_node:
            cash = row['cash'] or 0
            excl_value = (row['solde_value'] or 0) + (row['rg_value'] or 0)
            excl_cash = (row['solde_cash'] or 0) + (row['rg_cash'] or 0)
            credit = ((row['order_value'] or 0) - excl_value) - (cash - excl_cash)
            summary.append({'node__code': row['node__code'], 'payment_type': 'CASH', 'total': cash, 'count': row['count']})
            summary.append({'node__code': row['node__code'], 'payment_type': 'CREDIT', 'total': credit, 'count': 0})
        return Response(summary)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def bread_summary(self, request):
        """Pains vendus par catégorie (unit_price) pour les factures livrées à une date donnée."""
        from datetime import date as _date
        from django.db.models import Q
        from core.workday import delivered_on_work_date_filter
        user = request.user
        date_str = request.query_params.get('date') or str(_default_work_date(user))
        try:
            target_date = _date.fromisoformat(date_str)
        except ValueError:
            return Response({'detail': 'Date invalide (format AAAA-MM-JJ attendu).'}, status=status.HTTP_400_BAD_REQUEST)
        node_param = request.query_params.get('node')
        # BUG-212 : périmètre par nœud. Un utilisateur non-HQ rattaché à une
        # boulangerie ne voit que la sienne ; `?node=` d'un autre nœud -> 403.
        if not user.can_access_all_nodes and user.node_id:
            if node_param and str(node_param) != str(user.node_id):
                return Response({'detail': "Accès refusé : vous ne pouvez consulter que votre boulangerie."}, status=status.HTTP_403_FORBIDDEN)
            nodes = Node.objects.filter(pk=user.node_id)
        elif is_node_less_non_hq(user):
            nodes = Node.objects.none()  # compte sans boulangerie : rien
        elif node_param:
            # BUG-6NN : entier strict borné (« 1e400 », « 9…9 » géant -> 400, pas de surprise).
            node_pk = _strict_whole_number(node_param, _MAX_DB_ID)
            if node_pk is None:
                return Response({'detail': 'Boulangerie invalide.'}, status=status.HTTP_400_BAD_REQUEST)
            nodes = Node.objects.filter(pk=node_pk)
        else:
            nodes = Node.objects.all()
        # BUG-211 : « livré le » = journée de travail du nœud (relève à
        # relève en rotation), via la source unique core/workday.py.
        cond = Q(pk__in=[])
        for n in nodes:
            cond |= Q(invoice__node=n, **delivered_on_work_date_filter(n, target_date, 'invoice__delivered_at'))
        qs = InvoiceLine.objects.filter(invoice__status='DELIVERED').filter(cond)
        # BUG-664 : une facture d'ajustement porte la MAGNITUDE en lignes ; le signe
        # (`adjustment_sign`) s'applique aux quantités et aux montants.
        from django.db.models import Case, When, Value, IntegerField
        sign = Case(
            When(invoice__is_adjustment=True, then=F('invoice__adjustment_sign')),
            default=Value(1), output_field=IntegerField(),
        )
        qs = qs.annotate(signed_qty=F('quantity') * sign, signed_fc=F('line_total') * sign)
        summary = (
            qs.values('unit_price')
              .annotate(total_qty=Sum('signed_qty'), total_fc=Sum('signed_fc'))
              .order_by('unit_price')
        )
        totals = qs.aggregate(grand_qty=Sum('signed_qty'), grand_fc=Sum('signed_fc'))
        return Response({
            'by_category': list(summary),
            'grand_total_qty': totals['grand_qty'] or 0,
            'grand_total_fc': float(totals['grand_fc'] or 0),
        })
