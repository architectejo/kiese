# BUG-017 (docs/qa/REGISTRE_BUGS.md) — ajout du compteur persistant de codes
# client (voir clients/models.py::ClientCodeSequence et _generate_client_code).
#
# Écrite à la main (plutôt que générée par `makemigrations`) pour n'inclure
# que ce changement de schéma : une dérive préexistante et non liée à ce
# ticket existe entre `clients/migrations/0005_social.py` (unique_together
# exprimé en `AddConstraint` + `id` en `AutoField` explicite) et l'état
# actuel des modèles (`Meta.unique_together` + `DEFAULT_AUTO_FIELD =
# BigAutoField`, sans champ `id` explicite) — elle fait que `makemigrations`
# propose en plus de retirer/ré-ajouter les contraintes uniques de
# SocialContribution/SocialDistribution/SocialDistributionLine et de changer
# leur `id` en BigAutoField. Cette dérive est sans rapport avec BUG-017 et
# n'est pas corrigée ici (hors périmètre de ce ticket) ; elle est signalée
# au coordinateur dans le rapport d'agent.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0005_social'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClientCodeSequence',
            fields=[
                ('node_code', models.CharField(max_length=10, primary_key=True, serialize=False)),
                ('last_number', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Séquence Code Client',
                'verbose_name_plural': 'Séquences Codes Clients',
            },
        ),
    ]
