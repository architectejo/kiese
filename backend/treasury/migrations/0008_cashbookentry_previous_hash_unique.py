# BUG-002 (docs/qa/REGISTRE_BUGS.md) : contrainte d'unicité sur
# `CashbookEntry.previous_hash`. Deux écritures concurrentes ne peuvent plus
# chaîner un bloc enfant à partir du même parent (fourche de la chaîne) :
# la seconde insertion échoue en base avec une IntegrityError, que
# `treasury.views.append_cashbook_entry` retente après relecture du nouveau
# dernier solde. Appliquée APRÈS la migration de données 0007 qui a
# recalculé/vérifié la chaîne, pour ne jamais se heurter à un doublon
# préexistant.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0007_recompute_cashbook_hash'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cashbookentry',
            name='previous_hash',
            field=models.CharField(blank=True, default='', max_length=64, unique=True, verbose_name='Hash Précédent'),
        ),
    ]
