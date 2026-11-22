"""BUG-362 : un compte non-siege SANS boulangerie ne voit rien et ne peut rien ecrire."""
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk

LISTS = [
    '/api/production/sessions/', '/api/production/movements/', '/api/production/stocks/',
    '/api/production/disposals/', '/api/production/transfers/', '/api/production/counts/',
    '/api/treasury/reports/', '/api/treasury/expenses/', '/api/treasury/closures/',
    '/api/sales/invoices/',
]
CREATES = [
    ('/api/production/movements/', {'movement_type': 'ENTRY', 'quantity': '1'}),
    ('/api/production/disposals/', {'disposal_type': 'DECLASSED', 'quantity': 1}),
    ('/api/treasury/reports/', {'date': '2026-11-11'}),
    ('/api/treasury/expenses/', {'description': 'x', 'amount': '10', 'date': '2026-11-21'}),
    ('/api/sales/invoices/', {'lines': []}),
]


class CompteSansBoulangerieTests(Base):
    def test_lists_empty_and_creates_403(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            u = mk(f'nonode_{role.lower()}', role, None)
            c = cl(u)
            for url in LISTS:
                r = c.get(url)
                if r.status_code in (403, 404):
                    continue
                self.assertEqual(r.status_code, 200, (role, url))
                data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
                self.assertEqual(len(data), 0, (role, url))
            for url, body in CREATES:
                r = c.post(url, body, format='json')
                self.assertEqual(r.status_code, 403, (role, url, r.content[:100]))
                self.assertIn('detail', r.data)

    def test_hq_and_node_users_unchanged(self):
        self.assertEqual(cl(self.u['DIRECTION']).get('/api/production/sessions/').status_code, 200)
        r = cl(self.u['GERANT']).get('/api/production/sessions/')
        data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        self.assertEqual({str(x['node']) for x in data}, {str(self.k1.pk)})
