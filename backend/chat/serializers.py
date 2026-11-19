from rest_framework import serializers

from .models import MAX_MESSAGE_LENGTH, Message


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'sender_name', 'is_mine', 'body', 'created_at']
        read_only_fields = fields

    def get_sender_name(self, obj):
        return obj.sender.get_full_name() or obj.sender.username

    def get_is_mine(self, obj):
        request = self.context.get('request')
        return bool(request and obj.sender_id == request.user.pk)


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(
        max_length=MAX_MESSAGE_LENGTH, trim_whitespace=True,
        error_messages={
            'blank': "Le message ne peut pas être vide.",
            'required': "Le message est obligatoire.",
            'max_length': f"Le message ne peut pas dépasser {MAX_MESSAGE_LENGTH} caractères.",
        })
