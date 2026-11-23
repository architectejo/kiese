from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sync', '0004_transfermirror'),
    ]

    operations = [
        migrations.AddField(
            model_name='transfermirror',
            name='peak',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
