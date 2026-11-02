from django.contrib import admin

from .models import DebtMovement, NodeAuthToken, SyncBatchLog, SyncConflictLog


@admin.register(DebtMovement)
class DebtMovementAdmin(admin.ModelAdmin):
    list_display = ['client', 'kind', 'amount', 'invoice', 'node_origin', 'created_at']
    list_filter = ['kind', 'node_origin']
    search_fields = ['client__code', 'client__first_name', 'client__last_name']
    readonly_fields = ['id', 'node_origin', 'is_synced', 'created_at', 'updated_at']


@admin.register(NodeAuthToken)
class NodeAuthTokenAdmin(admin.ModelAdmin):
    list_display = ['node', 'is_active', 'issued_at', 'issued_by', 'last_used_at', 'revoked_at']
    list_filter = ['node']
    readonly_fields = ['id', 'token_hash', 'issued_at', 'last_used_at']

    def has_change_permission(self, request, obj=None):
        # Un jeton ne se modifie pas : on le révoque et on en émet un
        # nouveau (issue_for_node) — jamais de modification en place.
        return False


@admin.register(SyncBatchLog)
class SyncBatchLogAdmin(admin.ModelAdmin):
    list_display = ['batch_id', 'node', 'status', 'received_at']
    list_filter = ['node', 'status']
    readonly_fields = ['batch_id', 'node', 'status', 'result', 'received_at']

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SyncConflictLog)
class SyncConflictLogAdmin(admin.ModelAdmin):
    list_display = ['model_label', 'object_id', 'conflict_type', 'node', 'detected_at', 'resolved_at']
    list_filter = ['node', 'conflict_type']
    readonly_fields = ['node', 'model_label', 'object_id', 'conflict_type', 'detail', 'detected_at']
