from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('commissions', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientcommission',
            name='deduction_carte',
            field=models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Retenue CARTE 1% (FC)'),
        ),
        migrations.AddField(
            model_name='clientcommission',
            name='deduction_remise',
            field=models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='Remise 0.1% (FC)'),
        ),
        migrations.AddField(
            model_name='clientcommission',
            name='net_ordi',
            field=models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='NET/ORDI (CM − BP)'),
        ),
        migrations.AddField(
            model_name='clientcommission',
            name='net_carte',
            field=models.DecimalField(decimal_places=2, default='0.00', max_digits=14, verbose_name='NET/CARTE (NET/ORDI − CARTE)'),
        ),
        migrations.AddField(
            model_name='clientcommission',
            name='manuel_adjustment',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, verbose_name='Ajustement Manuel (FC)'),
        ),
        migrations.AddField(
            model_name='clientcommission',
            name='manuel_notes',
            field=models.TextField(blank=True, default='', verbose_name='Observation Ajustement'),
        ),
    ]
