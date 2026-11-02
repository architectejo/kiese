# Makes the consumable list (Farine, Sel, Levure, Huile...) admin-managed
# from Configuration instead of a fixed enum. consumable_type stays a plain
# CharField (no FK) on ConsumableStock/ConsumableCount — deliberately, so
# deleting a ConsumableType later never blocks or orphans existing stock
# rows/movements; it only affects which codes show up as addable going
# forward and which label is displayed.
#
# NOTE: this migration only includes the changes relevant to this feature.
# `makemigrations --dry-run` also reports unrelated pre-existing drift
# (breadtransfer.transfer_status choices wording, breadtransferline/
# consumablecount id field type) that predates this change — intentionally
# left out here, untouched.

from django.db import migrations, models


SEED_TYPES = [
    ('FLOUR', 'Farine (Sac 50 kg)', 'sacs'),
    ('SALT',  'Sel (g)',            'g'),
    ('YEAST', 'Levure (Paquet 450 g)', 'paquets'),
    ('OIL',   'Huile (Litre)',      'litres'),
]


def seed_types(apps, schema_editor):
    ConsumableType = apps.get_model('production', 'ConsumableType')
    for code, label, unit in SEED_TYPES:
        ConsumableType.objects.get_or_create(code=code, defaults={'label': label, 'unit': unit})


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0009_consumablecount'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConsumableType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(help_text='Identifiant court unique, ex: FLOUR, SUCRE', max_length=10, unique=True, verbose_name='Code')),
                ('label', models.CharField(max_length=100, verbose_name='Libellé')),
                ('unit', models.CharField(blank=True, default='', max_length=20, verbose_name='Unité')),
                ('is_active', models.BooleanField(default=True, verbose_name='Actif')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Type de Consommable',
                'verbose_name_plural': 'Types de Consommables',
                'ordering': ['code'],
            },
        ),
        migrations.AlterField(
            model_name='consumablestock',
            name='consumable_type',
            field=models.CharField(help_text="Code d'un ConsumableType (Configuration)", max_length=10, verbose_name='Consommable'),
        ),
        migrations.AlterField(
            model_name='consumablecount',
            name='consumable_type',
            field=models.CharField(help_text="Code d'un ConsumableType (Configuration)", max_length=10, verbose_name='Consommable'),
        ),
        migrations.RunPython(seed_types, noop_reverse),
    ]
