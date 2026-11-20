"""
BUG-327 (remarque.md l.447) : `GET /api/production/daily-closure/clients/`
(liste du jour des clients servis pour la boîte modale de la Clôture
journalière). Données entièrement fictives ; factures créées via l'ORM.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_client
from sales.models import Invoice

URL = '/api/production/daily-closure/clients/'
DAY = date(2026, 10, 14)
OTHER = date(2026, 10, 15)


def _aware(d, hour=10):
    return timezone.make_aware(datetime(d.year, d.month, d.day, hour, 0), timezone.get_current_timezone())


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class _Base(TestCase):
    _seq = 0

    def setUp(self):
        self.node = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.gerant = make_user('GERANT', node=self.node)
        self.api = _api(self.gerant)
        self.alice = make_client(self.node, last_name='Alpha', first_name='Anne', current_debt=Decimal('7000'))
        self.bob = make_client(self.node, last_name='Beta', first_name='Bob', current_debt=Decimal('-500'))

    def inv(self, client, order='1000', paid='0', before='0', hour=10, day=DAY, status=Invoice.Status.DELIVERED,
            node=None, team='A', rate='0.25', **kw):
        _Base._seq += 1
        node = node or self.node
        delivered = _aware(day, hour) if status == Invoice.Status.DELIVERED else None
        return Invoice.objects.create(
            node=node, node_origin=node.code, client=client, team=team, status=status,
            order_total=Decimal(order), payment_amount=Decimal(paid), debt_before=Decimal(before),
            debt_after=Decimal(before) + Decimal(order) - Decimal(paid), commission_rate=Decimal(rate),
            invoice_date=day, delivered_at=delivered, receipt_number=f'T327-{_Base._seq}', **kw)

    def get(self, api=None, **params):
        params.setdefault('date', str(DAY))
        return (api or self.api).get(URL, params)


class ContenuTests(_Base):
    def test_tours_totaux_commission_bp_et_tri(self):
        self.inv(self.bob, '2000', '2000', before='-500', hour=9)
        self.inv(self.alice, '10000', '4000', before='1000', hour=8)
        self.inv(self.alice, '6000', '6000', before='7000', hour=12)
        r = self.get()
        self.assertEqual(r.status_code, 200, r.data)
        rows = r.data['results']
        self.assertEqual([x['client_name'] for x in rows], ['Anne Alpha', 'Bob Beta'])  # tri par nom
        a, b = rows
        self.assertEqual(a['client_code'], self.alice.code)
        self.assertEqual(a['tours'], 2)
        self.assertEqual(a['order_value'], Decimal('16000.00'))
        self.assertEqual(a['paid'], Decimal('10000.00'))
        self.assertEqual(a['commission'], Decimal('4000.00'))  # 16000 x 0,25
        self.assertEqual(a['bp_before'], Decimal('1000.00'))  # première facture du jour
        self.assertEqual(a['bp_current'], Decimal('7000.00'))  # client.current_debt
        self.assertEqual(a['sale_types'], ['REGULIER'])
        self.assertEqual(b['bp_before'], Decimal('-500.00'))
        self.assertEqual(b['bp_current'], Decimal('-500.00'))
        t = r.data['totals']
        self.assertEqual(t, {'clients': 2, 'tours': 3, 'order_value': Decimal('18000.00'),
                             'paid': Decimal('12000.00'), 'commission': Decimal('4500.00')})
        self.assertEqual(r.data['non_servis'], {'count': 0, 'results': []})

    def test_solde_cash_epargne_remboursement(self):
        self.inv(self.alice, '4000', '4000', is_soldee=True, rate='0.00')
        self.inv(self.alice, '2000', '2000', commission_exempt=True, rate='0.25')
        self.inv(self.bob, '0', '5000', before='-500')  # épargne : commande 0, paiement = dépôt
        self.inv(self.bob, '0', '1000', before='-5500', is_debt_repayment=True, rate='0.00')
        rows = {x['client_name']: x for x in self.get().data['results']}
        a, b = rows['Anne Alpha'], rows['Bob Beta']
        self.assertEqual(a['commission'], Decimal('0.00'))
        self.assertEqual(a['order_value'], Decimal('6000.00'))
        self.assertEqual(a['sale_types'], ['SOLDE', 'CASH'])
        self.assertEqual(b['sale_types'], ['EPARGNE', 'REMBOURSEMENT'])
        self.assertEqual(b['tours'], 1)  # le remboursement n'est pas un tour
        self.assertEqual(b['order_value'], Decimal('0.00'))
        self.assertEqual(b['paid'], Decimal('6000.00'))  # dépôt + remboursement encaissés
        self.assertEqual(b['commission'], Decimal('0.00'))

    def test_non_servi_compte_a_part(self):
        self.inv(self.alice, '3000', '0', hour=9)
        ns = self.inv(self.bob, '0', '0', status=Invoice.Status.NOT_SERVED)
        Invoice.objects.filter(pk=ns.pk).update(not_served_at=_aware(DAY, 11))
        self.inv(self.bob, '5000', '0', status=Invoice.Status.PENDING, special_code='NS')
        r = self.get()
        self.assertEqual([x['client_name'] for x in r.data['results']], ['Anne Alpha'])
        self.assertEqual(r.data['totals']['clients'], 1)
        self.assertEqual(r.data['totals']['order_value'], Decimal('3000.00'))
        self.assertEqual(r.data['non_servis']['count'], 2)
        self.assertEqual(r.data['non_servis']['results'][0]['client_name'], 'Bob Beta')
        self.assertNotIn('order_value', r.data['non_servis']['results'][0])

    def test_pending_annule_et_autre_jour_exclus(self):
        self.inv(self.alice, '1000', status=Invoice.Status.PENDING)
        self.inv(self.alice, '1000', status=Invoice.Status.CANCELLED)
        self.inv(self.alice, '1000', day=OTHER)
        r = self.get()
        self.assertEqual(r.data['results'], [])
        self.assertEqual(r.data['totals']['tours'], 0)
        self.assertEqual(self.get(date=str(OTHER)).data['totals']['tours'], 1)

    def test_filtre_equipe(self):
        self.inv(self.alice, '1000', team='A')
        self.inv(self.bob, '2000', team='B')
        r = self.get(team='B')
        self.assertEqual([x['client_name'] for x in r.data['results']], ['Bob Beta'])
        self.assertEqual(r.data['team'], 'B')
        self.assertEqual(self.get().data['totals']['clients'], 2)
        self.assertEqual(self.get(team='Z').status_code, 400)

    def test_pagination(self):
        self.inv(self.alice, '1000')
        self.inv(self.bob, '1000')
        r = self.get(page_size=1, page=2)
        self.assertEqual(len(r.data['results']), 1)
        self.assertEqual(r.data['results'][0]['client_name'], 'Bob Beta')
        self.assertEqual(r.data['count'], 2)
        self.assertEqual(r.data['totals']['clients'], 2)  # totaux sur l'ensemble
        self.assertEqual(self.get(page_size='x').status_code, 400)


class NoeudEtRolesTests(_Base):
    def test_isolation_noeud_gerant(self):
        other_client = make_client(self.k2, last_name='Zeta')
        self.inv(other_client, '9000', node=self.k2)
        self.inv(self.alice, '1000')
        # un gérant K1 qui demande K2 ne voit que K1
        r = self.get(node='K2')
        self.assertEqual([x['client_name'] for x in r.data['results']], ['Anne Alpha'])
        self.assertEqual(r.data['node'], 'K1')

    def test_direction_choisit_le_noeud(self):
        other_client = make_client(self.k2, last_name='Zeta', first_name='Zoe')
        self.inv(other_client, '9000', node=self.k2)
        self.inv(self.alice, '1000')
        d = _api(make_user('DIRECTION', node=None))
        r = self.get(d, node='K2')
        self.assertEqual([x['client_name'] for x in r.data['results']], ['Zoe Zeta'])
        r = self.get(d)
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)
        self.assertEqual(self.get(d, node='ZZ').status_code, 400)

    def test_comptable_autorise_facturier_livreur_refuses(self):
        c = _api(make_user('COMPTABLE', node=None))
        self.assertEqual(self.get(c, node='K1').status_code, 200)
        for role in ('FACTURIER', 'LIVREUR'):
            r = self.get(_api(make_user(role, node=self.node)))
            self.assertEqual(r.status_code, 403, role)
        anon = APIClient().get(URL, {'date': str(DAY)})
        self.assertIn(anon.status_code, (401, 403))

    def test_date_requise_et_invalide(self):
        r = self.api.get(URL)
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)
        self.assertEqual(self.get(date='pas-une-date').status_code, 400)


class PerformanceTests(_Base):
    def test_nombre_de_requetes_constant(self):
        def count_for(n):
            from django.db import connection
            from django.test.utils import CaptureQueriesContext
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.get().status_code, 200)
            return len(ctx)
        self.inv(self.alice, '1000')
        count_for(1)  # échauffement (caches)
        base = count_for(1)
        self.assertLessEqual(base, 4)
        for i in range(8):
            c = make_client(self.node, last_name=f'N{i}')
            self.inv(c, '1000')
            self.inv(c, '500')
        self.assertEqual(count_for(9), base)
