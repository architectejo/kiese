# Fictional "Siège" (headquarters) node used to attribute HQ-level
# cashbook movements (bordereaux de versement) that aren't tied to a
# real bakery. Kept inactive so it never appears in operational
# bakery pickers (sales/production/client assignment).

from django.db import migrations


def create_siege(apps, schema_editor):
    Node = apps.get_model('core', 'Node')
    Node.objects.get_or_create(
        code='SIEGE',
        defaults={'name': 'Direction Générale — Siège', 'is_active': False},
    )


def reverse_siege(apps, schema_editor):
    Node = apps.get_model('core', 'Node')
    Node.objects.filter(code='SIEGE').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_expensecategory'),
    ]

    operations = [
        migrations.RunPython(create_siege, reverse_code=reverse_siege),
    ]
