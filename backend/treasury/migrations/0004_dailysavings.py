import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0003_journalentry'),
        ('core', '0008_config_savings_rate'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DailySavings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Date')),
                ('flour_sacks', models.DecimalField(decimal_places=2, default='0.00', max_digits=6, verbose_name='Sacs farine (PROD)')),
                ('daily_revenue', models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Revenu du jour (FC)')),
                ('savings_rate', models.DecimalField(decimal_places=4, default='0.1580', max_digits=5, verbose_name='Taux épargne')),
                ('savings_amount', models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Montant Épargne (FC)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('node', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='daily_savings',
                    to='core.node',
                    verbose_name='Boulangerie',
                )),
                ('recorded_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='daily_savings',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Saisi par',
                )),
            ],
            options={
                'verbose_name': 'Épargne Journalière',
                'verbose_name_plural': 'Épargnes Journalières',
                'ordering': ['-date', 'node__code'],
            },
        ),
        migrations.AddConstraint(
            model_name='dailysavings',
            constraint=models.UniqueConstraint(fields=['node', 'date'], name='unique_daily_savings_node_date'),
        ),
    ]
