# Seeds additional ExpenseCategory rows from the client's official Plan
# Comptable (cadre_comptable.md). Per the client's clarification, items like
# la chaîne bois détaillée, les remboursements de crédits, le CAPEX et le
# carburant de mission ne sont PAS de nouveaux modules — ce sont de simples
# libellés de sortie de caisse à enregistrer dans le Livre de Caisse /
# Dépenses Locales, avec totalisation automatique (déjà supportée par
# ExpenseCategory + LocalExpense). Ferme Agricole et Pâtisserie sont hors
# périmètre, mais la subvention envoyée à la Ferme reste une sortie de
# caisse côté boulangerie, donc gardée.

from django.db import migrations


SEED_CATEGORIES = [
    ('WOOD_LABOR',    'Bois — Main-d\'œuvre Coupe'),
    ('WOOD_SAW_FUEL', 'Bois — Carburant & Maintenance Scies/Tronçonneuses'),
    ('WOOD_TRUCK',    'Bois — Carburant & Maintenance Camions'),
    ('WOOD_CONVOY',   'Bois — Primes Convoyeurs'),
    ('LOAN_BANK',     'Remboursement Crédit Bancaire'),
    ('LOAN_COOPEC',   'Remboursement Crédit COOPEC'),
    ('LOAN_THIRD',    'Remboursement Crédit Tiers'),
    ('CAPEX_BUILD',   'Investissement — Construction'),
    ('CAPEX_EQUIP',   'Investissement — Équipement'),
    ('FUEL_MISSION',  'Carburant — Mission Véhicule'),
    ('FARM_SUBSIDY',  'Subvention / Avance Ferme Agricole'),
    ('THEFT',         'Vol & Détournement'),
    ('RENT',          'Loyers'),
    ('FEES',          'Honoraires (Avocat, Conseil, Informatique)'),
    ('TAXES',         'Taxes & Redevances (DGI, INSS, INPP...)'),
]


def seed_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model('core', 'ExpenseCategory')
    for code, label in SEED_CATEGORIES:
        ExpenseCategory.objects.get_or_create(code=code, defaults={'label': label})


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_data_node_siege'),
    ]

    operations = [
        migrations.RunPython(seed_categories, noop_reverse),
    ]
