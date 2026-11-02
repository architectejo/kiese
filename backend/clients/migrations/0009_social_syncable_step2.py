# Generated manually — BUG-004 (extension 2026-11-02, suite).
#
# Étape 2/2 : repeuple les colonnes temporaires ajoutées par 0008 (RunPython,
# une seule transaction — volume borné : cotisations/distributions par
# client et par boulangerie, jamais de l'ordre des factures/mouvements —
# voir note de risque dans le rapport d'extension si ce volume devait un
# jour dépasser ce qui tient en mémoire d'un coup), PUIS bascule les PK
# entières (`AutoField`) de SocialContribution/SocialDistribution/
# SocialDistributionLine vers des UUID, en réécrivant au passage le FK
# `SocialDistributionLine.distribution -> SocialDistribution` vers le
# nouvel UUID (jamais vers l'ancienne PK locale, qui disparaît).
#
# Irréversible : la migration inverse (`reverse_code`) ne reconstruit pas
# les anciens entiers (perdus par construction — ils n'ont plus aucun sens
# une fois que `SocialDistribution`/`SocialContribution` sont partagés entre
# plusieurs nœuds).
import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def _populate_uuids(apps, schema_editor):
    # `db_alias` : OBLIGATOIRE pour toute donnée migrée via RunPython — sans
    # `.using(db_alias)` explicite, les QuerySet ci-dessous retomberaient
    # silencieusement sur l'alias `'default'` (comportement standard du
    # routeur Django par défaut), QUEL QUE SOIT l'alias réellement migré par
    # `schema_editor`. Sans incidence constatée sur ce dépôt aujourd'hui (une
    # seule base, toujours `'default'`), mais détecté concrètement en testant
    # cette migration sur une base secondaire ad hoc (`UNIQUE constraint
    # failed` : toutes les lignes `new_id` restaient `NULL`, faute d'avoir
    # été mises à jour sur la bonne connexion, puis `COALESCE` leur
    # attribuait à toutes la MÊME valeur de repli lors du changement de PK
    # qui suit) — corrigé ici par prudence avant que la migration ne soit
    # jamais appliquée en production (cf. CLAUDE.md §4 : une migration
    # appliquée ne se modifie plus).
    db_alias = schema_editor.connection.alias
    SocialContribution = apps.get_model('clients', 'SocialContribution')
    SocialDistribution = apps.get_model('clients', 'SocialDistribution')
    SocialDistributionLine = apps.get_model('clients', 'SocialDistributionLine')

    now = timezone.now()
    BATCH = 500

    # --- SocialContribution : nouvel UUID + created_at de secours ---------
    contributions = list(SocialContribution.objects.using(db_alias).all())
    for obj in contributions:
        obj.new_id = uuid.uuid4()
        if obj.created_at is None:
            obj.created_at = now
    if contributions:
        SocialContribution.objects.using(db_alias).bulk_update(
            contributions, ['new_id', 'created_at'], batch_size=BATCH
        )

    # --- SocialDistribution : nouvel UUID (created_at existait déjà) ------
    distributions = list(SocialDistribution.objects.using(db_alias).all())
    mapping = {}
    for obj in distributions:
        obj.new_id = uuid.uuid4()
        mapping[obj.pk] = obj.new_id
    if distributions:
        SocialDistribution.objects.using(db_alias).bulk_update(
            distributions, ['new_id'], batch_size=BATCH
        )

    # --- SocialDistributionLine : nouvel UUID + remappage du FK -----------
    lines = list(SocialDistributionLine.objects.using(db_alias).all())
    for obj in lines:
        obj.new_id = uuid.uuid4()
        obj.new_distribution = mapping[obj.distribution_id]
        if obj.created_at is None:
            obj.created_at = now
    if lines:
        SocialDistributionLine.objects.using(db_alias).bulk_update(
            lines, ['new_id', 'new_distribution', 'created_at'], batch_size=BATCH
        )


def _populate_uuids_reverse(apps, schema_editor):
    # Irréversible par construction (voir en-tête du fichier) : rien à
    # défaire, les anciennes PK entières n'existent plus après cette
    # migration. `migrate clients 0008` échouera explicitement plutôt que de
    # produire des données fausses — c'est le comportement souhaité.
    raise RuntimeError(
        "Migration irréversible : SocialContribution/SocialDistribution/"
        "SocialDistributionLine n'ont plus de PK entière à restaurer."
    )


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0008_social_syncable_step1'),
    ]

    operations = [
        migrations.RunPython(_populate_uuids, _populate_uuids_reverse),

        # --- created_at : retire le null=True temporaire (0008), toutes les
        # lignes existantes sont désormais backfillées par le RunPython.
        migrations.AlterField(
            model_name='socialcontribution',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name="Créé le"),
        ),
        migrations.AlterField(
            model_name='socialdistributionline',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name="Créé le"),
        ),
        # SocialDistribution avait déjà `created_at` (0005), mais sans
        # `verbose_name` — alignement sur `SyncableModel.created_at` pour
        # que l'état de migration corresponde exactement au modèle final.
        migrations.AlterField(
            model_name='socialdistribution',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name="Créé le"),
        ),

        # ─── SocialContribution : PK entière → UUID ─────────────────────
        # Ordre volontaire pour qu'il existe à chaque étape au moins un champ
        # explicitement marqué `primary_key=True` : `RenameField` conserve les
        # attributs du champ renommé (donc `legacy_int_id` reste `pk=True`
        # juste après son renommage) ; si on lui retirait ce statut (via
        # `AlterField`) AVANT que `id` (renommé depuis `new_id`) ne devienne
        # lui-même `pk=True`, l'état de migration se retrouverait sans aucun
        # champ `pk=True` déclaré, et Django réinjecte alors implicitement un
        # second champ auto-incrémenté nommé `id` — collision détectée par
        # SQLite au moment de la reconstruction de table (« duplicate column
        # name: id »), constatée concrètement en testant cette migration sur
        # une base jetable avant de la committer.
        migrations.RenameField(model_name='socialcontribution', old_name='id', new_name='legacy_int_id'),
        migrations.RenameField(model_name='socialcontribution', old_name='new_id', new_name='id'),
        migrations.AlterField(
            model_name='socialcontribution',
            name='id',
            field=models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False, verbose_name="Identifiant unique"),
        ),
        migrations.AlterField(
            model_name='socialcontribution',
            name='legacy_int_id',
            field=models.BigIntegerField(),
        ),
        migrations.RemoveField(model_name='socialcontribution', name='legacy_int_id'),

        # ─── SocialDistribution : PK entière → UUID (même ordre, même raison) ─
        migrations.RenameField(model_name='socialdistribution', old_name='id', new_name='legacy_int_id'),
        migrations.RenameField(model_name='socialdistribution', old_name='new_id', new_name='id'),
        migrations.AlterField(
            model_name='socialdistribution',
            name='id',
            field=models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False, verbose_name="Identifiant unique"),
        ),
        migrations.AlterField(
            model_name='socialdistribution',
            name='legacy_int_id',
            field=models.BigIntegerField(),
        ),
        migrations.RemoveField(model_name='socialdistribution', name='legacy_int_id'),

        # ─── SocialDistributionLine.distribution : FK entier → FK UUID ──
        # (retire d'abord unique_together(distribution, client), sinon
        # impossible de retirer/renommer le champ qu'elle référence)
        migrations.AlterUniqueTogether(name='socialdistributionline', unique_together=set()),
        migrations.RemoveField(model_name='socialdistributionline', name='distribution'),
        migrations.RenameField(model_name='socialdistributionline', old_name='new_distribution', new_name='distribution'),
        migrations.AlterField(
            model_name='socialdistributionline',
            name='distribution',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='lines',
                to='clients.socialdistribution',
                verbose_name='Distribution',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='socialdistributionline',
            unique_together={('distribution', 'client')},
        ),

        # ─── SocialDistributionLine : PK entière → UUID (même ordre, même raison) ─
        migrations.RenameField(model_name='socialdistributionline', old_name='id', new_name='legacy_int_id'),
        migrations.RenameField(model_name='socialdistributionline', old_name='new_id', new_name='id'),
        migrations.AlterField(
            model_name='socialdistributionline',
            name='id',
            field=models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False, verbose_name="Identifiant unique"),
        ),
        migrations.AlterField(
            model_name='socialdistributionline',
            name='legacy_int_id',
            field=models.BigIntegerField(),
        ),
        migrations.RemoveField(model_name='socialdistributionline', name='legacy_int_id'),
    ]
