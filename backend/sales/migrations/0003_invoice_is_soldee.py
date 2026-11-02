from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0002_invoice_client_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='is_soldee',
            field=models.BooleanField(default=False, verbose_name='Vente Soldée'),
        ),
    ]
