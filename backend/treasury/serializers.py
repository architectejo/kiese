from rest_framework import serializers
from .models import (
    LocalExpense, FacturierReport, CashClosure, CashbookEntry, JournalEntry,
    DailySavings, DisbursementVoucher, DirectionCashCount,
)
from core.models import Node


class LocalExpenseSerializer(serializers.ModelSerializer):
    node_display     = serializers.StringRelatedField(source='node', read_only=True)
    category_display = serializers.CharField(source='category.label', read_only=True)

    class Meta:
        model  = LocalExpense
        fields = [
            'id', 'node', 'node_display', 'gerant', 'description',
            'amount', 'category', 'category_display', 'date',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'node', 'gerant', 'node_origin', 'is_synced', 'created_at', 'updated_at']


class FacturierReportSerializer(serializers.ModelSerializer):
    node_display      = serializers.StringRelatedField(source='node', read_only=True)
    facturier_display = serializers.SerializerMethodField()

    class Meta:
        model  = FacturierReport
        fields = [
            'id', 'node', 'node_display', 'facturier', 'facturier_display',
            'team', 'date',
            'total_cash_sales', 'total_credit_sales', 'theoretical_cash',
            # BUG-033 (remarque.md l.142) : détail par catégorie de pain.
            'sacks_consumed', 'breads_produced_by_category',
            'breads_sold_by_category', 'sacks_value_gap',
            'is_validated', 'validated_by', 'validated_at',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'validated_at', 'node_origin', 'is_synced', 'created_at', 'updated_at',
            'sacks_consumed', 'breads_produced_by_category',
            'breads_sold_by_category', 'sacks_value_gap',
        ]

    def get_facturier_display(self, obj):
        return obj.facturier.get_full_name() if obj.facturier else None


class CashClosureSerializer(serializers.ModelSerializer):
    node_display        = serializers.StringRelatedField(source='node', read_only=True)
    gerant_display      = serializers.SerializerMethodField()
    has_cashbook_entry  = serializers.SerializerMethodField()

    class Meta:
        model  = CashClosure
        fields = [
            'id', 'node', 'node_display', 'gerant', 'gerant_display', 'date',
            'total_entries', 'total_expenses', 'net_cash',
            'bills_20000', 'bills_10000', 'bills_5000', 'bills_1000',
            'bills_500', 'bills_200', 'bills_100', 'bills_50',
            'physical_cash_total', 'cash_gap',
            'is_validated', 'is_rejected', 'rejection_reason', 'notes',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
            'has_cashbook_entry',
        ]
        read_only_fields = [
            'id', 'node', 'node_display', 'gerant', 'gerant_display',
            'total_entries', 'total_expenses',
            'net_cash', 'physical_cash_total', 'cash_gap',
            'is_validated', 'is_rejected', 'rejection_reason',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
            'has_cashbook_entry',
        ]

    def get_gerant_display(self, obj):
        return obj.gerant.get_full_name() if obj.gerant else None

    def get_has_cashbook_entry(self, obj):
        return obj.cashbook_entries.exists()


class JournalEntrySerializer(serializers.ModelSerializer):
    node_display        = serializers.StringRelatedField(source='node', read_only=True)
    imput_display       = serializers.CharField(source='get_imput_display', read_only=True)
    recorded_by_display = serializers.SerializerMethodField()
    # node is resolved in perform_create from user.node or request.data
    node = serializers.PrimaryKeyRelatedField(
        queryset=Node.objects.all(),
        required=False, allow_null=True,
    )

    class Meta:
        model  = JournalEntry
        fields = [
            'id', 'node', 'node_display', 'recorded_by', 'recorded_by_display',
            'date', 'imput', 'imput_display', 'label',
            'entry_amount', 'exit_amount', 'running_balance', 'month_carried',
            'created_at',
            # BUG-091 : rapprochement de l'imputation CA avec la CashClosure
            # du même (nœud, date) — toujours en lecture seule, renseigné
            # côté serveur (perform_create), jamais saisi par le client.
            'is_reconciled', 'reconciliation_gap', 'reconciled_closure',
        ]
        read_only_fields = [
            'id', 'recorded_by', 'recorded_by_display', 'node_display',
            'running_balance', 'month_carried', 'created_at',
            'is_reconciled', 'reconciliation_gap', 'reconciled_closure',
        ]

    def get_recorded_by_display(self, obj):
        return obj.recorded_by.get_full_name() if obj.recorded_by else None


class DailySavingsSerializer(serializers.ModelSerializer):
    node_display  = serializers.StringRelatedField(source='node', read_only=True)
    # node is resolved in perform_create from user.node or request.data
    node = serializers.PrimaryKeyRelatedField(
        queryset=Node.objects.all(),
        required=False, allow_null=True,
    )

    class Meta:
        model  = DailySavings
        fields = [
            'id', 'node', 'node_display', 'recorded_by',
            'date', 'flour_sacks', 'daily_revenue', 'savings_rate', 'savings_amount',
            'created_at',
        ]
        read_only_fields = ['id', 'savings_amount', 'recorded_by', 'node_display', 'created_at']
        extra_kwargs = {
            'savings_rate': {'required': False},
        }
        # Remove auto-generated UniqueTogetherValidator so perform_create can upsert
        validators = []


class CashbookEntrySerializer(serializers.ModelSerializer):
    node_display = serializers.StringRelatedField(source='node', read_only=True)
    corrected_by_display = serializers.SerializerMethodField()

    class Meta:
        model  = CashbookEntry
        fields = [
            'id', 'node', 'node_display', 'date',
            'piece_number', 'imputation', 'label',
            'entry_amount', 'exit_amount', 'running_balance',
            'source_closure', 'source_bordereau',
            'block_hash', 'previous_hash', 'is_tampered',
            # BUG-083 : traçabilité des écritures de correction (« ventes
            # passées » sur une clôture déjà validée) — jamais une
            # modification d'une écriture existante, voir models.py.
            'is_correction', 'correction_reason', 'corrected_by', 'corrected_by_display',
            'correction_source_invoice',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'running_balance', 'block_hash', 'previous_hash', 'is_tampered',
            'is_correction', 'correction_reason', 'corrected_by', 'correction_source_invoice',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]

    def get_corrected_by_display(self, obj):
        return obj.corrected_by.get_full_name() if obj.corrected_by else None


class DisbursementVoucherSerializer(serializers.ModelSerializer):
    created_by_display = serializers.SerializerMethodField()

    class Meta:
        model  = DisbursementVoucher
        fields = [
            'id', 'date', 'created_by', 'created_by_display', 'motif', 'beneficiary',
            'bills_20000', 'bills_10000', 'bills_5000', 'bills_1000',
            'bills_500', 'bills_200', 'bills_100', 'bills_50',
            'physical_cash_total', 'piece_number',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'created_by', 'created_by_display', 'physical_cash_total', 'piece_number',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]

    def get_created_by_display(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None


class DirectionCashCountSerializer(serializers.ModelSerializer):
    """
    BUG-119 : comptage physique de billets au niveau Direction (CLAUDE.md
    §5.5), distinct et sans effet sur le chaînage SHA-256 de `CashbookEntry`
    (voir docstring de `DirectionCashCount` dans models.py).
    """
    counted_by_display = serializers.SerializerMethodField()

    class Meta:
        model  = DirectionCashCount
        fields = [
            'id', 'date', 'counted_by', 'counted_by_display',
            'bills_20000', 'bills_10000', 'bills_5000', 'bills_1000',
            'bills_500', 'bills_200', 'bills_100', 'bills_50',
            'physical_cash_total', 'reference_entry', 'theoretical_balance',
            'cash_gap', 'notes', 'created_at',
        ]
        read_only_fields = [
            'id', 'counted_by', 'counted_by_display',
            'physical_cash_total', 'reference_entry', 'theoretical_balance',
            'cash_gap', 'created_at',
        ]

    def get_counted_by_display(self, obj):
        return obj.counted_by.get_full_name() if obj.counted_by else None
