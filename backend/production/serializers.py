from decimal import Decimal, InvalidOperation

from rest_framework import serializers
from core.models import Node
from core.numeric import NumericError, parse_ascii_decimal, parse_ascii_int
from .models import ProductionSession, ProductionSessionLine, BreadStock, ConsumableType, ConsumableStock, ConsumableMovement, ConsumableCount, BreadTransfer, BreadTransferLine, BreadDisposal


# BUG-623 : plafond de la valeur produite par session (colonne entière 32 bits).
MAX_SESSION_FC = 2_000_000_000
MAX_DISPOSAL_QTY = 1_000_000
MAX_DISPOSAL_VALUE = 9_999_999_999  # DecimalField(max_digits=12, decimal_places=2)


def _refuse_non_ascii_quantity(data):
    """
    BUG-654/682/1015-1018 : la quantite brute doit respecter la regle canonique
    partagee (core.numeric) : entier ASCII, sans exposant, souligne, espace non
    ASCII, bool ni null. Les bornes metier restent controlees plus loin.
    """
    if hasattr(data, 'get') and 'quantity' in data:
        try:
            parse_ascii_int(data.get('quantity'), label='quantity')
        except NumericError:
            raise serializers.ValidationError({'detail': "Quantité invalide (nombre entier en chiffres 0-9 attendu)."})


def _refuse_non_ascii_fields(data, names, places=None):
    """
    BUG-686/1015-1018 : champs numeriques bruts selon la regle canonique.
    `places` : nombre de decimales (decimal) ; None = entier.
    """
    if hasattr(data, 'get'):
        for name in names:
            if name not in data:
                continue
            raw = data.get(name)
            try:
                if places is None:
                    parse_ascii_int(raw, label=name)
                else:
                    parse_ascii_decimal(raw, places=places + 12, label=name)
            except NumericError:
                raise serializers.ValidationError({'detail': f"« {name} » invalide (nombre en chiffres 0-9 attendu)."})
    return data


def _canonical_decimal_data(data, fields):
    """
    BUG-1031 : meme verdict que le push pour les zeros finaux. Une chaine decimale
    dont les chiffres au-dela de `places` sont tous des zeros (`0.3330`, `1.500`)
    est reecrite a `places` decimales avant le DecimalField DRF (qui, lui, compte
    les zeros finaux). Les valeurs a decimale non nulle excedentaire restent
    inchangees (refusees ensuite par DRF, BUG-907). `fields` : {nom: places}.
    Renvoie une copie de `data` si elle a ete modifiee, sinon `data`.
    """
    if not hasattr(data, 'get'):
        return data
    out = data
    for name, places in fields.items():
        raw = data.get(name) if name in data else None
        if not isinstance(raw, str):
            continue
        try:
            number = parse_ascii_decimal(raw, places=places + 12, label=name)
            quantized = number.quantize(Decimal(1).scaleb(-places))
        except (NumericError, InvalidOperation):
            continue
        if quantized != number:
            continue
        if out is data:
            out = data.copy() if hasattr(data, 'copy') else dict(data)
        out[name] = format(quantized, 'f')
    return out


class ProductionSessionLineSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        _refuse_non_ascii_quantity(data)
        return super().to_internal_value(data)

    bread_price_display = serializers.StringRelatedField(source='bread_price', read_only=True)
    unit_price = serializers.IntegerField(source='bread_price.unit_price', read_only=True)
    line_fc = serializers.IntegerField(read_only=True)
    # BUG-142 : exposé en lecture seule — distingue une ligne de vraie
    # déclaration de fournée (DECLARED) d'une ligne issue de la confirmation
    # du stock de départ (CARRYOVER, BUG-133/136). Champ additif, non cassant
    # pour le frontend existant (ignoré tel quel s'il n'est pas consommé).
    source = serializers.CharField(read_only=True)

    class Meta:
        model = ProductionSessionLine
        fields = ['bread_price', 'bread_price_display', 'unit_price', 'quantity', 'line_fc', 'source']


class ProductionSessionSerializer(serializers.ModelSerializer):
    node_display        = serializers.StringRelatedField(source='node', read_only=True)
    declared_by_display = serializers.SerializerMethodField()
    team_display        = serializers.CharField(source='get_team_display', read_only=True)
    # BUG-306 : `lines` facultatif — une fournée peut être déclarée par le seul
    # nombre de sacs (pains alors incrémentés à la livraison des ventes).
    lines               = ProductionSessionLineSerializer(many=True, required=False)
    # BUG-306 : objectif et avancement (lecture seule). Voir get_* ci-dessous.
    objective_fc        = serializers.SerializerMethodField()
    progress_value_fc   = serializers.SerializerMethodField()
    progress_pct        = serializers.SerializerMethodField()
    is_in_progress      = serializers.SerializerMethodField()
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
            'auto_track', 'objective_fc', 'progress_value_fc', 'progress_pct', 'is_in_progress',
            'notes', 'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'auto_track',
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

    def get_objective_fc(self, obj):
        # Montant à atteindre = sacs x valeur théorique du sac (figée à la
        # déclaration, BUG-038) ; entier en FC.
        return obj.theoretical_yield

    def get_progress_value_fc(self, obj):
        # Valeur déjà produite/livrée sur la fournée (lignes DECLARED au prix
        # catalogue) ; pour une fournée auto : valeur vendue/livrée.
        # BUG-319 : fournée par sacs = valeur LIVRÉE suivie (`delivered_value_fc`),
        # jamais une production ; fournée classique = lignes DECLARED.
        return self._progress_value(obj)

    @staticmethod
    def _progress_value(obj):
        return obj.delivered_value_fc if obj.auto_track else obj.total_fc_produced

    def get_progress_pct(self, obj):
        # Pourcentage d'avancement, 2 décimales, NON plafonné (peut dépasser 100).
        from decimal import Decimal, ROUND_HALF_UP
        if not obj.theoretical_yield:
            return '0.00'
        pct = Decimal(self._progress_value(obj)) * Decimal('100') / Decimal(obj.theoretical_yield)
        return str(pct.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    def get_is_in_progress(self, obj):
        return not obj.is_closed

    # BUG-309 : borne haute de sécurité (le modèle autorise 999 999,99).
    MAX_FLOUR_SACKS = 100000

    def to_internal_value(self, data):
        # BUG-309 : `flour_sacks_used` invalide (négatif, non numérique,
        # NaN/infini, trop grand, > 2 décimales) -> 400 {"detail": "..."} en
        # français, au lieu d'une IntegrityError (CHECK theoretical_yield) = 500.
        # 0 reste accepté (contrat BUG-306 : fournée non « en cours »).
        from decimal import Decimal, InvalidOperation
        if hasattr(data, 'get') and 'flour_sacks_used' in data:
            raw = data.get('flour_sacks_used')
            msg = None
            # BUG-309/654/1017 : regle canonique partagee (null, vide, bool, exposant,
            # souligne, espaces/chiffres non ASCII refuses) ; bornes metier ci-dessous.
            try:
                val = parse_ascii_decimal(raw, places=12, label='flour_sacks_used')
            except NumericError:
                val = None
                msg = "« flour_sacks_used » : nombre de sacs invalide (chiffres 0-9 uniquement)."
            if val is not None:
                if val < 0:
                    msg = "« flour_sacks_used » : le nombre de sacs ne peut pas être négatif."
                elif val > self.MAX_FLOUR_SACKS:
                    msg = f"« flour_sacks_used » : le nombre de sacs ne peut pas dépasser {self.MAX_FLOUR_SACKS}."
                elif val != val.quantize(Decimal('0.01')):
                    msg = "« flour_sacks_used » : 2 décimales maximum."
            if msg:
                raise serializers.ValidationError({'detail': msg})
            data = _canonical_decimal_data(data, {'flour_sacks_used': 2})  # BUG-1031
        return super().to_internal_value(data)

    def validate(self, attrs):
        # BUG-142 (remarque.md) : une session existante pour (node, team,
        # date) n'est plus un rejet — `ProductionSessionViewSet.
        # perform_create()` l'ADDITIONNE désormais à la session du jour
        # existante (sauf si elle est déjà clôturée, cas traité là-bas avec
        # le bon message d'erreur). Ne plus bloquer ici, sous peine
        # d'empêcher perform_create() de même voir le payload.
        # BUG-622 : lignes dupliquées (même catégorie) et changement de date/équipe
        # vers une session existante -> 400 français au lieu d'une IntegrityError (500).
        # BUG-623 : quantités / valeur agrégée bornées (colonne entière 32 bits).
        lines = attrs.get('lines')
        if lines is not None:
            seen = set()
            total_fc = 0
            for line in lines:
                bp = line.get('bread_price')
                if bp.pk in seen:
                    raise serializers.ValidationError({'detail': (
                        f"La catégorie de pain « {bp.label} » figure plusieurs fois dans les lignes : "
                        f"regroupez-la en une seule ligne."
                    )})
                seen.add(bp.pk)
                total_fc += (line.get('quantity') or 0) * bp.unit_price
            if total_fc > MAX_SESSION_FC:
                raise serializers.ValidationError({'detail': (
                    "Quantités trop grandes : la valeur produite dépasse la limite autorisée."
                )})
        inst = self.instance
        if inst is not None and any(k in attrs for k in ('date', 'team', 'node')):
            new_date = attrs.get('date', inst.date)
            new_team = attrs.get('team', inst.team)
            new_node = attrs.get('node') or inst.node
            if ProductionSession.objects.filter(
                node=new_node, team=new_team, date=new_date,
            ).exclude(pk=inst.pk).exists():
                raise serializers.ValidationError({'detail': (
                    f"Une session existe déjà pour l'Équipe {new_team} le {new_date} "
                    f"à la boulangerie {new_node.code}."
                )})
        return attrs

    def create(self, validated_data):
        lines_data = validated_data.pop('lines', [])
        session = ProductionSession.objects.create(**validated_data)
        for line in lines_data:
            if line.get('quantity', 0) > 0:
                ProductionSessionLine.objects.create(
                    session=session, source=ProductionSessionLine.Source.DECLARED, **line,
                )
        return session

    def update(self, instance, validated_data):
        lines_data = validated_data.pop('lines', None)
        instance = super().update(instance, validated_data)
        if lines_data is not None:
            # BUG-142 : ne remplace que les lignes DECLARED (vraie fournée
            # éditée) — ne jamais effacer les lignes CARRYOVER (reste d'hier
            # confirmé, BUG-133/136) qui peuvent coexister sur la même
            # session, sous peine de perdre silencieusement cette donnée à
            # la moindre édition d'une fournée le même jour.
            instance.lines.filter(source=ProductionSessionLine.Source.DECLARED).delete()
            for line in lines_data:
                if line.get('quantity', 0) > 0:
                    ProductionSessionLine.objects.create(
                        session=instance, source=ProductionSessionLine.Source.DECLARED, **line,
                    )
        return instance


class BreadStockSerializer(serializers.ModelSerializer):
    node_display        = serializers.StringRelatedField(source='node', read_only=True)
    bread_price_display = serializers.StringRelatedField(source='bread_price', read_only=True)
    unit_price          = serializers.IntegerField(source='bread_price.unit_price', read_only=True)
    qty_available       = serializers.IntegerField(read_only=True)
    # BUG-319 : lecture du jour de travail courant du nœud (vendus seuls tant
    # que la journée n'est pas clôturée ; null = pas encore connu).
    sold_qty            = serializers.SerializerMethodField()
    remaining_qty       = serializers.SerializerMethodField()
    produced_total      = serializers.SerializerMethodField()
    closed              = serializers.SerializerMethodField()

    class Meta:
        model  = BreadStock
        fields = [
            'id', 'node', 'node_display', 'bread_price', 'bread_price_display', 'unit_price',
            'qty_produced', 'qty_received', 'qty_sent', 'qty_disposed', 'qty_adjusted', 'qty_available',
            'sold_qty', 'remaining_qty', 'produced_total', 'closed',
        ]

    def _day(self, obj):
        from core.workday import work_date_for
        from .services import compute_day_production
        cache = self.context.setdefault('_day_production_cache', {})
        if obj.node_id not in cache:
            cache[obj.node_id] = compute_day_production(obj.node, work_date_for(obj.node))
        return cache[obj.node_id]

    def _row(self, obj):
        return self._day(obj)['by_bp'].get(obj.bread_price_id)

    def get_sold_qty(self, obj):
        row = self._row(obj)
        return row['sold'] if row else 0

    def get_remaining_qty(self, obj):
        row = self._row(obj)
        if self._day(obj)['closed']:
            return row['remaining'] if row else 0
        return None

    def get_produced_total(self, obj):
        row = self._row(obj)
        if self._day(obj)['closed']:
            return row['produced'] if row else 0
        return None

    def get_closed(self, obj):
        return self._day(obj)['closed']
        read_only_fields = ['id', 'qty_produced', 'qty_received', 'qty_sent', 'qty_disposed', 'qty_adjusted']


class ConsumableTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ConsumableType
        fields = ['id', 'code', 'label', 'unit', 'is_active', 'bag_weight_g', 'units_per_bag', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def validate_bag_weight_g(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Le poids d'un sac doit être strictement positif.")
        return value

    def validate_units_per_bag(self, value):
        if value is not None and value < 1:
            raise serializers.ValidationError("Le nombre de boîtes par sac doit être au moins 1.")
        return value

    def validate(self, attrs):
        inst = self.instance
        w = attrs.get('bag_weight_g', getattr(inst, 'bag_weight_g', None))
        u = attrs.get('units_per_bag', getattr(inst, 'units_per_bag', None))
        if (w is None) != (u is None):
            raise serializers.ValidationError({'detail': "Renseignez à la fois le poids d'un sac et le nombre de boîtes par sac, ou aucun des deux."})
        return attrs


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
        # BUG-251 : `quantity` n'évolue que par mouvements (ConsumableMovement).
        read_only_fields = ['id', 'quantity', 'average_unit_cost', 'node_origin', 'is_synced', 'created_at', 'updated_at']

    def get_consumable_type_display(self, obj):
        return _consumable_type_label(obj.consumable_type)


def _check_fk_in_user_node(serializer, obj, label):
    """BUG-504/36x : un non-siège ne peut référencer (stock, session...) que
    des objets de sa propre boulangerie ; 404 sans fuite d'existence."""
    from rest_framework.exceptions import NotFound
    request = serializer.context.get('request')
    user = getattr(request, 'user', None)
    if obj is None or user is None or not user.is_authenticated or user.can_access_all_nodes:
        return obj
    if getattr(obj, 'node_id', None) != user.node_id:
        raise NotFound(f"{label} introuvable.")
    return obj


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

    def to_internal_value(self, data):
        _refuse_non_ascii_fields(data, ('quantity',), places=3)
        # BUG-1033 : prix unitaire via le parseur canonique (4 decimales), comme la quantite
        # et comme le push (`1_0`, `1e1`, chiffres non ASCII refuses).
        if hasattr(data, 'get') and 'unit_price' in data and data.get('unit_price') not in (None, ''):
            try:
                price = parse_ascii_decimal(data.get('unit_price'), places=4 + 12, label='unit_price')
            except NumericError:
                raise serializers.ValidationError({'detail': "« unit_price » invalide (chiffres 0-9 uniquement)."})
            # BUG-1032 : un prix d'achat negatif rendrait le CUMP negatif (BUG-803) : refus REST et push.
            if price < 0:
                raise serializers.ValidationError({'detail': "Le prix unitaire ne peut pas être négatif."})
        data = _canonical_decimal_data(data, {'quantity': 3, 'unit_price': 4})  # BUG-1031
        return super().to_internal_value(data)

    def validate_stock(self, value):
        return _check_fk_in_user_node(self, value, 'Stock')

    def validate_session(self, value):
        return _check_fk_in_user_node(self, value, 'Session')


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

    def to_internal_value(self, data):
        _refuse_non_ascii_fields(data, ('physical_quantity',), places=3)
        data = _canonical_decimal_data(data, {'physical_quantity': 3})  # BUG-1031
        return super().to_internal_value(data)

    def validate_physical_quantity(self, value):
        # BUG-688 : une quantité physique comptée ne peut pas être négative.
        if value is not None and value < 0:
            raise serializers.ValidationError("La quantité physique ne peut pas être négative.")
        return value

    def validate_count_date(self, value):
        # BUG-687 : pas de comptage daté dans le futur (jour de travail du nœud).
        from core.workday import work_date_for
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        node = self.instance.node if self.instance is not None else None
        if node is None and user is not None and getattr(user, 'node', None) is not None:
            node = user.node
        if node is None:
            raw = getattr(request, 'data', {}).get('node') if request is not None else None
            if raw not in (None, ''):
                try:
                    node = Node.objects.filter(pk=int(raw)).first()
                except (TypeError, ValueError):
                    node = None
        if node is not None and value is not None and value > work_date_for(node):
            raise serializers.ValidationError("La date ne peut pas être dans le futur.")
        return value

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
    flow_display            = serializers.CharField(source='get_flow_display', read_only=True)
    quantity_gap            = serializers.IntegerField(read_only=True)
    total_sent              = serializers.IntegerField(read_only=True)
    lines                   = BreadTransferLineSerializer(many=True, read_only=True)

    class Meta:
        model  = BreadTransfer
        fields = [
            'id', 'from_node', 'from_node_display', 'to_node', 'to_node_display',
            'quantity_sent', 'quantity_received', 'quantity_gap', 'total_sent',
            'transfer_status', 'transfer_status_display', 'flow', 'flow_display',
            'initiated_by', 'confirmed_by', 'notes', 'lines',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'transfer_status', 'flow', 'flow_display', 'confirmed_by', 'quantity_gap', 'total_sent',
            'node_origin', 'is_synced', 'created_at', 'updated_at',
        ]
        extra_kwargs = {
            # to_node is always set server-side from user.node in perform_create
            'to_node': {'required': False},
        }

    # BUG-522 : champs figés après création (identité des boulangeries
    # concernées, auteur, quantités d'en-tête). Les changements d'état passent
    # exclusivement par les actions dédiées du viewset.
    IMMUTABLE_ON_UPDATE = ('from_node', 'to_node', 'initiated_by', 'quantity_sent', 'quantity_received')

    def validate(self, attrs):
        if self.instance is not None:
            for name in self.IMMUTABLE_ON_UPDATE:
                if name not in attrs:
                    continue
                if attrs[name] != getattr(self.instance, name):
                    raise serializers.ValidationError({'detail': (
                        "Les boulangeries (source, destination) et l'auteur d'un transfert "
                        "ne sont pas modifiables après sa création."
                    )})
                attrs.pop(name)  # valeur identique : sans effet
        return attrs


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

    def validate_session(self, value):
        return _check_fk_in_user_node(self, value, 'Session')

    def to_internal_value(self, data):
        _refuse_non_ascii_quantity(data)
        _refuse_non_ascii_fields(data, ('unit_price_sold',))
        return super().to_internal_value(data)

    def validate(self, attrs):
        # BUG-158 : seule une ligne REMAINING (« reste du jour », reflet du
        # stock physique) peut porter une quantité négative. Vérifié sur l'état
        # final (création, PUT ou PATCH partiel) pour qu'un changement de type
        # d'une ligne REMAINING négative soit aussi refusé.
        instance = self.instance
        quantity = attrs.get('quantity', getattr(instance, 'quantity', 0))
        disposal_type = attrs.get('disposal_type', getattr(instance, 'disposal_type', None))
        if quantity is not None and quantity < 0 and disposal_type != BreadDisposal.DisposalType.REMAINING:
            raise serializers.ValidationError({
                'quantity': "La quantité ne peut pas être négative (sauf pour un reste du jour).",
            })
        # BUG-623 : quantité et valeur totale bornées (sinon OverflowError / InvalidOperation = 500).
        unit_price = attrs.get('unit_price_sold', getattr(instance, 'unit_price_sold', 0)) or 0
        if quantity is not None and abs(quantity) > MAX_DISPOSAL_QTY:
            raise serializers.ValidationError({
                'quantity': f"La quantité ne peut pas dépasser {MAX_DISPOSAL_QTY}.",
            })
        if quantity is not None and abs(quantity) * unit_price > MAX_DISPOSAL_VALUE:
            raise serializers.ValidationError({
                'unit_price_sold': "La valeur totale (quantité × prix unitaire) dépasse la limite autorisée.",
            })
        return attrs
