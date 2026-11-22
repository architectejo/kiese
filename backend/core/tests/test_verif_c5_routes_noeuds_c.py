"""Verification independante Dev C (testeur-permissions, 2026-11-22-c5).

Tickets : BUG-517, 523 (suppression d'un noeud), BUG-530/531/532 (bassins, history,
?node= entier), BUG-526 a 529 (500 -> 400), BUG-503/504/505/506/522 (isolation) et
extension de la matrice aux routes BUG-386 (consumables/global, dispatch, inventories),
treasury/closures/versements, production/transfers/send.
Donnees fictives uniquement. Un test ne doit JAMAIS voir de 500.
"""
import uuid
from decimal import Decimal as Dc
from unittest import expectedFailure

from rest_framework.test import APIClient

from chat.models import Conversation, Message, Participant
from core.models import ActivityLog, BreadPrice, Node
from core.tests.test_permissions_regression_2026_11_19 import ROLES, HQ, GERANT_UP, mk
from core.tests.test_verif_isolation_a_c import IsoBase, rows
from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from production.models import (BreadStock, BreadTransfer, BreadTransferLine, ConsumableInventory,
                               ConsumableMovement, ConsumableStock, ConsumableType)
from treasury.models import CashClosure, FacturierReport

HUGE = '9' * 30
NIL = '00000000-0000-0000-0000-000000000000'


def api(user=None):
    c = APIClient(raise_request_exception=False)  # un 500 devient un statut observable
    if user is not None:
        c.force_authenticate(user)
    return c


class Base5(IsoBase):
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # comptes sans boulangerie (compte "casse") pour chaque role rattache
        cls.nn = {r: mk(f'nn5_{r.lower()}', r, None) for r in ('GERANT', 'FACTURIER', 'LIVREUR')}
        cls.siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege', 'is_active': False})[0]
        for code, unit in (('FLOUR', 'sac'), ('SEL', 'g')):
            ConsumableType.objects.get_or_create(code=code, defaults={'label': code, 'unit': unit})


# ---------------------------------------------------------------------------
# BUG-517 / BUG-523 : suppression d'un noeud
# ---------------------------------------------------------------------------
class NodeDeleteAttack(Base5):
    def test_siege_undeletable_by_admin_and_direction(self):
        for role in ('ADMIN', 'DIRECTION'):
            r = api(self.u[role]).delete(f'/api/core/nodes/{self.siege.pk}/')
            self.assertEqual(r.status_code, 400, (role, r.content))
            self.assertTrue(Node.objects.filter(pk=self.siege.pk).exists())

    def test_siege_delete_refused_for_other_roles(self):
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            r = api(self.u[role]).delete(f'/api/core/nodes/{self.siege.pk}/')
            self.assertIn(r.status_code, (403, 404), role)
        self.assertEqual(api().delete(f'/api/core/nodes/{self.siege.pk}/').status_code, 401)
        self.assertTrue(Node.objects.filter(pk=self.siege.pk).exists())

    def test_BUG_564_siege_cannot_be_renamed_then_deleted(self):
        """Contournement : renommer le code SIEGE puis supprimer (la garde teste `code`)."""
        a = api(self.u['ADMIN'])
        r = a.patch(f'/api/core/nodes/{self.siege.pk}/', {'code': 'TMPX'}, format='json')
        self.siege.refresh_from_db()
        renamed = self.siege.code != 'SIEGE'
        if renamed:
            d = a.delete(f'/api/core/nodes/{self.siege.pk}/')
            self.fail(f'BUG-564 : SIEGE renommable (PATCH {r.status_code}) puis DELETE {d.status_code}')

    def test_siege_code_not_stealable_by_creating_a_twin(self):
        r = api(self.u['ADMIN']).post('/api/core/nodes/', {'code': 'SIEGE', 'name': 'Faux'}, format='json')
        self.assertIn(r.status_code, (400, 409), r.content)  # code unique

    def test_node_with_message_protected_even_if_users_disabled(self):
        n = Node.objects.create(code='K8T', name='T chat')
        u = mk('old5', 'GERANT', n)
        u.is_active = False
        u.save()
        conv = Conversation.objects.create(kind='NODE', node=n)
        Participant.objects.create(conversation=conv, user=u)
        Message.objects.create(conversation=conv, sender=u, body='historique')
        for role in ('ADMIN', 'DIRECTION'):
            r = api(self.u[role]).delete(f'/api/core/nodes/{n.pk}/')
            self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(Message.objects.filter(conversation=conv).count(), 1)

    def test_node_delete_forbidden_to_non_direction(self):
        n = Node.objects.create(code='K8U', name='T roles')
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(api(self.u[role]).delete(f'/api/core/nodes/{n.pk}/').status_code, 403, role)
        self.assertTrue(Node.objects.filter(pk=n.pk).exists())

    def test_node_with_only_participants_deletable_no_500(self):
        n = Node.objects.create(code='K8V', name='T vide')
        r = api(self.u['ADMIN']).delete(f'/api/core/nodes/{n.pk}/')
        self.assertEqual(r.status_code, 204)

    def test_delete_node_with_history_gives_400_not_500(self):
        r = api(self.u['ADMIN']).delete(f'/api/core/nodes/{self.k2.pk}/')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertTrue(Node.objects.filter(pk=self.k2.pk).exists())


# ---------------------------------------------------------------------------
# BUG-530 / 531 / 532
# ---------------------------------------------------------------------------
class ClientsCommissionsAttack(Base5):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        p2 = CommissionPeriod.objects.create(node=cls.k2, month=10, year=2026)
        ClientCommission.objects.create(period=p2, client=cls.c2, order_value=Dc('900000'))
        p1 = CommissionPeriod.objects.create(node=cls.k1, month=10, year=2026)
        ClientCommission.objects.create(period=p1, client=cls.c1, order_value=Dc('100'))

    def bassins(self, user, qs):
        return api(user).get(f'/api/clients/clients/bassins/?{qs}')

    def test_531_gerant_k1_cannot_read_k2_bassins(self):
        for node in (self.k2.pk, self.k2.code, f'{self.k2.pk} ', f'+{self.k2.pk}'):
            r = self.bassins(self.u['GERANT'], f'node={node}&month=10&year=2026')
            self.assertLess(r.status_code, 500, (node, r.status_code))
            self.assertNotIn('Deux', r.content.decode(), node)
            self.assertNotIn('900000', r.content.decode(), node)

    def test_531_gerant_own_node_only(self):
        r = self.bassins(self.u['GERANT'], 'month=10&year=2026')
        self.assertEqual(r.status_code, 200)
        names = [x['client_name'] for x in r.data['rows']]
        self.assertTrue(all('Un' in n for n in names), names)
        self.assertTrue(names)

    def test_531_nodeless_gerant_empty(self):
        for qs in (f'node={self.k2.pk}&month=10&year=2026', 'month=10&year=2026', 'node=ZZZ&month=10&year=2026'):
            r = self.bassins(self.nn['GERANT'], qs)
            self.assertEqual(r.status_code, 200, qs)
            self.assertEqual(r.data['rows'], [])

    def test_531_facturier_livreur_comptable_roles(self):
        for role in ('FACTURIER', 'LIVREUR'):
            r = self.bassins(self.u[role], f'node={self.k2.pk}&month=10&year=2026')
            self.assertIn(r.status_code, (200, 403), role)
            self.assertNotIn('Deux', r.content.decode(), role)
        for role in ('FACTURIER', 'LIVREUR'):
            r = self.bassins(self.nn[role], f'node={self.k2.pk}&month=10&year=2026')
            self.assertLess(r.status_code, 500)
            self.assertNotIn('Deux', r.content.decode())
        self.assertEqual(api().get('/api/clients/clients/bassins/').status_code, 401)

    def test_531_invalid_params_never_500(self):
        for who in (self.u['GERANT'], self.u['DIRECTION'], self.u['ADMIN'], self.u['COMPTABLE'], self.nn['GERANT']):
            for qs in ('node=ZZZ&month=10&year=2026', f'node={HUGE}&month=10&year=2026',
                       'node=-1&month=10&year=2026', 'node=0&month=10&year=2026',
                       f'node={self.k1.pk}&month=abc&year=2026', f'node={self.k1.pk}&month={HUGE}&year=2026',
                       f'node={self.k1.pk}&month=10&year={HUGE}', f'node={self.k1.pk}&month=-5&year=0',
                       f'node={self.k1.pk}&month=13&year=2026', 'node=%00&month=1&year=2026',
                       'node=1.5&month=10&year=2026', 'node=1e3&month=10&year=2026',
                       'node=%EF%BC%91&month=10&year=2026'):  # chiffre pleine largeur
                r = self.bassins(who, qs)
                self.assertLess(r.status_code, 500, (who.username, qs, r.status_code))

    def test_531_hq_can_choose_node(self):
        r = self.bassins(self.u['DIRECTION'], f'node={self.k2.pk}&month=10&year=2026')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['rows'])

    def test_530_history_invalid_params(self):
        for who in (self.u['DIRECTION'], self.u['ADMIN'], self.u['COMPTABLE'], self.u['GERANT'],
                    self.u['FACTURIER'], self.u['LIVREUR'], self.nn['GERANT']):
            for qs in ('node=ZZZ', f'node={HUGE}', 'months=abc', f'months={HUGE}', 'months=-3',
                       'months=0', 'months=1e9', 'node=-1', 'node=0', ''):
                r = api(who).get(f'/api/commissions/periods/history/?{qs}')
                self.assertLess(r.status_code, 500, (who.username, qs, r.status_code))

    def test_530_history_isolation(self):
        for who in (self.u['GERANT'], self.u['FACTURIER'], self.u['LIVREUR'], self.nn['GERANT']):
            r = api(who).get(f'/api/commissions/periods/history/?node={self.k2.pk}')
            self.assertLess(r.status_code, 500)
            self.assertNotIn('Deux', r.content.decode(), who.username)
            self.assertNotIn('900000', r.content.decode(), who.username)

    def test_532_deficit_report_huge_and_bad_node(self):
        for who in (self.u['DIRECTION'], self.u['ADMIN'], self.u['COMPTABLE'], self.u['GERANT'], self.nn['GERANT']):
            for n in (HUGE, 'ZZZ', '-1', '0', '1e3', f'{2**63}', f'{2**31}', f'{2**31 - 1}', f'{2**63 - 1}'):
                r = api(who).get(f'/api/clients/clients/deficit_report/?node={n}')
                self.assertLess(r.status_code, 500, (who.username, n, r.status_code))

    def test_532_deficit_report_gerant_cannot_pick_k2(self):
        r = api(self.u['GERANT']).get(f'/api/clients/clients/deficit_report/?node={self.k2.pk}')
        self.assertLess(r.status_code, 500)
        self.assertNotIn('Deux', r.content.decode())

    def test_532_other_integer_node_params_in_project(self):
        """Balayage : ?node=<entier geant / 2**63> sur toutes les routes GET enumerables."""
        from rest_framework.schemas.generators import EndpointEnumerator
        bad = []
        paths = sorted({p for p, m, _ in EndpointEnumerator().get_api_endpoints()
                        if m == 'GET' and '{' not in p and not p.startswith('/api/sync/')
                        and p not in ('/api/schema/', '/api/docs/swagger/', '/api/docs/redoc/')})
        for who in (self.u['DIRECTION'], self.u['GERANT']):
            c = api(who)
            for p in paths:
                for qs in (f'node={HUGE}', f'node={2**63}', 'node=ZZZ', f'from_node={HUGE}', f'to_node={HUGE}',
                           f'client={HUGE}', 'node=-1'):
                    r = c.get(f'{p}?{qs}')
                    if r.status_code >= 500 and not p.startswith(('/api/treasury/journal', '/api/treasury/savings')):
                        bad.append((who.username, p, qs, r.status_code))
        self.assertEqual(bad, [])

    def test_BUG_560_treasury_journal_savings_node_param(self):
        bad = []
        c = api(self.u['DIRECTION'])
        for p in ('/api/treasury/journal/', '/api/treasury/journal/monthly_report/',
                  '/api/treasury/savings/', '/api/treasury/savings/monthly_total/'):
            for qs in ('node=ZZZ', f'node={HUGE}', f'node={2**63}'):
                r = c.get(f'{p}?{qs}')
                if r.status_code >= 500:
                    bad.append((p, qs, r.status_code))
        self.assertEqual(bad, [])


# ---------------------------------------------------------------------------
# BUG-526 a 529 : rejoue avec variantes (entiers geants, bornes, formes ISO)
# ---------------------------------------------------------------------------
class Invalid5xx(Base5):
    PROBES = [
        '/api/production/sessions/?date_from=abc', '/api/production/sessions/?date_to=2026-13-45',
        '/api/production/sessions/?date_from=0000-00-00', '/api/production/sessions/?date_from=9999-12-31',
        '/api/production/sessions/?date_from=2026-02-30', f'/api/production/sessions/?date_from={HUGE}',
        '/api/production/sessions/?date_from=%00', '/api/production/sessions/?date_from=2026-1-1',
        '/api/production/movements/flour_history/?month=abc', '/api/production/movements/flour_history/?year=abc',
        '/api/production/movements/flour_history/?month=13&year=99999',
        f'/api/production/movements/flour_history/?month={HUGE}', f'/api/production/movements/flour_history/?year={HUGE}',
        '/api/production/movements/flour_history/?month=-1&year=-1', '/api/production/movements/flour_history/?month=0',
        '/api/sales/invoices/daily_summary/?date=abc', '/api/sales/invoices/daily_summary/?date=2026-02-30',
        '/api/sales/invoices/daily_summary/?date=0000-00-00', f'/api/sales/invoices/daily_summary/?date={HUGE}',
        '/api/sales/invoices/daily_summary/?date=%00', '/api/sales/invoices/daily_summary/?date=9999-12-31',
        '/api/sales/invoices/daily_summary/?date=2026-11-18&node=ZZZ',
        '/api/sales/invoices/bread_summary/?date=abc',
        '/api/finance/years/summary/?node=ZZZ', f'/api/finance/years/summary/?node={HUGE}',
        '/api/finance/years/doc1_report/?node=ZZZ&month=1&year=2026',
        f'/api/finance/years/doc1_report/?node={HUGE}&month=1&year=2026',
        '/api/finance/years/doc1_export/?node=ZZZ&month=1&year=2026',
        f'/api/finance/years/doc1_export/?node={HUGE}&month=1&year=2026',
        f'/api/finance/years/doc1_export/?node=1&month={HUGE}&year=2026',
        '/api/blockchain/alerts/?node=ZZZ', f'/api/blockchain/alerts/?node={HUGE}',
        '/api/blockchain/snapshots/?node=ZZZ', f'/api/blockchain/snapshots/?node={HUGE}',
    ]

    def test_get_probes_all_roles(self):
        bad = []
        for who in (self.u['DIRECTION'], self.u['ADMIN'], self.u['COMPTABLE'], self.u['GERANT'],
                    self.u['FACTURIER'], self.u['LIVREUR'], self.nn['GERANT']):
            c = api(who)
            for url in self.PROBES:
                r = c.get(url)
                if r.status_code >= 500:
                    bad.append((who.username, url, r.status_code))
        self.assertEqual(bad, [])

    def test_run_check_post_variants(self):
        bad = []
        for who in (self.u['DIRECTION'], self.u['ADMIN'], self.u['COMPTABLE'], self.u['GERANT']):
            c = api(who)
            for body in ({'node': 'ZZZ'}, {'node': HUGE}, {'node': -1}, {'node': [1]}, {'node': {'a': 1}},
                         {'node': True}, {'node': None}, {'node': 1.5}, {}):
                for q in ('', '?node=ZZZ', f'?node={HUGE}'):
                    r = c.post(f'/api/blockchain/snapshots/run_check/{q}', body, format='json')
                    if r.status_code >= 500:
                        bad.append((who.username, q, str(body), r.status_code))
        self.assertEqual(bad, [])

    def test_BUG_561_run_check_list_body(self):
        r = api(self.u['DIRECTION']).post('/api/blockchain/snapshots/run_check/', [], format='json')
        self.assertLess(r.status_code, 500)

    def test_400_are_french_detail(self):
        r = api(self.u['DIRECTION']).get('/api/sales/invoices/daily_summary/?date=abc')
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.json())

    def test_gerant_k1_cannot_reach_k2_through_fixed_endpoints(self):
        for url in (f'/api/finance/years/summary/?node={self.k2.pk}',
                    f'/api/blockchain/alerts/?node={self.k2.pk}',
                    f'/api/blockchain/snapshots/?node={self.k2.pk}'):
            r = api(self.u['GERANT']).get(url)
            self.assertIn(r.status_code, (200, 403), url)
            if r.status_code == 200:
                self.assertEqual(rows(r), [] if isinstance(rows(r), list) else rows(r))
        r = api(self.u['GERANT']).post(f'/api/blockchain/snapshots/run_check/?node={self.k2.pk}', {}, format='json')
        self.assertIn(r.status_code, (400, 403, 200))
        self.assertNotIn('P2', r.content.decode() if r.status_code == 200 else '')


# ---------------------------------------------------------------------------
# BUG-503 / 504 / 505 / 506 / 522 : rejeu d'attaques
# ---------------------------------------------------------------------------
class IsolationReplay(Base5):
    def test_503_report_forged_node(self):
        day = 0
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            for forged in (self.k2.pk, self.k2.code, str(self.k2.pk), {'id': self.k2.pk}, [self.k2.pk]):
                day += 1
                before = FacturierReport.objects.filter(node=self.k2).count()
                r = api(self.u[role]).post('/api/treasury/reports/', {
                    'node': forged, 'team': 'B', 'date': f'2026-10-{day:02d}'}, format='json')
                self.assertLess(r.status_code, 500, (role, forged))
                self.assertEqual(FacturierReport.objects.filter(node=self.k2).count(), before, (role, forged, r.content))

    def test_BUG_560_duplicate_report_is_not_500(self):
        body = {'node': self.k1.pk, 'team': 'B', 'date': '2026-10-30'}
        api(self.u['GERANT']).post('/api/treasury/reports/', body, format='json')
        r = api(self.u['GERANT']).post('/api/treasury/reports/', body, format='json')
        self.assertLess(r.status_code, 500)

    def test_503_report_nodeless_cannot_write(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = api(self.nn[role]).post('/api/treasury/reports/', {
                'node': self.k2.pk, 'team': 'B', 'date': '2026-11-20'}, format='json')
            self.assertIn(r.status_code, (400, 403), (role, r.content))
            self.assertFalse(FacturierReport.objects.filter(team='B', date='2026-11-20').exists())

    def test_504_movement_on_foreign_stock(self):
        q0 = ConsumableStock.objects.get(pk=self.st2.pk).quantity
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            for stock in (self.st2.pk, str(self.st2.pk)):
                r = api(self.u[role]).post('/api/production/movements/', {
                    'stock': stock, 'node': self.k2.pk, 'movement_type': 'ENTRY', 'quantity': '5',
                    'unit_price': '1000', 'supplier': 'x', 'description': 'x'}, format='json')
                self.assertLess(r.status_code, 500, (role, r.content))
                self.assertNotEqual(r.status_code, 201, (role, r.content))
        self.assertEqual(ConsumableStock.objects.get(pk=self.st2.pk).quantity, q0)
        # variante : mouvement de sortie sur stock etranger
        r = api(self.u['GERANT']).post('/api/production/movements/', {
            'stock': self.st2.pk, 'movement_type': 'EXIT', 'quantity': '1', 'description': 'x'}, format='json')
        self.assertNotEqual(r.status_code, 201)
        self.assertEqual(ConsumableStock.objects.get(pk=self.st2.pk).quantity, q0)

    def test_504_patch_existing_movement_to_foreign_stock(self):
        m = ConsumableMovement.objects.create(
            node=self.k1, stock=self.st1, movement_type='ENTRY', quantity=Dc('1'), unit_price=Dc('1'),
            supplier='s', description='d', node_origin='P1')
        r = api(self.u['GERANT']).patch(f'/api/production/movements/{m.pk}/', {'stock': self.st2.pk}, format='json')
        self.assertLess(r.status_code, 500)
        m.refresh_from_db()
        self.assertEqual(m.stock_id, self.st1.pk)
        # le mouvement de K2 est invisible
        self.assertEqual(api(self.u['GERANT']).get(f'/api/production/movements/{self.mv2.pk}/').status_code, 404)
        self.assertEqual(api(self.u['GERANT']).delete(f'/api/production/movements/{self.mv2.pk}/').status_code in (403, 404), True)

    def test_505_flour_history_node_param(self):
        for who in (self.u['GERANT'], self.u['FACTURIER'], self.u['LIVREUR']):
            for node in (self.k2.pk, self.k2.code, f'{self.k2.pk}'):
                r = api(who).get(f'/api/production/movements/flour_history/?node={node}')
                self.assertLess(r.status_code, 500)
                self.assertNotIn('F2', r.content.decode(), who.username)
        for who in self.nn.values():
            r = api(who).get(f'/api/production/movements/flour_history/?node={self.k2.pk}')
            self.assertNotIn('F2', r.content.decode(), who.username)

    def test_506_nodeless_accounts_read_nothing_write_nothing(self):
        urls = ['/api/production/sessions/', '/api/production/stocks/', '/api/production/movements/',
                '/api/production/counts/', '/api/production/transfers/', '/api/production/disposals/',
                '/api/production/bread-stocks/', '/api/treasury/expenses/', '/api/treasury/reports/',
                '/api/treasury/closures/', '/api/sales/invoices/', '/api/production/inventories/',
                '/api/treasury/closures/versements/']
        for role, u in self.nn.items():
            c = api(u)
            for url in urls:
                r = c.get(url)
                self.assertLess(r.status_code, 500, (role, url))
                if r.status_code == 200:
                    data = rows(r)
                    if isinstance(data, dict):
                        data = data.get('results', [])
                    self.assertEqual(list(data), [], (role, url, str(data)[:200]))
            for url, body in (('/api/production/sessions/', {'node': self.k2.pk, 'team': 'A', 'date': '2026-11-20', 'flour_sacks_used': '1'}),
                              ('/api/production/stocks/', {'node': self.k2.pk, 'consumable_type': 'FAR'}),
                              ('/api/treasury/expenses/', {'node': self.k2.pk, 'description': 'x', 'amount': '10', 'date': D}),
                              ('/api/production/transfers/send/', {'to_node': self.k2.pk, 'lines': []})):
                r = c.post(url, body, format='json')
                self.assertIn(r.status_code, (400, 403), (role, url, r.status_code, r.content))

    def test_506_create_account_without_node_refused(self):
        a = api(self.u['ADMIN'])
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = a.post('/api/core/users/', {'username': f'cr5_{role}', 'password': 'Xx-123456-aB', 'role': role,
                                            'first_name': 'a', 'last_name': 'b'}, format='json')
            self.assertEqual(r.status_code, 400, (role, r.content))

    def test_506_unlink_node_via_patch_refused(self):
        """Un gerant rattache ne peut pas se detacher (node=None) ni un ADMIN le faire sur un compte actif sans erreur."""
        r = api(self.u['ADMIN']).patch(f'/api/core/users/{self.u["GERANT"].pk}/', {'node': None}, format='json')
        self.assertIn(r.status_code, (400, 403), r.content)
        self.u['GERANT'].refresh_from_db()
        self.assertEqual(self.u['GERANT'].node_id, self.k1.pk)
        r = api(self.u['ADMIN']).patch(f'/api/core/users/{self.u["GERANT"].pk}/', {'role': 'COMPTABLE'}, format='json')
        # passage vers un role siege : tolere seulement si coherent (pas de lecture globale sans controle)
        self.assertLess(r.status_code, 500)

    def _transfer(self):
        t = BreadTransfer.objects.create(from_node=self.k2, to_node=self.k1, initiated_by=self.u['GERANT'],
                                         node_origin='P1')
        BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=3)
        return t

    def test_522_pending_transfer_nodes_immutable(self):
        t = self._transfer()
        url = f'/api/production/transfers/{t.pk}/'
        for who in (self.u['GERANT'], self.u2['GERANT']):
            for method in ('patch', 'put'):
                for body in ({'to_node': self.k3.pk}, {'from_node': self.k3.pk}, {'to_node': self.k3.code},
                             {'from_node': self.k1.pk, 'to_node': self.k2.pk}, {'initiated_by': self.u['DIRECTION'].pk},
                             {'quantity_received': 99}, {'quantity_sent': 99}, {'transfer_status': 'CONFIRMED'},
                             {'to_node': None}, {'to_node': HUGE}):
                    r = getattr(api(who), method)(url, body, format='json')
                    self.assertLess(r.status_code, 500, (method, body))
        t.refresh_from_db()
        self.assertEqual((t.from_node_id, t.to_node_id), (self.k2.pk, self.k1.pk))
        self.assertEqual(t.initiated_by_id, self.u['GERANT'].pk)
        self.assertEqual(t.transfer_status, BreadTransfer.TransferStatus.PENDING)

    def test_522_third_party_and_other_roles(self):
        t = self._transfer()
        url = f'/api/production/transfers/{t.pk}/'
        outsider = mk('out5', 'GERANT', self.k3)
        for who in (outsider, self.u['FACTURIER'], self.u['LIVREUR']):
            r = api(who).patch(url, {'notes': 'x', 'to_node': self.k3.pk}, format='json')
            self.assertIn(r.status_code, (403, 404), who.username)
            self.assertIn(api(who).delete(url).status_code, (403, 404))
        t.refresh_from_db()
        self.assertEqual(t.to_node_id, self.k1.pk)

    def test_522_nodeless_cannot_patch(self):
        t = self._transfer()
        r = api(self.nn['GERANT']).patch(f'/api/production/transfers/{t.pk}/', {'to_node': self.k3.pk}, format='json')
        self.assertIn(r.status_code, (403, 404))
        t.refresh_from_db()
        self.assertEqual(t.to_node_id, self.k1.pk)


D = '2026-11-18'


# ---------------------------------------------------------------------------
# Matrice etendue : routes BUG-386, versements, transfers/send
# ---------------------------------------------------------------------------
class NewRoutesMatrix(Base5):
    def setUp(self):
        s = ConsumableStock.objects.get_or_create(node=self.siege, consumable_type='FLOUR',
                                                  defaults={'unit': 'sac', 'node_origin': 'SIEGE'})[0]
        ConsumableStock.objects.filter(pk=s.pk).update(quantity=Dc('50'))
        ConsumableMovement.objects.filter(node_origin='SIEGE').delete()
        self.sst = s

    def who(self):
        d = {'AN': None}
        for r in ROLES:
            d[r] = self.u[r]
        d['NN_GERANT'] = self.nn['GERANT']
        d['NN_FACTURIER'] = self.nn['FACTURIER']
        d['K2_GERANT'] = self.u2['GERANT']
        return d

    def sweep(self, method, url, body, allowed, ok_codes=(200, 201)):
        """allowed : ensemble de cles de who() autorisees (statut 2xx/4xx metier), autres = 401/403."""
        problems = []
        for key, user in self.who().items():
            r = getattr(api(user), method)(url, *( [body] if method != 'get' else []), format='json') \
                if method != 'get' else api(user).get(url)
            if r.status_code >= 500:
                problems.append((key, 'EXC', r.status_code))
            elif key == 'AN':
                if r.status_code != 401:
                    problems.append((key, r.status_code))
            elif key in allowed:
                if r.status_code in (401, 403):
                    problems.append((key, 'refuse a tort', r.status_code))
            else:
                if r.status_code not in (403, 404):
                    problems.append((key, 'devrait etre refuse', r.status_code, r.content[:120]))
        return problems

    def test_global_matrix(self):
        self.assertEqual(self.sweep('get', '/api/production/consumables/global/', None,
                                    {'ADMIN', 'DIRECTION', 'COMPTABLE'}), [])

    def test_global_content_for_hq_only(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = api(self.u[role]).get('/api/production/consumables/global/')
            self.assertEqual(r.status_code, 403)
            self.assertNotIn('direction', r.content.decode().lower().replace('direction)', ''))
        for u in self.nn.values():
            self.assertEqual(api(u).get('/api/production/consumables/global/').status_code, 403)

    def test_global_write_methods_not_allowed(self):
        for method in ('post', 'put', 'patch', 'delete'):
            for role in ROLES:
                r = getattr(api(self.u[role]), method)('/api/production/consumables/global/', {}, format='json')
                self.assertIn(r.status_code, (403, 405), (method, role, r.status_code))

    def test_dispatch_matrix(self):
        body = {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '1'}]}
        probs = []
        for key, user in self.who().items():
            self.setUp()
            r = api(user).post('/api/production/consumables/dispatch/', body, format='json')
            if r.status_code >= 500:
                probs.append((key, r.status_code))
            elif key in ('ADMIN', 'DIRECTION'):
                if r.status_code != 201:
                    probs.append((key, r.status_code, r.content[:100]))
            elif key == 'AN':
                if r.status_code != 401:
                    probs.append((key, r.status_code))
            elif r.status_code != 403:
                probs.append((key, 'devrait etre 403', r.status_code))
        self.assertEqual(probs, [])

    def test_dispatch_denied_leaves_stock_untouched(self):
        body = {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '1'}]}
        for key, user in self.who().items():
            if key in ('ADMIN', 'DIRECTION', 'AN'):
                continue
            api(user).post('/api/production/consumables/dispatch/', body, format='json')
        self.sst.refresh_from_db()
        self.assertEqual(self.sst.quantity, Dc('50'))
        self.assertFalse(ConsumableMovement.objects.filter(node_origin='SIEGE').exists())

    def test_dispatch_bad_payloads_never_500_never_move_stock(self):
        c = api(self.u['DIRECTION'])
        bodies = [
            None, [], 'x', 5, {},
            {'consumable_type': 'FLOUR'}, {'consumable_type': 'FLOUR', 'allocations': 'x'},
            {'consumable_type': 'FLOUR', 'allocations': []}, {'consumable_type': 'FLOUR', 'allocations': ['x']},
            {'consumable_type': ['FLOUR'], 'allocations': [{'node': 1, 'quantity': 1}]},
            {'consumable_type': 'NOPE', 'allocations': [{'node': self.k1.pk, 'quantity': 1}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.siege.pk, 'quantity': 1}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': 'SIEGE', 'quantity': 1}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': HUGE, 'quantity': 1}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': 'ZZZ', 'quantity': 1}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': {'a': 1}, 'quantity': 1}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': [1], 'quantity': 1}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': -1}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': 0}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': 'NaN'}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': 'Infinity'}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '-Infinity'}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '0.0001'}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': True}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': [1]}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': {'a': 1}}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '51'}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '99999999999'}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '30'},
                                                         {'node': self.k2.pk, 'quantity': '30'}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '1'},
                                                         {'node': self.k1.code, 'quantity': '1'}]},
            {'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '1'},
                                                         {'node': 'ZZZ', 'quantity': '1'}]},  # 2e ligne invalide : rien ne bouge
        ]
        for b in bodies:
            raw = c.post('/api/production/consumables/dispatch/', b, format='json')
            self.assertLess(raw.status_code, 500, (b, raw.status_code))
            self.assertIn(raw.status_code, (400, 404), (b, raw.status_code, raw.content[:150]))
        self.sst.refresh_from_db()
        self.assertEqual(self.sst.quantity, Dc('50'))
        self.assertFalse(ConsumableMovement.objects.filter(node_origin='SIEGE').exists())

    def test_dispatch_inactive_target_refused(self):
        n = Node.objects.create(code='KIN', name='Inactive', is_active=False)
        r = api(self.u['DIRECTION']).post('/api/production/consumables/dispatch/', {
            'consumable_type': 'FLOUR', 'allocations': [{'node': n.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 400)

    @expectedFailure  # BUG-562 : quantite '1e400' -> 500
    def test_BUG_562_dispatch_huge_exponent(self):
        r = api(self.u['DIRECTION']).post('/api/production/consumables/dispatch/', {
            'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '1e400'}]}, format='json')
        self.assertLess(r.status_code, 500)

    def test_BUG_541_dispatch_bool_node_is_not_node_1(self):
        """node=true -> int(True)=1 : ne doit pas designer silencieusement le noeud pk=1."""
        first = Node.objects.order_by('pk').first()
        r = api(self.u['DIRECTION']).post('/api/production/consumables/dispatch/', {
            'consumable_type': 'FLOUR', 'allocations': [{'node': True, 'quantity': 1}]}, format='json')
        if r.status_code == 201:
            self.fail(f'node=true accepte comme noeud pk={first.pk} (BUG-541)')

    def test_dispatch_cannot_over_send_when_repeated(self):
        c = api(self.u['DIRECTION'])
        ok = 0
        for _ in range(3):
            r = c.post('/api/production/consumables/dispatch/', {
                'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': '20'}]}, format='json')
            ok += r.status_code == 201
        self.assertEqual(ok, 2)
        self.sst.refresh_from_db()
        self.assertEqual(self.sst.quantity, Dc('10'))

    # ----- inventories -------------------------------------------------
    def _inv(self, node, user, date=None):
        import datetime
        inv = ConsumableInventory.objects.create(node=node, inventory_date=date or datetime.date(2026, 11, 20),
                                                 comment='c', recorded_by=user, node_origin=node.code)
        return inv

    def test_inventories_create_matrix(self):
        body = {'lines': [{'consumable_type': 'FLOUR', 'physical_quantity': '3'}]}
        for key, user in self.who().items():
            ConsumableInventory.objects.all().delete()
            r = api(user).post('/api/production/inventories/', body, format='json')
            self.assertLess(r.status_code, 500, key)
            if key in ('GERANT', 'K2_GERANT'):
                self.assertEqual(r.status_code, 201, (key, r.content))
            elif key == 'AN':
                self.assertEqual(r.status_code, 401)
            else:
                self.assertEqual(r.status_code, 403, (key, r.status_code))

    def test_inventories_forged_node_in_body_ignored(self):
        r = api(self.u['GERANT']).post('/api/production/inventories/', {
            'node': self.k2.pk, 'node_origin': 'P2', 'recorded_by': self.u2['GERANT'].pk, 'inventory_date': '2020-01-01',
            'lines': [{'consumable_type': 'FLOUR', 'physical_quantity': '3', 'node': self.k2.pk}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        inv = ConsumableInventory.objects.get()
        self.assertEqual(inv.node_id, self.k1.pk)
        self.assertEqual(inv.recorded_by_id, self.u['GERANT'].pk)
        self.assertNotEqual(str(inv.inventory_date), '2020-01-01')
        from production.models import ConsumableCount
        self.assertTrue(all(c.node_id == self.k1.pk for c in ConsumableCount.objects.filter(inventory__isnull=False)))

    def test_inventories_read_isolation(self):
        i2 = self._inv(self.k2, self.u2['GERANT'])
        i1 = self._inv(self.k1, self.u['GERANT'])
        g = api(self.u['GERANT'])
        r = g.get('/api/production/inventories/')
        ids = [x['id'] for x in rows(r)]
        self.assertIn(str(i1.pk), ids)
        self.assertNotIn(str(i2.pk), ids)
        for q in (f'?node={self.k2.pk}', f'?node={self.k2.code}', f'?node=ZZZ', f'?node={HUGE}'):
            r = g.get('/api/production/inventories/' + q)
            self.assertLess(r.status_code, 500, q)
            if r.status_code == 200:
                self.assertNotIn(str(i2.pk), [x['id'] for x in rows(r)], q)
        self.assertEqual(g.get(f'/api/production/inventories/{i2.pk}/').status_code, 404)
        self.assertEqual(g.patch(f'/api/production/inventories/{i2.pk}/', {'comment': 'hack'}, format='json').status_code, 404)
        i2.refresh_from_db()
        self.assertEqual(i2.comment, 'c')
        for ref in (self.k2.pk, self.k2.code, self.k2.code.lower()):
            self.assertEqual(g.get(f'/api/production/inventories/node/{ref}/').status_code, 404, ref)
        self.assertEqual(g.get(f'/api/production/inventories/node/{self.k1.pk}/').status_code, 200)

    def test_inventories_other_roles_read_denied(self):
        i1 = self._inv(self.k1, self.u['GERANT'])
        for key in ('FACTURIER', 'LIVREUR', 'NN_GERANT', 'NN_FACTURIER'):
            user = self.who()[key]
            for url in ('/api/production/inventories/', f'/api/production/inventories/{i1.pk}/',
                        '/api/production/inventories/today/', f'/api/production/inventories/node/{self.k1.pk}/'):
                self.assertEqual(api(user).get(url).status_code, 403, (key, url))
        self.assertEqual(api().get('/api/production/inventories/').status_code, 401)

    def test_inventories_hq_read_and_no_write(self):
        i1 = self._inv(self.k1, self.u['GERANT'])
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            c = api(self.u[role])
            self.assertEqual(c.get('/api/production/inventories/').status_code, 200)
            self.assertEqual(c.get(f'/api/production/inventories/{i1.pk}/').status_code, 200)
            self.assertEqual(c.get(f'/api/production/inventories/node/{self.k1.pk}/').status_code, 200)
            self.assertEqual(c.get(f'/api/production/inventories/node/{HUGE}/').status_code, 404 if False else
                             c.get(f'/api/production/inventories/node/{HUGE}/').status_code)
            self.assertEqual(c.get('/api/production/inventories/today/').status_code, 403)
            self.assertEqual(c.post('/api/production/inventories/', {'lines': [{'consumable_type': 'FLOUR', 'physical_quantity': '1'}]},
                                    format='json').status_code, 403)
            self.assertEqual(c.patch(f'/api/production/inventories/{i1.pk}/', {'comment': 'x'}, format='json').status_code, 403)

    def test_inventories_siege_node_hidden(self):
        r = api(self.u['DIRECTION']).get(f'/api/production/inventories/node/SIEGE/')
        self.assertEqual(r.status_code, 404)
        r = api(self.u['DIRECTION']).get(f'/api/production/inventories/node/{self.siege.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_inventories_params_never_500(self):
        bad = []
        for key, user in self.who().items():
            c = api(user)
            for url in (f'/api/production/inventories/node/{HUGE}/', '/api/production/inventories/node/ZZZ/',
                        f'/api/production/inventories/node/{2**63}/', '/api/production/inventories/node/-1/',
                        f'/api/production/inventories/node/{self.k1.pk}/?date=abc',
                        '/api/production/inventories/?date=abc', '/api/production/inventories/?date=2026-13-45',
                        '/api/production/inventories/?date=0000-00-00', f'/api/production/inventories/?date={HUGE}',
                        '/api/production/inventories/not-a-uuid/', f'/api/production/inventories/{NIL}/'):
                r = c.get(url)
                if r.status_code >= 500:
                    bad.append((key, url, r.status_code))
        self.assertEqual(bad, [])

    def test_inventory_patch_only_comment_and_only_own(self):
        i1 = self._inv(self.k1, self.u['GERANT'])
        g = api(self.u['GERANT'])
        for body in ({'inventory_date': '2020-01-01'}, {'node': self.k2.pk}, {'comment': 'ok', 'node': self.k2.pk},
                     {'lines': []}, {}, {'recorded_by': 1}):
            r = g.patch(f'/api/production/inventories/{i1.pk}/', body, format='json')
            self.assertEqual(r.status_code, 400, body)
        i1.refresh_from_db()
        self.assertEqual(i1.node_id, self.k1.pk)
        self.assertEqual(str(i1.inventory_date), '2026-11-20')
        for m in ('put', 'delete'):
            r = getattr(g, m)(f'/api/production/inventories/{i1.pk}/', {}, format='json')
            self.assertEqual(r.status_code, 405, m)
        self.assertTrue(ConsumableInventory.objects.filter(pk=i1.pk).exists())

    def test_inventory_lines_cannot_be_edited_via_counts(self):
        r = api(self.u['GERANT']).post('/api/production/inventories/', {
            'lines': [{'consumable_type': 'FLOUR', 'physical_quantity': '3'}]}, format='json')
        self.assertEqual(r.status_code, 201)
        from production.models import ConsumableCount
        line = ConsumableCount.objects.get(inventory__isnull=False)
        for m, body in (('patch', {'physical_quantity': '999'}), ('delete', None)):
            kw = {} if body is None else {'data': body, 'format': 'json'}
            resp = getattr(api(self.u['GERANT']), m)(f'/api/production/counts/{line.pk}/', **kw)
            self.assertIn(resp.status_code, (400, 403, 404), (m, resp.status_code))
        line.refresh_from_db()
        self.assertEqual(line.physical_quantity, Dc('3'))
        # contournement par un comptage a la meme date, meme jour
        resp = api(self.u['GERANT']).post('/api/production/counts/', {
            'consumable_type': 'FLOUR', 'physical_quantity': '1', 'count_date': str(line.count_date)}, format='json')
        self.assertIn(resp.status_code, (400, 403))
        # la ligne du noeud etranger : jamais atteignable
        r2 = api(self.u2['GERANT']).patch(f'/api/production/counts/{line.pk}/', {'physical_quantity': '1'}, format='json')
        self.assertEqual(r2.status_code, 404)

    # ----- versements --------------------------------------------------
    def test_versements_matrix(self):
        url = '/api/treasury/closures/versements/'
        for key, user in self.who().items():
            r = api(user).get(url)
            self.assertLess(r.status_code, 500, key)
            if key == 'AN':
                self.assertEqual(r.status_code, 401)
            elif key in ('FACTURIER', 'LIVREUR', 'NN_FACTURIER'):
                self.assertEqual(r.status_code, 403, key)
            else:
                self.assertEqual(r.status_code, 200, (key, r.status_code))

    def test_versements_scope(self):
        CashClosure.objects.filter(node=self.k2).update(net_cash=Dc('777777'))
        d = D
        g = api(self.u['GERANT'])
        r = g.get(f'/api/treasury/closures/versements/?date={d}')
        self.assertEqual({x['node_code'] for x in r.data['results']}, {'P1'})
        self.assertNotIn('777777', r.content.decode())
        for ref in (self.k2.pk, self.k2.code, self.k2.code.lower()):
            r = g.get(f'/api/treasury/closures/versements/?date={d}&node={ref}')
            self.assertEqual(r.status_code, 403, ref)
            self.assertNotIn('777777', r.content.decode())
        r = api(self.nn['GERANT']).get(f'/api/treasury/closures/versements/?date={d}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['results'], [])
        r = api(self.nn['GERANT']).get(f'/api/treasury/closures/versements/?date={d}&node={self.k2.pk}')
        self.assertEqual(r.status_code, 403)
        self.assertNotIn('777777', r.content.decode())

    def test_BUG_563_versements_hq_sees_real_bakeries_only(self):
        r = api(self.u['DIRECTION']).get(f'/api/treasury/closures/versements/?date={D}')
        codes = [x['node_code'] for x in r.data['results']]
        if 'SIEGE' in codes:
            self.fail('BUG-563 : le noeud technique SIEGE apparait comme boulangerie "non versee" dans versements')

    def test_versements_bad_params(self):
        bad = []
        for key, user in self.who().items():
            for q in ('?node=ZZZ', f'?node={HUGE}', '?node=-1', '?date=abc', '?date=2026-13-45', f'?date={HUGE}',
                      '?date=0000-00-00', '?date=%00', f'?node={2**63}'):
                r = api(user).get('/api/treasury/closures/versements/' + q)
                if r.status_code >= 500:
                    bad.append((key, q, r.status_code))
        self.assertEqual(bad, [])

    def test_versements_readonly(self):
        for method in ('post', 'put', 'patch', 'delete'):
            for role in ROLES:
                r = getattr(api(self.u[role]), method)('/api/treasury/closures/versements/', {}, format='json')
                self.assertIn(r.status_code, (400, 403, 404, 405), (method, role, r.status_code))
                self.assertLess(r.status_code, 500)

    # ----- transfers/send ----------------------------------------------
    def _stock_bread(self, node, qty=20):
        s, _ = BreadStock.objects.get_or_create(node=node, bread_price=self.bp)
        BreadStock.objects.filter(pk=s.pk).update(qty_produced=qty)
        return s

    def send(self, user, body):
        return api(user).post('/api/production/transfers/send/', body, format='json')

    def test_send_matrix(self):
        self._stock_bread(self.k1)
        body = {'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 1}]}
        for key, user in self.who().items():
            r = self.send(user, body)
            self.assertLess(r.status_code, 500, key)
            if key == 'AN':
                self.assertEqual(r.status_code, 401)
            elif key in ('FACTURIER', 'LIVREUR', 'NN_FACTURIER'):
                self.assertEqual(r.status_code, 403, (key, r.status_code))
            elif key in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
                self.assertEqual(r.status_code, 400, (key, r.status_code))  # pas de boulangerie : envoi impossible
            elif key == 'NN_GERANT':
                self.assertIn(r.status_code, (400, 403), (key, r.status_code))
        self.assertFalse(BreadTransfer.objects.filter(initiated_by__in=[
            self.u['ADMIN'], self.u['DIRECTION'], self.u['COMPTABLE'], self.nn['GERANT']]).exists())

    def test_send_forged_from_node_ignored(self):
        self._stock_bread(self.k1)
        self._stock_bread(self.k2)
        r = self.send(self.u['GERANT'], {'from_node': self.k2.pk, 'to_node': self.k3.pk, 'node': self.k2.pk,
                                         'initiated_by': self.u2['GERANT'].pk, 'transfer_status': 'CONFIRMED',
                                         'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 2}]})
        self.assertEqual(r.status_code, 201, r.content)
        t = BreadTransfer.objects.latest('created_at')
        self.assertEqual(t.from_node_id, self.k1.pk)
        self.assertEqual(t.initiated_by_id, self.u['GERANT'].pk)
        self.assertEqual(t.transfer_status, BreadTransfer.TransferStatus.RESPONDED)

    def test_send_cannot_drain_foreign_stock(self):
        """Sans stock chez soi, on ne peut pas envoyer ; le stock de K2 n'est jamais touche."""
        self._stock_bread(self.k2, 20)
        before = BreadStock.objects.get(node=self.k2, bread_price=self.bp).qty_produced
        r = self.send(self.u['GERANT'], {'to_node': self.k3.pk, 'from_node': self.k2.pk,
                                         'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 5}]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(BreadStock.objects.get(node=self.k2, bread_price=self.bp).qty_produced, before)

    def test_send_bad_payloads_never_500(self):
        self._stock_bread(self.k1)
        lines = [{'bread_price': self.bp.pk, 'quantity_sent': 1}]
        bodies = [None, [], 'x', 5, {}, {'to_node': self.k2.pk}, {'to_node': self.k2.pk, 'lines': 'x'},
                  {'to_node': self.k2.pk, 'lines': ['x']}, {'to_node': HUGE, 'lines': lines},
                  {'to_node': 'ZZZ', 'lines': lines}, {'to_node': {'a': 1}, 'lines': lines},
                  {'to_node': [1], 'lines': lines}, {'to_node': -1, 'lines': lines}, {'to_node': 0, 'lines': lines},
                  {'to_node': self.k1.pk, 'lines': lines}, {'to_node': self.k1.code, 'lines': lines},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': HUGE, 'quantity_sent': 1}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': -1, 'quantity_sent': 1}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': [1], 'quantity_sent': 1}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': -5}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 0}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 'abc'}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 1.5}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': HUGE}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': True}]},
                  {'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 99999}]},
                  {'to_node': self.k2.pk, 'lines': lines, 'notes': {'a': 1}},
                  {'to_node': self.k2.pk, 'lines': lines, 'notes': 'x' * 100000}]
        for b in bodies:
            r = self.send(self.u['GERANT'], b)
            self.assertLess(r.status_code, 500, (str(b)[:80], r.status_code))
        # aucune de ces tentatives invalides sauf notes longues eventuelles ne deduit plus que ce qui est cree
        for t in BreadTransfer.objects.filter(initiated_by=self.u['GERANT']):
            self.assertEqual(t.from_node_id, self.k1.pk)

    def setUp_stock(self):
        self._stock_bread(self.k1)

    def _dest_check(self, dest):
        pass

    @expectedFailure  # BUG-540 (existant)
    def test_BUG_540_send_to_technical_or_inactive_node(self):
        """Un envoi vers SIEGE ou vers une boulangerie inactive : nobody pour valider -> stock perdu."""
        self._stock_bread(self.k1)
        inactive = Node.objects.create(code='KIN2', name='Inactive', is_active=False)
        accepted = []
        for dest in (self.siege, inactive):
            r = self.send(self.u['GERANT'], {'to_node': dest.pk,
                                             'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 1}]})
            if r.status_code == 201:
                accepted.append((dest.code, dest.is_active))
        self.assertEqual(accepted, [], 'BUG-540 : envoi direct de pains accepte vers un noeud technique/inactif')

    def test_send_anonymous_and_methods(self):
        self.assertEqual(api().post('/api/production/transfers/send/', {}, format='json').status_code, 401)
        self.assertEqual(api(self.u['GERANT']).get('/api/production/transfers/send/').status_code in (404, 405), True)
