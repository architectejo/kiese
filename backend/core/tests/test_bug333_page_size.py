"""BUG-333 : `?page_size=` est honoré (plafonné à 500) par la pagination par défaut."""
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user
from kiese.pagination import DeterministicPageNumberPagination


class PageSizeTests(TestCase):
    def setUp(self):
        self.node = make_node(code='PG1')
        for i in range(60):
            make_node(code=f'PZ{i:02d}')
        self.api = APIClient()
        self.api.force_authenticate(make_user(role='ADMIN', node=None))

    def test_page_size_param_honore(self):
        r = self.api.get('/api/core/nodes/', {'page': 1, 'page_size': 2})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.data['results']), 2)
        self.assertGreaterEqual(r.data['count'], 60)

    def test_taille_par_defaut_et_plafond(self):
        r = self.api.get('/api/core/nodes/')
        self.assertEqual(len(r.data['results']), 25)
        self.assertEqual(DeterministicPageNumberPagination.max_page_size, 500)
        self.assertEqual(DeterministicPageNumberPagination.page_size_query_param, 'page_size')
        r = self.api.get('/api/core/nodes/', {'page_size': 100})
        self.assertEqual(len(r.data['results']), min(100, r.data['count']))
