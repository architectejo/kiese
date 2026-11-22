from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations
from django.db.models import F

RATIO = Decimal('0.75')
BATCH = 500


def _freeze(p):
    return int((Decimal(p) * RATIO).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def backfill(apps, schema_editor):
    """Rétro-remplit `full_unit_price` (idempotent : ne touche que les lignes NULL).

    - ventes normales : un seul UPDATE (prix plein = prix figé) ;
    - ventes soldées : par lots de 500 (pk croissant). Tarif catalogue courant s'il
      est compatible avec le prix figé (arrondi du 75 %), sinon prix figé / 0,75 arrondi.
    """
    InvoiceLine = apps.get_model('sales', 'InvoiceLine')
    InvoiceLine.objects.filter(
        full_unit_price__isnull=True, invoice__is_soldee=False,
    ).update(full_unit_price=F('unit_price'))

    last_pk = 0
    while True:
        batch = list(
            InvoiceLine.objects.filter(
                full_unit_price__isnull=True, invoice__is_soldee=True, pk__gt=last_pk,
            ).select_related('bread_price').order_by('pk')[:BATCH]
        )
        if not batch:
            break
        for line in batch:
            catalog = int(line.bread_price.unit_price)
            if _freeze(catalog) == line.unit_price:
                full = catalog
            else:
                full = int((Decimal(line.unit_price) / RATIO).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            InvoiceLine.objects.filter(pk=line.pk, full_unit_price__isnull=True).update(full_unit_price=full)
        last_pk = batch[-1].pk


class Migration(migrations.Migration):
    # Non atomique : chaque lot est validé seul, aucun verrou long sur la table.
    atomic = False

    dependencies = [
        ('sales', '0011_bug508_full_unit_price'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
