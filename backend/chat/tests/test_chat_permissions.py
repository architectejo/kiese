"""Verification independante de la messagerie (BUG-307) par testeur-permissions.
Rapport : docs/qa/rapports/testeur-permissions-2026-11-19-chat.md"""
import uuid
from unittest import expectedFailure

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from chat.models import Conversation, Message
from core.models import ActivityLog, Node

User = get_user_model()
ROLES = ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR']
B = '/api/chat/'


def mk(username, role, node=None):
    return User.objects.create_user(
        username=username, password='x-Strong-pass-1', role=role, node=node,
        first_name=username.capitalize(), last_name='Qa',
        email=f'{username}@secret.test', phone='0991112223')


def cl(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code='K1', name='QA K1')
        cls.k2 = Node.objects.create(code='K2', name='QA K2')
        cls.admin = mk('qadmin', 'ADMIN')
        cls.dir = mk('qdir', 'DIRECTION')
        cls.compta = mk('qcompta', 'COMPTABLE')
        cls.gerant = mk('qgerant', 'GERANT', cls.k1)
        cls.fact = mk('qfact', 'FACTURIER', cls.k1)
        cls.liv = mk('qliv', 'LIVREUR', cls.k1)
        cls.fact2 = mk('qfact2', 'FACTURIER', cls.k2)
        cls.liv2 = mk('qliv2', 'LIVREUR', cls.k2)
        cls.all = [cls.admin, cls.dir, cls.compta, cls.gerant, cls.fact, cls.liv]

    def direct(self, a, b):
        r = cl(a).post(B + 'conversations/direct/', {'user': str(b.pk)}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        return r.data['id']

    def send(self, u, cid, body='salut'):
        return cl(u).post(f'{B}conversations/{cid}/messages/', {'body': body}, format='json')


class Anonymous(Base):
    def test_all_endpoints_401(self):
        c = APIClient()
        fid = uuid.uuid4()
        for m, url in [('get', 'conversations/'), ('post', 'conversations/direct/'),
                       ('get', 'conversations/node/'), ('get', 'conversations/direction/'),
                       ('get', f'conversations/{fid}/messages/'),
                       ('post', f'conversations/{fid}/messages/'),
                       ('post', f'conversations/{fid}/read/'),
                       ('get', 'unread-count/'), ('get', 'users/')]:
            self.assertEqual(getattr(c, m)(B + url).status_code, 401, (m, url))

    def test_garbage_token_401(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION='Bearer not.a.jwt')
        self.assertEqual(c.get(B + 'conversations/').status_code, 401)


class RolesMatrix(Base):
    def test_six_roles_all_endpoints(self):
        for u in self.all:
            c = cl(u)
            self.assertEqual(c.get(B + 'conversations/').status_code, 200, u.role)
            self.assertEqual(c.get(B + 'unread-count/').status_code, 200, u.role)
            self.assertEqual(c.get(B + 'users/').status_code, 200, u.role)
            exp_node = 200 if u.node_id else 403
            self.assertEqual(c.get(B + 'conversations/node/').status_code, exp_node, u.role)
            exp_dir = 200 if u.is_headquarters else 403
            self.assertEqual(c.get(B + 'conversations/direction/').status_code, exp_dir, u.role)

    def test_direction_thread_forbidden_for_field_roles_even_via_id(self):
        r = cl(self.dir).get(B + 'conversations/direction/')
        did = r.data['id']
        self.send(self.dir, did, 'secret direction')
        for u in (self.gerant, self.fact, self.liv, self.fact2):
            self.assertEqual(cl(u).get(f'{B}conversations/{did}/messages/').status_code, 404, u.role)
            self.assertEqual(self.send(u, did, 'intrus').status_code, 404, u.role)
            self.assertEqual(cl(u).post(f'{B}conversations/{did}/read/').status_code, 404, u.role)
            ids = [c['id'] for c in cl(u).get(B + 'conversations/').data]
            self.assertNotIn(did, ids)
        # les 3 roles siege voient le message
        for u in (self.admin, self.compta):
            cl(u).get(B + 'conversations/direction/')
            self.assertEqual(cl(u).get(f'{B}conversations/{did}/messages/').data['count'], 1)

    def test_node_thread_other_bakery_isolated(self):
        nid = cl(self.fact).get(B + 'conversations/node/').data['id']
        self.send(self.fact, nid, 'info K1')
        for u in (self.fact2, self.liv2):
            self.assertEqual(cl(u).get(f'{B}conversations/{nid}/messages/').status_code, 404)
            self.assertEqual(self.send(u, nid, 'x').status_code, 404)
        # K2 a son propre fil
        nid2 = cl(self.fact2).get(B + 'conversations/node/').data['id']
        self.assertNotEqual(nid, nid2)
        # un user siege n'a pas acces au fil K1
        self.assertEqual(cl(self.admin).get(f'{B}conversations/{nid}/messages/').status_code, 404)

    def test_node_thread_members_k1_only(self):
        nid = cl(self.fact).get(B + 'conversations/node/').data['id']
        self.send(self.fact, nid, 'k1')
        self.assertEqual(cl(self.liv).get(f'{B}conversations/{nid}/messages/').data['count'], 1)
        self.assertEqual(cl(self.gerant).get(f'{B}conversations/{nid}/messages/').data['count'], 1)


class ForgedIds(Base):
    def test_malformed_and_unknown_ids_404(self):
        c = cl(self.fact)
        for bad in ('abc', '1', 'x' * 200, str(uuid.uuid4()), '00000000-0000-0000-0000-000000000000',
                    "1' OR '1'='1", '%00', '..%2f..'):
            for m, suf in (('get', 'messages/'), ('post', 'messages/'), ('post', 'read/')):
                r = getattr(c, m)(f'{B}conversations/{bad}/{suf}', {'body': 'x'}, format='json')
                self.assertIn(r.status_code, (404,), (bad, m, suf, r.status_code))

    def test_direct_forged_user_ids(self):
        c = cl(self.fact)
        for bad in (None, '', 'abc', 123, [], {}, str(uuid.uuid4()), "' OR 1=1"):
            r = c.post(B + 'conversations/direct/', {'user': bad}, format='json')
            self.assertEqual(r.status_code, 404, bad)
        self.assertEqual(c.post(B + 'conversations/direct/', {'user': str(self.fact.pk)},
                                format='json').status_code, 400)

    def test_direct_inactive_user_404(self):
        self.liv.is_active = False
        self.liv.save()
        r = cl(self.fact).post(B + 'conversations/direct/', {'user': str(self.liv.pk)}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_other_users_direct_conversation_404(self):
        cid = self.direct(self.fact, self.fact2)
        self.send(self.fact, cid, 'prive')
        for u in (self.gerant, self.liv, self.admin, self.dir, self.liv2):
            c = cl(u)
            self.assertEqual(c.get(f'{B}conversations/{cid}/messages/').status_code, 404, u.role)
            self.assertEqual(self.send(u, cid).status_code, 404)
            self.assertEqual(c.post(f'{B}conversations/{cid}/read/').status_code, 404)
            self.assertNotIn(cid, [x['id'] for x in c.get(B + 'conversations/').data])
        # un tiers qui rouvre "direct" avec l'un des deux ne recupere pas cette conv
        cid2 = self.direct(self.admin, self.fact)
        self.assertNotEqual(cid, cid2)


class Injection(Base):
    def test_body_injection_ignored(self):
        cid = self.direct(self.fact, self.fact2)
        forged = {'body': 'hello', 'sender': str(self.admin.pk), 'node': self.k2.pk,
                  'conversation': str(uuid.uuid4()), 'participants': [str(self.admin.pk)],
                  'node_origin': 'ZZ', 'id': str(uuid.uuid4()), 'created_at': '2000-01-01T00:00:00Z'}
        r = cl(self.fact).post(f'{B}conversations/{cid}/messages/', forged, format='json')
        self.assertEqual(r.status_code, 201)
        m = Message.objects.get(pk=r.data['id'])
        self.assertEqual(m.sender_id, self.fact.pk)
        self.assertEqual(str(m.conversation_id), cid)
        self.assertNotEqual(str(m.pk), forged['id'])
        self.assertGreater(m.created_at.year, 2020)
        self.assertEqual(m.node_origin, 'K1')
        self.assertFalse(Conversation.objects.get(pk=cid).participants
                         .filter(user=self.admin).exists())

    def test_direct_body_extra_fields_ignored(self):
        r = cl(self.fact).post(B + 'conversations/direct/', {
            'user': str(self.fact2.pk), 'participants': [str(self.admin.pk)],
            'node': self.k2.pk, 'kind': 'DIRECTION'}, format='json')
        self.assertIn(r.status_code, (200, 201))
        conv = Conversation.objects.get(pk=r.data['id'])
        self.assertEqual(conv.kind, 'DIRECT')
        self.assertIsNone(conv.node_id)
        self.assertEqual(conv.participants.count(), 2)

    def test_direct_conversation_with_headquarters_not_a_direction_thread(self):
        # une conversation privee avec l'admin ne donne pas acces au fil Direction
        self.direct(self.fact, self.admin)
        self.assertEqual(cl(self.fact).get(B + 'conversations/direction/').status_code, 403)

    def test_query_param_cannot_override(self):
        cid = self.direct(self.fact, self.fact2)
        self.send(self.fact, cid)
        r = cl(self.gerant).get(f'{B}conversations/?user={self.fact.pk}&node={self.k1.pk}')
        self.assertNotIn(cid, [x['id'] for x in r.data])


class Immutability(Base):
    def test_no_put_patch_delete(self):
        cid = self.direct(self.fact, self.liv)
        mid = self.send(self.fact, cid, 'orig').data['id']
        c = cl(self.fact)
        urls = [f'{B}conversations/{cid}/messages/', f'{B}conversations/{cid}/messages/{mid}/',
                f'{B}conversations/{cid}/', f'{B}conversations/', f'{B}unread-count/',
                f'{B}users/', f'{B}conversations/{cid}/read/', f'{B}conversations/node/']
        for url in urls:
            for m in ('put', 'patch', 'delete'):
                r = getattr(c, m)(url, {'body': 'hack'}, format='json')
                self.assertIn(r.status_code, (404, 405), (m, url, r.status_code))
        self.assertEqual(Message.objects.get(pk=mid).body, 'orig')
        self.assertEqual(Message.objects.filter(conversation_id=cid).count(), 1)

    def test_model_resave_refused(self):
        cid = self.direct(self.fact, self.liv)
        m = Message.objects.get(pk=self.send(self.fact, cid).data['id'])
        m.body = 'x'
        with self.assertRaises(ValueError):
            m.save()


class Directory(Base):
    def test_no_sensitive_fields(self):
        allowed = {'id', 'name', 'role', 'role_label', 'node', 'node_code'}
        for u in self.all:
            r = cl(u).get(B + 'users/')
            self.assertEqual(r.status_code, 200)
            self.assertNotIn(str(u.pk), [x['id'] for x in r.data])
            for x in r.data:
                self.assertEqual(set(x), allowed)
            raw = r.content.decode()
            for s in ('@secret.test', '0991112223', 'password', 'pbkdf2', 'is_superuser'):
                self.assertNotIn(s, raw)

    def test_inactive_excluded_and_search(self):
        self.liv2.is_active = False
        self.liv2.save()
        ids = [x['id'] for x in cl(self.fact).get(B + 'users/').data]
        self.assertNotIn(str(self.liv2.pk), ids)
        r = cl(self.fact).get(B + 'users/?search=qadmin')
        self.assertEqual([x['id'] for x in r.data], [str(self.admin.pk)])
        # la recherche ne permet pas de deviner email/telephone
        self.assertEqual(cl(self.fact).get(B + 'users/?search=secret.test').data, [])
        self.assertEqual(cl(self.fact).get(B + 'users/?search=0991112223').data, [])


class XssAndLimits(Base):
    def test_xss_returned_verbatim(self):
        cid = self.direct(self.fact, self.liv)
        payload = '<script>alert(1)</script><img src=x onerror=alert(1)>'
        r = self.send(self.fact, cid, payload)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['body'], payload)
        self.assertTrue(r['Content-Type'].startswith('application/json'))

    def test_length_2000(self):
        cid = self.direct(self.fact, self.liv)
        self.assertEqual(self.send(self.fact, cid, 'a' * 2000).status_code, 201)
        r = self.send(self.fact, cid, 'a' * 2001)
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)
        for bad in ('', '   ', None):
            self.assertEqual(self.send(self.fact, cid, bad).status_code, 400)
        r = cl(self.fact).post(f'{B}conversations/{cid}/messages/', {'body': ['a', 'b']}, format='json')
        self.assertEqual(r.status_code, 400)
        r = cl(self.fact).post(f'{B}conversations/{cid}/messages/', {}, format='json')
        self.assertEqual(r.status_code, 400)

    @override_settings(CHAT_FLOOD_MAX_MESSAGES=3, CHAT_FLOOD_WINDOW_SECONDS=60)
    def test_flood_429_per_user(self):
        cid = self.direct(self.fact, self.liv)
        for _ in range(3):
            self.assertEqual(self.send(self.fact, cid).status_code, 201)
        self.assertEqual(self.send(self.fact, cid).status_code, 429)
        # contournement par une autre conversation : toujours limite
        cid2 = self.direct(self.fact, self.gerant)
        self.assertEqual(self.send(self.fact, cid2).status_code, 429)
        # un autre utilisateur n'est pas bloque
        self.assertEqual(self.send(self.liv, cid).status_code, 201)

    def test_pagination_abuse(self):
        cid = self.direct(self.fact, self.liv)
        Message.objects.bulk_create([
            Message(conversation_id=cid, sender=self.fact, body=f'm{i}', node_origin='K1')
            for i in range(150)])
        c = cl(self.liv)
        r = c.get(f'{B}conversations/{cid}/messages/')
        self.assertEqual(len(r.data['results']), 30)
        self.assertEqual(r.data['count'], 150)
        r = c.get(f'{B}conversations/{cid}/messages/?page_size=100000')
        self.assertEqual(len(r.data['results']), 100)
        for ps in ('-1', '0', 'abc', '1e9'):
            r = c.get(f'{B}conversations/{cid}/messages/?page_size={ps}')
            self.assertEqual(r.status_code, 200, ps)
            self.assertLessEqual(len(r.data['results']), 100)
        for pg in ('0', '-1', 'abc', '9999'):
            self.assertEqual(c.get(f'{B}conversations/{cid}/messages/?page={pg}').status_code, 404, pg)
        # plus recent d'abord
        r = c.get(f'{B}conversations/{cid}/messages/?page_size=5')
        ts = [x['created_at'] for x in r.data['results']]
        self.assertEqual(ts, sorted(ts, reverse=True))


class Unread(Base):
    def test_unread_consistency(self):
        cid = self.direct(self.fact, self.liv)
        for _ in range(3):
            self.send(self.fact, cid)
        self.assertEqual(cl(self.liv).get(B + 'unread-count/').data['unread_count'], 3)
        self.assertEqual(cl(self.fact).get(B + 'unread-count/').data['unread_count'], 0)
        lst = {x['id']: x for x in cl(self.liv).get(B + 'conversations/').data}
        self.assertEqual(lst[cid]['unread_count'], 3)
        # un tiers n'est pas impacte
        self.assertEqual(cl(self.gerant).get(B + 'unread-count/').data['unread_count'], 0)
        r = cl(self.liv).post(f'{B}conversations/{cid}/read/')
        self.assertEqual(r.data['unread_count'], 0)
        self.assertEqual(cl(self.liv).get(B + 'unread-count/').data['unread_count'], 0)
        # lecture de l'historique seule ne marque pas lu
        self.send(self.fact, cid)
        cl(self.liv).get(f'{B}conversations/{cid}/messages/')
        self.assertEqual(cl(self.liv).get(B + 'unread-count/').data['unread_count'], 1)
        # un tiers ne peut pas marquer lu a ma place
        self.assertEqual(cl(self.gerant).post(f'{B}conversations/{cid}/read/').status_code, 404)
        self.assertEqual(cl(self.liv).get(B + 'unread-count/').data['unread_count'], 1)


class Deactivated(Base):
    def test_sender_deactivated_cannot_use_api(self):
        cid = self.direct(self.fact, self.liv)
        self.fact.is_active = False
        self.fact.save()
        c = APIClient()
        c.force_authenticate(User.objects.get(pk=self.fact.pk))
        # force_authenticate court-circuite is_active : on teste via vrai JWT
        from rest_framework_simplejwt.tokens import RefreshToken
        tok = str(RefreshToken.for_user(self.fact).access_token)
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        self.assertEqual(c2.get(B + 'conversations/').status_code, 401)
        self.assertEqual(c2.post(f'{B}conversations/{cid}/messages/', {'body': 'x'},
                                 format='json').status_code, 401)

    def test_recipient_deactivated_cannot_receive(self):
        cid = self.direct(self.fact, self.liv)
        self.liv.is_active = False
        self.liv.save()
        self.assertEqual(self.send(self.fact, cid).status_code, 403)

    def test_deactivated_not_in_group_threads(self):
        nid = cl(self.fact).get(B + 'conversations/node/').data['id']
        self.liv.is_active = False
        self.liv.save()
        self.send(self.fact, nid)
        # le desactive reste participant en base mais ne peut plus s'authentifier
        from rest_framework_simplejwt.tokens import RefreshToken
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.liv).access_token}')
        self.assertEqual(c.get(f'{B}conversations/{nid}/messages/').status_code, 401)


class StaleMembership(Base):
    """Un participant de fil de groupe conserve l'acces apres changement de
    boulangerie ou de role (les Participant ne sont jamais retires)."""

    def test_moved_user_loses_old_node_thread(self):
        nid = cl(self.fact).get(B + 'conversations/node/').data['id']
        self.send(self.gerant, nid, 'confidentiel K1')
        self.fact.node = self.k2
        self.fact.save()
        r = cl(User.objects.get(pk=self.fact.pk)).get(f'{B}conversations/{nid}/messages/')
        self.assertEqual(r.status_code, 404)

    def test_demoted_user_loses_direction_thread(self):
        did = cl(self.dir).get(B + 'conversations/direction/').data['id']
        cl(self.compta).get(B + 'conversations/direction/')
        self.send(self.dir, did, 'budget confidentiel')
        self.compta.role = 'FACTURIER'
        self.compta.node = self.k1
        self.compta.save()
        r = cl(User.objects.get(pk=self.compta.pk)).get(f'{B}conversations/{did}/messages/')
        self.assertEqual(r.status_code, 404)


class StaleMembershipExtra(Base):
    """Verification BUG-308 : cas supplementaires."""

    def fresh(self, u):
        return cl(User.objects.get(pk=u.pk))

    def test_moved_user_all_endpoints_then_return(self):
        nid = cl(self.fact).get(B + 'conversations/node/').data['id']
        cl(self.gerant).get(B + 'conversations/node/')
        self.send(self.gerant, nid, 'confidentiel K1')
        self.assertEqual(self.fresh(self.fact).get(B + 'unread-count/').data['unread_count'], 1)
        self.fact.node = self.k2
        self.fact.save()
        c = self.fresh(self.fact)
        self.assertEqual(c.get(f'{B}conversations/{nid}/messages/').status_code, 404)
        self.assertEqual(c.post(f'{B}conversations/{nid}/read/').status_code, 404)
        self.assertEqual(c.post(f'{B}conversations/{nid}/messages/', {'body': 'x'},
                                format='json').status_code, 403)
        lst = c.get(B + 'conversations/').data
        self.assertNotIn(nid, [x['id'] for x in lst])
        self.assertEqual(c.get(B + 'unread-count/').data['unread_count'], 0)
        self.assertFalse(Message.objects.filter(conversation_id=nid, sender=self.fact).exists())
        # il voit desormais le fil K2 uniquement
        nid2 = c.get(B + 'conversations/node/').data['id']
        self.assertNotEqual(nid, nid2)
        # retour en K1 : l'acces revient
        self.fact.node = self.k1
        self.fact.save()
        c = self.fresh(self.fact)
        self.assertEqual(c.get(f'{B}conversations/{nid}/messages/').status_code, 200)

    def test_demoted_all_endpoints_and_badge(self):
        did = cl(self.dir).get(B + 'conversations/direction/').data['id']
        cl(self.compta).get(B + 'conversations/direction/')
        self.send(self.dir, did, 'budget')
        self.assertEqual(self.fresh(self.compta).get(B + 'unread-count/').data['unread_count'], 1)
        self.compta.role = 'GERANT'
        self.compta.node = self.k1
        self.compta.save()
        c = self.fresh(self.compta)
        self.assertEqual(c.get(f'{B}conversations/{did}/messages/').status_code, 404)
        self.assertEqual(c.post(f'{B}conversations/{did}/read/').status_code, 404)
        self.assertEqual(c.post(f'{B}conversations/{did}/messages/', {'body': 'x'},
                                format='json').status_code, 403)
        self.assertNotIn(did, [x['id'] for x in c.get(B + 'conversations/').data])
        self.assertEqual(c.get(B + 'unread-count/').data['unread_count'], 0)
        self.assertEqual(c.get(B + 'conversations/direction/').status_code, 403)

    def test_direct_conversations_unaffected_by_role_change(self):
        cid = self.direct(self.fact, self.fact2)
        self.send(self.fact2, cid, 'perso')
        self.fact.node = self.k2
        self.fact.save()
        c = self.fresh(self.fact)
        self.assertEqual(c.get(f'{B}conversations/{cid}/messages/').status_code, 200)
        self.assertEqual(c.get(B + 'unread-count/').data['unread_count'], 1)

    def test_deactivated_member_cannot_access_group(self):
        nid = cl(self.fact).get(B + 'conversations/node/').data['id']
        cl(self.gerant).get(B + 'conversations/node/')
        self.send(self.gerant, nid, 'k1')
        self.fact.is_active = False
        self.fact.save()
        from rest_framework_simplejwt.tokens import RefreshToken
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.fact).access_token}')
        for url in (f'{B}conversations/{nid}/messages/', B + 'conversations/', B + 'unread-count/'):
            self.assertEqual(c.get(url).status_code, 401)
        # et l'envoi par un tiers reste possible sans le compter parmi les eligibles
        self.assertEqual(self.send(self.gerant, nid, 'encore').status_code, 201)

    def test_other_node_thread_never_listed_after_moves(self):
        n1 = cl(self.fact).get(B + 'conversations/node/').data['id']
        n2 = cl(self.fact2).get(B + 'conversations/node/').data['id']
        self.send(self.fact2, n2, 'k2 prive')
        self.fact.node = self.k2
        self.fact.save()
        c = self.fresh(self.fact)
        ids = [x['id'] for x in c.get(B + 'conversations/').data]
        self.assertNotIn(n1, ids)
        self.assertIn(n2, ids)
        self.assertEqual(c.get(f'{B}conversations/{n2}/messages/').data['count'], 1)


class NoLogging(Base):
    def test_no_content_in_activity_log(self):
        before = set(ActivityLog.objects.values_list('pk', flat=True))
        cid = self.direct(self.fact, self.liv)
        self.send(self.fact, cid, 'MOT-SECRET-XYZ')
        cl(self.liv).get(f'{B}conversations/{cid}/messages/')
        cl(self.liv).post(f'{B}conversations/{cid}/read/')
        # La creation paresseuse de Config (hors chat) journalise une fois : ignoree.
        new = list(ActivityLog.objects.exclude(pk__in=before)
                   .exclude(action='Modification Configuration').values())
        self.assertEqual(new, [])
        for log in ActivityLog.objects.all():
            self.assertNotIn('MOT-SECRET-XYZ', str(log.__dict__))
