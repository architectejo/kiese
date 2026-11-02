from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0002_client_credit_limit'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='cotisation_sociale',
            field=models.DecimalField(
                decimal_places=2, default='3000.00', max_digits=10,
                verbose_name='Cotisation Sociale (FC)'
            ),
        ),
    ]
