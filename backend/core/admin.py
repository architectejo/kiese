"""
Core admin configuration.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Node, Config, BreadPrice, ExpenseCategory


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'get_full_name', 'role', 'team', 'node', 'is_active']
    list_filter = ['role', 'team', 'node', 'is_active']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('ETS. KIESE', {
            'fields': ('role', 'team', 'node', 'phone', 'photo')
        }),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('ETS. KIESE', {
            'fields': ('role', 'team', 'node', 'phone')
        }),
    )


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_active', 'last_sync']
    list_filter = ['is_active']


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'default_commission_rate', 'debt_ceiling', 'updated_at']

    def has_add_permission(self, request):
        """Prevent creation of additional Config instances."""
        return not Config.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BreadPrice)
class BreadPriceAdmin(admin.ModelAdmin):
    list_display = ['category', 'label', 'unit_price', 'is_active']
    list_filter = ['is_active']


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'label', 'is_active']
    list_filter = ['is_active']
