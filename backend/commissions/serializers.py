from decimal import Decimal

from rest_framework import serializers
from .models import CommissionPeriod, ClientCommission


class CommissionPeriodSerializer(serializers.ModelSerializer):
    node_display = serializers.StringRelatedField(source='node', read_only=True)

    class Meta:
        model  = CommissionPeriod
        fields = [
            'id', 'node', 'node_display', 'month', 'year',
            'is_closed', 'closed_at',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_closed', 'closed_at', 'node_origin', 'is_synced', 'created_at', 'updated_at']


class ClientCommissionSerializer(serializers.ModelSerializer):
    client_display = serializers.StringRelatedField(source='client', read_only=True)
    period_display = serializers.StringRelatedField(source='period', read_only=True)
    node           = serializers.PrimaryKeyRelatedField(source='period.node', read_only=True)
    node_display   = serializers.StringRelatedField(source='period.node', read_only=True)

    class Meta:
        model  = ClientCommission
        fields = [
            'id', 'period', 'period_display', 'node', 'node_display', 'client', 'client_display',
            'total_breads', 'order_value', 'commission_rate',
            'commission_gross',
            'deduction_debt', 'deduction_social', 'deduction_prints', 'deduction_other',
            'deduction_carte', 'deduction_remise', 'total_deductions',
            'carried_debt_in',
            'net_ordi', 'net_carte',
            'annual_bonus', 'annual_bonus_incorporated',
            'net_payable',
            'manuel_adjustment', 'manuel_notes',
            'is_paid', 'paid_at', 'paid_by', 'notes',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'commission_gross', 'annual_bonus',
            'deduction_carte', 'deduction_remise', 'total_deductions',
            'carried_debt_in',
            'net_ordi', 'net_carte', 'net_payable',
            'is_paid', 'paid_at', 'paid_by', 'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]

    MONEY_FIELDS = ('order_value', 'deduction_debt', 'deduction_social', 'deduction_prints', 'deduction_other')

    def validate(self, attrs):
        # BUG-262 : montants >= 0 ; taux dans [0 ; 0,30] (CLAUDE.md §5.3).
        errors = {}
        for f in self.MONEY_FIELDS:
            if f in attrs and attrs[f] is not None and attrs[f] < 0:
                errors[f] = "Le montant ne peut pas être négatif."
        rate = attrs.get('commission_rate')
        if rate is not None and not (0 <= rate <= Decimal('0.30')):
            errors['commission_rate'] = "Le taux de commission doit être compris entre 0 et 0,30."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
