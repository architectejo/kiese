"""Verification des correctifs BUG-701 a 707 + nouvelles routes (testeur-permissions, ronde b3, 2026-11-22).
Donnees fictives. Aucun code applicatif modifie."""
import io
import uuid
from decimal import Decimal as Dc
from unittest import expectedFailure, mock

from django.core.cache import cache
from django.test import Client as DjangoClient, override_settings

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.models import ActivityLog, ColisDistribution, User
from core.tests.test_permissions_regression_2026_11_19 import (
    DIRECTION_UP, GERANT_UP, ROLES, Base, cl, mk)
from production.models import ConsumableMovement, ConsumableStock, ConsumableType

NIL = '00000000-0000-0000-0000-000000000000'
DENIED = (401, 403)


class B3(Base):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()


# --- BUG-704 : throttle /admin/login/ -------------------------------------
class AdminThrottle(B3):
    def _post(self, dc, user, pw='faux', **extra):
        return dc.post('/admin/login/', {'username': user, 'password': pw}, **extra).status_code

    def test_blocks_after_10_failures_per_account(self):
        dc = DjangoClient()
        codes = [self._post(dc, 'cible') for _ in range(12)]
        self.assertEqual(codes[:10], [200] * 10)
        self.assertEqual(codes[10:], [429, 429])

    def test_case_and_space_variants_share_counter(self):
        dc = DjangoClient()
        for i in range(10):
            self._post(dc, ['cible', 'CIBLE', ' Cible ', 'cIbLe\t'][i % 4])
        self.assertEqual(self._post(dc, ' CIBLE'), 429)

    def test_forged_xff_does_not_reset(self):
        dc = DjangoClient()
        for i in range(10):
            self._post(dc, 'cible', HTTP_X_FORWARDED_FOR=f'10.0.0.{i}')
        self.assertEqual(self._post(dc, 'cible', HTTP_X_FORWARDED_FOR='9.9.9.9'), 429)

    def test_ip_cap_30_across_accounts(self):
        dc = DjangoClient()
        codes = [self._post(dc, f'u{i}') for i in range(35)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertIn(429, codes[30:])

    def test_success_resets_and_is_not_counted(self):
        s = User.objects.create(username='stf', role='ADMIN', is_staff=True, is_superuser=True)
        s.set_password('Mdp-test-Qa-2026x')
        s.save()
        dc = DjangoClient()
        for _ in range(9):
            self._post(dc, 'stf')
        self.assertEqual(self._post(dc, 'stf', 'Mdp-test-Qa-2026x'), 302)
        for _ in range(9):
            self.assertEqual(self._post(DjangoClient(), 'stf'), 200)

    def test_blocked_even_with_right_password(self):
        s = User.objects.create(username='stf2', role='ADMIN', is_staff=True, is_superuser=True)
        s.set_password('Mdp-test-Qa-2026x')
        s.save()
        dc = DjangoClient()
        for _ in range(10):
            self._post(dc, 'stf2')
        self.assertEqual(self._post(dc, 'stf2', 'Mdp-test-Qa-2026x'), 429)

    def test_path_variants_and_get_not_blocked(self):
        dc = DjangoClient()
        for _ in range(10):
            self._post(dc, 'cible')
        self.assertEqual(dc.post('/admin/login', {'username': 'cible', 'password': 'x'}).status_code in (301, 429), True)
        self.assertEqual(dc.get('/admin/login/').status_code, 200)

    def test_missing_or_weird_username_no_500(self):
        dc = DjangoClient()
        self.assertLess(dc.post('/admin/login/', {}).status_code, 500)
        self.assertLess(dc.post('/admin/login/', {'username': ['a', 'b'], 'password': 'x'}).status_code, 500)
        self.assertLess(dc.post('/admin/login/', {'username': 'é' * 400, 'password': 'x'}).status_code, 500)

    def test_api_login_still_not_blocked_by_admin_counter(self):
        dc = DjangoClient()
        for _ in range(12):
            self._post(dc, 'cible')
        r = cl().post('/api/core/auth/login/', {'username': 'pr_admin', 'password': 'nope'}, format='json')
        self.assertIn(r.status_code, (400, 401))


# --- BUG-702 / BUG-701 ------------------------------------------------------
class SmallFixes(B3):
    def test_username_non_string_400(self):
        for v in (['a'], 123, {'a': 1}, True):
            r = cl().post('/api/core/auth/login/', {'username': v, 'password': 'x'}, format='json')
            self.assertEqual(r.status_code, 400, v)
            self.assertIn('detail', r.json())
        r = cl().post('/api/core/auth/login/', {'username': None, 'password': 'x'}, format='json')
        self.assertLess(r.status_code, 500)

    def test_colis_without_amounts(self):
        c = cl(self.u['GERANT'])
        r = c.post('/api/core/colis/', {'year': 2026, 'beneficiary_label': 'Z', 'node': str(self.k1.pk)}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(str(r.json()['total_value'])), Dc('0'))
        r = c.post('/api/core/colis/', {'year': 2026, 'beneficiary_label': 'Y', 'node': str(self.k1.pk), 'rice_value': '1000',
                                        'cash_amount': '500.50'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(str(r.json()['total_value'])), Dc('1500.50'))
        r = c.post('/api/core/colis/', {'year': 2026, 'beneficiary_label': 'W', 'node': str(self.k1.pk), 'rice_value': 'abc'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_colis_forged_node_ignored(self):
        r = cl(self.u['GERANT']).post('/api/core/colis/', {'year': 2026, 'beneficiary_label': 'F',
                                                           'node': str(self.k2.pk)}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(ColisDistribution.objects.get(pk=r.json()['id']).node_id, self.k1.pk)


# --- BUG-703 ----------------------------------------------------------------
class ManuelReadOnly(B3):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.per = CommissionPeriod.objects.create(node=cls.k1, month=10, year=2026, node_origin='P1')
        cls.cm = ClientCommission.objects.create(period=cls.per, client=cls.c1, order_value=Dc('100000'),
                                                 node_origin='P1')

    def _reset(self):
        ClientCommission.objects.filter(pk=self.cm.pk).update(manuel_adjustment=None, manuel_notes='')

    def test_patch_put_by_all_roles_ignores_manuel(self):
        for role in ROLES:
            for m in ('patch', 'put'):
                self._reset()
                body = {'manuel_adjustment': '1', 'manuel_notes': 'x'}
                if m == 'put':
                    body.update(period=str(self.per.pk), client=str(self.c1.pk), order_value='100000')
                r = getattr(cl(self.u[role]), m)(f'/api/commissions/commissions/{self.cm.pk}/', body, format='json')
                self.assertLess(r.status_code, 500, (role, m))
                self.cm.refresh_from_db()
                self.assertIsNone(self.cm.manuel_adjustment, (role, m, r.status_code))
                self.assertEqual(self.cm.manuel_notes, '', (role, m))

    def test_post_create_ignores_manuel(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            c2 = Client.objects.create(node=self.k1, node_origin='P1', first_name=f'M{role}', last_name='Z')
            r = cl(self.u[role]).post('/api/commissions/commissions/', {
                'period': str(self.per.pk), 'client': str(c2.pk), 'order_value': '1000',
                'manuel_adjustment': '5', 'manuel_notes': 'x'}, format='json')
            self.assertLess(r.status_code, 500)
            if r.status_code == 201:
                obj = ClientCommission.objects.get(pk=r.json()['id'])
                self.assertIsNone(obj.manuel_adjustment)

    def test_set_manuel_still_works_for_direction_and_is_logged(self):
        self._reset()
        n = ActivityLog.objects.count()
        r = cl(self.u['DIRECTION']).patch(f'/api/commissions/commissions/{self.cm.pk}/set_manuel/',
                                          {'manuel_adjustment': '1234', 'manuel_notes': 'n'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.cm.refresh_from_db()
        self.assertEqual(self.cm.manuel_adjustment, Dc('1234.00'))
        self.assertEqual(self.cm.net_payable, Dc('1234.00'))
        self.assertGreater(ActivityLog.objects.count(), n)
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).patch(f'/api/commissions/commissions/{self.cm.pk}/set_manuel/',
                                       {'manuel_adjustment': '1'}, format='json')
            self.assertEqual(r.status_code, 403, role)

    def test_recompute_after_patch_keeps_manuel_when_set(self):
        """Un PATCH legitime (order_value) par le COMPTABLE ne doit pas effacer ni forger l'ajustement."""
        self._reset()
        cl(self.u['DIRECTION']).patch(f'/api/commissions/commissions/{self.cm.pk}/set_manuel/',
                                      {'manuel_adjustment': '777'}, format='json')
        cl(self.u['COMPTABLE']).patch(f'/api/commissions/commissions/{self.cm.pk}/',
                                      {'deduction_other': '10'}, format='json')
        self.cm.refresh_from_db()
        self.assertEqual(self.cm.manuel_adjustment, Dc('777.00'))


# --- BUG-706 / 707 ----------------------------------------------------------
class Movements(B3):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ConsumableType.objects.get_or_create(code='FAR', defaults={'label': 'FAR', 'unit': 'sac', 'is_active': True})
        cls.st1 = ConsumableStock.objects.get_or_create(
            node=cls.k1, consumable_type='FAR', defaults={'unit': 'sac', 'node_origin': 'P1'})[0]
        cls.st2 = ConsumableStock.objects.get_or_create(
            node=cls.k2, consumable_type='FAR', defaults={'unit': 'sac', 'node_origin': 'P2'})[0]

    def _mv(self, node, stock):
        return ConsumableMovement.objects.create(
            node=node, stock=stock, movement_type='ENTRY', quantity=Dc('1'))

    def test_comptable_read_only_others_ok(self):
        m = self._mv(self.k1, self.st1)
        url = f'/api/production/movements/{m.pk}/'
        for role in ROLES:
            c = cl(self.u[role])
            g = c.get('/api/production/movements/').status_code
            p = c.patch(url, {'comment': 'x'}, format='json').status_code
            po = c.post('/api/production/movements/', {}, format='json').status_code
            if role in ('FACTURIER', 'LIVREUR'):
                self.assertEqual((g, p, po), (403, 403, 403), role)
            elif role == 'COMPTABLE':
                self.assertEqual(g, 200)
                self.assertEqual((p, po), (403, 403))
            else:
                self.assertEqual(g, 200, role)
                self.assertNotIn(p, DENIED + (500,), role)
                self.assertNotIn(po, DENIED + (500,), role)
        r = cl(self.u['COMPTABLE']).delete(url)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(ConsumableMovement.objects.filter(pk=m.pk).exists())
        self.assertEqual(cl().get('/api/production/movements/').status_code, 401)

    def test_comptable_cannot_put(self):
        m = self._mv(self.k1, self.st1)
        r = cl(self.u['COMPTABLE']).put(f'/api/production/movements/{m.pk}/', {}, format='json')
        self.assertIn(r.status_code, (403, 405))

    def test_delete_logged_and_isolated(self):
        m = self._mv(self.k1, self.st1)
        n = ActivityLog.objects.count()
        r = cl(self.u['GERANT']).delete(f'/api/production/movements/{m.pk}/')
        self.assertIn(r.status_code, (200, 204), r.content)
        self.assertGreater(ActivityLog.objects.count(), n)
        m2 = self._mv(self.k2, self.st2)
        r = cl(self.u['GERANT']).delete(f'/api/production/movements/{m2.pk}/')
        self.assertEqual(r.status_code, 404)
        self.assertTrue(ConsumableMovement.objects.filter(pk=m2.pk).exists())
        # direction peut supprimer n'importe quel noeud et c'est journalise
        n = ActivityLog.objects.count()
        r = cl(self.u['DIRECTION']).delete(f'/api/production/movements/{m2.pk}/')
        self.assertIn(r.status_code, (200, 204))
        self.assertGreater(ActivityLog.objects.count(), n)


# --- Nouvelles routes : clients bulk_*, import_excel -------------------------
class ClientsBulk(B3):
    def test_matrix_roles(self):
        for role in ROLES:
            c = cl(self.u[role])
            for url, body in (('/api/clients/clients/bulk_delete/', {'ids': []}),
                              ('/api/clients/clients/bulk_move/', {'ids': [], 'node': str(self.k2.pk)})):
                s = c.post(url, body, format='json').status_code
                if role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
                    self.assertEqual(s, 400, (role, url))
                else:
                    self.assertEqual(s, 403, (role, url))
            s = c.post('/api/clients/clients/import_excel/', {}, format='multipart').status_code
            self.assertEqual(s, 400 if role in ('ADMIN', 'DIRECTION', 'COMPTABLE') else 403, role)
        for url in ('/api/clients/clients/bulk_delete/', '/api/clients/clients/bulk_move/',
                    '/api/clients/clients/import_excel/'):
            self.assertEqual(cl().post(url, {}, format='json').status_code, 401)

    def test_comptable_bulk_delete_and_move_actually_work(self):
        """Constat : la docstring dit « Direction centrale uniquement » mais IsHeadquarters inclut COMPTABLE."""
        c3 = Client.objects.create(node=self.k1, node_origin='P1', first_name='Del', last_name='Me')
        r = cl(self.u['COMPTABLE']).post('/api/clients/clients/bulk_delete/', {'ids': [str(c3.pk)]}, format='json')
        self.assertEqual(r.status_code, 200)  # constat : coherent avec la hierarchie (COMPTABLE >= GERANT)

    # BUG-760 : corrige (dev-backend d6)
    def test_single_client_delete_with_protected_relation_not_500(self):
        from clients.models import SocialDistribution, SocialDistributionLine
        d = SocialDistribution.objects.get_or_create(node=self.k1, year=2026)[0]
        SocialDistributionLine.objects.get_or_create(distribution=d, client=self.c1)
        c = cl(self.u['GERANT'])
        c.raise_request_exception = False
        r = c.delete(f'/api/clients/clients/{self.c1.pk}/')
        self.assertIn(r.status_code, (400, 409))

    def test_comptable_bulk_move(self):
        c3 = Client.objects.create(node=self.k1, node_origin='P1', first_name='Mov', last_name='Me')
        r = cl(self.u['COMPTABLE']).post('/api/clients/clients/bulk_move/',
                                         {'ids': [str(c3.pk)], 'node': str(self.k2.pk)}, format='json')
        self.assertEqual(r.status_code, 200)  # constat : coherent avec la hierarchie (COMPTABLE >= GERANT)

    def test_import_excel_non_excel_file_no_500(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        for name, data in (('a.xlsx', b'not a zip'), ('b.xlsx', b''), ('c.xlsx', b'PK\x03\x04' + b'\0' * 50)):
            r = cl(self.u['DIRECTION']).post(
                '/api/clients/clients/import_excel/', {'file': SimpleUploadedFile(name, data)}, format='multipart')
            self.assertEqual(r.status_code, 400, name)

    def test_bulk_ids_forged(self):
        for ids in ('abc', [None], [{'a': 1}], [NIL], [str(uuid.uuid4())] * 3, 5, {'a': 1}):
            r = cl(self.u['DIRECTION']).post('/api/clients/clients/bulk_delete/', {'ids': ids}, format='json')
            self.assertLess(r.status_code, 500, ids)
        r = cl(self.u['DIRECTION']).post('/api/clients/clients/bulk_move/',
                                         {'ids': [str(self.c1.pk)], 'node': 'zzz'}, format='json')
        self.assertLess(r.status_code, 500)

    def test_client_writes_by_node_and_facturier(self):
        c = cl(self.u['FACTURIER'])
        for m, body in (('patch', {'credit_limit': '999999'}), ('put', {}), ('delete', None)):
            r = getattr(c, m)(f'/api/clients/clients/{self.c1.pk}/', body, format='json') if body is not None \
                else c.delete(f'/api/clients/clients/{self.c1.pk}/')
            self.assertEqual(r.status_code, 403, m)
        g = cl(self.u['GERANT'])
        for m in ('patch', 'delete'):
            r = getattr(g, m)(f'/api/clients/clients/{self.c2.pk}/', {'first_name': 'X'}, format='json')
            self.assertEqual(r.status_code, 404, m)
        r = g.patch(f'/api/clients/clients/{self.c1.pk}/', {'node': str(self.k2.pk)}, format='json')
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.node_id, self.k1.pk)

    def test_search_fold_no_cross_node_for_gerant_and_no_sql_injection(self):
        g = cl(self.u['GERANT'])
        r = g.get('/api/clients/clients/', {'search': 'BOB'})
        d = r.json()
        rows = d['results'] if isinstance(d, dict) else d
        self.assertEqual(rows, [])
        for term in ("'; DROP TABLE clients_client;--", '%', '_', '\x00', 'é' * 300, '" OR 1=1'):
            r = cl(self.u['FACTURIER']).get('/api/clients/clients/', {'search': term})
            self.assertLess(r.status_code, 500, term)
        self.assertTrue(Client.objects.exists())
        # facturier : exception voulue, voit K2
        r = cl(self.u['FACTURIER']).get('/api/clients/clients/', {'search': 'bob'})
        d = r.json()
        rows = d['results'] if isinstance(d, dict) else d
        self.assertEqual(len(rows), 1)


# --- Consumables global / dispatch ------------------------------------------
class ConsumablesNew(B3):
    def test_dispatch_forged(self):
        for role in ROLES:
            r = cl(self.u[role]).post('/api/production/consumables/dispatch/',
                                      {'node': str(self.k2.pk), 'consumable_type': 'FAR', 'quantity': '-5'},
                                      format='json')
            if role in ('ADMIN', 'DIRECTION'):
                self.assertLess(r.status_code, 500, role)
            else:
                self.assertEqual(r.status_code, 403, role)
        for bad in ({'quantity': 'NaN'}, {'quantity': '1e999'}, {'quantity': [1]}, {'node': 'zz'}, {'node': NIL},
                    {'items': 'x'}, {'items': [None]}):
            r = cl(self.u['DIRECTION']).post('/api/production/consumables/dispatch/', bad, format='json')
            self.assertLess(r.status_code, 500, bad)

    def test_global_hq_only(self):
        for role in ROLES:
            s = cl(self.u[role]).get('/api/production/consumables/global/').status_code
            self.assertEqual(s == 200, role in ('ADMIN', 'DIRECTION', 'COMPTABLE'), role)
        for q in ({'node': 'zz'}, {'node': NIL}, {'date': 'x'}, {'month': '99'}):
            self.assertLess(cl(self.u['DIRECTION']).get('/api/production/consumables/global/', q).status_code, 500, q)


# --- Inventaires : IDs forges / node dans le corps ---------------------------
class Inventories(B3):
    def test_inventory_forced_node_and_node_route(self):
        g = cl(self.u['GERANT'])
        r = g.post('/api/production/inventories/', {'node': str(self.k2.pk), 'inventory_date': '2026-11-21'},
                   format='json')
        self.assertLess(r.status_code, 500)
        if r.status_code == 201:
            self.assertEqual(str(r.json().get('node')), str(self.k1.pk))
        for ref in (self.k2.code, str(self.k2.pk)):
            self.assertIn(g.get(f'/api/production/inventories/node/{ref}/').status_code, (403, 404), ref)
        for ref in ('zz', '../..', "%27", NIL):
            self.assertLess(g.get(f'/api/production/inventories/node/{ref}/').status_code, 500, ref)
        # facturier/livreur
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).get('/api/production/inventories/').status_code, 403)
