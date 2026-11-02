from django.contrib import admin
from .models import ProductionSession, ConsumableType, ConsumableStock, ConsumableMovement, BreadTransfer, BreadDisposal


@admin.register(ConsumableType)
class ConsumableTypeAdmin(admin.ModelAdmin):
    list_display = ['code', 'label', 'unit', 'is_active']
    list_filter = ['is_active']


@admin.register(ProductionSession)
class ProductionSessionAdmin(admin.ModelAdmin):
    list_display  = ['node', 'team', 'date', 'flour_sacks_used', 'total_breads', 'theoretical_yield', 'yield_gap', 'is_closed']
    list_filter   = ['node', 'team', 'is_closed']
    readonly_fields = ['id', 'total_breads', 'theoretical_yield', 'yield_gap', 'node_origin', 'is_synced', 'created_at', 'updated_at']
    ordering      = ['-date', 'node__code']


@admin.register(ConsumableStock)
class ConsumableStockAdmin(admin.ModelAdmin):
    list_display = ['node', 'consumable_type', 'quantity', 'unit']
    list_filter  = ['node', 'consumable_type']
    readonly_fields = ['id', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(ConsumableMovement)
class ConsumableMovementAdmin(admin.ModelAdmin):
    list_display = ['node', 'movement_type', 'stock', 'quantity', 'recorded_by', 'created_at']
    list_filter  = ['movement_type', 'node']
    readonly_fields = ['id', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(BreadTransfer)
class BreadTransferAdmin(admin.ModelAdmin):
    list_display = ['from_node', 'to_node', 'bread_price', 'quantity_sent', 'quantity_received', 'transfer_status', 'created_at']
    list_filter  = ['transfer_status', 'from_node', 'to_node']
    readonly_fields = ['id', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(BreadDisposal)
class BreadDisposalAdmin(admin.ModelAdmin):
    list_display = ['node', 'session', 'bread_price', 'disposal_type', 'quantity', 'total_value']
    list_filter  = ['disposal_type', 'node']
    readonly_fields = ['id', 'total_value', 'node_origin', 'is_synced', 'created_at', 'updated_at']
