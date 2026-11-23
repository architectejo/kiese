from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('commissions', '0005_bug292_remise_label'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientcommission',
            name='deduction_manual',
            field=models.BooleanField(default=False, verbose_name='Retenue décidée manuellement'),
        ),
    ]
