"""
BUG-357 : recalcule le CUMP (`ConsumableStock.average_unit_cost`) et la
valorisation des sorties (`ConsumableMovement.unit_price` des EXIT) en
rejouant chronologiquement les mouvements de chaque stock avec la formule
corrigée par BUG-402 : un stock négatif n'a pas de valeur, seule la part
positive (`base_qty = max(old_qty, 0)`) pèse dans la moyenne, au numérateur
comme au dénominateur (cf. `ConsumableMovement.save()`).

Usage :
    python manage.py recompute_cump              # SIMULATION (par défaut)
    python manage.py recompute_cump --apply      # écrit en base
    python manage.py recompute_cump --node K1    # limite à une boulangerie

Convention de rejeu identique à la migration 0018 : départ à quantité 0 et
CUMP 0, ordre `created_at, pk`. La quantité du stock n'est JAMAIS modifiée ;
si le rejeu ne retombe pas sur la quantité en base (stock initial saisi sans
mouvement), un avertissement est affiché : le CUMP de la part non tracée
ne peut pas être reconstitué.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.utils import log_activity
from production.models import ConsumableMovement, ConsumableStock

_Q_AVG = Decimal('0.0001')
_Q_PRICE = Decimal('0.01')
ZERO = Decimal('0')


def replay_stock(movements):
    """
    Rejoue `movements` (déjà ordonnés) et retourne
    (cump_final, quantité_finale, {pk_mouvement_EXIT: prix_unitaire_recalculé}).
    Fonction pure, Decimal uniquement.
    """
    qty = ZERO
    avg = ZERO
    exit_prices = {}
    for mv in movements:
        mq = Decimal(str(mv.quantity))
        if mv.movement_type == ConsumableMovement.MovementType.ENTRY:
            price = Decimal(str(mv.unit_price or '0'))
            new_qty = qty + mq
            base_qty = max(qty, ZERO)
            if new_qty > 0:
                avg = ((base_qty * avg) + (mq * price)) / (base_qty + mq)
            else:
                avg = price
            qty = new_qty
        else:
            exit_prices[mv.pk] = avg.quantize(_Q_PRICE)
            qty -= mq
    return avg.quantize(_Q_AVG), qty, exit_prices


class Command(BaseCommand):
    help = ("Recalcule le CUMP des stocks de consommables avec la formule corrigée (BUG-402). "
            "Simulation par défaut ; --apply pour écrire.")

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Écrit les corrections en base.")
        parser.add_argument('--dry-run', action='store_true', help="Simulation (comportement par défaut).")
        parser.add_argument('--node', default=None, help="Code d'une boulangerie (ex. K1).")

    def handle(self, *args, **opts):
        apply = opts['apply']
        if apply and opts['dry_run']:
            raise CommandError("--apply et --dry-run sont incompatibles.")
        mode = "APPLICATION" if apply else "SIMULATION (aucune écriture ; --apply pour appliquer)"
        self.stdout.write(f"recompute_cump : {mode}")

        qs = ConsumableStock.objects.order_by('node__code', 'consumable_type')
        if opts['node']:
            qs = qs.filter(node__code=opts['node'])
        stock_ids = list(qs.values_list('pk', flat=True))

        changed = 0
        for pk in stock_ids:
            with transaction.atomic():
                stock = ConsumableStock.objects.select_for_update().select_related('node').get(pk=pk)
                movements = list(
                    ConsumableMovement.objects.select_for_update()
                    .filter(stock=stock).order_by('created_at', 'pk')
                )
                new_avg, replay_qty, exit_prices = replay_stock(movements)
                old_avg = Decimal(str(stock.average_unit_cost)).quantize(_Q_AVG)
                exits_to_fix = [
                    (m, exit_prices[m.pk]) for m in movements
                    if m.pk in exit_prices
                    and Decimal(str(m.unit_price)).quantize(_Q_PRICE) != exit_prices[m.pk]
                ]
                label = f"{stock.node.code} {stock.consumable_type}"
                if new_avg == old_avg and not exits_to_fix:
                    self.stdout.write(f"  {label} : inchangé (CUMP {old_avg})")
                else:
                    changed += 1
                    self.stdout.write(
                        f"  {label} : CUMP {old_avg} -> {new_avg} (écart {new_avg - old_avg:+}) ; "
                        f"{len(exits_to_fix)} sortie(s) à revaloriser"
                    )
                if Decimal(str(stock.quantity)) != replay_qty:
                    self.stdout.write(self.style.WARNING(
                        f"    attention : quantité en base {stock.quantity} != quantité rejouée {replay_qty} "
                        f"(stock initial non tracé par des mouvements ; quantité NON modifiée)."
                    ))
                if apply and (new_avg != old_avg or exits_to_fix):
                    for m, price in exits_to_fix:
                        ConsumableMovement.objects.filter(pk=m.pk).update(unit_price=price)
                    ConsumableStock.objects.filter(pk=stock.pk).update(average_unit_cost=new_avg)
                    log_activity(
                        None, "Recalcul CUMP (BUG-357)",
                        f"{label} : CUMP {old_avg} -> {new_avg}, {len(exits_to_fix)} sortie(s) revalorisée(s).",
                        node_origin=stock.node.code,
                    )

        verb = "corrigé(s)" if apply else "à corriger"
        self.stdout.write(f"Terminé : {len(stock_ids)} stock(s) examiné(s), {changed} {verb}.")
