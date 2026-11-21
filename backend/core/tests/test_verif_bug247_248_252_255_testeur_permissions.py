"""Verification BUG-247, 248, 252, 255 (testeur-permissions, 2026-11-20b). Donnees fictives."""
from core.models import ActivityLog, Config, SystemNotification
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, User


class Bug247(Base):
    def u_url(self, u, suffix=''):
        return f'/api/core/users/{u.pk}/{suffix}'

    def test_direction_cannot_self_promote_or_move(self):
        d = self.u['DIRECTION']
        c = cl(d)
        for body in ({'role': 'ADMIN'}, {'node': str(self.k1.pk)}, {'is_active': False}):
            self.assertEqual(c.patch(self.u_url(d), body, format='json').status_code, 403, body)
        r = c.put(self.u_url(d), {'username': d.username, 'role': 'ADMIN'}, format='json')
        self.assertEqual(r.status_code, 403, r.content)
        r = c.patch(self.u_url(d), {'is_superuser': True, 'is_staff': True, 'first_name': 'X'}, format='json')
        self.assertEqual(r.status_code, 200)
        d.refresh_from_db()
        self.assertEqual((d.role, d.node, d.is_superuser, d.is_staff, d.is_active),
                         ('DIRECTION', None, False, False, True))

    def test_direction_cannot_touch_admin_nor_create_admin(self):
        c = cl(self.u['DIRECTION'])
        a = self.u['ADMIN']
        self.assertEqual(c.patch(self.u_url(a), {'first_name': 'Z'}, format='json').status_code, 403)
        self.assertEqual(c.delete(self.u_url(a)).status_code, 403)
        self.assertEqual(c.post(self.u_url(a, 'reset_password/')).status_code, 403)
        r = c.post('/api/core/users/', {'username': 'zz_new_admin', 'password': 'abcdef12', 'role': 'ADMIN'},
                   format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(User.objects.filter(username='zz_new_admin').exists())
        su = User.objects.create(username='zz_su', role='DIRECTION', is_superuser=True)
        self.assertEqual(c.post(self.u_url(su, 'reset_password/')).status_code, 403)
        self.assertEqual(c.patch(self.u_url(su), {'first_name': 'Q'}, format='json').status_code, 403)

    def test_direction_cannot_promote_other_user_to_admin(self):
        r = cl(self.u['DIRECTION']).patch(self.u_url(self.u['GERANT']), {'role': 'ADMIN'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.u['GERANT'].refresh_from_db()
        self.assertEqual(self.u['GERANT'].role, 'GERANT')

    def test_non_direction_roles_cannot_write_users(self):
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            u = self.u[role]
            c = cl(u)
            self.assertEqual(c.patch(self.u_url(u), {'role': 'ADMIN'}, format='json').status_code, 403, role)
            self.assertEqual(c.post('/api/core/users/', {'username': 'zz_' + role, 'password': 'abcdef12',
                                                         'role': 'ADMIN'}, format='json').status_code, 403, role)
            self.assertEqual(c.post(self.u_url(self.u['FACTURIER'], 'reset_password/')).status_code, 403, role)
            u.refresh_from_db()
            self.assertEqual(u.role, role)
        self.assertEqual(cl().patch(self.u_url(self.u['GERANT']), {}, format='json').status_code, 401)

    def test_self_delete_denied_admin_ok(self):
        d = self.u['DIRECTION']
        self.assertEqual(cl(d).delete(self.u_url(d)).status_code, 403)
        a = self.u['ADMIN']
        self.assertEqual(cl(a).post('/api/core/users/', {'username': 'zz_adm2', 'password': 'abcdef12',
                                                         'role': 'ADMIN'}, format='json').status_code, 201)
        self.assertEqual(cl(a).post(self.u_url(d, 'reset_password/')).status_code, 200)
        self.assertEqual(cl(a).delete(self.u_url(a)).status_code, 403)

    def test_create_ignores_superuser_forged(self):
        r = cl(self.u['ADMIN']).post('/api/core/users/', {
            'username': 'zz_f', 'password': 'abcdef12', 'role': 'FACTURIER', 'node': str(self.k1.pk),
            'is_superuser': True, 'is_staff': True}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        n = User.objects.get(username='zz_f')
        self.assertFalse(n.is_superuser or n.is_staff)


class Bug248(Base):
    def reset(self, target, actor=None):
        return cl(actor or self.u['DIRECTION']).post(f'/api/core/users/{target.pk}/reset_password/')

    def test_random_temp_password(self):
        t = self.u['FACTURIER']
        t.set_password(t.username)
        t.save()
        seen = set()
        for _ in range(3):
            r = self.reset(t)
            self.assertEqual(r.status_code, 200, r.content)
            tp = r.data['temporary_password']
            self.assertGreaterEqual(len(tp), 10)
            self.assertNotEqual(tp, t.username)
            self.assertNotIn(tp, r.data['detail'])
            t.refresh_from_db()
            self.assertTrue(t.check_password(tp))
            self.assertFalse(t.check_password(t.username))
            self.assertTrue(t.must_change_password)
            seen.add(tp)
        self.assertEqual(len(seen), 3)

    def test_secret_not_logged(self):
        tp = self.reset(self.u['LIVREUR']).data['temporary_password']
        for log in ActivityLog.objects.all():
            self.assertNotIn(tp, f'{log.action} {log.description}')

    def test_other_roles_denied_and_anonymous(self):
        t = self.u['LIVREUR']
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(self.reset(t, self.u[role]).status_code, 403, role)
        self.assertEqual(cl().post(f'/api/core/users/{t.pk}/reset_password/').status_code, 401)
        t.refresh_from_db()
        self.assertFalse(t.must_change_password)


class Bug252(Base):
    def setUp(self):
        self.n = SystemNotification.objects.create(title='Alerte siege', message='m', severity='WARNING',
                                                   node_origin='CLOUD')
        self.nk1 = SystemNotification.objects.create(title='K1', message='m', node_origin='P1')
        self.nk2 = SystemNotification.objects.create(title='K2', message='m', node_origin='P2')

    def url(self, n, s=''):
        return f'/api/core/notifications/{n.pk}/{s}'

    def test_non_hq_cannot_touch_cloud(self):
        for u in (self.u['GERANT'], self.u['FACTURIER'], self.u['LIVREUR'], self.u2['GERANT']):
            c = cl(u)
            self.assertEqual(c.delete(self.url(self.n)).status_code, 403, u.role)
            self.assertEqual(c.post(self.url(self.n, 'mark_read/')).status_code, 403, u.role)
            self.assertEqual(c.patch(self.url(self.n), {'is_read': True}, format='json').status_code, 403)
            self.assertEqual(c.post('/api/core/notifications/', {'title': 'x', 'message': 'y',
                             'node_origin': 'CLOUD'}, format='json').status_code, 403)
        self.n.refresh_from_db()
        self.assertFalse(self.n.is_read)

    def test_mark_all_read_spares_cloud_for_non_hq(self):
        r = cl(self.u['LIVREUR']).post('/api/core/notifications/mark_all_read/')
        self.assertEqual(r.status_code, 200)
        for o, expected in ((self.n, False), (self.nk1, True), (self.nk2, False)):
            o.refresh_from_db()
            self.assertEqual(o.is_read, expected, o.title)

    def test_cross_node_notification_hidden(self):
        c = cl(self.u['GERANT'])
        self.assertEqual(c.delete(self.url(self.nk2)).status_code, 404)
        self.assertEqual(c.post(self.url(self.nk2, 'mark_read/')).status_code, 404)
        self.assertTrue(SystemNotification.objects.filter(pk=self.nk2.pk).exists())
        self.assertEqual(c.delete(self.url(self.nk1)).status_code, 204)

    def test_hq_can(self):
        self.assertEqual(cl(self.u['DIRECTION']).post(self.url(self.n, 'mark_read/')).status_code, 200)
        self.assertEqual(cl(self.u['ADMIN']).delete(self.url(self.n)).status_code, 204)


class Bug255(Base):
    def test_anonymous_config_minimal(self):
        Config.objects.get_or_create(pk=1)
        r = cl().get('/api/core/config/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {'on_line'})
        self.assertIn('debt_ceiling', cl(self.u['LIVREUR']).get('/api/core/config/').data)

    def test_anonymous_cannot_write_config_or_prices(self):
        c = cl()
        self.assertEqual(c.put('/api/core/config/', {'debt_ceiling': '1'}, format='json').status_code, 401)
        self.assertEqual(c.patch('/api/core/config/', {'debt_ceiling': '1'}, format='json').status_code, 401)
        self.assertEqual(c.get('/api/core/bread-prices/').status_code, 200)
        self.assertEqual(c.post('/api/core/bread-prices/', {}, format='json').status_code, 401)

    def test_schema_requires_auth_outside_debug(self):
        from django.conf import settings
        perms = settings.SPECTACULAR_SETTINGS['SERVE_PERMISSIONS']
        if settings.DEBUG:
            self.skipTest('DEBUG actif : schema libre par conception')
        self.assertEqual(perms, ['rest_framework.permissions.IsAuthenticated'])
        for url in ('/api/schema/', '/api/docs/swagger/', '/api/docs/redoc/'):
            self.assertIn(cl().get(url).status_code, (401, 403), url)
