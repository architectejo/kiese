from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers
from core.mixins import AsciiDigitsMixin
from .models import Client, SocialContribution, SocialDistribution, SocialDistributionLine


MAX_CREDIT_LIMIT = Decimal('10000000')
MAX_COMMISSION_RATE = Decimal('0.30')
MAX_PHOTO_BYTES = 5 * 1024 * 1024


class ClientBoundsMixin(AsciiDigitsMixin):
    """BUG-250/257/258 : bornes communes à la création et à la modification."""
    MAX_CREDIT_LIMIT = MAX_CREDIT_LIMIT
    MAX_COMMISSION_RATE = MAX_COMMISSION_RATE
    ascii_digit_fields = ('credit_limit', 'commission_rate', 'cotisation_sociale')

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
        if value is not None and value < 0:
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
    effective_cotisation_sociale = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model  = Client
        fields = [
            'id', 'code', 'first_name', 'last_name', 'full_name',
            'phone', 'address', 'photo',
            'node', 'node_display',
            'cotisation_sociale', 'effective_cotisation_sociale', 'commission_rate', 'credit_limit', 'current_debt', 'total_breads_received',
            'category', 'category_display', 'client_type', 'client_type_display', 'is_active', 'notes',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'code', 'full_name', 'node_display', 'category_display', 'effective_cotisation_sociale',
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


class SocialContributionSerializer(AsciiDigitsMixin, serializers.ModelSerializer):
    ascii_digit_fields = '__numeric__'  # BUG-915
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

    def validate_year(self, value):
        # BUG-946 : mêmes bornes que le push de synchronisation (2000-2200).
        if value < 2000 or value > 2200:
            raise serializers.ValidationError("Année invalide : une année entre 2000 et 2200 est attendue.")
        return value

    def validate(self, attrs):
        inst = self.instance
        if inst is not None:
            # BUG-948 : la boulangerie d'une cotisation est figée et son client doit en relever.
            if 'node' in attrs and attrs['node'].pk != inst.node_id:
                raise serializers.ValidationError(
                    {'node': "La boulangerie d'une cotisation ne peut pas être modifiée."})
            client = attrs.get('client', inst.client)
            if client.node_id != inst.node_id:
                raise serializers.ValidationError(
                    {'client': "Ce client n'appartient pas à la boulangerie de la cotisation."})
        # BUG-947 : date de paiement cohérente avec l'état « payé » (comme toggle_paid).
        if 'is_paid' in attrs:
            if attrs['is_paid']:
                if inst is None or not inst.is_paid or inst.paid_at is None:
                    attrs['paid_at'] = timezone.now()
            else:
                attrs['paid_at'] = None
        return attrs

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


class SocialDistributionLineSerializer(AsciiDigitsMixin, serializers.ModelSerializer):
    ascii_digit_fields = '__numeric__'  # BUG-915
    client_display = serializers.SerializerMethodField()

    class Meta:
        model  = SocialDistributionLine
        fields = ['id', 'distribution', 'client', 'client_display', 'indice', 'total_social', 'remise', 'merite', 'total_payer', 'position', 'form']
        read_only_fields = ['id', 'remise', 'total_payer']

    def validate_indice(self, value):
        # BUG-740 : un indice = nombre de mois cotisés dans l'année (0 à 12).
        if value < 0 or value > 12:
            raise serializers.ValidationError("L'indice doit être compris entre 0 et 12 (mois cotisés).")
        return value

    def validate_merite(self, value):
        # BUG-740 : le mérite est un bonus, jamais négatif.
        if value < 0:
            raise serializers.ValidationError("Le mérite ne peut pas être négatif.")
        return value

    def validate_total_social(self, value):
        if value < 0:
            raise serializers.ValidationError("Le total des cotisations ne peut pas être négatif.")
        return value

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
        # BUG-747 : les montants calculés (remise, total à recevoir) doivent tenir
        # dans les colonnes (max_digits=10) : 400 au lieu d'un 500.
        if distribution is not None:
            inst = self.instance
            indice = attrs.get('indice', inst.indice if inst else 0)
            total_social = attrs.get('total_social', inst.total_social if inst else Decimal('0'))
            merite = attrs.get('merite', inst.merite if inst else Decimal('0'))
            limit = Decimal('10') ** 8
            remise = indice * Decimal(str(distribution.tarif))
            if remise >= limit:
                raise serializers.ValidationError(
                    {'indice': "La remise (indice × tarif) dépasse le maximum autorisé (99 999 999,99 FC)."})
            if Decimal(str(total_social)) + remise + Decimal(str(merite)) >= limit:
                raise serializers.ValidationError(
                    {'detail': "Le total à recevoir (cotisations + remise + mérite) dépasse le maximum autorisé (99 999 999,99 FC)."})
        return attrs

    def get_client_display(self, obj):
        return f"[{obj.client.code}] {obj.client.full_name}"


class SocialDistributionSerializer(AsciiDigitsMixin, serializers.ModelSerializer):
    ascii_digit_fields = '__numeric__'  # BUG-915
    node_display = serializers.StringRelatedField(source='node', read_only=True)
    lines        = SocialDistributionLineSerializer(many=True, read_only=True)

    class Meta:
        model  = SocialDistribution
        fields = ['id', 'node', 'node_display', 'year', 'tarif', 'is_closed', 'lines', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_tarif(self, value):
        if value < 0:
            raise serializers.ValidationError("Le tarif ne peut pas être négatif.")
        # BUG-295 : le tarif (fixé par la direction, par an et par boulangerie)
        # d'une distribution clôturée est figé : il détermine les remises versées.
        if self.instance is not None and self.instance.is_closed and value != self.instance.tarif:
            raise serializers.ValidationError("Distribution clôturée : le tarif ne peut plus être modifié.")
        # BUG-747 : un nouveau tarif recalcule les lignes existantes, sans dépasser la colonne.
        if self.instance is not None:
            for line in self.instance.lines.all():
                if line.indice * value + line.total_social + line.merite >= Decimal('10') ** 8:
                    raise serializers.ValidationError(
                        "Ce tarif ferait dépasser le maximum autorisé (99 999 999,99 FC) sur au moins une ligne.")
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
