"""Verification croisee Dev C (testeur-permissions, 2026-11-21c).

1. Rejeu independant des tickets securite BUG-247, 248, 249, 250, 251, 252, 255.
2. Rejeu de la matrice anonyme + 6 roles sur TOUTES les routes /api/ (enumeration
   automatique via EndpointEnumerator) : pas de 5xx, anonyme = 401 hors liste
   publique, hierarchie des roles.
   Si MATRICE_C_OUT est defini, la matrice observee est ecrite (JSON) a cet endroit.
3. Isolation K1/K2 : production (BUG-147 auto-creation des stocks), tresorerie
   (rapports retroactifs, BUG-175), IDs forges, `node` force dans le corps.
4. `recompute_cump` (BUG-357) non exposee par l'API.
Donnees fictives uniquement.
"""
import json
import os
import uuid
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.core.cache import cache
from rest_framework.schemas.generators import EndpointEnumerator

from clients.models import Client, SocialContribution
from core.models import ActivityLog, Config, ExpenseCategory, SystemNotification
from core.tests.test_permissions_regression_2026_11_19 import (
    Base, ROLES, User, cl, mk)
from production.models import ConsumableMovement, ConsumableStock, ConsumableType
from treasury.models import FacturierReport, LocalExpense

NIL = '00000000-0000-0000-0000-000000000000'


def _stock(node, code='FAR'):
    return ConsumableStock.objects.get_or_create(
        node=node, consumable_type=code, defaults={'unit': 'sac', 'node_origin': node.code})[0]


# ---------------------------------------------------------------------------
# 1. Tickets securite (rejeu independant)
# ---------------------------------------------------------------------------
class V247(Base):
    """BUG-247 : elevation de role / prise de controle ADMIN."""

    def url(self, u, s=''):
        return f'/api/core/users/{u.pk}/{s}'

    def test_self_elevation_all_roles_all_fields(self):
        for role in ROLES:
            u = self.u[role]
            c = cl(u)
            for body in ({'role': 'ADMIN'}, {'role': 'DIRECTION'}, {'node': self.k2.pk},
                         {'node': None}, {'is_active': False}):
                if role == 'ADMIN':
                    continue  # ADMIN : voir test_admin_cannot_self_demote...
                if body.get('role') == role or (role in ('DIRECTION', 'COMPTABLE') and 'node' in body and body['node'] is None):
                    continue  # valeur identique a l'existant : sans effet
                r = c.patch(self.url(u), body, format='json')
                self.assertIn(r.status_code, (403, 404), (role, body, r.status_code))
            r = c.patch(self.url(u), {'is_superuser': True, 'is_staff': True}, format='json')
            u.refresh_from_db()
            self.assertFalse(u.is_superuser, role)
            self.assertFalse(u.is_staff, role)
            if role != 'ADMIN':
                u.refresh_from_db()
                self.assertEqual(u.role, role)

    def test_admin_cannot_self_demote_or_self_delete_or_set_superuser(self):
        a = self.u['ADMIN']
        c = cl(a)
        self.assertEqual(c.patch(self.url(a), {'role': 'GERANT'}, format='json').status_code, 403)
        self.assertEqual(c.delete(self.url(a)).status_code, 403)
        c.patch(self.url(a), {'is_superuser': True}, format='json')
        a.refresh_from_db()
        self.assertFalse(a.is_superuser)
        self.assertEqual(a.role, 'ADMIN')

    def test_direction_cannot_create_or_touch_admin_nor_superuser(self):
        d = cl(self.u['DIRECTION'])
        for body in ({'role': 'ADMIN'}, {'role': 'ADMIN', 'is_superuser': True}):
            r = d.post('/api/core/users/', {'username': 'zz_c_adm', 'password': 'abcdef12', **body}, format='json')
            self.assertEqual(r.status_code, 403, r.content)
        self.assertFalse(User.objects.filter(username='zz_c_adm').exists())
        # promotion d'un tiers en ADMIN via PUT et PATCH
        g = self.u['GERANT']
        self.assertEqual(d.patch(self.url(g), {'role': 'ADMIN'}, format='json').status_code, 403)
        self.assertEqual(d.put(self.url(g), {'username': g.username, 'role': 'ADMIN'}, format='json').status_code, 403)
        g.refresh_from_db()
        self.assertEqual(g.role, 'GERANT')
        su = mk('zz_c_su', 'DIRECTION')
        User.objects.filter(pk=su.pk).update(is_superuser=True)
        self.assertEqual(d.post(self.url(su, 'reset_password/')).status_code, 403)
        self.assertEqual(d.delete(self.url(su)).status_code, 403)

    def test_non_direction_write_users_denied_and_forged_ids(self):
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.post('/api/core/users/', {'username': 'zz_' + role, 'password': 'abcdef12',
                                                         'role': 'FACTURIER'}, format='json').status_code, 403, role)
            self.assertEqual(c.patch(self.url(self.u['LIVREUR']), {'role': 'ADMIN'}, format='json').status_code, 403)
            self.assertEqual(c.delete(self.url(self.u['LIVREUR'])).status_code, 403)
        self.assertEqual(cl().get('/api/core/users/').status_code, 401)

    def test_password_change_cannot_carry_role(self):
        f = self.u['FACTURIER']
        f.set_password('Ancien-mdp-1')
        f.save()
        r = cl(f).post('/api/core/auth/change-password/', {
            'old_password': 'Ancien-mdp-1', 'current_password': 'Ancien-mdp-1',
            'new_password': 'Nouveau-mdp-22', 'role': 'ADMIN', 'is_superuser': True}, format='json')
        f.refresh_from_db()
        self.assertEqual((f.role, f.is_superuser), ('FACTURIER', False), r.content)

    def test_users_list_scope_for_non_hq(self):
        """Un gerant K1 ne doit pas lister les comptes de K2 (isolation)."""
        r = cl(self.u['GERANT']).get('/api/core/users/')
        if r.status_code == 200:
            data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
            names = {x['username'] for x in data}
            self.assertNotIn(self.u2['GERANT'].username, names)


class V248(Base):
    def test_temp_password_random_once_and_not_logged(self):
        t = self.u['FACTURIER']
        pw = set()
        for _ in range(3):
            r = cl(self.u['ADMIN']).post(f'/api/core/users/{t.pk}/reset_password/')
            self.assertEqual(r.status_code, 200, r.content)
            tp = r.data['temporary_password']
            self.assertGreaterEqual(len(tp), 10)
            self.assertNotEqual(tp.lower(), t.username.lower())
            self.assertNotIn(tp, str(r.data['detail']))
            pw.add(tp)
        self.assertEqual(len(pw), 3)
        for log in ActivityLog.objects.all():
            for tp in pw:
                self.assertNotIn(tp, f'{log.action} {log.description}')
        t.refresh_from_db()
        self.assertTrue(t.must_change_password)
        self.assertFalse(t.check_password(t.username))

    def test_nobody_below_direction_can_reset_and_cross_node(self):
        t = self.u2['LIVREUR']
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).post(f'/api/core/users/{t.pk}/reset_password/').status_code, 403, role)
        self.assertEqual(cl().post(f'/api/core/users/{t.pk}/reset_password/').status_code, 401)
        self.assertEqual(cl(self.u['ADMIN']).post(f'/api/core/users/{NIL}/reset_password/').status_code, 404)


class V249(Base):
    def test_gerant_k1_cannot_write_social_cash_of_k2(self):
        c = cl(self.u['GERANT'])
        n0 = SocialContribution.objects.filter(node=self.k2).count()
        for node in (self.k2.pk, self.k1.pk):
            r = c.post('/api/clients/contributions/', {'client': str(self.c2.pk), 'node': node, 'month': 7,
                                                       'year': 2026, 'amount': '1000'}, format='json')
            self.assertGreaterEqual(r.status_code, 400, (node, r.content))
        r = c.post('/api/clients/contributions/bulk_create_month/', {'node': self.k2.pk, 'month': 8, 'year': 2026},
                   format='json')
        self.assertIn(r.status_code, (400, 403, 404), r.content)
        self.assertEqual(SocialContribution.objects.filter(node=self.k2).count(), n0)
        # PATCH / DELETE d'une cotisation K2, et deplacement d'une cotisation K1 vers un client K2
        self.assertIn(c.patch(f'/api/clients/contributions/{self.contrib2.pk}/', {'amount': '1'},
                              format='json').status_code, (403, 404))
        self.assertIn(c.delete(f'/api/clients/contributions/{self.contrib2.pk}/').status_code, (403, 404))
        r = c.patch(f'/api/clients/contributions/{self.contrib1.pk}/', {'client': str(self.c2.pk), 'node': self.k2.pk},
                    format='json')
        self.contrib1.refresh_from_db()
        self.assertEqual((self.contrib1.node_id, self.contrib1.client_id), (self.k1.pk, self.c1.pk), r.content)

    def test_legit_contribution_forces_own_node(self):
        r = cl(self.u['GERANT']).post('/api/clients/contributions/', {
            'client': str(self.c1.pk), 'node': self.k2.pk, 'month': 9, 'year': 2026, 'amount': '1500'}, format='json')
        if r.status_code == 201:
            self.assertEqual(SocialContribution.objects.get(pk=r.data['id']).node_id, self.k1.pk)

    def test_facturier_livreur_denied(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.get('/api/clients/contributions/').status_code, 403, role)
            self.assertEqual(c.post('/api/clients/contributions/bulk_create_month/', {}, format='json').status_code, 403)


class V250(Base):
    def test_facturier_cannot_set_credit_limit_or_rate_at_creation_nor_patch(self):
        c = cl(self.u['FACTURIER'])
        r = c.post('/api/clients/clients/', {
            'first_name': 'Zed', 'last_name': 'Cee', 'credit_limit': '9999999', 'commission_rate': '0.30',
            'node': self.k2.pk}, format='json')
        if r.status_code == 201:
            obj = Client.objects.get(pk=r.data['id'])
            self.assertEqual((obj.credit_limit, obj.commission_rate), (Dc('50000'), Dc('0.25')))
            self.assertEqual(obj.node_id, self.k1.pk)
            self.assertIn(c.patch(f'/api/clients/clients/{obj.pk}/', {'credit_limit': '1'}, format='json').status_code,
                          (403, 404))
        else:
            self.assertIn(r.status_code, (400, 403), r.content)
        for role in ('LIVREUR', 'FACTURIER'):
            self.assertEqual(cl(self.u[role]).patch(f'/api/clients/clients/{self.c1.pk}/', {'credit_limit': '1'},
                                                    format='json').status_code, 403, role)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.credit_limit, Dc('50000'))

    def test_gerant_bounds_and_other_node(self):
        g = cl(self.u['GERANT'])
        self.assertEqual(g.patch(f'/api/clients/clients/{self.c1.pk}/', {'credit_limit': '99999999'},
                                 format='json').status_code, 400)
        self.assertEqual(g.patch(f'/api/clients/clients/{self.c1.pk}/', {'commission_rate': '0.50'},
                                 format='json').status_code, 400)
        self.assertIn(g.patch(f'/api/clients/clients/{self.c2.pk}/', {'credit_limit': '10'}, format='json').status_code,
                      (403, 404))
        self.c2.refresh_from_db()
        self.assertEqual(self.c2.credit_limit, Dc('50000'))


class V251(Base):
    def setUp(self):
        self.st1 = _stock(self.k1)
        self.st2 = _stock(self.k2)

    def test_facturier_livreur_read_only(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.get('/api/production/stocks/').status_code, 200)
            u = f'/api/production/stocks/{self.st1.pk}/'
            self.assertEqual(c.patch(u, {'quantity': '123'}, format='json').status_code, 403, role)
            self.assertEqual(c.put(u, {'quantity': '123'}, format='json').status_code, 403, role)
            self.assertEqual(c.delete(u).status_code, 403, role)
            self.assertEqual(c.post('/api/production/stocks/', {'consumable_type': 'SEL'}, format='json').status_code, 403)
        self.st1.refresh_from_db()
        self.assertEqual(self.st1.quantity, Dc('0'))

    def test_gerant_quantity_and_cump_read_only_and_node_forced(self):
        g = cl(self.u['GERANT'])
        u = f'/api/production/stocks/{self.st1.pk}/'
        g.patch(u, {'quantity': '123', 'average_unit_cost': '9999', 'node': self.k2.pk}, format='json')
        self.st1.refresh_from_db()
        self.assertEqual((self.st1.quantity, self.st1.average_unit_cost, self.st1.node_id),
                         (Dc('0'), Dc('0'), self.k1.pk))
        # detail / modification d'un stock de K2 par UUID connu
        u2 = f'/api/production/stocks/{self.st2.pk}/'
        self.assertEqual(g.get(u2).status_code, 404)
        self.assertEqual(g.patch(u2, {'unit': 'x'}, format='json').status_code, 404)
        self.assertEqual(g.delete(u2).status_code, 404)
        self.assertTrue(ConsumableStock.objects.filter(pk=self.st2.pk).exists())

    @expectedFailure  # BUG-504 (ouvert, Dev C 2026-11-21c) : retirer le marqueur a la correction
    def test_movement_on_foreign_stock_forged(self):
        """Gerant K1 : mouvement sur le stock de K2 (stock= et node= forges)."""
        g = cl(self.u['GERANT'])
        n0 = ConsumableMovement.objects.count()
        before = ConsumableStock.objects.get(pk=self.st2.pk).quantity
        r = g.post('/api/production/movements/', {
            'stock': str(self.st2.pk), 'node': self.k2.pk, 'movement_type': 'ENTRY', 'quantity': '5',
            'unit_price': '1000'}, format='json')
        after = ConsumableStock.objects.get(pk=self.st2.pk)
        self.assertEqual((after.quantity, after.average_unit_cost), (before, Dc('0')),
                         f'stock de K2 modifie par un gerant K1 : {r.status_code} {r.content[:120]}')
        self.assertGreaterEqual(r.status_code, 400, r.content)
        self.assertEqual(ConsumableMovement.objects.count(), n0)


class V252(Base):
    def setUp(self):
        self.cloud = SystemNotification.objects.create(title='Siege', message='m', node_origin='CLOUD')
        self.n2 = SystemNotification.objects.create(title='K2', message='m', node_origin='P2')

    def test_cloud_alert_protected_and_cross_node_hidden(self):
        for u in (self.u['GERANT'], self.u['FACTURIER'], self.u['LIVREUR']):
            c = cl(u)
            self.assertEqual(c.delete(f'/api/core/notifications/{self.cloud.pk}/').status_code, 403, u.role)
            self.assertEqual(c.post(f'/api/core/notifications/{self.cloud.pk}/mark_read/').status_code, 403, u.role)
            self.assertEqual(c.delete(f'/api/core/notifications/{self.n2.pk}/').status_code, 404, u.role)
            self.assertEqual(c.post(f'/api/core/notifications/{self.n2.pk}/mark_read/').status_code, 404, u.role)
            r = c.post('/api/core/notifications/mark_all_read/')
            self.assertEqual(r.status_code, 200)
        self.cloud.refresh_from_db()
        self.n2.refresh_from_db()
        self.assertFalse(self.cloud.is_read)
        self.assertFalse(self.n2.is_read)
        self.assertEqual(cl(self.u['DIRECTION']).post(f'/api/core/notifications/{self.cloud.pk}/mark_read/').status_code, 200)


class V255(Base):
    def test_public_endpoints_limited(self):
        """AllowAny : login, refresh, GET config (reduit), GET bread-prices ; le reste 401."""
        Config.objects.get_or_create(pk=1)
        c = cl()
        r = c.get('/api/core/config/')
        self.assertEqual((r.status_code, set(r.data)), (200, {'on_line'}))
        self.assertEqual(c.get('/api/core/bread-prices/').status_code, 200)
        for m, url in (('post', '/api/core/bread-prices/'), ('put', '/api/core/config/'),
                       ('patch', '/api/core/config/'), ('get', '/api/core/users/'),
                       ('get', '/api/core/nodes/'), ('get', '/api/core/auth/me/'),
                       ('get', '/api/core/activities/'), ('post', '/api/core/reset-data/')):
            self.assertEqual(getattr(c, m)(url, **({'data': {}, 'format': 'json'} if m != 'get' else {})).status_code,
                             401, (m, url))

    def test_schema_policy_matches_debug(self):
        from django.conf import settings
        perms = settings.SPECTACULAR_SETTINGS['SERVE_PERMISSIONS']
        # NB : le runner de tests force settings.DEBUG=False ; la politique du schema est figee
        # a l'import des reglages d'apres DJANGO_DEBUG (cause de BUG-401).
        if ENV_DEBUG:
            self.assertEqual(perms, ['rest_framework.permissions.AllowAny'])
        else:
            self.assertEqual(perms, ['rest_framework.permissions.IsAuthenticated'])
            for url in ('/api/schema/', '/api/docs/swagger/', '/api/docs/redoc/'):
                self.assertIn(cl().get(url, secure=True).status_code, (401, 403), url)
                self.assertEqual(cl(self.u['LIVREUR']).get(url, secure=True).status_code, 200, url)


# ---------------------------------------------------------------------------
# 2. Matrice complete anonyme + 6 roles (enumeration automatique)
# ---------------------------------------------------------------------------
PUBLIC = {  # (methode, gabarit) accessibles sans jeton
    ('POST', '/api/core/auth/login/'),
    ('POST', '/api/core/auth/login/refresh/'),
    ('GET', '/api/core/config/'),
    ('GET', '/api/core/bread-prices/'),
    ('GET', '/api/core/bread-prices/{id}/'),
    ('GET', '/api/core/bread-prices/{pk}/'),
}
# Schema / Swagger / ReDoc : publics UNIQUEMENT si DJANGO_DEBUG=True dans l'environnement du processus.
ENV_DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('true', '1', 'yes')
if ENV_DEBUG:
    PUBLIC |= {('GET', '/api/schema/'), ('GET', '/api/docs/swagger/'), ('GET', '/api/docs/redoc/')}
# Constats connus (comportement par conception, voir rapport) : ADMIN sans noeud => 403 sur le fil de son noeud.
HIER_ALLOW = {('GET', '/api/chat/conversations/node/')}
# Endpoints a jeton de noeud (pas JWT humain) : authentification propre (sync)
NODE_TOKEN_PREFIX = '/api/sync/'
SKIP_ROLE_LOOP = {'/api/core/auth/login/', '/api/core/auth/login/refresh/'}
COLS = ['AN', 'ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR']
DENIED = (401, 403)


def _endpoints():
    seen = set()
    for path, method, _cb in EndpointEnumerator().get_api_endpoints():
        if method in ('HEAD', 'OPTIONS'):
            continue
        key = (method, path)
        if key in seen or '{format}' in path or '.{' in path:
            continue
        seen.add(key)
        yield method, path


class MatrixFull(Base):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def concrete(self, path):
        import re
        return re.sub(r'\{[^}]+\}', NIL, path)

    def call(self, client, method, path):
        url = self.concrete(path)
        kw = {} if method == 'GET' or method == 'DELETE' else {'data': {}, 'format': 'json'}
        return getattr(client, method.lower())(url, **kw)

    def test_matrix(self):
        clients = {'AN': cl()}
        for r in ROLES:
            clients[r] = cl(self.u[r])
        obs = {}
        problems = []
        for method, path in sorted(_endpoints()):
            if path in SKIP_ROLE_LOOP and method == 'POST':
                continue
            if path.startswith(NODE_TOKEN_PREFIX) and path != '/api/sync/local-status/':
                continue
            row = {}
            for col in COLS:
                try:
                    resp = self.call(clients[col], method, path)
                    row[col] = resp.status_code
                except Exception as e:  # une exception = 500 non geree
                    row[col] = 'EXC:' + type(e).__name__
            obs[f'{method} {path}'] = row
            key = (method, path)
            # a) pas de 5xx
            for col, st in row.items():
                if isinstance(st, str) or st >= 500:
                    problems.append(f'5XX {col} {method} {path} -> {st}')
            # b) anonyme = 401 hors liste publique
            if key not in PUBLIC and row['AN'] != 401:
                problems.append(f'ANON {method} {path} -> {row["AN"]}')
            # c) hierarchie : GERANT refuse => FACTURIER et LIVREUR refuses
            if row['GERANT'] in DENIED:
                for low in ('FACTURIER', 'LIVREUR'):
                    if row[low] not in DENIED:
                        problems.append(f'HIER {method} {path} GERANT={row["GERANT"]} {low}={row[low]}')
            # d) ADMIN jamais refuse si un autre role non-super passe
            if row['ADMIN'] in DENIED:
                for col in COLS[2:]:
                    if key in HIER_ALLOW:
                        break
                    if row[col] not in DENIED:
                        problems.append(f'ADMIN< {method} {path} ADMIN={row["ADMIN"]} {col}={row[col]}')
        out = os.environ.get('MATRICE_C_OUT')
        if out:
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(obs, f, ensure_ascii=False, indent=0)
        self.assertGreater(len(obs), 150)
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_every_route_declares_an_explicit_permission(self):
        """Aucune vue /api/ sans permission_classes explicite NI politique par defaut IsAuthenticated."""
        from django.conf import settings
        self.assertEqual(settings.REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES'],
                         ['rest_framework.permissions.IsAuthenticated'])
        from rest_framework.permissions import AllowAny
        allow_any = []
        for path, method, cb in EndpointEnumerator().get_api_endpoints():
            cls = getattr(cb, 'cls', None)
            if cls is None:
                continue
            if AllowAny in getattr(cls, 'permission_classes', []):
                allow_any.append((method, path))
        # login, refresh (SimpleJWT), config, bread-prices : rien d'autre
        for method, path in allow_any:
            if ENV_DEBUG and path in ('/api/schema/', '/api/docs/swagger/', '/api/docs/redoc/'):
                continue
            self.assertIn(path, {'/api/core/auth/login/', '/api/core/auth/login/refresh/',
                                 '/api/core/config/', '/api/core/bread-prices/', '/api/core/bread-prices/{id}/',
                         '/api/core/bread-prices/{pk}/'}, path)


# ---------------------------------------------------------------------------
# 3. Isolation inter-noeuds : production / tresorerie / ventes
# ---------------------------------------------------------------------------
class IsolationProduction(Base):
    def setUp(self):
        cache.clear()
        for code, unit in (('FAR', 'sac'), ('SEL', 'g')):
            ConsumableType.objects.get_or_create(code=code, defaults={'label': code, 'unit': unit, 'is_active': True})
        ConsumableStock.objects.all().delete()

    def n(self, node):
        return ConsumableStock.objects.filter(node=node).count()

    def test_bug147_auto_creation_stays_on_own_node(self):
        """GET /stocks/ par un role non siege ne cree jamais de compte pour un autre noeud."""
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for q in ('', f'?node={self.k2.pk}', '?node=999999', f'?node={self.k1.pk}&node={self.k2.pk}'):
                r = c.get('/api/production/stocks/' + q)
                self.assertIn(r.status_code, (200, 400), (role, q, r.content[:200]))
                if r.status_code == 400:
                    continue
                data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
                self.assertTrue(all(x['node'] == self.k1.pk for x in data), (role, q))
            self.assertEqual(self.n(self.k2), 0, role)
        self.assertGreater(self.n(self.k1), 0)

    @expectedFailure  # BUG-506 (ouvert, Dev C 2026-11-21c) : retirer le marqueur a la correction
    def test_bug147_node_less_non_hq_account_cannot_reach_other_nodes(self):
        """Compte GERANT sans noeud (mal configure) : ne doit ni creer ni lire les stocks d'un noeud."""
        orphan = mk('pr_orphan', 'GERANT', None)
        r = cl(orphan).get(f'/api/production/stocks/?node={self.k2.pk}')
        data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        self.assertEqual(self.n(self.k2), 0, 'auto-creation pour un noeud etranger par un compte sans noeud')
        self.assertEqual(len(data), 0, 'lecture des stocks de K2 par un compte sans noeud')

    def test_bug147_hq_filter_junk_does_not_500(self):
        for junk in ('abc', 'not-a-uuid', '99999999999999999999', ''):
            r = cl(self.u['DIRECTION']).get('/api/production/stocks/?node=' + junk)
            self.assertLess(r.status_code, 500, junk)

    def test_bug147_hq_can_scope_to_node(self):
        r = cl(self.u['DIRECTION']).get(f'/api/production/stocks/?node={self.k2.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertGreater(self.n(self.k2), 0)

    def test_no_cump_manipulation_via_api(self):
        st = _stock(self.k1, 'FAR')
        for role in ROLES:
            c = cl(self.u[role])
            for m in ('patch', 'put'):
                getattr(c, m)(f'/api/production/stocks/{st.pk}/',
                              {'average_unit_cost': '123456', 'quantity': '77', 'consumable_type': 'FAR'}, format='json')
        st.refresh_from_db()
        self.assertEqual((st.average_unit_cost, st.quantity), (Dc('0'), Dc('0')))

    def test_recompute_cump_not_exposed(self):
        for path, method, cb in EndpointEnumerator().get_api_endpoints():
            self.assertNotIn('cump', path.lower(), path)
            self.assertNotIn('recompute', path.lower(), path)
            cls = getattr(cb, 'cls', None)
            if cls is not None and hasattr(cls, 'get_extra_actions'):
                for act in cls.get_extra_actions():
                    self.assertNotIn('recompute', act.__name__.lower())
                    self.assertNotIn('cump', act.__name__.lower())
        for url in ('/api/production/recompute_cump/', '/api/production/stocks/recompute_cump/',
                    '/api/production/movements/recompute_cump/', '/api/core/recompute_cump/'):
            for who in (cl(), cl(self.u['ADMIN'])):
                for m in ('get', 'post'):
                    self.assertIn(getattr(who, m)(url).status_code, (401, 404, 405), (m, url))
        # la commande n'est importee par aucune vue / route
        import production.views as pv
        self.assertFalse(hasattr(pv, 'recompute_cump'))

    def test_cross_node_production_lists_and_detail(self):
        st2 = _stock(self.k2)
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for url in ('/api/production/sessions/', '/api/production/stocks/', '/api/production/movements/',
                        '/api/production/transfers/', '/api/production/bread-stocks/'):
                r = c.get(url + f'?node={self.k2.pk}')
                if r.status_code == 403:
                    continue
                data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
                for x in data:
                    ids = {x.get('node'), x.get('from_node'), x.get('to_node')}
                    if url.endswith('transfers/'):
                        self.assertIn(self.k1.pk, ids, (role, url))
                    else:
                        self.assertNotIn(self.k2.pk, ids, (role, url))
            self.assertEqual(c.get(f'/api/production/sessions/{self.s2.pk}/').status_code, 404, role)
            self.assertEqual(c.get(f'/api/production/stocks/{st2.pk}/').status_code, 404, role)
        for m in ('patch', 'delete'):
            r = getattr(cl(self.u['GERANT']), m)(f'/api/production/sessions/{self.s2.pk}/',
                                                 **({} if m == 'delete' else {'data': {'flour_sacks_used': '9'}, 'format': 'json'}))
            self.assertIn(r.status_code, (403, 404), m)
        self.s2.refresh_from_db()
        self.assertEqual(self.s2.flour_sacks_used, Dc('3'))

    def test_session_create_forged_node(self):
        r = cl(self.u['GERANT']).post('/api/production/sessions/', {
            'flour_sacks_used': '2', 'team': 'B', 'date': '2026-11-21', 'node': self.k2.pk}, format='json')
        if r.status_code == 201:
            from production.models import ProductionSession
            self.assertEqual(ProductionSession.objects.get(pk=r.data['id']).node_id, self.k1.pk)
        self.assertFalse(__import__('production.models', fromlist=['x']).ProductionSession.objects
                         .filter(node=self.k2).exclude(pk=self.s2.pk).exists())


class IsolationTreasury(Base):
    """BUG-175 : les rapports retroactifs ne dependent que de reports/generate et reports/validate."""

    def setUp(self):
        cache.clear()
        self.r1 = FacturierReport.objects.create(node=self.k1, team='A', date='2026-11-10', node_origin='P1')
        self.r2 = FacturierReport.objects.create(node=self.k2, team='A', date='2026-11-10', node_origin='P2')

    def test_reports_list_scope_and_detail(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for q in ('', f'?node={self.k2.pk}', f'?node={self.k2.pk}&date=2026-11-10'):
                r = c.get('/api/treasury/reports/' + q)
                data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
                self.assertEqual(r.status_code, 200)
                self.assertNotIn(self.k2.pk, {x['node'] for x in data}, (role, q))
            self.assertEqual(c.get(f'/api/treasury/reports/{self.r2.pk}/').status_code, 404, role)

    def test_validate_and_generate_guarded(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.post(f'/api/treasury/reports/{self.r1.pk}/validate/').status_code, 403, role)
            self.assertEqual(c.post('/api/treasury/reports/generate/', {'date': '2026-11-10'}, format='json').status_code,
                             403, role)
        self.assertEqual(cl().post(f'/api/treasury/reports/{self.r1.pk}/validate/').status_code, 401)
        g = cl(self.u['GERANT'])
        self.assertEqual(g.post(f'/api/treasury/reports/{self.r2.pk}/validate/').status_code, 404)
        self.r2.refresh_from_db()
        self.assertFalse(self.r2.is_validated)
        # generate : `node` du corps ignore pour un non-siege (aucun rapport cree pour K2)
        n0 = FacturierReport.objects.filter(node=self.k2).count()
        g.post('/api/treasury/reports/generate/', {'date': '2026-11-10', 'node': self.k2.pk}, format='json')
        self.assertEqual(FacturierReport.objects.filter(node=self.k2).count(), n0)

    @expectedFailure  # BUG-503 (ouvert, Dev C 2026-11-21c) : retirer le marqueur a la correction
    def test_report_create_forged_node_by_gerant(self):
        """POST /reports/ avec node=K2 par un gerant K1 : ne doit rien creer pour K2."""
        n0 = FacturierReport.objects.filter(node=self.k2).count()
        r = cl(self.u['GERANT']).post('/api/treasury/reports/', {
            'node': self.k2.pk, 'date': '2026-11-11', 'total_cash_sales': '1000', 'total_credit_sales': '0'},
            format='json')
        self.assertEqual(FacturierReport.objects.filter(node=self.k2).count(), n0,
                         f'rapport cree pour K2 par un gerant K1 : {r.status_code} {r.content[:200]}')

    def test_report_update_delete_cross_node(self):
        g = cl(self.u['GERANT'])
        self.assertEqual(g.patch(f'/api/treasury/reports/{self.r2.pk}/', {'total_cash_sales': '1'},
                                 format='json').status_code, 404)
        self.assertEqual(g.delete(f'/api/treasury/reports/{self.r2.pk}/').status_code, 404)
        g.patch(f'/api/treasury/reports/{self.r1.pk}/', {'node': self.k2.pk}, format='json')
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.node_id, self.k1.pk)

    def test_expenses_closures_cashbook_isolation(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for url in ('/api/treasury/closures/', '/api/treasury/savings/', '/api/treasury/journal/',
                        '/api/treasury/cashbook/'):
                self.assertEqual(c.get(url).status_code, 403, (role, url))
        g = cl(self.u['GERANT'])
        n0 = LocalExpense.objects.filter(node=self.k2).count()
        cat = ExpenseCategory.objects.first()
        if cat:
            g.post('/api/treasury/expenses/', {'node': self.k2.pk, 'description': 'x', 'amount': '10',
                                               'category': cat.pk, 'date': '2026-11-21'}, format='json')
        self.assertEqual(LocalExpense.objects.filter(node=self.k2).count(), n0)


class IsolationExtra(Base):
    """Fuites constatees pendant le rejeu : flour_history, compte sans noeud, creation de compte."""

    def setUp(self):
        cache.clear()

    @expectedFailure  # BUG-505 (ouvert, Dev C 2026-11-21c) : retirer le marqueur a la correction
    def test_flour_history_node_param_not_honoured_for_non_hq(self):
        for code in ('FLOUR', 'FAR'):
            for node in (self.k1, self.k2):
                st = _stock(node, code)
                ConsumableMovement.objects.create(
                    node=node, stock=st, movement_type='ENTRY', quantity=Dc('2'), unit_price=Dc('1000'),
                    supplier='', description='secret ' + node.code, node_origin=node.code)
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).get(f'/api/production/movements/flour_history/?node={self.k2.pk}')
            if r.status_code == 403:
                continue
            self.assertEqual(r.status_code, 200)
            self.assertEqual([x for x in r.data if x['node'] == 'P2'], [], f'{role} lit les entrees de farine de K2')

    # BUG-506 corrige (Dev B, e347918) : marque retiree, verifie par Dev C 2026-11-21c2
    def test_non_hq_user_cannot_be_created_without_node(self):
        """Sinon `if not can_access_all_nodes and user.node_id` ne filtre rien (voir BUG ouvert)."""
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = cl(self.u['DIRECTION']).post('/api/core/users/', {
                'username': 'zz_orph_' + role, 'password': 'abcdef12xyz', 'role': role}, format='json')
            self.assertGreaterEqual(r.status_code, 400, f'{role} cree sans boulangerie : {r.status_code}')

    @expectedFailure  # BUG-506 (ouvert, Dev C 2026-11-21c) : retirer le marqueur a la correction
    def test_node_less_non_hq_sees_nothing_cross_node(self):
        orphan = mk('zz_orph', 'GERANT', None)
        for url in ('/api/production/sessions/', '/api/clients/contributions/', '/api/clients/distributions/',
                    '/api/treasury/reports/', '/api/treasury/expenses/', '/api/sales/invoices/'):
            r = cl(orphan).get(url)
            if r.status_code != 200:
                continue
            data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
            self.assertEqual(len(data), 0, f'compte sans noeud : {url} renvoie {len(data)} objets')


class FacturierClientSearchException(Base):
    """Exception 5.1 : le facturier recherche les clients des autres boulangeries, sans pouvoir les modifier."""

    def test_search_ok_write_denied(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            r = c.get('/api/clients/clients/?search=Deux')
            self.assertEqual(r.status_code, 200)
            data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
            if role == 'FACTURIER':
                self.assertIn(str(self.c2.pk), {str(x['id']) for x in data})
            self.assertEqual(c.patch(f'/api/clients/clients/{self.c2.pk}/', {'first_name': 'Hack'}, format='json')
                             .status_code, 403, role)
            self.assertEqual(c.delete(f'/api/clients/clients/{self.c2.pk}/').status_code, 403, role)
        g = cl(self.u['GERANT'])
        self.assertIn(g.patch(f'/api/clients/clients/{self.c2.pk}/', {'first_name': 'Hack'}, format='json').status_code,
                      (403, 404))
        self.c2.refresh_from_db()
        self.assertEqual(self.c2.first_name, 'Bob')

    @expectedFailure  # BUG-507 (ouvert, A CLARIFIER) : l'exception 5.1 ne vise que les facturiers
    def test_livreur_does_not_get_cross_node_client_search(self):
        r = cl(self.u['LIVREUR']).get('/api/clients/clients/?search=Deux')
        data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        self.assertNotIn(str(self.c2.pk), {str(x['id']) for x in data})


# ---------------------------------------------------------------------------
# 5. Authentification / JWT / limitation de tentatives / changement force
# ---------------------------------------------------------------------------
class JwtAuth(Base):
    PW = 'Mdp-test-Qa-2026x'

    def setUp(self):
        cache.clear()
        self.f = self.u['FACTURIER']
        self.f.set_password(self.PW)
        self.f.save()

    def tearDown(self):
        cache.clear()

    def login(self, username=None, pw=None):
        return cl().post('/api/core/auth/login/', {'username': username or self.f.username,
                                                    'password': pw or self.PW}, format='json')

    def bearer(self, token):
        from rest_framework.test import APIClient
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        return c

    def test_refresh_after_logout_refused_and_rotation_blacklists(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        acc, ref = r.data['access'], r.data['refresh']
        self.assertEqual(self.bearer(acc).post('/api/core/auth/logout/', {'refresh': ref}, format='json').status_code, 200)
        self.assertEqual(cl().post('/api/core/auth/login/refresh/', {'refresh': ref}, format='json').status_code, 401)
        # rotation : l'ancien refresh est invalide apres usage
        ref2 = self.login().data['refresh']
        new = cl().post('/api/core/auth/login/refresh/', {'refresh': ref2}, format='json')
        self.assertEqual(new.status_code, 200)
        self.assertEqual(cl().post('/api/core/auth/login/refresh/', {'refresh': ref2}, format='json').status_code, 401)

    def test_expired_forged_and_deactivated_tokens(self):
        from datetime import timedelta
        from rest_framework_simplejwt.tokens import AccessToken
        tok = AccessToken.for_user(self.f)
        tok.set_exp(from_time=tok.current_time - timedelta(hours=2), lifetime=timedelta(minutes=1))
        self.assertEqual(self.bearer(str(tok)).get('/api/core/auth/me/').status_code, 401)
        good = str(AccessToken.for_user(self.f))
        self.assertEqual(self.bearer(good).get('/api/core/auth/me/').status_code, 200)
        head, payload, sig = good.split('.')
        self.assertEqual(self.bearer(f'{head}.{payload}.{sig[:-3]}AAA').get('/api/core/auth/me/').status_code, 401)
        # alg=none
        import base64
        none_head = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b'=').decode()
        self.assertEqual(self.bearer(f'{none_head}.{payload}.').get('/api/core/auth/me/').status_code, 401)
        # un access token n'est pas un refresh
        self.assertEqual(cl().post('/api/core/auth/login/refresh/', {'refresh': good}, format='json').status_code, 401)
        # compte desactive apres emission
        self.f.is_active = False
        self.f.save()
        self.assertEqual(self.bearer(good).get('/api/core/auth/me/').status_code, 401)

    def test_login_throttle_per_account_and_inactive(self):
        for _ in range(5):
            self.assertEqual(self.login(pw='mauvais').status_code, 401)
        self.assertEqual(self.login(pw='mauvais').status_code, 429)
        self.assertEqual(self.login().status_code, 429, 'meme le bon mot de passe est bloque pendant la fenetre')
        other = self.u['LIVREUR']
        other.set_password(self.PW)
        other.save()
        self.assertEqual(self.login(other.username).status_code, 200, 'un autre compte ne doit pas etre bloque')

    def test_me_patch_cannot_change_role_node_or_flags(self):
        c = cl(self.f)
        c.patch('/api/core/auth/me/', {'role': 'ADMIN', 'node': self.k2.pk, 'is_superuser': True, 'is_staff': True,
                                      'is_active': True, 'first_name': 'Nouveau'}, format='json')
        self.f.refresh_from_db()
        self.assertEqual((self.f.role, self.f.node_id, self.f.is_superuser, self.f.is_staff),
                         ('FACTURIER', self.k1.pk, False, False))

    def test_must_change_password_blocks_api(self):
        self.f.must_change_password = True
        self.f.save()
        acc = self.login().data['access']
        c = self.bearer(acc)
        for url in ('/api/clients/clients/', '/api/sales/invoices/', '/api/core/nodes/', '/api/production/stocks/'):
            r = c.get(url)
            self.assertEqual(r.status_code, 403, url)
        self.assertEqual(c.get('/api/core/auth/me/').status_code, 200)

    def test_sync_endpoints_refuse_human_jwt_and_anonymous(self):
        for url, m in (('/api/sync/push/', 'post'), ('/api/sync/pull/', 'get'), ('/api/sync/handshake/', 'post'),
                       ('/api/sync/status/', 'get'), ('/api/sync/conflicts/', 'get')):
            for who in (cl(), cl(self.u['ADMIN']), cl(self.u['GERANT'])):
                if url.endswith('/conflicts/') and who is not None and getattr(who.handler._force_user, 'role', '') == 'ADMIN':
                    continue  # liste des conflits : JWT humain siege (IsHeadquarters) par conception
                r = getattr(who, m)(url) if m == 'get' else getattr(who, m)(url, {}, format='json')
                self.assertIn(r.status_code, (401, 403), (url, r.status_code))
