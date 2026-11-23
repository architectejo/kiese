# BUG-980 : transferts non terminaux connus d'un poste (rattrapage après > 30 jours hors ligne).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_sync_degraded_mode_fields'),
        ('sync', '0002_batchlog_fingerprint_conflict_occurrences'),
    ]

    operations = [
        migrations.CreateModel(
            name='NodeOpenTransfers',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transfer_ids', models.JSONField(default=list, verbose_name='Transferts non terminaux connus du poste')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('node', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='open_transfers_state', to='core.node')),
            ],
            options={
                'verbose_name': "Transferts ouverts d'un poste",
                'verbose_name_plural': 'Transferts ouverts des postes',
            },
        ),
    ]
