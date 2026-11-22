"""BUG-517 (nœud SIEGE non supprimable) et BUG-523 (fil de discussion du nœud conservé)."""
from django.test import TestCase
from rest_framework.test import APIClient

from chat.models import Conversation, Message, Participant
from core.models import ActivityLog, Node, User


class NodeDeleteGuards(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('g_admin', password='x', role='ADMIN')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def delete(self, node):
        return self.api.delete(f'/api/core/nodes/{node.pk}/')

    def test_siege_cannot_be_deleted(self):
        s = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siège'})[0]
        r = self.delete(s)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('SIEGE', r.json()['detail'])
        self.assertTrue(Node.objects.filter(pk=s.pk).exists())
        self.assertFalse(ActivityLog.objects.filter(action='DELETE').exists())

    def test_node_with_messages_cannot_be_deleted(self):
        n = Node.objects.create(code='K8', name='TEST CHAT')
        u = User.objects.create_user('g_old', password='x', role='GERANT', node=n, is_active=False)
        conv = Conversation.objects.create(kind='NODE', node=n)
        Participant.objects.create(conversation=conv, user=u)
        Message.objects.create(conversation=conv, sender=u, body='bonjour')
        r = self.delete(n)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('discussion', r.json()['detail'])
        self.assertTrue(Node.objects.filter(pk=n.pk).exists())
        self.assertEqual(Message.objects.filter(conversation=conv).count(), 1)

    def test_node_with_empty_conversation_can_be_deleted(self):
        n = Node.objects.create(code='K9', name='TEST VIDE')
        Conversation.objects.create(kind='NODE', node=n)
        r = self.delete(n)
        self.assertEqual(r.status_code, 204, r.content)
        self.assertFalse(Node.objects.filter(pk=n.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='DELETE').exists())
