# BUG-066 : index ciblé pour FinancialYearViewSet.comparative() (finance/views.py)
# — ne reprend pas la dérive de schéma préexistante (BUG-057, id BigAutoField /
# libellé transfer_status) détectée par makemigrations sur cette app.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0011_productionsession_sac_value_fc_used'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='consumablemovement',
            index=models.Index(fields=['movement_type', 'created_at'], name='prod_consmove_type_crea_idx'),
        ),
    ]
