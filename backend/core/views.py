"""
Core API views — Authentication, Config, Nodes, Users management.
"""

from rest_framework import viewsets, status, generics
from rest_framework.decorators import api_view, permission_classes, action, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate, get_user_model
from django.db.models import ProtectedError
from django_filters.rest_framework import DjangoFilterBackend

from .models import Node, Config, BreadPrice, ExpenseCategory, ActivityLog, SystemNotification, ColisDistribution
from .serializers import (
    NodeSerializer, UserSerializer, UserCreateSerializer,
    ConfigSerializer, BreadPriceSerializer, ExpenseCategorySerializer, LoginSerializer,
    ActivityLogSerializer, SystemNotificationSerializer,
    ColisDistributionSerializer,
)
from .permissions import IsAdmin, IsDirection, IsHeadquarters, IsGerant
from .throttling import LoginAccountRateThrottle, LoginIPRateThrottle

User = get_user_model()


# ─── Authentication ──────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([LoginAccountRateThrottle, LoginIPRateThrottle])
def login_view(request):
    """Authenticate user and return JWT tokens + user profile.

    BUG-006 : limitation des tentatives de connexion (voir
    REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login'] et
    ['login_ip'] dans settings.py).

    BUG-087 : la limitation se fait désormais par **compte visé**
    (`LoginAccountRateThrottle`, clé = `username` du payload) et non plus
    uniquement par IP. Plusieurs comptes différents connectés depuis la
    même IP (ex. même boulangerie/réseau local) ne se bloquent plus entre
    eux ; marteler un seul compte reste throttlé. `LoginIPRateThrottle`
    est conservé en complément avec un plafond plus large, en garde-fou
    anti credential-stuffing sur l'IP.
    """
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = authenticate(
        username=serializer.validated_data['username'],
        password=serializer.validated_data['password']
    )
    if user is None:
        return Response(
            {'detail': 'Identifiants invalides.'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    if not user.is_active:
        return Response(
            {'detail': 'Ce compte est désactivé.'},
            status=status.HTTP_403_FORBIDDEN
        )

    refresh = RefreshToken.for_user(user)
    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': UserSerializer(user).data
    })


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def me_view(request):
    """Return or update current authenticated user's profile."""
    user = request.user
    if request.method == 'GET':
        return Response(UserSerializer(user).data)

    # PATCH — allow users to update their own basic info
    allowed = {'first_name', 'last_name', 'phone', 'email', 'username'}
    data = {k: v for k, v in request.data.items() if k in allowed}
    serializer = UserSerializer(user, data=data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()

    # Password change (separate from profile fields)
    new_password = request.data.get('new_password', '').strip()
    if new_password:
        old_password = request.data.get('old_password', '')
        if not user.check_password(old_password):
            return Response({'old_password': 'Mot de passe actuel incorrect.'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()

    return Response(UserSerializer(user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """Blacklist the refresh token to logout."""
    try:
        refresh_token = request.data.get('refresh')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
    except Exception:
        pass
    return Response({'detail': 'Déconnexion réussie.'})


# ─── Config ──────────────────────────────────────────────────────────

class ConfigView(generics.RetrieveUpdateAPIView):
    """
    GET: Retrieve global config (public for on_line check, auth for full).
    PUT/PATCH: Update config (ADMIN/DIRECTION only).
    """
    serializer_class = ConfigSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsDirection()]

    def get_object(self):
        return Config.get_instance()


# ─── Nodes ───────────────────────────────────────────────────────────

class NodeViewSet(viewsets.ModelViewSet):
    """CRUD for bakery nodes. Only ADMIN/DIRECTION can create/update/delete."""
    queryset = Node.objects.all()
    serializer_class = NodeSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsDirection()]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == 'list':
            # The fictional SIEGE node (HQ cashbook attribution for
            # bordereaux de versement) must never appear in bakery pickers.
            qs = qs.exclude(code='SIEGE')
        return qs


# ─── Users ───────────────────────────────────────────────────────────

class UserViewSet(viewsets.ModelViewSet):
    """User management. ADMIN/DIRECTION only for create/update/delete."""
    queryset = User.objects.select_related('node').all()
    filter_backends  = [DjangoFilterBackend]
    filterset_fields  = ['node', 'role']

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsHeadquarters()]
        return [IsDirection()]

    @action(detail=True, methods=['post'], permission_classes=[IsDirection])
    def reset_password(self, request, pk=None):
        """Reset a user's password to their username (DIRECTION only)."""
        user = self.get_object()
        user.set_password(user.username)
        user.save()
        return Response({'detail': f"Mot de passe réinitialisé — nouveau mot de passe : {user.username}"})


# ─── Bread Prices ────────────────────────────────────────────────────

class BreadPriceViewSet(viewsets.ModelViewSet):
    """
    Bread price grid management.
    Public read access (used by the public Vitrine pricing page),
    only ADMIN/DIRECTION can modify.
    """
    queryset = BreadPrice.objects.all()
    serializer_class = BreadPriceSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return [IsDirection()]

    def destroy(self, request, *args, **kwargs):
        # BreadPrice is referenced with on_delete=PROTECT by InvoiceLine,
        # BreadStock and several production models — without this, deleting
        # a price already used somewhere raises an unhandled 500 and the
        # frontend silently swallows it (delete button looks like it does nothing).
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': (
                    "Impossible de supprimer ce tarif : il est déjà utilisé dans des factures ou des productions "
                    "existantes. Désactivez-le plutôt (Modifier → Statut Inactif) pour le retirer des nouvelles "
                    "ventes sans perdre l'historique."
                )},
                status=status.HTTP_400_BAD_REQUEST
            )


# ─── Expense Categories ──────────────────────────────────────────────

class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    """
    Local-expense category management (§5.1.2).
    Open-ended list — the comptable (not just DIRECTION) can add categories.
    """
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsHeadquarters()]

    def destroy(self, request, *args, **kwargs):
        # LocalExpense.category is on_delete=PROTECT — same failure mode as BreadPrice above.
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': "Impossible de supprimer cette catégorie : elle est déjà utilisée par des dépenses locales existantes. Désactivez-la plutôt (Modifier → Statut Inactif)."},
                status=status.HTTP_400_BAD_REQUEST
            )


# ─── Activity Log Viewset ───────────────────────────────────────────

class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly viewset for system actions and activity logs.
    Available to Headquarters (ADMIN/DIRECTION/COMPTABLE).
    """
    queryset = ActivityLog.objects.all()
    serializer_class = ActivityLogSerializer
    permission_classes = [IsHeadquarters]


# ─── System Notification Viewset ────────────────────────────────────

class SystemNotificationViewSet(viewsets.ModelViewSet):
    """
    Manage system wide notifications (alarms, warnings, credit limits).
    Available to authenticated agents.
    """
    queryset = SystemNotification.objects.all()
    serializer_class = SystemNotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        # BUG-022 (écriture) : aucun flux légitime du frontend ne crée ou
        # ne modifie une notification via l'API — `create_notification()`
        # (core/utils.py) les insère directement en base depuis le code
        # serveur. Un utilisateur non-HQ ne doit donc jamais pouvoir POSTer
        # ou PATCHer un `node_origin` falsifié (ex. "CLOUD" pour usurper une
        # alerte siège) : on réserve create/update/partial_update au siège.
        # list/retrieve/destroy/mark_read/mark_all_read restent disponibles
        # à tout utilisateur authentifié, filtrés par `get_queryset()`.
        if self.action in ('create', 'update', 'partial_update'):
            return [IsHeadquarters()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            # BUG-022 : SystemNotification n'a pas de FK `node` mais un
            # `node_origin` (code de boulangerie ou 'CLOUD' pour les
            # alertes globales/siège, toujours visibles de tous).
            qs = qs.filter(node_origin__in=[user.node.code, 'CLOUD'])
        return qs

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """Mark all unread notifications as read (dans le périmètre de l'utilisateur)."""
        self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({'status': 'notifications marked read'})

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Mark a single notification as read."""
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({'status': 'notification marked read'})


class ColisDistributionViewSet(viewsets.ModelViewSet):
    serializer_class = ColisDistributionSerializer
    permission_classes = [IsGerant]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['node', 'year']

    def get_queryset(self):
        qs = ColisDistribution.objects.select_related('node').all()
        user = self.request.user
        if not user.can_access_all_nodes and user.node_id:
            # BUG-022 : aucun filtrage par nœud auparavant.
            qs = qs.filter(node=user.node)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not user.can_access_all_nodes:
            # BUG-022 (écriture) : `serializer.save()` sans argument laissait
            # passer n'importe quel `node` forgé dans le payload pour un
            # non-HQ — même motif que ClientViewSet (BUG-025).
            obj = serializer.save(node=user.node)
        else:
            obj = serializer.save()
        obj.compute_total()
        obj.save(update_fields=['total_value'])

    def perform_update(self, serializer):
        user = self.request.user
        if not user.can_access_all_nodes:
            obj = serializer.save(node=user.node)
        else:
            obj = serializer.save()
        obj.compute_total()
        obj.save(update_fields=['total_value'])

