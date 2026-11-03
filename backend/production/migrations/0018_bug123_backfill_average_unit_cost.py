"""
BUG-123 (Q-005) : recalcule `ConsumableStock.average_unit_cost` (CUMP) à
partir de l'historique réel des mouvements `ConsumableMovement` déjà en
base, en les rejouant dans l'ordre chronologique (ENTRY met à jour la
moyenne pondérée, EXIT la laisse inchangée) — pour que les sorties déjà
enregistrées avant ce correctif disposent elles aussi d'une valorisation
cohérente si elles sont relues plus tard, et que le Compte de Résultat
reparte d'un état cohérent dès l'application de cette migration.

BUG-126 (vérification de BUG-123 par auditeur-comptable, 2026-11-02/03) :
le recalcul initial ne mettait à jour que `ConsumableStock.average_unit_cost`
(le CUMP final du stock), jamais `ConsumableMovement.unit_price` sur les
sorties (EXIT) déjà en base — alors que `finance.views._income_statement_for_year`
valorise le coût matière en sommant `quantity × unit_price` ligne par ligne
sur chaque EXIT, pas via le CUMP courant du stock. Toute sortie historique
restait donc comptée pour 0 FC, pour toujours. Corrigé : chaque EXIT
historique reçoit désormais, lui aussi, le CUMP tel qu'il était calculé
CHRONOLOGIQUEMENT à cet instant précis de l'historique (`running_avg` au
moment de cette sortie, pas le CUMP final du stock) — même principe que
`InvoiceLine.unit_price` figé au moment de la vente (CLAUDE.md §4).

Réversible : la migration inverse remet `average_unit_cost` à 0 et les
`unit_price` des EXIT à 0 (état par défaut avant cette migration — aucune
perte, ces valeurs étaient déjà 0.00 pour tout EXIT antérieur au correctif).
"""
from decimal import Decimal

from django.db import migrations


def backfill_average_unit_cost(apps, schema_editor):
    ConsumableStock = apps.get_model('production', 'ConsumableStock')
    ConsumableMovement = apps.get_model('production', 'ConsumableMovement')

    for stock in ConsumableStock.objects.all():
        running_qty = Decimal('0')
        running_avg = Decimal('0')
        movements = ConsumableMovement.objects.filter(stock=stock).order_by('created_at', 'pk')
        exits_to_restamp = []
        for mv in movements:
            qty = Decimal(str(mv.quantity))
            if mv.movement_type == 'ENTRY':
                price = Decimal(str(mv.unit_price or '0'))
                new_qty = running_qty + qty
                if new_qty > 0:
                    running_avg = ((running_qty * running_avg) + (qty * price)) / new_qty
                else:
                    running_avg = price
                running_qty = new_qty
            else:
                # BUG-126 : fige sur CETTE sortie le CUMP tel qu'il était à
                # cet instant chronologique précis de l'historique, pas le
                # CUMP final du stock calculé en fin de boucle.
                mv.unit_price = running_avg
                exits_to_restamp.append(mv)
                running_qty -= qty
        for mv in exits_to_restamp:
            mv.save(update_fields=['unit_price'])
        stock.average_unit_cost = running_avg
        stock.save(update_fields=['average_unit_cost'])


def reset_average_unit_cost(apps, schema_editor):
    ConsumableStock = apps.get_model('production', 'ConsumableStock')
    ConsumableMovement = apps.get_model('production', 'ConsumableMovement')
    ConsumableStock.objects.update(average_unit_cost=Decimal('0.0000'))
    ConsumableMovement.objects.filter(movement_type='EXIT').update(unit_price=Decimal('0.00'))


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0017_bug123_consumable_average_unit_cost'),
    ]

    operations = [
        migrations.RunPython(backfill_average_unit_cost, reset_average_unit_cost),
    ]
