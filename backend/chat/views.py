"""API de messagerie (BUG-307). Voir docs/qa/rapports/dev-backend-chat-2026-11-19.md."""
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.mixins import get_json_object
from .models import Conversation, Message, Participant
from .serializers import MessageCreateSerializer, MessageSerializer

User = get_user_model()


def _flood_limits():
    return (getattr(settings, 'CHAT_FLOOD_MAX_MESSAGES', 10),
            getattr(settings, 'CHAT_FLOOD_WINDOW_SECONDS', 30))


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _node_origin(user):
    return user.node.code if user.node_id else 'CLOUD'


def _display(user):
    return user.get_full_name() or user.username


def _eligible_group_users(conv):
    """Utilisateurs actifs autorisés dans un fil de groupe."""
    qs = User.objects.filter(is_active=True)
    if conv.kind == Conversation.Kind.NODE:
        return qs.filter(node_id=conv.node_id)
    return qs.filter(Q(is_superuser=True) | Q(role__in=['ADMIN', 'DIRECTION', 'COMPTABLE']))


def _can_access(conv, user):
    """BUG-308 : un fil de groupe exige l'éligibilité COURANTE (nœud / rôle)."""
    if conv.kind == Conversation.Kind.DIRECT:
        return True
    return _eligible_group_users(conv).filter(pk=user.pk).exists()


def _accessible_participations(user):
    """Participations de l'utilisateur, hors fils de groupe devenus interdits."""
    parts = Participant.objects.filter(user=user).select_related('conversation')
    return [p for p in parts if _can_access(p.conversation, user)]


def _get_or_create_group(kind, node=None):
    lookup = {'kind': kind, 'node': node}
    try:
        with transaction.atomic():
            conv, _ = Conversation.objects.get_or_create(
                **lookup, defaults={'node_origin': node.code if node else 'CLOUD'})
    except IntegrityError:
        conv = Conversation.objects.get(**lookup)
    return conv


def _ensure_participant(conv, user):
    Participant.objects.get_or_create(
        conversation=conv, user=user,
        defaults={'node_origin': _node_origin(user)})


def _ensure_group_threads(user):
    """Rattache l'utilisateur à ses fils de groupe (créés au besoin)."""
    if user.node_id:
        _ensure_participant(_get_or_create_group(Conversation.Kind.NODE, user.node), user)
    if user.is_headquarters:
        _ensure_participant(_get_or_create_group(Conversation.Kind.DIRECTION), user)


def _my_conversation_or_404(user, pk, check_access=True):
    """Conversation dont l'utilisateur est participant, sinon 404 (pas de fuite).
    check_access=False : le POST renvoie lui-même 403 (comportement BUG-307)."""
    cid = _parse_uuid(pk)
    conv = (Conversation.objects.filter(pk=cid, participants__user=user).first()
            if cid else None)
    if conv is None or (check_access and not _can_access(conv, user)):
        raise Http404("Conversation introuvable.")
    return conv


def _unread_qs(user, part):
    qs = Message.objects.filter(conversation_id=part.conversation_id).exclude(sender=user)
    if part.last_read_at:
        qs = qs.filter(created_at__gt=part.last_read_at)
    return qs


def _user_payload(u):
    return {
        'id': str(u.pk),
        'name': _display(u),
        'role': u.role,
        'role_label': u.get_role_display(),
        'node': u.node_id,
        'node_code': u.node.code if u.node_id else None,
    }


def _serialize_conversation(conv, user, request):
    part = Participant.objects.filter(conversation=conv, user=user).first()
    last = conv.messages.select_related('sender').first()
    data = {
        'id': str(conv.pk),
        'kind': conv.kind,
        'node': conv.node_id,
        'last_message_at': conv.last_message_at,
        'last_message': (MessageSerializer(last, context={'request': request}).data
                         if last else None),
        'unread_count': _unread_qs(user, part).count() if part else 0,
        'other_user': None,
    }
    if conv.kind == Conversation.Kind.DIRECT:
        other = (User.objects.select_related('node')
                 .filter(chat_participations__conversation=conv)
                 .exclude(pk=user.pk).first())
        data['title'] = _display(other) if other else 'Conversation'
        data['other_user'] = _user_payload(other) if other else None
    elif conv.kind == Conversation.Kind.NODE:
        data['title'] = f'Boulangerie {conv.node.code}'
    else:
        data['title'] = 'Direction'
    return data


class ConversationListView(APIView):
    """Conversations de l'utilisateur, avec dernier message et non-lus."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        _ensure_group_threads(user)
        convs = (Conversation.objects.filter(participants__user=user)
                 .select_related('node').distinct())
        return Response([_serialize_conversation(c, user, request)
                         for c in convs if _can_access(c, user)])


class DirectConversationView(APIView):
    """Crée ou retrouve la conversation 1-à-1 avec `user`."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        oid = _parse_uuid(get_json_object(request).get('user'))  # BUG-886
        other = (User.objects.select_related('node').filter(pk=oid, is_active=True).first()
                 if oid else None)
        if other is None:
            return Response({'detail': "Utilisateur introuvable."},
                            status=status.HTTP_404_NOT_FOUND)
        if other.pk == request.user.pk:
            return Response({'detail': "Vous ne pouvez pas converser avec vous-même."},
                            status=status.HTTP_400_BAD_REQUEST)
        key = ':'.join(sorted([str(request.user.pk), str(other.pk)]))
        created = False
        conv = Conversation.objects.filter(direct_key=key).first()
        if conv is None:
            try:
                with transaction.atomic():
                    conv = Conversation.objects.create(
                        kind=Conversation.Kind.DIRECT, direct_key=key,
                        node_origin=_node_origin(request.user))
                    created = True
            except IntegrityError:
                conv = Conversation.objects.get(direct_key=key)
        _ensure_participant(conv, request.user)
        _ensure_participant(conv, other)
        return Response(_serialize_conversation(conv, request.user, request),
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class GroupConversationView(APIView):
    """Fil de la boulangerie (kind=NODE) ou fil Direction (kind=DIRECTION)."""
    permission_classes = [IsAuthenticated]
    kind = None

    def get(self, request):
        user = request.user
        if self.kind == Conversation.Kind.NODE:
            if not user.node_id:
                return Response(
                    {'detail': "Aucune boulangerie n'est affectée à votre compte."},
                    status=status.HTTP_403_FORBIDDEN)
            conv = _get_or_create_group(self.kind, user.node)
        else:
            if not user.is_headquarters:
                return Response({'detail': "Le fil Direction est réservé à la direction."},
                                status=status.HTTP_403_FORBIDDEN)
            conv = _get_or_create_group(self.kind)
        _ensure_participant(conv, user)
        return Response(_serialize_conversation(conv, user, request))


class MessagePagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100


class MessageListCreateView(APIView):
    """GET : historique paginé (récent d'abord) ; POST : envoi.
    Pas de PUT/PATCH/DELETE (messages non modifiables)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        conv = _my_conversation_or_404(request.user, pk)
        qs = conv.messages.select_related('sender').order_by('-created_at', '-id')
        paginator = MessagePagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            MessageSerializer(page, many=True, context={'request': request}).data)

    def post(self, request, pk):
        user = request.user
        conv = _my_conversation_or_404(user, pk, check_access=False)
        ser = MessageCreateSerializer(data=request.data)
        if not ser.is_valid():
            errors = ser.errors.get('body') or ['Message invalide.']
            return Response({'detail': str(errors[0])}, status=status.HTTP_400_BAD_REQUEST)

        if conv.kind == Conversation.Kind.DIRECT:
            if not User.objects.filter(chat_participations__conversation=conv,
                                       is_active=True).exclude(pk=user.pk).exists():
                return Response({'detail': "Le destinataire n'est plus actif."},
                                status=status.HTTP_403_FORBIDDEN)
        elif not _eligible_group_users(conv).filter(pk=user.pk).exists():
            return Response({'detail': "Vous n'avez plus accès à ce fil."},
                            status=status.HTTP_403_FORBIDDEN)

        max_msgs, window = _flood_limits()
        since = timezone.now() - timedelta(seconds=window)
        if Message.objects.filter(sender=user, created_at__gte=since).count() >= max_msgs:
            return Response(
                {'detail': "Vous envoyez trop de messages. Patientez quelques secondes."},
                status=status.HTTP_429_TOO_MANY_REQUESTS)

        with transaction.atomic():
            msg = Message.objects.create(
                conversation=conv, sender=user, body=ser.validated_data['body'],
                node_origin=_node_origin(user))
            Conversation.objects.filter(pk=conv.pk).update(last_message_at=msg.created_at)
            if conv.kind != Conversation.Kind.DIRECT:
                existing = set(Participant.objects.filter(conversation=conv)
                               .values_list('user_id', flat=True))
                Participant.objects.bulk_create([
                    Participant(conversation=conv, user=u, node_origin=_node_origin(u))
                    for u in _eligible_group_users(conv).select_related('node')
                    if u.pk not in existing])
            Participant.objects.filter(conversation=conv, user=user).update(
                last_read_at=msg.created_at)
        # Volontairement pas de log_activity : le contenu des messages ne doit
        # pas être journalisé. Pas de create_notification non plus (la
        # notification système est globale, pas par destinataire) : le compteur
        # de non-lus sert d'alerte.
        return Response(MessageSerializer(msg, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)


class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conv = _my_conversation_or_404(request.user, pk)
        Participant.objects.filter(conversation=conv, user=request.user).update(
            last_read_at=timezone.now())
        return Response({'id': str(conv.pk), 'unread_count': 0})


class UnreadCountView(APIView):
    """Total de non-lus (compteur de l'en-tête, polling)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        total = sum(_unread_qs(user, p).count()
                    for p in _accessible_participations(user))
        return Response({'unread_count': total})


class UserDirectoryView(APIView):
    """Annuaire : utilisateurs actifs, sans donnée sensible (ni email, ni téléphone)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (User.objects.filter(is_active=True).exclude(pk=request.user.pk)
              .select_related('node').order_by('last_name', 'first_name', 'username'))
        q = (request.query_params.get('search') or '').strip()
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q)
                           | Q(username__icontains=q))
        return Response([_user_payload(u) for u in qs[:500]])
