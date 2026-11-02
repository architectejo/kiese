from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashclosure',
            name='is_rejected',
            field=models.BooleanField(default=False, verbose_name='Infirmé'),
        ),
        migrations.AddField(
            model_name='cashclosure',
            name='rejection_reason',
            field=models.TextField(blank=True, default='', verbose_name='Motif de rejet'),
        ),
    ]
