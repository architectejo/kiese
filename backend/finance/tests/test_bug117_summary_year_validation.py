"""
BUG-117 : même défaut que BUG-114/115 (treasury/finance) — mais ici repéré
sur `FinancialYearViewSet.summary()`, qui faisait
`int(request.query_params.get('year', ...))` directement, sans aucune
protection. Un paramètre `year` non numérique (ex. `year='abc'`) ou hors
bornes levait une `ValueError` non rattrapée, remontée en 500 au lieu d'un
400 propre.

Correctif : réutilisation de `_validate_month_year(None, year)`
(`treasury/views.py`, introduite par BUG-114) — `month=None` signifie
« aucun filtre mois demandé », donc seul `year` est validé (bornes
2000-2100), sans dupliquer de logique de validation.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user


class SummaryYearValidationTests(TestCase):

    def setUp(self):
        self.node = make_node(code='K3', name='K3 - ATHENEE')
        self.admin = make_user(role='ADMIN', node=None, username='admin_bug117')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_summary_with_non_integer_year_returns_400_not_500(self):
        resp = self.api.get('/api/finance/years/summary/', {'year': 'abc'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_summary_with_out_of_range_year_returns_400(self):
        resp = self.api.get('/api/finance/years/summary/', {'year': '20000'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_summary_with_valid_year_still_works(self):
        """Non-régression : une valeur plausible n'est pas rejetée (liste vide acceptée)."""
        resp = self.api.get('/api/finance/years/summary/', {'year': '2026'})
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_summary_without_year_param_defaults_to_current_year(self):
        """Non-régression : l'absence de `year` doit toujours utiliser l'année courante."""
        resp = self.api.get('/api/finance/years/summary/')
        self.assertEqual(resp.status_code, 200, resp.content)
