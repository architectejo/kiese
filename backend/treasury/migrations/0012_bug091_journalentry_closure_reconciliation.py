# Generated for BUG-091 : rapprochement de l'imputation « Recettes du jour
# (CA) » de JournalEntry avec la CashClosure (Niveau 2) du même (nœud, date).
#
# Rédigée à la main (plutôt que par `makemigrations treasury`) pour isoler
# strictement ce changement de schéma d'une dérive préexistante et non liée
# (DailySavings.unique_together / type de champ `id`) détectée par
# `makemigrations --check --dry-run` sur ce dépôt — hors périmètre de ce
# ticket, à signaler séparément.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0011_bug083_cashbook_correction_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='journalentry',
            name='is_reconciled',
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Vrai si une CashClosure existait pour ce (nœud, date) au moment de la "
                    "saisie de cette écriture CA. Faux = « non rapprochée avec la Clôture », "
                    "y compris pour toute autre imputation que CA."
                ),
                verbose_name='Rapproché avec la Clôture (imputation CA)',
            ),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='reconciliation_gap',
            field=models.DecimalField(
                decimal_places=2,
                default='0.00',
                help_text=(
                    "entry_amount saisi − CashClosure.total_entries de la clôture rapprochée. "
                    "Non nul = avertissement journalisé (SystemNotification), jamais un blocage."
                ),
                max_digits=14,
                verbose_name='Écart de rapprochement (CA) (FC)',
            ),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='reconciled_closure',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='journal_entries',
                to='treasury.cashclosure',
                verbose_name='Clôture rapprochée (imputation CA)',
            ),
        ),
    ]
