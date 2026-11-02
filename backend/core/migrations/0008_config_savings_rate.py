from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_data_nodes_b1_b2'),
    ]

    operations = [
        migrations.AddField(
            model_name='config',
            name='savings_rate',
            field=models.DecimalField(
                decimal_places=4, default='0.1580', max_digits=5,
                verbose_name='Taux épargne journalière',
                help_text='Ex: 0.1580 = 15,80% du CA journalier',
            ),
        ),
    ]
