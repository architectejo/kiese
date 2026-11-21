"""Vérification croisée Dev C de BUG-511 : filtres period__month / period__year."""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from commissions.models import ClientCommission, CommissionPeriod
from core.testing import make_node, make_user, make_client

URL = '/api/commissions/commissions/'


class VerifBug511C(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.k1 = make_node('K1')
        cls.k2 = make_node('K2')
        cls.direction = make_user(role='DIRECTION', username='v511_dir')
        cls.g1 = make_user(role='GERANT', node=cls.k1, username='v511_g1')
        cls.cm = {}
        for node in (cls.k1, cls.k2):
            clients = [make_client(node) for _ in range(3)]
            for (m, y) in ((1, 2026), (11, 2026), (12, 2025)):
                p = CommissionPeriod.objects.create(node=node, month=m, year=y)
                for c in clients:
                    cls.cm[(node.code, m, y, c.pk)] = ClientCommission.objects.create(period=p, client=c)

    def get(self, user, qs=''):
        c = APIClient()
        c.force_authenticate(user)
        return c.get(URL + qs)

    def ids(self, user, qs=''):
        r = self.get(user, qs + ('&' if '?' in qs else '?') + 'page_size=500')
        self.assertEqual(r.status_code, 200, r.content)
        return {str(x['id']) for x in r.data['results']}

    def test_invalid_month_string_rejected(self):
        r = self.get(self.direction, '?period__month=abc')
        self.assertEqual(r.status_code, 400, r.content)

    def test_invalid_year_string_rejected(self):
        r = self.get(self.direction, '?period__year=20x6')
        self.assertEqual(r.status_code, 400, r.content)

    def test_out_of_range_returns_empty_not_error(self):
        for qs in ('?period__month=13', '?period__month=0', '?period__year=1900', '?period__month=-1'):
            r = self.get(self.direction, qs)
            self.assertIn(r.status_code, (200, 400), qs)
            if r.status_code == 200:
                self.assertEqual(r.data['count'], 0, qs)

    def test_empty_values_ignored(self):
        self.assertEqual(self.ids(self.direction, '?period__month=&period__year='), self.ids(self.direction))

    def test_no_filter_returns_everything(self):
        self.assertEqual(len(self.ids(self.direction)), len(self.cm))

    def test_month_year_combination_exact(self):
        got = self.ids(self.direction, '?period__month=1&period__year=2026')
        want = {str(v.pk) for k, v in self.cm.items() if k[1:3] == (1, 2026)}
        self.assertEqual(got, want)
        self.assertEqual(len(got), 6)

    def test_month_without_matching_year_empty(self):
        self.assertEqual(self.ids(self.direction, '?period__month=12&period__year=2026'), set())

    def test_filter_union_equals_whole(self):
        union = set()
        for m, y in ((1, 2026), (11, 2026), (12, 2025)):
            union |= self.ids(self.direction, f'?period__month={m}&period__year={y}')
        self.assertEqual(union, self.ids(self.direction))

    def test_isolation_gerant_cannot_reach_other_node_even_when_asked(self):
        got = self.ids(self.g1, f'?period__month=11&period__year=2026&period__node={self.k2.pk}')
        self.assertEqual(got, set())
        got = self.ids(self.g1, '?period__month=11&period__year=2026')
        self.assertEqual(len(got), 3)
        for pk in got:
            self.assertEqual(ClientCommission.objects.get(pk=pk).period.node_id, self.k1.pk)

    def test_page_size_honored_and_total_count_kept(self):
        r = self.get(self.direction, '?period__year=2026&page_size=4')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['results']), 4)
        self.assertEqual(r.data['count'], 12)
        r2 = self.get(self.direction, '?period__year=2026&page_size=4&page=3')
        self.assertEqual(len(r2.data['results']), 4)
        seen = set()
        for p in (1, 2, 3):
            seen |= {x['id'] for x in self.get(self.direction, f'?period__year=2026&page_size=4&page={p}').data['results']}
        self.assertEqual(len(seen), 12)

    def test_no_n_plus_one(self):
        def count(qs):
            with CaptureQueriesContext(connection) as ctx:
                r = self.get(self.direction, qs)
                self.assertEqual(r.status_code, 200)
            return len(ctx)
        count('?period__month=1&period__year=2026&page_size=1')  # échauffement des caches
        small = count('?period__month=1&period__year=2026&page_size=2')
        big = count('?period__month=1&period__year=2026&page_size=6')
        self.assertEqual(small, big, 'le nombre de requêtes dépend de la taille de page (N+1)')
