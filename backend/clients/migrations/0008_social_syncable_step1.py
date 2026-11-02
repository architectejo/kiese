# Generated manually — BUG-004 (extension 2026-11-02, suite) : préparation
# du passage de SocialContribution/SocialDistribution/SocialDistributionLine
# à SyncableModel (PK UUIDv4, node_origin, is_synced) — voir
# docs/qa/REGISTRE_BUGS.md fiche BUG-004 et CLAUDE.md §4 ("ne jamais
# introduire d'ID auto-incrémenté sur une entité synchronisable").
#
# Étape 1/2 (schéma uniquement, aucune perte de données) : ajoute les
# colonnes manquantes de SyncableModel (node_origin, is_synced, created_at,
# updated_at — `SocialDistribution.created_at` existe déjà, inchangé) ainsi
# qu'une colonne temporaire `new_id` (UUID, nullable) sur les 3 modèles, et
# `new_distribution` (UUID, nullable) sur `SocialDistributionLine` pour
# recevoir la future valeur de son FK vers `SocialDistribution` une fois que
# celle-ci aura, elle aussi, un UUID. Les anciennes colonnes entières
# (`id` AutoField, `distribution_id`) restent intactes à ce stade : la
# migration 0009 les repeuple (RunPython) puis les retire.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0007_bug057_schema_drift_fix'),
    ]

    operations = [
        # --- SocialContribution -------------------------------------------------
        migrations.AddField(
            model_name='socialcontribution',
            name='node_origin',
            field=models.CharField(default='CLOUD', help_text="Code du nœud ayant créé cet enregistrement (ex: K1, K2, CLOUD)", max_length=10, verbose_name="Nœud d'origine"),
        ),
        migrations.AddField(
            model_name='socialcontribution',
            name='is_synced',
            field=models.BooleanField(default=True, help_text="Indique si cet enregistrement a été synchronisé avec le Cloud", verbose_name="Synchronisé"),
        ),
        migrations.AddField(
            model_name='socialcontribution',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=None, null=True, verbose_name="Créé le"),
        ),
        migrations.AddField(
            model_name='socialcontribution',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, verbose_name="Modifié le"),
        ),
        migrations.AddField(
            model_name='socialcontribution',
            name='new_id',
            field=models.UUIDField(editable=False, null=True),
        ),

        # --- SocialDistribution (created_at déjà présent, inchangé) -------------
        migrations.AddField(
            model_name='socialdistribution',
            name='node_origin',
            field=models.CharField(default='CLOUD', help_text="Code du nœud ayant créé cet enregistrement (ex: K1, K2, CLOUD)", max_length=10, verbose_name="Nœud d'origine"),
        ),
        migrations.AddField(
            model_name='socialdistribution',
            name='is_synced',
            field=models.BooleanField(default=True, help_text="Indique si cet enregistrement a été synchronisé avec le Cloud", verbose_name="Synchronisé"),
        ),
        migrations.AddField(
            model_name='socialdistribution',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, verbose_name="Modifié le"),
        ),
        migrations.AddField(
            model_name='socialdistribution',
            name='new_id',
            field=models.UUIDField(editable=False, null=True),
        ),

        # --- SocialDistributionLine ---------------------------------------------
        migrations.AddField(
            model_name='socialdistributionline',
            name='node_origin',
            field=models.CharField(default='CLOUD', help_text="Code du nœud ayant créé cet enregistrement (ex: K1, K2, CLOUD)", max_length=10, verbose_name="Nœud d'origine"),
        ),
        migrations.AddField(
            model_name='socialdistributionline',
            name='is_synced',
            field=models.BooleanField(default=True, help_text="Indique si cet enregistrement a été synchronisé avec le Cloud", verbose_name="Synchronisé"),
        ),
        migrations.AddField(
            model_name='socialdistributionline',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=None, null=True, verbose_name="Créé le"),
        ),
        migrations.AddField(
            model_name='socialdistributionline',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, verbose_name="Modifié le"),
        ),
        migrations.AddField(
            model_name='socialdistributionline',
            name='new_id',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='socialdistributionline',
            name='new_distribution',
            field=models.UUIDField(editable=False, null=True),
        ),
    ]
