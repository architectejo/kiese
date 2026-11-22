"""BUG-386 (remarque.md l.472) : vue globale des consommables pour la direction,
envoi (orientation) du stock « direction » vers les boulangeries, et
« Inventaire Physique » journalier du gérant.

- Stock direction = `ConsumableStock` du nœud technique `SIEGE` (inactif, créé par
  core/0011) : aucun nouveau modèle de stock, mêmes mouvements (`ConsumableMovement`).
- Tout est en `Decimal` ; toute écriture de solde sous `transaction.atomic()` +
  `select_for_update()`.
"""
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.mixins import is_node_less_non_hq
from core.models import Node
from core.permissions import IsDirection, IsGerant, IsHeadquarters
from core.utils import create_notification, log_activity
from kiese.node_guard import resolve_node_param

from .models import ConsumableCount, ConsumableInventory, ConsumableMovement, ConsumableStock, ConsumableType

Q3 = Decimal('0.001')
MAX_QTY = Decimal('9999999.999')  # max_digits=10, decimal_places=3
SIEGE_CODE = 'SIEGE'


def err(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': message}, status=code)


def parse_qty(raw, label, allow_zero=False):
    """Décimal borné (3 décimales). Retourne (Decimal, None) ou (None, message FR)."""
    if raw is None or isinstance(raw, bool) or raw == '':
        return None, f"{label} : quantité requise."
    try:
        value = Decimal(str(raw).strip().replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None, f"{label} : quantité invalide."
    if not value.is_finite():
        return None, f"{label} : quantité invalide."
    if value != value.quantize(Q3):
        return None, f"{label} : au plus 3 décimales."
    if value < 0 or (value == 0 and not allow_zero):
        return None, f"{label} : la quantité doit être strictement positive." if not allow_zero \
            else f"{label} : la quantité ne peut pas être négative."
    if value > MAX_QTY:
        return None, f"{label} : quantité trop grande."
    return value, None


def siege_node():
    node, _ = Node.objects.get_or_create(
        code=SIEGE_CODE, defaults={'name': 'Direction Générale — Siège', 'is_active': False})
    return node


def _type_meta(codes=None):
    qs = ConsumableType.objects.filter(is_active=True)
    if codes is not None:
        qs = ConsumableType.objects.filter(code__in=codes)
    return {t.code: t for t in qs}


class IsGerantOfANode(BasePermission):
    """Saisie de l'inventaire : rôle GERANT rattaché à une boulangerie uniquement."""
    message = "Seul le gérant de la boulangerie peut saisir l'inventaire physique."

    def has_permission(self, request, view):
        u = request.user
        return bool(u.is_authenticated and u.role == 'GERANT' and u.node_id)


class IsDirectionStrict(IsDirection):
    message = "Réservé à la direction (ADMIN, DIRECTION)."


# --------------------------------------------------------------------------- global
class GlobalConsumablesView(APIView):
    """GET /api/production/consumables/global/ : matrice boulangeries x consommables
    + stock direction (siège). Lecture : ADMIN, DIRECTION, COMPTABLE."""
    permission_classes = [IsHeadquarters]

    def get(self, request):
        types = list(ConsumableType.objects.filter(is_active=True).order_by('code'))
        codes = [t.code for t in types]
        siege = Node.objects.filter(code=SIEGE_CODE).first()
        nodes = list(Node.objects.filter(is_active=True).exclude(code=SIEGE_CODE).order_by('code'))
        stocks = {}
        for s in ConsumableStock.objects.filter(consumable_type__in=codes).values(
                'node_id', 'consumable_type', 'quantity'):
            stocks[(s['node_id'], s['consumable_type'])] = s['quantity']
        zero = Decimal('0')

        def row_stocks(node_id):
            return {c: str(stocks.get((node_id, c), zero)) for c in codes}

        last_inv = {}
        for inv in ConsumableInventory.objects.filter(node__in=nodes).order_by('node_id', '-inventory_date'):
            last_inv.setdefault(inv.node_id, inv)

        totals = {c: zero for c in codes}
        node_rows = []
        for n in nodes:
            for c in codes:
                totals[c] += stocks.get((n.pk, c), zero)
            li = last_inv.get(n.pk)
            node_rows.append({
                'node': n.pk, 'code': n.code, 'name': n.name,
                'stocks': row_stocks(n.pk),
                'last_inventory': None if li is None else {
                    'id': str(li.pk), 'date': li.inventory_date.isoformat(), 'has_comment': bool(li.comment)},
            })
        direction = {c: str(stocks.get((siege.pk, c), zero)) if siege else str(zero) for c in codes}
        return Response({
            'types': [{'code': t.code, 'label': t.label, 'unit': t.unit} for t in types],
            'direction': {'node': siege.pk if siege else None, 'code': SIEGE_CODE, 'stocks': direction},
            'nodes': node_rows,
            'totals_bakeries': {c: str(v) for c, v in totals.items()},
            'totals_group': {c: str(totals[c] + (stocks.get((siege.pk, c), zero) if siege else zero)) for c in codes},
        })


# --------------------------------------------------------------------------- dispatch
class DispatchConsumablesView(APIView):
    """POST /api/production/consumables/dispatch/ : la direction envoie une quantité
    d'un consommable de son stock (SIEGE) vers une ou plusieurs boulangeries.
    Corps : {"consumable_type": "FLOUR", "note": "...", "allocations": [{"node": <id|code>, "quantity": "12.5"}]}"""
    permission_classes = [IsDirectionStrict]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        code = str(data.get('consumable_type') or '').strip()
        ctype = ConsumableType.objects.filter(code=code, is_active=True).first() if code else None
        if ctype is None:
            return err("Consommable inconnu ou inactif.")
        allocs = data.get('allocations')
        if not isinstance(allocs, list) or not allocs:
            return err("Indiquez au moins une boulangerie destinataire et sa quantité.")
        note = str(data.get('note') or '').strip()[:200]

        plan, seen, total = [], set(), Decimal('0')
        for i, a in enumerate(allocs, 1):
            if not isinstance(a, dict):
                return err(f"Ligne {i} invalide.")
            raw_node = a.get('node')
            if raw_node in (None, ''):
                return err(f"Ligne {i} : boulangerie requise.")
            node, resp = resolve_node_param(raw_node)
            if resp is not None:
                return resp
            if node.code == SIEGE_CODE or not node.is_active:
                return err(f"Ligne {i} : « {node.code} » n'est pas une boulangerie destinataire valide.")
            if node.pk in seen:
                return err(f"Boulangerie « {node.code} » indiquée plusieurs fois.")
            seen.add(node.pk)
            qty, e = parse_qty(a.get('quantity'), f"Ligne {i} ({node.code})")
            if e:
                return err(e)
            total += qty
            plan.append((node, qty))

        with transaction.atomic():
            siege = siege_node()
            src, _ = ConsumableStock.objects.get_or_create(
                node=siege, consumable_type=code,
                defaults={'unit': ctype.unit, 'node_origin': SIEGE_CODE})
            src = ConsumableStock.objects.select_for_update().get(pk=src.pk)
            if total > src.quantity:
                return err(
                    f"Stock direction insuffisant en {ctype.label} : {src.quantity} {ctype.unit} "
                    f"disponible(s), {total} demandé(s).")
            unit_cost = src.average_unit_cost
            label = f"Envoi direction{(' — ' + note) if note else ''}"
            done = []
            for node, qty in plan:
                dst, _ = ConsumableStock.objects.get_or_create(
                    node=node, consumable_type=code,
                    defaults={'unit': ctype.unit, 'node_origin': node.code})
                ConsumableMovement.objects.create(
                    node=siege, stock=src, movement_type='EXIT', quantity=qty,
                    description=f"{label} -> {node.code}"[:255], recorded_by=request.user,
                    node_origin=SIEGE_CODE)
                ConsumableMovement.objects.create(
                    node=node, stock=dst, movement_type='ENTRY', quantity=qty, unit_price=unit_cost,
                    description=f"{label} (reçu de la direction)"[:255], recorded_by=request.user,
                    node_origin=SIEGE_CODE)
                done.append((node, qty))
            src.refresh_from_db()
            remaining = src.quantity
            log_activity(
                request.user, "Envoi Consommable Direction",
                f"{ctype.label} : " + ", ".join(f"{n.code} {q}" for n, q in done)
                + f" (total {total} {ctype.unit}, reste direction {remaining}).",
                node_origin=SIEGE_CODE)
            for node, qty in done:
                create_notification(
                    title=f"Réception de la direction — {ctype.label} {node.code}",
                    message=f"La direction a envoyé {qty} {ctype.unit} de {ctype.label} à {node.code}.",
                    severity='INFO', node_origin=node.code)
        return Response({
            'consumable_type': code, 'unit': ctype.unit, 'total_sent': str(total.quantize(Q3)),
            'direction_remaining': str(remaining.quantize(Q3)),
            'sent': [{'node': n.pk, 'code': n.code, 'quantity': str(q.quantize(Q3))} for n, q in done],
        }, status=status.HTTP_201_CREATED)


# --------------------------------------------------------------------------- inventaire
def _label_unit(code):
    t = ConsumableType.objects.filter(code=code).first()
    return (t.label if t else code), (t.unit if t else '')


def serialize_inventory(inv, with_lines=True):
    out = {
        'id': str(inv.pk), 'node': inv.node_id, 'node_code': inv.node.code, 'node_name': inv.node.name,
        'inventory_date': inv.inventory_date.isoformat(), 'comment': inv.comment,
        'recorded_by': inv.recorded_by_id,
        'recorded_by_display': inv.recorded_by.get_full_name() if inv.recorded_by else None,
        'created_at': inv.created_at.isoformat(), 'updated_at': inv.updated_at.isoformat(),
        'lines_editable': False,
    }
    if with_lines:
        types = _type_meta(None)
        out['lines'] = []
        for c in inv.lines.all().order_by('consumable_type'):
            t = types.get(c.consumable_type)
            out['lines'].append({
                'id': c.pk, 'consumable_type': c.consumable_type,
                'consumable_type_display': t.label if t else c.consumable_type,
                'unit': t.unit if t else '',
                'system_quantity': str(c.system_quantity), 'physical_quantity': str(c.physical_quantity),
                'gap': str(c.gap), 'notes': c.notes,
            })
    return out


class ConsumableInventoryViewSet(viewsets.ViewSet):
    """Inventaire Physique journalier. `/api/production/inventories/`
    GET (liste, filtres ?node= (siège) ?date=), GET <uuid>/, POST (gérant),
    PATCH <uuid>/ ({"comment": "..."} seulement), GET today/, GET node/<id|code>/."""
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_permissions(self):
        if self.action == 'create' or self.action == 'partial_update' or self.action == 'today':
            return [IsAuthenticated(), IsGerantOfANode()]
        return [IsAuthenticated(), IsGerant()]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if is_node_less_non_hq(request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Votre compte n'est rattaché à aucune boulangerie : action impossible.")

    def _base_qs(self, request):
        qs = ConsumableInventory.objects.select_related('node', 'recorded_by').exclude(node__code=SIEGE_CODE)
        if not request.user.can_access_all_nodes:
            qs = qs.filter(node_id=request.user.node_id)
        return qs

    def _get_one(self, request, pk):
        try:
            return self._base_qs(request).filter(pk=pk).first()
        except (ValueError, TypeError, Exception):
            return None

    def list(self, request):
        qs = self._base_qs(request)
        node = request.query_params.get('node')
        if node and request.user.can_access_all_nodes:
            n, resp = resolve_node_param(node)
            if resp is not None:
                return resp
            qs = qs.filter(node=n)
        d = request.query_params.get('date')
        if d:
            from django.utils.dateparse import parse_date
            try:
                pd = parse_date(d)
            except ValueError:
                pd = None
            if pd is None:
                return err("Date invalide (format AAAA-MM-JJ).")
            qs = qs.filter(inventory_date=pd)
        return Response([serialize_inventory(i, with_lines=False) for i in qs[:200]])

    def retrieve(self, request, pk=None):
        inv = self._get_one(request, pk)
        if inv is None:
            return err("Inventaire introuvable.", status.HTTP_404_NOT_FOUND)
        return Response(serialize_inventory(inv))

    @action(detail=False, methods=['get'], url_path='today')
    def today(self, request):
        today = timezone.localdate()
        inv = self._base_qs(request).filter(inventory_date=today).first()
        return Response({'date': today.isoformat(), 'done': inv is not None,
                         'inventory': serialize_inventory(inv) if inv else None})

    @action(detail=False, methods=['get'], url_path=r'node/(?P<node_ref>[^/.]+)')
    def node_detail(self, request, node_ref=None):
        node, resp = resolve_node_param(node_ref)
        if node is None or node.code == SIEGE_CODE:
            return err("Boulangerie introuvable.", status.HTTP_404_NOT_FOUND)
        if not request.user.can_access_all_nodes and node.pk != request.user.node_id:
            return err("Boulangerie introuvable.", status.HTTP_404_NOT_FOUND)
        qs = ConsumableInventory.objects.select_related('node', 'recorded_by').filter(node=node)
        d = request.query_params.get('date')
        if d:
            from django.utils.dateparse import parse_date
            try:
                pd = parse_date(d)
            except ValueError:
                pd = None
            if pd is None:
                return err("Date invalide (format AAAA-MM-JJ).")
            qs = qs.filter(inventory_date=pd)
        inv = qs.order_by('-inventory_date').first()
        history = list(ConsumableInventory.objects.filter(node=node)
                       .order_by('-inventory_date').values_list('inventory_date', flat=True)[:30])
        return Response({
            'node': node.pk, 'code': node.code, 'name': node.name,
            'inventory': serialize_inventory(inv) if inv else None,
            'history_dates': [h.isoformat() for h in history],
        })

    def create(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        user, node = request.user, request.user.node
        lines = data.get('lines')
        if not isinstance(lines, list) or not lines:
            return err("Saisissez au moins une ligne d'inventaire.")
        comment = str(data.get('comment') or '').strip()
        if len(comment) > 2000:
            return err("Commentaire trop long (2000 caractères maximum).")
        known = set(ConsumableType.objects.filter(is_active=True).values_list('code', flat=True))
        known |= set(ConsumableStock.objects.filter(node=node).values_list('consumable_type', flat=True))
        parsed, seen = [], set()
        for i, ln in enumerate(lines, 1):
            if not isinstance(ln, dict):
                return err(f"Ligne {i} invalide.")
            code = str(ln.get('consumable_type') or '').strip()
            if code not in known:
                return err(f"Ligne {i} : consommable « {code} » inconnu.")
            if code in seen:
                return err(f"Ligne {i} : consommable « {code} » indiqué plusieurs fois.")
            seen.add(code)
            qty, e = parse_qty(ln.get('physical_quantity'), f"Ligne {i} ({code})", allow_zero=True)
            if e:
                return err(e)
            parsed.append((code, qty, str(ln.get('notes') or '').strip()[:500]))

        today = timezone.localdate()
        already = ("L'inventaire physique du jour a déjà été saisi : il n'est plus modifiable "
                   "aujourd'hui (seul le commentaire peut être ajouté). Nouvelle saisie demain.")
        try:
            with transaction.atomic():
                if ConsumableInventory.objects.select_for_update().filter(node=node, inventory_date=today).exists():
                    return err(already)
                inv = ConsumableInventory.objects.create(
                    node=node, inventory_date=today, comment=comment, recorded_by=user,
                    node_origin=node.code)
                for code, qty, notes in parsed:
                    st = ConsumableStock.objects.select_for_update().filter(node=node, consumable_type=code).first()
                    sys_q = st.quantity if st else Decimal('0')
                    ConsumableCount.objects.create(
                        node=node, consumable_type=code, count_date=today, system_quantity=sys_q,
                        physical_quantity=qty, gap=qty - sys_q, counted_by=user, notes=notes, inventory=inv)
                log_activity(user, "Inventaire Physique",
                             f"{node.code} {today} : {len(parsed)} consommable(s) inventoriés.",
                             node_origin=node.code)
        except IntegrityError:
            return err(already)
        return Response(serialize_inventory(inv), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        inv = self._get_one(request, pk)
        if inv is None:
            return err("Inventaire introuvable.", status.HTTP_404_NOT_FOUND)
        data = request.data if isinstance(request.data, dict) else {}
        extra = set(data.keys()) - {'comment'}
        if extra or 'comment' not in data:
            return err("L'inventaire physique n'est plus modifiable : seul le commentaire peut être ajouté.")
        comment = str(data.get('comment') or '').strip()
        if len(comment) > 2000:
            return err("Commentaire trop long (2000 caractères maximum).")
        with transaction.atomic():
            inv = ConsumableInventory.objects.select_for_update().get(pk=inv.pk)
            inv.comment = comment
            inv.save(update_fields=['comment', 'updated_at'])
            log_activity(request.user, "Commentaire Inventaire",
                         f"{inv.node.code} {inv.inventory_date} : commentaire mis à jour.",
                         node_origin=inv.node.code)
        inv = ConsumableInventory.objects.select_related('node', 'recorded_by').get(pk=inv.pk)
        return Response(serialize_inventory(inv))
