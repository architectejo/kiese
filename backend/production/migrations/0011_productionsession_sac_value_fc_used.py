# BUG-038 (docs/qa/REGISTRE_BUGS.md) : fige la valeur du sac (FC) utilisée au
# moment de la déclaration initiale d'une fournée, pour ne jamais recalculer
# son historique avec la valeur courante de Node.sac_value_fc/Config lors
# d'une édition ultérieure.
#
# Volontairement isolée de la dérive préexistante détectée par ailleurs par
# `makemigrations production` (AlterField transfer_status/id sur
# breadtransfer/breadtransferline/consumablecount, due à un changement de
# DEFAULT_AUTO_FIELD / ordre des choices non lié à ce ticket) — non incluse
# ici, à traiter séparément si besoin.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0010_consumabletype'),
    ]

    operations = [
        migrations.AddField(
            model_name='productionsession',
            name='sac_value_fc_used',
            field=models.PositiveIntegerField(default=200000, verbose_name='Valeur du sac utilisée (figée à la déclaration, FC)'),
        ),
    ]
