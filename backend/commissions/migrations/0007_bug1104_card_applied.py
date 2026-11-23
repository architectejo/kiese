from django.db import migrations, models


def mark_existing(apps, schema_editor):
    # Les commissions deja generees gardent leur carte telle quelle : une regeneration
    # ne leur ajoute jamais la carte (changer card_fee_fc ne modifie pas l'existant).
    apps.get_model('commissions', 'ClientCommission').objects.update(card_applied=True)


class Migration(migrations.Migration):

    dependencies = [
        ('commissions', '0006_bug1014_deduction_manual'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientcommission',
            name='card_applied',
            field=models.BooleanField(default=False, verbose_name='Porte la carte du mois'),
        ),
        migrations.RunPython(mark_existing, migrations.RunPython.noop),
    ]
