from django.db import migrations


def create_b1_b2(apps, schema_editor):
    Node = apps.get_model('core', 'Node')
    Node.objects.get_or_create(
        code='B1',
        defaults={'name': 'KUMBI', 'is_active': True},
    )
    Node.objects.get_or_create(
        code='B2',
        defaults={'name': 'MPETE', 'is_active': True},
    )


def reverse_b1_b2(apps, schema_editor):
    Node = apps.get_model('core', 'Node')
    Node.objects.filter(code__in=['B1', 'B2']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_node_sac_value_fc'),
    ]

    operations = [
        migrations.RunPython(create_b1_b2, reverse_code=reverse_b1_b2),
    ]
