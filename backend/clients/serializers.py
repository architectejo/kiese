from rest_framework import serializers
from .models import Client, SocialContribution, SocialDistribution, SocialDistributionLine


class ClientSerializer(serializers.ModelSerializer):
    full_name     = serializers.CharField(read_only=True)
    node_display  = serializers.StringRelatedField(source='node', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    client_type_display = serializers.CharField(source='get_client_type_display', read_only=True)

    class Meta:
        model  = Client
        fields = [
            'id', 'code', 'first_name', 'last_name', 'full_name',
            'phone', 'address', 'photo',
            'node', 'node_display',
            'cotisation_sociale', 'commission_rate', 'credit_limit', 'current_debt', 'total_breads_received',
            'category', 'category_display', 'client_type', 'client_type_display', 'is_active', 'notes',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'code', 'full_name', 'node_display', 'category_display',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]


class ClientCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Client
        fields = [
            'id', 'code',
            'first_name', 'last_name', 'phone', 'address', 'photo',
            'node', 'cotisation_sociale', 'commission_rate', 'credit_limit', 'client_type', 'is_active', 'notes',
        ]
        read_only_fields = ['id', 'code']
        extra_kwargs = {'node': {'required': False}}


class SocialContributionSerializer(serializers.ModelSerializer):
    client_display = serializers.SerializerMethodField()

    class Meta:
        model  = SocialContribution
        fields = ['id', 'client', 'client_display', 'node', 'month', 'year', 'amount', 'is_paid', 'paid_at']
        read_only_fields = ['id', 'paid_at']

    def get_client_display(self, obj):
        return f"[{obj.client.code}] {obj.client.full_name}"


class SocialDistributionLineSerializer(serializers.ModelSerializer):
    client_display = serializers.SerializerMethodField()

    class Meta:
        model  = SocialDistributionLine
        fields = ['id', 'client', 'client_display', 'indice', 'total_social', 'remise', 'merite', 'total_payer', 'position', 'form']
        read_only_fields = ['id', 'remise', 'total_payer']

    def get_client_display(self, obj):
        return f"[{obj.client.code}] {obj.client.full_name}"


class SocialDistributionSerializer(serializers.ModelSerializer):
    node_display = serializers.StringRelatedField(source='node', read_only=True)
    lines        = SocialDistributionLineSerializer(many=True, read_only=True)

    class Meta:
        model  = SocialDistribution
        fields = ['id', 'node', 'node_display', 'year', 'tarif', 'is_closed', 'lines', 'created_at']
        read_only_fields = ['id', 'created_at']
