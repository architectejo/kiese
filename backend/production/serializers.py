from rest_framework import serializers
from core.models import Node
from .models import ProductionSession, ProductionSessionLine, BreadStock, ConsumableType, ConsumableStock, ConsumableMovement, ConsumableCount, BreadTransfer, BreadTransferLine, BreadDisposal


class ProductionSessionLineSerializer(serializers.ModelSerializer):
    bread_price_display = serializers.StringRelatedField(source='bread_price', read_only=True)
    unit_price = serializers.IntegerField(source='bread_price.unit_price', read_only=True)
    line_fc = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProductionSessionLine
        fields = ['bread_price', 'bread_price_display', 'unit_price', 'quantity', 'line_fc']


class ProductionSessionSerializer(serializers.ModelSerializer):
    node_display        = serializers.StringRelatedField(source='node', read_only=True)
    declared_by_display = serializers.SerializerMethodField()
    team_display        = serializers.CharField(source='get_team_display', read_only=True)
    lines               = ProductionSessionLineSerializer(many=True)
    # node auto-assigned from user in perform_create — not required in payload
    node                = serializers.PrimaryKeyRelatedField(
        queryset=Node.objects.all(), required=False, allow_null=True,
    )

    class Meta:
        model  = ProductionSession
        fields = [
            'id', 'node', 'node_display', 'team', 'team_display', 'date',
            'declared_by', 'declared_by_display',
            'flour_sacks_used', 'lines',
            'breads_300', 'breads_400', 'breads_500', 'breads_1000', 'total_breads',
            'total_fc_produced', 'theoretical_yield', 'yield_gap', 'sac_value_fc_used',
            'is_closed', 'closed_at', 'closure_summary',
            'notes', 'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'total_breads', 'total_fc_produced', 'theoretical_yield', 'yield_gap',
            'breads_300', 'breads_400', 'breads_500', 'breads_1000', 'sac_value_fc_used',
            'is_closed', 'closed_at', 'closure_summary',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        # Disable auto UniqueTogetherValidator for ['node','team','date']:
        # it requires node present at validation time but node is auto-assigned
        # in perform_create from user.node — manual check done in validate().
        validators = []

    def get_declared_by_display(self, obj):
        return obj.declared_by.get_full_name() if obj.declared_by else None

    def validate(self, attrs):
        node = attrs.get('node')
        team = attrs.get('team')
        date = attrs.get('date')
        if node and team and date:
            qs = ProductionSession.objects.filter(node=node, team=team, date=date)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "Une session existe déjà pour cette boulangerie, cette équipe et cette date."
                )
        return attrs

    def create(self, validated_data):
        lines_data = validated_data.pop('lines', [])
        session = ProductionSession.objects.create(**validated_data)
        for line in lines_data:
            if line.get('quantity', 0) > 0:
                ProductionSessionLine.objects.create(session=session, **line)
        return session

    def update(self, instance, validated_data):
        lines_data = validated_data.pop('lines', None)
        instance = super().update(instance, validated_data)
        if lines_data is not None:
            instance.lines.all().delete()
            for line in lines_data:
                if line.get('quantity', 0) > 0:
                    ProductionSessionLine.objects.create(session=instance, **line)
        return instance


class BreadStockSerializer(serializers.ModelSerializer):
    node_display        = serializers.StringRelatedField(source='node', read_only=True)
    bread_price_display = serializers.StringRelatedField(source='bread_price', read_only=True)
    unit_price          = serializers.IntegerField(source='bread_price.unit_price', read_only=True)
    qty_available       = serializers.IntegerField(read_only=True)

    class Meta:
        model  = BreadStock
        fields = [
            'id', 'node', 'node_display', 'bread_price', 'bread_price_display', 'unit_price',
            'qty_produced', 'qty_received', 'qty_sent', 'qty_disposed', 'qty_available',
        ]
        read_only_fields = ['id', 'qty_produced', 'qty_received', 'qty_sent', 'qty_disposed']


class ConsumableTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ConsumableType
        fields = ['id', 'code', 'label', 'unit', 'is_active', 'updated_at']
        read_only_fields = ['id', 'updated_at']


def _consumable_type_label(code):
    labels = dict(ConsumableType.objects.values_list('code', 'label'))
    return labels.get(code, code)


class ConsumableStockSerializer(serializers.ModelSerializer):
    node_display = serializers.StringRelatedField(source='node', read_only=True)
    consumable_type_display = serializers.SerializerMethodField()

    class Meta:
        model  = ConsumableStock
        fields = [
            'id', 'node', 'node_display', 'consumable_type', 'consumable_type_display',
            'quantity', 'unit', 'average_unit_cost', 'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'average_unit_cost', 'node_origin', 'is_synced', 'created_at', 'updated_at']

    def get_consumable_type_display(self, obj):
        return _consumable_type_label(obj.consumable_type)


class ConsumableMovementSerializer(serializers.ModelSerializer):
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    node_display = serializers.StringRelatedField(source='node', read_only=True)
    node         = serializers.PrimaryKeyRelatedField(
        queryset=Node.objects.all(), required=False, allow_null=True,
    )

    class Meta:
        model  = ConsumableMovement
        fields = [
            'id', 'node', 'node_display', 'stock', 'session',
            'movement_type', 'movement_type_display',
            'quantity', 'unit_price', 'supplier', 'description', 'recorded_by',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'node_origin', 'is_synced', 'created_at', 'updated_at']


class ConsumableCountSerializer(serializers.ModelSerializer):
    node_display            = serializers.StringRelatedField(source='node', read_only=True)
    consumable_type_display = serializers.SerializerMethodField()
    counted_by_display      = serializers.SerializerMethodField()
    # BUG-042 : node est assigné côté serveur (ConsumableCountViewSet.perform_create,
    # depuis user.node pour un gérant non-HQ) — ne doit pas être obligatoire
    # dans le payload, comme ProductionSessionSerializer/BreadDisposalSerializer.
    node = serializers.PrimaryKeyRelatedField(
        queryset=Node.objects.all(), required=False, allow_null=True,
    )

    class Meta:
        model  = ConsumableCount
        fields = [
            'id', 'node', 'node_display', 'consumable_type', 'consumable_type_display',
            'count_date', 'system_quantity', 'physical_quantity', 'gap',
            'counted_by', 'counted_by_display', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'gap', 'system_quantity', 'counted_by', 'created_at']

    def get_consumable_type_display(self, obj):
        return _consumable_type_label(obj.consumable_type)

    def get_counted_by_display(self, obj):
        return obj.counted_by.get_full_name() if obj.counted_by else None


class BreadTransferLineSerializer(serializers.ModelSerializer):
    bread_price_display = serializers.StringRelatedField(source='bread_price', read_only=True)
    unit_price          = serializers.IntegerField(source='bread_price.unit_price', read_only=True)
    quantity_gap        = serializers.IntegerField(read_only=True)

    class Meta:
        model  = BreadTransferLine
        fields = ['id', 'bread_price', 'bread_price_display', 'unit_price', 'quantity_sent', 'quantity_received', 'quantity_gap']


class BreadTransferSerializer(serializers.ModelSerializer):
    from_node_display       = serializers.StringRelatedField(source='from_node', read_only=True)
    to_node_display         = serializers.StringRelatedField(source='to_node', read_only=True)
    transfer_status_display = serializers.CharField(source='get_transfer_status_display', read_only=True)
    quantity_gap            = serializers.IntegerField(read_only=True)
    total_sent              = serializers.IntegerField(read_only=True)
    lines                   = BreadTransferLineSerializer(many=True, read_only=True)

    class Meta:
        model  = BreadTransfer
        fields = [
            'id', 'from_node', 'from_node_display', 'to_node', 'to_node_display',
            'quantity_sent', 'quantity_received', 'quantity_gap', 'total_sent',
            'transfer_status', 'transfer_status_display',
            'initiated_by', 'confirmed_by', 'notes', 'lines',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'transfer_status', 'confirmed_by', 'quantity_gap', 'total_sent',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        extra_kwargs = {
            # to_node is always set server-side from user.node in perform_create
            'to_node': {'required': False},
        }


class BreadDisposalSerializer(serializers.ModelSerializer):
    disposal_type_display = serializers.CharField(source='get_disposal_type_display', read_only=True)
    bread_price_display   = serializers.StringRelatedField(source='bread_price', read_only=True)
    # node is auto-assigned from user in perform_create — not required in payload
    node = serializers.PrimaryKeyRelatedField(
        queryset=Node.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model  = BreadDisposal
        fields = [
            'id', 'node', 'session', 'bread_price', 'bread_price_display',
            'disposal_type', 'disposal_type_display',
            'quantity', 'unit_price_sold', 'total_value', 'notes',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'total_value', 'node_origin', 'is_synced', 'created_at', 'updated_at']
