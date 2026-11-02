# DisbursementVoucher (bordereau de versement) — additive only.
# No data migration needed: purely new model + nullable FK on CashbookEntry.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_data_node_siege'),
        ('treasury', '0005_localexpense_category_fk'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DisbursementVoucher',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='Identifiant unique')),
                ('node_origin', models.CharField(default='CLOUD', help_text='Code du nœud ayant créé cet enregistrement (ex: K1, K2, CLOUD)', max_length=10, verbose_name="Nœud d'origine")),
                ('is_synced', models.BooleanField(default=True, help_text='Indique si cet enregistrement a été synchronisé avec le Cloud', verbose_name='Synchronisé')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Créé le')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Modifié le')),
                ('date', models.DateField(verbose_name='Date')),
                ('motif', models.CharField(max_length=255, verbose_name='Motif / Objet')),
                ('beneficiary', models.CharField(blank=True, default='', max_length=150, verbose_name='Bénéficiaire')),
                ('bills_20000', models.PositiveIntegerField(default=0, verbose_name='Billets 20 000 FC')),
                ('bills_10000', models.PositiveIntegerField(default=0, verbose_name='Billets 10 000 FC')),
                ('bills_5000', models.PositiveIntegerField(default=0, verbose_name='Billets 5 000 FC')),
                ('bills_1000', models.PositiveIntegerField(default=0, verbose_name='Billets 1 000 FC')),
                ('bills_500', models.PositiveIntegerField(default=0, verbose_name='Billets 500 FC')),
                ('bills_200', models.PositiveIntegerField(default=0, verbose_name='Billets 200 FC')),
                ('bills_100', models.PositiveIntegerField(default=0, verbose_name='Billets 100 FC')),
                ('bills_50', models.PositiveIntegerField(default=0, verbose_name='Billets 50 FC')),
                ('physical_cash_total', models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Montant Total (FC)')),
                ('piece_number', models.CharField(blank=True, default='', max_length=30, verbose_name='N° Pièce')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='disbursement_vouchers', to=settings.AUTH_USER_MODEL, verbose_name='Émis par')),
            ],
            options={
                'verbose_name': 'Bordereau de Versement',
                'verbose_name_plural': 'Bordereaux de Versement',
                'ordering': ['-date', '-created_at'],
            },
        ),
        migrations.AddField(
            model_name='cashbookentry',
            name='source_bordereau',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cashbook_entries', to='treasury.disbursementvoucher', verbose_name='Bordereau source'),
        ),
    ]
