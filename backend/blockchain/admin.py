from django.contrib import admin
from .models import TamperAlert, BlockchainSnapshot


@admin.register(TamperAlert)
class TamperAlertAdmin(admin.ModelAdmin):
    list_display  = ['node', 'detected_at', 'affected_model', 'severity', 'is_resolved', 'resolved_by']
    list_filter   = ['node', 'severity', 'is_resolved']
    readonly_fields = ['id', 'detected_at', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(BlockchainSnapshot)
class BlockchainSnapshotAdmin(admin.ModelAdmin):
    list_display  = ['node', 'snapshot_date', 'total_entries', 'tampered_entries', 'is_intact', 'checked_by']
    list_filter   = ['node', 'is_intact', 'snapshot_date']
    readonly_fields = ['id', 'node_origin', 'is_synced', 'created_at', 'updated_at']
