"""
BUG-115 : même défaut que BUG-114 (treasury), repéré sur
`FinancialYearViewSet.doc1_report()` et `.doc1_export()` — `month`/`year`
pris directement depuis la requête et transmis à
`Invoice.objects.filter(invoice_date__month=..., invoice_date__year=...)`
sans validation, ce qui lève une `ValueError` (ex. `year=20000` ou
`year='abc'`) remontée en 500 au lieu d'un 400 propre.

Correctif : réutilisation de `_validate_month_year()`
(`treasury/views.py`, introduite par BUG-114), importée dans
`finance/views.py`, appliquée aux deux endpoints avant tout filtre
`invoice_date__month=`/`invoice_date__year=`.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user


class Doc1ReportMonthYearValidationTests(TestCase):

    def setUp(self):
        self.node = make_node(code='K3', name='K3 - ATHENEE')
        self.admin = make_user(role='ADMIN', node=None, username='admin_bug115')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_doc1_report_with_out_of_range_year_returns_400_not_500(self):
        resp = self.api.get('/api/finance/years/doc1_report/', {
            'node': str(self.node.id), 'month': '10', 'year': '20000',
        })
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_doc1_report_with_non_integer_year_returns_400(self):
        resp = self.api.get('/api/finance/years/doc1_report/', {
            'node': str(self.node.id), 'month': '10', 'year': 'abc',
        })
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_doc1_report_with_out_of_range_month_returns_400(self):
        resp = self.api.get('/api/finance/years/doc1_report/', {
            'node': str(self.node.id), 'month': '13', 'year': '2026',
        })
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_doc1_report_with_valid_year_still_works(self):
        """Non-régression : une valeur plausible n'est pas rejetée (liste vide acceptée)."""
        resp = self.api.get('/api/finance/years/doc1_report/', {
            'node': str(self.node.id), 'month': '10', 'year': '2026',
        })
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_doc1_export_with_out_of_range_year_returns_400_not_500(self):
        resp = self.api.get('/api/finance/years/doc1_export/', {
            'node': str(self.node.id), 'month': '10', 'year': '20000',
        })
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.data)

    def test_doc1_export_with_non_integer_year_returns_400(self):
        resp = self.api.get('/api/finance/years/doc1_export/', {
            'node': str(self.node.id), 'month': '10', 'year': 'abc',
        })
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_doc1_export_with_valid_year_still_works(self):
        resp = self.api.get('/api/finance/years/doc1_export/', {
            'node': str(self.node.id), 'month': '10', 'year': '2026',
        })
        # Réponse CSV en streaming (`StreamingHttpResponse`) : pas de
        # `.content`, seulement `.streaming_content`.
        self.assertEqual(resp.status_code, 200)
