# BUG-033 (docs/qa/REGISTRE_BUGS.md) : détail par catégorie de pain du
# Rapport Facturier Niveau 1 (remarque.md l.142) — sacs de farine consommés,
# pains produits/vendus par catégorie, écart valeur sacs/ventes. Migration
# volontairement limitée à ces quatre nouveaux champs : le drift détecté par
# ailleurs par `makemigrations --check --dry-run` sur `core`/`production`/
# `clients` (alter des champs `id`/`unique_together` liés aux modèles
# `SyncableModel`) est pré-existant, sans rapport avec ce ticket, et laissé
# tel quel (voir rapport dev-backend-tresorerie-2026-10-22.md).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0008_cashbookentry_previous_hash_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='facturierreport',
            name='sacks_consumed',
            field=models.DecimalField(decimal_places=2, default='0.00', max_digits=8, verbose_name='Sacs de farine consommés (vacation)'),
        ),
        migrations.AddField(
            model_name='facturierreport',
            name='breads_produced_by_category',
            field=models.JSONField(blank=True, default=dict, help_text='Dictionnaire {libellé catégorie: quantité produite} pour la vacation.', verbose_name='Pains produits par catégorie'),
        ),
        migrations.AddField(
            model_name='facturierreport',
            name='breads_sold_by_category',
            field=models.JSONField(blank=True, default=dict, help_text='Dictionnaire {libellé catégorie: quantité vendue} pour la vacation.', verbose_name='Pains vendus par catégorie'),
        ),
        migrations.AddField(
            model_name='facturierreport',
            name='sacks_value_gap',
            field=models.DecimalField(decimal_places=2, default='0.00', help_text="Valeur réalisée par la vente moins la valeur théorique des sacs consommés (sacs × valeur du sac, remarque.md l.142). Convention alignée sur production.ProductionSession.yield_gap : positif = excédent, négatif = manquant.", max_digits=14, verbose_name='Écart valeur sacs / ventes (FC)'),
        ),
    ]
