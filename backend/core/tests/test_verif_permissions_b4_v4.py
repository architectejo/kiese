"""Verification BUG-760 + matrice roles x routes sur ce qui a change depuis b3
(testeur-permissions, ronde b4, 2026-11-22). Donnees fictives. Code applicatif non modifie.

Perimetre : clients destroy, commissions (set_manuel, generate, summary, payroll_listing, mark_paid,
CRUD), sync (pull curseur, push, status, handshake, conflicts), tresorerie (resoumission de cloture),
blockchain (integrity_check, run_check, is_tampered, alertes), sales adjust, COMPTABLE.
"""
import uuid
from datetime import date
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.core.cache import cache
from django.utils import timezone

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.models import ActivityLog, BreadPrice
from core.tests import test_verif_permissions_b2_v2 as b2
from core.tests.test_permissions_regression_2026_11_19 import (
    DIRECTION_UP, GERANT_UP, HQ, ROLES, cl, mk)
from blockchain.models import TamperAlert
from sales.models import Invoice, InvoiceLine
from sync.models import NodeAuthToken
from treasury.models import CashbookEntry, CashClosure
from rest_framework.test import APIClient

NIL = '00000000-0000-0000-0000-000000000000'
DENIED = (401, 403)


def codes(r):
    return r.status_code


BUG762_SUFFIXES = ('/set_manuel/', '/mark_paid/', '/periods/generate/', '/validate/', '/reject/', '/bulk_delete/', '/bulk_move/')


class B4(b2.B2Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.today = timezone.localdate()
        _, cls.raw1 = NodeAuthToken.issue_for_node(cls.k1)
        _, cls.raw2 = NodeAuthToken.issue_for_node(cls.k2)

    def mk_invoice(self, node=None, client=None, status=Invoice.Status.DELIVERED, rcpt=None):
        node = node or self.k1
        client = client or (self.c1 if node == self.k1 else self.c2)
        inv = Invoice.objects.create(
            node=node, client=client, facturier=self.u['FACTURIER'] if node == self.k1 else self.u2['FACTURIER'],
            team='A', payment_type='CASH', payment_amount=500, debt_before=0, order_total=500,
            commission_rate='0.25', node_origin=node.code, receipt_number=rcpt or f'B4-{uuid.uuid4().hex[:8]}',
            status=status)
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=1)
        return inv

    def node_client(self, raw):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
        return c


# ---------------------------------------------------------------------------
# 1. BUG-760 : DELETE client protege -> 400
# ---------------------------------------------------------------------------
class Bug760(B4):
    def _delete(self, who, cid):
        c = cl(who)
        c.raise_request_exception = False
        return c.delete(f'/api/clients/clients/{cid}/')

    def test_protected_by_social_distribution_line_is_400_with_detail(self):
        # c1 est reference par line1 (PROTECT) dans Base
        for role in ('GERANT', 'COMPTABLE', 'DIRECTION', 'ADMIN'):
            r = self._delete(self.u[role], self.c1.pk)
            self.assertEqual(r.status_code, 400, (role, r.content))
            self.assertIn('detail', r.json())
            self.assertTrue(Client.objects.filter(pk=self.c1.pk).exists())

    def test_protected_by_invoice_is_400(self):
        self.mk_invoice(self.k2, self.c2)
        SocialLineGone = self.line2.__class__.objects.filter(pk=self.line2.pk).delete()
        r = self._delete(self.u['DIRECTION'], self.c2.pk)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertTrue(Client.objects.filter(pk=self.c2.pk).exists())

    def test_protected_by_commission_is_400(self):
        self.line1.__class__.objects.filter(pk=self.line1.pk).delete()
        # cm1 reference c1 (ClientCommission)
        r = self._delete(self.u['GERANT'], self.c1.pk)
        self.assertLess(r.status_code, 500, r.content)
        if ClientCommission.objects.filter(client=self.c1).exists():
            self.assertTrue(Client.objects.filter(pk=self.c1.pk).exists())
            self.assertEqual(r.status_code, 400, r.content)

    def test_unreferenced_client_deleted_204_and_roles_matrix(self):
        free = Client.objects.create(node=self.k1, node_origin='P1', first_name='Libre', last_name='Zero')
        self.assertEqual(self._delete(None, free.pk).status_code, 401)
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(self._delete(self.u[role], free.pk).status_code, 403, role)
        self.assertEqual(self._delete(self.u2['GERANT'], free.pk).status_code, 404)  # autre noeud
        self.assertEqual(self._delete(self.u['GERANT'], free.pk).status_code, 204)
        self.assertFalse(Client.objects.filter(pk=free.pk).exists())

    def test_ids_forges_never_500(self):
        for ref in (NIL, str(uuid.uuid4()), 'abc', '1', '%27'):
            self.assertLess(self._delete(self.u['DIRECTION'], ref).status_code, 500, ref)


# ---------------------------------------------------------------------------
# 2. Commissions : matrice roles x routes + isolation
# ---------------------------------------------------------------------------
class CommissionsMatrix(B4):
    def routes(self):
        p1, p2 = self.per1.pk, self.per2.pk
        cm1 = self.cm1.pk
        return [
            # (methode, url, roles autorises (200-499 hors 401/403), corps)
            ('get', '/api/commissions/periods/', GERANT_UP, None),
            ('get', f'/api/commissions/periods/{p1}/', GERANT_UP, None),
            ('get', '/api/commissions/periods/history/', HQ, None),
            ('post', '/api/commissions/periods/', HQ, {}),
            ('patch', f'/api/commissions/periods/{p1}/', HQ, {}),
            ('delete', f'/api/commissions/periods/{uuid.uuid4()}/', HQ, None),
            ('post', '/api/commissions/periods/generate/', HQ, {}),
            ('post', f'/api/commissions/periods/{uuid.uuid4()}/close_period/', HQ, {}),
            ('get', '/api/commissions/commissions/', GERANT_UP, None),
            ('get', f'/api/commissions/commissions/{cm1}/', GERANT_UP, None),
            ('get', '/api/commissions/commissions/summary/', GERANT_UP, None),
            ('get', '/api/commissions/commissions/payroll_listing/', HQ, None),
            ('post', '/api/commissions/commissions/', HQ, {}),
            ('patch', f'/api/commissions/commissions/{uuid.uuid4()}/', HQ, {}),
            ('delete', f'/api/commissions/commissions/{uuid.uuid4()}/', HQ, None),
            ('post', f'/api/commissions/commissions/{uuid.uuid4()}/mark_paid/', DIRECTION_UP, {}),
            ('patch', f'/api/commissions/commissions/{uuid.uuid4()}/set_manuel/', DIRECTION_UP, {}),
        ]

    def test_matrix(self):
        bad = []
        for m, url, allowed, body in self.routes():
            def call(who):
                c = cl(who)
                c.raise_request_exception = False
                return getattr(c, m)(url, body, format='json') if body is not None else getattr(c, m)(url)
            s = call(None).status_code
            if s != 401:
                bad.append(('anon', m, url, s))
            for role in ROLES:
                s = call(self.u[role]).status_code
                if role in allowed and s in DENIED:
                    bad.append((role, m, url, s, 'refuse a tort'))
                if role not in allowed and s != 403:
                    bad.append((role, m, url, s, 'devrait etre 403'))
                if s >= 500:
                    bad.append((role, m, url, s, '5xx'))
        self.assertEqual(bad, [])

    def test_set_manuel_only_direction_up_and_audited(self):
        url = f'/api/commissions/commissions/{self.cm1.pk}/set_manuel/'
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).patch(url, {'manuel_adjustment': '1'}, format='json').status_code,
                             403, role)
        self.assertEqual(cl().patch(url, {'manuel_adjustment': '1'}, format='json').status_code, 401)
        self.cm1.refresh_from_db()
        self.assertIsNone(self.cm1.manuel_adjustment)
        before = ActivityLog.objects.count()
        r = cl(self.u['DIRECTION']).patch(
            url, {'manuel_adjustment': '1234.50', 'is_paid': True, 'net_payable': '9', 'order_value': '1',
                  'manuel_notes': 'qa'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.cm1.refresh_from_db()
        self.assertEqual(self.cm1.manuel_adjustment, Dc('1234.50'))
        self.assertFalse(self.cm1.is_paid)            # champ force ignore
        self.assertEqual(self.cm1.order_value, Dc('100000'))
        self.assertGreater(ActivityLog.objects.count(), before)

    def test_set_manuel_payload_hostile_never_500_and_no_write(self):
        url = f'/api/commissions/commissions/{self.cm2.pk}/set_manuel/'
        for v in ('abc', 'NaN', 'Infinity', '1e999', [1], {'a': 1}, True, '9' * 30, '-' + '9' * 30):
            c = cl(self.u['DIRECTION'])
            c.raise_request_exception = False
            r = c.patch(url, {'manuel_adjustment': v}, format='json')
            self.assertEqual(r.status_code, 400, (v, r.status_code))
        self.cm2.refresh_from_db()
        self.assertIsNone(self.cm2.manuel_adjustment)
        c = cl(self.u['DIRECTION'])
        c.raise_request_exception = False
        self.assertEqual(c.patch(url, {}, format='json').status_code, 400)

    def _non_object_500s(self, only):
        """Corps JSON non-objet (liste, nombre, chaine) sur les routes d'ecriture : jamais 5xx."""
        inv = self.mk_invoice()
        clo = CashClosure.objects.create(node=self.k1, date=self.today, gerant=self.u['GERANT'], node_origin='P1')
        al = TamperAlert.objects.create(node=self.k1, affected_model='CashbookEntry', description='d')
        routes = [('patch', f'/api/commissions/commissions/{self.cm1.pk}/set_manuel/', 'DIRECTION'),
                  ('post', f'/api/commissions/commissions/{self.cm1.pk}/mark_paid/', 'DIRECTION'),
                  ('post', '/api/commissions/periods/generate/', 'DIRECTION'),
                  ('post', f'/api/commissions/periods/{self.per1.pk}/close_period/', 'DIRECTION'),
                  ('post', f'/api/sales/invoices/{inv.pk}/adjust/', 'GERANT'),
                  ('post', f'/api/sales/invoices/{inv.pk}/cancel/', 'GERANT'),
                  ('post', f'/api/treasury/closures/{clo.pk}/validate/', 'COMPTABLE'),
                  ('post', f'/api/treasury/closures/{clo.pk}/reject/', 'COMPTABLE'),
                  ('post', f'/api/treasury/closures/{clo.pk}/push_to_cashbook/', 'COMPTABLE'),
                  ('patch', f'/api/treasury/closures/{clo.pk}/', 'GERANT'),
                  ('post', '/api/treasury/closures/', 'GERANT'),
                  ('post', f'/api/blockchain/alerts/{al.pk}/resolve/', 'COMPTABLE'),
                  ('post', '/api/blockchain/snapshots/run_check/', 'DIRECTION'),
                  ('post', '/api/clients/clients/bulk_delete/', 'DIRECTION'),
                  ('post', '/api/clients/clients/bulk_move/', 'DIRECTION'),
                  ('patch', f'/api/clients/clients/{self.c1.pk}/', 'GERANT'),
                  ('post', '/api/sync/push/', None)]
        five = []
        for m, url, role in routes:
            if (only is True) != any(url.endswith(x) for x in BUG762_SUFFIXES):
                continue
            for body in ([], 5, 'x', None):
                c = self.node_client(self.raw1) if role is None else cl(self.u[role])
                c.raise_request_exception = False
                try:
                    s = getattr(c, m)(url, body, format='json').status_code
                except Exception as exc:  # noqa
                    s = f'EXC {type(exc).__name__}'
                if s == 500 or isinstance(s, str):
                    five.append((m, __import__('re').sub(r'[0-9a-f]{8}-[0-9a-f-]{27}', '<id>', url.split('/api/')[1]), repr(body), s))
        return five

    def test_non_object_json_bodies_other_write_routes_are_not_500(self):
        self.maxDiff = None
        self.assertEqual(self._non_object_500s(only=False), [])

    def test_BUG_762_non_object_json_body_is_400_not_500(self):
        self.assertEqual(self._non_object_500s(only=True), [])

    def test_set_manuel_refused_on_paid_or_closed(self):
        url = f'/api/commissions/commissions/{self.cm1.pk}/set_manuel/'
        ClientCommission.objects.filter(pk=self.cm1.pk).update(is_paid=True)
        r = cl(self.u['ADMIN']).patch(url, {'manuel_adjustment': '5'}, format='json')
        self.assertEqual(r.status_code, 400)
        ClientCommission.objects.filter(pk=self.cm1.pk).update(is_paid=False)
        CommissionPeriod.objects.filter(pk=self.per1.pk).update(is_closed=True)
        r = cl(self.u['ADMIN']).patch(url, {'manuel_adjustment': '5'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.cm1.refresh_from_db()
        self.assertIsNone(self.cm1.manuel_adjustment)

    def test_mark_paid_roles_and_cross_node(self):
        url = f'/api/commissions/commissions/{self.cm2.pk}/mark_paid/'
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).post(url, {}, format='json').status_code, 403, role)
        for who in (self.u2['GERANT'], self.u2['FACTURIER']):
            self.assertEqual(cl(who).post(url, {}, format='json').status_code, 403)
        self.cm2.refresh_from_db()
        self.assertFalse(self.cm2.is_paid)

    def test_gerant_isolation_list_detail_summary_filters(self):
        g = cl(self.u['GERANT'])
        ids = {x['id'] for x in b2.results(g.get('/api/commissions/commissions/'))}
        self.assertIn(str(self.cm1.pk), ids)
        self.assertNotIn(str(self.cm2.pk), ids)
        self.assertEqual(g.get(f'/api/commissions/commissions/{self.cm2.pk}/').status_code, 404)
        pids = {x['id'] for x in b2.results(g.get('/api/commissions/periods/'))}
        self.assertEqual(pids, {str(self.per1.pk)})
        self.assertEqual(g.get(f'/api/commissions/periods/{self.per2.pk}/').status_code, 404)
        # filtres forces vers K2
        for q in ({'period__node': self.k2.pk}, {'period': str(self.per2.pk)}, {'client': str(self.c2.pk)}):
            r = g.get('/api/commissions/commissions/', q)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(b2.results(r), [], q)
        # summary : totaux K1 uniquement
        s = g.get('/api/commissions/commissions/summary/').json()
        self.assertEqual(s['count'], 1)
        self.assertEqual(Dc(s['total_orders']), Dc('100000'))
        s2 = g.get('/api/commissions/commissions/summary/', {'period__node': self.k2.pk}).json()
        self.assertEqual(s2['count'], 0)
        # HQ voit les deux
        s3 = cl(self.u['DIRECTION']).get('/api/commissions/commissions/summary/').json()
        self.assertEqual(s3['count'], 2)

    def test_gerant_k2_cannot_write_k1_commission_nor_period(self):
        g2 = cl(self.u2['GERANT'])
        for m, url in (('patch', f'/api/commissions/commissions/{self.cm1.pk}/'),
                       ('delete', f'/api/commissions/commissions/{self.cm1.pk}/'),
                       ('patch', f'/api/commissions/periods/{self.per1.pk}/'),
                       ('post', f'/api/commissions/periods/{self.per1.pk}/close_period/')):
            self.assertEqual(getattr(g2, m)(url, {'order_value': '1'}, format='json').status_code, 403, (m, url))
        self.cm1.refresh_from_db()
        self.assertEqual(self.cm1.order_value, Dc('100000'))
        self.assertTrue(CommissionPeriod.objects.filter(pk=self.per1.pk, is_closed=False).exists())

    def test_generate_roles_and_hostile_params(self):
        url = '/api/commissions/periods/generate/'
        body = {'node': self.k1.pk, 'month': 9, 'year': 2026}
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).post(url, body, format='json').status_code, 403, role)
        self.assertFalse(CommissionPeriod.objects.filter(node=self.k1, month=9, year=2026).exists())
        self.assertEqual(cl().post(url, body, format='json').status_code, 401)
        for bad in ({'node': 'zz', 'month': 9, 'year': 2026}, {'node': NIL, 'month': 9, 'year': 2026},
                    {'node': True, 'month': 9, 'year': 2026}, {'node': 1.5, 'month': 9, 'year': 2026},
                    {'node': self.k1.pk, 'month': 13, 'year': 2026}, {'node': self.k1.pk, 'month': [1], 'year': 2026},
                    {'node': self.k1.pk, 'month': 9, 'year': 'x'}, {'node': self.k1.pk, 'month': 9, 'year': 99999},
                    {'node': {'a': 1}, 'month': 9, 'year': 2026}):
            c = cl(self.u['COMPTABLE'])
            c.raise_request_exception = False
            self.assertLess(c.post(url, bad, format='json').status_code, 500, bad)
        r = cl(self.u['COMPTABLE']).post(url, body, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)

    def test_payroll_listing_roles_and_hostile_period(self):
        url = '/api/commissions/commissions/payroll_listing/'
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).get(url, {'period': str(self.per1.pk)}).status_code, 403, role)
        self.assertEqual(cl().get(url, {'period': str(self.per1.pk)}).status_code, 401)
        for p in ('abc', NIL, '1', "' OR 1=1", '', str(self.per2.pk)):
            c = cl(self.u['COMPTABLE'])
            c.raise_request_exception = False
            self.assertLess(c.get(url, {'period': p}).status_code, 500, p)
        r = cl(self.u['COMPTABLE']).get(url, {'period': str(self.per2.pk)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)

    def test_comptable_commission_write_state_documented_a_clarifier(self):
        """Etat constate (decision : ecriture commissions COMPTABLE = A CLARIFIER) : PATCH recalcule le
        net via les champs de base ; set_manuel / mark_paid restent interdits ; manuel_adjustment non forgeable."""
        c = cl(self.u['COMPTABLE'])
        r = c.patch(f'/api/commissions/commissions/{self.cm1.pk}/',
                    {'order_value': '120000', 'manuel_adjustment': '777', 'is_paid': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.cm1.refresh_from_db()
        self.assertEqual(self.cm1.order_value, Dc('120000'))
        self.assertIsNone(self.cm1.manuel_adjustment)
        self.assertFalse(self.cm1.is_paid)

    def test_hq_post_commission_cannot_forge_paid_or_net(self):
        r = cl(self.u['DIRECTION']).post('/api/commissions/commissions/', {
            'period': str(self.per1.pk), 'client': str(self.c1.pk), 'order_value': '5000',
            'is_paid': True, 'paid_by': 'x', 'net_payable': '999999', 'manuel_adjustment': '1'}, format='json')
        self.assertIn(r.status_code, (201, 400), r.content)
        if r.status_code == 201:
            d = ClientCommission.objects.get(pk=r.json()['id'])
            self.assertFalse(d.is_paid)
            self.assertNotEqual(d.net_payable, Dc('999999'))
            self.assertIsNone(d.manuel_adjustment)

    def test_comptable_stock_movements_read_only(self):
        c = cl(self.u['COMPTABLE'])
        self.assertEqual(c.get('/api/production/movements/').status_code, 200)
        r = c.post('/api/production/movements/', {'stock': str(self.st1.pk), 'movement_type': 'ENTRY',
                                                  'quantity': '3', 'unit_price': '10'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.st1.refresh_from_db()
        self.assertEqual(self.st1.quantity, Dc('0'))


# ---------------------------------------------------------------------------
# 3. Sync : jetons de noeud
# ---------------------------------------------------------------------------
class SyncAuth(B4):
    def test_matrix_anon_jwt_and_bad_tokens(self):
        routes = (('get', '/api/sync/pull/'), ('post', '/api/sync/push/'), ('get', '/api/sync/status/'),
                  ('post', '/api/sync/handshake/'))
        for m, url in routes:
            body = {'batch_id': str(uuid.uuid4()), 'records': {}}
            def call(c):
                c.raise_request_exception = False
                return getattr(c, m)(url, body, format='json') if m == 'post' else getattr(c, m)(url)
            self.assertEqual(call(cl()).status_code, 401, (m, url))
            for role in ROLES:  # un JWT humain, meme ADMIN, ne passe pas
                self.assertIn(call(cl(self.u[role])).status_code, DENIED, (role, m, url))
            bad = APIClient()
            bad.credentials(HTTP_AUTHORIZATION='Bearer ' + 'x' * 64)
            self.assertEqual(call(bad).status_code, 401)
            weird = APIClient()
            weird.credentials(HTTP_AUTHORIZATION='Bearer ')
            self.assertEqual(call(weird).status_code, 401)
            ok = call(self.node_client(self.raw1))
            self.assertEqual(ok.status_code, 200, (m, url, ok.content))

    def test_revoked_token_refused_and_reissue_revokes_old(self):
        NodeAuthToken.objects.filter(node=self.k1).update(revoked_at=timezone.now())
        self.assertEqual(self.node_client(self.raw1).get('/api/sync/status/').status_code, 401)
        self.assertEqual(self.node_client(self.raw2).get('/api/sync/status/').status_code, 200)

    def test_BUG_761_reissue_token_for_node_rotates(self):
        _, new = NodeAuthToken.issue_for_node(self.k1)
        self.assertEqual(self.node_client(self.raw1).get('/api/sync/status/').status_code, 401)
        self.assertEqual(self.node_client(new).get('/api/sync/status/').status_code, 200)

    def test_node_token_not_valid_on_user_routes(self):
        c = self.node_client(self.raw1)
        for url in ('/api/clients/clients/', '/api/sales/invoices/', '/api/treasury/closures/',
                    '/api/core/auth/me/', '/api/commissions/commissions/', '/api/sync/conflicts/'):
            self.assertEqual(c.get(url).status_code, 401, url)

    def test_conflicts_route_hq_only(self):
        for role in ROLES:
            s = cl(self.u[role]).get('/api/sync/conflicts/').status_code
            self.assertEqual(s == 200, role in HQ, (role, s))
        self.assertEqual(cl().get('/api/sync/conflicts/').status_code, 401)
        self.assertIn(self.node_client(self.raw1).get('/api/sync/conflicts/').status_code, DENIED)

    def test_local_status_roles(self):
        for role in ROLES:
            c = cl(self.u[role])
            c.raise_request_exception = False
            self.assertLess(c.get('/api/sync/local-status/').status_code, 500, role)
        self.assertEqual(cl().get('/api/sync/local-status/').status_code, 401)


class SyncPull(B4):
    # BUG-998/999 : un poste de boulangerie recoit les clients ACTIFS de toutes les boulangeries
    # (CLAUDE.md 5.1) ; seules les colonnes client descendent, jamais factures/mouvements/commissions/
    # jetons d'un autre noeud, et jamais un client INACTIF d'un autre noeud au pull initial.
    CLIENT_KEYS = {'id', 'code', 'current_debt', 'credit_limit', 'category', 'first_name', 'last_name',
                   'phone', 'address', 'updated_at', 'node', 'node_origin', 'commission_rate',
                   'cotisation_sociale', 'client_type', 'notes', 'total_breads_received', 'is_active'}

    def _inactive_foreign(self):
        d2 = Client.objects.create(node=self.k2, node_origin='P2', first_name='Zed', last_name='Inactif',
                                   is_active=False)
        return d2

    def test_pull_only_own_clients_and_tokens_scoped(self):
        d2 = self._inactive_foreign()
        self.mk_invoice(self.k2, self.c2)
        r = self.node_client(self.raw1).get('/api/sync/pull/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        ids = {c['id'] for c in body['clients']}
        self.assertIn(str(self.c1.pk), ids)
        self.assertIn(str(self.c2.pk), ids)          # BUG-998 : client actif d'une autre boulangerie
        self.assertNotIn(str(d2.pk), ids)            # inactif d'un autre noeud : jamais au pull initial
        # aucune donnee d'un autre noeud hors colonnes client : ni factures, mouvements, commissions, jetons
        for key in body:
            self.assertFalse(any(w in key.lower() for w in ('invoice', 'debt_mov', 'commission_p', 'token')), key)
        for c in body['clients']:
            self.assertLessEqual(set(c), self.CLIENT_KEYS)
        r2 = self.node_client(self.raw2).get('/api/sync/pull/').json()
        ids2 = {c['id'] for c in r2['clients']}
        self.assertIn(str(self.c2.pk), ids2)
        self.assertIn(str(self.c1.pk), ids2)
        self.assertEqual(r2['node_code'], 'P2')

    def test_client_billed_by_node_comes_down_by_design(self):
        self.mk_invoice(self.k1, self.c2)   # K1 facture un client K2 (regle remarque.md)
        ids = {c['id'] for c in self.node_client(self.raw1).get('/api/sync/pull/').json()['clients']}
        self.assertIn(str(self.c2.pk), ids)

    def test_pull_payload_has_no_secrets_nor_foreign_identity(self):
        txt = self.node_client(self.raw1).get('/api/sync/pull/').content.decode()
        # jamais de secret ; l'identite des clients d'autres boulangeries descend par conception
        # (BUG-998) mais jamais celle du personnel (comptes utilisateurs) d'un autre noeud.
        needles = ['password', 'token_hash', 'SECRET', 'is_superuser']
        needles += [u.username for u in self.u2.values()]
        for needle in needles:
            self.assertNotIn(needle, txt, needle)

    def test_cursor_hostile_values_never_500_and_no_widening(self):
        c = self.node_client(self.raw1)
        c.raise_request_exception = False
        for v in ('abc', 'x' * 100, '2026-13-45', '0000-00-00T00:00:00', '10000-01-01T00:00:00Z', '-1',
                  '2026-11-22T25:00:00', "' OR 1=1 --", '%00', '9999-12-31T23:59:59Z', '0001-01-01T00:00:00Z',
                  '2026-11-22T00:00:00+99:00'):
            for p in ('since_config', 'since_client_debt'):
                s = c.get('/api/sync/pull/', {p: v}).status_code
                self.assertIn(s, (200, 400), (p, v, s))
        # curseur futur = pull complet (BUG-785), toujours borne au perimetre du noeud (BUG-998 : actifs
        # de toutes les boulangeries, jamais un inactif d'un autre noeud)
        d2 = self._inactive_foreign()
        far = c.get('/api/sync/pull/', {'since_client_debt': '9999-12-31T23:59:59Z'})
        self.assertEqual(far.status_code, 200)
        far_ids = {x['id'] for x in far.json()['clients']}
        self.assertNotIn(str(d2.pk), far_ids)
        base_ids = {x['id'] for x in c.get('/api/sync/pull/').json()['clients']}
        self.assertEqual(far_ids, base_ids)
        # parametres repetes
        self.assertIn(c.get('/api/sync/pull/?since_config=a&since_config=b').status_code, (200, 400))
        # un `node=K2` force n'elargit rien
        ids = {x['id'] for x in c.get('/api/sync/pull/', {'node': self.k2.pk}).json()['clients']}
        self.assertEqual(ids, base_ids)
        self.assertNotIn(str(d2.pk), ids)

    def test_pull_is_get_only(self):
        c = self.node_client(self.raw1)
        for m in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(c, m)('/api/sync/pull/', {}, format='json').status_code, 405, m)


class SyncPush(B4):
    def push(self, raw, records, batch=None):
        c = self.node_client(raw)
        c.raise_request_exception = False
        return c.post('/api/sync/push/', {'batch_id': batch or str(uuid.uuid4()), 'records': records}, format='json')

    def res(self, r, label):
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['results'][label][0]

    def test_cannot_write_in_other_node_name(self):
        cid = str(uuid.uuid4())
        for extra in ({'node': 'P2'}, {'node_origin': 'P2'}, {'node': 'P2', 'node_origin': 'P2'}, {'node': ['P2']}):
            rec = {'id': cid, 'first_name': 'Forge', 'last_name': 'Z', **extra}
            out = self.res(self.push(self.raw1, {'clients.Client': [rec]}), 'clients.Client')
            self.assertEqual(out['status'], 'REJECTED', extra)
        self.assertFalse(Client.objects.filter(pk=cid).exists())

    def test_own_record_accepted_then_cannot_be_modified_by_other_node(self):
        cid = str(uuid.uuid4())
        out = self.res(self.push(self.raw1, {'clients.Client': [
            {'id': cid, 'first_name': 'Mien', 'last_name': 'K1', 'node': 'P1', 'node_origin': 'P1'}]}),
            'clients.Client')
        self.assertEqual(out['status'], 'ACCEPTED')
        out = self.res(self.push(self.raw2, {'clients.Client': [
            {'id': cid, 'first_name': 'Vol', 'last_name': 'K2', 'credit_limit': '9999999'}]}), 'clients.Client')
        self.assertEqual(out['status'], 'REJECTED')
        cc = Client.objects.get(pk=cid)
        self.assertEqual(cc.first_name, 'Mien')
        self.assertEqual(cc.node_id, self.k1.pk)

    def test_cannot_overwrite_existing_foreign_client_or_invoice(self):
        out = self.res(self.push(self.raw1, {'clients.Client': [
            {'id': str(self.c2.pk), 'first_name': 'Hack', 'credit_limit': '99999999'}]}), 'clients.Client')
        self.c2.refresh_from_db()
        self.assertEqual(self.c2.first_name, 'Bob')
        self.assertEqual(self.c2.credit_limit, Dc('50000'))
        inv = self.mk_invoice(self.k2, self.c2, status=Invoice.Status.PENDING)
        out = self.res(self.push(self.raw1, {'sales.Invoice': [
            {'id': str(inv.pk), 'status': 'DELIVERED', 'payment_amount': '1'}]}), 'sales.Invoice')
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PENDING)
        self.assertEqual(out['status'], 'REJECTED')

    def test_foreign_closure_and_cashbook_refused(self):
        cid = str(uuid.uuid4())
        rec = {'id': cid, 'node': 'P2', 'date': str(self.today), 'total_entries': '1000', 'total_expenses': '0',
               'is_validated': True, 'node_origin': 'P2'}
        out = self.res(self.push(self.raw1, {'treasury.CashClosure': [rec]}), 'treasury.CashClosure')
        self.assertEqual(out['status'], 'REJECTED')
        # meme sans `node` : id d'une cloture de K2 existante
        cl2 = CashClosure.objects.create(node=self.k2, date=self.today, gerant=self.u2['GERANT'], node_origin='P2')
        out = self.res(self.push(self.raw1, {'treasury.CashClosure': [
            {'id': str(cl2.pk), 'date': str(self.today), 'is_validated': True}]}), 'treasury.CashClosure')
        self.assertEqual(out['status'], 'REJECTED')
        cl2.refresh_from_db()
        self.assertFalse(cl2.is_validated)
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_unknown_model_and_hostile_bodies_never_500(self):
        c = self.node_client(self.raw1)
        c.raise_request_exception = False
        for body in ([], 5, 'x', {'batch_id': 5}, {'batch_id': 'zz'}, {'batch_id': str(uuid.uuid4()), 'records': []},
                     {'batch_id': str(uuid.uuid4()), 'records': {'core.User': [{'id': 1, 'role': 'ADMIN'}]}},
                     {'batch_id': str(uuid.uuid4()), 'records': {'clients.Client': 'x'}},
                     {'batch_id': str(uuid.uuid4()), 'records': {'clients.Client': [None, 5, 'a', [], {}]}}):
            r = c.post('/api/sync/push/', body, format='json')
            self.assertLess(r.status_code, 500, body)
        self.assertFalse(self.u['GERANT'].__class__.objects.filter(role='ADMIN', username='pr_gerant').exists())

    def test_batch_id_not_shared_across_nodes_and_replay_conflict(self):
        b = str(uuid.uuid4())
        r1 = self.push(self.raw1, {'clients.Client': []}, batch=b)
        self.assertEqual(r1.status_code, 200)
        r2 = self.push(self.raw2, {'clients.Client': [{'id': str(uuid.uuid4()), 'first_name': 'N'}]}, batch=b)
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()['replayed'])   # le lot de K1 n'est pas visible de K2
        r3 = self.push(self.raw1, {'clients.Client': [{'id': str(uuid.uuid4()), 'first_name': 'M'}]}, batch=b)
        self.assertEqual(r3.status_code, 409)

    def test_push_closure_self_validated_state(self):
        """Constat (pas de ticket, voir rapport) : un jeton de noeud qui pousse SA cloture avec
        is_validated=True la fait inscrire au livre de caisse sans confirmation comptable cote cloud."""
        cid = str(uuid.uuid4())
        rec = {'id': cid, 'node': 'P1', 'date': str(self.today), 'total_entries': '1000', 'total_expenses': '0',
               'is_validated': True, 'node_origin': 'P1'}
        out = self.res(self.push(self.raw1, {'treasury.CashClosure': [rec]}), 'treasury.CashClosure')
        self.assertIn(out['status'], ('ACCEPTED', 'REJECTED'))
        self.assertLess(CashbookEntry.objects.exclude(node=self.k1).count() + 0, 1)  # jamais au nom de K2


# ---------------------------------------------------------------------------
# 4. Tresorerie : resoumission de cloture
# ---------------------------------------------------------------------------
class ClosureResubmission(B4):
    def setUp(self):
        super().setUp()
        self.clo = CashClosure.objects.create(node=self.k1, date=self.today, gerant=self.u['GERANT'],
                                              node_origin='P1', is_rejected=True, rejection_reason='recompter')
        self.url = f'/api/treasury/closures/{self.clo.pk}/'

    def test_role_matrix_on_patch(self):
        body = {'bills_5000': 1}
        self.assertEqual(cl().patch(self.url, body, format='json').status_code, 401)
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).patch(self.url, body, format='json').status_code, 403, role)
        self.assertEqual(cl(self.u2['GERANT']).patch(self.url, body, format='json').status_code, 404)
        for who in (self.u2['FACTURIER'], self.u2['LIVREUR']):
            self.assertEqual(cl(who).patch(self.url, body, format='json').status_code, 403)
        self.clo.refresh_from_db()
        self.assertEqual(self.clo.bills_5000, 0)
        self.assertTrue(self.clo.is_rejected)

    def test_gerant_resubmit_forged_fields_ignored(self):
        before = ActivityLog.objects.count()
        r = cl(self.u['GERANT']).patch(self.url, {
            'bills_5000': 2, 'is_validated': True, 'is_rejected': True, 'node': self.k2.pk,
            'cash_gap': '0', 'net_cash': '999999999', 'total_entries': '999999', 'gerant': self.u['ADMIN'].pk,
            'physical_cash_total': '1', 'node_origin': 'P2'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.clo.refresh_from_db()
        self.assertFalse(self.clo.is_validated)
        self.assertFalse(self.clo.is_rejected)           # resoumission efface l'infirmation
        self.assertEqual(self.clo.node_id, self.k1.pk)
        self.assertEqual(self.clo.gerant_id, self.u['GERANT'].pk)
        self.assertEqual(self.clo.node_origin, 'P1')
        self.assertEqual(self.clo.total_entries, Dc('0'))
        self.assertEqual(self.clo.physical_cash_total, Dc('10000'))
        self.assertEqual(self.clo.cash_gap, Dc('10000') - self.clo.net_cash)
        self.assertGreater(ActivityLog.objects.count(), before)   # BUG-860

    def test_put_forged_node_ignored_for_gerant(self):
        r = cl(self.u['GERANT']).put(self.url, {'date': str(self.today), 'node': self.k2.pk, 'bills_100': 1},
                                     format='json')
        self.assertLess(r.status_code, 500)
        self.clo.refresh_from_db()
        self.assertEqual(self.clo.node_id, self.k1.pk)

    def test_confirmed_closure_frozen_for_everyone(self):
        CashClosure.objects.filter(pk=self.clo.pk).update(is_validated=True, is_rejected=False)
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'):
            r = cl(self.u[role]).patch(self.url, {'bills_5000': 9}, format='json')
            self.assertEqual(r.status_code, 400, role)
            self.assertEqual(cl(self.u[role]).delete(self.url).status_code, 403, role)
        self.clo.refresh_from_db()
        self.assertEqual(self.clo.bills_5000, 0)
        self.assertTrue(CashClosure.objects.filter(pk=self.clo.pk).exists())

    def test_gerant_cannot_validate_reject_push(self):
        for act in ('validate', 'reject', 'push_to_cashbook'):
            for who in (self.u['GERANT'], self.u['FACTURIER'], self.u['LIVREUR'], self.u2['GERANT']):
                self.assertEqual(cl(who).post(f'{self.url}{act}/', {'reason': 'x'}, format='json').status_code,
                                 403, (act, who.username))
            self.assertEqual(cl().post(f'{self.url}{act}/', {}, format='json').status_code, 401)
        self.clo.refresh_from_db()
        self.assertFalse(self.clo.is_validated)
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_hostile_bills_never_500(self):
        for v in (-1, 'abc', 1e30, [1], None, 2 ** 70, '1e5'):
            c = cl(self.u['GERANT'])
            c.raise_request_exception = False
            self.assertLess(c.patch(self.url, {'bills_50': v}, format='json').status_code, 500, v)
        for d in ('2999-01-01', 'x', '0001-01-01', None):
            c = cl(self.u['GERANT'])
            c.raise_request_exception = False
            self.assertLess(c.patch(self.url, {'date': d}, format='json').status_code, 500, d)

    def test_list_isolation(self):
        CashClosure.objects.create(node=self.k2, date=self.today, gerant=self.u2['GERANT'], node_origin='P2')
        ids = {x['id'] for x in b2.results(cl(self.u['GERANT']).get('/api/treasury/closures/'))}
        self.assertEqual(ids, {str(self.clo.pk)})
        self.assertEqual(len(b2.results(cl(self.u['GERANT']).get('/api/treasury/closures/', {'node': self.k2.pk}))), 0)


# ---------------------------------------------------------------------------
# 5. Blockchain : integrity_check, run_check, is_tampered, alertes
# ---------------------------------------------------------------------------
class BlockchainPerms(B4):
    def entry(self, node, piece, amount='100'):
        from treasury.views import append_cashbook_entry
        return append_cashbook_entry(node=node, date=self.today, piece_number=piece, label='x',
                                     entry_amount=Dc(amount), exit_amount=Dc('0'))

    def test_matrix(self):
        al = TamperAlert.objects.create(node=self.k2, affected_model='CashbookEntry', description='d')
        routes = [('get', '/api/treasury/cashbook/integrity_check/', None),
                  ('get', '/api/treasury/cashbook/', None),
                  ('get', '/api/blockchain/alerts/', None), ('get', f'/api/blockchain/alerts/{al.pk}/', None),
                  ('post', f'/api/blockchain/alerts/{al.pk}/resolve/', {}),
                  ('get', '/api/blockchain/snapshots/', None),
                  ('post', '/api/blockchain/snapshots/run_check/', {}),
                  ('get', '/api/blockchain/snapshots/global_status/', None)]
        for m, url, body in routes:
            def call(who):
                c = cl(who)
                c.raise_request_exception = False
                return getattr(c, m)(url, body, format='json') if body is not None else getattr(c, m)(url)
            self.assertEqual(call(None).status_code, 401, url)
            for role in ROLES:
                s = call(self.u[role]).status_code
                if role in HQ:
                    # `resolve` : 200 la 1re fois, 400 « deja resolue » ensuite (pas un refus de droit)
                    self.assertTrue(s < 400 or (url.endswith('/resolve/') and s == 400), (role, url, s))
                else:
                    self.assertEqual(s, 403, (role, url))
            for who in (self.u2['GERANT'], self.u2['FACTURIER']):
                self.assertEqual(call(who).status_code, 403, (who.username, url))

    def test_alerts_are_read_only_for_everyone(self):
        al = TamperAlert.objects.create(node=self.k1, affected_model='CashbookEntry', description='d')
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            c = cl(self.u[role])
            self.assertEqual(c.post('/api/blockchain/alerts/', {'node': self.k1.pk, 'description': 'f'},
                                    format='json').status_code, 405)
            for m in ('put', 'patch'):
                self.assertEqual(getattr(c, m)(f'/api/blockchain/alerts/{al.pk}/',
                                               {'is_resolved': True, 'description': 'effacee'}, format='json').status_code, 405)
            self.assertEqual(c.delete(f'/api/blockchain/alerts/{al.pk}/').status_code, 405)
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for m in ('post', 'put', 'patch', 'delete'):
                url = '/api/blockchain/alerts/' if m == 'post' else f'/api/blockchain/alerts/{al.pk}/'
                self.assertEqual(getattr(c, m)(url, {}, format='json').status_code, 403, (role, m))
        al.refresh_from_db()
        self.assertFalse(al.is_resolved)
        self.assertEqual(al.description, 'd')

    def test_cashbook_read_only_and_is_tampered_not_forgeable(self):
        e = self.entry(self.k1, 'B4-1')
        for role in ROLES:
            c = cl(self.u[role])
            for m in ('post', 'put', 'patch', 'delete'):
                url = '/api/treasury/cashbook/' if m == 'post' else f'/api/treasury/cashbook/{e.pk}/'
                s = getattr(c, m)(url, {'is_tampered': True, 'entry_amount': '1'}, format='json').status_code
                self.assertIn(s, (403, 405), (role, m, s))
        e.refresh_from_db()
        self.assertFalse(e.is_tampered)
        self.assertEqual(e.entry_amount, Dc('100'))

    def test_integrity_check_flags_and_repairs_and_is_idempotent(self):
        e = self.entry(self.k1, 'B4-2')
        self.entry(self.k2, 'B4-3', '50')
        h = cl(self.u['COMPTABLE'])
        r = h.get('/api/treasury/cashbook/integrity_check/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['chain_valid'], r.json())
        CashbookEntry.objects.filter(pk=e.pk).update(entry_amount=Dc('9999'))   # falsification directe en base
        r = h.get('/api/treasury/cashbook/integrity_check/').json()
        self.assertFalse(r['chain_valid'])
        self.assertIn(str(e.pk), r['tampered_ids'])
        from core.models import SystemNotification
        n1 = SystemNotification.objects.count()
        h.get('/api/treasury/cashbook/integrity_check/')
        self.assertEqual(SystemNotification.objects.count(), n1)          # BUG-842 : pas de doublon
        e.refresh_from_db()
        self.assertTrue(e.is_tampered)
        CashbookEntry.objects.filter(pk=e.pk).update(entry_amount=Dc('100'))     # restauration
        r = h.get('/api/treasury/cashbook/integrity_check/').json()
        self.assertTrue(r['chain_valid'], r)
        e.refresh_from_db()
        self.assertFalse(e.is_tampered)                                    # BUG-861

    def test_run_check_hostile_node_param_and_body(self):
        d = cl(self.u['DIRECTION'])
        d.raise_request_exception = False
        for body in ({'node': 'zz'}, {'node': NIL}, {'node': True}, {'node': 1.5}, {'node': [1]}, {'node': {'a': 1}},
                     [], 5, 'x', {'node': self.k1.code}, {'node': 99999999999999999999}):
            self.assertLess(d.post('/api/blockchain/snapshots/run_check/', body, format='json').status_code, 500, body)
        for q in ('zz', "' or 1=1", '-1', '1.5'):
            self.assertLess(d.post(f'/api/blockchain/snapshots/run_check/?node={q}', {}, format='json').status_code,
                            500, q)
            self.assertLess(d.get('/api/blockchain/alerts/', {'node': q}).status_code, 500, q)
            self.assertLess(d.get('/api/blockchain/snapshots/', {'node': q}).status_code, 500, q)

    def test_run_check_flags_tampered_only_for_its_node_and_is_audited(self):
        e1 = self.entry(self.k1, 'B4-4')
        self.entry(self.k2, 'B4-5')
        CashbookEntry.objects.filter(pk=e1.pk).update(entry_amount=Dc('1'))
        before = ActivityLog.objects.count()
        r = cl(self.u['DIRECTION']).post('/api/blockchain/snapshots/run_check/', {'node': self.k2.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        # chaine globale : apres une falsification, les blocs suivants sont aussi signales (documente dans
        # verify_cashbook_chain) ; l'ecriture de K1 elle-meme n'est jamais imputee a K2 (BUG-836a)
        for a in TamperAlert.objects.filter(node=self.k2):
            self.assertNotIn(str(e1.pk), a.affected_id)
        self.assertFalse(TamperAlert.objects.filter(node=self.k1).exists())
        self.assertGreater(ActivityLog.objects.count(), before)                 # BUG-837

    def test_resolve_audited_and_not_twice(self):
        al = TamperAlert.objects.create(node=self.k1, affected_model='CashbookEntry', description='d')
        url = f'/api/blockchain/alerts/{al.pk}/resolve/'
        before = ActivityLog.objects.count()
        self.assertEqual(cl(self.u['COMPTABLE']).post(url, {}, format='json').status_code, 200)
        self.assertGreater(ActivityLog.objects.count(), before)
        self.assertEqual(cl(self.u['DIRECTION']).post(url, {}, format='json').status_code, 400)
        al.refresh_from_db()
        self.assertEqual(al.resolved_by_id, self.u['COMPTABLE'].pk)
        c = cl(self.u['DIRECTION'])
        c.raise_request_exception = False
        self.assertLess(c.post(f'/api/blockchain/alerts/{NIL}/resolve/', {}, format='json').status_code, 500)


# ---------------------------------------------------------------------------
# 6. Ventes : adjust
# ---------------------------------------------------------------------------
class SalesAdjust(B4):
    def body(self, **kw):
        d = {'adjustment_sign': -1, 'payment_amount': 0, 'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}
        d.update(kw)
        return d

    def post(self, who, inv, body=None):
        c = cl(who)
        c.raise_request_exception = False
        return c.post(f'/api/sales/invoices/{inv.pk}/adjust/', body or self.body(), format='json')

    def test_matrix(self):
        inv = self.mk_invoice()
        self.assertEqual(self.post(None, inv).status_code, 401)
        for who in (self.u['FACTURIER'], self.u['LIVREUR'], self.u2['FACTURIER'], self.u2['LIVREUR']):
            self.assertEqual(self.post(who, inv).status_code, 403, who.username)
        self.assertEqual(self.post(self.u2['GERANT'], inv).status_code, 404)
        self.assertFalse(Invoice.objects.filter(adjusts=inv).exists())
        for role in ('GERANT', 'COMPTABLE', 'DIRECTION', 'ADMIN'):
            inv = self.mk_invoice()
            r = self.post(self.u[role], inv)
            self.assertEqual(r.status_code, 201 if r.status_code == 201 else 200, (role, r.content))
            self.assertLess(r.status_code, 300, (role, r.content))
            self.assertTrue(Invoice.objects.filter(adjusts=inv).exists(), role)

    def test_forged_fields_ignored(self):
        inv = self.mk_invoice()
        r = self.post(self.u['GERANT'], inv, self.body(node=self.k2.pk, facturier=self.u2['FACTURIER'].pk,
                                                         status='CANCELLED', receipt_number='FORGED',
                                                         node_origin='P2', client=str(self.c2.pk)))
        self.assertLess(r.status_code, 300, r.content)
        adj = Invoice.objects.get(adjusts=inv)
        self.assertEqual(adj.node_id, self.k1.pk)
        self.assertEqual(adj.client_id, self.c1.pk)
        self.assertNotEqual(adj.receipt_number, 'FORGED')

    def test_hostile_payloads_never_500(self):
        inv = self.mk_invoice()
        for kw in ({'adjustment_sign': 0}, {'adjustment_sign': 2}, {'adjustment_sign': 'x'}, {'adjustment_sign': None},
                   {'payment_amount': -5}, {'payment_amount': 'abc'}, {'payment_amount': 10 ** 30},
                   {'lines': []}, {'lines': 'x'}, {'lines': [None]}, {'lines': [{'bread_price': 99999, 'quantity': 1}]},
                   {'lines': [{'bread_price': self.bp.pk, 'quantity': -1}]},
                   {'lines': [{'bread_price': self.bp.pk, 'quantity': 10 ** 12}]},
                   {'lines': [{'bread_price': 'a', 'quantity': 'b'}]},
                   {'lines': [{'bread_price': self.bp.pk, 'quantity': 999}]}):
            s = self.post(self.u['GERANT'], inv, self.body(**kw)).status_code
            self.assertLess(s, 500, kw)
        self.assertEqual(Invoice.objects.filter(adjusts=inv).count(), 0)   # aucun ajustement accepte

    def test_cannot_adjust_cancelled_adjustment_or_unknown(self):
        cancelled = self.mk_invoice(status=Invoice.Status.CANCELLED)
        self.assertEqual(self.post(self.u['GERANT'], cancelled).status_code, 400)
        inv = self.mk_invoice()
        self.assertLess(self.post(self.u['GERANT'], inv).status_code, 300)
        adj = Invoice.objects.get(adjusts=inv)
        self.assertEqual(self.post(self.u['GERANT'], adj).status_code, 400)
        c = cl(self.u['GERANT'])
        c.raise_request_exception = False
        self.assertEqual(c.post(f'/api/sales/invoices/{NIL}/adjust/', self.body(), format='json').status_code, 404)

    def test_list_and_detail_isolation(self):
        i1 = self.mk_invoice(self.k1)
        i2 = self.mk_invoice(self.k2)
        g = cl(self.u['GERANT'])
        ids = {x['id'] for x in b2.results(g.get('/api/sales/invoices/'))}
        self.assertIn(str(i1.pk), ids)
        self.assertNotIn(str(i2.pk), ids)
        self.assertEqual(g.get(f'/api/sales/invoices/{i2.pk}/').status_code, 404)
        for who in (self.u['FACTURIER'], self.u['LIVREUR']):
            self.assertEqual(cl(who).get(f'/api/sales/invoices/{i2.pk}/').status_code, 404)
            self.assertIn(cl(who).post(f'/api/sales/invoices/{i2.pk}/cancel/', {}, format='json').status_code,
                          (403, 404))
