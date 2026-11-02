"""
Logique métier de synchronisation — séparée des vues pour rester testable
indépendamment du transport HTTP (SYNC.md §2.2, §3).
"""

import random
import time
from datetime import date as _date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Sum

from core.models import Node
from .models import DebtMovement

# Même logique que `treasury.views._APPEND_MAX_RETRIES` : sous SQLite (dev/
# desktop), une écriture concurrente peut heurter "database is locked" —
# transitoire, pas une vraie erreur applicative. `record_debt_movement` est
# appelé DANS la même transaction que la création de facture
# (`sales/views.py::InvoiceViewSet.create`) : une `OperationalError` non
# retentée y remonterait et annulerait toute la transaction (facture ET mise
# à jour `current_debt` comprises), pas seulement l'écriture du journal —
# constaté concrètement par `sales.tests.test_invoices.ConcurrentInvoiceBPTests`
# (10 créations simultanées perdaient des mises à jour de dette tant que
# cette nouvelle écriture supplémentaire n'avait pas, elle aussi, de
# retentatives). Sans incidence sur PostgreSQL en production (verrouillage de
# ligne réel, pas de verrou fichier global).
# BUG-062 : relevé de 25 à 150 — une fois l'authentification de nœud et
# `PushView.post` eux-mêmes protégés par une retentative (voir
# `sync.models.NodeAuthToken.authenticate()` / `sync.views.PushView`), un
# rejeu concurrent agressif (10 requêtes simultanées sur le même `batch_id`,
# chacune pouvant elle-même redéclencher ce chemin plusieurs fois) sature le
# budget de 25 tentatives ici — le symptôme n'est plus une `OperationalError`
# brute mais un enregistrement REJETÉ silencieusement par
# `process_push_batch` (capture défensive `except Exception`, SYNC.md §3.4),
# ce qui est pire (aucune trace d'erreur serveur, juste 0 mouvement créé).
_WRITE_MAX_RETRIES = 150


def recompute_client_debt(client_id):
    """
    Recalcule `Client.current_debt` comme la somme de tous ses
    `DebtMovement` et republie `category` (SYNC.md §2.2 point 3).

    Verrouille la ligne `Client` pendant le recalcul : deux mouvements
    concurrents pour le même client (ex. deux lots `push` de deux nœuds
    différents arrivant en même temps) ne peuvent jamais produire un
    recalcul fondé sur une lecture obsolète.
    """
    from clients.models import Client

    last_exc = None
    for _attempt in range(_WRITE_MAX_RETRIES):
        try:
            with transaction.atomic():
                client = Client.objects.select_for_update().get(pk=client_id)
                total = DebtMovement.objects.filter(client_id=client_id).aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0.00')
                client.current_debt = total
                client.refresh_category()
                client.save(update_fields=['current_debt', 'category'])
                return client
        except OperationalError as exc:
            last_exc = exc
            time.sleep(random.uniform(0.01, 0.05))
    raise last_exc


def record_debt_movement(client, amount, kind, node_origin, invoice=None, note='', movement_id=None):
    """
    Crée un `DebtMovement` — journal immuable UNIQUEMENT, sans recalculer
    `current_debt` (contrairement à `apply_debt_movement` ci-dessous).

    C'est l'opération à utiliser pour les écritures LOCALES normales (ex.
    `sales/views.py::InvoiceViewSet.create`) : `Client.current_debt` reste
    mis à jour par son mécanisme actuel, rapide et déjà testé
    (`Client.objects.filter(pk=...).update(current_debt=F('current_debt') + x)`),
    et ce mouvement n'est qu'une **trace additive en parallèle**, destinée à
    remonter au Cloud lors de la synchronisation (SYNC.md §2.2 point 1) —
    jamais à remplacer immédiatement la valeur locale déjà correcte.

    Pourquoi ne pas toujours recalculer localement (voir `apply_debt_movement`) :
    tant que ce dépôt sert à la fois de nœud local ET de Cloud (avant que
    les postes desktop séparés n'existent réellement), une base de clients
    peut avoir une dette initiale (`current_debt` fixé manuellement, import
    Excel, données de démonstration) qui n'est couverte par AUCUN
    `DebtMovement` — un recalcul "somme des mouvements" écraserait alors
    silencieusement cette dette d'ouverture. Le recalcul par somme
    (`recompute_client_debt`) n'est correct que lorsqu'il agit sur
    l'ensemble complet des mouvements d'un client (cas du Cloud recevant
    des mouvements poussés par plusieurs nœuds réellement séparés,
    `_push_debt_movement`) — pas en complément d'une mise à jour locale
    partielle.
    """
    if amount == 0:
        return None
    if movement_id and DebtMovement.objects.filter(pk=movement_id).exists():
        return DebtMovement.objects.get(pk=movement_id)
    kwargs = dict(
        client=client, invoice=invoice, amount=amount,
        kind=kind, node_origin=node_origin, note=note,
    )
    if movement_id:
        kwargs['id'] = movement_id

    last_exc = None
    for _attempt in range(_WRITE_MAX_RETRIES):
        try:
            with transaction.atomic():
                return DebtMovement.objects.create(**kwargs)
        except OperationalError as exc:
            last_exc = exc
            time.sleep(random.uniform(0.01, 0.05))
        except IntegrityError:
            # BUG-062 : deux rejeux concurrents du même `movement_id`
            # peuvent tous les deux passer le contrôle `exists()` ci-dessus
            # avant que l'un des deux n'ait committé — le second heurte
            # alors la contrainte d'unicité de la PK plutôt qu'un verrou.
            # Ce n'est pas une vraie erreur : le mouvement existe désormais
            # (créé par l'autre tentative), on le renvoie tel quel —
            # comportement idempotent attendu pour `movement_id`.
            if movement_id:
                existing = DebtMovement.objects.filter(pk=movement_id).first()
                if existing is not None:
                    return existing
            raise
    raise last_exc


def apply_debt_movement(client, amount, kind, node_origin, invoice=None, note='', movement_id=None):
    """
    Crée un `DebtMovement` (comme `record_debt_movement`) PUIS recalcule
    immédiatement `current_debt` comme la somme de TOUS les mouvements
    connus pour ce client (SYNC.md §2.2).

    Réservé au traitement des mouvements reçus d'un nœud distinct via
    `/api/sync/push/` (`sync.services._push_debt_movement`) : c'est là,
    et seulement là, que le recalcul par somme est l'opération correcte —
    il réconcilie les mouvements de deux boulangeries ayant facturé le même
    client hors-ligne, indépendamment de l'ordre d'arrivée des lots
    (propriété de commutativité recherchée, voir SYNC.md §2.2 point 5).

    `movement_id` permet de rejouer un mouvement déjà créé ailleurs avec le
    même UUID sans le dupliquer (idempotence) ; le recalcul, lui, est de
    toute façon toujours idempotent par construction.
    """
    if amount == 0:
        return None

    with transaction.atomic():
        movement = record_debt_movement(
            client, amount, kind, node_origin,
            invoice=invoice, note=note, movement_id=movement_id,
        )
        recompute_client_debt(client.pk)
    return movement


# ─── Traitement des lots `push` (Local → Cloud) ─────────────────────────
#
# Ordre fixe de traitement (SYNC.md §3.5) : un enregistrement qui dépend
# d'un autre non encore vu dans ce lot (ou lors d'un push précédent) est
# REJETÉ avec le motif "dépendance manquante" — jamais deviné ni créé en
# partie. Périmètre V1 initial (SYNC.md §11) : Client, Invoice, InvoiceLine,
# DebtMovement, CashClosure.
#
# BUG-004 (extension 2026-11-02, périmètre documenté SYNC.md §11) : ajout de
# `ProductionSession`/`ProductionSessionLine`/`BreadDisposal`/
# `ConsumableMovement`/`BreadTransfer`/`BreadTransferLine` (production) et
# `LocalExpense`/`FacturierReport`/`DisbursementVoucher` (treasury), dans
# l'ordre de dépendance SYNC.md §3.5 point 4/5/6.
#
# BUG-004 (suite, 2026-11-02) : `SocialContribution`/`SocialDistribution`/
# `SocialDistributionLine` (clients) étaient restées HORS PÉRIMÈTRE lors de
# l'extension ci-dessus car ce n'étaient pas des `SyncableModel` (PK
# `BigAutoField`, pas UUID) — contradiction signalée au coordinateur (voir
# `docs/qa/rapports/architecte-sync-2026-11-02-bug004-extension.md`).
# Après arbitrage, les 3 modèles ont été migrés vers `SyncableModel` (PK
# UUIDv4, `clients/migrations/0008_social_syncable_step1.py` +
# `0009_social_syncable_step2.py` — migration de données irréversible,
# réécrit au passage le FK `SocialDistributionLine.distribution`) et sont
# câblés ci-dessous par le même mécanisme (upsert UUID, dépendance manquante
# rejetée explicitement, `_sync_bypass=True`). Enregistrements mono-nœud
# (jamais partagés entre deux boulangeries comme `Client`/`Invoice`) : pas de
# règle de résolution de conflit multi-nœud à définir, `SocialDistribution`
# doit précéder `SocialDistributionLine` (FK).

PUSH_MODEL_ORDER = [
    'clients.Client',
    'sales.Invoice',
    'sales.InvoiceLine',
    'sync.DebtMovement',
    'production.ProductionSession',
    'production.ProductionSessionLine',
    'production.BreadDisposal',
    'production.ConsumableMovement',
    'production.BreadTransfer',
    'production.BreadTransferLine',
    'treasury.LocalExpense',
    'treasury.FacturierReport',
    'treasury.CashClosure',
    'treasury.DisbursementVoucher',
    'clients.SocialContribution',
    'clients.SocialDistribution',
    'clients.SocialDistributionLine',
]

ACCEPTED = 'ACCEPTED'
REJECTED = 'REJECTED'


def _record_result(record_id, accepted, reason=None):
    result = {'id': str(record_id), 'status': ACCEPTED if accepted else REJECTED}
    if reason:
        result['reason'] = reason
    return result


def _log_conflict(node, model_label, object_id, conflict_type, detail=''):
    from .models import SyncConflictLog
    SyncConflictLog.objects.create(
        node=node, model_label=model_label, object_id=str(object_id),
        conflict_type=conflict_type, detail=detail,
    )


def _to_decimal(value, default=Decimal('0')):
    if value is None or value == '':
        return default
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return default


def _push_client(node, record):
    from clients.models import Client

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    existing = Client.objects.filter(pk=record_id).first()
    if existing:
        # Règle de propriété (SYNC.md §1.3/§5.1) : seul le nœud propriétaire
        # (ou le Cloud) peut modifier l'identité d'un client. Un nœud tiers
        # qui a seulement facturé ce client ne peut jamais réécrire son
        # identité — le push est accepté en no-op idempotent, jamais rejeté
        # (il se peut légitimement que le même client soit renvoyé par
        # plusieurs nœuds qui l'ont tous les deux facturé).
        if existing.node_origin not in (node.code, 'CLOUD'):
            _log_conflict(
                node, 'clients.Client', record_id, 'NON_PROPRIETAIRE',
                f"Le nœud {node.code} a tenté de modifier un client appartenant à {existing.node_origin}."
            )
            return _record_result(record_id, False, "nœud non propriétaire de ce client")
        return _record_result(record_id, True)

    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    client = Client(
        id=record_id,
        code=record.get('code') or '',
        first_name=record.get('first_name', ''),
        last_name=record.get('last_name', ''),
        phone=record.get('phone', ''),
        address=record.get('address', ''),
        node=bakery,
        cotisation_sociale=_to_decimal(record.get('cotisation_sociale'), Decimal('3000.00')),
        commission_rate=_to_decimal(record.get('commission_rate'), Decimal('0.25')),
        credit_limit=_to_decimal(record.get('credit_limit'), Decimal('50000.00')),
        client_type=record.get('client_type', 'DETAILLANT'),
        notes=record.get('notes', ''),
        node_origin=record.get('node_origin', bakery_code),
    )
    # Un enregistrement accepté par le Cloud est par définition déjà
    # synchronisé : `_sync_bypass` neutralise le marquage automatique
    # `is_synced=False` (core.models.SyncableModel.save) qui ne concerne
    # que les écritures locales d'un nœud, pas leur réception au Cloud.
    client.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_invoice(node, record):
    from clients.models import Client
    from sales.models import Invoice

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    existing = Invoice.objects.filter(pk=record_id).first()
    if existing:
        # Transition de statut idempotente (ex. livraison confirmée côté
        # nœud, remontée après coup) — jamais de régression PENDING←DELIVERED.
        new_status = record.get('status')
        changed_fields = []
        if new_status and new_status != existing.status:
            if existing.status == 'PENDING' and new_status in ('DELIVERED', 'CANCELLED'):
                existing.status = new_status
                changed_fields.append('status')
                if record.get('delivered_at'):
                    existing.delivered_at = record['delivered_at']
                    changed_fields.append('delivered_at')
        if changed_fields:
            existing.save(update_fields=changed_fields, _sync_bypass=True)
        return _record_result(record_id, True)

    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    client = None
    client_id = record.get('client')
    if client_id:
        client = Client.objects.filter(pk=client_id).first()
        if client is None:
            return _record_result(record_id, False, "dépendance manquante : client")

    invoice = Invoice(
        id=record_id,
        node=bakery,
        client=client,
        team=record.get('team', ''),
        status=record.get('status', 'PENDING'),
        payment_type=record.get('payment_type', 'CASH'),
        debt_before=_to_decimal(record.get('debt_before')),
        order_total=_to_decimal(record.get('order_total')),
        payment_amount=_to_decimal(record.get('payment_amount')),
        debt_after=_to_decimal(record.get('debt_after')),
        commission_rate=_to_decimal(record.get('commission_rate'), Decimal('0.25')),
        is_soldee=bool(record.get('is_soldee', False)),
        special_code=record.get('special_code', ''),
        is_debt_repayment=bool(record.get('is_debt_repayment', False)),
        receipt_number=record.get('receipt_number', ''),
        delivered_at=record.get('delivered_at'),
        node_origin=record.get('node_origin', bakery_code),
    )
    invoice.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_invoice_line(node, record):
    from core.models import BreadPrice
    from sales.models import Invoice, InvoiceLine

    record_id = record.get('id')
    if InvoiceLine.objects.filter(pk=record_id).exists():
        return _record_result(record_id, True)

    invoice = Invoice.objects.filter(pk=record.get('invoice')).first()
    if invoice is None:
        return _record_result(record_id, False, "dépendance manquante : invoice")
    bread_price = BreadPrice.objects.filter(pk=record.get('bread_price')).first()
    if bread_price is None:
        return _record_result(record_id, False, "dépendance manquante : bread_price")

    kwargs = dict(invoice=invoice, bread_price=bread_price, quantity=record.get('quantity', 0))
    if record_id:
        kwargs['id'] = record_id
    InvoiceLine.objects.create(**kwargs)
    return _record_result(record_id, True)


def _push_debt_movement(node, record):
    from clients.models import Client
    from sales.models import Invoice

    record_id = record.get('id')
    client = Client.objects.filter(pk=record.get('client')).first()
    if client is None:
        return _record_result(record_id, False, "dépendance manquante : client")

    invoice = None
    invoice_id = record.get('invoice')
    if invoice_id:
        invoice = Invoice.objects.filter(pk=invoice_id).first()
        if invoice is None:
            return _record_result(record_id, False, "dépendance manquante : invoice")

    amount = _to_decimal(record.get('amount'))
    kind = record.get('kind', DebtMovement.Kind.ADJUSTMENT)
    apply_debt_movement(
        client, amount, kind,
        node_origin=record.get('node_origin', node.code),
        invoice=invoice, note=record.get('note', ''), movement_id=record_id,
    )
    return _record_result(record_id, True)


def _push_cash_closure(node, record):
    from treasury.models import CashClosure
    from treasury.services import (
        promote_closure_to_cashbook, ClosureAlreadyPromotedError, ClosureNotValidatedError,
    )

    record_id = record.get('id')
    existing = CashClosure.objects.filter(pk=record_id).first()
    if existing is None:
        bakery_code = record.get('node') or node.code
        try:
            bakery = Node.objects.get(code=bakery_code)
        except Node.DoesNotExist:
            return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

        closure = CashClosure(
            id=record_id,
            node=bakery,
            date=_date.fromisoformat(record.get('date')),
            total_entries=_to_decimal(record.get('total_entries')),
            total_expenses=_to_decimal(record.get('total_expenses')),
            bills_20000=record.get('bills_20000', 0), bills_10000=record.get('bills_10000', 0),
            bills_5000=record.get('bills_5000', 0), bills_1000=record.get('bills_1000', 0),
            bills_500=record.get('bills_500', 0), bills_200=record.get('bills_200', 0),
            bills_100=record.get('bills_100', 0), bills_50=record.get('bills_50', 0),
            is_validated=bool(record.get('is_validated', False)),
            notes=record.get('notes', ''),
            node_origin=record.get('node_origin', bakery_code),
        )
        closure.compute_physical_cash()
        closure.save(_sync_bypass=True)
        existing = closure

    if existing.is_validated and not existing.cashbook_entries.exists():
        try:
            # Le Livre de Caisse Direction n'est jamais écrit par un nœud :
            # c'est le Cloud qui, ici, appelle la même fonction que l'action
            # DRF `push_to_cashbook` (SYNC.md §0).
            promote_closure_to_cashbook(existing, acting_user=None, node_origin_override='CLOUD')
        except ClosureAlreadyPromotedError:
            pass
        except ClosureNotValidatedError:
            pass
    return _record_result(record_id, True)


# ─── Extension BUG-004 (2026-11-02) : production ────────────────────────
#
# Principe commun à tous les handlers ci-dessous, repris à l'identique de
# `_push_invoice`/`_push_invoice_line` : upsert idempotent par UUID, rejet
# explicite (jamais deviné) sur dépendance manquante, `_sync_bypass=True`
# pour ne pas ré-marquer `is_synced=False` un enregistrement qu'on vient
# d'accepter côté Cloud (CLAUDE.md §4/§8, SYNC.md §3.3).

def _push_production_session(node, record):
    from production.models import ProductionSession

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    existing = ProductionSession.objects.filter(pk=record_id).first()
    if existing:
        # Transition idempotente is_closed False→True uniquement (comme
        # Invoice.status) : jamais de régression closed→ouvert.
        changed_fields = []
        if record.get('is_closed') and not existing.is_closed:
            existing.is_closed = True
            changed_fields.append('is_closed')
            if record.get('closed_at'):
                existing.closed_at = record['closed_at']
                changed_fields.append('closed_at')
            if record.get('closure_summary') is not None:
                existing.closure_summary = record['closure_summary']
                changed_fields.append('closure_summary')
        if changed_fields:
            existing.save(update_fields=changed_fields, _sync_bypass=True)
        return _record_result(record_id, True)

    if not record.get('date'):
        return _record_result(record_id, False, "date manquante")
    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    session = ProductionSession(
        id=record_id,
        node=bakery,
        team=record.get('team', ''),
        date=_date.fromisoformat(record['date']),
        flour_sacks_used=_to_decimal(record.get('flour_sacks_used')),
        breads_300=record.get('breads_300', 0),
        breads_400=record.get('breads_400', 0),
        breads_500=record.get('breads_500', 0),
        breads_1000=record.get('breads_1000', 0),
        total_breads=record.get('total_breads', 0),
        total_fc_produced=record.get('total_fc_produced', 0),
        theoretical_yield=record.get('theoretical_yield', 0),
        yield_gap=record.get('yield_gap', 0),
        sac_value_fc_used=record.get('sac_value_fc_used', 200000),
        is_closed=bool(record.get('is_closed', False)),
        closed_at=record.get('closed_at'),
        closure_summary=record.get('closure_summary'),
        notes=record.get('notes', ''),
        node_origin=record.get('node_origin', bakery_code),
    )
    session.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_production_session_line(node, record):
    from core.models import BreadPrice
    from production.models import ProductionSession, ProductionSessionLine

    record_id = record.get('id')
    if record_id and ProductionSessionLine.objects.filter(pk=record_id).exists():
        return _record_result(record_id, True)

    session = ProductionSession.objects.filter(pk=record.get('session')).first()
    if session is None:
        return _record_result(record_id, False, "dépendance manquante : session")
    bread_price = BreadPrice.objects.filter(pk=record.get('bread_price')).first()
    if bread_price is None:
        return _record_result(record_id, False, "dépendance manquante : bread_price")

    kwargs = dict(session=session, bread_price=bread_price, quantity=record.get('quantity', 0))
    if record_id:
        kwargs['id'] = record_id
    try:
        ProductionSessionLine.objects.create(**kwargs)
    except IntegrityError:
        # Rejeu sans id (ou unique_together session+bread_price déjà
        # honoré par une tentative concurrente) — idempotent par construction.
        pass
    return _record_result(record_id, True)


def _push_bread_disposal(node, record):
    from core.models import BreadPrice
    from production.models import ProductionSession, BreadDisposal

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")
    if BreadDisposal.objects.filter(pk=record_id).exists():
        return _record_result(record_id, True)

    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    session = ProductionSession.objects.filter(pk=record.get('session')).first()
    if session is None:
        return _record_result(record_id, False, "dépendance manquante : session")
    bread_price = BreadPrice.objects.filter(pk=record.get('bread_price')).first()
    if bread_price is None:
        return _record_result(record_id, False, "dépendance manquante : bread_price")

    disposal = BreadDisposal(
        id=record_id, node=bakery, session=session, bread_price=bread_price,
        disposal_type=record.get('disposal_type', ''),
        quantity=record.get('quantity', 0),
        unit_price_sold=record.get('unit_price_sold', 0),
        notes=record.get('notes', ''),
        node_origin=record.get('node_origin', bakery_code),
    )
    # `total_value` est recalculé par BreadDisposal.save() lui-même
    # (quantity × unit_price_sold) — déterministe, jamais de conflit
    # possible (SYNC.md §5.1, objets immuables après création).
    disposal.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_consumable_movement(node, record):
    from django.core.exceptions import ValidationError
    from production.models import ConsumableMovement, ConsumableStock, ProductionSession

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")
    if ConsumableMovement.objects.filter(pk=record_id).exists():
        return _record_result(record_id, True)

    if record.get('quantity') is None:
        return _record_result(record_id, False, "quantité manquante")
    if not record.get('movement_type'):
        return _record_result(record_id, False, "type de mouvement manquant")

    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    consumable_type = record.get('consumable_type')
    if not consumable_type:
        return _record_result(record_id, False, "dépendance manquante : consumable_type")
    # `ConsumableStock` n'est lui-même jamais poussé (SYNC.md §2.4, comme
    # `BreadStock`) : le Cloud tient sa propre ligne consolidée par
    # (nœud, consommable), créée paresseusement au premier mouvement vu
    # pour cette paire — `node_origin='CLOUD'` car cette ligne est une
    # construction du Cloud, pas la remontée d'un objet créé localement.
    stock, _created = ConsumableStock.objects.get_or_create(
        node=bakery, consumable_type=consumable_type,
        defaults={'node_origin': 'CLOUD', 'unit': record.get('unit', '')},
    )

    session = None
    session_id = record.get('session')
    if session_id:
        session = ProductionSession.objects.filter(pk=session_id).first()
        if session is None:
            return _record_result(record_id, False, "dépendance manquante : session")

    movement = ConsumableMovement(
        id=record_id, node=bakery, stock=stock, session=session,
        movement_type=record['movement_type'],
        quantity=_to_decimal(record.get('quantity')),
        unit_price=_to_decimal(record.get('unit_price')),
        supplier=record.get('supplier', ''),
        description=record.get('description', ''),
        node_origin=record.get('node_origin', bakery_code),
    )
    try:
        movement.save(_sync_bypass=True)
    except ValidationError as exc:
        # BUG-041 : une sortie ne fait jamais passer le stock consolidé
        # Cloud en négatif. Si l'ENTRÉE correspondante n'est pas encore
        # synchronisée (ou arrive dans un lot ultérieur), on NE DEVINE
        # jamais : on rejette comme une dépendance manquante classique
        # (SYNC.md §3.4) — retenté automatiquement au prochain cycle, une
        # fois le stock reconstitué par les mouvements encore en attente.
        reason = exc.messages[0] if getattr(exc, 'messages', None) else str(exc)
        return _record_result(record_id, False, f"dépendance manquante (stock insuffisant) : {reason}")
    return _record_result(record_id, True)


def _push_bread_transfer(node, record):
    from core.models import BreadPrice
    from production.models import BreadTransfer

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    existing = BreadTransfer.objects.filter(pk=record_id).first()
    if existing:
        # Machine à états (SYNC.md §5.1) : seule une transition AVANT vers
        # un statut autorisé est appliquée, jamais de régression. Les
        # effets sur le stock (déduction chez from_node, crédit chez
        # to_node) ont déjà eu lieu LOCALEMENT au moment de l'action
        # (`respond_to_request`/`confirm_reception`, production/views.py) :
        # le Cloud ne fait ici que consolider l'état final pour reporting
        # (SYNC.md §5.3) — il ne rejoue JAMAIS `_adjust_bread_stock`
        # lui-même, ce qui doublerait l'effet sur un stock qui n'est de
        # toute façon pas partagé entre nœud et Cloud.
        allowed_forward = {
            BreadTransfer.TransferStatus.PENDING: {
                BreadTransfer.TransferStatus.RESPONDED, BreadTransfer.TransferStatus.CANCELLED,
            },
            BreadTransfer.TransferStatus.RESPONDED: {
                BreadTransfer.TransferStatus.CONFIRMED, BreadTransfer.TransferStatus.DISPUTED,
            },
        }
        new_status = record.get('transfer_status')
        changed_fields = []
        if new_status and new_status != existing.transfer_status:
            if new_status in allowed_forward.get(existing.transfer_status, set()):
                existing.transfer_status = new_status
                changed_fields.append('transfer_status')
                if record.get('quantity_received') is not None:
                    existing.quantity_received = record['quantity_received']
                    changed_fields.append('quantity_received')
        if changed_fields:
            existing.save(update_fields=changed_fields, _sync_bypass=True)
        return _record_result(record_id, True)

    from_code = record.get('from_node')
    to_code = record.get('to_node')
    try:
        from_bakery = Node.objects.get(code=from_code)
        to_bakery = Node.objects.get(code=to_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, "boulangerie inconnue (from_node/to_node)")

    bread_price = None
    bp_id = record.get('bread_price')
    if bp_id:
        bread_price = BreadPrice.objects.filter(pk=bp_id).first()

    transfer = BreadTransfer(
        id=record_id, from_node=from_bakery, to_node=to_bakery, bread_price=bread_price,
        quantity_sent=record.get('quantity_sent'),
        quantity_received=record.get('quantity_received'),
        transfer_status=record.get('transfer_status', BreadTransfer.TransferStatus.PENDING),
        notes=record.get('notes', ''),
        node_origin=record.get('node_origin', to_code or node.code),
    )
    transfer.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_bread_transfer_line(node, record):
    from core.models import BreadPrice
    from production.models import BreadTransfer, BreadTransferLine

    record_id = record.get('id')
    if record_id:
        existing = BreadTransferLine.objects.filter(pk=record_id).first()
        if existing:
            changed_fields = []
            if (record.get('quantity_received') is not None
                    and existing.quantity_received != record['quantity_received']):
                existing.quantity_received = record['quantity_received']
                changed_fields.append('quantity_received')
            if changed_fields:
                existing.save(update_fields=changed_fields)
            return _record_result(record_id, True)

    transfer = BreadTransfer.objects.filter(pk=record.get('transfer')).first()
    if transfer is None:
        return _record_result(record_id, False, "dépendance manquante : transfer")
    bread_price = BreadPrice.objects.filter(pk=record.get('bread_price')).first()
    if bread_price is None:
        return _record_result(record_id, False, "dépendance manquante : bread_price")

    kwargs = dict(
        transfer=transfer, bread_price=bread_price,
        quantity_sent=record.get('quantity_sent', 0),
        quantity_received=record.get('quantity_received'),
    )
    if record_id:
        kwargs['id'] = record_id
    try:
        BreadTransferLine.objects.create(**kwargs)
    except IntegrityError:
        pass
    return _record_result(record_id, True)


# ─── Extension BUG-004 (2026-11-02) : trésorerie ─────────────────────────

def _push_local_expense(node, record):
    from core.models import ExpenseCategory
    from treasury.models import LocalExpense

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")
    if LocalExpense.objects.filter(pk=record_id).exists():
        return _record_result(record_id, True)

    if not record.get('date'):
        return _record_result(record_id, False, "date manquante")
    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    category = ExpenseCategory.objects.filter(pk=record.get('category')).first()
    if category is None:
        return _record_result(record_id, False, "dépendance manquante : category")

    expense = LocalExpense(
        id=record_id, node=bakery, description=record.get('description', ''),
        amount=_to_decimal(record.get('amount')), category=category,
        date=_date.fromisoformat(record['date']),
        node_origin=record.get('node_origin', bakery_code),
    )
    expense.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_facturier_report(node, record):
    from treasury.models import FacturierReport

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    existing = FacturierReport.objects.filter(pk=record_id).first()
    if existing:
        # Transition idempotente is_validated False→True (gérant valide
        # après coup une vacation déjà remontée) — jamais de régression.
        changed_fields = []
        if record.get('is_validated') and not existing.is_validated:
            existing.is_validated = True
            changed_fields.append('is_validated')
            if record.get('validated_at'):
                existing.validated_at = record['validated_at']
                changed_fields.append('validated_at')
        if changed_fields:
            existing.save(update_fields=changed_fields, _sync_bypass=True)
        return _record_result(record_id, True)

    if not record.get('date'):
        return _record_result(record_id, False, "date manquante")
    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    report = FacturierReport(
        id=record_id, node=bakery, team=record.get('team', ''),
        date=_date.fromisoformat(record['date']),
        total_cash_sales=_to_decimal(record.get('total_cash_sales')),
        total_credit_sales=_to_decimal(record.get('total_credit_sales')),
        theoretical_cash=_to_decimal(record.get('theoretical_cash')),
        is_validated=bool(record.get('is_validated', False)),
        validated_at=record.get('validated_at'),
        sacks_consumed=_to_decimal(record.get('sacks_consumed')),
        breads_produced_by_category=record.get('breads_produced_by_category') or {},
        breads_sold_by_category=record.get('breads_sold_by_category') or {},
        sacks_value_gap=_to_decimal(record.get('sacks_value_gap')),
        node_origin=record.get('node_origin', bakery_code),
    )
    report.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_disbursement_voucher(node, record):
    """
    SYNC.md §0/§1.2 : un `DisbursementVoucher` est aujourd'hui toujours créé
    au Cloud (`node_origin='CLOUD'`, `IsHeadquarters`) — ce handler couvre le
    cas documenté « si un poste direction local existe » (SYNC.md §1.2), par
    symétrie avec `_push_cash_closure` : c'est le Cloud qui appelle
    `append_cashbook_entry()` lui-même à réception, jamais le nœud qui
    écrirait directement le Livre de Caisse (SYNC.md §0).
    """
    from rest_framework.exceptions import ValidationError as DRFValidationError

    from treasury.models import DisbursementVoucher, CashbookEntry
    from treasury.views import append_cashbook_entry

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    existing = DisbursementVoucher.objects.filter(pk=record_id).first()
    if existing is None:
        if not record.get('date') or not record.get('motif'):
            return _record_result(record_id, False, "champs requis manquants (date/motif)")
        voucher = DisbursementVoucher(
            id=record_id, date=_date.fromisoformat(record['date']),
            motif=record.get('motif', ''), beneficiary=record.get('beneficiary', ''),
            bills_20000=record.get('bills_20000', 0), bills_10000=record.get('bills_10000', 0),
            bills_5000=record.get('bills_5000', 0), bills_1000=record.get('bills_1000', 0),
            bills_500=record.get('bills_500', 0), bills_200=record.get('bills_200', 0),
            bills_100=record.get('bills_100', 0), bills_50=record.get('bills_50', 0),
            piece_number=record.get('piece_number', ''),
            node_origin=record.get('node_origin', node.code),
        )
        voucher.compute_physical_cash()
        if not voucher.piece_number:
            voucher.piece_number = f"BV-{voucher.date.strftime('%Y%m%d')}-{str(voucher.id)[:6].upper()}"
        voucher.save(_sync_bypass=True)
        existing = voucher

    if CashbookEntry.objects.filter(source_bordereau=existing).exists():
        return _record_result(record_id, True)

    siege = Node.objects.filter(code='SIEGE').first()
    if siege is None:
        return _record_result(record_id, False, "nœud SIEGE introuvable — exécutez les migrations avant de synchroniser un bordereau")

    label = f"Bordereau de versement — {existing.motif}"
    if existing.beneficiary:
        label += f" ({existing.beneficiary})"

    def _check_sufficient_balance(last_balance):
        if existing.physical_cash_total > last_balance:
            raise DRFValidationError(
                f"Montant du bordereau ({existing.physical_cash_total:,.0f} FC) "
                f"supérieur au solde disponible ({last_balance:,.0f} FC)."
            )

    try:
        append_cashbook_entry(
            validate_balance=_check_sufficient_balance,
            node=siege, date=existing.date, piece_number=existing.piece_number,
            imputation='SORTIE', label=label, exit_amount=existing.physical_cash_total,
            source_bordereau=existing, node_origin='CLOUD',
        )
    except DRFValidationError as exc:
        return _record_result(record_id, False, str(exc.detail[0]) if hasattr(exc, 'detail') else str(exc))
    return _record_result(record_id, True)


def _push_social_contribution(node, record):
    """
    `SocialContribution` (caisse sociale, CLAUDE.md §5.1) : toujours créée et
    modifiée par le gérant d'une seule boulangerie (jamais partagée entre
    deux nœuds comme `Client`/`Invoice`) — pas de règle de conflit
    multi-nœud à arbitrer ici. Idempotent : une fois créée, seuls `is_paid`/
    `paid_at`/`amount` peuvent être mis à jour (reflet de `toggle_paid` côté
    nœud, rejoué sans effet si déjà identique).
    """
    from clients.models import Client, SocialContribution

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    existing = SocialContribution.objects.filter(pk=record_id).first()
    if existing:
        changed_fields = []
        if 'is_paid' in record and bool(record['is_paid']) != existing.is_paid:
            existing.is_paid = bool(record['is_paid'])
            changed_fields.append('is_paid')
        if 'paid_at' in record and record['paid_at'] != existing.paid_at:
            existing.paid_at = record['paid_at']
            changed_fields.append('paid_at')
        if 'amount' in record:
            new_amount = _to_decimal(record['amount'], existing.amount)
            if new_amount != existing.amount:
                existing.amount = new_amount
                changed_fields.append('amount')
        if changed_fields:
            existing.save(update_fields=changed_fields, _sync_bypass=True)
        return _record_result(record_id, True)

    client = Client.objects.filter(pk=record.get('client')).first()
    if client is None:
        return _record_result(record_id, False, "dépendance manquante : client")
    if not record.get('month') or not record.get('year'):
        return _record_result(record_id, False, "month/year manquants")

    contribution = SocialContribution(
        id=record_id, client=client, node=bakery,
        month=record['month'], year=record['year'],
        amount=_to_decimal(record.get('amount'), Decimal('3000.00')),
        is_paid=bool(record.get('is_paid', False)),
        paid_at=record.get('paid_at'),
        node_origin=record.get('node_origin', bakery_code),
    )
    contribution.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_social_distribution(node, record):
    """
    `SocialDistribution` : transition idempotente `is_closed` False→True
    (clôture annuelle côté gérant), jamais de régression — même motif que
    `_push_facturier_report`.
    """
    from clients.models import SocialDistribution

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    existing = SocialDistribution.objects.filter(pk=record_id).first()
    if existing:
        if record.get('is_closed') and not existing.is_closed:
            existing.is_closed = True
            existing.save(update_fields=['is_closed'], _sync_bypass=True)
        return _record_result(record_id, True)

    if not record.get('year'):
        return _record_result(record_id, False, "year manquant")

    distribution = SocialDistribution(
        id=record_id, node=bakery, year=record['year'],
        tarif=_to_decimal(record.get('tarif'), Decimal('700.00')),
        is_closed=bool(record.get('is_closed', False)),
        node_origin=record.get('node_origin', bakery_code),
    )
    distribution.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_social_distribution_line(node, record):
    """
    `SocialDistributionLine` : dépend de `SocialDistribution` (doit déjà
    exister, même lot ou lot précédent — ordre `PUSH_MODEL_ORDER`) et de
    `Client`. Les montants (`total_social`/`remise`/`merite`/`total_payer`)
    et `position`/`form` restent éditables par le gérant jusqu'à la clôture
    de la distribution parente : contrairement à `_push_bread_transfer`
    (machine à états), on applique ici un simple remplacement des champs
    fournis (dernier remontée gagne) — enregistrement mono-nœud, jamais
    partagé, donc pas de conflit multi-boulangerie possible par construction.
    """
    from clients.models import Client, SocialDistribution, SocialDistributionLine

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    distribution = SocialDistribution.objects.filter(pk=record.get('distribution')).first()
    if distribution is None:
        return _record_result(record_id, False, "dépendance manquante : distribution")

    existing = SocialDistributionLine.objects.filter(pk=record_id).first()
    if existing:
        if existing.distribution_id != distribution.pk:
            return _record_result(record_id, False, "distribution différente de l'enregistrement existant")
        changed_fields = []
        for field, default in (
            ('indice', existing.indice), ('total_social', existing.total_social),
            ('remise', existing.remise), ('merite', existing.merite),
            ('total_payer', existing.total_payer),
        ):
            if field in record:
                value = record[field] if field == 'indice' else _to_decimal(record[field], default)
                if value != getattr(existing, field):
                    setattr(existing, field, value)
                    changed_fields.append(field)
        for field in ('position', 'form'):
            if field in record and record[field] != getattr(existing, field):
                setattr(existing, field, record[field])
                changed_fields.append(field)
        if changed_fields:
            existing.save(update_fields=changed_fields, _sync_bypass=True)
        return _record_result(record_id, True)

    client = Client.objects.filter(pk=record.get('client')).first()
    if client is None:
        return _record_result(record_id, False, "dépendance manquante : client")

    line = SocialDistributionLine(
        id=record_id, distribution=distribution, client=client,
        indice=record.get('indice', 0),
        total_social=_to_decimal(record.get('total_social')),
        remise=_to_decimal(record.get('remise')),
        merite=_to_decimal(record.get('merite')),
        total_payer=_to_decimal(record.get('total_payer')),
        position=record.get('position', 'present'),
        form=record.get('form', 'especes'),
        node_origin=record.get('node_origin', node.code),
    )
    line.save(_sync_bypass=True)
    return _record_result(record_id, True)


PUSH_HANDLERS = {
    'clients.Client': _push_client,
    'sales.Invoice': _push_invoice,
    'sales.InvoiceLine': _push_invoice_line,
    'sync.DebtMovement': _push_debt_movement,
    'production.ProductionSession': _push_production_session,
    'production.ProductionSessionLine': _push_production_session_line,
    'production.BreadDisposal': _push_bread_disposal,
    'production.ConsumableMovement': _push_consumable_movement,
    'production.BreadTransfer': _push_bread_transfer,
    'production.BreadTransferLine': _push_bread_transfer_line,
    'treasury.LocalExpense': _push_local_expense,
    'treasury.FacturierReport': _push_facturier_report,
    'treasury.CashClosure': _push_cash_closure,
    'treasury.DisbursementVoucher': _push_disbursement_voucher,
    'clients.SocialContribution': _push_social_contribution,
    'clients.SocialDistribution': _push_social_distribution,
    'clients.SocialDistributionLine': _push_social_distribution_line,
}


def process_push_batch(node, records_by_model):
    """
    Traite un lot `push` reçu d'un nœud local : chaque enregistrement,
    de chaque modèle supporté, est traité DANS L'ORDRE de dépendance
    `PUSH_MODEL_ORDER` (SYNC.md §3.5), dans sa propre transaction (une
    ligne rejetée n'annule jamais les autres déjà acceptées — SYNC.md §3.4).

    Renvoie {model_label: [résultats par enregistrement]}.
    """
    from django.db import transaction as _tx

    results = {}
    for model_label in PUSH_MODEL_ORDER:
        records = records_by_model.get(model_label) or []
        handler = PUSH_HANDLERS[model_label]
        model_results = []
        for record in records:
            try:
                with _tx.atomic():
                    model_results.append(handler(node, record))
            except OperationalError as exc:
                # BUG-062 (réouverture) : un verrou SQLite épuisé après les
                # 150 retentatives internes (`_WRITE_MAX_RETRIES`, voir
                # `record_debt_movement`/`recompute_client_debt`) est un
                # échec TRANSITOIRE d'infrastructure, jamais un rejet
                # métier. Le capturer ici dans `_record_result(..., False,
                # ...)` l'archiverait pour toujours dans `SyncBatchLog`
                # (idempotence de lot) : un rejeu légitime du même
                # `batch_id` après coupure réseau retrouverait ce résultat
                # figé et ne recréerait JAMAIS l'enregistrement perdu — la
                # dette client correctement facturée hors-ligne
                # disparaîtrait silencieusement et définitivement (constat
                # testeur-charge, 2026-10-23). On NE DOIT PAS convertir ceci
                # en résultat terminal : on laisse l'exception se propager
                # jusqu'à `sync.views.PushView.post`, qui retente la
                # construction ENTIÈRE du lot depuis le début (y compris le
                # contrôle d'idempotence `existing_batch`) — sans jamais
                # avoir persisté de `SyncBatchLog` pour ce `batch_id`. Les
                # enregistrements déjà traités avec succès dans CET appel
                # sont sans risque à rejouer : chaque gestionnaire
                # (`_push_client`, `_push_invoice`, `_push_debt_movement`
                # via `movement_id`...) est lui-même idempotent par
                # construction (no-op sur un enregistrement déjà créé) —
                # aucun double-comptage possible.
                raise
            except Exception as exc:  # defensive — un modèle ne doit jamais planter tout le lot
                model_results.append(_record_result(record.get('id'), False, f"erreur serveur : {exc}"))
        if model_results:
            results[model_label] = model_results

    # Modèles envoyés mais non supportés en V1 : rejetés explicitement,
    # jamais ignorés en silence (SYNC.md §3.4).
    for model_label, records in records_by_model.items():
        if model_label not in PUSH_HANDLERS and records:
            results[model_label] = [
                _record_result(r.get('id'), False, "modèle non supporté en V1")
                for r in records
            ]
    return results
