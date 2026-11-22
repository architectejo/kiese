from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models

RATIO = Decimal('0.75')


def _freeze(p):
    return int((Decimal(p) * RATIO).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def backfill(apps, schema_editor):
    """Prix plein des lignes existantes : prix figé tel quel (vente normale) ;
    pour une vente soldée, tarif catalogue s'il est compatible avec le prix figé
    (arrondi du 75 %), sinon prix figé / 0,75 arrondi (meilleure déduction)."""
    InvoiceLine = apps.get_model('sales', 'InvoiceLine')
    for line in InvoiceLine.objects.select_related('invoice', 'bread_price').filter(full_unit_price__isnull=True).iterator():
        if line.invoice.is_soldee:
            catalog = int(line.bread_price.unit_price)
            if _freeze(catalog) == line.unit_price:
                full = catalog
            else:
                full = int((Decimal(line.unit_price) / RATIO).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        else:
            full = line.unit_price
        InvoiceLine.objects.filter(pk=line.pk).update(full_unit_price=full)


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0010_bug318_not_served'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceline',
            name='full_unit_price',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Prix plein figé (FC)'),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
