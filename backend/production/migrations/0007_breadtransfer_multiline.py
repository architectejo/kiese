from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('production', '0006_productionsession_notes'),
    ]

    operations = [
        # Make legacy single-category fields nullable
        migrations.AlterField(
            model_name='breadtransfer',
            name='bread_price',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='core.breadprice',
                verbose_name='Catégorie Pain (legacy)',
            ),
        ),
        migrations.AlterField(
            model_name='breadtransfer',
            name='quantity_sent',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Quantité envoyée (legacy)'),
        ),
        # New multi-line table
        migrations.CreateModel(
            name='BreadTransferLine',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity_sent', models.PositiveIntegerField(verbose_name='Quantité envoyée')),
                ('quantity_received', models.PositiveIntegerField(blank=True, null=True, verbose_name='Quantité reçue')),
                ('bread_price', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to='core.breadprice',
                    verbose_name='Catégorie Pain',
                )),
                ('transfer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lines',
                    to='production.breadtransfer',
                    verbose_name='Transfert',
                )),
            ],
            options={
                'verbose_name': 'Ligne de Transfert',
                'verbose_name_plural': 'Lignes de Transfert',
                'ordering': ['bread_price__unit_price'],
                'unique_together': {('transfer', 'bread_price')},
            },
        ),
    ]
