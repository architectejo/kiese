# BUG-066 : index ciblés pour FinancialYearViewSet.comparative() (finance/views.py)
# — ne reprend pas la dérive de schéma préexistante (BUG-057, unique_together
# dailysavings / id BigAutoField) détectée par makemigrations sur cette app.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0009_facturierreport_category_detail'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='cashbookentry',
            index=models.Index(fields=['date', 'created_at'], name='treas_cashbook_date_crea_idx'),
        ),
        migrations.AddIndex(
            model_name='localexpense',
            index=models.Index(fields=['date'], name='treas_localexp_date_idx'),
        ),
    ]
