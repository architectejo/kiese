from decimal import Decimal

from rest_framework import serializers
from .models import Invoice, InvoiceLine


class InvoiceLineSerializer(serializers.ModelSerializer):
    bread_label = serializers.CharField(source='bread_price.label', read_only=True)
    # BUG-092 : perte (prix catalogue − prix facturé) × quantité, pour une
    # ligne de vente soldée/CASH (CLAUDE.md §5.1). Nulle pour une ligne au
    # prix plein.
    loss = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model  = InvoiceLine
        fields = ['id', 'bread_price', 'bread_label', 'quantity', 'unit_price', 'line_total', 'loss']
        read_only_fields = ['id', 'unit_price', 'line_total', 'loss']


class InvoiceSerializer(serializers.ModelSerializer):
    lines                = InvoiceLineSerializer(many=True, read_only=True)
    client_display       = serializers.SerializerMethodField()
    client_code          = serializers.SerializerMethodField()
    client_photo         = serializers.SerializerMethodField()
    client_current_debt  = serializers.SerializerMethodField()
    facturier_display    = serializers.SerializerMethodField()
    livreur_display      = serializers.SerializerMethodField()
    node_display         = serializers.StringRelatedField(source='node', read_only=True)
    status_display       = serializers.CharField(source='get_status_display', read_only=True)
    payment_type_display = serializers.CharField(source='get_payment_type_display', read_only=True)
    # BUG-092 : perte totale de la facture (somme des pertes par ligne),
    # exposée pour le reçu/l'historique client — jamais stockée, toujours
    # recalculée depuis les lignes réelles.
    total_loss            = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    # BUG-097 : « grande trace » d'un ajustement — nombre d'ajustements liés
    # (pas le détail complet ici, pour ne pas alourdir chaque ligne de
    # liste ; dev-frontend peut charger `?adjusts=<id>` sur ce même
    # endpoint pour le détail complet d'une facture donnée).
    adjustments_count = serializers.IntegerField(source='adjustments.count', read_only=True)

    class Meta:
        model  = Invoice
        fields = [
            'id', 'receipt_number', 'node', 'node_display',
            'client', 'client_display', 'client_code', 'client_photo', 'client_current_debt',
            'facturier', 'facturier_display', 'livreur', 'livreur_display',
            'team', 'status', 'status_display', 'payment_type', 'payment_type_display',
            'debt_before', 'order_total', 'payment_amount', 'debt_after', 'commission_rate',
            'is_soldee', 'commission_exempt', 'special_code', 'is_debt_repayment', 'total_loss',
            'adjusts', 'is_adjustment', 'adjustment_sign', 'adjustments_count',
            'invoice_date', 'delivered_at',
            'lines',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'receipt_number', 'node_display', 'client_display',
            'client_code', 'client_photo', 'client_current_debt',
            'facturier_display', 'livreur_display', 'status_display', 'payment_type_display',
            'order_total', 'debt_after', 'invoice_date', 'delivered_at', 'total_loss',
            'adjusts', 'is_adjustment', 'adjustment_sign', 'adjustments_count',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]

    def get_client_display(self, obj):
        if not obj.client_id:
            return 'CLIENT DIVERS'
        return str(obj.client)

    def get_client_code(self, obj):
        if not obj.client_id:
            return 'DIVERS'
        return obj.client.code

    def get_client_photo(self, obj):
        if not obj.client_id:
            return None
        request = self.context.get('request')
        if obj.client.photo and hasattr(obj.client.photo, 'url'):
            return request.build_absolute_uri(obj.client.photo.url) if request else obj.client.photo.url
        return None

    def get_client_current_debt(self, obj):
        if not obj.client_id:
            return '0.00'
        return str(obj.client.current_debt)

    def get_facturier_display(self, obj):
        return obj.facturier.get_full_name() if obj.facturier else None

    def get_livreur_display(self, obj):
        return obj.livreur.get_full_name() if obj.livreur else None


class InvoiceCreateSerializer(serializers.Serializer):
    """Create an invoice with its lines in a single request."""
    # `Node` a une clé entière (BigAutoField, core/migrations/0001_initial.py),
    # pas une clé UUID (contrairement à `Client`/`Invoice`, qui héritent de
    # `SyncableModel`) — `UUIDField` ici rejetait systématiquement tout `node`
    # explicite avec 400 "Doit être un UUID valide", masquant de fait BUG-030
    # (la valeur n'atteignait jamais `InvoiceViewSet.create`).
    node            = serializers.IntegerField(required=False)
    client          = serializers.UUIDField(required=False, allow_null=True)
    payment_type    = serializers.ChoiceField(choices=Invoice.PaymentType.choices)
    payment_amount  = serializers.DecimalField(max_digits=14, decimal_places=2)
    # BUG-083 : date antérieure optionnelle (« ventes passées »). La
    # validation métier (Config.allow_backdated_sales, jamais de date
    # future) est faite dans InvoiceViewSet._create_once — pas ici — car
    # elle dépend de la configuration globale et de `timezone.localdate()`.
    invoice_date    = serializers.DateField(required=False, allow_null=True)
    commission_rate = serializers.DecimalField(max_digits=4, decimal_places=2, required=False)
    is_soldee          = serializers.BooleanField(required=False, default=False)
    # BUG-052 : « vente sans commission de 25 % », distincte de « vente
    # solde » (remarque.md l.190) — voir sales/models.py::Invoice.commission_exempt.
    commission_exempt  = serializers.BooleanField(required=False, default=False)
    is_debt_repayment  = serializers.BooleanField(required=False, default=False)
    special_code       = serializers.ChoiceField(
        choices=['', 'NV', 'RG', 'NS'], required=False, default=''
    )
    lines = serializers.ListField(
        child=serializers.DictField(),
        min_length=0,
        required=False,
        default=list,
        help_text="[{bread_price: uuid, quantity: int}, ...] — vide pour un remboursement BP"
    )


class InvoiceAdjustSerializer(serializers.Serializer):
    """
    BUG-097 : corrige/annule une commande déjà enregistrée via une nouvelle
    facture liée (« grande trace »), jamais une mutation de l'originale.

    `adjustment_sign` porte le signe de l'opération au niveau de la facture
    entière (+1 = augmentation, -1 = diminution) — les lignes ci-dessous
    restent des quantités positives (magnitude du changement), voir
    `sales/models.py::Invoice.adjusts`.
    """
    adjustment_sign = serializers.ChoiceField(choices=[1, -1])
    payment_amount  = serializers.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), min_value=Decimal('0.00'))
    invoice_date    = serializers.DateField(required=False, allow_null=True)
    lines = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        help_text="[{bread_price: uuid, quantity: int (> 0)}, ...] — magnitude du changement"
    )
