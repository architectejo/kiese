"""
Testeur charge/resilience, ronde b2 (2026-11-22) : volumetrie (5 000
commissions) et concurrence (mark_paid / set_manuel / generate) cote
commissions.

NOTE SQLite : `select_for_update()` n'a aucun effet sous SQLite ; la
concurrence est donc SIMULEE de facon deterministe (on insere l'ecriture
concurrente entre la lecture et l'ecriture de la vue), ce qui reproduit
exactement le « lost update » qu'un verrou de ligne empecherait sous
PostgreSQL.

Defaut non corrige = `@expectedFailure` + ticket BUG-7NN. Donnees fictives.
"""
import time
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from commissions.views import ClientCommissionViewSet
from core.testing import make_node, make_user

BIG = 5000


def _seed_commissions(node, period, n):
    clients = [Client(code=f"{node.code}-C{i:05d}", first_name=f"P{i}", last_name=f"N{i % 40}",
                      node=node, node_origin=node.code) for i in range(n)]
    Client.objects.bulk_create(clients, batch_size=500)
    ClientCommission.objects.bulk_create([
        ClientCommission(period=period, client=c, order_value=Decimal('100000.00'),
                         commission_gross=Decimal('25000.00'), deduction_debt=Decimal('1000.00'),
                         net_payable=Decimal('20000.00'), node_origin=node.code)
        for c in clients], batch_size=500)


class CommissionsVolumetryTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.period = CommissionPeriod.objects.create(node=self.k1, month=10, year=2026)
        self.direction = make_user('DIRECTION', node=None, username='v2c_dir')
        self.api = APIClient(raise_request_exception=False)
        self.api.force_authenticate(self.direction)

    def _measure(self, url):
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            resp = self.api.get(url)
            dt = (time.perf_counter() - t0) * 1000
        return resp, len(ctx), dt

    def _compare(self, url, label, cap=12):
        _seed_commissions(self.k1, self.period, 50)
        self._measure(url)  # echauffement : caches de session/Config
        r1, q1, t1 = self._measure(url)
        self.assertEqual(r1.status_code, 200, label)
        # second jeu (codes differents)
        clients = [Client(code=f"K1-D{i:05d}", first_name=f"P{i}", last_name=f"N{i % 40}",
                          node=self.k1, node_origin='K1') for i in range(BIG - 50)]
        Client.objects.bulk_create(clients, batch_size=500)
        ClientCommission.objects.bulk_create([
            ClientCommission(period=self.period, client=c, order_value=Decimal('90000.00'),
                             commission_gross=Decimal('22500.00'), net_payable=Decimal('20000.00'),
                             node_origin='K1') for c in clients], batch_size=500)
        r2, q2, t2 = self._measure(url)
        self.assertEqual(r2.status_code, 200, label)
        print(f"PERF {label}: requetes {q1}->{q2}, {t1:.0f} ms -> {t2:.0f} ms, {len(r2.content) / 1024:.0f} Ko")
        self.assertEqual(q1, q2, f"N+1 sur {label}: {q1} -> {q2}")
        self.assertLessEqual(q2, cap, label)
        return r2

    def test_liste_commissions_page_500(self):
        r = self._compare(f'/api/commissions/commissions/?period={self.period.pk}&page_size=500', 'commissions list p500')
        self.assertEqual(r.data['count'], BIG)
        self.assertEqual(len(r.data['results']), 500)

    def test_recherche_commissions(self):
        self._compare(f'/api/commissions/commissions/?period={self.period.pk}&search=N7&page_size=100',
                      'commissions search')

    def test_summary_totaux_verticaux(self):
        r = self._compare(f'/api/commissions/commissions/summary/?period={self.period.pk}', 'commissions summary', cap=4)
        self.assertEqual(r.data['count'], BIG)
        self.assertEqual(Decimal(r.data['total_cm']), Decimal('25000.00') * 50 + Decimal('22500.00') * (BIG - 50))

    def test_payroll_listing_pas_de_n_plus_1(self):
        r = self._compare(f'/api/commissions/commissions/payroll_listing/?period={self.period.pk}', 'payroll_listing')
        self.assertEqual(len(r.data), BIG)

    @expectedFailure  # BUG-734
    def test_payroll_listing_est_borne(self):
        _seed_commissions(self.k1, self.period, BIG)
        resp = self.api.get(f'/api/commissions/commissions/payroll_listing/?period={self.period.pk}')
        body = resp.data
        count = len(body['results']) if isinstance(body, dict) and 'results' in body else len(body)
        self.assertLessEqual(count, 500)

    def test_history_periodes(self):
        url = f'/api/commissions/periods/history/?node={self.k1.pk}'
        _seed_commissions(self.k1, self.period, 20)
        self._measure(url)
        _, q_small, _ = self._measure(url)
        clients = [Client(code=f"K1-H{i:05d}", first_name='P', last_name='N', node=self.k1, node_origin='K1')
                   for i in range(1000)]
        Client.objects.bulk_create(clients, batch_size=500)
        ClientCommission.objects.bulk_create([
            ClientCommission(period=self.period, client=c, order_value=Decimal('1000.00'), node_origin='K1')
            for c in clients], batch_size=500)
        resp, q_big, _ = self._measure(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(q_small, q_big)

    def test_filtres_hostiles_jamais_500(self):
        _seed_commissions(self.k1, self.period, 100)
        for qs in ('period=abc', 'period=-1', 'period__node=zzz', 'period__month=13', 'period__year=abc',
                   'is_paid=maybe', 'client=not-a-uuid', 'page_size=0', 'page=999', 'ordering=net_payable',
                   'ordering=__class__', 'search=%27%20OR%201=1--'):
            resp = self.api.get('/api/commissions/commissions/?' + qs)
            self.assertLess(resp.status_code, 500, qs)


class CommissionsConcurrencyTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.period = CommissionPeriod.objects.create(node=self.k1, month=10, year=2026)
        _seed_commissions(self.k1, self.period, 3)
        self.cm = ClientCommission.objects.filter(period=self.period).first()
        self.direction = make_user('DIRECTION', node=None, username='v2c_dir2')
        self.api = APIClient(raise_request_exception=False)
        self.api.force_authenticate(self.direction)

    def test_double_mark_paid_sequentiel_refuse(self):
        url = f'/api/commissions/commissions/{self.cm.pk}/mark_paid/'
        self.assertEqual(self.api.post(url, {}, format='json').status_code, 200)
        second = self.api.post(url, {}, format='json')
        self.assertEqual(second.status_code, 400)

    def test_mark_paid_verrouille_la_commission(self):
        calls = []
        original = QuerySet.select_for_update

        def spy(qs, *a, **kw):
            calls.append(qs.model.__name__)
            return original(qs, *a, **kw)

        with patch.object(QuerySet, 'select_for_update', spy):
            self.api.post(f'/api/commissions/commissions/{self.cm.pk}/mark_paid/', {}, format='json')
        self.assertIn('ClientCommission', calls)

    def test_set_manuel_concurrent_d_un_paiement_ne_modifie_pas_une_commission_payee(self):
        # Entre le controle `_locked_response` (commission non payee) et l'ecriture,
        # un autre utilisateur marque la commission payee : l'ajustement manuel ne doit
        # pas ecraser le net deja verse.
        net_before = ClientCommission.objects.get(pk=self.cm.pk).net_payable
        real_locked = ClientCommissionViewSet._locked_response

        def racing(commission):
            result = real_locked(commission)
            ClientCommission.objects.filter(pk=commission.pk).update(is_paid=True)  # paiement concurrent
            return result

        with patch.object(ClientCommissionViewSet, '_locked_response', staticmethod(racing)):
            self.api.patch(f'/api/commissions/commissions/{self.cm.pk}/set_manuel/',
                           {'manuel_adjustment': '-500000'}, format='json')
        after = ClientCommission.objects.get(pk=self.cm.pk)
        self.assertTrue(after.is_paid)
        self.assertEqual(after.net_payable, net_before, "net a payer modifie sur une commission payee")

    def test_generate_deux_fois_ne_duplique_pas_les_commissions(self):
        hq = self.api
        n_before = ClientCommission.objects.filter(period=self.period).count()
        for _ in range(2):
            resp = hq.post('/api/commissions/periods/generate/',
                           {'node': self.k1.pk, 'month': 10, 'year': 2026}, format='json')
            self.assertLess(resp.status_code, 500)
        self.assertEqual(ClientCommission.objects.filter(period=self.period).count(), n_before)
        self.assertEqual(CommissionPeriod.objects.filter(node=self.k1, month=10, year=2026).count(), 1)

    def test_generate_parametres_hostiles_jamais_500(self):
        bodies = ({'node': 'abc', 'month': 10, 'year': 2026}, {'node': self.k1.pk, 'month': 13, 'year': 2026},
                  {'node': self.k1.pk, 'month': 'x', 'year': 2026}, {'node': self.k1.pk, 'month': 10, 'year': -5},
                  {'node': [1], 'month': 10, 'year': 2026}, {'node': self.k1.pk, 'month': 0, 'year': 2026})
        codes = []
        for body in bodies:
            resp = self.api.post('/api/commissions/periods/generate/', body, format='json')
            codes.append(resp.status_code)
        print('PERF generate hostile -> statuts', codes)
        self.assertLess(max(codes), 500, codes)
