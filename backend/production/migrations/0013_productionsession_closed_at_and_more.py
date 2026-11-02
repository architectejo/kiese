# Generated for BUG-093 (docs/qa/REGISTRE_BUGS.md) on 2026-10-30.
# Ne garde que les champs ajoutés par ce ticket (closed_at, closure_summary) ;
# le reste du diff auto-détecté par `makemigrations` (transfer_status,
# id de breadtransferline/consumablecount, et dérive similaire dans
# clients/treasury) est une dérive de schéma préexistante, sans rapport avec
# BUG-093 — signalée au coordinateur plutôt que corrigée ici (hors périmètre).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0012_bug066_consumablemovement_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='productionsession',
            name='closed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Clôturée le'),
        ),
        migrations.AddField(
            model_name='productionsession',
            name='closure_summary',
            field=models.JSONField(blank=True, null=True, verbose_name='Détail du recoupement à la clôture'),
        ),
    ]
