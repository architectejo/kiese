from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_alter_node_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='node',
            name='sac_value_fc',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=12, null=True,
                verbose_name='Valeur théorique sac farine (FC)',
                help_text='Valeur FC attendue par sac 50 kg pour cette boulangerie'
            ),
        ),
    ]
