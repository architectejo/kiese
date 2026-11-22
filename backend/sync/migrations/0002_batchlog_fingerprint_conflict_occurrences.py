# BUG-726 : idempotence de lot indexée sur (nœud, batch_id) + empreinte du
# contenu ; BUG-723 : compteur d'occurrences d'un conflit de synchronisation.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sync', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='syncbatchlog',
            name='batch_id',
            field=models.UUIDField(db_index=True, verbose_name='Identifiant du lot'),
        ),
        migrations.AddField(
            model_name='syncbatchlog',
            name='fingerprint',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='Empreinte du contenu'),
        ),
        migrations.AlterUniqueTogether(
            name='syncbatchlog',
            unique_together={('node', 'batch_id')},
        ),
        migrations.AddField(
            model_name='syncconflictlog',
            name='occurrences',
            field=models.PositiveIntegerField(default=1, verbose_name='Occurrences'),
        ),
    ]
