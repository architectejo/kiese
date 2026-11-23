from django.db import migrations, models

SALT_BAG_G = '20000.000'
SALT_UNITS = 204


def set_salt(apps, schema_editor):
    """Reponse ferme du client : 1 sac de sel = 20 kg = 204 boites (idempotent, ne
    remplace jamais une valeur deja saisie)."""
    CT = apps.get_model('production', 'ConsumableType')
    CT.objects.filter(code='SALT', bag_weight_g__isnull=True, units_per_bag__isnull=True).update(
        bag_weight_g=SALT_BAG_G, units_per_bag=SALT_UNITS)


def unset_salt(apps, schema_editor):
    CT = apps.get_model('production', 'ConsumableType')
    CT.objects.filter(code='SALT', bag_weight_g=SALT_BAG_G, units_per_bag=SALT_UNITS).update(
        bag_weight_g=None, units_per_bag=None)


class Migration(migrations.Migration):
    dependencies = [('production', '0030_bug626_consumablecount_is_synced')]

    operations = [
        migrations.AddField('consumabletype', 'bag_weight_g', models.DecimalField(
            blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="Poids d'un sac (g)")),
        migrations.AddField('consumabletype', 'units_per_bag', models.PositiveIntegerField(
            blank=True, null=True, verbose_name='Boîtes par sac')),
        migrations.RunPython(set_salt, unset_salt),
    ]
