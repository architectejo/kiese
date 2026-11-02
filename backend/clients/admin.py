from django.contrib import admin
from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display  = ['code', 'full_name', 'node', 'commission_rate', 'current_debt', 'category', 'is_active']
    list_filter   = ['node', 'category', 'is_active']
    search_fields = ['code', 'first_name', 'last_name', 'phone']
    readonly_fields = ['id', 'code', 'node_origin', 'is_synced', 'created_at', 'updated_at']
    ordering      = ['node__code', 'last_name']
    fieldsets = (
        ('Identité', {'fields': ('id', 'code', 'first_name', 'last_name', 'phone', 'address', 'photo')}),
        ('Boulangerie', {'fields': ('node',)}),
        ('Financier', {'fields': ('commission_rate', 'current_debt', 'total_breads_received', 'category')}),
        ('Statut', {'fields': ('is_active', 'notes')}),
        ('Système', {'fields': ('node_origin', 'is_synced', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
