from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0007_breadtransfer_multiline'),
    ]

    operations = [
        migrations.AddField(
            model_name='consumablemovement',
            name='supplier',
            field=models.CharField(
                blank=True,
                choices=[
                    ('MIDEMA', 'MIDEMA'),
                    ('GMK',    'GMK'),
                    ('DVS',    'DVS'),
                    ('LOCAL',  'Achat local'),
                ],
                default='',
                max_length=10,
                verbose_name='Fournisseur',
            ),
        ),
    ]
