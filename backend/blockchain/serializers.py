from rest_framework import serializers
from .models import TamperAlert, BlockchainSnapshot


class TamperAlertSerializer(serializers.ModelSerializer):
    node_name = serializers.CharField(source='node.name', read_only=True)
    resolved_by_name = serializers.CharField(source='resolved_by.get_full_name', read_only=True)

    class Meta:
        model  = TamperAlert
        fields = [
            'id', 'node', 'node_name', 'detected_at', 'affected_model',
            'affected_id', 'severity', 'description',
            'is_resolved', 'resolved_by', 'resolved_by_name', 'resolved_at',
        ]
        read_only_fields = ['id', 'detected_at', 'node', 'affected_model', 'affected_id']


class BlockchainSnapshotSerializer(serializers.ModelSerializer):
    node_name = serializers.CharField(source='node.name', read_only=True)

    class Meta:
        model  = BlockchainSnapshot
        fields = [
            'id', 'node', 'node_name', 'snapshot_date',
            'total_entries', 'tampered_entries', 'is_intact',
            'checked_by', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
