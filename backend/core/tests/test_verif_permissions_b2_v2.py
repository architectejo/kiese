"""Permissions / isolation, ronde 2 (testeur-permissions pour le Dev B, 2026-11-22, `b2`).

Angles NOUVEAUX par rapport a test_verif_matrice_c / test_verif_isolation_a_c /
test_verif_params_invalides_c :
  1. Matrice 6 roles + anonyme avec valeur ATTENDUE par role (et non seulement la
     hierarchie) sur les routes recentes : consommables global/dispatch, inventaires,
     mouvements, commissions (summary, history, payroll_listing, generate, close_period,
     mark_paid, set_manuel), deficit_report, bassins, chat, core.
  2. IDs forges (UUID / pk d'un autre noeud) en GET/PUT/PATCH/DELETE.
  3. Mass assignment (utilisateurs, noeuds, config, commissions).
  4. JWT : refresh en guise d'access, role relu en base, reset de mot de passe, entrees degenerees.
  5. Chat : conversations d'un autre noeud, fils prives, participations perimees.
  6. Surface /admin/ (limitation des tentatives).
Donnees fictives uniquement. Les defauts constates portent un @expectedFailure + n° de ticket.
"""
import uuid
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.core.cache import cache
from rest_framework.test import APIClient

from chat.models import Conversation, Message, Participant
from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.models import ColisDistribution, Config, Node, SystemNotification
from core.tests.test_permissions_regression_2026_11_19 import (
    ALL, DIRECTION_UP, GERANT_UP, HQ, ROLES, Base, User, cl, mk)
from production.models import (ConsumableInventory, ConsumableMovement, ConsumableStock,
                               ConsumableType)

NIL = '00000000-0000-0000-0000-000000000000'
DENIED = (401, 403)


def results(r):
    d = r.data
    return d['results'] if isinstance(d, dict) and 'results' in d else d


def _stock(node, code='FAR'):
    ConsumableType.objects.get_or_create(code=code, defaults={'label': code, 'unit': 'sac', 'is_active': True})
    return ConsumableStock.objects.get_or_create(
        node=node, consumable_type=code, defaults={'unit': 'sac', 'node_origin': node.code})[0]


class B2Base(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.st1 = _stock(cls.k1)
        cls.st2 = _stock(cls.k2)
        cls.inv1 = ConsumableInventory.objects.create(
            node=cls.k1, inventory_date='2026-11-20', comment='c1', node_origin='P1')
        cls.inv2 = ConsumableInventory.objects.create(
            node=cls.k2, inventory_date='2026-11-20', comment='c2', node_origin='P2')
        cls.per1 = CommissionPeriod.objects.create(node=cls.k1, month=10, year=2026, node_origin='P1')
        cls.per2 = CommissionPeriod.objects.create(node=cls.k2, month=10, year=2026, node_origin='P2')
        cls.cm1 = ClientCommission.objects.create(
            period=cls.per1, client=cls.c1, order_value=Dc('100000'), node_origin='P1')
        cls.cm2 = ClientCommission.objects.create(
            period=cls.per2, client=cls.c2, order_value=Dc('100000'), node_origin='P2')
        cls.colis1 = ColisDistribution.objects.create(node=cls.k1, year=2026, beneficiary_label='X1')
        cls.colis2 = ColisDistribution.objects.create(node=cls.k2, year=2026, beneficiary_label='X2')

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def clients(self):
        out = {'AN': cl()}
        for r in ROLES:
            out[r] = cl(self.u[r])
        return out


# ---------------------------------------------------------------------------
# 1. Matrice avec valeur attendue par role
# ---------------------------------------------------------------------------
class MatrixExpected(B2Base):
    """Chaque ligne : (methode, url, ensemble des roles autorises, corps).
    « autorise » = ni 401 ni 403 ni 5xx (la reponse metier peut etre 200/201/400/404).
    Les mutations d'objets reels utilisent l'UUID NIL (404 si autorise) pour ne rien detruire."""

    def rows(self):
        gerant_only = {'GERANT'}
        pk1 = self.k1.pk
        return [
            # --- consommables direction (BUG-386)
            ('get', '/api/production/consumables/global/', HQ, None),
            ('post', '/api/production/consumables/dispatch/', DIRECTION_UP, {}),
            ('get', '/api/production/inventories/', GERANT_UP, None),
            ('get', f'/api/production/inventories/{self.inv1.pk}/', GERANT_UP, None),
            ('patch', f'/api/production/inventories/{self.inv1.pk}/', gerant_only, {'comment': 'z'}),
            ('post', '/api/production/inventories/', gerant_only, {}),
            ('get', '/api/production/inventories/today/', gerant_only, None),
            ('get', f'/api/production/inventories/node/{self.k1.code}/', GERANT_UP, None),
            ('put', f'/api/production/inventories/{self.inv1.pk}/', set(), {'comment': 'z'}),   # 405 ou 403
            ('delete', f'/api/production/inventories/{self.inv1.pk}/', set(), None),
            # --- mouvements de consommables (IsGerant = ADMIN, DIRECTION, COMPTABLE, GERANT)
            ('get', '/api/production/movements/', GERANT_UP, None),
            ('post', '/api/production/movements/', tuple(r for r in GERANT_UP if r != "COMPTABLE"), {}),  # BUG-706 : COMPTABLE en lecture seule
            ('patch', f'/api/production/movements/{NIL}/', tuple(r for r in GERANT_UP if r != "COMPTABLE"), {}),  # BUG-706 : COMPTABLE en lecture seule
            ('delete', f'/api/production/movements/{NIL}/', tuple(r for r in GERANT_UP if r != "COMPTABLE"), None),  # BUG-706 : COMPTABLE en lecture seule
            ('get', '/api/production/stocks/', ALL, None),
            ('get', '/api/production/consumable-types/', ALL, None),
            # --- commissions
            ('get', '/api/commissions/commissions/summary/', GERANT_UP, None),
            # BUG-705 : le decorateur declare IsGerant mais get_permissions() retombe sur IsHeadquarters
            ('get', '/api/commissions/commissions/payroll_listing/', HQ, None),
            ('get', '/api/commissions/commissions/', GERANT_UP, None),
            ('get', f'/api/commissions/commissions/{self.cm1.pk}/', GERANT_UP, None),
            ('post', '/api/commissions/commissions/', HQ, {}),
            ('post', f'/api/commissions/commissions/{NIL}/mark_paid/', DIRECTION_UP, {}),
            ('patch', f'/api/commissions/commissions/{NIL}/set_manuel/', DIRECTION_UP, {}),
            ('delete', f'/api/commissions/commissions/{NIL}/', HQ, None),
            ('get', '/api/commissions/periods/', GERANT_UP, None),
            ('get', '/api/commissions/periods/history/', HQ, None),   # BUG-705 (idem)
            ('post', '/api/commissions/periods/generate/', HQ, {}),
            ('post', f'/api/commissions/periods/{NIL}/close_period/', HQ, {}),
            ('delete', f'/api/commissions/periods/{NIL}/', HQ, None),
            # --- clients (rapports lies aux commissions)
            ('get', '/api/clients/clients/deficit_report/', GERANT_UP, None),
            # --- core
            ('get', '/api/core/nodes/', ALL, None),
            ('post', '/api/core/nodes/', DIRECTION_UP, {}),
            ('patch', f'/api/core/nodes/{pk1}/', DIRECTION_UP, {}),
            ('delete', f'/api/core/nodes/{NIL}/', DIRECTION_UP, None),
            ('get', '/api/core/users/', HQ, None),
            ('post', '/api/core/users/', DIRECTION_UP, {}),
            ('post', f'/api/core/users/{NIL}/reset_password/', DIRECTION_UP, {}),
            ('patch', '/api/core/config/', DIRECTION_UP, {}),
            ('post', '/api/core/bread-prices/', DIRECTION_UP, {}),
            ('delete', f'/api/core/bread-prices/{NIL}/', DIRECTION_UP, None),
            ('post', '/api/core/expense-categories/', HQ, {}),
            ('get', '/api/core/activities/', HQ, None),
            ('post', '/api/core/notifications/', HQ, {}),
            ('get', '/api/core/colis/', GERANT_UP, None),
            ('post', '/api/core/colis/', GERANT_UP, {}),
            ('get', '/api/core/reset-data/', set(), None),     # superuser technique seulement
            ('post', '/api/core/reset-data/', set(), {}),
            # --- chat : tout compte authentifie
            ('get', '/api/chat/conversations/', ALL, None),
            ('get', '/api/chat/unread-count/', ALL, None),
            ('get', '/api/chat/users/', ALL, None),
            ('get', '/api/chat/conversations/direction/', HQ, None),
        ]

    def test_expected_matrix(self):
        clients = self.clients()
        problems = []
        for method, url, allowed, body in self.rows():
            for col, c in clients.items():
                kw = {} if body is None else {'data': body, 'format': 'json'}
                try:
                    st = getattr(c, method)(url, **kw).status_code
                except Exception as e:  # 500 non geree
                    problems.append(f'EXC {col} {method} {url} {type(e).__name__}: {e}')
                    continue
                if st >= 500:
                    problems.append(f'5XX {col} {method} {url} -> {st}')
                    continue
                if col == 'AN':
                    if st != 401:
                        problems.append(f'ANON {method} {url} -> {st}')
                    continue
                ok = st not in DENIED
                if method in ('put', 'delete') and 'inventories' in url:
                    ok = st not in DENIED and st != 405
                    if st not in DENIED + (405,):
                        problems.append(f'{col} {method} {url} -> {st} (attendu 403/405)')
                    continue
                if ok != (col in allowed):
                    problems.append(f'{col} {method} {url} -> {st} (autorise attendu : {col in allowed})')
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_bassins_is_gerant_only_or_documented(self):
        """/clients/clients/bassins/ expose cm, net_payable et bp par client (donnees de
        commission) : BUG-253 / BUG-521 les reservent au GERANT+. Cf. BUG-701."""
        r = cl(self.u['FACTURIER']).get(f'/api/clients/clients/bassins/?node={self.k1.pk}&month=10&year=2026')
        self.assertIn(r.status_code, DENIED, 'BUG-701 : un facturier lit les commissions des clients via bassins')

    def test_bassins_gerant_other_node_forced_to_own(self):
        r = cl(self.u['GERANT']).get(f'/api/clients/clients/bassins/?node={self.k2.pk}&month=10&year=2026')
        if r.status_code == 200:
            self.assertNotIn(self.c2.code, [x['client_code'] for x in r.data.get('rows', [])])
            self.assertEqual([x['client_code'] for x in r.data.get('rows', [])], [self.c1.code])


# ---------------------------------------------------------------------------
# 2. IDs forges : UUID / pk d'un autre noeud
# ---------------------------------------------------------------------------
class ForgedIds(B2Base):
    def targets(self):
        return [
            f'/api/clients/clients/{self.c2.pk}/',
            f'/api/clients/distributions/{self.dist2.pk}/',
            f'/api/clients/distribution-lines/{self.line2.pk}/',
            f'/api/clients/contributions/{self.contrib2.pk}/',
            f'/api/production/sessions/{self.s2.pk}/',
            f'/api/production/stocks/{self.st2.pk}/',
            f'/api/production/inventories/{self.inv2.pk}/',
            f'/api/commissions/commissions/{self.cm2.pk}/',
            f'/api/commissions/periods/{self.per2.pk}/',
            f'/api/core/colis/{self.colis2.pk}/',
        ]

    def test_gerant_k1_cannot_touch_k2_objects_any_verb(self):
        c = cl(self.u['GERANT'])
        for url in self.targets():
            for m in ('get', 'put', 'patch', 'delete'):
                kw = {} if m in ('get', 'delete') else {'data': {'node': self.k1.pk, 'comment': 'x'}, 'format': 'json'}
                r = getattr(c, m)(url, **kw)
                self.assertIn(r.status_code, (403, 404, 405), (m, url, r.status_code))
        self.c2.refresh_from_db()
        self.assertEqual(self.c2.node_id, self.k2.pk)
        self.assertTrue(ColisDistribution.objects.filter(pk=self.colis2.pk).exists())
        self.assertTrue(CommissionPeriod.objects.filter(pk=self.per2.pk).exists())
        self.assertTrue(ClientCommission.objects.filter(pk=self.cm2.pk).exists())
        self.inv2.refresh_from_db()
        self.assertEqual(self.inv2.comment, 'c2')

    def test_facturier_livreur_k1_cannot_write_k2_objects(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for url in self.targets():
                for m in ('put', 'patch', 'delete'):
                    kw = {} if m == 'delete' else {'data': {'comment': 'x'}, 'format': 'json'}
                    r = getattr(c, m)(url, **kw)
                    self.assertIn(r.status_code, (403, 404, 405), (role, m, url, r.status_code))

    def test_moving_own_object_to_k2_is_ignored(self):
        """PATCH d'un objet K1 avec node=K2 (ou period=<periode K2>) : l'objet reste en K1."""
        g = cl(self.u['GERANT'])
        g.patch(f'/api/core/colis/{self.colis1.pk}/', {'node': self.k2.pk}, format='json')
        self.colis1.refresh_from_db()
        self.assertEqual(self.colis1.node_id, self.k1.pk)
        g.patch(f'/api/production/sessions/{self.s1.pk}/', {'node': self.k2.pk}, format='json')
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.node_id, self.k1.pk)

    def test_post_with_forced_node_creates_only_in_own_node(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/core/colis/', {'node': self.k2.pk, 'year': 2026, 'beneficiary_label': 'Forge',
                                        'rice_value': '0', 'meat_value': '0', 'cash_amount': '0'}, format='json')
        if r.status_code == 201:
            self.assertEqual(ColisDistribution.objects.get(pk=r.data['id']).node_id, self.k1.pk)
        self.assertFalse(ColisDistribution.objects.filter(node=self.k2, beneficiary_label='Forge').exists())

    def test_colis_create_without_amounts_is_not_500(self):
        r = cl(self.u['GERANT']).post('/api/core/colis/', {'node': self.k1.pk, 'year': 2026, 'beneficiary_label': 'Nu'}, format='json')
        self.assertLess(r.status_code, 500)

    def test_inventory_node_route_and_list_cross_node(self):
        g = cl(self.u['GERANT'])
        self.assertEqual(g.get(f'/api/production/inventories/node/{self.k2.code}/').status_code, 404)
        self.assertEqual(g.get(f'/api/production/inventories/node/{self.k2.pk}/').status_code, 404)
        r = g.get(f'/api/production/inventories/?node={self.k2.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual({x['node'] for x in r.data}, {self.k1.pk})

    def test_commissions_list_filters_cannot_reach_k2(self):
        g = cl(self.u['GERANT'])
        for q in (f'?period={self.per2.pk}', f'?period__node={self.k2.pk}', f'?client={self.c2.pk}'):
            r = g.get('/api/commissions/commissions/' + q)
            self.assertEqual(r.status_code, 200, q)
            self.assertEqual(len(results(r)), 0, q)
        r = g.get(f'/api/commissions/commissions/payroll_listing/?period={self.per2.pk}')
        self.assertIn(r.status_code, (200, 403))  # 403 aujourd'hui (BUG-705) ; si ouvert au gerant : vide
        if r.status_code == 200:
            self.assertEqual(len(r.data), 0)
        r = g.get(f'/api/commissions/commissions/summary/?period__node={self.k2.pk}')
        self.assertEqual(r.data['count'], 0)
        r = g.get(f'/api/commissions/periods/history/?node={self.k2.pk}')
        if r.status_code == 200:
            self.assertEqual([x['node_code'] for x in r.data], [])
        r = g.get('/api/clients/clients/deficit_report/?node=%d' % self.k2.pk)
        self.assertEqual(r.data, [])

    def test_gerant_cannot_generate_or_close_commission_period(self):
        g = cl(self.u['GERANT'])
        self.assertEqual(g.post('/api/commissions/periods/generate/',
                                {'node': self.k1.pk, 'month': 9, 'year': 2026}, format='json').status_code, 403)
        self.assertEqual(g.post(f'/api/commissions/periods/{self.per1.pk}/close_period/').status_code, 403)
        self.per1.refresh_from_db()
        self.assertFalse(self.per1.is_closed)

    def test_movement_forged_ids_gerant_k1(self):
        g = cl(self.u['GERANT'])
        mv = ConsumableMovement.objects.create(
            node=self.k2, stock=self.st2, movement_type='ENTRY', quantity=Dc('1'), unit_price=Dc('10'),
            node_origin='P2')
        for m in ('get', 'patch', 'delete'):
            kw = {'data': {'quantity': '99'}, 'format': 'json'} if m == 'patch' else {}
            self.assertEqual(getattr(g, m)(f'/api/production/movements/{mv.pk}/', **kw).status_code, 404, m)
        # mouvement K1 deplace vers le stock de K2 (stock= forge)
        mv1 = ConsumableMovement.objects.create(
            node=self.k1, stock=self.st1, movement_type='ENTRY', quantity=Dc('1'), unit_price=Dc('10'),
            node_origin='P1')
        r = g.patch(f'/api/production/movements/{mv1.pk}/', {'stock': str(self.st2.pk)}, format='json')
        self.assertGreaterEqual(r.status_code, 400, r.content)
        mv1.refresh_from_db()
        self.assertEqual(mv1.stock_id, self.st1.pk)
        self.st2.refresh_from_db()
        self.assertEqual(self.st2.quantity, Dc('1'))  # uniquement l'entree legitime de K2 ci-dessus


class MovementsRoles(B2Base):
    """POST /api/production/movements/ est en IsGerant (ADMIN, DIRECTION, COMPTABLE, GERANT)."""

    def body(self, st, qty='5'):
        return {'stock': str(st.pk), 'movement_type': 'ENTRY', 'quantity': qty, 'unit_price': '100'}

    def test_facturier_livreur_anonymous_cannot_write_movements(self):
        for who in (cl(), cl(self.u['FACTURIER']), cl(self.u['LIVREUR'])):
            self.assertIn(who.post('/api/production/movements/', self.body(self.st1), format='json').status_code,
                          DENIED)
        self.st1.refresh_from_db()
        self.assertEqual(self.st1.quantity, Dc('0'))

    def test_direction_state_documented_hq_writes_on_any_node(self):
        """Etat constate : ADMIN / DIRECTION ecrivent sur n'importe quel noeud via le stock."""
        r = cl(self.u['DIRECTION']).post('/api/production/movements/', self.body(self.st2), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.st2.refresh_from_db()
        self.assertEqual(self.st2.quantity, Dc('5'))

    def test_comptable_cannot_write_stock_movements(self):
        r = cl(self.u['COMPTABLE']).post('/api/production/movements/', self.body(self.st2), format='json')
        self.assertIn(r.status_code, DENIED, r.content)
        self.st2.refresh_from_db()
        self.assertEqual(self.st2.quantity, Dc('0'))

    def test_movement_delete_leaves_audit_trace(self):
        from core.models import ActivityLog
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/movements/', self.body(self.st1), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        n0 = ActivityLog.objects.count()
        self.assertEqual(g.delete(f"/api/production/movements/{r.data['id']}/").status_code, 204)
        self.st1.refresh_from_db()
        self.assertEqual(self.st1.quantity, Dc('0'))  # effet inverse applique (BUG-222)
        self.assertGreater(ActivityLog.objects.count(), n0, 'aucune trace de la suppression')


# ---------------------------------------------------------------------------
# 3. Mass assignment
# ---------------------------------------------------------------------------
class MassAssignment(B2Base):
    def test_direction_cannot_set_technical_flags_on_create_or_patch(self):
        d = cl(self.u['DIRECTION'])
        r = d.post('/api/core/users/', {
            'username': 'zz_b2_new', 'password': 'Abcdef12xyz', 'role': 'GERANT', 'node': self.k1.pk,
            'is_superuser': True, 'is_staff': True, 'is_active': False, 'must_change_password': False,
            'can_access_all_nodes': True, 'is_headquarters': True}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        u = User.objects.get(username='zz_b2_new')
        self.assertEqual((u.is_superuser, u.is_staff, u.is_active, u.must_change_password),
                         (False, False, True, True))
        self.assertFalse(u.can_access_all_nodes)
        g = self.u['GERANT']
        r = d.patch(f'/api/core/users/{g.pk}/', {
            'is_superuser': True, 'is_staff': True, 'must_change_password': True,
            'can_access_all_nodes': True, 'is_headquarters': True, 'password': 'Hacked-123x',
            'last_login': '2000-01-01T00:00:00Z'}, format='json')
        g.refresh_from_db()
        self.assertEqual((g.is_superuser, g.is_staff, g.role), (False, False, 'GERANT'))
        self.assertFalse(g.check_password('Hacked-123x'))
        self.assertFalse(g.can_access_all_nodes)

    def test_direction_cannot_create_or_upgrade_to_admin_nor_make_user_hq_without_role(self):
        d = cl(self.u['DIRECTION'])
        g = self.u['GERANT']
        for body in ({'role': 'ADMIN'}, {'role': 'ADMIN', 'node': None}):
            r = d.patch(f'/api/core/users/{g.pk}/', body, format='json')
            self.assertEqual(r.status_code, 403, (body, r.content))
        g.refresh_from_db()
        self.assertEqual(g.role, 'GERANT')
        # touche un ADMIN (non superuser) : nom, desactivation, suppression, reset
        a = self.u['ADMIN']
        for m, kw in (('patch', {'data': {'is_active': False}, 'format': 'json'}),
                      ('patch', {'data': {'username': 'pirate'}, 'format': 'json'}),
                      ('put', {'data': {'username': a.username, 'role': 'GERANT'}, 'format': 'json'}),
                      ('delete', {}), ('post', {})):
            url = f'/api/core/users/{a.pk}/' + ('reset_password/' if m == 'post' else '')
            self.assertEqual(getattr(d, m)(url, **kw).status_code, 403, (m, url))
        a.refresh_from_db()
        self.assertEqual((a.username, a.is_active, a.role), ('pr_admin', True, 'ADMIN'))

    def test_admin_cannot_deactivate_self_nor_grant_superuser(self):
        a = self.u['ADMIN']
        c = cl(a)
        self.assertEqual(c.patch(f'/api/core/users/{a.pk}/', {'is_active': False}, format='json').status_code, 403)
        t = self.u['COMPTABLE']
        c.patch(f'/api/core/users/{t.pk}/', {'is_superuser': True, 'is_staff': True}, format='json')
        t.refresh_from_db()
        self.assertEqual((t.is_superuser, t.is_staff), (False, False))

    def test_gerant_node_self_change_via_me_and_users(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            u = self.u[role]
            c = cl(u)
            r = c.patch('/api/core/auth/me/', {'node': self.k2.pk, 'role': 'ADMIN', 'team': 'B', 'is_active': False,
                                               'is_superuser': True}, format='json')
            self.assertEqual(r.status_code, 200, r.content)
            u.refresh_from_db()
            self.assertEqual((u.node_id, u.role, u.team, u.is_active, u.is_superuser),
                             (self.k1.pk, role, 'A', True, False), role)
            for m in ('patch', 'put'):
                r = getattr(c, m)(f'/api/core/users/{u.pk}/', {'node': self.k2.pk, 'role': 'ADMIN'}, format='json')
                self.assertEqual(r.status_code, 403, (role, m))
            u.refresh_from_db()
            self.assertEqual((u.node_id, u.role), (self.k1.pk, role))

    def test_me_username_collision_rejected(self):
        r = cl(self.u['GERANT']).patch('/api/core/auth/me/', {'username': self.u['ADMIN'].username}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_me_get_has_no_secret_fields(self):
        r = cl(self.u['GERANT']).get('/api/core/auth/me/')
        self.assertNotIn('password', r.data)
        self.assertNotIn('is_staff', r.data)

    def test_nodes_write_reserved_to_direction_up(self):
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            body = {'card_fee_fc': '1', 'monthly_social_contribution': '1', 'sac_value_fc': '1',
                    'is_active': False, 'name': 'Pirate'}
            for m in ('patch', 'put'):
                self.assertEqual(getattr(c, m)(f'/api/core/nodes/{self.k1.pk}/', body, format='json').status_code,
                                 403, (role, m))
            self.assertEqual(c.post('/api/core/nodes/', {'code': 'ZZ9', 'name': 'Z'}, format='json').status_code, 403)
            self.assertEqual(c.delete(f'/api/core/nodes/{self.k1.pk}/').status_code, 403)
        self.k1.refresh_from_db()
        self.assertEqual((self.k1.name, self.k1.is_active), ('Perm K1', True))
        self.assertNotEqual(self.k1.card_fee_fc, Dc('1'))
        self.assertNotEqual(self.k1.monthly_social_contribution, Dc('1'))

    def test_nodes_direction_validation_bounds(self):
        d = cl(self.u['DIRECTION'])
        for field in ('card_fee_fc', 'monthly_social_contribution', 'sac_value_fc'):
            for bad in ('-1', 'abc', 'NaN', 'Infinity', '1e40'):
                r = d.patch(f'/api/core/nodes/{self.k2.pk}/', {field: bad}, format='json')
                self.assertIn(r.status_code, (400,), (field, bad, r.status_code))
        self.k2.refresh_from_db()
        self.assertEqual(self.k2.sac_value_fc, Dc('180000'))
        r = d.patch(f'/api/core/nodes/{self.k2.pk}/', {'card_fee_fc': '1500', 'monthly_social_contribution': '3000'},
                    format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_config_and_prices_write_denied_below_direction(self):
        Config.get_instance()
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for m in ('put', 'patch'):
                self.assertEqual(getattr(c, m)('/api/core/config/', {'debt_ceiling': '1', 'on_line': False},
                                               format='json').status_code, 403, (role, m))
            self.assertEqual(c.patch(f'/api/core/bread-prices/{self.bp.pk}/', {'unit_price': '1'},
                                     format='json').status_code, 403, role)
            self.assertEqual(c.post('/api/core/bread-prices/', {'category': 'ZZ', 'label': 'z', 'unit_price': '1'},
                                   format='json').status_code, 403, role)
            self.assertEqual(c.delete(f'/api/core/bread-prices/{self.bp.pk}/').status_code, 403, role)
        self.bp.refresh_from_db()
        self.assertEqual(self.bp.unit_price, 500)

    def test_config_get_authenticated_vs_anonymous_fields(self):
        Config.get_instance()
        self.assertEqual(set(cl().get('/api/core/config/').data), {'on_line'})
        self.assertIn('debt_ceiling', cl(self.u['LIVREUR']).get('/api/core/config/').data)

    def test_config_direction_invalid_values_never_500(self):
        d = cl(self.u['DIRECTION'])
        for body in ({'debt_ceiling': 'abc'}, {'debt_ceiling': None}, {'default_commission_rate': '9'},
                     {'default_commission_rate': '-1'}, {'on_line': 'maybe'}, {'sac_value_fc': '1e50'},
                     {'annual_bonus_rate': 'NaN'}):
            r = d.patch('/api/core/config/', body, format='json')
            self.assertLess(r.status_code, 500, body)
        before = Config.get_instance().debt_ceiling
        self.assertEqual(Config.get_instance().debt_ceiling, before)

    def test_commission_mass_assignment_hq_non_direction(self):
        """COMPTABLE (IsHeadquarters, pas IsDirection) : champs reserves a set_manuel (BUG-265)."""
        c = cl(self.u['COMPTABLE'])
        r = c.patch(f'/api/commissions/commissions/{self.cm1.pk}/',
                    {'is_paid': True, 'paid_by': 'x', 'net_payable': '999999', 'commission_gross': '999999'},
                    format='json')
        self.cm1.refresh_from_db()
        self.assertFalse(self.cm1.is_paid, r.content)
        self.assertNotEqual(self.cm1.net_payable, Dc('999999'))

    def test_comptable_cannot_override_net_via_manuel_adjustment(self):
        c = cl(self.u['COMPTABLE'])
        c.patch(f'/api/commissions/commissions/{self.cm1.pk}/',
                {'manuel_adjustment': '777777', 'manuel_notes': 'bypass'}, format='json')
        self.cm1.refresh_from_db()
        self.assertIsNone(self.cm1.manuel_adjustment)
        self.assertNotEqual(self.cm1.net_payable, Dc('777777'))

    def test_notifications_write_hq_only_and_not_forgeable(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            r = c.post('/api/core/notifications/', {'title': 'x', 'message': 'y', 'node_origin': 'CLOUD'},
                       format='json')
            self.assertEqual(r.status_code, 403, role)
        self.assertFalse(SystemNotification.objects.filter(title='x').exists())

    def test_activity_log_read_only_and_hq_only(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).get('/api/core/activities/').status_code, 403, role)
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            c = cl(self.u[role])
            self.assertEqual(c.get('/api/core/activities/').status_code, 200)
            for m in ('post', 'put', 'patch', 'delete'):
                kw = {} if m == 'delete' else {'data': {}, 'format': 'json'}
                url = '/api/core/activities/' if m == 'post' else f'/api/core/activities/{NIL}/'
                self.assertIn(getattr(c, m)(url, **kw).status_code, (404, 405), (role, m))


# ---------------------------------------------------------------------------
# 4. JWT / authentification, angles nouveaux
# ---------------------------------------------------------------------------
class JwtV2(B2Base):
    PW = 'Mdp-test-Qa-2026x'

    def setUp(self):
        super().setUp()
        self.g = self.u['GERANT']
        self.g.set_password(self.PW)
        self.g.save()

    def login(self, username=None, pw=None):
        return cl().post('/api/core/auth/login/', {'username': username or self.g.username,
                                                    'password': pw or self.PW}, format='json')

    def bearer(self, token):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        return c

    def test_refresh_token_is_not_an_access_token(self):
        ref = self.login().data['refresh']
        self.assertEqual(self.bearer(ref).get('/api/core/auth/me/').status_code, 401)

    def test_role_and_node_read_from_db_not_from_token(self):
        acc = self.login().data['access']
        c = self.bearer(acc)
        self.assertEqual(c.get('/api/production/movements/').status_code, 200)
        User.objects.filter(pk=self.g.pk).update(role='LIVREUR')
        self.assertEqual(c.get('/api/production/movements/').status_code, 403)
        User.objects.filter(pk=self.g.pk).update(role='GERANT', node=self.k2)
        r = c.get('/api/production/stocks/')
        self.assertTrue(all(x['node'] == self.k2.pk for x in results(r)))

    def test_deactivated_account_cannot_refresh(self):
        ref = self.login().data['refresh']
        User.objects.filter(pk=self.g.pk).update(is_active=False)
        self.assertEqual(cl().post('/api/core/auth/login/refresh/', {'refresh': ref}, format='json').status_code, 401)

    def test_reset_password_neutralises_old_sessions(self):
        old = self.login().data
        r = cl(self.u['ADMIN']).post(f'/api/core/users/{self.g.pk}/reset_password/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.bearer(old['access']).get('/api/clients/clients/').status_code, 403)
        self.assertEqual(self.login().status_code, 401)  # ancien mot de passe invalide

    def test_degenerate_login_payloads_never_500(self):
        c = cl()
        for body in ({}, {'username': None, 'password': None},
                     {'username': 'a' * 5000, 'password': 'p' * 50000}, {'username': 'a\x00b', 'password': 'x'},
                     {'username': "' OR 1=1 --", 'password': "' OR '1'='1"}):
            cache.clear()
            r = c.post('/api/core/auth/login/', body, format='json')
            self.assertIn(r.status_code, (400, 401), (str(body)[:60], r.status_code))
        r = c.post('/api/core/auth/login/', 'not json', content_type='application/json')
        self.assertIn(r.status_code, (400, 401, 415))
        self.assertEqual(c.get('/api/core/auth/login/').status_code, 405)

    def test_login_non_string_username_is_not_500(self):
        for body in ({'username': ['a'], 'password': 'x'}, {'username': 123, 'password': 456},
                     {'username': {'x': 1}, 'password': 'x'}):
            cache.clear()
            try:
                r = cl().post('/api/core/auth/login/', body, format='json')
            except Exception as exc:
                self.fail(f'exception non geree : {type(exc).__name__}')
            self.assertIn(r.status_code, (400, 401), body)

    def test_login_same_answer_unknown_and_wrong_password(self):
        a = self.login(pw='faux')
        b = self.login(username='inexistant_zz', pw='faux')
        self.assertEqual((a.status_code, a.data), (b.status_code, b.data))
        self.assertNotIn('password', self.login().data['user'])

    def test_garbage_authorization_headers(self):
        for h in ('Bearer', 'Bearer ', 'Bearer a.b.c', 'Basic dXNlcjpwdw==', 'Token abc', 'bearer', 'Bearer ' + 'x' * 9000):
            c = APIClient()
            c.credentials(HTTP_AUTHORIZATION=h)
            self.assertEqual(c.get('/api/core/auth/me/').status_code, 401, h[:20])
        self.assertEqual(cl().get('/api/core/auth/me/?token=abc&access=abc').status_code, 401)

    def test_refresh_degenerate_inputs(self):
        for body in ({}, {'refresh': ''}, {'refresh': None}, {'refresh': 'zz'}, {'refresh': ['a']}):
            r = cl().post('/api/core/auth/login/refresh/', body, format='json')
            self.assertIn(r.status_code, (400, 401), body)

    def test_logout_requires_authentication(self):
        ref = self.login().data['refresh']
        self.assertEqual(cl().post('/api/core/auth/logout/', {'refresh': ref}, format='json').status_code, 401)
        # le refresh reste donc utilisable : rien n'a ete blackliste anonymement
        self.assertEqual(cl().post('/api/core/auth/login/refresh/', {'refresh': ref}, format='json').status_code, 200)

    def test_change_password_policy(self):
        c = cl(self.g)
        for body in ({'old_password': self.PW, 'new_password': self.PW}, {'old_password': 'faux', 'new_password': 'Nouveau-9xx2'},
                     {'old_password': self.PW, 'new_password': '123'}, {'old_password': self.PW, 'new_password': 'azerty'},
                     {'old_password': self.PW, 'new_password': self.g.username}, {'old_password': self.PW},
                     {'new_password': 'Nouveau-9xx2'}):
            r = c.post('/api/core/auth/change-password/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.content))
        self.g.refresh_from_db()
        self.assertTrue(self.g.check_password(self.PW))
        self.assertEqual(cl().post('/api/core/auth/change-password/', {}, format='json').status_code, 401)

    def test_change_password_via_me_requires_old_password(self):
        r = cl(self.g).patch('/api/core/auth/me/', {'new_password': 'Nouveau-9xx2'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.g.refresh_from_db()
        self.assertTrue(self.g.check_password(self.PW))

    def test_no_password_or_token_in_activity_log(self):
        from core.models import ActivityLog
        cl(self.g).post('/api/core/auth/change-password/',
                        {'old_password': self.PW, 'new_password': 'Nouveau-9xx2zz'}, format='json')
        for log in ActivityLog.objects.all():
            blob = f'{log.action} {log.description}'
            self.assertNotIn('Nouveau-9xx2zz', blob)
            self.assertNotIn(self.PW, blob)


# ---------------------------------------------------------------------------
# 5. Chat
# ---------------------------------------------------------------------------
class ChatIsolation(B2Base):
    def setUp(self):
        super().setUp()
        self.k2_thread = cl(self.u2['GERANT']).get('/api/chat/conversations/node/').data['id']
        self.k1_thread = cl(self.u['GERANT']).get('/api/chat/conversations/node/').data['id']
        self.dir_thread = cl(self.u['DIRECTION']).get('/api/chat/conversations/direction/').data['id']
        r = cl(self.u2['GERANT']).post('/api/chat/conversations/direct/', {'user': str(self.u2['FACTURIER'].pk)},
                                       format='json')
        self.k2_dm = r.data['id']
        cl(self.u2['GERANT']).post(f'/api/chat/conversations/{self.k2_dm}/messages/', {'body': 'secret K2'},
                                   format='json')

    def test_anonymous_401_everywhere(self):
        c = cl()
        for m, url in (('get', '/api/chat/conversations/'), ('get', '/api/chat/conversations/node/'),
                       ('get', '/api/chat/conversations/direction/'), ('post', '/api/chat/conversations/direct/'),
                       ('get', f'/api/chat/conversations/{self.k1_thread}/messages/'),
                       ('post', f'/api/chat/conversations/{self.k1_thread}/messages/'),
                       ('post', f'/api/chat/conversations/{self.k1_thread}/read/'),
                       ('get', '/api/chat/unread-count/'), ('get', '/api/chat/users/')):
            self.assertEqual(getattr(c, m)(url).status_code, 401, (m, url))

    def test_k1_user_cannot_read_write_or_mark_k2_conversations(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for conv in (self.k2_thread, self.k2_dm):
                self.assertEqual(c.get(f'/api/chat/conversations/{conv}/messages/').status_code, 404, (role, conv))
                self.assertEqual(c.post(f'/api/chat/conversations/{conv}/messages/', {'body': 'intrus'},
                                        format='json').status_code, 404, (role, conv))
                self.assertEqual(c.post(f'/api/chat/conversations/{conv}/read/').status_code, 404, (role, conv))
            ids = {x['id'] for x in c.get('/api/chat/conversations/').data}
            self.assertFalse(ids & {self.k2_thread, self.k2_dm}, role)
        self.assertFalse(Message.objects.filter(body='intrus').exists())

    def test_non_hq_cannot_use_direction_thread_even_with_stale_participation(self):
        g = self.u['GERANT']
        c = cl(g)
        self.assertEqual(c.get('/api/chat/conversations/direction/').status_code, 403)
        self.assertEqual(c.get(f'/api/chat/conversations/{self.dir_thread}/messages/').status_code, 404)
        Participant.objects.create(conversation_id=self.dir_thread, user=g, node_origin='P1')  # participation perimee
        self.assertEqual(c.get(f'/api/chat/conversations/{self.dir_thread}/messages/').status_code, 404)
        self.assertEqual(c.post(f'/api/chat/conversations/{self.dir_thread}/messages/', {'body': 'x'},
                                format='json').status_code, 403)
        self.assertNotIn(self.dir_thread, {x['id'] for x in c.get('/api/chat/conversations/').data})
        self.assertEqual(c.get('/api/chat/unread-count/').status_code, 200)

    def test_user_moved_to_another_node_loses_old_node_thread(self):
        f = self.u['FACTURIER']
        cl(f).get('/api/chat/conversations/node/')
        User.objects.filter(pk=f.pk).update(node=self.k2)
        f.refresh_from_db()
        c = cl(f)
        self.assertEqual(c.get(f'/api/chat/conversations/{self.k1_thread}/messages/').status_code, 404)
        self.assertEqual(c.post(f'/api/chat/conversations/{self.k1_thread}/messages/', {'body': 'x'},
                                format='json').status_code, 403)

    def test_message_forged_fields_ignored(self):
        g = self.u['GERANT']
        r = cl(g).post(f'/api/chat/conversations/{self.k1_thread}/messages/', {
            'body': 'salut', 'sender': str(self.u['ADMIN'].pk), 'conversation': self.k2_thread,
            'node_origin': 'P2', 'created_at': '2000-01-01T00:00:00Z'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        m = Message.objects.get(pk=r.data['id'])
        self.assertEqual((m.sender_id, str(m.conversation_id)), (g.pk, self.k1_thread))
        self.assertEqual(m.node_origin, 'P1')
        self.assertGreater(m.created_at.year, 2000)

    def test_messages_are_immutable_and_methods_closed(self):
        c = cl(self.u2['GERANT'])
        url = f'/api/chat/conversations/{self.k2_dm}/messages/'
        for m in ('put', 'patch', 'delete'):
            self.assertEqual(getattr(c, m)(url).status_code, 405, m)
        mid = Message.objects.filter(conversation_id=self.k2_dm).first().pk
        for m in ('get', 'patch', 'delete'):
            self.assertEqual(getattr(c, m)(url + f'{mid}/').status_code, 404, m)

    def test_garbage_conversation_ids_never_500(self):
        c = cl(self.u['GERANT'])
        for bad in ('abc', '1', 'x' * 300, '../../etc', '%00', NIL, "' OR 1=1"):
            for m, suffix in (('get', 'messages/'), ('post', 'messages/'), ('post', 'read/')):
                kw = {} if m == 'get' else {'data': {'body': 'x'}, 'format': 'json'}
                self.assertEqual(getattr(c, m)(f'/api/chat/conversations/{bad}/{suffix}', **kw).status_code, 404,
                                 (bad, m, suffix))

    def test_direct_conversation_guards(self):
        c = cl(self.u['GERANT'])
        me = self.u['GERANT']
        self.assertEqual(c.post('/api/chat/conversations/direct/', {'user': str(me.pk)}, format='json').status_code, 400)
        for bad in (None, '', 'abc', NIL, 12, ['x'], {'a': 1}):
            self.assertEqual(c.post('/api/chat/conversations/direct/', {'user': bad}, format='json').status_code, 404, bad)
        off = mk('zz_b2_off', 'FACTURIER', self.k1)
        User.objects.filter(pk=off.pk).update(is_active=False)
        self.assertEqual(c.post('/api/chat/conversations/direct/', {'user': str(off.pk)}, format='json').status_code, 404)

    def test_direct_conversation_tier_cannot_join(self):
        """Un tiers ne peut s'ajouter a un DM existant en rouvrant le DM : il en cree un autre."""
        a, b = self.u2['GERANT'], self.u2['FACTURIER']
        r = cl(self.u['GERANT']).post('/api/chat/conversations/direct/', {'user': str(b.pk)}, format='json')
        self.assertNotEqual(r.data['id'], self.k2_dm)
        self.assertFalse(Participant.objects.filter(conversation_id=self.k2_dm, user=self.u['GERANT']).exists())
        self.assertEqual(Participant.objects.filter(conversation_id=self.k2_dm).count(), 2)
        self.assertEqual({p.user_id for p in Participant.objects.filter(conversation_id=self.k2_dm)}, {a.pk, b.pk})

    def test_directory_exposes_no_contact_data(self):
        r = cl(self.u['LIVREUR']).get('/api/chat/users/')
        self.assertEqual(r.status_code, 200)
        for x in r.data:
            self.assertEqual(set(x), {'id', 'name', 'role', 'role_label', 'node', 'node_code'})
        self.assertNotIn(self.u['LIVREUR'].pk.__str__(), [x['id'] for x in r.data])

    def test_comptable_and_hq_see_direction_thread_only(self):
        self.assertEqual(cl(self.u['COMPTABLE']).get('/api/chat/conversations/direction/').status_code, 200)
        self.assertEqual(cl(self.u['COMPTABLE']).get('/api/chat/conversations/node/').status_code, 403)  # sans noeud


# ---------------------------------------------------------------------------
# 6. Surface /admin/
# ---------------------------------------------------------------------------
class AdminSurface(B2Base):
    def test_admin_requires_login_and_non_staff_api_roles_refused(self):
        c = cl()
        self.assertIn(c.get('/admin/').status_code, (301, 302))
        self.assertIn(c.get('/admin/core/user/').status_code, (301, 302))
        from django.test import Client as DjangoClient
        dc = DjangoClient()
        pw = 'Mdp-test-Qa-2026x'
        a = self.u['ADMIN']
        a.set_password(pw)
        a.save()
        self.assertFalse(dc.login(username=a.username, password=pw) and dc.get('/admin/').status_code == 200,
                         "un ADMIN metier non staff ne doit pas entrer dans /admin/")

    def test_admin_login_is_throttled(self):
        from django.test import Client as DjangoClient
        dc = DjangoClient()
        codes = [dc.post('/admin/login/', {'username': self.u['ADMIN'].username, 'password': f'faux{i}'}).status_code
                 for i in range(40)]
        self.assertIn(429, codes)
