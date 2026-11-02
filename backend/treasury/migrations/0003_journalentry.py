import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0002_cashclosure_rejection'),
        ('core', '0007_data_nodes_b1_b2'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='JournalEntry',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Date')),
                ('imput', models.CharField(
                    choices=[
                        ('CA',        'Recettes du jour (CA)'),
                        ('PAY_BLG',   'Paye boulangers'),
                        ('RATION',    'Ration boulangers'),
                        ('LIVRAISON', 'Livraison inter-site'),
                        ('EAU',       'Eau'),
                        ('APPRO',     "Frais d'appro"),
                        ('DEPOT',     'Dépôt rapport direction'),
                        ('TRANSPORT', 'Transport'),
                        ('CREDIT',    'Crédit personnel'),
                        ('PRIME',     'Prime personnel'),
                        ('CARBURANT', 'Essence / Mazout'),
                        ('ACHAT',     'Achat matériel / fourniture'),
                        ('AUTRE',     'Autre'),
                    ],
                    max_length=12,
                    verbose_name='Imputation',
                )),
                ('label', models.CharField(blank=True, default='', max_length=200, verbose_name='Libellé')),
                ('entry_amount', models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Entrée (FC)')),
                ('exit_amount', models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Sortie (FC)')),
                ('running_balance', models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Solde Courant (FC)')),
                ('month_carried', models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Report Mois Précédent (FC)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('node', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='journal_entries',
                    to='core.node',
                    verbose_name='Boulangerie',
                )),
                ('recorded_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='journal_entries',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Saisi par',
                )),
            ],
            options={
                'verbose_name': 'Écriture Journal de Caisse',
                'verbose_name_plural': 'Journal de Caisse',
                'ordering': ['date', 'created_at'],
            },
        ),
    ]
