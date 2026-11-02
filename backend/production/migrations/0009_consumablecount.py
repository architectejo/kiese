import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0008_consumablemovement_supplier'),
        ('core', '0007_data_nodes_b1_b2'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ConsumableCount',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('consumable_type', models.CharField(
                    choices=[
                        ('FLOUR', 'Farine (Sac 50 kg)'),
                        ('SALT',  'Sel (g)'),
                        ('YEAST', 'Levure (Paquet 450 g)'),
                        ('OIL',   'Huile (Litre)'),
                    ],
                    max_length=10,
                    verbose_name='Consommable',
                )),
                ('count_date', models.DateField(verbose_name='Date de comptage')),
                ('system_quantity', models.DecimalField(decimal_places=3, max_digits=10, verbose_name='Qté Système')),
                ('physical_quantity', models.DecimalField(decimal_places=3, max_digits=10, verbose_name='Qté Physique Constatée')),
                ('gap', models.DecimalField(decimal_places=3, max_digits=10, verbose_name='Écart (physique − système)')),
                ('notes', models.TextField(blank=True, default='', verbose_name='Notes')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('node', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='consumable_counts',
                    to='core.node',
                    verbose_name='Boulangerie',
                )),
                ('counted_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='consumable_counts',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Compté par',
                )),
            ],
            options={
                'verbose_name': 'Comptage Physique',
                'verbose_name_plural': 'Comptages Physiques',
                'ordering': ['-count_date', 'node__code'],
            },
        ),
    ]
