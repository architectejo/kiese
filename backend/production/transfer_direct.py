"""
Envoi direct de pains entre boulangeries (remarque.md, section « Transferts
Inter-Boulangeries » : « donner à un gérant la possibilité d'envoyer les pains
à une autre boulangerie sans avoir reçu la demande de cette autre
boulangerie »).

Second flux, à côté du flux « demande -> réponse -> confirmation » :
  - le gérant de B envoie (`POST /api/production/transfers/send/`) ; le
    transfert naît directement au statut RESPONDED (= « envoyé, en attente de
    validation par la réceptrice ») et le stock de B est déduit tout de suite ;
  - la réceptrice A valide avec l'action existante `confirm_reception` (écart
    -> litige + blocage de clôture, BUG-037/223 ; résolution par
    `resolve_dispute`). Aucune de ces actions n'est dupliquée.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from core.models import BreadPrice, Node
from core.utils import create_notification, log_activity
from .models import BreadStock, BreadTransfer, BreadTransferLine, _adjust_bread_stock


def _resolve_destination(raw):
    """Boulangerie destinataire : clé primaire ou code (K1, B2…)."""
    from kiese.node_guard import resolve_node_param

    if raw is None or raw == '':
        raise ValidationError({'detail': "La boulangerie destinataire (to_node) est requise."})
    # BUG-541 : bool / flottant / liste refusés (400) par le helper commun.
    node, bad = resolve_node_param(raw)
    if bad is not None:
        raise ValidationError({'detail': f"Boulangerie destinataire introuvable ({str(raw)[:40]})."})
    # BUG-540 : le nœud technique SIEGE et les boulangeries inactives ne reçoivent pas de pains.
    if node.code == 'SIEGE' or not node.is_active:
        raise ValidationError({'detail': f"« {node.code} » n'est pas une boulangerie destinataire valide."})
    return node


class DirectTransferMixin:
    """À mélanger à `BreadTransferViewSet` (permissions : IsGerant via get_permissions)."""

    @action(detail=False, methods=['post'], url_path='send')
    def send_direct(self, request):
        from .views import _body_not_object_response, _strict_int, _strict_pk  # évite l'import circulaire

        user = request.user
        bad_body = _body_not_object_response(request)
        if bad_body is not None:
            return bad_body
        if not user.node_id:
            raise ValidationError({'detail': (
                "Votre compte n'est rattaché à aucune boulangerie : un envoi de pains "
                "doit être fait depuis une boulangerie."
            )})
        # from_node = boulangerie de l'appelant, jamais lue dans le corps.
        from_node = user.node
        to_node = _resolve_destination(request.data.get('to_node'))
        if to_node.pk == from_node.pk:
            raise ValidationError({'detail': "Une boulangerie ne peut pas s'envoyer des pains à elle-même."})

        raw_lines = request.data.get('lines')
        if not isinstance(raw_lines, list) or not raw_lines:
            raise ValidationError({'detail': "Au moins une ligne (catégorie de pain et quantité) est requise."})
        wanted = {}
        for ld in raw_lines:
            if not isinstance(ld, dict):
                raise ValidationError({'detail': "Chaque ligne doit être un objet {bread_price, quantity_sent}."})
            bp_id = ld.get('bread_price')
            try:
                bp = BreadPrice.objects.get(pk=_strict_pk(bp_id, 'catégorie de pain'))
            except (BreadPrice.DoesNotExist, TypeError, ValueError, DjangoValidationError):
                raise ValidationError({'detail': f"Catégorie de pain introuvable ({bp_id})."})
            qty = _strict_int(ld.get('quantity_sent'), f"quantité envoyée ({bp.label})", minimum=1)
            wanted[bp.pk] = (bp, wanted.get(bp.pk, (bp, 0))[1] + qty)
        notes = request.data.get('notes') or ''
        if not isinstance(notes, str):
            raise ValidationError({'detail': "Les notes doivent être un texte."})

        with transaction.atomic():
            # Verrou des stocks de l'émetteur (ordre stable) : deux envois
            # simultanés ne peuvent pas déduire deux fois les mêmes pains.
            for bp_pk in sorted(wanted):
                BreadStock.objects.get_or_create(node=from_node, bread_price_id=bp_pk)
            stocks = {
                s.bread_price_id: s for s in BreadStock.objects.select_for_update()
                .filter(node=from_node, bread_price_id__in=list(wanted)).order_by('bread_price_id')
            }
            for bp_pk, (bp, qty) in wanted.items():
                available = stocks[bp_pk].qty_available
                if qty > available:
                    raise ValidationError({'detail': (
                        f"Stock insuffisant pour {bp.label} : {max(available, 0)} disponible(s) "
                        f"à {from_node.code}, {qty} demandé(s)."
                    )})
            transfer = BreadTransfer.objects.create(
                from_node=from_node, to_node=to_node, initiated_by=user,
                transfer_status=BreadTransfer.TransferStatus.RESPONDED,
                flow=BreadTransfer.Flow.DIRECT, notes=notes.strip(),
                node_origin=from_node.code,
            )
            for bp, qty in wanted.values():
                BreadTransferLine.objects.create(transfer=transfer, bread_price=bp, quantity_sent=qty)
                _adjust_bread_stock(from_node, bp, sent=qty)

        summary = ', '.join(f"{qty}×{bp.label}" for bp, qty in wanted.values())
        create_notification(
            title=f"Pains Envoyés — {to_node.code}",
            message=(
                f"La boulangerie {from_node.code} vous envoie directement {summary}. "
                f"Veuillez confirmer la réception."
            ),
            severity='INFO', node_origin=to_node.code,
        )
        log_activity(
            user, "Envoi Direct de Pains",
            f"{from_node.code} envoie {summary} à {to_node.code} (envoi direct).",
            node_origin=from_node.code,
        )
        from .serializers import BreadTransferSerializer
        return Response(BreadTransferSerializer(transfer).data, status=status.HTTP_201_CREATED)
