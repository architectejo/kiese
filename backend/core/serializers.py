"""
Core serializers — User, Node, Config, BreadPrice.
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Node, Config, BreadPrice, ExpenseCategory, ActivityLog, SystemNotification, ColisDistribution

User = get_user_model()


class NodeSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source='__str__', read_only=True)

    class Meta:
        model = Node
        fields = [
            'id', 'code', 'name', 'address', 'sac_value_fc', 'is_active',
            'last_sync', 'display_name',
            'team_a_start_time', 'team_a_end_time',
            'team_b_start_time', 'team_b_end_time',
            'handover_time', 'team_rotation_enabled',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


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
            'is_superuser', 'last_login', 'date_joined'
        ]
        read_only_fields = [
            'id', 'last_login', 'date_joined',
            'is_headquarters', 'can_access_all_nodes', 'is_superuser'
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
        user.set_password(password)
        user.save()
        return user


class ConfigSerializer(serializers.ModelSerializer):
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


class BreadPriceSerializer(serializers.ModelSerializer):
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
        fields = ['id', 'code', 'label', 'is_active', 'updated_at']
        read_only_fields = ['updated_at']


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

