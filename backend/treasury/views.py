import random
import time
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Sum, F
from django.utils import timezone
from rest_framework import viewsets, mixins, status, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend

from core.models import Node, Config
from core.permissions import IsGerant, IsHeadquarters
from core.utils import log_activity, create_notification, validate_requested_date
from .hashing import compute_cashbook_entry_hash, verify_cashbook_chain, GENESIS_HASH
from .models import (
    LocalExpense, FacturierReport, CashClosure, CashbookEntry, JournalEntry,
    DailySavings, DisbursementVoucher, DirectionCashCount,
)
from .serializers import (
    LocalExpenseSerializer, FacturierReportSerializer,
    CashClosureSerializer, CashbookEntrySerializer, JournalEntrySerializer, DailySavingsSerializer,
    DisbursementVoucherSerializer, DirectionCashCountSerializer,
)

# BUG-001 : _compute_hash locale supprimée — remplacée par l'unique fonction
# partagée `treasury.hashing.compute_cashbook_entry_hash`, importée aussi par
# `blockchain/views.py` pour la vérification. Voir ce module pour le détail.

# Nombre maximal de nouvelles tentatives en cas de collision de previous_hash
# (deux écritures concurrentes ayant lu le même "dernier solde" avant que
# l'une des deux n'ait validé — voir BUG-002), ou en cas de verrou de base
# de données occupé (SQLite : "database is locked", attendu sous forte
# concurrence puisque SQLite n'autorise qu'un seul writer à la fois — voir
# aussi `DisbursementVoucherViewSet`/tests de concurrence). Chaque tentative
# relit le dernier solde sous verrou puis retente l'insertion.
_APPEND_MAX_RETRIES = 25

# BUG-114 : bornes de validation pour les filtres `?month=`/`?year=` du
# Journal de Caisse (`JournalEntryViewSet.get_queryset()` et
# `.monthly_report()`). Sans cela, une valeur hors plage (ex. `year=20000`)
# est transmise telle quelle à `QuerySet.filter(date__year=...)`, qui lève une
# `ValueError` remontée par Django jusqu'à un 500 au lieu d'un 400 propre.
# Plage large (et non les bornes 2024-2035 de l'UI, qui ne concernent que le
# sélecteur par défaut du frontend) pour ne pas rejeter des données
# historiques légitimes.
_JOURNAL_YEAR_MIN = 2000
_JOURNAL_YEAR_MAX = 2100


def _validate_month_year(month, year):
    """
    Valide les paramètres `month`/`year` d'une requête sur le Journal de
    Caisse avant tout `QuerySet.filter(date__year=..., date__month=...)`.

    Retourne un message d'erreur (str) si l'un des deux est invalide, sinon
    `None`. `month`/`year` peuvent être `None` (aucun filtre demandé).
    """
    if month is not None:
        try:
            month_int = int(month)
        except (TypeError, ValueError):
            return "Le paramètre 'month' doit être un entier (1-12)."
        if not (1 <= month_int <= 12):
            return "Le paramètre 'month' doit être compris entre 1 et 12."
    if year is not None:
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            return "Le paramètre 'year' doit être un entier."
        if not (_JOURNAL_YEAR_MIN <= year_int <= _JOURNAL_YEAR_MAX):
            return (
                f"Le paramètre 'year' doit être compris entre "
                f"{_JOURNAL_YEAR_MIN} et {_JOURNAL_YEAR_MAX}."
            )
    return None


def _unresolved_incoming_transfer_gap(node) -> str:
    """
    BUG-037 (CLAUDE.md §5.4) : renvoie une description non vide s'il existe
    au moins un transfert inter-boulangeries entrant vers `node` présentant
    un écart de quantité non résolu sur l'une de ses lignes (quantité reçue
    renseignée et différente de la quantité envoyée). Lecture seule de
    `production.models` — ce ticket ne modifie jamais ce modèle.

    Un transfert ANNULÉ (`CANCELLED`) n'est jamais considéré comme un écart
    à résoudre : il est sans effet. Tout autre statut (y compris
    `DISPUTED`, mais aussi un écart saisi directement sans passer par le
    protocole de confirmation) est pris en compte, tant que l'écart
    constaté (`quantity_sent != quantity_received`) n'a pas été corrigé.
    """
    from production.models import BreadTransfer, BreadTransferLine

    gap_lines = (
        BreadTransferLine.objects
        .filter(transfer__to_node=node, quantity_received__isnull=False)
        .exclude(transfer__transfer_status=BreadTransfer.TransferStatus.CANCELLED)
        .exclude(quantity_sent=F('quantity_received'))
        .select_related('transfer', 'bread_price')
    )
    if not gap_lines.exists():
        return ''
    details = '; '.join(
        f"{line.transfer.from_node.code}→{line.transfer.to_node.code} "
        f"{line.bread_price.label}: envoyé {line.quantity_sent}, reçu {line.quantity_received}"
        for line in gap_lines
    )
    return details


def _get_last_balance() -> tuple:
    """Return (last running_balance, last block_hash) from cashbook.

    Verrouille la dernière écriture (si elle existe) pour la durée de la
    transaction appelante (BUG-002) : tant qu'une transaction n'a pas validé
    ou annulé, aucune autre transaction concurrente ne peut lire cette même
    ligne via `select_for_update()` sur un backend qui le supporte
    (PostgreSQL en production). SQLite (dev/tests) ignore silencieusement
    `select_for_update()` : c'est pourquoi la contrainte d'unicité sur
    `CashbookEntry.previous_hash` (voir models.py) est la garantie réelle
    anti-fourche, indépendante du moteur de base de données — cette fonction
    doit donc toujours être appelée depuis `append_cashbook_entry`, qui
    retente l'opération en cas de collision.
    """
    last = CashbookEntry.objects.select_for_update().order_by('-date', '-created_at').first()
    if last:
        return last.running_balance, last.block_hash
    return Decimal('0'), GENESIS_HASH


def append_cashbook_entry(validate_balance=None, **entry_kwargs) -> CashbookEntry:
    """Point d'entrée UNIQUE pour ajouter un bloc au Livre de Caisse Direction.

    Lit le dernier solde/hash sous verrou, construit l'écriture, calcule son
    hash avec la fonction partagée, puis l'enregistre dans une transaction
    atomique. En cas de collision sur `previous_hash` (deux écritures
    concurrentes — BUG-002), retente jusqu'à `_APPEND_MAX_RETRIES` fois en
    relisant le nouveau dernier solde à chaque tentative.

    :param validate_balance: callable optionnel `f(last_balance)` appelé
        À L'INTÉRIEUR de la même transaction verrouillée, avant toute
        écriture — utilisé par exemple par `DisbursementVoucherViewSet`
        pour refuser un bordereau supérieur au solde disponible sans
        laisser de fenêtre de course entre la vérification et l'écriture.
        Doit lever une exception (ex. `rest_framework.exceptions.ValidationError`)
        pour annuler l'opération.

    `entry_kwargs` doit fournir tous les champs de `CashbookEntry` sauf
    `running_balance`, `previous_hash` et `block_hash`, calculés ici. Doit
    fournir soit `entry_amount`, soit `exit_amount` (l'autre reste à 0), le
    signe net déterminant le nouveau solde cumulé.
    """
    net_amount = entry_kwargs.get('entry_amount', Decimal('0')) - entry_kwargs.get('exit_amount', Decimal('0'))

    last_exc = None
    for _attempt in range(_APPEND_MAX_RETRIES):
        try:
            with transaction.atomic():
                last_balance, last_hash = _get_last_balance()
                if validate_balance is not None:
                    validate_balance(last_balance)
                running_balance = last_balance + net_amount
                entry = CashbookEntry(
                    running_balance=running_balance,
                    previous_hash=last_hash,
                    **entry_kwargs,
                )
                entry.block_hash = compute_cashbook_entry_hash(entry)
                entry.save()
                return entry
        except IntegrityError as exc:
            # Un autre thread/process a inséré une écriture avec le même
            # previous_hash entre notre lecture et notre écriture : on
            # retente avec le nouveau dernier solde.
            last_exc = exc
            continue
        except OperationalError as exc:
            # SQLite : "database is locked" — un autre writer tient le
            # verrou d'écriture. Non pertinent sur PostgreSQL en production
            # (verrouillage par ligne via select_for_update), mais nécessaire
            # ici pour que les écritures concurrentes se mettent en file
            # plutôt que d'échouer (voir tests de concurrence BUG-002).
            last_exc = exc
            time.sleep(random.uniform(0.01, 0.05))
            continue
    raise last_exc


class LocalExpenseViewSet(viewsets.ModelViewSet):
    queryset = LocalExpense.objects.select_related('node', 'gerant').all()
    serializer_class = LocalExpenseSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'category', 'date']
    ordering         = ['-date']
    permission_classes = [IsGerant]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        params = self.request.query_params
        month = params.get('month')
        year  = params.get('year')
        # BUG-115 : même défaut que BUG-114 (JournalEntryViewSet) — une
        # valeur hors plage (ex. year=20000) transmise telle quelle à
        # `QuerySet.filter(date__year=...)` lève une `ValueError` remontée
        # en 500 au lieu d'un 400 propre.
        error = _validate_month_year(month, year)
        if error:
            raise ValidationError({'detail': error})
        if month:
            qs = qs.filter(date__month=month)
        if year:
            qs = qs.filter(date__year=year)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        node = user.node
        if user.can_access_all_nodes:
            node_id = self.request.data.get('node')
            if node_id:
                try:
                    node = Node.objects.get(pk=node_id)
                except Node.DoesNotExist:
                    pass
        if not node:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'node': 'Boulangerie requise. Sélectionnez une succursale dans le filtre.'})
        serializer.save(
            gerant=user,
            node=node,
            node_origin=node.code,
        )


class FacturierReportViewSet(viewsets.ModelViewSet):
    queryset = FacturierReport.objects.select_related('node', 'facturier', 'validated_by').all()
    serializer_class = FacturierReportSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'team', 'date', 'is_validated']
    ordering         = ['-date']

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsGerant()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(
            facturier=self.request.user,
            team=self.request.user.team,
            node_origin=self.request.user.node.code if self.request.user.node else 'CLOUD',
        )
        # If theoretical_cash not provided, mirror total_cash_sales
        if not obj.theoretical_cash:
            obj.theoretical_cash = obj.total_cash_sales
            obj.save(update_fields=['theoretical_cash'])

    @action(detail=False, methods=['post'], permission_classes=[IsGerant])
    def generate(self, request):
        """Generate/refresh FacturierReport(s) from a day's delivered invoices.

        BUG-083 : la logique d'agrégation est désormais extraite dans
        `treasury.services.regenerate_facturier_reports` (import local pour
        éviter l'import circulaire views↔services — `services` importe déjà
        `append_cashbook_entry` depuis ce module) — réutilisée par le
        mécanisme de correction d'une livraison rétroactive sur une vacation
        déjà rapportée.

        BUG-086 (volet « Rapports Journaliers des Facturiers », demande
        client complémentaire) : `date` optionnel dans le payload, même
        règle que `CashClosureViewSet.perform_create`/`perform_update`
        (`core.utils.validate_requested_date`) — une date future est
        toujours refusée ; une date passée n'est acceptée que si
        `Config.allow_backdated_sales` est actif. Comportement par défaut
        (aucun `date` fourni) strictement inchangé : date du jour.
        """
        from django.utils.dateparse import parse_date

        from .services import regenerate_facturier_reports

        requested_date_raw = request.data.get('date')
        if requested_date_raw:
            target_date = parse_date(str(requested_date_raw)[:10])
            if target_date is None:
                return Response(
                    {'detail': "date invalide — format attendu AAAA-MM-JJ."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            config = Config.get_instance()
            date_error = validate_requested_date(
                target_date, config, field_label="La date du rapport (date)"
            )
            if date_error:
                return Response({'detail': date_error}, status=status.HTTP_400_BAD_REQUEST)
        else:
            target_date = date.today()

        user = request.user
        node = user.node
        if user.can_access_all_nodes:
            node_id = request.data.get('node')
            if node_id:
                try:
                    node = Node.objects.get(pk=node_id)
                except Node.DoesNotExist:
                    pass

        if not node:
            return Response({'detail': 'Aucune boulangerie assignée. Sélectionnez une succursale dans le filtre.'}, status=status.HTTP_400_BAD_REQUEST)

        created_reports = regenerate_facturier_reports(node, target_date)
        if not created_reports:
            return Response({'detail': 'Aucune facture livrée pour cette date.', 'reports': []})

        log_activity(
            request.user, "Génération Rapport Facturier",
            f"{len(created_reports)} rapport(s) généré(s) pour {target_date} — {node.code}.",
            node_origin=node.code,
        )
        return Response(FacturierReportSerializer(created_reports, many=True).data)

    @action(detail=True, methods=['post'], permission_classes=[IsGerant])
    def validate(self, request, pk=None):
        report = self.get_object()
        if report.is_validated:
            return Response({'detail': 'Rapport déjà validé.'}, status=status.HTTP_400_BAD_REQUEST)
        report.is_validated = True
        report.validated_by = request.user
        report.validated_at = timezone.now()
        report.save(update_fields=['is_validated', 'validated_by', 'validated_at'])
        log_activity(
            request.user, "Validation Rapport Facturier",
            f"Rapport Éq.{report.team} {report.date} validé — Cash: {report.total_cash_sales} FC.",
            node_origin=report.node.code
        )
        return Response(FacturierReportSerializer(report).data)


class CashClosureViewSet(viewsets.ModelViewSet):
    queryset = CashClosure.objects.select_related('node', 'gerant').prefetch_related('cashbook_entries').all()
    serializer_class = CashClosureSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'date', 'is_validated']
    ordering         = ['-date']

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsGerant()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        return qs

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        user = self.request.user
        node = user.node
        if user.can_access_all_nodes:
            node_id = self.request.data.get('node')
            if node_id:
                try:
                    node = Node.objects.get(pk=node_id)
                except Node.DoesNotExist:
                    pass
        if not node:
            raise ValidationError({'node': 'Boulangerie requise. Sélectionnez une succursale dans le filtre.'})
        target_date = serializer.validated_data.get('date', date.today())

        # BUG-086 (remarque.md l.362 — extension de BUG-083) : `date` était
        # déjà acceptée librement dans le payload (trou préexistant, voir
        # fiche BUG-086), sans AUCUN lien avec `Config.allow_backdated_sales`
        # ni de refus d'une date future. Même règle que pour une facture
        # (`sales.views._validate_requested_date`, désormais partagée via
        # `core.utils.validate_requested_date`) : une date future est
        # toujours refusée ; une date passée n'est acceptée que si le
        # réglage est actif — y compris pour un rôle Siège (can_access_all_nodes),
        # ce réglage n'étant pas un contournement de permission.
        config = Config.get_instance()
        date_error = validate_requested_date(
            target_date, config, field_label="La date de clôture (date)"
        )
        if date_error:
            raise ValidationError({'detail': date_error})

        # BUG-037 (CLAUDE.md §5.4 : « écart quantité validée ≠ envoyée →
        # alerte et blocage de la clôture ») : un transfert inter-
        # boulangeries entrant vers ce nœud avec un écart de quantité non
        # résolu bloque la création de la clôture. Lecture seule de
        # `production.BreadTransfer`/`BreadTransferLine`, aucune écriture.
        unresolved_gap = _unresolved_incoming_transfer_gap(node)
        if unresolved_gap:
            raise ValidationError({
                'detail': (
                    "Clôture bloquée : un transfert de pains reçu par "
                    f"{node.code} présente un écart de quantité non résolu "
                    f"({unresolved_gap}). Faites valider/corriger le transfert "
                    "avant de clôturer la caisse."
                )
            })

        # Aggregate today's cash entries and expenses for this node
        total_entries = FacturierReport.objects.filter(
            node=node, date=target_date
        ).aggregate(s=Sum('total_cash_sales'))['s'] or 0

        total_expenses = LocalExpense.objects.filter(
            node=node, date=target_date
        ).aggregate(s=Sum('amount'))['s'] or 0

        try:
            with transaction.atomic():
                closure = serializer.save(
                    gerant=user,
                    node=node,
                    node_origin=node.code,
                    total_entries=total_entries,
                    total_expenses=total_expenses,
                )
        except IntegrityError:
            # BUG-035 : la contrainte unique_together (node, date) protège
            # bien les données, mais doit être traduite en un refus propre
            # (400) plutôt que remonter en erreur serveur (500).
            raise ValidationError({
                'detail': f"Une clôture existe déjà pour {node.code} à la date {target_date}."
            })
        closure.compute_physical_cash()
        closure.save(update_fields=['net_cash', 'physical_cash_total', 'cash_gap'])

        if closure.cash_gap != 0:
            create_notification(
                title=f"Écart de Caisse — {closure.node.code}",
                message=(
                    f"Clôture du {closure.date} : écart de {closure.cash_gap:+,.0f} FC "
                    f"(théorique {closure.net_cash:,.0f} FC, compté {closure.physical_cash_total:,.0f} FC)."
                ),
                severity='WARNING' if abs(closure.cash_gap) < 10000 else 'DANGER',
                node_origin=closure.node.code
            )

    def perform_update(self, serializer):
        from rest_framework.exceptions import ValidationError

        # BUG-034 (remarque.md l.156) : seule une clôture INFIRMÉE par le
        # comptable peut être modifiée puis resoumise par le gérant. Une
        # clôture déjà CONFIRMÉE est figée — elle a pu alimenter le Livre
        # de Caisse Direction (push_to_cashbook), immuable ; la laisser
        # divergente créerait un trou d'audit.
        if serializer.instance.is_validated:
            raise ValidationError({
                'detail': (
                    "Clôture déjà confirmée par le comptable — modification impossible. "
                    "Seule une clôture infirmée peut être modifiée par le gérant."
                )
            })

        # BUG-086 : `date` n'est pas en lecture seule sur ce serializer
        # (modifiable à la resoumission après infirmation) — même trou que
        # `perform_create` si un nouveau `date` est fourni dans le payload de
        # modification. Même règle appliquée ici par cohérence.
        target_date = serializer.validated_data.get('date', serializer.instance.date)
        config = Config.get_instance()
        date_error = validate_requested_date(
            target_date, config, field_label="La date de clôture (date)"
        )
        if date_error:
            raise ValidationError({'detail': date_error})

        # Gérant resubmits after rejection — clear the rejection flag
        closure = serializer.save(is_rejected=False, rejection_reason='')
        # Re-aggregate in case expenses changed since creation
        total_entries = FacturierReport.objects.filter(
            node=closure.node, date=closure.date
        ).aggregate(s=Sum('total_cash_sales'))['s'] or 0
        total_expenses = LocalExpense.objects.filter(
            node=closure.node, date=closure.date
        ).aggregate(s=Sum('amount'))['s'] or 0
        closure.total_entries  = total_entries
        closure.total_expenses = total_expenses
        closure.compute_physical_cash()
        closure.save(update_fields=['total_entries', 'total_expenses', 'net_cash', 'physical_cash_total', 'cash_gap'])

    @action(detail=True, methods=['post'], permission_classes=[IsHeadquarters])
    def validate(self, request, pk=None):
        """Comptable DG confirms the closure after physical cash count.

        Accepts an optional `notes` comment, appended to the closure's
        existing notes (the gérant's original observation is never overwritten).
        """
        closure = self.get_object()
        if closure.is_validated:
            return Response({'detail': 'Clôture déjà confirmée.'}, status=status.HTTP_400_BAD_REQUEST)
        comptable_note = (request.data.get('notes') or '').strip()
        update_fields = ['is_validated', 'is_rejected', 'rejection_reason']
        closure.is_validated  = True
        closure.is_rejected   = False
        closure.rejection_reason = ''
        if comptable_note:
            prefix = f"[Comptable — {request.user.get_full_name() or request.user.username}] {comptable_note}"
            closure.notes = f"{closure.notes}\n{prefix}" if closure.notes else prefix
            update_fields.append('notes')
        closure.save(update_fields=update_fields)
        log_activity(
            request.user, "Confirmation Clôture de Caisse",
            f"Clôture {closure.node.code} {closure.date} confirmée — Net: {closure.net_cash} FC · Écart: {closure.cash_gap} FC."
            + (f" Commentaire: {comptable_note}" if comptable_note else ""),
            node_origin=closure.node.code,
        )
        return Response(CashClosureSerializer(closure).data)

    @action(detail=True, methods=['post'], permission_classes=[IsHeadquarters])
    def reject(self, request, pk=None):
        """Comptable DG rejects the closure, sending it back to the gérant."""
        closure = self.get_object()
        if closure.is_validated:
            return Response({'detail': 'Impossible d\'infirmer une clôture déjà confirmée.'}, status=status.HTTP_400_BAD_REQUEST)
        reason = request.data.get('reason', '').strip()
        closure.is_rejected      = True
        closure.rejection_reason = reason
        closure.is_validated     = False
        closure.save(update_fields=['is_rejected', 'rejection_reason', 'is_validated'])
        log_activity(
            request.user, "Rejet Clôture de Caisse",
            f"Clôture {closure.node.code} {closure.date} infirmée — Motif: {reason or 'Non précisé'}.",
            node_origin=closure.node.code,
        )
        return Response(CashClosureSerializer(closure).data)

    @action(detail=True, methods=['post'], permission_classes=[IsHeadquarters])
    def push_to_cashbook(self, request, pk=None):
        """
        Promote a validated closure into the immutable central cashbook.

        Logique extraite dans `treasury.services.promote_closure_to_cashbook`
        (voir ce module) pour être réutilisée par `sync.views` quand une
        `CashClosure` validée arrive par `/api/sync/push/` depuis un nœud
        local — docs/architecture/SYNC.md §0 : le Livre de Caisse Direction
        n'est jamais écrit directement par un nœud, seul le Cloud y écrit,
        ici ou via la synchronisation, par le même chemin de code.
        """
        from .services import promote_closure_to_cashbook, ClosureNotValidatedError, ClosureAlreadyPromotedError

        closure = self.get_object()

        # BUG-037 : second filet — même si la clôture a été créée avant
        # l'apparition d'un transfert litigieux, elle ne doit pas pouvoir
        # être poussée au Livre de Caisse (immuable) tant que l'écart
        # n'est pas résolu.
        unresolved_gap = _unresolved_incoming_transfer_gap(closure.node)
        if unresolved_gap:
            return Response({
                'detail': (
                    "Poussée au Livre de Caisse bloquée : un transfert de pains reçu "
                    f"par {closure.node.code} présente un écart de quantité non résolu "
                    f"({unresolved_gap}). Faites valider/corriger le transfert d'abord."
                )
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            entry = promote_closure_to_cashbook(closure, acting_user=request.user)
        except (ClosureNotValidatedError, ClosureAlreadyPromotedError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(CashbookEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class CashbookEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    The central cashbook is read-only via API. Entries are created
    only through the push_to_cashbook action on CashClosure.
    """
    queryset = CashbookEntry.objects.select_related('node', 'source_closure').all()
    serializer_class = CashbookEntrySerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'date', 'is_tampered']
    ordering         = ['-date', '-created_at']
    # BUG-026 : le Livre de Caisse Direction (cahierDesCharges.md §5.1.3)
    # est un document de direction consolidé sur l'ensemble des boulangeries
    # — il ne doit pas être lisible par un GERANT/FACTURIER/LIVREUR, qui
    # verrait sinon les mouvements de caisse de toutes les autres bakeries.
    # Restreint à ADMIN/DIRECTION/COMPTABLE (IsHeadquarters), cohérent avec
    # DisbursementVoucherViewSet (sorties de cette même caisse) déjà
    # restreint ainsi. Décision documentée dans REGISTRE_BUGS.md (BUG-026).
    permission_classes = [IsHeadquarters]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        date_from = params.get('date_from')
        date_to   = params.get('date_to')
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    @action(detail=False, methods=['get'])
    def integrity_check(self, request):
        """Verify the entire hash chain and flag tampered entries.

        BUG-001 : utilise désormais `verify_cashbook_chain`, la même
        fonction de vérification que `blockchain.views._verify_chain_for_node`
        — il n'existe plus qu'une seule logique de vérification de la chaîne.
        """
        entries = list(CashbookEntry.objects.order_by('date', 'created_at'))
        tampered = []
        for i, (entry, _expected, is_valid) in enumerate(verify_cashbook_chain(entries)):
            if not is_valid:
                entry.is_tampered = True
                entry.save(update_fields=['is_tampered'])
                tampered.append(str(entry.id))
                create_notification(
                    title="Alerte Blockchain — Intégrité compromise",
                    message=f"L'écriture {entry.piece_number} du {entry.date} a été altérée. Bloc {i+1} corrompu.",
                    severity='DANGER', node_origin=entry.node.code
                )
        return Response({
            'total_entries': len(entries),
            'tampered_count': len(tampered),
            'tampered_ids': tampered,
            'chain_valid': len(tampered) == 0,
        })

    @action(detail=False, methods=['get'])
    def period_summary(self, request):
        """Aggregate cashbook by node for a date range."""
        date_from = request.query_params.get('date_from', str(date.today().replace(day=1)))
        date_to   = request.query_params.get('date_to',   str(date.today()))
        qs = self.get_queryset().filter(date__gte=date_from, date__lte=date_to)
        summary = qs.values('node__code', 'node__name').annotate(
            total_entries=Sum('entry_amount'),
            total_exits=Sum('exit_amount'),
        )
        return Response(list(summary))


class DisbursementVoucherViewSet(viewsets.ModelViewSet):
    """
    Bordereaux de versement — sorties de caisse Direction, financées par
    l'argent consolidé reçu de toutes les boulangeries. Chaque bordereau
    crée une écriture de sortie (exit_amount) au Livre de Caisse, chaînée
    par hash comme les versements des clôtures.
    """
    queryset = DisbursementVoucher.objects.select_related('created_by').all()
    serializer_class = DisbursementVoucherSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['date']
    ordering         = ['-date', '-created_at']
    permission_classes = [IsHeadquarters]

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        siege = Node.objects.filter(code='SIEGE').first()
        if not siege:
            raise ValidationError({'detail': "Nœud SIEGE introuvable — exécutez les migrations avant de créer un bordereau."})

        voucher = serializer.save(created_by=self.request.user, node_origin='CLOUD')
        voucher.compute_physical_cash()
        voucher.piece_number = f"BV-{voucher.date.strftime('%Y%m%d')}-{str(voucher.id)[:6].upper()}"
        voucher.save(update_fields=['physical_cash_total', 'piece_number'])

        label = f"Bordereau de versement — {voucher.motif}"
        if voucher.beneficiary:
            label += f" ({voucher.beneficiary})"

        def _check_sufficient_balance(last_balance):
            if voucher.physical_cash_total > last_balance:
                raise ValidationError({
                    'detail': f"Montant du bordereau ({voucher.physical_cash_total:,.0f} FC) supérieur au solde disponible ({last_balance:,.0f} FC)."
                })

        try:
            entry = append_cashbook_entry(
                validate_balance=_check_sufficient_balance,
                node=siege,
                date=voucher.date,
                piece_number=voucher.piece_number,
                imputation='SORTIE',
                label=label,
                exit_amount=voucher.physical_cash_total,
                source_bordereau=voucher,
                node_origin='CLOUD',
            )
        except ValidationError:
            voucher.delete()
            raise

        log_activity(
            self.request.user, "Bordereau de Versement",
            f"Bordereau {voucher.piece_number} — {voucher.motif} — {voucher.physical_cash_total:,.0f} FC. Nouveau solde: {entry.running_balance:,.0f} FC.",
            node_origin='CLOUD',
        )

    @action(detail=False, methods=['get'], permission_classes=[IsHeadquarters])
    def final_report(self, request):
        """Bordereau final — synthèse imprimable des bordereaux d'une période + solde restant."""
        date_from = request.query_params.get('date_from')
        date_to   = request.query_params.get('date_to')
        qs = self.get_queryset()
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        total_disbursed = qs.aggregate(s=Sum('physical_cash_total'))['s'] or 0
        # Lecture seule : pas besoin du verrou utilisé à l'écriture, mais
        # select_for_update() exige une transaction active.
        with transaction.atomic():
            remaining_balance, _ = _get_last_balance()
        return Response({
            'vouchers': DisbursementVoucherSerializer(qs, many=True).data,
            'total_disbursed': str(total_disbursed),
            'remaining_balance': str(remaining_balance),
        })


class DirectionCashCountViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin,
    mixins.RetrieveModelMixin, viewsets.GenericViewSet,
):
    """
    BUG-119 (Chantier A) : comptage physique des billets au niveau Direction,
    avec calcul d'écart physique/théorique (CLAUDE.md §5.5) — même logique
    que `CashClosureViewSet` au Niveau 2, mais consolidée au Niveau 3.

    Volontairement PAS un `ModelViewSet` complet : ni `update`, ni `destroy`.
    Un comptage physique déjà enregistré est un constat daté — comme les
    autres écritures de ce module (CLAUDE.md §5.5 : « lecture seule »), on ne
    le corrige jamais en place ; un nouveau comptage (nouvelle date, ou une
    nouvelle saisie après suppression manuelle en base par un administrateur
    hors API en cas d'erreur de saisie avérée) est la seule voie. Réservé à
    IsHeadquarters (ADMIN/DIRECTION/COMPTABLE), comme le reste du Livre de
    Caisse Direction (BUG-026).
    """
    queryset = DirectionCashCount.objects.select_related('counted_by', 'reference_entry').all()
    serializer_class = DirectionCashCountSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields  = ['date']
    ordering          = ['-date']
    permission_classes = [IsHeadquarters]

    def perform_create(self, serializer):
        target_date = serializer.validated_data.get('date', date.today())

        config = Config.get_instance()
        date_error = validate_requested_date(
            target_date, config, field_label="La date du comptage (date)"
        )
        if date_error:
            raise ValidationError({'detail': date_error})

        # Solde théorique Direction = running_balance de la dernière
        # CashbookEntry connue à cette date ou avant (chaîne consolidée,
        # pas un solde journalier — voir docstring du modèle).
        reference_entry = (
            CashbookEntry.objects.filter(date__lte=target_date)
            .order_by('-date', '-created_at')
            .first()
        )
        theoretical_balance = reference_entry.running_balance if reference_entry else Decimal('0.00')

        try:
            with transaction.atomic():
                count = serializer.save(
                    counted_by=self.request.user,
                    reference_entry=reference_entry,
                    theoretical_balance=theoretical_balance,
                )
        except IntegrityError:
            # unique=True sur `date` — même traitement que BUG-035 (double
            # CashClosure) : refus propre (400) plutôt qu'erreur serveur.
            raise ValidationError({
                'detail': f"Un comptage Direction existe déjà pour la date {target_date}."
            })

        count.compute_physical_cash()
        count.save(update_fields=['physical_cash_total', 'cash_gap'])

        if count.cash_gap != 0:
            create_notification(
                title="Écart de Caisse — Direction",
                message=(
                    f"Comptage Direction du {count.date} : écart de "
                    f"{count.cash_gap:+,.0f} FC (théorique {count.theoretical_balance:,.0f} FC, "
                    f"compté {count.physical_cash_total:,.0f} FC)."
                ),
                severity='WARNING' if abs(count.cash_gap) < 10000 else 'DANGER',
                node_origin='CLOUD',
            )

        log_activity(
            self.request.user, "Comptage Caisse Direction",
            f"Comptage {count.date} — compté {count.physical_cash_total:,.0f} FC, "
            f"théorique {count.theoretical_balance:,.0f} FC, écart {count.cash_gap:+,.0f} FC.",
            node_origin='CLOUD',
        )


class JournalEntryViewSet(viewsets.ModelViewSet):
    """
    Journal de Caisse par Boulangerie (§5.1.4).
    Supports filtering by node, date, month, year.
    """
    queryset = JournalEntry.objects.select_related('node', 'recorded_by').all()
    serializer_class = JournalEntrySerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'date', 'imput']
    ordering         = ['date', 'created_at']
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        params = self.request.query_params

        # Scope to node
        # BUG-113 : un non-HQ ne doit jamais pouvoir lire le Journal de Caisse
        # d'une autre boulangerie en forgeant `?node=<autre>` — on ignore
        # silencieusement tout `node` fourni et on impose le nœud de
        # l'utilisateur. Même motif que BUG-022/025.
        node_id = params.get('node')
        if not user.can_access_all_nodes:
            if user.node_id:
                qs = qs.filter(node=user.node)
            else:
                qs = qs.none()
        elif node_id:
            qs = qs.filter(node_id=node_id)

        # Month/year filter
        month = params.get('month')
        year  = params.get('year')
        # BUG-114 : valeurs hors plage (ex. year=20000) → 400 propre au lieu
        # d'une ValueError non interceptée remontant en 500.
        error = _validate_month_year(month, year)
        if error:
            raise ValidationError({'detail': error})
        if month:
            qs = qs.filter(date__month=month)
        if year:
            qs = qs.filter(date__year=year)

        return qs

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        user = self.request.user
        node = user.node
        if user.can_access_all_nodes:
            node_id = self.request.data.get('node')
            if node_id:
                try:
                    node = Node.objects.get(pk=node_id)
                except Node.DoesNotExist:
                    pass
        if not node:
            raise ValidationError({'node': 'Boulangerie requise.'})

        target_date = serializer.validated_data.get('date', date.today())
        entry_amount = serializer.validated_data.get('entry_amount', Decimal('0'))
        exit_amount  = serializer.validated_data.get('exit_amount',  Decimal('0'))

        # Determine month_carried (first entry this month = last balance of previous month)
        prev_in_month = (
            JournalEntry.objects
            .filter(node=node, date__year=target_date.year, date__month=target_date.month)
            .order_by('-date', '-created_at')
            .first()
        )

        if prev_in_month:
            month_carried   = prev_in_month.month_carried
            running_balance = prev_in_month.running_balance + entry_amount - exit_amount
        else:
            # First entry this month: carry balance from last entry of previous month
            prev_month_entry = (
                JournalEntry.objects
                .filter(node=node)
                .exclude(date__year=target_date.year, date__month=target_date.month)
                .order_by('-date', '-created_at')
                .first()
            )
            month_carried   = prev_month_entry.running_balance if prev_month_entry else Decimal('0')
            running_balance = month_carried + entry_amount - exit_amount

        imput = serializer.validated_data.get('imput')

        # BUG-091 (remarque.md l.384-385) : rapprochement automatique de
        # l'imputation « Recettes du jour (CA) » avec la CashClosure (Niveau
        # 2, §5.5) du même (nœud, date), déjà calculée automatiquement à
        # partir des factures réelles (FacturierReport.total_cash_sales).
        #
        # Choix du champ de confrontation : CashClosure.total_entries (et
        # non net_cash ni physical_cash_total). « Recettes du jour (CA) »
        # désigne l'ARGENT ENTRÉ en caisse ce jour-là (le libellé CA du
        # Journal est une « Entrée », comme total_entries — « Total Entrées
        # Cash (FC) »). net_cash = total_entries − total_expenses est déjà
        # un solde net (après dépenses), et les dépenses locales ont leur
        # propre imputation dans ce même Journal (ex. RATION, APPRO,
        # CARBURANT...) : les soustraire une seconde fois ici doublerait
        # leur effet sur le solde courant du Journal. physical_cash_total
        # est le comptage physique du gérant (billetage), pas la recette
        # théorique du logiciel. total_entries est donc le montant qui
        # correspond réellement à ce que le client appelle « les données sur
        # les recettes [...] affichées automatiquement » (remarque.md).
        #
        # Jamais de blocage (cohérent avec BUG-083 « Autoriser et
        # avertir ») : le montant saisi par l'utilisateur est toujours
        # accepté tel quel ; seul un écart avec la Clôture déclenche un
        # avertissement journalisé (SystemNotification), sans empêcher la
        # sauvegarde. Si aucune CashClosure n'existe encore pour ce (nœud,
        # date), l'écriture est enregistrée normalement mais marquée
        # `is_reconciled=False` (« non rapprochée avec la Clôture »).
        reconciled_closure = None
        is_reconciled = False
        reconciliation_gap = Decimal('0.00')

        if imput == 'CA':
            closure = CashClosure.objects.filter(node=node, date=target_date).first()
            if closure:
                reconciled_closure = closure
                is_reconciled = True
                reconciliation_gap = entry_amount - closure.total_entries
                if reconciliation_gap != 0:
                    create_notification(
                        title=f"Écart Journal de Caisse / Clôture — {node.code}",
                        message=(
                            f"Imputation « Recettes du jour (CA) » du {target_date} : "
                            f"montant saisi {entry_amount:,.0f} FC, écart de "
                            f"{reconciliation_gap:+,.0f} FC par rapport aux recettes "
                            f"calculées automatiquement par la Clôture Niveau 2 "
                            f"({closure.total_entries:,.0f} FC)."
                        ),
                        severity='WARNING',
                        node_origin=node.code,
                    )

        entry = serializer.save(
            node=node,
            recorded_by=user,
            running_balance=running_balance,
            month_carried=month_carried,
            reconciled_closure=reconciled_closure,
            is_reconciled=is_reconciled,
            reconciliation_gap=reconciliation_gap,
        )
        if imput == 'CA':
            log_activity(
                user, 'JOURNAL_CA_ENTRY',
                (
                    f"Journal {node.code} {target_date} — Recettes du jour (CA) : "
                    f"{entry_amount:,.0f} FC saisi, "
                    + (
                        f"rapproché à la Clôture ({reconciled_closure.total_entries:,.0f} FC, "
                        f"écart {reconciliation_gap:+,.0f} FC)."
                        if is_reconciled else
                        "non rapproché — aucune CashClosure pour ce (nœud, date)."
                    )
                ),
                node_origin=node.code,
            )
        return entry

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def suggested_ca(self, request):
        """
        BUG-091 : montant suggéré pour l'imputation « Recettes du jour (CA) »
        d'un (nœud, date) donné, lu depuis CashClosure.total_entries, pour
        pré-remplissage côté frontend avant soumission du Journal.
        Ne bloque jamais : si aucune clôture n'existe, `available=False` et
        `amount=None` — le champ reste en saisie libre côté client.
        """
        params = request.query_params
        date_str = params.get('date')

        # BUG-113 : un non-HQ ne doit jamais pouvoir lire les recettes cash
        # (CashClosure.total_entries) d'une autre boulangerie en forgeant
        # `?node=<autre>` — on ignore tout `node` fourni et on impose le
        # nœud de l'utilisateur. Même motif que BUG-022/025.
        if not request.user.can_access_all_nodes:
            if not request.user.node_id:
                return Response(
                    {'detail': "Aucune boulangerie associée à cet utilisateur."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            node_id = str(request.user.node_id)
        else:
            node_id = params.get('node')

        if not node_id or not date_str:
            return Response(
                {'detail': "Paramètres 'node' et 'date' requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return Response(
                {'detail': "Format de date invalide (attendu AAAA-MM-JJ)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        closure = CashClosure.objects.filter(node_id=node_id, date=target_date).first()
        if not closure:
            return Response({
                'available': False,
                'amount': None,
                'closure_id': None,
                'message': "Aucune Clôture (Niveau 2) pour ce jour — écriture non rapprochée.",
            })
        return Response({
            'available': True,
            'amount': str(closure.total_entries),
            'closure_id': str(closure.id),
            'message': None,
        })

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def monthly_report(self, request):
        """Totals for a given month/year and node."""
        params  = request.query_params
        month   = params.get('month', str(date.today().month))
        year    = params.get('year',  str(date.today().year))

        # BUG-114 : valeurs hors plage (ex. year=20000) → 400 propre au lieu
        # d'une ValueError non interceptée remontant en 500.
        error = _validate_month_year(month, year)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-113 : un non-HQ ne doit jamais pouvoir lire les totaux mensuels
        # du Journal de Caisse d'une autre boulangerie en forgeant
        # `?node=<autre>` — on ignore tout `node` fourni et on impose le
        # nœud de l'utilisateur. Même motif que BUG-022/025.
        if not request.user.can_access_all_nodes:
            if not request.user.node_id:
                return Response(
                    {'detail': "Aucune boulangerie associée à cet utilisateur."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            node_id = str(request.user.node_id)
        else:
            node_id = params.get('node')

        qs = JournalEntry.objects.filter(date__month=month, date__year=year)
        if node_id:
            qs = qs.filter(node_id=node_id)

        totals = qs.aggregate(
            total_entries=Sum('entry_amount'),
            total_exits=Sum('exit_amount'),
        )
        first_entry = qs.order_by('date', 'created_at').first()
        last_entry  = qs.order_by('-date', '-created_at').first()

        return Response({
            'month':         month,
            'year':          year,
            'month_carried': str(first_entry.month_carried) if first_entry else '0',
            'total_entries': str(totals['total_entries'] or 0),
            'total_exits':   str(totals['total_exits']   or 0),
            'final_balance': str(last_entry.running_balance if last_entry else 0),
        })


class DailySavingsViewSet(viewsets.ModelViewSet):
    """
    Épargne journalière par boulangerie (§5.1.5).
    savings_amount is auto-computed: daily_revenue × savings_rate.
    """
    queryset = DailySavings.objects.select_related('node', 'recorded_by').all()
    serializer_class = DailySavingsSerializer
    filter_backends  = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['node', 'date']
    ordering         = ['-date']
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user   = self.request.user
        params = self.request.query_params
        node_id = params.get('node')
        if node_id:
            qs = qs.filter(node_id=node_id)
        elif not user.can_access_all_nodes and user.node_id:
            qs = qs.filter(node=user.node)
        month = params.get('month')
        year  = params.get('year')
        # BUG-115 : même défaut que BUG-114 — valider avant tout
        # `date__month=`/`date__year=` pour éviter une `ValueError` → 500.
        error = _validate_month_year(month, year)
        if error:
            raise ValidationError({'detail': error})
        if month:
            qs = qs.filter(date__month=month)
        if year:
            qs = qs.filter(date__year=year)
        return qs

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError as DRFValidationError
        user = self.request.user
        node = user.node
        if user.can_access_all_nodes:
            node_id = self.request.data.get('node')
            if node_id:
                try:
                    node = Node.objects.get(pk=node_id)
                except Node.DoesNotExist:
                    pass
        if not node:
            raise DRFValidationError({'node': 'Boulangerie requise.'})

        daily_revenue  = serializer.validated_data.get('daily_revenue', Decimal('0'))
        savings_rate   = serializer.validated_data.get('savings_rate') or Decimal(str(Config.get_instance().savings_rate))
        savings_amount = (daily_revenue * savings_rate).quantize(Decimal('0.01'))
        date           = serializer.validated_data.get('date')
        flour_sacks    = serializer.validated_data.get('flour_sacks', Decimal('0'))

        # Upsert: update if already exists for this node+date
        obj, created = DailySavings.objects.update_or_create(
            node=node,
            date=date,
            defaults={
                'recorded_by':   user,
                'flour_sacks':   flour_sacks,
                'daily_revenue': daily_revenue,
                'savings_rate':  savings_rate,
                'savings_amount': savings_amount,
            },
        )
        # Bind the instance so DRF serializes the response correctly
        serializer.instance = obj

    def perform_update(self, serializer):
        instance = serializer.save()
        daily_revenue  = instance.daily_revenue
        savings_rate   = instance.savings_rate
        instance.savings_amount = (daily_revenue * savings_rate).quantize(Decimal('0.01'))
        instance.save(update_fields=['savings_amount'])

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def monthly_total(self, request):
        """Total savings per node for a given month/year."""
        params  = request.query_params
        month   = params.get('month', str(date.today().month))
        year    = params.get('year',  str(date.today().year))
        node_id = params.get('node')

        # BUG-115 : même défaut que BUG-114 — valider avant tout
        # `date__month=`/`date__year=` pour éviter une `ValueError` → 500.
        error = _validate_month_year(month, year)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        qs = DailySavings.objects.filter(date__month=month, date__year=year)
        if node_id:
            qs = qs.filter(node_id=node_id)
        elif not request.user.can_access_all_nodes and request.user.node_id:
            qs = qs.filter(node=request.user.node)

        totals = qs.aggregate(
            total_revenue=Sum('daily_revenue'),
            total_savings=Sum('savings_amount'),
        )
        by_node = list(
            qs.values('node__code', 'node__name')
            .annotate(total_savings=Sum('savings_amount'), total_revenue=Sum('daily_revenue'))
            .order_by('node__code')
        )
        return Response({
            'month': month,
            'year':  year,
            'total_revenue': str(totals['total_revenue'] or 0),
            'total_savings': str(totals['total_savings'] or 0),
            'by_node': by_node,
        })
