"""
BUG-318 : « Non servi » (manuel ou à l'expiration) et livraison partielle.

Rappel du flux existant (inchangé) : à la CRÉATION d'une facture, le stock de
pains est déjà décrémenté et la dette client (`current_debt`) déjà mise à jour
de `Invoice.debt_delta`. Le « non servi » et la livraison partielle doivent
donc RESTITUER la part non servie (stock + dette) : l'effet net est qu'aucun
pain non servi ne quitte le stock et que la BP est rétablie.

Traitement du versement : il N'EST PAS perdu. Une facture non servie se
comporte comme une facture à commande 0 : le versement reste un encaissement
qui réduit la BP du client (BP négative = crédit en faveur du client). Pour
une vente sans client (CLIENT DIVERS), aucune BP ne peut porter ce crédit : le
versement est ramené à la valeur servie (le surplus est rendu au client).
"""
from datetime import timedelta
from decimal import Decimal

from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from clients.models import Client
from core.utils import create_notification, log_activity
from production.models import _adjust_bread_stock
from sync.models import DebtMovement

from .models import Invoice, InvoiceLine

# Échéance d'une facture en attente de livraison (affichée « Expire dans… »).
PENDING_EXPIRY_HOURS = 12
EXPIRED_REASON = "Expirée automatiquement"


class InvoiceStateError(Exception):
    """Transition impossible ; `status_code` = code HTTP à renvoyer."""

    def __init__(self, detail, status_code=409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _record_debt_movement(client, amount, invoice, note):
    def _write():
        from sync.services import record_debt_movement
        record_debt_movement(
            client, amount, DebtMovement.Kind.ADJUSTMENT,
            node_origin=invoice.node.code, invoice=invoice, note=note,
        )
    transaction.on_commit(_write)


def expiry_cutoff(now=None):
    return (now or timezone.now()) - timedelta(hours=PENDING_EXPIRY_HOURS)


def is_expirable(invoice, now=None):
    return (
        invoice.status == Invoice.Status.PENDING
        and invoice.special_code != Invoice.SpecialCode.NS
        and not invoice.is_adjustment
        and not invoice.is_debt_repayment
        and invoice.created_at < expiry_cutoff(now)
    )


def _apply_new_served_quantities(invoice, new_quantities):
    """
    Réduit les lignes (`{line_pk: nouvelle_quantité}`) et propage sur stock,
    `order_total`, `payment_amount` (sans client), BP client et `debt_after`.
    Appelée DANS une transaction, `invoice` déjà verrouillée.
    """
    old_delta = invoice.debt_delta
    if invoice.initial_order_total is None:
        invoice.initial_order_total = invoice.order_total

    lines = {l.pk: l for l in invoice.lines.select_related('bread_price')}
    for pk, new_qty in new_quantities.items():
        line = lines[pk]
        if new_qty == line.quantity:
            continue
        if line.ordered_quantity is None:
            line.ordered_quantity = line.quantity
        removed = line.quantity - new_qty
        # `unit_price` figé à la création : jamais recalculé depuis le catalogue.
        InvoiceLine.objects.filter(pk=line.pk).update(
            quantity=new_qty,
            line_total=Decimal(new_qty) * line.unit_price,
            ordered_quantity=line.ordered_quantity,
        )
        _adjust_bread_stock(invoice.node, line.bread_price, sent=-removed)

    invoice.compute_order_total()
    if invoice.client_id is None and invoice.payment_amount > invoice.order_total:
        invoice.payment_amount = invoice.order_total
    new_delta = invoice.debt_delta
    invoice.debt_after = invoice.debt_before + new_delta

    diff = new_delta - old_delta
    if invoice.client_id and diff != 0:
        Client.objects.filter(pk=invoice.client_id).update(current_debt=F('current_debt') + diff)
        _record_debt_movement(
            invoice.client, diff, invoice,
            f"Réduction servi {invoice.receipt_number}",
        )
    return invoice


def _refresh_client_category(invoice):
    if invoice.client_id:
        client = Client.objects.get(pk=invoice.client_id)
        client.refresh_category()
        client.save(update_fields=['category'])


def _lock(invoice_pk):
    return Invoice.objects.select_for_update().select_related('client', 'node').get(pk=invoice_pk)


def mark_not_served(invoice_pk, actor, reason='', auto=False):
    """
    Déclare la facture « Non servi » (statut terminal, ligne conservée).
    Idempotent pour l'expiration automatique (retourne None si déjà traitée /
    plus expirable) ; pour l'action manuelle lève `InvoiceStateError` (409).
    """
    with transaction.atomic():
        invoice = _lock(invoice_pk)
        if auto:
            if not is_expirable(invoice):
                return None
        else:
            if invoice.status != Invoice.Status.PENDING:
                raise InvoiceStateError(
                    f"Facture déjà au statut « {invoice.get_status_display()} » : "
                    "seule une facture en attente de livraison peut être déclarée non servie."
                )
            if invoice.special_code == Invoice.SpecialCode.NS or invoice.is_adjustment:
                raise InvoiceStateError(
                    "Cette facture ne peut pas être déclarée « Non servi » (déjà NS ou ajustement).",
                    status_code=400,
                )
        reason = EXPIRED_REASON if auto else (reason or '').strip()[:200]
        zero = {l.pk: 0 for l in invoice.lines.all()}
        _apply_new_served_quantities(invoice, zero)
        invoice.order_total = Decimal('0.00')
        invoice.status = Invoice.Status.NOT_SERVED
        invoice.not_served_reason = reason
        invoice.not_served_at = timezone.now()
        invoice.save(update_fields=[
            'order_total', 'payment_amount', 'debt_after', 'initial_order_total',
            'status', 'not_served_reason', 'not_served_at', 'updated_at',
        ])
        _refresh_client_category(invoice)
        client_label = invoice.client.full_name if invoice.client_id else 'CLIENT DIVERS'
        log_activity(
            actor, "Facture Non Servi",
            f"Facture {invoice.receipt_number} ({client_label}) déclarée non servie"
            f"{' automatiquement' if auto else ''} — commandé initial {invoice.initial_order_total} FC, "
            f"versement conservé {invoice.payment_amount} FC, BP {invoice.debt_after} FC."
            + (f" Motif : {reason}." if reason else ''),
            node_origin=invoice.node.code,
        )
        create_notification(
            title=f"Facture non servie — {invoice.receipt_number}",
            message=(
                f"{client_label} : facture de {invoice.initial_order_total} FC "
                f"{'expirée (non servie automatiquement)' if auto else 'déclarée non servie'}."
                + (f" Motif : {reason}." if reason else '')
                + f" Versement conservé : {invoice.payment_amount} FC."
            ),
            severity='INFO' if not auto else 'WARNING',
            node_origin=invoice.node.code,
        )
        return invoice


def expire_pending_invoices(node=None, now=None):
    """
    Passe en « Non servi » toute facture PENDING dont l'échéance est dépassée.
    Idempotent (une facture déjà traitée n'est jamais retraitée). Retourne le
    nombre de factures traitées. `node` : restreint à une boulangerie.
    """
    qs = Invoice.objects.filter(
        status=Invoice.Status.PENDING,
        created_at__lt=expiry_cutoff(now),
        is_adjustment=False, is_debt_repayment=False,
    ).exclude(special_code=Invoice.SpecialCode.NS)
    if node is not None:
        qs = qs.filter(node=node)
    count = 0
    for pk in list(qs.values_list('pk', flat=True)):
        if mark_not_served(pk, None, auto=True) is not None:
            count += 1
    return count


def deliver_invoice(invoice_pk, actor, served_quantities=None, delivered_at=None):
    """
    Livraison (éventuellement partielle) sous verrou. `served_quantities` =
    `{line_pk: servi}` déjà validé (0 <= servi <= commandé). Retourne
    `(invoice, reduced)`.
    """
    with transaction.atomic():
        invoice = _lock(invoice_pk)
        if invoice.status == Invoice.Status.NOT_SERVED:
            raise InvoiceStateError(
                f"Facture déjà non servie{' (' + invoice.not_served_reason + ')' if invoice.not_served_reason else ''} : "
                "elle ne peut plus être livrée.",
            )
        if invoice.status != Invoice.Status.PENDING:
            raise InvoiceStateError(
                f"Facture déjà au statut « {invoice.get_status_display()} ».", status_code=400,
            )
        if is_expirable(invoice):
            raise InvoiceStateError(
                "Cette facture a expiré : elle est à traiter comme « Non servi » "
                "(échéance dépassée)."
            )
        reduced = False
        if served_quantities:
            current = {l.pk: l.quantity for l in invoice.lines.all()}
            changes = {pk: q for pk, q in served_quantities.items() if q != current.get(pk)}
            if changes:
                final_total = sum(
                    served_quantities.get(pk, qty) for pk, qty in current.items()
                )
                if final_total == 0:
                    raise InvoiceStateError(
                        "Aucun pain servi : utilisez « Non servi » pour cette facture.", status_code=400,
                    )
                _apply_new_served_quantities(invoice, changes)
                reduced = True
        invoice.deliver(actor, delivered_at=delivered_at)
        if reduced:
            invoice.save(update_fields=[
                'order_total', 'payment_amount', 'debt_after', 'initial_order_total', 'updated_at',
            ])
            _refresh_client_category(invoice)
            log_activity(
                actor, "Livraison Partielle",
                f"Facture {invoice.receipt_number} servie en partie : {invoice.order_total} FC "
                f"sur {invoice.initial_order_total} FC commandés — BP {invoice.debt_after} FC.",
                node_origin=invoice.node.code,
            )
        return invoice, reduced
