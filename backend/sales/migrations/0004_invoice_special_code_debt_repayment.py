from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0003_invoice_is_soldee'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='special_code',
            field=models.CharField(
                blank=True,
                choices=[('', '—'), ('NV', 'Nouveau client'), ('RG', 'Régularisation'), ('NS', 'Non Servi')],
                default='',
                max_length=2,
                verbose_name='Code Spécial (NV/RG/NS)',
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='is_debt_repayment',
            field=models.BooleanField(default=False, verbose_name='Remboursement BP'),
        ),
    ]
