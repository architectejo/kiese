import random
import time
from datetime import date as _date_cls
from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Sum, Count
from django.utils import timezone
from rest_framework import viewsets, status, filters, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from core.models import Node, BreadPrice, Config
from core.permissions import IsFacturier, IsLivreur, IsGerant, IsFacturierOrLivreur
from core.utils import log_activity, create_notification, validate_requested_date as _validate_requested_date
from core.workday import work_date_for
from clients.models import Client
from production.models import _adjust_bread_stock
from sync.models import DebtMovement
from .models import Invoice, InvoiceLine, SOLDEE_PRICE_RATIO
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
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
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
        return Response(InvoiceSerializer(invoice, context=self.get_serializer_context()).data)

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
                client = Client.objects.get(pk=client_id)
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
        lines_data        = data.get('lines', [])

        if not is_debt_repayment and len(lines_data) == 0:
            return Response({'detail': 'Au moins une ligne de pain est requise.'}, status=status.HTTP_400_BAD_REQUEST)

        payment_amount = data['payment_amount']

        # BUG-177 : NS (non servi) et RG (régularisation) — écritures de
        # classeur (K6!L12:L13), pas des ventes ordinaires.
        is_ns = special_code == Invoice.SpecialCode.NS and not is_debt_repayment
        is_rg = special_code == Invoice.SpecialCode.RG and not is_debt_repayment
        if is_rg or (is_ns and data['payment_type'] != Invoice.PaymentType.CREDIT):
            # RG : ni paiement ni dette. NS au comptant : rien n'a été remis,
            # aucune dette (seul NS à crédit conserve `order_total - paiement`).
            payment_amount = Decimal('0.00')

        if is_debt_repayment:
            # Pure repayment — no bread lines, no stock deduction, commission = 0
            if client is None:
                return Response({'detail': 'Un client doit être sélectionné pour un remboursement BP.'}, status=status.HTTP_400_BAD_REQUEST)
            # BUG-213 : un remboursement à 0 FC n'a aucun effet (ni BP ni
            # versement) mais consommerait un numéro de reçu.
            if payment_amount <= 0:
                return Response({'detail': 'Le montant du remboursement doit être supérieur à 0 FC.'}, status=status.HTTP_400_BAD_REQUEST)
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
                special_code=special_code,
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
                f"Remboursement {invoice.receipt_number} — {client.full_name} : {payment_amount} FC versé, BP {invoice.debt_after} FC.",
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

        # Credit block applies only when a client is selected — jamais pour
        # une NS (BUG-177 : écriture de régularisation d'une commande déjà
        # prise, pas une nouvelle vente à crédit) ni pour une RG (BUG-180 :
        # sans paiement ni dette, elle compense un NS antérieur).
        if client is not None and not is_ns and not is_rg:
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

    @action(detail=True, methods=['post'], permission_classes=[IsFacturierOrLivreur])
    @transaction.atomic
    def deliver(self, request, pk=None):
        """Facturier or livreur confirms physical delivery. Locks BP, updates client debt.

        BUG-053 : `Invoice.deliver()` est désormais atomique (voir sales/models.py),
        mais cette vue effectue aussi `log_activity`/`create_notification` après —
        on l'enveloppe également pour que toute la séquence réussisse ou échoue
        ensemble, comme `create()` ci-dessus."""
        invoice = self.get_object()
        if invoice.special_code == Invoice.SpecialCode.NS:
            return Response(
                {'detail': "Une facture « Non Servi » ne peut pas être livrée : aucun pain n'a été remis."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if invoice.status != Invoice.Status.PENDING:
            return Response(
                {'detail': f"Facture déjà au statut « {invoice.get_status_display()} »."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # BUG-083 (« ventes passées ») : `delivered_at` optionnel dans le
        # payload — une date (YYYY-MM-DD), pas un datetime complet, l'heure
        # réelle de la confirmation étant conservée (voir
        # `_combine_date_with_now_time`). Comportement par défaut (aucun
        # champ fourni) strictement inchangé : horodatage réel de l'appel.
        delivered_at_dt = None
        requested_delivery_date_raw = request.data.get('delivered_at')
        if requested_delivery_date_raw:
            from django.utils.dateparse import parse_date
            requested_delivery_date = parse_date(str(requested_delivery_date_raw)[:10])
            if requested_delivery_date is None:
                return Response({'detail': "delivered_at invalide — format attendu AAAA-MM-JJ."}, status=status.HTTP_400_BAD_REQUEST)
            config = Config.get_instance()
            date_error = _validate_requested_date(
                requested_delivery_date, config, field_label="La date de livraison (delivered_at)",
                node=invoice.node,
            )
            if date_error:
                return Response({'detail': date_error}, status=status.HTTP_400_BAD_REQUEST)
            delivered_at_dt = _combine_date_with_now_time(requested_delivery_date, invoice.node)

        invoice.deliver(request.user, delivered_at=delivered_at_dt)
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

    @action(detail=True, methods=['post'], permission_classes=[IsFacturier])
    def cancel(self, request, pk=None):
        """Gérant or Facturier can cancel a PENDING order. Restores bread stock and reverses client debt."""
        invoice = self.get_object()
        if invoice.status == Invoice.Status.DELIVERED:
            return Response(
                {'detail': "Impossible d'annuler une facture déjà livrée."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if invoice.status == Invoice.Status.PENDING:
            if invoice.client_id:
                # Reverse only the debt that was actually applied at creation
                net_delta = invoice.debt_delta
                Client.objects.filter(pk=invoice.client_id).update(
                    current_debt=F('current_debt') - net_delta
                )
                if net_delta != 0:
                    _record_debt_movement_after_commit(
                        invoice.client, -net_delta, DebtMovement.Kind.ADJUSTMENT,
                        node_origin=invoice.node.code, invoice=invoice,
                        note=f"Annulation {invoice.receipt_number}",
                    )
            # Restore bread stock per category (BUG-177 : une NS n'a jamais
            # déstocké, rien à restituer)
            if invoice.special_code != Invoice.SpecialCode.NS:
                for line in invoice.lines.select_related('bread_price').all():
                    _adjust_bread_stock(invoice.node, line.bread_price, sent=-line.quantity)
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=['status'])
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
        original = self.get_object()

        if original.status == Invoice.Status.CANCELLED:
            return Response(
                {'detail': "Impossible d'ajuster une facture annulée."},
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

        try:
            bp_ids = [int(ld['bread_price']) for ld in lines_data]
            quantities = [int(ld['quantity']) for ld in lines_data]
        except (TypeError, ValueError, KeyError):
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
            for adj in original.adjustments.filter(is_adjustment=True).prefetch_related('lines'):
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

        config = Config.get_instance()
        current_work_date = work_date_for(original.node)
        requested_invoice_date = data.get('invoice_date') or current_work_date
        date_error = _validate_requested_date(
            requested_invoice_date, config, field_label="La date de l'ajustement (invoice_date)",
            node=original.node,
        )
        if date_error:
            return Response({'detail': date_error}, status=status.HTTP_400_BAD_REQUEST)

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

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def cleanup_expired(self, request):
        """Delete PENDING invoices older than 12 h and reverse client debts."""
        from datetime import timedelta
        from django.utils import timezone
        cutoff = timezone.now() - timedelta(hours=12)
        expired = list(
            self.get_queryset()
                .filter(status=Invoice.Status.PENDING, created_at__lt=cutoff)
                # BUG-177 : une NS reste PENDING par définition (jamais livrée)
                # — ne jamais la purger.
                .exclude(special_code=Invoice.SpecialCode.NS)
                .select_related('client', 'node')
                .prefetch_related('lines__bread_price')
        )
        for inv in expired:
            if inv.client_id:
                net_delta = inv.debt_delta
                Client.objects.filter(pk=inv.client_id).update(
                    current_debt=F('current_debt') - net_delta
                )
                if net_delta != 0:
                    _record_debt_movement_after_commit(
                        inv.client, -net_delta, DebtMovement.Kind.ADJUSTMENT,
                        node_origin=inv.node.code, invoice=None,  # la facture va être supprimée
                        note=f"Expiration auto {inv.receipt_number or inv.pk}",
                    )
            # BUG-029 : comme `cancel()`, une facture PENDING jamais livrée
            # doit restituer le stock de pains déduit à la création —
            # ces pains n'ont jamais réellement quitté la boulangerie.
            for line in inv.lines.all():
                _adjust_bread_stock(inv.node, line.bread_price, sent=-line.quantity)
        Invoice.objects.filter(pk__in=[i.pk for i in expired]).delete()
        return Response({'deleted': len(expired)})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def pending_deliveries(self, request):
        """Livreur screen: all PENDING invoices for today."""
        qs = self.get_queryset().filter(
            status=Invoice.Status.PENDING, invoice_date=_default_work_date(request.user),
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
        target_date = request.query_params.get('date', str(_default_work_date(request.user)))
        qs = self.get_queryset().filter(invoice_date=target_date, status=Invoice.Status.DELIVERED)
        per_node = qs.values('node__code').annotate(
            cash=Sum('payment_amount'), order_value=Sum('order_total'), count=Count('id')
        )
        summary = []
        for row in per_node:
            cash = row['cash'] or 0
            credit = (row['order_value'] or 0) - cash
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
        elif node_param:
            try:
                nodes = Node.objects.filter(pk=int(node_param))
            except (TypeError, ValueError):
                return Response({'detail': 'Boulangerie invalide.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            nodes = Node.objects.all()
        # BUG-211 : « livré le » = journée de travail du nœud (relève à
        # relève en rotation), via la source unique core/workday.py.
        cond = Q(pk__in=[])
        for n in nodes:
            cond |= Q(invoice__node=n, **delivered_on_work_date_filter(n, target_date, 'invoice__delivered_at'))
        qs = InvoiceLine.objects.filter(invoice__status='DELIVERED').filter(cond)
        summary = (
            qs.values('unit_price')
              .annotate(total_qty=Sum('quantity'), total_fc=Sum('line_total'))
              .order_by('unit_price')
        )
        totals = qs.aggregate(grand_qty=Sum('quantity'), grand_fc=Sum('line_total'))
        return Response({
            'by_category': list(summary),
            'grand_total_qty': totals['grand_qty'] or 0,
            'grand_total_fc': float(totals['grand_fc'] or 0),
        })
