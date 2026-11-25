import datetime

from django.db import migrations, models


def enable_rotation_everywhere(apps, schema_editor):
    """Q-017 (réponse client) : toutes les boulangeries (hors SIEGE, nœud technique) passent en
    rotation de 24 h ; heure de clôture/relève 12:00 si elle est absente (colonne non nulle,
    la garde est défensive)."""
    Node = apps.get_model('core', 'Node')
    Node.objects.exclude(code='SIEGE').update(team_rotation_enabled=True)
    Node.objects.exclude(code='SIEGE').filter(handover_time__isnull=True).update(
        handover_time=datetime.time(12, 0))


def noop_reverse(apps, schema_editor):
    """Non réversible de façon sûre : on ne sait plus quels nœuds étaient en rotation avant."""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_node_default_commission_rate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='node',
            name='team_rotation_enabled',
            field=models.BooleanField(db_default=True, default=True, help_text="BUG-161 : si activé, la facturation est bloquée tant que l'équipe de service de la journée de travail n'est pas désignée. Q-017 (réponse client 2026-11-24) : ACTIVÉ par défaut, toutes les boulangeries sont en rotation de 24 h (relève 12:00 par défaut).", verbose_name="Rotation d'équipes active"),
        ),
        migrations.RunPython(enable_rotation_everywhere, noop_reverse),
    ]
