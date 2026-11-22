"""BUG-526 a 529 (dev-backend, Dev C pour A) : parametre de requete invalide -> 400
`{"detail": <francais>}`, jamais 500 ; le comportement sans parametre reste intact.
Donnees fictives uniquement."""
from rest_framework.test import APIClient

from core.tests.test_verif_isolation_a_c import IsoBase

HUGE = '99999999999999999999999999'


class ParamsInvalidesA(IsoBase):
    def _c(self, role):
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(self.u[role])
        return c

    def assert400(self, role, method, url, body=None):
        c = self._c(role)
        r = c.post(url, body or {}, format='json') if method == 'post' else c.get(url)
        self.assertEqual(r.status_code, 400, (role, url, r.status_code))
        self.assertIn('detail', r.data, (role, url))
        self.assertIsInstance(str(r.data['detail']), str)

    def both(self, method, url, body=None):
        for role in ('GERANT', 'DIRECTION'):
            self.assert400(role, method, url, body)

    # BUG-526
    def test_526_sessions_dates(self):
        self.both('get', '/api/production/sessions/?date_from=abc')
        self.both('get', '/api/production/sessions/?date_to=2026-13-45')

    def test_526_flour_history_mois_annee(self):
        for q in ('month=abc', 'year=abc', 'month=13&year=99999', f'year={HUGE}', 'month=0'):
            self.both('get', f'/api/production/movements/flour_history/?{q}')

    def test_526_valeurs_valides_inchangees(self):
        for role in ('GERANT', 'DIRECTION'):
            c = self._c(role)
            for url in ('/api/production/sessions/?date_from=2026-01-01&date_to=2026-12-31',
                        '/api/production/sessions/',
                        '/api/production/movements/flour_history/?month=11&year=2026',
                        '/api/production/movements/flour_history/'):
                self.assertEqual(c.get(url).status_code, 200, (role, url))

    # BUG-527
    def test_527_daily_summary_date(self):
        self.both('get', '/api/sales/invoices/daily_summary/?date=abc')
        self.both('get', '/api/sales/invoices/daily_summary/?date=2026-13-45')

    def test_527_daily_summary_valide(self):
        for role in ('GERANT', 'DIRECTION'):
            c = self._c(role)
            self.assertEqual(c.get('/api/sales/invoices/daily_summary/').status_code, 200)
            self.assertEqual(c.get('/api/sales/invoices/daily_summary/?date=2026-11-10').status_code, 200)

    # BUG-528
    def test_528_finance_node_inconnu(self):
        for url in ('/api/finance/years/summary/?node=ZZZ',
                    '/api/finance/years/doc1_report/?node=ZZZ&month=1&year=2026',
                    '/api/finance/years/doc1_export/?node=ZZZ&month=1&year=2026'):
            self.assert400('DIRECTION', 'get', url)

    def test_528_finance_node_valide_par_pk_et_code(self):
        c = self._c('DIRECTION')
        for ref in (str(self.k1.pk), self.k1.code):
            self.assertEqual(c.get(f'/api/finance/years/summary/?year=2026&node={ref}').status_code, 200)
            self.assertEqual(
                c.get(f'/api/finance/years/doc1_report/?node={ref}&month=1&year=2026').status_code, 200)
        self.assertEqual(c.get('/api/finance/years/summary/?year=2026').status_code, 200)

    # BUG-529
    def test_529_blockchain_node_inconnu(self):
        c = self._c('DIRECTION')
        for url in ('/api/blockchain/alerts/?node=ZZZ', '/api/blockchain/snapshots/?node=ZZZ'):
            self.assert400('DIRECTION', 'get', url)
        self.assert400('DIRECTION', 'post', '/api/blockchain/snapshots/run_check/?node=ZZZ')
        self.assert400('DIRECTION', 'post', '/api/blockchain/snapshots/run_check/', {'node': 'ZZZ'})
        self.assert400('DIRECTION', 'get', f'/api/blockchain/alerts/?node={HUGE}x')

    def test_529_blockchain_valide(self):
        c = self._c('DIRECTION')
        self.assertEqual(c.get('/api/blockchain/alerts/').status_code, 200)
        self.assertEqual(c.get(f'/api/blockchain/alerts/?node={self.k1.pk}').status_code, 200)
        self.assertEqual(c.get(f'/api/blockchain/snapshots/?node={self.k1.code}').status_code, 200)
        self.assertEqual(c.post('/api/blockchain/snapshots/run_check/', {}, format='json').status_code, 200)
