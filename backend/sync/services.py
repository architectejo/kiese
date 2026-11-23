"""
Logique métier de synchronisation — séparée des vues pour rester testable
indépendamment du transport HTTP (SYNC.md §2.2, §3).
"""

import logging
import random
import re
import threading
import time
from datetime import date as _date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Sum

from core.models import Node
from .models import DebtMovement, SyncConflictLog

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

logger = logging.getLogger(__name__)

# BUG-721 : plage de `DebtMovement.amount` / `Client.current_debt`
# (DecimalField 14 chiffres dont 2 décimales) : |valeur| < 10^12.
MAX_DEBT_ABS = Decimal(10) ** 12


def recompute_client_debt(client_id, opening=None):
    """
    Recalcule `Client.current_debt` comme la somme de tous ses
    `DebtMovement` et republie `category` (SYNC.md §2.2 point 3).

    Verrouille la ligne `Client` pendant le recalcul : deux mouvements
    concurrents pour le même client (ex. deux lots `push` de deux nœuds
    différents arrivant en même temps) ne peuvent jamais produire un
    recalcul fondé sur une lecture obsolète.

    BUG-728 : `opening` (Decimal, optionnel) est la dette d'ouverture non
    couverte par un mouvement (import Excel, dette initiale) ; elle est
    ajoutée à la somme au lieu d'être écrasée. Absent = comportement
    historique (somme pure des mouvements).
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
                if opening:
                    total = total + opening
                old_category = client.category
                client.current_debt = total
                client.refresh_category()
                # BUG-787 : `updated_at` doit avancer pour que le pull
                # incrémental renvoie ce client aux autres postes.
                client.save(update_fields=['current_debt', 'category', 'updated_at'])
                client.notify_risk_transition(old_category)  # BUG-945
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

    from clients.models import Client

    with transaction.atomic():
        # BUG-728 : dette d'ouverture = écart entre la dette stockée et la
        # somme des mouvements connus AVANT ce mouvement. Elle est conservée
        # (jamais écrasée) ; un rejeu du même mouvement la retrouve à
        # l'identique (somme inchangée), donc reste idempotent.
        locked = Client.objects.select_for_update().get(pk=client.pk)
        total_before = DebtMovement.objects.filter(client_id=client.pk).aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        opening = locked.current_debt - total_before
        movement = record_debt_movement(
            client, amount, kind, node_origin,
            invoice=invoice, note=note, movement_id=movement_id,
        )
        recompute_client_debt(client.pk, opening=opening)
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
    'production.ConsumableInventory',
    'production.ConsumableCount',
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

# BUG-905/909 : une ligne ne s'ajoute pas à une fournée clôturée ni à une
# facture livrée/annulée (comme la voie REST). Exception légitime : le nœud
# pousse la fournée/facture DÉJÀ terminée avec ses lignes dans le MÊME lot
# (le parent précède ses lignes dans PUSH_MODEL_ORDER). Le lot en cours
# retient donc les parents créés/passés à l'état terminal par ce lot.
_batch_ctx = threading.local()


def _batch_terminal_parents():
    if not hasattr(_batch_ctx, 'parents'):
        _batch_ctx.parents = set()
    return _batch_ctx.parents


def _record_result(record_id, accepted, reason=None):
    result = {'id': str(record_id)[:64], 'status': ACCEPTED if accepted else REJECTED}
    if reason:
        result['reason'] = reason
    return result


def _log_conflict(node, model_label, object_id, conflict_type, detail=''):
    """
    Journalise un conflit. BUG-723 : une seule ligne NON RÉSOLUE par
    (nœud, modèle, objet, type) ; un rejeu incrémente `occurrences` au lieu
    d'ajouter une ligne (journal non inondable par un nœud défaillant).
    """
    from django.db.models import F

    from .models import SyncConflictLog
    object_id = str(object_id)[:40]
    existing = SyncConflictLog.objects.filter(
        node=node, model_label=model_label, object_id=object_id,
        conflict_type=conflict_type, resolved_at__isnull=True,
    ).first()
    if existing is not None:
        SyncConflictLog.objects.filter(pk=existing.pk).update(occurrences=F('occurrences') + 1)
        return existing
    return SyncConflictLog.objects.create(
        node=node, model_label=model_label, object_id=object_id,
        conflict_type=conflict_type, detail=detail,
    )


def _to_decimal(value, default=Decimal('0')):
    if value is None or value == '':
        return default
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return default


_CLIENT_TEXT_FIELDS = (('first_name', 100, True), ('last_name', 100, True), ('phone', 25, False),
                       ('address', None, False), ('notes', None, False))


def _apply_client_identity_push(existing, record, node):
    """
    BUG-941 (SYNC.md §5.1) : identité et paramètres d'un client (nom, téléphone,
    adresse, plafond, taux, cotisation, type) = dernier écrivain gagne, poussés
    par le nœud propriétaire. `current_debt`, `total_breads_received` et le
    stock ne sont JAMAIS touchés (§2.2). Un enregistrement plus ancien que la
    version du Cloud (`updated_at`) est ignoré (no-op accepté). Champ invalide :
    tout l'enregistrement est rejeté, rien n'est écrit.
    """
    from clients.models import Client

    record_id = record.get('id')
    try:
        # BUG-970 : version d'identité du poste si fournie, sinon `updated_at`
        # (ancien poste : rien n'est envoyé, le push est appliqué).
        sent_at = _parse_aware_datetime(record.get('identity_updated_at') or record.get('updated_at'))
    except ValueError as exc:
        return _record_result(record_id, False, str(exc))
    # BUG-951 : la garde porte sur la version de l'IDENTITÉ seule. Un mouvement de
    # dette (d'un autre poste) fait avancer `updated_at` sans toucher l'identité :
    # il ne doit jamais invalider une édition. Sans édition d'identité tracée, la
    # référence est `updated_at` tant qu'aucun mouvement de dette n'existe ; sinon
    # `updated_at` ne dit plus rien de l'identité et le propriétaire fait autorité.
    reference = existing.identity_updated_at
    if reference is None and not DebtMovement.objects.filter(client_id=existing.pk).exists():
        reference = existing.updated_at
    if sent_at is not None and reference is not None and sent_at < reference:
        # BUG-969 : perte tracée (journal de conflits + notification), statut ACCEPTED
        # conservé pour que le poste marque l'enregistrement synchronisé.
        # Un rejeu d'un push déjà appliqué (mêmes valeurs) n'est pas une perte : pas de bruit.
        def _differs(name):
            if name not in record or record[name] in (None, ''):
                return False
            cur = getattr(existing, name)
            try:
                return (Decimal(str(record[name])) != Decimal(str(cur))
                        if isinstance(cur, Decimal) else str(record[name]) != str(cur))
            except InvalidOperation:
                return True
        if not any(_differs(n) for n in ('first_name', 'last_name', 'phone', 'address', 'notes', 'credit_limit',
                                          'commission_rate', 'cotisation_sociale', 'client_type')):
            return _record_result(record_id, True)
        _log_conflict(
            node, 'clients.Client', record_id, 'IDENTITE_OBSOLETE',
            f"Modification d'identité du client {existing.code} poussée par {node.code} ignorée : "
            f"plus ancienne que la version du Cloud ({reference.isoformat()}).")
        try:
            from core.utils import create_notification
            create_notification(
                title="Modification de client ignorée",
                message=(f"La modification du client {existing.code} faite sur {node.code} est plus ancienne "
                         f"que celle déjà enregistrée : elle a été ignorée. Vérifiez la fiche client."),
                severity='WARNING', node_origin=node.code,
            )
        except Exception:  # la notification ne doit jamais faire échouer le lot
            logger.warning("Notification d'identité obsolète non créée (%s)", record_id)
        return _record_result(record_id, True)

    changes = {}
    try:
        for name, max_len, required in _CLIENT_TEXT_FIELDS:
            if name not in record:
                continue
            val = record[name]
            if val is None and not required:
                val = ''
            if not isinstance(val, str) or (required and not val.strip()) or (max_len and len(val) > max_len):
                raise ValueError(f"« {name} » invalide")
            changes[name] = val
        if record.get('credit_limit') not in (None, ''):
            changes['credit_limit'] = _sync_decimal(record['credit_limit'], 'credit_limit', 2,
                                                    Decimal('0'), Decimal('10000000'))
        if record.get('commission_rate') not in (None, ''):
            changes['commission_rate'] = _sync_decimal(record['commission_rate'], 'commission_rate', 2,
                                                       Decimal('0'), MAX_SYNC_COMMISSION_RATE)
        if 'cotisation_sociale' in record:
            raw = record['cotisation_sociale']
            changes['cotisation_sociale'] = (None if raw in (None, '') else
                                             _sync_decimal(raw, 'cotisation_sociale', 2, Decimal('0'), max_digits=10))
        if record.get('client_type') not in (None, ''):
            if record['client_type'] not in Client.ClientType.values:
                raise ValueError("« client_type » invalide")
            changes['client_type'] = record['client_type']
    except ValueError as exc:
        return _record_result(record_id, False, str(exc))

    changes = {k: v for k, v in changes.items() if getattr(existing, k) != v}
    if not changes:
        return _record_result(record_id, True)
    with transaction.atomic():
        locked = Client.objects.select_for_update().get(pk=existing.pk)
        old_category = locked.category
        for k, v in changes.items():
            setattr(locked, k, v)
        fields = list(changes)
        if 'credit_limit' in changes:
            locked.refresh_category()
            fields.append('category')
        from django.utils import timezone
        locked.identity_updated_at = timezone.now()  # BUG-951
        locked.save(update_fields=fields + ['updated_at', 'identity_updated_at'], _sync_bypass=True)
        locked.notify_risk_transition(old_category)
    return _record_result(record_id, True)


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
        return _apply_client_identity_push(existing, record, node)  # BUG-941

    bakery_code = record.get('node') or node.code
    try:
        bakery = Node.objects.get(code=bakery_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, f"boulangerie inconnue : {bakery_code}")

    # BUG-724 : collision de code (UNIQUE) = conflit explicite et journalisé,
    # jamais un rejet silencieux qui fuit le détail SQL.
    code = record.get('code') or ''
    if code and Client.objects.filter(code=code).exists():
        _log_conflict(
            node, 'clients.Client', record_id, 'CODE_CLIENT_DUPLIQUE',
            f"Le code client « {code} » est déjà attribué à un autre client : "
            f"le client {record_id} poussé par {node.code} est rejeté.",
        )
        return _record_result(record_id, False, "code client déjà utilisé par un autre client")

    client = Client(
        id=record_id,
        code=code,
        first_name=record.get('first_name', ''),
        last_name=record.get('last_name', ''),
        phone=record.get('phone', ''),
        address=record.get('address', ''),
        node=bakery,
        cotisation_sociale=(_to_decimal(record.get('cotisation_sociale'), Decimal('0'))
                            if record.get('cotisation_sociale') not in (None, '') else None),
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


def _parse_aware_datetime(value):
    """
    BUG-323 : normalise une date/heure de payload JSON (chaîne ISO, datetime
    ou None) en datetime aware. Lève ValueError si la valeur est illisible.
    """
    from datetime import datetime as _datetime

    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    if value in (None, ''):
        return None
    if isinstance(value, str):
        try:
            parsed = parse_datetime(value.strip())
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValueError(f"date/heure invalide : {value!r}")
        value = parsed
    elif not isinstance(value, _datetime):
        raise ValueError(f"date/heure invalide : {value!r}")
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value


def _push_invoice(node, record):
    from clients.models import Client
    from sales.models import Invoice

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    try:
        delivered_at = _parse_aware_datetime(record.get('delivered_at'))
        not_served_at = _parse_aware_datetime(record.get('not_served_at'))
    except ValueError as exc:
        return _record_result(record_id, False, str(exc))

    # BUG-725 : montants jamais négatifs (la BP négative se porte par
    # `debt_before`/`debt_after`, pas par la commande ni le versement).
    for fname in ('order_total', 'payment_amount', 'initial_order_total'):
        raw = record.get(fname)
        if raw not in (None, '') and _to_decimal(raw) < 0:
            return _record_result(record_id, False, f"{fname} ne peut pas être négatif")

    existing = Invoice.objects.filter(pk=record_id).first()
    if existing:
        # Transition de statut idempotente (ex. livraison confirmée côté
        # nœud, remontée après coup) — jamais de régression PENDING←DELIVERED.
        new_status = record.get('status')
        changed_fields = []
        if new_status and new_status != existing.status:
            if existing.status == 'PENDING' and new_status in ('DELIVERED', 'CANCELLED', 'NOT_SERVED'):
                existing.status = new_status
                changed_fields.append('status')
                if delivered_at:
                    existing.delivered_at = delivered_at
                    changed_fields.append('delivered_at')
                # BUG-321 : Non servi / livraison partielle (BUG-318) — les
                # montants réduits et le motif remontent avec la transition.
                if new_status == 'NOT_SERVED':
                    if record.get('not_served_reason') not in (None, ''):
                        existing.not_served_reason = record['not_served_reason']
                        changed_fields.append('not_served_reason')
                    if not_served_at:
                        existing.not_served_at = not_served_at
                        changed_fields.append('not_served_at')
                for fname in ('order_total', 'payment_amount', 'debt_after', 'initial_order_total'):
                    if record.get(fname) not in (None, ''):
                        setattr(existing, fname, _to_decimal(record[fname]))
                        changed_fields.append(fname)
        if changed_fields:
            existing.save(update_fields=changed_fields, _sync_bypass=True)
            if 'status' in changed_fields and existing.status in ('DELIVERED', 'CANCELLED'):
                _batch_terminal_parents().add(str(existing.pk))
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
        delivered_at=delivered_at,
        node_origin=record.get('node_origin', bakery_code),
    )
    invoice.save(_sync_bypass=True)
    if invoice.status in ('DELIVERED', 'CANCELLED'):
        _batch_terminal_parents().add(str(invoice.pk))
    return _record_result(record_id, True)


# BUG-331/332 : borne haute d'une quantité de ligne (line_total est un
# Decimal(14, 2) : 1 000 000 x prix unitaire reste largement dans la plage).
MAX_LINE_QUANTITY = 1_000_000


def _parse_line_quantity(value):
    """Retourne un entier 0..MAX_LINE_QUANTITY ou None si la valeur est invalide.

    Refuse : booléens, flottants non entiers/NaN/infinis, chaînes non
    entières (« 2.5 », « 1e3 »), négatifs et valeurs hors borne.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if value != value or value in (float('inf'), float('-inf')) or value != int(value):
            return None
        number = int(value)
    elif isinstance(value, str):
        try:
            number = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    if number < 0 or number > MAX_LINE_QUANTITY:
        return None
    return number


def _parse_line_price(value):
    """BUG-519 : prix unitaire en FC entiers >= 0 (Decimal), sinon None.

    Refuse booléens, flottants, NaN/infini, négatifs, non numériques et
    valeurs fractionnaires (les champs du modèle sont des entiers FC).
    """
    from decimal import Decimal, InvalidOperation
    if isinstance(value, bool) or isinstance(value, float):
        return None
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, (str, Decimal)):
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            return None
    else:
        return None
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        return None
    if number > 100_000_000:
        return None
    return int(number)


def _resolve_invoice_line(record_id, record):
    """BUG-919 : retrouve la ligne déjà connue du cloud pour ce payload.

    Contrat d'id : l'id envoyé par le poste (PK entière locale) n'est qu'un
    INDICE. Il désigne la ligne cloud de même PK seulement si elle appartient à
    la facture indiquée (ou si la facture n'est pas précisée : ancien payload).
    Sinon (collision avec la ligne d'un autre poste), la ligne est cherchée par
    clé naturelle (facture, catégorie de pain)."""
    from sales.models import InvoiceLine

    invoice_uuid = _strict_uuid(record.get('invoice'))
    line = None
    id_valid = (record_id not in (None, '') and not isinstance(record_id, bool)
                and str(record_id).strip().isdigit() and str(record_id).isascii())
    if id_valid:
        line = InvoiceLine.objects.filter(pk=int(str(record_id).strip())).first()
    bp = _bread_price_or_none(record.get('bread_price'))

    def natural():
        # Clé naturelle (facture, catégorie[, prix net]) : BUG-938/940.
        if invoice_uuid is None or bp is None:
            return None
        qs = InvoiceLine.objects.filter(invoice_id=invoice_uuid, bread_price=bp).order_by('pk')
        price = record.get('unit_price')
        if price is not None:
            exact = _parse_line_price(price)
            if exact is not None:
                match = qs.filter(unit_price=exact).first()
                if match is not None:
                    return match
        return qs.first()

    if not id_valid:
        return natural()    # BUG-940 : id absent / non numérique -> idempotent
    if line is None:
        return None     # id libre : nouvelle ligne (créée avec cet id)
    if invoice_uuid is None:
        # BUG-955 : repli par l'id seul réservé à l'ancien payload SANS clé `invoice`.
        return line if 'invoice' not in record else None
    if line.invoice_id == invoice_uuid and (bp is None or line.bread_price_id == bp.pk):
        return line
    # id pris par la ligne d'une autre facture, ou d'une autre catégorie de la
    # même facture (BUG-938) : collision d'id entre postes, on n'écrase pas.
    return natural()


def _push_invoice_line(node, record):
    from core.models import BreadPrice
    from sales.models import Invoice, InvoiceLine

    record_id = record.get('id')
    existing_line = _resolve_invoice_line(record_id, record)
    if existing_line is not None:
        # BUG-321 : quantité servie réduite (livraison partielle / non servi).
        # Le prix figé et le commandé initial restent inchangés ; on ne
        # propage que quantity / ordered_quantity (line_total recalculé).
        # BUG-324 : un push rejoué/retardé ne doit jamais ramener la ligne
        # d'une facture terminale (NOT_SERVED/DELIVERED/CANCELLED) à une
        # quantité plus ancienne : sur statut terminal, la quantité servie ne
        # peut que diminuer et le commandé initial, une fois renseigné, n'est
        # plus touché.
        inv_row = Invoice.objects.filter(pk=existing_line.invoice_id).values_list(
            'status', 'node_id').first()
        inv_status = inv_row[0] if inv_row else None
        # BUG-732 : seule la boulangerie propriétaire de la facture modifie ses lignes.
        if inv_row is not None and inv_row[1] != node.pk:
            return _record_result(record_id, False, "ligne d'une facture d'une autre boulangerie refusée")
        terminal = inv_status in ('NOT_SERVED', 'DELIVERED', 'CANCELLED')
        changed = []
        for fname in ('quantity', 'ordered_quantity'):
            val = record.get(fname)
            if val is None:
                continue
            # BUG-331/332 : entier borné strict ; booléen, non-entier,
            # négatif, infini ou énorme -> REJECTED (jamais de 500).
            val = _parse_line_quantity(val)
            if val is None:
                return _record_result(record_id, False, f"{fname} invalide")
            current = getattr(existing_line, fname)
            if val == current:
                continue
            if terminal:
                # Commandé initial : renseigné une seule fois (None -> valeur),
                # jamais réécrit ; quantité servie : uniquement à la baisse.
                if fname == 'ordered_quantity' and current is not None:
                    continue
                if fname == 'quantity' and val > current:
                    # Quantité périmée (supérieure à la servie) = l'ancien
                    # commandé : on la retient comme commandé initial si
                    # celui-ci n'est pas encore renseigné.
                    if existing_line.ordered_quantity is None:
                        existing_line.ordered_quantity = val
                        changed.append('ordered_quantity')
                    continue
            setattr(existing_line, fname, val)
            changed.append(fname)
        if changed:
            # update() : `InvoiceLine.save()` re-lirait le prix du catalogue.
            InvoiceLine.objects.filter(pk=existing_line.pk).update(
                quantity=existing_line.quantity,
                ordered_quantity=existing_line.ordered_quantity,
                line_total=existing_line.quantity * existing_line.unit_price,
            )
        return _record_result(record_id, True)

    invoice_uuid = _strict_uuid(record.get('invoice'))
    invoice = Invoice.objects.filter(pk=invoice_uuid).first() if invoice_uuid else None
    if invoice is None:
        return _record_result(record_id, False, "dépendance manquante : invoice")
    # BUG-732 (a) : jamais de ligne sur la facture d'une autre boulangerie.
    if invoice.node_id != node.pk:
        return _record_result(record_id, False, "facture d'une autre boulangerie : ligne refusée")
    # BUG-909 : pas de nouvelle ligne sur une facture livrée/annulée (sauf
    # facture poussée terminée dans ce même lot, avec ses lignes).
    if invoice.status in ('DELIVERED', 'CANCELLED') and str(invoice.pk) not in _batch_terminal_parents():
        return _record_result(record_id, False, "facture livrée ou annulée : ajout de ligne refusé")
    bp_id = record.get('bread_price')
    if isinstance(bp_id, bool) or not isinstance(bp_id, (int, str)) or not str(bp_id).strip().isdigit():
        return _record_result(record_id, False, "dépendance manquante : bread_price")
    bread_price = BreadPrice.objects.filter(pk=int(str(bp_id).strip())).first()
    if bread_price is None:
        return _record_result(record_id, False, "dépendance manquante : bread_price")

    quantity = _parse_line_quantity(record.get('quantity', 0))
    if quantity is None:
        return _record_result(record_id, False, "quantity invalide")
    # BUG-519 : prix figés du nœud local. Absents (ancien payload) -> None et
    # comportement historique (tarif courant figé par InvoiceLine.save()).
    unit_price = full_unit_price = None
    if record.get('full_unit_price') is not None:
        full_unit_price = _parse_line_price(record.get('full_unit_price'))
        if full_unit_price is None:
            return _record_result(record_id, False, "full_unit_price invalide")
    if record.get('unit_price') is not None:
        unit_price = _parse_line_price(record.get('unit_price'))
        if unit_price is None:
            return _record_result(record_id, False, "unit_price invalide")
    # BUG-732 (b) : le prix net ne peut pas dépasser le prix plein figé.
    if unit_price is not None and full_unit_price is not None and unit_price > full_unit_price:
        return _record_result(record_id, False, "unit_price supérieur au prix plein")
    # BUG-721 : line_total = DecimalField(14, 2) -> |total| < 10^12.
    effective_price = (unit_price if unit_price is not None
                       else full_unit_price if full_unit_price is not None else bread_price.unit_price)
    if Decimal(quantity) * Decimal(effective_price) >= MAX_DEBT_ABS:
        return _record_result(record_id, False, "total de ligne hors plage")
    kwargs = dict(invoice=invoice, bread_price=bread_price, quantity=quantity)
    if full_unit_price is not None:
        kwargs['full_unit_price'] = full_unit_price
    # BUG-919 : l'id du poste n'est repris comme clé que s'il est libre ; sinon
    # (collision avec la ligne d'un autre poste) la clé cloud est auto-attribuée
    # et la ligne se retrouve ensuite par (facture, catégorie).
    if record_id and str(record_id).strip().isdigit() and str(record_id).isascii()             and not InvoiceLine.objects.filter(pk=int(record_id)).exists():
        kwargs['id'] = int(record_id)
    line = InvoiceLine.objects.create(**kwargs)
    if unit_price is not None and line.unit_price != unit_price:
        # Prix net exact du nœud local (ex. arrondi soldée) : update() pour ne
        # pas repasser par save().
        InvoiceLine.objects.filter(pk=line.pk).update(
            unit_price=unit_price, line_total=quantity * unit_price)
    return _record_result(record_id, True)


def _push_debt_movement(node, record):
    from clients.models import Client
    from sales.models import Invoice

    record_id = record.get('id')
    client_uuid = _strict_uuid(record.get('client'))
    client = Client.objects.filter(pk=client_uuid).first() if client_uuid else None
    if client is None:
        return _record_result(record_id, False, "dépendance manquante : client")

    invoice = None
    invoice_id = record.get('invoice')
    if invoice_id:
        invoice_uuid = _strict_uuid(invoice_id)
        invoice = Invoice.objects.filter(pk=invoice_uuid).first() if invoice_uuid else None
        if invoice is None:
            return _record_result(record_id, False, "dépendance manquante : invoice")
        # BUG-722 : on ne rattache pas un mouvement à la facture d'une autre boulangerie.
        if invoice.node_id != node.pk:
            return _record_result(record_id, False, "facture d'une autre boulangerie refusée")

    # BUG-933/934 : montant obligatoire, ASCII, 2 décimales au plus (comme BUG-900).
    if record.get('amount') in (None, ''):
        return _record_result(record_id, False, "« amount » obligatoire")
    try:
        amount = _sync_decimal(record['amount'], 'amount', 2)
    except ValueError as exc:
        return _record_result(record_id, False, str(exc))
    # BUG-721 : plage du DecimalField(14, 2) — jamais de valeur qui rendrait
    # `Client.current_debt` illisible (SQLite n'applique pas la contrainte).
    if abs(amount) >= MAX_DEBT_ABS:
        return _record_result(record_id, False, "montant hors plage autorisée")

    # BUG-727 : un mouvement est immuable ; le rejouer avec un autre montant
    # ou un autre client est un conflit (rejeté et journalisé).
    if record_id:
        existing = DebtMovement.objects.filter(pk=record_id).first()
        if existing is not None:
            if existing.node_origin != node.code or existing.client_id != client.pk \
                    or existing.amount != amount.quantize(Decimal('0.01')):
                _log_conflict(
                    node, 'sync.DebtMovement', record_id, 'MOUVEMENT_IMMUABLE_MODIFIE',
                    f"Mouvement {record_id} déjà enregistré ({existing.amount} FC) : "
                    f"le rejeu avec un contenu différent ({amount} FC) est rejeté.",
                )
                return _record_result(record_id, False, "mouvement déjà enregistré avec un contenu différent")
            return _record_result(record_id, True)

    if amount != 0:
        total = DebtMovement.objects.filter(client_id=client.pk).aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        if abs(client.current_debt + amount) >= MAX_DEBT_ABS or abs(total + amount) >= MAX_DEBT_ABS:
            return _record_result(record_id, False, "dette cumulée hors plage autorisée")

    kind = record.get('kind') or DebtMovement.Kind.ADJUSTMENT
    apply_debt_movement(
        client, amount, kind,
        node_origin=node.code,
        invoice=invoice, note=record.get('note') or '', movement_id=record_id,
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
        # BUG-722 : jamais d'écriture de clôture (donc de livre de caisse) au
        # nom d'une autre boulangerie que celle du jeton.
        if bakery.pk != node.pk:
            return _record_result(record_id, False, "clôture d'une autre boulangerie refusée")
        closure_date = _strict_date(record.get('date'))
        if closure_date is None:
            return _record_result(record_id, False, "date invalide (AAAA-MM-JJ attendu)")
        # BUG-960 : comme REST (BUG-037/277), pas de clôture confirmée tant qu'un transfert
        # entrant de la boulangerie présente un écart non résolu.
        if record.get('is_validated'):
            from treasury.views import _unresolved_incoming_transfer_gap
            gap = _unresolved_incoming_transfer_gap(bakery)
            if gap:
                return _record_result(
                    record_id, False,
                    f"clôture confirmée refusée : transfert entrant en écart non résolu ({gap})")

        closure = CashClosure(
            id=record_id,
            node=bakery,
            date=closure_date,
            total_entries=_to_decimal(record.get('total_entries')),
            total_expenses=_to_decimal(record.get('total_expenses')),
            **_bills_kwargs(record),
            # BUG-971 : un jeton de boulangerie ne confirme jamais une clôture
            # (remarque.md l.156, BUG-200) ; seule la voie REST IsHeadquarters
            # (validate / push_to_cashbook) la confirme.
            is_validated=False,
            notes=record.get('notes', ''),
            node_origin=record.get('node_origin', bakery_code),
        )
        closure.compute_physical_cash()
        closure.save(_sync_bypass=True)
        existing = closure

    if existing.node_id != node.pk:
        return _record_result(record_id, False, "clôture d'une autre boulangerie refusée")

    if existing.is_validated and not existing.cashbook_entries.exists():
        from treasury.views import _unresolved_incoming_transfer_gap
        gap = _unresolved_incoming_transfer_gap(existing.node)
        if gap:  # BUG-960 : même blocage que push_to_cashbook (REST)
            return _record_result(
                record_id, False,
                f"versement au livre refusé : transfert entrant en écart non résolu ({gap})")
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
        # BUG-939 : tant que la fournée est ouverte, ses champs modifiables
        # (farine, valeur du sac, notes) suivent le poste (valeurs déjà bornées
        # par _check_production_session) ; jamais sur une fournée close.
        if not existing.is_closed and existing.node_id == node.pk:
            upd = {}
            raw_flour = record.get('flour_sacks_used')
            if raw_flour not in (None, ''):
                new_flour = _to_decimal(raw_flour)
                if new_flour != existing.flour_sacks_used:
                    upd['flour_sacks_used'] = new_flour
            raw_sac = record.get('sac_value_fc_used')
            if raw_sac not in (None, ''):
                new_sac = _sync_int(raw_sac, 'sac_value_fc_used', 0, 100_000_000)
                if new_sac != existing.sac_value_fc_used:
                    upd['sac_value_fc_used'] = new_sac
            if isinstance(record.get('notes'), str) and record['notes'] != existing.notes:
                upd['notes'] = record['notes']
            if upd:
                from production.models import ProductionSession as _PS
                _PS.objects.filter(pk=existing.pk).update(**upd)
                for k, v in upd.items():
                    setattr(existing, k, v)
                _recompute_session_totals(existing)
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
            if 'is_closed' in changed_fields:
                _batch_terminal_parents().add(str(existing.pk))
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
        # BUG-924 : les totaux (pains, FC, rendement, écart) ne sont JAMAIS copiés
        # du poste : ils sont recalculés depuis les lignes (compute_totals, comme
        # la voie REST) après la sauvegarde, puis à chaque ligne poussée.
        # BUG-956/957 : décimal entier ('150000.0') normalisé ; 0 conservé (comme la mise à jour).
        sac_value_fc_used=(200000 if record.get('sac_value_fc_used') in (None, '')
                           else _sync_int(record['sac_value_fc_used'], 'sac_value_fc_used', 0, 100_000_000)),
        is_closed=bool(record.get('is_closed', False)),
        closed_at=record.get('closed_at'),
        closure_summary=record.get('closure_summary'),
        notes=record.get('notes', ''),
        node_origin=record.get('node_origin', bakery_code),
    )
    session.save(_sync_bypass=True)
    _recompute_session_totals(session)
    if session.is_closed:
        _batch_terminal_parents().add(str(session.pk))
    return _record_result(record_id, True)


def _recompute_session_totals(session):
    """BUG-924 : totaux de la fournée dérivés de ses lignes (update() : pas de save())."""
    from production.models import ProductionSession
    session.compute_totals()
    ProductionSession.objects.filter(pk=session.pk).update(
        total_breads=session.total_breads, total_fc_produced=session.total_fc_produced,
        theoretical_yield=session.theoretical_yield, yield_gap=session.yield_gap,
        breads_300=session.breads_300, breads_400=session.breads_400,
        breads_500=session.breads_500, breads_1000=session.breads_1000,
    )


def _push_production_session_line(node, record):
    """Ligne de fournée. BUG-919 : l'id local du poste (PK entière auto-incrémentée)
    n'est JAMAIS utilisé comme clé cloud ; la ligne est identifiée par sa clé
    naturelle (session, catégorie de pain, source), unique en base. Rejeu
    idempotent, pas de collision entre postes, lignes déjà synchronisées
    retrouvées sans doublon."""
    from production.models import ProductionSession, ProductionSessionLine

    record_id = record.get('id')
    session_uuid = _strict_uuid(record.get('session'))
    session = ProductionSession.objects.filter(pk=session_uuid).first() if session_uuid else None
    if session is None:
        return _record_result(record_id, False, "dépendance manquante : session")
    if session.node_id != node.pk:
        return _record_result(record_id, False, "session d'une autre boulangerie refusée")
    bread_price = _bread_price_or_none(record.get('bread_price'))
    if bread_price is None:
        return _record_result(record_id, False, "dépendance manquante : bread_price")

    # BUG-904 : une quantité absente/nulle n'est jamais « acceptée » sans ligne.
    if record.get('quantity', 0) is None:
        return _record_result(record_id, False, "« quantity » manquante")
    quantity = _sync_int(record.get('quantity', 0), 'quantity')
    # BUG-142 : `source` (DECLARED/CARRYOVER), défaut DECLARED si absent.
    source = record.get('source') or ProductionSessionLine.Source.DECLARED
    if source not in ProductionSessionLine.Source.values:
        return _record_result(record_id, False, "« source » invalide")

    # BUG-905 : pas de nouvelle valeur sur une fournée clôturée (sauf fournée
    # terminée dans ce même lot, avec ses lignes).
    locked = session.is_closed and str(session.pk) not in _batch_terminal_parents()
    existing = ProductionSessionLine.objects.filter(
        session=session, bread_price=bread_price, source=source).first()
    if existing is not None:
        if existing.quantity == quantity:
            return _record_result(record_id, True)      # rejeu idempotent
        if locked:
            return _record_result(record_id, False, "fournée clôturée : modification de ligne refusée")
        # BUG-920 : même (fournée, catégorie, source) avec une autre quantité =
        # mise à jour de la ligne (ex. incrément à la livraison), jamais « accepté » sans effet.
        ProductionSessionLine.objects.filter(pk=existing.pk).update(quantity=quantity)
        _recompute_session_totals(session)
        return _record_result(record_id, True)
    if locked:
        return _record_result(record_id, False, "fournée clôturée : ajout de ligne refusé")

    try:
        with transaction.atomic():
            ProductionSessionLine.objects.create(
                session=session, bread_price=bread_price, quantity=quantity, source=source)
    except IntegrityError:
        return _record_result(record_id, False, "ligne en double (écriture concurrente) : à rejouer")
    _recompute_session_totals(session)
    return _record_result(record_id, True)


def _bread_price_or_none(raw):
    from core.models import BreadPrice
    if isinstance(raw, bool) or not str(raw).strip().isdigit() or not str(raw).strip().isascii():
        return None
    return BreadPrice.objects.filter(pk=int(str(raw).strip())).first()


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
    if session.node_id != node.pk:
        return _record_result(record_id, False, "session d'une autre boulangerie refusée")
    bread_price = BreadPrice.objects.filter(pk=record.get('bread_price')).first()
    if bread_price is None:
        return _record_result(record_id, False, "dépendance manquante : bread_price")

    # BUG-968 : '3.0' / '1e1' / 3.0 (entiers valides) normalisés en int, jamais de
    # chaîne brute dans quantity * unit_price_sold ; rejet motivé sinon.
    try:
        qty = _sync_int(record.get('quantity') or 0, 'quantity', minimum=-MAX_SYNC_INT)
        unit_price = _sync_int(record.get('unit_price_sold') or 0, 'unit_price_sold')
    except ValueError as exc:
        return _record_result(record_id, False, str(exc))
    disposal = BreadDisposal(
        id=record_id, node=bakery, session=session, bread_price=bread_price,
        disposal_type=record.get('disposal_type', ''),
        quantity=qty,
        unit_price_sold=unit_price,
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
    # BUG-788 : un poste ne modifie que le stock de consommables de sa boulangerie.
    if bakery.pk != node.pk:
        return _record_result(record_id, False, "mouvement de consommable d'une autre boulangerie refusé")

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
        if session.node_id != node.pk:
            return _record_result(record_id, False, "session d'une autre boulangerie refusée")

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
        # BUG-143 (annule BUG-041, demande client directe 2026-11-10) :
        # `ConsumableMovement.save()` n'empêche plus une sortie de faire
        # passer le stock consolidé Cloud en négatif — ce `except` n'est
        # donc plus déclenché pour ce motif précis. Conservé par prudence
        # pour toute AUTRE `ValidationError` du modèle. Conséquence notée
        # pour `architecte-sync`/`auditeur-comptable` (pas tranchée ici,
        # hors périmètre de ce ticket) : une sortie (EXIT) qui arrive avant
        # son entrée (ENTRY) correspondante est maintenant ACCEPTÉE tout de
        # suite plutôt que retentée au cycle suivant, valorisée au CUMP
        # courant du stock consolidé (0 si la ligne vient d'être créée
        # paresseusement) — risque de valorisation provisoirement incorrecte
        # sur `finance.views` (BUG-123/COGS) tant que l'ordre réel des
        # mouvements n'est pas rejoué. Non traité ici : décision
        # d'architecture de synchronisation distincte de la demande client
        # sur l'enregistrement local d'une fournée.
        reason = exc.messages[0] if getattr(exc, 'messages', None) else str(exc)
        return _record_result(record_id, False, f"dépendance manquante : {reason}")
    # BUG-146 : voir `_track_orphan_exit` / `_restamp_orphan_exits`.
    if movement.movement_type == ConsumableMovement.MovementType.EXIT:
        _track_orphan_exit(movement)
    elif movement.movement_type == ConsumableMovement.MovementType.ENTRY:
        _restamp_orphan_exits(stock.pk)
    return _record_result(record_id, True)


INVENTORY_DUPLICATE_CONFLICT = 'CONSUMABLE_INVENTORY_DUPLICATE'
INVENTORY_NOT_OWNER_CONFLICT = 'NON_PROPRIETAIRE'


def _strict_uuid(value):
    """UUID strict (chaîne ou UUID) ou None. Refuse tout le reste."""
    import uuid as _uuid
    if isinstance(value, _uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return _uuid.UUID(value.strip())
    except ValueError:
        return None


def _strict_decimal(value, max_digits=10, decimal_places=3):
    """
    Decimal strict pour un champ DecimalField(max_digits, decimal_places).
    Refuse booléens, NaN/infinis, valeurs illisibles, trop de décimales ou
    trop de chiffres. Lève ValueError (message français) sinon.
    """
    if isinstance(value, bool) or value is None or value == '':
        raise ValueError("quantité invalide")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"quantité invalide : {value!r}")
    if not dec.is_finite():
        raise ValueError(f"quantité invalide : {value!r}")
    step = Decimal(1).scaleb(-decimal_places)
    try:
        quantized = dec.quantize(step)
    except InvalidOperation:
        raise ValueError(f"quantité hors plage : {value!r}")
    if quantized != dec:
        raise ValueError(f"trop de décimales : {value!r}")
    dec = quantized
    if len(dec.as_tuple().digits) > max_digits:
        raise ValueError(f"quantité hors plage : {value!r}")
    return dec


def _strict_date(value):
    from datetime import date as _date, datetime as _datetime
    if isinstance(value, _datetime):
        return None
    if isinstance(value, _date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return _date.fromisoformat(value.strip())
    except ValueError:
        return None


def _push_consumable_inventory(node, record):
    """
    BUG-386 : « Inventaire Physique » journalier des consommables
    (`ConsumableInventory`, en-tête). Mono-nœud : seul le nœud émetteur peut
    pousser SES inventaires (node == node d'authentification). Unicité
    (node, inventory_date) : un second inventaire d'un autre id pour le même
    jour est REJETÉ et inscrit au journal des conflits (règle du module :
    pas d'écrasement silencieux). Un inventaire existant n'accepte que la
    mise à jour de `comment` (comme `ConsumableInventory` côté API).
    """
    from production.models import ConsumableInventory

    raw_id = record.get('id')
    inv_id = _strict_uuid(raw_id)
    if inv_id is None:
        return _record_result(raw_id, False, "id invalide (UUID attendu)")

    bakery_code = record.get('node') or node.code
    if bakery_code != node.code:
        return _record_result(raw_id, False, "inventaire d'une autre boulangerie refusé")
    origin = record.get('node_origin') or node.code
    if origin != node.code:
        return _record_result(raw_id, False, "node_origin différent du nœud authentifié")

    inv_date = _strict_date(record.get('inventory_date'))
    if inv_date is None:
        return _record_result(raw_id, False, "inventory_date invalide (AAAA-MM-JJ attendu)")
    if _is_future_date(inv_date):
        return _record_result(raw_id, False, "inventory_date dans le futur refusée")
    comment = record.get('comment', '')
    if comment is None:
        comment = ''
    if not isinstance(comment, str):
        return _record_result(raw_id, False, "comment invalide")

    existing = ConsumableInventory.objects.filter(pk=inv_id).first()
    if existing:
        if existing.node_id != node.pk:
            _log_conflict(
                node, 'production.ConsumableInventory', inv_id, INVENTORY_NOT_OWNER_CONFLICT,
                f"Le nœud {node.code} a tenté de modifier un inventaire de {existing.node.code}.",
            )
            return _record_result(raw_id, False, "nœud non propriétaire de cet inventaire")
        if existing.inventory_date != inv_date:
            return _record_result(raw_id, False, "inventory_date non modifiable")
        if existing.comment != comment:
            existing.comment = comment
            existing.save(update_fields=['comment'], _sync_bypass=True)
        return _record_result(raw_id, True)

    other = ConsumableInventory.objects.filter(node=node, inventory_date=inv_date).first()
    if other:
        _log_conflict(
            node, 'production.ConsumableInventory', inv_id, INVENTORY_DUPLICATE_CONFLICT,
            f"Inventaire {other.pk} déjà enregistré pour {node.code} le {inv_date} ; "
            f"celui-ci ({inv_id}) est rejeté (un seul inventaire par jour).",
        )
        return _record_result(raw_id, False, "un inventaire existe déjà pour ce nœud et ce jour")

    ConsumableInventory(
        id=inv_id, node=node, inventory_date=inv_date, comment=comment,
        node_origin=node.code,
    ).save(_sync_bypass=True)
    return _record_result(raw_id, True)


def _is_future_date(value):
    """BUG-729 : date postérieure à demain (tolérance d'un jour pour les fuseaux)."""
    from datetime import timedelta
    return value > _date.today() + timedelta(days=1)


def _push_consumable_count(node, record):
    """
    BUG-731 : enveloppe de `_push_consumable_count_inner` — le résultat
    porte la clé `inventory` (UUID de l'en-tête visé) afin que le nœud
    émetteur ne marque PAS l'inventaire « synchronisé » tant qu'une de ses
    lignes a été rejetée (`sync_now.apply_push_response`).
    """
    result = _push_consumable_count_inner(node, record)
    inv_ref = _strict_uuid(record.get('inventory'))
    if inv_ref is not None:
        result['inventory'] = str(inv_ref)
    return result


def _push_consumable_count_inner(node, record):
    """
    BUG-386 : ligne de comptage physique (`ConsumableCount`). PK entière
    locale (pas un SyncableModel) : identité cross-nœud = clé naturelle
    (node, consumable_type, count_date, inventory, quantités), jamais la PK.
    `inventory` (UUID de `ConsumableInventory`) est OPTIONNEL : un payload
    sans ce champ (comptage historique) reste accepté avec inventory=NULL.
    """
    from production.models import ConsumableCount, ConsumableInventory

    rid = record.get('id')
    bakery_code = record.get('node') or node.code
    if bakery_code != node.code:
        return _record_result(rid, False, "comptage d'une autre boulangerie refusé")

    ctype = record.get('consumable_type')
    if not isinstance(ctype, str) or not ctype.strip() or len(ctype) > 10:
        return _record_result(rid, False, "consumable_type invalide")
    count_date = _strict_date(record.get('count_date'))
    if count_date is None:
        return _record_result(rid, False, "count_date invalide (AAAA-MM-JJ attendu)")
    if _is_future_date(count_date):
        return _record_result(rid, False, "count_date dans le futur refusée")
    try:
        system_q = _strict_decimal(record.get('system_quantity'))
        physical_q = _strict_decimal(record.get('physical_quantity'))
        gap = _strict_decimal(record.get('gap'))
    except ValueError as exc:
        return _record_result(rid, False, str(exc))
    if system_q < 0 or physical_q < 0:
        return _record_result(rid, False, "quantité négative refusée")
    if gap != physical_q - system_q:
        return _record_result(rid, False, "écart incohérent (gap ≠ physique − système)")
    notes = record.get('notes', '')
    if notes is None:
        notes = ''
    if not isinstance(notes, str):
        return _record_result(rid, False, "notes invalides")

    inventory = None
    if record.get('inventory') not in (None, ''):
        inv_id = _strict_uuid(record.get('inventory'))
        if inv_id is None:
            return _record_result(rid, False, "inventory invalide (UUID attendu)")
        inventory = ConsumableInventory.objects.filter(pk=inv_id).first()
        if inventory is None:
            return _record_result(rid, False, "dépendance manquante : inventory")
        if inventory.node_id != node.pk:
            return _record_result(rid, False, "inventaire d'une autre boulangerie refusé")
        if inventory.inventory_date != count_date:
            return _record_result(rid, False, "count_date différente de la date de l'inventaire")

    if ConsumableCount.objects.filter(
        node=node, consumable_type=ctype, count_date=count_date, inventory=inventory,
        system_quantity=system_q, physical_quantity=physical_q,
    ).exists():
        return _record_result(rid, True)

    # BUG-730 : un inventaire contient UNE seule ligne par type de
    # consommable. Un second jeu de valeurs pour (inventaire, type) est un
    # conflit : rejeté et journalisé, jamais deux vérités contradictoires.
    if inventory is not None:
        other = ConsumableCount.objects.filter(
            node=node, inventory=inventory, consumable_type=ctype).first()
        if other is not None:
            _log_conflict(
                node, 'production.ConsumableCount', other.pk, 'CONSUMABLE_COUNT_DUPLICATE',
                f"Inventaire {inventory.pk} : une ligne {ctype} existe déjà "
                f"(physique {other.physical_quantity}) ; la ligne reçue "
                f"(physique {physical_q}) est rejetée.",
            )
            return _record_result(rid, False, "une ligne existe déjà pour ce consommable dans cet inventaire")

    ConsumableCount.objects.create(
        node=node, consumable_type=ctype, count_date=count_date,
        system_quantity=system_q, physical_quantity=physical_q, gap=gap,
        notes=notes, inventory=inventory,
    )
    return _record_result(rid, True)


ORPHAN_EXIT_CONFLICT = 'CONSUMABLE_EXIT_ORPHAN'


def _track_orphan_exit(movement):
    """
    BUG-146 : une sortie reçue alors que le CUMP Cloud du stock est nul
    (aucune entrée valorisée vue encore) a été figée à 0 par
    `ConsumableMovement.save()`. On l'enregistre dans le journal des
    conflits (consultable au siège, SYNC.md §5.2) comme « en attente de
    valorisation » ; `_restamp_orphan_exits` la ré-estampille à l'arrivée
    d'une entrée valorisée. Idempotent (un seul marqueur par sortie).
    """
    if movement.unit_price and Decimal(str(movement.unit_price)) > 0:
        return
    obj_id = str(movement.pk)
    if SyncConflictLog.objects.filter(
        model_label='production.ConsumableMovement', object_id=obj_id,
        conflict_type=ORPHAN_EXIT_CONFLICT,
    ).exists():
        return
    SyncConflictLog.objects.create(
        node=movement.node, model_label='production.ConsumableMovement',
        object_id=obj_id, conflict_type=ORPHAN_EXIT_CONFLICT,
        detail=("Sortie reçue avant toute entrée valorisée : valorisée provisoirement "
                "à 0 FC, sera ré-estampillée au CUMP à l'arrivée de l'entrée."),
    )


def _restamp_orphan_exits(stock_id):
    """
    BUG-146 : ré-estampille `unit_price` des sorties orphelines d'un stock
    au prix moyen pondéré des entrées reçues, une fois une entrée valorisée arrivée.
    Écrit par `update()` (pas `save()`, qui retoucherait la quantité du
    stock). Atomique (verrou sur la ligne de stock), idempotent (marqueur
    résolu, jamais retraité), Decimal uniquement. Retourne le nombre de
    sorties corrigées. Ne réutilise pas `backfill_average_unit_cost`
    (production, migration 0018) : elle rejoue tout l'historique dans
    l'ordre de `created_at`, qui côté Cloud est l'ordre d'ARRIVÉE (la
    charge utile de push ne porte pas l'horodatage d'origine) et
    redonnerait donc 0.
    """
    from django.utils import timezone as _tz
    from production.models import ConsumableMovement, ConsumableStock

    with transaction.atomic():
        stock = ConsumableStock.objects.select_for_update().get(pk=stock_id)
        # Moyenne pondérée des ENTRÉES uniquement (indépendante de l'ordre
        # d'arrivée). On n'utilise PAS `stock.average_unit_cost` : tant que le
        # stock est négatif (sortie arrivée avant l'entrée), le CUMP du modèle
        # est gonflé (voir BUG-402).
        total_qty = Decimal('0')
        total_val = Decimal('0')
        for qty, price in ConsumableMovement.objects.filter(
                stock_id=stock_id, movement_type='ENTRY').values_list('quantity', 'unit_price'):
            qty, price = Decimal(str(qty)), Decimal(str(price or '0'))
            total_qty += qty
            total_val += qty * price
        if total_qty <= 0 or total_val <= 0:
            return 0
        cump = (total_val / total_qty).quantize(Decimal('0.01'))
        exit_ids = [str(i) for i in ConsumableMovement.objects.filter(
            stock_id=stock_id, movement_type='EXIT').values_list('pk', flat=True)]
        pending = list(SyncConflictLog.objects.select_for_update().filter(
            model_label='production.ConsumableMovement',
            conflict_type=ORPHAN_EXIT_CONFLICT, resolved_at__isnull=True,
            object_id__in=exit_ids,
        ))
        for marker in pending:
            ConsumableMovement.objects.filter(pk=marker.object_id).update(unit_price=cump)
            marker.resolved_at = _tz.now()
            marker.resolution_note = f"Ré-estampillée automatiquement au CUMP {cump} FC (BUG-146)."
            marker.save(update_fields=['resolved_at', 'resolution_note'])
        return len(pending)


def _sync_bounded_qty(raw):
    """BUG-894 : entier 0..2e9 (comme production.views._strict_int), sinon None."""
    if isinstance(raw, bool):
        return None
    try:
        d = Decimal(str(raw).strip())
    except (ArithmeticError, ValueError):
        return None
    if not str(raw).strip().isascii() or not d.is_finite() or d != d.to_integral_value():
        return None
    if d < 0 or d > 2_000_000_000:
        return None
    return int(d)


_TRANSFER_LOCKED = ('CONFIRMED', 'CANCELLED')  # BUG-921 : transfert immuable une fois terminé


def _push_bread_transfer(node, record):
    from core.models import BreadPrice
    from production.models import BreadTransfer

    record_id = record.get('id')
    if not record_id:
        return _record_result(record_id, False, "id manquant")

    existing = BreadTransfer.objects.filter(pk=record_id).first()
    if existing:
        if node.pk not in (existing.from_node_id, existing.to_node_id):
            return _record_result(record_id, False, "transfert étranger à ce nœud refusé")
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
            # BUG-966 : sortie de litige (recomptage de la réceptrice, ou résolution
            # par l'émettrice / le siège, REST resolve_dispute) ; acteurs ci-dessous.
            BreadTransfer.TransferStatus.DISPUTED: {BreadTransfer.TransferStatus.CONFIRMED},
        }
        new_status = record.get('transfer_status')
        changed_fields = []
        if new_status and new_status != existing.transfer_status:
            # BUG-874 : seule la réceptrice valide la réception (CLAUDE.md 5.4).
            # BUG-966 : exception : la sortie de litige (DISPUTED -> CONFIRMED) peut
            # aussi venir de l'émettrice (résolution, comme resolve_dispute REST).
            from_resolves = (new_status == BreadTransfer.TransferStatus.CONFIRMED
                             and existing.transfer_status == BreadTransfer.TransferStatus.DISPUTED
                             and node.pk == existing.from_node_id)
            if (new_status == BreadTransfer.TransferStatus.CONFIRMED
                    and node.pk != existing.to_node_id and not from_resolves):
                return _record_result(
                    record_id, False,
                    "seule la boulangerie réceptrice peut confirmer la réception")
            # BUG-888 : machine d'états par rôle. Émettrice (from_node) :
            # PENDING->RESPONDED/CANCELLED. Réceptrice (to_node) :
            # RESPONDED->CONFIRMED/DISPUTED. Toute autre combinaison refusée.
            TS = BreadTransfer.TransferStatus
            role_allowed = {
                existing.from_node_id: {(TS.PENDING, TS.RESPONDED), (TS.PENDING, TS.CANCELLED),
                                        (TS.DISPUTED, TS.CONFIRMED)},
                existing.to_node_id: {(TS.RESPONDED, TS.CONFIRMED), (TS.RESPONDED, TS.DISPUTED),
                                      (TS.DISPUTED, TS.CONFIRMED)},
            }.get(node.pk, set())
            if ((existing.transfer_status, new_status) not in role_allowed
                    and new_status in allowed_forward.get(existing.transfer_status, set())):
                return _record_result(
                    record_id, False,
                    "transition d'état réservée à l'autre boulangerie du transfert")
            if (existing.transfer_status == TS.DISPUTED and new_status == TS.CONFIRMED
                    and (existing.pk is None or any(
                        l.quantity_received is None or l.quantity_received != l.quantity_sent
                        for l in existing.lines.all()))):
                # BUG-966 : le litige ne se lève que si les lignes ne présentent plus d'écart
                # (recomptage égal à l'envoyé, ou lignes alignées par résolution).
                return _record_result(
                    record_id, False,
                    "litige non résolu : les quantités reçues et envoyées diffèrent encore "
                    "(poussez d'abord les lignes recomptées)")
            if new_status in allowed_forward.get(existing.transfer_status, set()):
                existing.transfer_status = new_status
                changed_fields.append('transfer_status')
                # BUG-788 : la quantité reçue ne vient que de la boulangerie réceptrice.
                if record.get('quantity_received') is not None and node.pk == existing.to_node_id:
                    # BUG-894 : mêmes bornes que la voie REST (entier 0 à 2e9).
                    qty_recv = _sync_bounded_qty(record['quantity_received'])
                    if qty_recv is None:
                        return _record_result(record_id, False, "quantité reçue invalide")
                    existing.quantity_received = qty_recv
                    changed_fields.append('quantity_received')
        if changed_fields:
            existing.save(update_fields=changed_fields, _sync_bypass=True)
            if existing.transfer_status in _TRANSFER_LOCKED:
                # BUG-921 : le lot qui termine le transfert peut encore pousser ses lignes.
                _batch_terminal_parents().add(str(existing.pk))
        return _record_result(record_id, True)

    from_code = record.get('from_node')
    to_code = record.get('to_node')
    try:
        from_bakery = Node.objects.get(code=from_code)
        to_bakery = Node.objects.get(code=to_code)
    except Node.DoesNotExist:
        return _record_result(record_id, False, "boulangerie inconnue (from_node/to_node)")
    # BUG-788 : seul un nœud partie au transfert (émetteur ou récepteur) peut le créer.
    if node.pk not in (from_bakery.pk, to_bakery.pk):
        return _record_result(record_id, False, "transfert étranger à ce nœud refusé")
    # BUG-874 : l'émettrice ne crée pas un transfert déjà reçu/confirmé.
    if node.pk != to_bakery.pk and (
            record.get('quantity_received') is not None
            or record.get('transfer_status') == BreadTransfer.TransferStatus.CONFIRMED):
        return _record_result(
            record_id, False,
            "seule la boulangerie réceptrice peut confirmer la réception")

    # BUG-891 : un transfert naît toujours « en attente » ; les autres états
    # s'obtiennent par la machine d'états (BUG-888), jamais à la création.
    # BUG-958 : seul l'envoi direct de l'émettrice (transfers/send/) naît
    # « répondu » (quantity_sent renseignée, aucune quantité reçue) ; le poste
    # n'exporte que son état courant. CONFIRMED/DISPUTED/CANCELLED jamais à la création.
    TS = BreadTransfer.TransferStatus
    initial_status = record.get('transfer_status') or TS.PENDING
    direct_send = (
        initial_status == TS.RESPONDED and node.pk == from_bakery.pk
        and record.get('quantity_received') in (None, ''))
    if initial_status != TS.PENDING and not direct_send:
        return _record_result(
            record_id, False,
            "un transfert est créé au statut « en attente » (ou « répondu » par l'émettrice) uniquement")
    if record.get('quantity_received') is not None:
        if _sync_bounded_qty(record['quantity_received']) is None:
            return _record_result(record_id, False, "quantité reçue invalide")

    bread_price = None
    bp_id = record.get('bread_price')
    if bp_id:
        bread_price = BreadPrice.objects.filter(pk=bp_id).first()

    # BUG-967 : quantités normalisées en entiers ('5.0', '1e1', 5.0 -> 5), jamais brutes.
    try:
        qty_sent = (None if record.get('quantity_sent') in (None, '')
                    else _sync_int(record['quantity_sent'], 'quantity_sent'))
    except ValueError as exc:
        return _record_result(record_id, False, str(exc))
    qty_received = (None if record.get('quantity_received') is None
                    else _sync_bounded_qty(record['quantity_received']))
    transfer = BreadTransfer(
        id=record_id, from_node=from_bakery, to_node=to_bakery, bread_price=bread_price,
        quantity_sent=qty_sent,
        quantity_received=qty_received,
        transfer_status=initial_status,
        # BUG-977 : `flow` conservé ; DIRECT uniquement pour un envoi direct de l'émettrice
        # (statut RESPONDED à la création), y compris d'un poste ancien qui n'exporte pas `flow`.
        flow=(BreadTransfer.Flow.DIRECT
              if direct_send and record.get('flow') != BreadTransfer.Flow.REQUEST
              else BreadTransfer.Flow.REQUEST),
        notes=record.get('notes', ''),
        node_origin=record.get('node_origin', to_code or node.code),
    )
    transfer.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _push_bread_transfer_line(node, record):
    """Ligne de transfert. BUG-919 : identifiée par sa clé naturelle
    (transfert, catégorie de pain), unique en base ; l'id local du poste n'est
    jamais utilisé comme clé cloud."""
    from production.models import BreadTransfer, BreadTransferLine

    record_id = record.get('id')
    transfer_uuid = _strict_uuid(record.get('transfer'))
    transfer = BreadTransfer.objects.filter(pk=transfer_uuid).first() if transfer_uuid else None
    if transfer is None:
        return _record_result(record_id, False, "dépendance manquante : transfer")
    if node.pk not in (transfer.from_node_id, transfer.to_node_id):
        return _record_result(record_id, False, "transfert étranger à ce nœud refusé")
    bread_price = _bread_price_or_none(record.get('bread_price'))
    if bread_price is None:
        return _record_result(record_id, False, "dépendance manquante : bread_price")
    # BUG-921 : transfert confirmé/annulé = immuable (hors lot qui le termine).
    locked = (transfer.transfer_status in _TRANSFER_LOCKED
              and str(transfer.pk) not in _batch_terminal_parents())

    existing = BreadTransferLine.objects.filter(transfer=transfer, bread_price=bread_price).first()
    if existing is not None:
        # BUG-788 : la quantité reçue n'est modifiable que par la boulangerie réceptrice.
        sent = record.get('quantity_sent')
        in_dispute = transfer.transfer_status == 'DISPUTED'
        update_fields = []
        if (sent not in (None, '') and node.pk == transfer.from_node_id
                and _sync_int(sent, 'quantity_sent') != existing.quantity_sent):
            # BUG-974 : résolution de l'émettrice « le reçu fait foi » (REST resolve_dispute
            # ALIGN_ON_RECEIVED) : seule exception, dans un litige et uniquement pour aligner
            # l'envoyé sur la quantité reçue déclarée par la réceptrice.
            new_sent = _sync_int(sent, 'quantity_sent')
            if in_dispute and existing.quantity_received is not None and new_sent == existing.quantity_received:
                existing.quantity_sent = new_sent
                update_fields.append('quantity_sent')
            else:
                # BUG-920 : doublon de ligne avec une autre quantité : jamais « accepté » sans effet.
                return _record_result(record_id, False, "ligne en double avec une quantité envoyée différente")
        recv = record.get('quantity_received')
        if (recv is not None and node.pk == transfer.from_node_id and in_dispute
                and existing.quantity_received != recv):
            # BUG-974 : résolution de l'émettrice « l'envoyé fait foi » (ALIGN_ON_SENT) : la
            # reçue est alignée sur l'envoyé, rien d'autre.
            recv_i = _sync_int(recv, 'quantity_received')
            if recv_i == existing.quantity_sent:
                existing.quantity_received = recv_i
                update_fields.append('quantity_received')
        if update_fields:
            existing.save(update_fields=update_fields)
        if recv is not None and node.pk == transfer.to_node_id and existing.quantity_received != recv:
            recv = _sync_int(recv, 'quantity_received')
            if recv != existing.quantity_received:
                if locked and existing.quantity_received is not None:
                    return _record_result(record_id, False, "transfert terminé : quantité reçue non modifiable")
                existing.quantity_received = recv
                existing.save(update_fields=['quantity_received'])
        return _record_result(record_id, True)

    if locked:
        return _record_result(record_id, False, "transfert terminé : ajout de ligne refusé")
    # BUG-874 : la quantité reçue ne vient que de la boulangerie réceptrice.
    if record.get('quantity_received') is not None and node.pk != transfer.to_node_id:
        return _record_result(
            record_id, False,
            "seule la boulangerie réceptrice peut renseigner la quantité reçue")
    recv = record.get('quantity_received')
    try:
        with transaction.atomic():
            BreadTransferLine.objects.create(
                transfer=transfer, bread_price=bread_price,
                quantity_sent=_sync_int(record.get('quantity_sent', 0) or 0, 'quantity_sent'),
                quantity_received=None if recv is None else _sync_int(recv, 'quantity_received'),
            )
    except IntegrityError:
        return _record_result(record_id, False, "ligne en double (écriture concurrente) : à rejouer")
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

    # BUG-899 : comme l'API REST (BUG-677), une catégorie réservée à la direction
    # est refusée à un jeton de boulangerie. Une catégorie désactivée reste
    # acceptée (dépense saisie hors ligne avant la désactivation).
    if node.code != 'SIEGE' and category.scope == category.Scope.DIRECTION:
        return _record_result(record_id, False, "catégorie réservée à la direction : refusée pour une boulangerie")

    # BUG-898 : comme l'API REST (BUG-205), le montant doit être un nombre
    # ASCII fini strictement positif (-500, 0, absent, texte, NaN -> rejet).
    raw_amount = record.get('amount')
    amount = None
    if raw_amount is not None and not isinstance(raw_amount, bool) and str(raw_amount).isascii():
        try:
            amount = Decimal(str(raw_amount).strip())
        except InvalidOperation:
            amount = None
    if amount is None or not amount.is_finite() or amount <= 0 or amount >= Decimal('1E12'):
        return _record_result(record_id, False, "montant invalide : un nombre strictement positif est attendu")
    # BUG-900 : comme l'API REST, 2 décimales au plus (pas de sous-centime arrondi à 0).
    if amount != amount.quantize(Decimal('0.01')):
        return _record_result(record_id, False, "montant invalide : 2 décimales au plus")

    expense = LocalExpense(
        id=record_id, node=bakery, description=record.get('description', ''),
        amount=amount, category=category,
        date=_date.fromisoformat(record['date']),
        node_origin=record.get('node_origin', bakery_code),
    )
    expense.save(_sync_bypass=True)
    return _record_result(record_id, True)


def _bill_int(raw, name):
    """Billetage : ENTIER strict. Int (non booléen) ou chaîne de chiffres ASCII 0-9
    uniquement ; '2.0', '1e3', négatifs, flottants, non ASCII refusés (ValueError)."""
    if isinstance(raw, bool) or isinstance(raw, float):
        raise ValueError(f"« {name} » invalide : entier attendu")
    if isinstance(raw, str):
        text = raw.strip()
        if not (text.isascii() and text.isdigit()):
            raise ValueError(f"« {name} » invalide : entier attendu (chiffres 0-9 uniquement)")
        raw = text
    return _sync_int(raw, name)


def _bills_kwargs(record):
    """BUG-932 : billetage en entiers (les chaînes numériques ASCII validées par
    `_check_bills` sont converties ; absent/vide = 0)."""
    return {n: (0 if record.get(n) in (None, '') else _bill_int(record[n], n))
            for n in ('bills_20000', 'bills_10000', 'bills_5000', 'bills_1000',
                      'bills_500', 'bills_200', 'bills_100', 'bills_50')}


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

    # BUG-911 : la contrainte (node, facturier, team, date) ne protège pas quand
    # `facturier` est NULL (rapport poussé) : une seule vacation (boulangerie,
    # équipe, jour), sinon la clôture compterait les ventes en double.
    report_date = _date.fromisoformat(record['date'])
    # d27 : REST autorise deux facturiers distincts sur la même vacation ; on ne
    # rejette que le doublon du même facturier (ou indéterminé des deux côtés).
    from django.contrib.auth import get_user_model
    pushed_fact = record.get('facturier')
    fact_id = None
    if pushed_fact not in (None, '') and _strict_uuid(pushed_fact):
        fact_id = get_user_model().objects.filter(pk=pushed_fact).values_list('pk', flat=True).first()
    duplicate = FacturierReport.objects.filter(
        node=bakery, team=record.get('team', ''), date=report_date, facturier_id=fact_id).exists()
    if duplicate:
        return _record_result(
            record_id, False,
            f"un rapport existe déjà pour {bakery.code}, équipe {record.get('team')}, à la date {report_date}")

    report = FacturierReport(
        id=record_id, node=bakery, team=record.get('team', ''),
        date=report_date, facturier_id=fact_id,
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

    # BUG-789 : le bordereau débite le livre de caisse direction (SIEGE) ;
    # comme l'API REST (IsHeadquarters), seul un jeton du nœud siège peut le pousser.
    if node.code != 'SIEGE':
        return _record_result(
            record_id, False, "bordereau de versement réservé au siège : refusé pour une boulangerie")

    existing = DisbursementVoucher.objects.filter(pk=record_id).first()
    created = existing is None
    if created and (not record.get('date') or not record.get('motif')):
        return _record_result(record_id, False, "champs requis manquants (date/motif)")

    # BUG-914 : bon + écriture au livre dans UNE transaction (comme REST) : un refus
    # (solde insuffisant) ne laisse aucun bon orphelin en base.
    with transaction.atomic():
        if created:
            voucher = DisbursementVoucher(
                id=record_id, date=_date.fromisoformat(record['date']),
                motif=record.get('motif', ''), beneficiary=record.get('beneficiary', ''),
                **_bills_kwargs(record),
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
            transaction.set_rollback(True)
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
            with transaction.atomic():
                append_cashbook_entry(
                    validate_balance=_check_sufficient_balance,
                    node=siege, date=existing.date, piece_number=existing.piece_number,
                    imputation='SORTIE', label=label, exit_amount=existing.physical_cash_total,
                    source_bordereau=existing, node_origin='CLOUD',
                )
        except DRFValidationError as exc:
            if created:
                transaction.set_rollback(True)  # aucun bon sans écriture au livre
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
    if distribution.node_id != node.pk:
        return _record_result(record_id, False, "distribution d'une autre boulangerie refusée")

    existing = SocialDistributionLine.objects.filter(pk=record_id).first()
    if existing:
        if existing.distribution_id != distribution.pk:
            return _record_result(record_id, False, "distribution différente de l'enregistrement existant")
        if distribution.is_closed:  # BUG-887 (comme BUG-752/872)
            return _record_result(record_id, False, "distribution clôturée : ligne non modifiable")
        changed_fields = []
        for field, default in (
            ('indice', existing.indice), ('total_social', existing.total_social),
            ('remise', existing.remise), ('merite', existing.merite),
            ('total_payer', existing.total_payer),
        ):
            if field in record:
                value = int(record[field]) if field == 'indice' else _to_decimal(record[field], default)
                if value != getattr(existing, field):
                    setattr(existing, field, value)
                    changed_fields.append(field)
        for field in ('position', 'form'):
            if field in record and record[field] != getattr(existing, field):
                setattr(existing, field, record[field])
                changed_fields.append(field)
        if changed_fields:
            # BUG-918 : remise et total_payer sont calculés côté serveur (comme REST).
            existing.distribution = distribution
            existing.compute()
            changed_fields = list(dict.fromkeys(changed_fields + ['remise', 'total_payer']))
            existing.save(update_fields=changed_fields, _sync_bypass=True)
        return _record_result(record_id, True)

    if distribution.is_closed:  # BUG-887
        return _record_result(record_id, False, "distribution clôturée : ligne non créable")
    client = Client.objects.filter(pk=record.get('client')).first()
    if client is None:
        return _record_result(record_id, False, "dépendance manquante : client")

    line = SocialDistributionLine(
        id=record_id, distribution=distribution, client=client,
        indice=int(record.get('indice') or 0),
        total_social=_to_decimal(record.get('total_social')),
        remise=_to_decimal(record.get('remise')),
        merite=_to_decimal(record.get('merite')),
        total_payer=_to_decimal(record.get('total_payer')),
        position=record.get('position', 'present'),
        form=record.get('form', 'especes'),
        node_origin=record.get('node_origin', node.code),
    )
    line.compute()  # BUG-918 : remise / total_payer jamais pris tels que poussés
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
    'production.ConsumableInventory': _push_consumable_inventory,
    'production.ConsumableCount': _push_consumable_count,
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


# ─── Contrôles communs avant tout handler (BUG-720/721/722) ─────────────
#
# Un lot `push` vient d'un nœud authentifié par jeton, mais son contenu reste
# une entrée NON FIABLE : forme (enregistrement objet, id UUID strict),
# appartenance (le nœud n'écrit que pour lui-même), plages et longueurs des
# champs (SQLite ne les applique pas ; PostgreSQL les rejetterait : le
# comportement doit être identique), puis propriété d'un enregistrement déjà
# connu. Tout échec = REJECTED avec un motif français, jamais un 500.

# Modèles dont la clé primaire est un UUID (SyncableModel).
UUID_PK_MODELS = {
    'clients.Client', 'sales.Invoice', 'sync.DebtMovement',
    'production.ProductionSession', 'production.BreadDisposal',
    'production.ConsumableMovement', 'production.ConsumableInventory',
    'production.BreadTransfer', 'treasury.LocalExpense', 'treasury.FacturierReport',
    'treasury.CashClosure', 'treasury.DisbursementVoucher',
    'clients.SocialContribution', 'clients.SocialDistribution',
    'clients.SocialDistributionLine',
}

# Modèles portant une FK `node` : un enregistrement déjà connu appartient à ce nœud.
NODE_FK_MODELS = {
    'sales.Invoice', 'production.ProductionSession', 'production.BreadDisposal',
    'production.ConsumableMovement', 'treasury.LocalExpense', 'treasury.FacturierReport',
    'treasury.CashClosure', 'clients.SocialContribution', 'clients.SocialDistribution',
}

# Modèles dont les champs ne sont pas validés génériquement (le handler
# dispose de son propre analyseur strict, BUG-331/332/519).
_NO_FIELD_VALIDATION = {'sales.InvoiceLine'}

# Hors contrôle de portée (dette technique, voir rapport dev-backend 2026-11-22 d2) :
# des suites existantes (BUG-146 isolation des stocks, BUG-004 transferts) poussent
# ces deux modèles pour un autre nœud avec un seul jeton. Un transfert implique deux
# boulangeries ; le mouvement de consommable ne touche ni dette ni livre de caisse.
SCOPE_EXEMPT_MODELS = {'production.ConsumableMovement', 'production.BreadTransfer'}

_TEXT_MAX = 10_000
_FIELD_CACHE = {}


def _model_fields(label):
    if label not in _FIELD_CACHE:
        from django.apps import apps
        model = apps.get_model(label)
        _FIELD_CACHE[label] = [
            f for f in model._meta.concrete_fields
            if not f.primary_key and not f.is_relation and f.editable
            and f.name not in ('node_origin', 'is_synced')
            and f.get_internal_type() not in ('DateField', 'DateTimeField', 'TimeField', 'JSONField')
        ]
    return _FIELD_CACHE[label]


def _validate_fields(label, record):
    """
    BUG-721 : plage / longueur / énumération de chaque champ du modèle
    présent dans le payload. Renvoie un motif français ou None. Les valeurs
    None/'' sont laissées au handler (défauts du modèle).
    """
    from django.core.exceptions import ValidationError

    if label in _NO_FIELD_VALIDATION:
        return None
    for field in _model_fields(label):
        name = field.name
        if name not in record:
            continue
        value = record[name]
        if value is None or value == '':
            continue
        itype = field.get_internal_type()
        bad = f"champ « {name} » invalide ou hors plage"
        if itype in ('CharField', 'TextField', 'SlugField', 'EmailField'):
            if not isinstance(value, str):
                return bad
            if itype == 'TextField' and len(value) > _TEXT_MAX:
                return bad
        elif itype == 'DecimalField':
            if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
                return bad
            if isinstance(value, str) and not value.isascii():  # BUG-902/907 : chiffres 0-9 uniquement
                return bad
            try:
                dec = Decimal(str(value).strip())
                if dec.is_finite():
                    # Décimales excédentaires : arrondi à la précision du champ
                    # (comme l'écriture du nœud) ; hors plage -> InvalidOperation.
                    dec = dec.quantize(Decimal(1).scaleb(-field.decimal_places))
                value = dec
            except (InvalidOperation, ValueError):
                return bad
        elif itype in ('IntegerField', 'PositiveIntegerField', 'BigIntegerField',
                       'SmallIntegerField', 'PositiveSmallIntegerField'):
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                return bad
            if isinstance(value, str) and not value.isascii():  # BUG-903 : chiffres 0-9 uniquement
                return bad
            if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))
                                             or value != int(value)):
                return bad
            # BUG-956 : '150000.0' (décimal entier en chaîne) = 150000 ; '1e3' reste refusé.
            if isinstance(value, str) and re.fullmatch(r'\s*[+-]?\d+\.0+\s*', value):
                value = value.strip().split('.')[0]
        elif itype == 'BooleanField':
            if not isinstance(value, (bool, int, str)):
                return bad
        try:
            field.clean(value, None)
        except (ValidationError, ValueError, TypeError, OverflowError):
            return bad
    return None


# ─── Contrôles stricts alignés sur la voie REST (BUG-901 à 909) ─────────
#
# `_validate_fields` appelle `field.clean(value, None)` : aucune plage métier,
# aucun contrôle ASCII (Decimal/int Python acceptent « ٣ »), aucune date
# future. Les helpers ci-dessous complètent ce contrôle générique, par modèle,
# avec les mêmes bornes que l'API REST. Un rejet = motif français, les autres
# enregistrements du lot passent.

MAX_FLOUR_SACKS_SYNC = Decimal('100000')   # ProductionSessionSerializer.MAX_FLOUR_SACKS
MAX_SYNC_INT = 2_000_000_000               # production.views._strict_int
MAX_SYNC_DISPOSAL_QTY = 1_000_000          # production.serializers.MAX_DISPOSAL_QTY
MAX_SYNC_DISPOSAL_VALUE = 9_999_999_999    # production.serializers.MAX_DISPOSAL_VALUE
MAX_SYNC_COMMISSION_RATE = Decimal('0.30')  # ClientBoundsMixin.MAX_COMMISSION_RATE


def _sync_decimal(raw, name, places, minimum=None, maximum=None, max_digits=None):
    """
    Décimal strict (ASCII, fini, `places` décimales au plus SANS arrondi
    silencieux, bornes incluses). Renvoie un Decimal ou lève ValueError
    (message français). Valeurs None/'' : à traiter par l'appelant.
    """
    bad = f"« {name} » invalide ou hors plage"
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        raise ValueError(bad)
    text = str(raw).strip()
    if not text.isascii():
        raise ValueError(f"« {name} » : chiffres 0-9 uniquement")
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError(bad)
    if not dec.is_finite():
        raise ValueError(bad)
    try:
        quantized = dec.quantize(Decimal(1).scaleb(-places))
    except InvalidOperation:
        raise ValueError(bad)
    if quantized != dec:
        raise ValueError(f"« {name} » : {places} décimale(s) au maximum")
    if minimum is not None and quantized < minimum:
        raise ValueError(f"« {name} » ne peut pas être inférieur à {minimum}")
    if maximum is not None and quantized > maximum:
        raise ValueError(f"« {name} » ne peut pas dépasser {maximum}")
    if max_digits is not None and len(quantized.as_tuple().digits) > max_digits:
        raise ValueError(bad)
    return quantized


def _sync_int(raw, name, minimum=0, maximum=MAX_SYNC_INT):
    """Entier strict ASCII borné (comme la voie REST), ValueError français sinon."""
    try:
        dec = _sync_decimal(raw, name, 0, minimum=Decimal(minimum), maximum=Decimal(maximum))
    except ValueError as exc:
        raise ValueError(str(exc))
    return int(dec)


def _sync_not_future_date(node, value, name):
    """Date (objet date) non postérieure à la date de travail du serveur."""
    from core.workday import work_date_for
    if value > work_date_for(node):
        raise ValueError(f"« {name} » ne peut pas être dans le futur")


def _check_production_session(node, record):
    if 'date' in record and record['date'] not in (None, ''):
        day = _strict_date(record['date'])
        if day is None:
            return "« date » invalide (AAAA-MM-JJ attendu)"
        try:
            _sync_not_future_date(node, day, 'date')
        except ValueError as exc:
            return str(exc)
    raw = record.get('flour_sacks_used')
    if raw not in (None, ''):
        try:
            _sync_decimal(raw, 'flour_sacks_used', 2, Decimal('0'), MAX_FLOUR_SACKS_SYNC)
        except ValueError as exc:
            return str(exc)
    # BUG-924 : valeur du sac bornée (les totaux, eux, sont recalculés depuis les lignes).
    if record.get('sac_value_fc_used') not in (None, ''):
        try:
            _sync_int(record['sac_value_fc_used'], 'sac_value_fc_used', 0, 100_000_000)
        except ValueError as exc:
            return str(exc)
    # BUG-923 : l'horodatage de clôture ne peut pas être dans le futur.
    if record.get('closed_at') not in (None, ''):
        from django.utils import timezone
        try:
            moment = _parse_aware_datetime(record['closed_at'])
            _sync_not_future_date(node, timezone.localtime(moment).date(), 'closed_at')
        except (ValueError, TypeError, OverflowError) as exc:
            return str(exc) or "« closed_at » invalide"
    return None


def _check_production_session_line(node, record):
    if 'quantity' in record:
        if record['quantity'] is None:
            return "« quantity » manquante"
        try:
            _sync_int(record['quantity'], 'quantity')
        except ValueError as exc:
            return str(exc)
    return None


def _check_bread_transfer(node, record):
    # BUG-922 : pas de transfert d'une boulangerie vers elle-même (REST).
    if record.get('from_node') not in (None, '') and record.get('from_node') == record.get('to_node'):
        return "une boulangerie ne peut pas s'envoyer un transfert à elle-même"
    return _check_transfer_quantities(record)


def _check_transfer_quantities(record):
    # BUG-928 : mêmes bornes que BUG-894 (entier 0 à 2e9).
    for name in ('quantity_sent', 'quantity_received'):
        if record.get(name) not in (None, ''):
            try:
                _sync_int(record[name], name)
            except ValueError as exc:
                return str(exc)
    return None


def _check_bread_transfer_line(node, record):
    return _check_transfer_quantities(record)


def _check_bread_disposal(node, record):
    from production.models import BreadDisposal
    dtype = record.get('disposal_type')
    if dtype is None and record.get('id') and BreadDisposal.objects.filter(pk=record['id']).exists():
        return None  # rejeu minimal d'une disposition connue : le handler reste idempotent
    if dtype not in BreadDisposal.DisposalType.values:
        return "« disposal_type » manquant ou invalide"
    if 'quantity' in record and record['quantity'] not in (None, ''):
        low = -MAX_SYNC_INT if dtype == 'REMAINING' else 0
        try:
            _sync_int(record['quantity'], 'quantity', minimum=low)
        except ValueError as exc:
            return str(exc)
    if record.get('unit_price_sold') not in (None, ''):
        try:
            _sync_int(record['unit_price_sold'], 'unit_price_sold')
        except ValueError as exc:
            return str(exc)
    # BUG-925 : mêmes bornes que la voie REST (quantité <= 1 000 000, valeur
    # totale <= 9 999 999 999 : colonne Decimal(12, 2)).
    qty = _sync_int(record.get('quantity') or 0, 'quantity', minimum=-MAX_SYNC_INT)
    price = _sync_int(record.get('unit_price_sold') or 0, 'unit_price_sold')
    if abs(qty) > MAX_SYNC_DISPOSAL_QTY:
        return f"« quantity » ne peut pas dépasser {MAX_SYNC_DISPOSAL_QTY}"
    if abs(qty) * price > MAX_SYNC_DISPOSAL_VALUE:
        return "la valeur totale (quantité × prix unitaire) dépasse la limite autorisée"
    return None


def _check_consumable_movement(node, record):
    # BUG-926 : code de consommable bien formé (texte court, sans blanc, comme
    # ConsumableCount) ; l'appartenance à ConsumableType reste du ressort de BUG-729
    # (des suites existantes poussent des codes métier non seedés : SEL, FARINE...).
    ctype = record.get('consumable_type')
    if ctype not in (None, ''):
        import re
        if not isinstance(ctype, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,10}', ctype):
            return "« consumable_type » invalide (code de 1 à 10 caractères sans espace attendu)"
    unit = record.get('unit')
    if unit not in (None, '') and (not isinstance(unit, str) or len(unit) > 20):
        return "« unit » invalide"
    if record.get('quantity') not in (None, ''):
        try:
            _sync_decimal(record['quantity'], 'quantity', 3, Decimal('0'), max_digits=10)
        except ValueError as exc:
            return str(exc)
    if record.get('unit_price') not in (None, ''):
        try:
            _sync_decimal(record['unit_price'], 'unit_price', 4, Decimal('0'), max_digits=16)
        except ValueError as exc:
            return str(exc)
    return None


def _check_invoice(node, record):
    from django.utils import timezone

    if record.get('commission_rate') not in (None, ''):
        try:
            _sync_decimal(record['commission_rate'], 'commission_rate', 2,
                          Decimal('0'), MAX_SYNC_COMMISSION_RATE)
        except ValueError as exc:
            return str(exc)
    for name in ('delivered_at', 'not_served_at'):
        if record.get(name) in (None, ''):
            continue
        try:
            moment = _parse_aware_datetime(record[name])
            _sync_not_future_date(node, timezone.localtime(moment).date(), name)
        except ValueError as exc:
            return str(exc)
    # BUG-927 : équipes A et B uniquement (CLAUDE.md 5.2).
    if record.get('team') not in (None, '', 'A', 'B'):
        return "« team » invalide : équipe A ou B uniquement"
    receipt = record.get('receipt_number')
    if receipt not in (None, ''):
        if not isinstance(receipt, str) or not receipt.isascii():
            return "« receipt_number » : caractères ASCII uniquement"
    return None


def _check_day(node, record, key='date'):
    """Date AAAA-MM-JJ valide et non future (si présente). Renvoie un motif ou None."""
    if record.get(key) in (None, ''):
        return None
    day = _strict_date(record[key])
    if day is None:
        return "« date » invalide (AAAA-MM-JJ attendu)"
    try:
        _sync_not_future_date(node, day, 'date')
    except ValueError as exc:
        return str(exc)
    return None


def _check_amounts(record, specs):
    """specs : (champ, décimales, minimum, max_digits). Renvoie un motif ou None."""
    for name, places, low, digits in specs:
        if record.get(name) in (None, ''):
            continue
        try:
            _sync_decimal(record[name], name, places, low, max_digits=digits)
        except ValueError as exc:
            return str(exc)
    return None


_BILL_FIELDS = ('bills_20000', 'bills_10000', 'bills_5000', 'bills_1000',
                'bills_500', 'bills_200', 'bills_100', 'bills_50')


def _check_bills(record):
    for name in _BILL_FIELDS:
        if record.get(name) in (None, ''):
            continue
        try:
            _bill_int(record[name], name)
        except ValueError as exc:
            return str(exc)
    return None


def _check_facturier_report(node, record):
    # BUG-910 : montants >= 0, ASCII, 2 décimales (sacks_value_gap peut être négatif).
    zero = Decimal('0')
    reason = _check_amounts(record, (
        ('total_cash_sales', 2, zero, 14), ('total_credit_sales', 2, zero, 14),
        ('theoretical_cash', 2, zero, 14), ('sacks_consumed', 2, zero, 8),
        ('sacks_value_gap', 2, None, 14),
    ))
    if reason:
        return reason
    # BUG-911 : équipes A et B uniquement (CLAUDE.md 5.2, REST BUG-812).
    from treasury.models import FacturierReport
    known = record.get('id') not in (None, '') and FacturierReport.objects.filter(pk=record['id']).exists()
    if 'team' in record or not known:
        if record.get('team') not in ('A', 'B'):
            return "« team » invalide : équipe A ou B uniquement"
    reason = _check_day(node, record)  # BUG-912
    if reason or known:
        return reason
    # BUG-929/930 : facturier = utilisateur ACTIF de rôle FACTURIER, du MÊME nœud que le
    # rapport (l'équipe du facturier n'est pas contrôlée : test c10 « même facturier, autre équipe »).
    bakery_code = record.get('node') or node.code
    pushed = record.get('facturier')
    if pushed not in (None, ''):
        uid = _strict_uuid(pushed) if isinstance(pushed, str) else None
        from django.contrib.auth import get_user_model
        fact = get_user_model().objects.filter(pk=uid).first() if uid else None
        if fact is None:
            return "« facturier » inconnu : utilisateur introuvable"
        # BUG-935 : rôles de la règle REST (IsGerant crée ; IsFacturier = FACTURIER et au-dessus).
        # BUG-936 : un facturier désactivé depuis la saisie hors ligne reste accepté.
        if fact.role not in ('FACTURIER', 'GERANT', 'COMPTABLE', 'DIRECTION', 'ADMIN'):
            return "« facturier » doit être un utilisateur de rôle facturier, gérant ou supérieur"
        # BUG-963 : les rôles sans rattachement (COMPTABLE/DIRECTION/ADMIN) créent des
        # rapports pour toute boulangerie en REST : pas de contrôle de nœud pour eux.
        if not fact.can_access_all_nodes and (fact.node is None or fact.node.code != bakery_code):
            return "« facturier » n'appartient pas à la boulangerie du rapport"
    # BUG-931 : jour d'une clôture confirmée figé (comme REST).
    from treasury.models import CashClosure
    day = _strict_date(record['date']) if record.get('date') not in (None, '') else None
    if day is not None and CashClosure.objects.filter(
            node__code=bakery_code, date=day, is_validated=True).exists():
        return f"la clôture de {bakery_code} du {day} est déjà confirmée : rapport refusé"
    return None


def _check_local_expense(node, record):
    # BUG-962 : date valide et non future (REST BUG-086/812) avec motif précis.
    reason = _check_day(node, record)
    if reason:
        return reason
    # BUG-961 : jour d'une clôture confirmée figé (REST _refuse_if_closure_confirmed).
    from treasury.models import CashClosure, LocalExpense
    if record.get('id') not in (None, '') and _strict_uuid(record['id']) \
            and LocalExpense.objects.filter(pk=record['id']).exists():
        return None  # rejeu : le handler reste idempotent
    day = _strict_date(record['date']) if record.get('date') not in (None, '') else None
    bakery_code = record.get('node') or node.code
    if day is not None and CashClosure.objects.filter(
            node__code=bakery_code, date=day, is_validated=True).exists():
        return f"la clôture de {bakery_code} du {day} est déjà confirmée : dépense refusée"
    return None


def _check_client(node, record):
    # BUG-916 : mêmes bornes que ClientBoundsMixin (REST).
    from clients.models import Client
    known = record.get('id') not in (None, '') and Client.objects.filter(pk=record['id']).exists()
    if known:
        return None  # client connu : le handler tranche (no-op / non propriétaire)
    for name in ('first_name', 'last_name'):
        val = record.get(name)
        if not isinstance(val, str) or not val.strip():
            return f"« {name} » obligatoire"
    reason = _check_amounts(record, (('cotisation_sociale', 2, Decimal('0'), 10),))
    if reason:
        return reason
    for name, places, low, high in (
        ('commission_rate', 2, Decimal('0'), MAX_SYNC_COMMISSION_RATE),
        ('credit_limit', 2, Decimal('0'), Decimal('10000000')),
    ):
        if record.get(name) in (None, ''):
            continue
        try:
            _sync_decimal(record[name], name, places, low, high)
        except ValueError as exc:
            return str(exc)
    return None


def _check_social_contribution(node, record):
    # BUG-917 : montant >= 0, mois 1-12, client de la boulangerie du jeton.
    from clients.models import Client
    if record.get('amount') not in (None, ''):
        try:
            _sync_decimal(record['amount'], 'amount', 2, Decimal('0'), max_digits=10)
        except ValueError as exc:
            return str(exc)
    if record.get('month') not in (None, ''):
        try:
            _sync_int(record['month'], 'month', 1, 12)
        except ValueError as exc:
            return str(exc)
    if record.get('year') not in (None, ''):
        try:
            _sync_int(record['year'], 'year', 2000, 2200)
        except ValueError as exc:
            return str(exc)
    if record.get('client') not in (None, ''):
        owner = Client.objects.filter(pk=record['client']).values_list('node_id', flat=True).first()             if _strict_uuid(record['client']) else None
        if owner is not None and owner != node.pk:
            return "ce client n'appartient pas à la boulangerie indiquée"
    return None


def _check_social_distribution(node, record):
    if record.get('tarif') not in (None, ''):
        try:
            _sync_decimal(record['tarif'], 'tarif', 2, Decimal('0'), max_digits=10)
        except ValueError as exc:
            return str(exc)
    if record.get('year') not in (None, ''):
        try:
            _sync_int(record['year'], 'year', 2000, 2200)
        except ValueError as exc:
            return str(exc)
    return None


def _check_social_distribution_line(node, record):
    # BUG-918 : indice 0-12, mérite / total >= 0, client du même nœud (comme REST).
    from clients.models import Client
    if record.get('indice') not in (None, ''):
        try:
            _sync_int(record['indice'], 'indice', 0, 12)
        except ValueError as exc:
            return str(exc)
    reason = _check_amounts(record, (('merite', 2, Decimal('0'), 8), ('total_social', 2, Decimal('0'), 8)))
    if reason:
        return reason
    if record.get('client') not in (None, ''):
        owner = Client.objects.filter(pk=record['client']).values_list('node_id', flat=True).first()             if _strict_uuid(record['client']) else None
        if owner is not None and owner != node.pk:
            return "ce client n'appartient pas à la boulangerie de la distribution"
    return None


def _check_cash_closure(node, record):
    zero = Decimal('0')
    reason = _check_amounts(record, (('total_entries', 2, zero, 14), ('total_expenses', 2, zero, 14)))
    return reason or _check_bills(record) or _check_day(node, record)  # BUG-913 / 912


def _check_disbursement_voucher(node, record):
    reason = _check_bills(record) or _check_day(node, record)  # BUG-914 / 912
    if reason:
        return reason
    from treasury.models import DisbursementVoucher
    if record.get('id') not in (None, '') and DisbursementVoucher.objects.filter(pk=record['id']).exists():
        return None  # rejeu : le handler reste idempotent
    total = sum(int(_sync_int(record.get(n) or 0, n)) * int(n.split('_')[1]) for n in _BILL_FIELDS)
    if total <= 0:
        return "le bordereau doit comporter au moins un billet (montant supérieur à 0 FC)"
    return None


_STRICT_CHECKS = {
    'clients.Client': _check_client,
    'clients.SocialContribution': _check_social_contribution,
    'clients.SocialDistribution': _check_social_distribution,
    'clients.SocialDistributionLine': _check_social_distribution_line,
    'treasury.FacturierReport': _check_facturier_report,
    'treasury.LocalExpense': _check_local_expense,
    'treasury.CashClosure': _check_cash_closure,
    'treasury.DisbursementVoucher': _check_disbursement_voucher,
    'production.ProductionSession': _check_production_session,
    'production.ProductionSessionLine': _check_production_session_line,
    'production.BreadDisposal': _check_bread_disposal,
    'production.BreadTransfer': _check_bread_transfer,
    'production.BreadTransferLine': _check_bread_transfer_line,
    'production.ConsumableMovement': _check_consumable_movement,
    'sales.Invoice': _check_invoice,
}


def _check_node_scope(node, label, record):
    """BUG-722 : le nœud authentifié n'écrit qu'en son propre nom."""
    if label in SCOPE_EXEMPT_MODELS:
        return None
    code = record.get('node')
    if code not in (None, '') and (not isinstance(code, str) or code != node.code):
        return "enregistrement d'une autre boulangerie refusé"
    origin = record.get('node_origin')
    if origin not in (None, ''):
        allowed = {node.code}
        if label == 'treasury.DisbursementVoucher':
            # Bordereau créé au siège : `node_origin='CLOUD'` documenté (SYNC.md §1.2).
            allowed.add('CLOUD')
        if not isinstance(origin, str) or origin not in allowed:
            return "node_origin différent du nœud authentifié"
    return None


def _preflight(node, label, record):
    """Renvoie (record_normalisé, None) ou (None, résultat REJECTED)."""
    if not isinstance(record, dict):
        return None, _record_result(None, False, "enregistrement invalide (objet attendu)")
    record = dict(record)
    rid = record.get('id')
    if label in UUID_PK_MODELS and rid not in (None, ''):
        uid = _strict_uuid(rid)
        if uid is None:
            return None, _record_result(rid, False, "id invalide (UUID attendu)")
        record['id'] = str(uid)
    elif rid is not None and (isinstance(rid, bool) or not isinstance(rid, (str, int))):
        return None, _record_result(rid, False, "id invalide")

    reason = _check_node_scope(node, label, record)
    if reason and label == 'clients.Client' and record.get('id') not in (None, ''):
        # Client déjà connu : le handler tranche (propriétaire -> no-op ;
        # non propriétaire -> conflit NON_PROPRIETAIRE journalisé, BUG-723).
        from clients.models import Client
        if Client.objects.filter(pk=record['id']).exists():
            reason = None
    if reason:
        logger.warning("Sync %s : %s rejeté (%s) id=%s", node.code, label, reason, str(rid)[:64])
        return None, _record_result(rid, False, reason)

    reason = _validate_fields(label, record)
    if not reason and label in _STRICT_CHECKS:
        reason = _STRICT_CHECKS[label](node, record)
    if reason:
        return None, _record_result(rid, False, reason)

    # Propriété d'un enregistrement déjà connu (modèles portant `node`).
    if label in NODE_FK_MODELS and record.get('id') not in (None, ''):
        from django.apps import apps
        owner = apps.get_model(label).objects.filter(pk=record['id']).values_list('node_id', flat=True).first()
        if owner is not None and owner != node.pk:
            _log_conflict(
                node, label, record['id'], 'NON_PROPRIETAIRE',
                f"Le nœud {node.code} a tenté de modifier un enregistrement d'une autre boulangerie.",
            )
            return None, _record_result(rid, False, "nœud non propriétaire de cet enregistrement")
    return record, None


def _tag_inventory(model_label, raw_record, result):
    """
    BUG-731 (réouverture) : le résultat d'une ligne de comptage porte TOUJOURS
    la clé `inventory`, y compris quand le rejet vient du contrôle commun
    (`_preflight`) ou d'une exception avant le handler ; sinon le nœud
    émetteur marquerait l'inventaire « synchronisé » et perdrait la ligne.
    """
    if model_label == 'production.ConsumableCount' and isinstance(raw_record, dict):
        inv_ref = _strict_uuid(raw_record.get('inventory'))
        if inv_ref is not None:
            result['inventory'] = str(inv_ref)
    return result


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
    _batch_ctx.parents = set()
    for model_label in PUSH_MODEL_ORDER:
        seen_ids = set()
        records = records_by_model.get(model_label) or []
        handler = PUSH_HANDLERS[model_label]
        model_results = []
        if not isinstance(records, list):
            # BUG-720 : valeur non liste = un rejet explicite, jamais un 500.
            results[model_label] = [_record_result(None, False, "liste d'enregistrements attendue")]
            continue
        for record in records:
            raw_record = record
            if model_label == 'clients.Client' and isinstance(record, dict) and record.get('id'):
                # BUG-972 : dans un même lot, un id déjà traité plus haut = rejeu (le premier
                # enregistrement gagne). Un AUTRE lot peut modifier l'identité (BUG-941).
                rid_key = str(record['id'])
                if rid_key in seen_ids:
                    model_results.append(_record_result(record['id'], True))
                    continue
                seen_ids.add(rid_key)
            try:
                with _tx.atomic():
                    record, rejected = _preflight(node, model_label, record)
                    if rejected is not None:
                        model_results.append(_tag_inventory(model_label, raw_record, rejected))
                        continue
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
                # BUG-724 : motif générique (jamais de détail SQL/contrainte
                # renvoyé à l'appelant) ; le détail va au journal serveur.
                logger.warning(
                    "Sync %s : %s non traité (%s : %s)", node.code, model_label, type(exc).__name__, exc,
                )
                rid = raw_record.get('id') if isinstance(raw_record, dict) else None
                model_results.append(_tag_inventory(model_label, raw_record, _record_result(
                    rid, False, "erreur serveur : enregistrement non traité (données invalides)")))
        if model_results:
            results[model_label] = model_results

    # Modèles envoyés mais non supportés en V1 : rejetés explicitement,
    # jamais ignorés en silence (SYNC.md §3.4).
    for model_label, records in records_by_model.items():
        if model_label not in PUSH_HANDLERS and records:
            if not isinstance(records, list):
                records = [None]
            results[model_label] = [
                _record_result(r.get('id') if isinstance(r, dict) else None, False, "modèle non supporté en V1")
                for r in records
            ]
    return results
