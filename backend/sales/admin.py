from django.contrib import admin
from .models import Invoice, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model  = InvoiceLine
    extra  = 0
    readonly_fields = ['unit_price', 'line_total']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display   = ['receipt_number', 'node', 'client', 'status', 'order_total', 'payment_amount', 'debt_after', 'invoice_date']
    list_filter    = ['status', 'payment_type', 'node', 'invoice_date']
    search_fields  = ['receipt_number', 'client__first_name', 'client__last_name']
    readonly_fields = ['id', 'receipt_number', 'order_total', 'debt_after', 'delivered_at', 'node_origin', 'is_synced', 'created_at', 'updated_at']
    inlines        = [InvoiceLineInline]
    ordering       = ['-created_at']
