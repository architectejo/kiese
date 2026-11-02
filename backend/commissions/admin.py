from django.contrib import admin
from .models import CommissionPeriod, ClientCommission


@admin.register(CommissionPeriod)
class CommissionPeriodAdmin(admin.ModelAdmin):
    list_display  = ['node', 'month', 'year', 'is_closed', 'closed_at']
    list_filter   = ['node', 'is_closed', 'year']
    readonly_fields = ['id', 'closed_at', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(ClientCommission)
class ClientCommissionAdmin(admin.ModelAdmin):
    list_display  = ['client', 'period', 'commission_gross', 'total_deductions', 'annual_bonus', 'net_payable', 'is_paid']
    list_filter   = ['is_paid', 'annual_bonus_incorporated', 'period__node']
    search_fields = ['client__first_name', 'client__last_name', 'client__code']
    readonly_fields = ['id', 'commission_gross', 'annual_bonus', 'total_deductions', 'net_payable', 'paid_at', 'node_origin', 'is_synced', 'created_at', 'updated_at']
