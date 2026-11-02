from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0005_add_unit_price_to_consumable_movement'),
    ]

    operations = [
        migrations.AddField(
            model_name='productionsession',
            name='notes',
            field=models.TextField(blank=True, default='', verbose_name='Commentaires'),
        ),
    ]
