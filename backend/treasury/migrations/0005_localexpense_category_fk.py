# Converts LocalExpense.category from a hardcoded CharField(choices=...)
# to a ForeignKey('core.ExpenseCategory') — safe 4-step pattern:
# add nullable FK -> backfill via RunPython -> drop old field -> rename + tighten.

import django.db.models.deletion
from django.db import migrations, models


def backfill_category_fk(apps, schema_editor):
    LocalExpense = apps.get_model('treasury', 'LocalExpense')
    ExpenseCategory = apps.get_model('core', 'ExpenseCategory')
    fallback, _ = ExpenseCategory.objects.get_or_create(code='MISC', defaults={'label': 'Frais Divers'})
    for expense in LocalExpense.objects.all():
        try:
            category = ExpenseCategory.objects.get(code=expense.category)
        except ExpenseCategory.DoesNotExist:
            category = fallback
        expense.category_new = category
        expense.save(update_fields=['category_new'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0004_dailysavings'),
        ('core', '0010_expensecategory'),
    ]

    operations = [
        migrations.AddField(
            model_name='localexpense',
            name='category_new',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='local_expenses_new', to='core.expensecategory',
            ),
        ),
        migrations.RunPython(backfill_category_fk, noop_reverse),
        migrations.RemoveField(
            model_name='localexpense',
            name='category',
        ),
        migrations.RenameField(
            model_name='localexpense',
            old_name='category_new',
            new_name='category',
        ),
        migrations.AlterField(
            model_name='localexpense',
            name='category',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='local_expenses', to='core.expensecategory',
                verbose_name='Catégorie',
            ),
        ),
    ]
