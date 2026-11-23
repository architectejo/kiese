"""
Core serializers — User, Node, Config, BreadPrice.
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from .mixins import AsciiDigitsMixin
from .models import Node, Config, BreadPrice, ExpenseCategory, ActivityLog, SystemNotification, ColisDistribution

User = get_user_model()


class NodeSerializer(AsciiDigitsMixin, serializers.ModelSerializer):
    ascii_digit_fields = ('sac_value_fc', 'monthly_social_contribution', 'card_fee_fc')  # BUG-897
    display_name = serializers.CharField(source='__str__', read_only=True)

    class Meta:
        model = Node
        fields = [
            'id', 'code', 'name', 'address', 'sac_value_fc', 'monthly_social_contribution', 'card_fee_fc', 'is_active',
            'last_sync', 'display_name',
            'team_a_start_time', 'team_a_end_time',
            'team_b_start_time', 'team_b_end_time',
            'handover_time', 'team_rotation_enabled', 'block_sales_after_closure',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_monthly_social_contribution(self, value):
        # BUG-314 : jamais négatif (NaN/inf/trop grand sont déjà refusés par DRF).
        if value is not None and value < 0:
            raise serializers.ValidationError("La cotisation sociale mensuelle ne peut pas être négative.")
        return value

    def validate_card_fee_fc(self, value):
        # BUG-417 : montant FC de la carte, jamais négatif.
        if value is not None and value < 0:
            raise serializers.ValidationError("Le montant de la carte ne peut pas être négatif.")
        return value

    def validate_sac_value_fc(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("La valeur du sac ne peut pas être négative.")
        return value


BAKERY_BOUND_ROLES = ('GERANT', 'FACTURIER', 'LIVREUR')


def check_node_required(role, node):
    """BUG-506 : GERANT/FACTURIER/LIVREUR doivent être rattachés à une boulangerie."""
    if role in BAKERY_BOUND_ROLES and node is None:
        raise serializers.ValidationError({
            'node': "Une boulangerie est obligatoire pour le rôle Gérant, Facturier ou Livreur."
        })


class UserSerializer(serializers.ModelSerializer):
    node_display = serializers.StringRelatedField(source='node', read_only=True)
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    team_display = serializers.CharField(source='get_team_display', read_only=True)
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'full_name',
            'email', 'role', 'role_display', 'team', 'team_display',
            'node', 'node_display', 'phone', 'photo',
            'is_active', 'is_headquarters', 'can_access_all_nodes',
            'is_superuser', 'last_login', 'date_joined', 'must_change_password'
        ]
        read_only_fields = [
            'id', 'last_login', 'date_joined',
            'is_headquarters', 'can_access_all_nodes', 'is_superuser',
            'must_change_password',
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False}
        }


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating users (includes password)."""
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'password', 'first_name', 'last_name',
            'email', 'role', 'team', 'node', 'phone'
        ]

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.must_change_password = True  # BUG-284 : mot de passe temporaire
        user.set_password(password)
        user.save()
        return user


class ConfigSerializer(AsciiDigitsMixin, serializers.ModelSerializer):
    ascii_digit_fields = ('best_client_threshold', 'debt_ceiling', 'sac_value_fc', 'print_fee',
                          'default_commission_rate', 'social_deduction_rate', 'annual_bonus_rate')
    class Meta:
        model = Config
        fields = [
            'on_line', 'default_commission_rate', 'debt_ceiling',
            'best_client_threshold', 'social_deduction_rate',
            'print_fee', 'annual_bonus_rate', 'sac_value_fc',
            'allow_backdated_sales',
            'updated_at'
        ]
        read_only_fields = ['updated_at']


class PublicConfigSerializer(serializers.ModelSerializer):
    """BUG-255 : vue anonyme de la configuration (indicateur en ligne seulement)."""
    class Meta:
        model = Config
        fields = ['on_line']
        read_only_fields = ['on_line']


class BreadPriceSerializer(AsciiDigitsMixin, serializers.ModelSerializer):
    ascii_digit_fields = ('unit_price',)
    # BUG-039 : category est désormais un champ texte libre (plus de
    # TextChoices) — category_display n'a plus de get_category_display()
    # généré par Django ; on affiche simplement la catégorie elle-même,
    # comme ExpenseCategorySerializer le fait pour son `code`.
    category_display = serializers.CharField(source='category', read_only=True)

    class Meta:
        model = BreadPrice
        fields = [
            'id', 'category', 'category_display', 'label',
            'unit_price', 'is_active', 'updated_at'
        ]
        read_only_fields = ['updated_at']


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ['id', 'code', 'label', 'is_active', 'scope', 'updated_at']
        read_only_fields = ['updated_at']


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = ActivityLog
        fields = ['id', 'user', 'user_name', 'user_display', 'action', 'description', 'node_origin', 'created_at']
        read_only_fields = ['id', 'created_at']


class SystemNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemNotification
        fields = ['id', 'title', 'message', 'severity', 'is_read', 'node_origin', 'created_at']
        read_only_fields = ['id', 'created_at']


class ColisDistributionSerializer(serializers.ModelSerializer):
    node_display = serializers.StringRelatedField(source='node', read_only=True)

    class Meta:
        model  = ColisDistribution
        fields = [
            'id', 'node', 'node_display', 'year', 'beneficiary_label',
            'rice_sacks', 'rice_value', 'meat_kg', 'meat_value',
            'cash_amount', 'total_value', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'total_value', 'created_at']

