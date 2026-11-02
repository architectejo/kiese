from django.contrib import admin
from .models import (
    LocalExpense, FacturierReport, CashClosure, CashbookEntry,
    DisbursementVoucher, DirectionCashCount,
)


@admin.register(LocalExpense)
class LocalExpenseAdmin(admin.ModelAdmin):
    list_display  = ['node', 'date', 'description', 'category', 'amount']
    list_filter   = ['node', 'category', 'date']
    readonly_fields = ['id', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(FacturierReport)
class FacturierReportAdmin(admin.ModelAdmin):
    list_display  = ['node', 'facturier', 'team', 'date', 'total_cash_sales', 'total_credit_sales', 'is_validated']
    list_filter   = ['node', 'team', 'is_validated']
    readonly_fields = ['id', 'validated_at', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(CashClosure)
class CashClosureAdmin(admin.ModelAdmin):
    list_display  = ['node', 'date', 'total_entries', 'total_expenses', 'net_cash', 'physical_cash_total', 'cash_gap', 'is_validated']
    list_filter   = ['node', 'is_validated']
    readonly_fields = ['id', 'net_cash', 'physical_cash_total', 'cash_gap', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(CashbookEntry)
class CashbookEntryAdmin(admin.ModelAdmin):
    list_display  = ['piece_number', 'node', 'date', 'label', 'entry_amount', 'exit_amount', 'running_balance', 'is_tampered']
    list_filter   = ['node', 'is_tampered']
    readonly_fields = ['id', 'running_balance', 'block_hash', 'previous_hash', 'is_tampered', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(DisbursementVoucher)
class DisbursementVoucherAdmin(admin.ModelAdmin):
    list_display  = ['piece_number', 'date', 'motif', 'beneficiary', 'physical_cash_total', 'created_by']
    list_filter   = ['date']
    readonly_fields = ['id', 'physical_cash_total', 'piece_number', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(DirectionCashCount)
class DirectionCashCountAdmin(admin.ModelAdmin):
    """BUG-119 : comptage physique de billets au niveau Direction."""
    list_display  = ['date', 'physical_cash_total', 'theoretical_balance', 'cash_gap', 'counted_by']
    list_filter   = ['date']
    readonly_fields = ['id', 'physical_cash_total', 'theoretical_balance', 'cash_gap', 'reference_entry', 'created_at']
