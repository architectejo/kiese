"""Tests de la messagerie (BUG-307) : isolation, IDs forgés, 401/403, non-lus,
pagination, anti-flood, six rôles, journal sans contenu."""
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from chat.models import Conversation, Message
from core.models import ActivityLog, Node

User = get_user_model()
ROLES = ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR']
BASE = '/api/chat/'


def mk(username, role, node=None):
    return User.objects.create_user(
        username=username, password='x-Strong-pass-1', role=role, node=node,
        first_name=username.capitalize(), last_name='Test', email=f'{username}@secret.test',
        phone='0990000000')


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class ChatBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code='K1', name='DEMO K1', team_rotation_enabled=False)
        cls.k2 = Node.objects.create(code='K2', name='DEMO K2', team_rotation_enabled=False)
        cls.admin = mk('admin1', 'ADMIN')
        cls.dir = mk('dir1', 'DIRECTION')
        cls.compta = mk('compta1', 'COMPTABLE')
        cls.gerant = mk('gerant1', 'GERANT', cls.k1)
        cls.fact = mk('fact1', 'FACTURIER', cls.k1)
        cls.liv = mk('liv1', 'LIVREUR', cls.k1)
        cls.fact2 = mk('fact2', 'FACTURIER', cls.k2)
        cls.all = [cls.admin, cls.dir, cls.compta, cls.gerant, cls.fact, cls.liv]

    def direct(self, a, b):
        r = client_for(a).post(BASE + 'conversations/direct/', {'user': str(b.pk)}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        return r.data['id']

    def send(self, user, conv_id, body='Bonjour'):
        return client_for(user).post(
            f'{BASE}conversations/{conv_id}/messages/', {'body': body}, format='json')


class AuthTests(ChatBase):
    def test_anonymous_401(self):
        c = APIClient()
        for url in ('conversations/', 'users/', 'unread-count/', 'conversations/node/'):
            self.assertEqual(c.get(BASE + url).status_code, 401, url)
        self.assertEqual(c.post(BASE + 'conversations/direct/', {}, format='json').status_code, 401)

    def test_all_six_roles_can_list_and_chat(self):
        for u in self.all:
            self.assertEqual(client_for(u).get(BASE + 'conversations/').status_code, 200, u.role)
            self.assertEqual(client_for(u).get(BASE + 'users/').status_code, 200, u.role)
        # chaque rôle écrit à un autre rôle, y compris entre boulangeries
        for u in self.all:
            conv = self.direct(u, self.fact2)
            self.assertEqual(self.send(u, conv, f'salut de {u.role}').status_code, 201, u.role)

    def test_group_threads_by_role(self):
        for u in (self.admin, self.dir, self.compta):
            r = client_for(u).get(BASE + 'conversations/direction/')
            self.assertEqual(r.status_code, 200, u.role)
        for u in (self.gerant, self.fact, self.liv):
            self.assertEqual(client_for(u).get(BASE + 'conversations/direction/').status_code, 403)
            self.assertEqual(client_for(u).get(BASE + 'conversations/node/').status_code, 200)
        # HQ sans boulangerie : pas de fil boulangerie
        r = client_for(self.dir).get(BASE + 'conversations/node/')
        self.assertEqual(r.status_code, 403)
        self.assertIn('detail', r.data)


class IsolationTests(ChatBase):
    def test_non_participant_gets_404_everywhere(self):
        conv = self.direct(self.fact, self.liv)
        self.send(self.fact, conv)
        intruder = client_for(self.fact2)
        self.assertEqual(intruder.get(f'{BASE}conversations/{conv}/messages/').status_code, 404)
        self.assertEqual(self.send(self.fact2, conv).status_code, 404)
        self.assertEqual(intruder.post(f'{BASE}conversations/{conv}/read/').status_code, 404)
        # même la direction ne lit pas un privé dont elle n'est pas membre
        self.assertEqual(client_for(self.dir).get(f'{BASE}conversations/{conv}/messages/').status_code, 404)

    def test_forged_ids_404(self):
        c = client_for(self.fact)
        for forged in (str(uuid.uuid4()), 'not-a-uuid', '1', '../etc'):
            self.assertEqual(c.get(f'{BASE}conversations/{forged}/messages/').status_code, 404, forged)
            self.assertEqual(c.post(f'{BASE}conversations/{forged}/read/').status_code, 404, forged)
        r = c.post(BASE + 'conversations/direct/', {'user': str(uuid.uuid4())}, format='json')
        self.assertEqual(r.status_code, 404)
        r = c.post(BASE + 'conversations/direct/', {'user': 'zzz'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertIn('detail', r.data)

    def test_list_only_my_conversations(self):
        self.direct(self.fact, self.liv)
        self.direct(self.fact2, self.dir)
        ids = {c['id'] for c in client_for(self.fact).get(BASE + 'conversations/').data}
        for c in client_for(self.fact2).get(BASE + 'conversations/').data:
            if c['kind'] == 'DIRECT':
                self.assertNotIn(c['id'], ids)
        kinds = [c['kind'] for c in client_for(self.fact).get(BASE + 'conversations/').data]
        self.assertEqual(sorted(kinds), ['DIRECT', 'NODE'])

    def test_node_thread_isolated_between_bakeries(self):
        node_conv = client_for(self.fact).get(BASE + 'conversations/node/').data['id']
        client_for(self.fact2).get(BASE + 'conversations/node/')
        self.assertEqual(client_for(self.fact2).get(f'{BASE}conversations/{node_conv}/messages/').status_code, 404)
        self.send(self.fact, node_conv, 'pour K1')
        r = client_for(self.liv).get(f'{BASE}conversations/{node_conv}/messages/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 1)

    def test_directory_has_no_sensitive_data(self):
        r = client_for(self.fact).get(BASE + 'users/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), len(self.all) + 1 - 1)  # tous sauf soi
        self.assertNotIn(str(self.fact.pk), [u['id'] for u in r.data])
        for u in r.data:
            self.assertEqual(set(u), {'id', 'name', 'role', 'role_label', 'node', 'node_code'})
        raw = str(r.content)
        self.assertNotIn('secret.test', raw)
        self.assertNotIn('0990000000', raw)
        self.assertNotIn('password', raw)

    def test_directory_excludes_inactive_and_filters(self):
        self.liv.is_active = False
        self.liv.save()
        names = [u['name'] for u in client_for(self.fact).get(BASE + 'users/').data]
        self.assertNotIn('Liv1 Test', names)
        r = client_for(self.fact).get(BASE + 'users/?search=gerant')
        self.assertEqual([u['name'] for u in r.data], ['Gerant1 Test'])


class MessageTests(ChatBase):
    def test_send_and_history(self):
        conv = self.direct(self.fact, self.liv)
        r = self.send(self.fact, conv, '  Salut  ')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['body'], 'Salut')
        self.assertTrue(r.data['is_mine'])
        h = client_for(self.liv).get(f'{BASE}conversations/{conv}/messages/')
        self.assertEqual(h.data['count'], 1)
        self.assertFalse(h.data['results'][0]['is_mine'])
        self.assertEqual(Message.objects.get().node_origin, 'K1')

    def test_direct_is_idempotent_and_symmetric(self):
        a = self.direct(self.fact, self.liv)
        b = self.direct(self.liv, self.fact)
        self.assertEqual(a, b)
        self.assertEqual(Conversation.objects.filter(kind='DIRECT').count(), 1)
        r = client_for(self.fact).post(BASE + 'conversations/direct/', {'user': str(self.fact.pk)}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_validation_errors_french_detail(self):
        conv = self.direct(self.fact, self.liv)
        for body in ('', '   ', None):
            r = client_for(self.fact).post(f'{BASE}conversations/{conv}/messages/', {'body': body}, format='json')
            self.assertEqual(r.status_code, 400)
            self.assertIn('detail', r.data)
        self.assertEqual(self.send(self.fact, conv, 'x' * 2000).status_code, 201)
        r = self.send(self.fact, conv, 'x' * 2001)
        self.assertEqual(r.status_code, 400)
        self.assertIn('2000', r.data['detail'])

    def test_messages_immutable(self):
        conv = self.direct(self.fact, self.liv)
        mid = self.send(self.fact, conv).data['id']
        c = client_for(self.fact)
        for url in (f'{BASE}conversations/{conv}/messages/', f'{BASE}conversations/{conv}/messages/{mid}/'):
            for method in ('put', 'patch', 'delete'):
                self.assertIn(getattr(c, method)(url, {'body': 'z'}, format='json').status_code, (404, 405))
        msg = Message.objects.get(pk=mid)
        msg.body = 'modifié'
        with self.assertRaises(ValueError):
            msg.save()
        self.assertEqual(Message.objects.get(pk=mid).body, 'Bonjour')

    def test_cannot_send_to_inactive_recipient(self):
        conv = self.direct(self.fact, self.liv)
        self.liv.is_active = False
        self.liv.save()
        r = self.send(self.fact, conv)
        self.assertEqual(r.status_code, 403)
        self.assertIn('detail', r.data)

    def test_user_moved_out_of_node_loses_thread_write(self):
        node_conv = client_for(self.fact).get(BASE + 'conversations/node/').data['id']
        self.fact.node = self.k2
        self.fact.save()
        self.assertEqual(self.send(self.fact, node_conv).status_code, 403)

    def test_activity_log_has_no_message_content(self):
        conv = self.direct(self.fact, self.liv)
        self.send(self.fact, conv, 'CONTENU-CONFIDENTIEL-XYZ')
        for log in ActivityLog.objects.all():
            self.assertNotIn('CONTENU-CONFIDENTIEL-XYZ', log.description)

    @override_settings(CHAT_FLOOD_MAX_MESSAGES=3, CHAT_FLOOD_WINDOW_SECONDS=60)
    def test_flood_limit_429(self):
        conv = self.direct(self.fact, self.liv)
        for _ in range(3):
            self.assertEqual(self.send(self.fact, conv).status_code, 201)
        r = self.send(self.fact, conv)
        self.assertEqual(r.status_code, 429)
        self.assertIn('detail', r.data)
        # un autre utilisateur n'est pas bloqué
        self.assertEqual(self.send(self.liv, conv).status_code, 201)


class UnreadAndPaginationTests(ChatBase):
    def test_unread_counters_and_mark_read(self):
        conv = self.direct(self.fact, self.liv)
        for i in range(3):
            self.send(self.fact, conv, f'm{i}')
        # expéditeur : 0 non-lu
        self.assertEqual(client_for(self.fact).get(BASE + 'unread-count/').data['unread_count'], 0)
        # destinataire : 3
        self.assertEqual(client_for(self.liv).get(BASE + 'unread-count/').data['unread_count'], 3)
        lst = client_for(self.liv).get(BASE + 'conversations/').data
        direct = [c for c in lst if c['kind'] == 'DIRECT'][0]
        self.assertEqual(direct['unread_count'], 3)
        self.assertEqual(direct['last_message']['body'], 'm2')
        self.assertEqual(direct['title'], 'Fact1 Test')
        r = client_for(self.liv).post(f'{BASE}conversations/{conv}/read/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client_for(self.liv).get(BASE + 'unread-count/').data['unread_count'], 0)
        # l'expéditeur n'a pas été affecté, nouveau message => 1 non-lu
        self.send(self.fact, conv, 'm3')
        self.assertEqual(client_for(self.liv).get(BASE + 'unread-count/').data['unread_count'], 1)

    def test_group_thread_unread_for_members_only(self):
        node_conv = client_for(self.fact).get(BASE + 'conversations/node/').data['id']
        self.send(self.fact, node_conv, 'hello K1')
        self.assertEqual(client_for(self.gerant).get(BASE + 'unread-count/').data['unread_count'], 1)
        self.assertEqual(client_for(self.liv).get(BASE + 'unread-count/').data['unread_count'], 1)
        self.assertEqual(client_for(self.fact2).get(BASE + 'unread-count/').data['unread_count'], 0)
        self.assertEqual(client_for(self.fact).get(BASE + 'unread-count/').data['unread_count'], 0)

    def test_direction_thread(self):
        conv = client_for(self.dir).get(BASE + 'conversations/direction/').data['id']
        self.assertEqual(self.send(self.dir, conv, 'note direction').status_code, 201)
        self.assertEqual(client_for(self.compta).get(BASE + 'unread-count/').data['unread_count'], 1)
        self.assertEqual(client_for(self.fact).get(BASE + 'unread-count/').data['unread_count'], 0)
        self.assertEqual(client_for(self.fact).get(f'{BASE}conversations/{conv}/messages/').status_code, 404)

    def test_pagination_newest_first(self):
        conv = self.direct(self.fact, self.liv)
        with override_settings(CHAT_FLOOD_MAX_MESSAGES=1000):
            for i in range(35):
                self.send(self.fact, conv, f'msg{i}')
        c = client_for(self.liv)
        p1 = c.get(f'{BASE}conversations/{conv}/messages/').data
        self.assertEqual(p1['count'], 35)
        self.assertEqual(len(p1['results']), 30)
        self.assertEqual(p1['results'][0]['body'], 'msg34')
        self.assertIsNotNone(p1['next'])
        p2 = c.get(f'{BASE}conversations/{conv}/messages/?page=2').data
        self.assertEqual(len(p2['results']), 5)
        self.assertEqual(p2['results'][-1]['body'], 'msg0')
        small = c.get(f'{BASE}conversations/{conv}/messages/?page_size=10').data
        self.assertEqual(len(small['results']), 10)
        big = c.get(f'{BASE}conversations/{conv}/messages/?page_size=9999').data
        self.assertEqual(len(big['results']), 35)
