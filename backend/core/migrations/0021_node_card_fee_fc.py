"""BUG-417 : carte (frais d'imprimé) par boulangerie ; défauts 2000 / 1000 FC.

Les cotisations déjà enregistrées ne sont PAS modifiées (B2 = 2000, autres = 0
issues des Excel d'août) : seul le défaut du champ change.
"""
from decimal import Decimal

from django.db import migrations, models


def fill_card_fee(apps, schema_editor):
    Node = apps.get_model('core', 'Node')
    Config = apps.get_model('core', 'Config')
    cfg = Config.objects.first()
    fee = Decimal(str(cfg.print_fee)) if cfg is not None and cfg.print_fee else Decimal('0')
    value = fee if fee > 0 else Decimal('1000.00')
    Node.objects.all().update(card_fee_fc=value)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_bug289'),
    ]

    operations = [
        migrations.AddField(
            model_name='node',
            name='card_fee_fc',
            field=models.DecimalField(db_default=Decimal('1000.00'), decimal_places=2, default=Decimal('1000.00'), help_text='Montant FC de la carte retenu par client dans cette boulangerie (remarque.md : défaut 1 000 FC)', max_digits=10, verbose_name="Carte / frais d'imprimé (FC)"),
        ),
        migrations.AlterField(
            model_name='node',
            name='monthly_social_contribution',
            field=models.DecimalField(db_default=Decimal('2000.00'), decimal_places=2, default=Decimal('2000.00'), help_text='Montant FC retenu par client et par mois dans cette boulangerie (remarque.md : défaut 2 000 FC pour une nouvelle boulangerie)', max_digits=10, verbose_name='Cotisation sociale mensuelle (FC)'),
        ),
        migrations.RunPython(fill_card_fee, migrations.RunPython.noop),
    ]
