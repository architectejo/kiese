"""
BUG-114 : `GET /api/treasury/journal/?month=10&year=20000` (liste standard,
`JournalEntryViewSet.get_queryset()`) et
`GET /api/treasury/journal/monthly_report/?month=10&year=20000`
levaient une `ValueError: year 20000 is out of range` (remontée depuis
`django.db.backends.base.operations.year_lookup_bounds_for_date_field` via
`JournalEntry.objects.filter(date__year=year)`), renvoyant un 500 au lieu
d'un 400 propre.

Correctif : `_validate_month_year()` (`treasury/views.py`) valide `month`
(1-12) et `year` (2000-2100) avant tout filtre `date__year=`/`date__month=`,
appliqué aux deux endroits.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user


class JournalYearValidationTests(TestCase):

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant1')
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def test_list_with_out_of_range_year_returns_400_not_500(self):
        resp = self.api.get('/api/treasury/journal/', {'month': '10', 'year': '20000'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_monthly_report_with_out_of_range_year_returns_400_not_500(self):
        resp = self.api.get('/api/treasury/journal/monthly_report/', {'month': '10', 'year': '20000'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_list_with_non_integer_year_returns_400(self):
        resp = self.api.get('/api/treasury/journal/', {'year': 'abc'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_monthly_report_with_non_integer_year_returns_400(self):
        resp = self.api.get('/api/treasury/journal/monthly_report/', {'year': 'abc'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_list_with_out_of_range_month_returns_400(self):
        resp = self.api.get('/api/treasury/journal/', {'month': '13', 'year': '2026'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_monthly_report_with_out_of_range_month_returns_400(self):
        resp = self.api.get('/api/treasury/journal/monthly_report/', {'month': '0', 'year': '2026'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_list_with_valid_year_still_works(self):
        """Non-régression : une valeur plausible n'est pas rejetée."""
        resp = self.api.get('/api/treasury/journal/', {'month': '10', 'year': '2026'})
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_monthly_report_with_valid_year_still_works(self):
        resp = self.api.get('/api/treasury/journal/monthly_report/', {'month': '10', 'year': '2026'})
        self.assertEqual(resp.status_code, 200, resp.content)
