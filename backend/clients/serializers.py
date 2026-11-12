from decimal import Decimal

from rest_framework import serializers
from .models import Client, SocialContribution, SocialDistribution, SocialDistributionLine


MAX_CREDIT_LIMIT = Decimal('10000000')
MAX_COMMISSION_RATE = Decimal('0.30')
MAX_PHOTO_BYTES = 5 * 1024 * 1024


class ClientBoundsMixin:
    """BUG-250/257/258 : bornes communes à la création et à la modification."""
    MAX_CREDIT_LIMIT = MAX_CREDIT_LIMIT
    MAX_COMMISSION_RATE = MAX_COMMISSION_RATE

    def validate_credit_limit(self, value):
        if value < 0 or value > self.MAX_CREDIT_LIMIT:
            raise serializers.ValidationError(
                "Le plafond de crédit doit être compris entre 0 et 10 000 000 FC.")
        return value

    def validate_commission_rate(self, value):
        if value < 0 or value > self.MAX_COMMISSION_RATE:
            raise serializers.ValidationError(
                "Le taux de commission doit être compris entre 0 et 0,30.")
        return value

    def validate_cotisation_sociale(self, value):
        if value < 0:
            raise serializers.ValidationError("La cotisation sociale ne peut pas être négative.")
        return value

    def validate_photo(self, value):
        if value is not None and getattr(value, 'size', 0) > MAX_PHOTO_BYTES:
            raise serializers.ValidationError("La photo ne doit pas dépasser 5 Mo.")
        return value


class ClientSerializer(ClientBoundsMixin, serializers.ModelSerializer):
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
            # BUG-259 : BP et total pains ne bougent que par les mécanismes métier.
            'current_debt', 'total_breads_received',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]


class ClientCreateSerializer(ClientBoundsMixin, serializers.ModelSerializer):
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

    def validate_month(self, value):
        if not 1 <= value <= 12:
            raise serializers.ValidationError("Le mois doit être compris entre 1 et 12.")
        return value

    def validate_amount(self, value):
        if value < 0:
            raise serializers.ValidationError("Le montant ne peut pas être négatif.")
        return value

    def validate_client(self, client):
        # BUG-249 : un non-siège ne rattache que les clients de son nœud.
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and not user.can_access_all_nodes:
            if client.node_id != user.node_id:
                raise serializers.ValidationError("Ce client n'appartient pas à votre boulangerie.")
        return client

    def get_client_display(self, obj):
        return f"[{obj.client.code}] {obj.client.full_name}"


class SocialDistributionLineSerializer(serializers.ModelSerializer):
    client_display = serializers.SerializerMethodField()

    class Meta:
        model  = SocialDistributionLine
        fields = ['id', 'distribution', 'client', 'client_display', 'indice', 'total_social', 'remise', 'merite', 'total_payer', 'position', 'form']
        read_only_fields = ['id', 'remise', 'total_payer']

    def validate(self, attrs):
        # BUG-254 : `distribution` est désormais exposé ; 400 propre au lieu d'un 500.
        distribution = attrs.get('distribution') or (self.instance.distribution if self.instance else None)
        client = attrs.get('client') or (self.instance.client if self.instance else None)
        if self.instance and 'distribution' in attrs and attrs['distribution'] != self.instance.distribution:
            raise serializers.ValidationError({'distribution': "La distribution d'une ligne ne peut pas être modifiée."})
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if distribution is not None and user is not None and user.is_authenticated \
                and not user.can_access_all_nodes and distribution.node_id != user.node_id:
            raise serializers.ValidationError({'distribution': "Cette distribution n'appartient pas à votre boulangerie."})
        if distribution is not None and client is not None and client.node_id != distribution.node_id:
            raise serializers.ValidationError({'client': "Ce client n'appartient pas à la boulangerie de la distribution."})
        return attrs

    def get_client_display(self, obj):
        return f"[{obj.client.code}] {obj.client.full_name}"


class SocialDistributionSerializer(serializers.ModelSerializer):
    node_display = serializers.StringRelatedField(source='node', read_only=True)
    lines        = SocialDistributionLineSerializer(many=True, read_only=True)

    class Meta:
        model  = SocialDistribution
        fields = ['id', 'node', 'node_display', 'year', 'tarif', 'is_closed', 'lines', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_tarif(self, value):
        if value < 0:
            raise serializers.ValidationError("Le tarif ne peut pas être négatif.")
        return value

    def validate_year(self, value):
        if value < 2000 or value > 2200:
            raise serializers.ValidationError("Année invalide.")
        return value

    def validate_is_closed(self, value):
        # BUG-260 : la clôture est irréversible.
        if self.instance is not None and self.instance.is_closed and not value:
            raise serializers.ValidationError("Une distribution clôturée ne peut pas être rouverte.")
        return value
