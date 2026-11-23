import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_node_block_sales_after_closure'),
        ('sync', '0005_transfermirror_peak'),
    ]

    operations = [
        migrations.CreateModel(
            name='TransferPull',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transfer_id', models.UUIDField(db_index=True)),
                ('pulled_at', models.DateTimeField()),
                ('node', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transfer_pulls', to='core.node')),
            ],
            options={
                'verbose_name': "Dernier pull d'un transfert",
                'verbose_name_plural': 'Derniers pulls des transferts',
                'unique_together': {('node', 'transfer_id')},
            },
        ),
    ]
