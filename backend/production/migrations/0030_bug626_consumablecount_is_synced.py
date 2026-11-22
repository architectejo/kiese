from django.db import migrations, models


def flag_legacy_counts(apps, schema_editor):
    """BUG-626 : les comptages historiques (sans inventaire) deviennent « à synchroniser ».
    Le Cloud les accepte de façon idempotente (clé naturelle), un rejeu est sans effet."""
    ConsumableCount = apps.get_model('production', 'ConsumableCount')
    ConsumableCount.objects.filter(inventory__isnull=True).update(is_synced=False)


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0029_bug803_movement_unit_price_4dp'),
    ]

    operations = [
        migrations.AddField(
            model_name='consumablecount',
            name='is_synced',
            field=models.BooleanField(default=True, verbose_name='Synchronisé'),
        ),
        migrations.RunPython(flag_legacy_counts, migrations.RunPython.noop),
    ]
