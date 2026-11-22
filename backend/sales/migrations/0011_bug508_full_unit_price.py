from django.db import migrations, models


class Migration(migrations.Migration):
    """BUG-508 : schéma seul (colonne nullable, sans verrou long sur PostgreSQL).

    Le rétro-remplissage des lignes existantes est dans `0012_bug508_backfill_full_unit_price`
    (migration non atomique, par lots), pour ne pas garder un ACCESS EXCLUSIVE sur
    `sales_invoiceline` pendant toute la reprise de données.
    """

    dependencies = [
        ('sales', '0010_bug318_not_served'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceline',
            name='full_unit_price',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Prix plein figé (FC)'),
        ),
    ]
