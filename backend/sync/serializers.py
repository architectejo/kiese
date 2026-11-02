from rest_framework import serializers

from .models import SyncConflictLog, DebtMovement, NodeAuthToken


class SyncConflictLogSerializer(serializers.ModelSerializer):
    node_display = serializers.CharField(source='node.code', read_only=True, default='')

    class Meta:
        model = SyncConflictLog
        fields = [
            'id', 'node', 'node_display', 'model_label', 'object_id',
            'conflict_type', 'detail', 'detected_at', 'resolved_at',
            'resolved_by', 'resolution_note', 'is_resolved',
        ]
        read_only_fields = ['detected_at', 'is_resolved']


class DebtMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = DebtMovement
        fields = [
            'id', 'client', 'invoice', 'amount', 'kind', 'note',
            'node_origin', 'is_synced', 'created_at',
        ]
        read_only_fields = ['created_at']


class NodeAuthTokenSerializer(serializers.ModelSerializer):
    """Ne renvoie jamais le jeton en clair (voir NodeAuthToken.issue_for_node)."""

    class Meta:
        model = NodeAuthToken
        fields = ['id', 'node', 'issued_at', 'issued_by', 'revoked_at', 'last_used_at']
        read_only_fields = fields
