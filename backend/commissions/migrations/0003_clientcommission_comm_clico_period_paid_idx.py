# BUG-066 : index ciblé pour FinancialYearViewSet.comparative() (finance/views.py)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0006_clientcodesequence'),
        ('commissions', '0002_commission_carte_remise_manuel'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='clientcommission',
            index=models.Index(fields=['period', 'is_paid'], name='comm_clico_period_paid_idx'),
        ),
    ]
