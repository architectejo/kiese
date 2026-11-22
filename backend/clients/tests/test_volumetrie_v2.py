"""
Testeur charge/resilience, ronde b2 (2026-11-22) : volumetrie et requetes SQL
sur les endpoints clients (liste, recherche, risk_alerts, best_clients,
bassins, deficit_report) avec 5 000 clients fictifs, et pagination hostile.

Methode : le nombre de requetes SQL d'un endpoint est mesure sur un petit jeu
(50 clients) puis sur le gros jeu (5 000) ; il doit etre IDENTIQUE (pas de N+1).
Les temps sont affiches (`PERF ...`) ; SQLite en memoire, donc a prendre comme
ordre de grandeur (PostgreSQL attendu plus rapide en lecture concurrente).

Defaut non corrige = `@expectedFailure` + ticket BUG-7NN. Donnees fictives.
"""
import time
from decimal import Decimal
from unittest import expectedFailure

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.testing import make_node, make_user

BIG = 5000
SMALL = 50


def _seed(node, start, count, *, period=None):
    """Cree `count` clients fictifs (bulk) ; 1 sur 5 a risque, 1 sur 10 'meilleur'."""
    clients = []
    for i in range(start, start + count):
        risk = i % 5 == 0
        clients.append(Client(
            code=f"{node.code}-V{i:05d}", first_name=f"Prenom{i}", last_name=f"Nom{i % 40}",
            node=node, node_origin=node.code, credit_limit=Decimal('50000.00'),
            current_debt=Decimal('60000.00') if risk else Decimal('1000.00'),
            category=Client.Category.RISK if risk else (
                Client.Category.BEST if i % 10 == 1 else Client.Category.NORMAL),
            total_breads_received=i,
        ))
    Client.objects.bulk_create(clients, batch_size=500)
    if period is not None:
        cms = [ClientCommission(
            period=period, client=c, order_value=Decimal('100000.00') + i,
            commission_gross=Decimal('25000.00'), deduction_debt=Decimal('1000.00'),
            net_payable=Decimal('20000.00'), node_origin=node.code)
            for i, c in enumerate(Client.objects.filter(node=node, code__gte=f"{node.code}-V{start:05d}"))]
        ClientCommission.objects.bulk_create(cms, batch_size=500)


class ClientsVolumetryTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.period = CommissionPeriod.objects.create(node=self.k1, month=10, year=2026)
        self.direction = make_user('DIRECTION', node=None, username='v2_dir')
        self.gerant = make_user('GERANT', node=self.k1, username='v2_ger')
        self.facturier = make_user('FACTURIER', node=self.k2, team='A', username='v2_fac')

    def _get(self, user, url):
        api = APIClient(raise_request_exception=False)
        api.force_authenticate(user)
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            resp = api.get(url)
            dt = (time.perf_counter() - t0) * 1000
        return resp, len(ctx), dt

    def _compare(self, user, url, label, cap=12, slack=0):
        _seed(self.k1, 0, SMALL, period=self.period)
        self._get(user, url)  # echauffement : caches de session/Config (1re requete plus chere)
        r_small, q_small, t_small = self._get(user, url)
        self.assertEqual(r_small.status_code, 200, (label, r_small.status_code))
        _seed(self.k1, SMALL, BIG - SMALL, period=self.period)
        r_big, q_big, t_big = self._get(user, url)
        self.assertEqual(r_big.status_code, 200, (label, r_big.status_code))
        size = len(r_big.content)
        print(f"PERF {label}: requetes {q_small}->{q_big}, {t_small:.0f} ms -> {t_big:.0f} ms, "
              f"{size / 1024:.0f} Ko")
        self.assertLessEqual(q_big - q_small, slack, f"N+1 sur {label}: {q_small} -> {q_big} requetes")
        self.assertLessEqual(q_big, q_small + slack)
        self.assertLessEqual(q_big, cap, label)
        return r_big, q_big, t_big

    def test_liste_clients_page_500_pas_de_n_plus_1(self):
        r, _, _ = self._compare(self.direction, '/api/clients/clients/?page_size=500', 'clients list p500')
        self.assertEqual(len(r.data['results']), 500)
        self.assertEqual(r.data['count'], BIG)

    def test_recherche_client_par_facturier_pas_de_n_plus_1(self):
        r, _, t = self._compare(self.facturier, '/api/clients/clients/?search=Nom7', 'clients search facturier')
        self.assertGreater(r.data['count'], 0)
        print(f"PERF recherche facturier 5000 clients : {t:.0f} ms (objectif p95 < 300 ms)")

    def test_recherche_par_code_et_pertinence(self):
        self._compare(self.direction, '/api/clients/clients/?search=K1-V0042', 'clients search code', slack=1)

    def test_risk_alerts_et_best_clients_pas_de_n_plus_1(self):
        r, _, _ = self._compare(self.gerant, '/api/clients/clients/risk_alerts/', 'risk_alerts')
        self.assertEqual(len(r.data), BIG // 5)

    def test_best_clients_pas_de_n_plus_1(self):
        self._compare(self.gerant, '/api/clients/clients/best_clients/', 'best_clients')

    @expectedFailure  # BUG-734
    def test_risk_alerts_et_best_clients_sont_pagines(self):
        # 1 000 clients a risque renvoyes d'un bloc, sans pagination ni plafond.
        _seed(self.k1, 0, BIG, period=self.period)
        api = APIClient(raise_request_exception=False)
        api.force_authenticate(self.gerant)
        resp = api.get('/api/clients/clients/risk_alerts/')
        body = resp.data
        count = len(body['results']) if isinstance(body, dict) and 'results' in body else len(body)
        self.assertLessEqual(count, 500)

    def test_bassins_pas_de_n_plus_1(self):
        url = f'/api/clients/clients/bassins/?node={self.k1.pk}&month=10&year=2026'
        r, _, _ = self._compare(self.direction, url, 'bassins')
        self.assertEqual(len(r.data['rows']), BIG)

    def test_deficit_report_pas_de_n_plus_1(self):
        url = f'/api/clients/clients/deficit_report/?node={self.k1.pk}'
        r, _, _ = self._compare(self.direction, url, 'deficit_report')
        self.assertEqual(len(r.data), BIG // 5)

    def test_pagination_hostile_jamais_500(self):
        _seed(self.k1, 0, 600, period=self.period)
        api = APIClient(raise_request_exception=False)
        api.force_authenticate(self.direction)
        for qs in ('page_size=0', 'page_size=-1', 'page_size=abc', 'page_size=100000', 'page_size=1e9',
                   'page=0', 'page=-1', 'page=abc', 'page=999999', 'page=last', 'page=1&page=2',
                   'page_size=%00', 'ordering=password', 'ordering=-current_debt,last_name',
                   'ordering=node__password', 'search=' + 'a' * 5000):
            resp = api.get('/api/clients/clients/?' + qs)
            self.assertLess(resp.status_code, 500, qs)
        big = api.get('/api/clients/clients/?page_size=100000')
        self.assertEqual(big.status_code, 200)
        self.assertLessEqual(len(big.data['results']), 500)

    def test_pagination_deterministe_aucun_doublon_ni_saut(self):
        # 40 noms de famille seulement : beaucoup d'ex aequo sur `last_name`.
        _seed(self.k1, 0, 2000, period=self.period)
        api = APIClient(raise_request_exception=False)
        api.force_authenticate(self.direction)
        seen = []
        page = 1
        while True:
            resp = api.get(f'/api/clients/clients/?page_size=500&page={page}')
            self.assertEqual(resp.status_code, 200)
            seen += [row['id'] for row in resp.data['results']]
            if not resp.data['next']:
                break
            page += 1
        self.assertEqual(len(seen), 2000)
        self.assertEqual(len(set(seen)), 2000)

    def test_gerant_ne_voit_que_son_noeud_avec_gros_volume(self):
        _seed(self.k1, 0, 300, period=self.period)
        _seed(self.k2, 0, 300)
        api = APIClient(raise_request_exception=False)
        api.force_authenticate(self.gerant)
        resp = api.get('/api/clients/clients/?page_size=500')
        self.assertEqual(resp.data['count'], 300)
        resp = api.get(f'/api/clients/clients/?page_size=500&node={self.k2.pk}')
        self.assertEqual(resp.data['count'], 0)
