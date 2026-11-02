# Generated for ExpenseCategory (§5.1.2 Dépenses Locales — Configuration)

import django.db.models.deletion
from django.db import migrations, models


SEED_CATEGORIES = [
    ('WOOD',        'Achat de Bois / Combustible'),
    ('MAINTENANCE', 'Petite Maintenance / Réparation'),
    ('TRANSPORT',   'Transport / Livraison'),
    ('MISC',        'Frais Divers'),
]


def seed_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model('core', 'ExpenseCategory')
    for code, label in SEED_CATEGORIES:
        ExpenseCategory.objects.get_or_create(code=code, defaults={'label': label})


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_config_bassins_colisdistribution'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExpenseCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(help_text='Identifiant court unique, ex: WOOD, TRANSPORT', max_length=20, unique=True, verbose_name='Code')),
                ('label', models.CharField(max_length=100, verbose_name='Libellé')),
                ('is_active', models.BooleanField(default=True, verbose_name='Actif')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Catégorie de Dépense',
                'verbose_name_plural': 'Catégories de Dépenses',
                'ordering': ['label'],
            },
        ),
        migrations.RunPython(seed_categories, noop_reverse),
    ]
