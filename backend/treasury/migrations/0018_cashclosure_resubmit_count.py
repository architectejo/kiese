from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0017_cashbook_head_anchor'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashclosure',
            name='resubmit_count',
            field=models.PositiveIntegerField(default=0, verbose_name='Nombre de resoumissions'),
        ),
    ]
