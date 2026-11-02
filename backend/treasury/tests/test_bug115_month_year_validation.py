"""
BUG-115 : même défaut que BUG-114 (voir `test_bug114_journal_year_validation.py`),
mais sur d'autres points de filtrage `date__year=`/`date__month=` non
validés, repérés en marge de BUG-114 :

- `GET /api/treasury/expenses/?year=20000` (`LocalExpenseViewSet.get_queryset()`)
- `GET /api/treasury/savings/?year=20000` (`DailySavingsViewSet.get_queryset()`)
- `GET /api/treasury/savings/monthly_total/?year=20000`
  (`DailySavingsViewSet.monthly_total()`)

levaient (ou pouvaient lever) une `ValueError: year 20000 is out of range`
remontée en 500 au lieu d'un 400 propre.

Correctif : réutilisation de `_validate_month_year()` (`treasury/views.py`,
introduite par BUG-114) aux trois endroits, avant tout filtre
`date__year=`/`date__month=`.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user


class LocalExpenseYearValidationTests(TestCase):

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_bug115_a')
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def test_list_with_out_of_range_year_returns_400_not_500(self):
        resp = self.api.get('/api/treasury/expenses/', {'month': '10', 'year': '20000'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_list_with_non_integer_year_returns_400(self):
        resp = self.api.get('/api/treasury/expenses/', {'year': 'abc'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_list_with_out_of_range_month_returns_400(self):
        resp = self.api.get('/api/treasury/expenses/', {'month': '13', 'year': '2026'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_list_with_valid_year_still_works(self):
        """Non-régression : une valeur plausible n'est pas rejetée."""
        resp = self.api.get('/api/treasury/expenses/', {'month': '10', 'year': '2026'})
        self.assertEqual(resp.status_code, 200, resp.content)


class DailySavingsYearValidationTests(TestCase):

    def setUp(self):
        self.node = make_node(code='K2', name='K2 - COQ')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_bug115_b')
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def test_list_with_out_of_range_year_returns_400_not_500(self):
        resp = self.api.get('/api/treasury/savings/', {'month': '10', 'year': '20000'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_list_with_non_integer_year_returns_400(self):
        resp = self.api.get('/api/treasury/savings/', {'year': 'abc'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_list_with_out_of_range_month_returns_400(self):
        resp = self.api.get('/api/treasury/savings/', {'month': '0', 'year': '2026'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_list_with_valid_year_still_works(self):
        resp = self.api.get('/api/treasury/savings/', {'month': '10', 'year': '2026'})
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_monthly_total_with_out_of_range_year_returns_400_not_500(self):
        resp = self.api.get('/api/treasury/savings/monthly_total/', {'month': '10', 'year': '20000'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_monthly_total_with_non_integer_year_returns_400(self):
        resp = self.api.get('/api/treasury/savings/monthly_total/', {'year': 'abc'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_monthly_total_with_out_of_range_month_returns_400(self):
        resp = self.api.get('/api/treasury/savings/monthly_total/', {'month': '13', 'year': '2026'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_monthly_total_with_valid_year_still_works(self):
        resp = self.api.get('/api/treasury/savings/monthly_total/', {'month': '10', 'year': '2026'})
        self.assertEqual(resp.status_code, 200, resp.content)
