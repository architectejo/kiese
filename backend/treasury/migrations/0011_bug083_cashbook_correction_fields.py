# BUG-083 (« ventes passées », remarque.md l.360) : champs de traçabilité
# d'une écriture de correction du Livre de Caisse Direction — jamais une
# modification d'une CashbookEntry existante (CLAUDE.md §5.5, point non
# négociable du ticket). Ne reprend pas la dérive de schéma préexistante
# (BUG-057, unique_together dailysavings / id BigAutoField sur
# dailysavings/journalentry) détectée par makemigrations sur cette app —
# même convention que 0010_bug066_cashbook_localexpense_indexes.py.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0010_bug066_cashbook_localexpense_indexes'),
        ('sales', '0006_alter_invoice_invoice_date'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='cashbookentry',
            name='is_correction',
            field=models.BooleanField(default=False, verbose_name='Écriture de correction'),
        ),
        migrations.AddField(
            model_name='cashbookentry',
            name='correction_reason',
            field=models.TextField(blank=True, default='', verbose_name='Motif de la correction'),
        ),
        migrations.AddField(
            model_name='cashbookentry',
            name='corrected_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cashbook_corrections',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Corrigé par',
            ),
        ),
        migrations.AddField(
            model_name='cashbookentry',
            name='correction_source_invoice',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cashbook_corrections',
                to='sales.invoice',
                verbose_name="Facture d'origine de la correction",
            ),
        ),
    ]
