"""Messagerie interne (BUG-307).

Hors chaîne de hash. Les messages ne sont jamais modifiés ni supprimés par les
utilisateurs. Modèles synchronisables (UUID + node_origin).
"""
from django.conf import settings
from django.db import models

from core.models import Node, SyncableModel

MAX_MESSAGE_LENGTH = 2000


class Conversation(SyncableModel):
    class Kind(models.TextChoices):
        DIRECT = 'DIRECT', 'Conversation privée'
        NODE = 'NODE', 'Fil de la boulangerie'
        DIRECTION = 'DIRECTION', 'Fil Direction'

    kind = models.CharField(max_length=10, choices=Kind.choices)
    node = models.ForeignKey(
        Node, null=True, blank=True, on_delete=models.CASCADE,
        related_name='chat_conversations',
    )
    # Clé canonique d'une conversation 1-à-1 : "<uuid_min>:<uuid_max>".
    direct_key = models.CharField(max_length=80, null=True, blank=True, unique=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ['-last_message_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['node'], condition=models.Q(kind='NODE'),
                name='chat_unique_node_thread',
            ),
            models.UniqueConstraint(
                fields=['kind'], condition=models.Q(kind='DIRECTION'),
                name='chat_unique_direction_thread',
            ),
        ]

    def __str__(self):
        return f'{self.kind} {self.pk}'


class Participant(SyncableModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='chat_participations')
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['conversation', 'user'], name='chat_unique_participant'),
        ]


class Message(SyncableModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='chat_messages')
    body = models.TextField(max_length=MAX_MESSAGE_LENGTH)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['conversation', '-created_at'])]

    def save(self, *args, **kwargs):
        # Messages non modifiables : toute réécriture est refusée.
        if not self._state.adding:
            raise ValueError("Un message ne peut pas être modifié.")
        super().save(*args, **kwargs)
