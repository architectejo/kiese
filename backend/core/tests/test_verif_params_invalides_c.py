"""Balayage boîte noire (testeur-production, Dev C, 2026-11-22-c4) : paramètres de
requête invalides (`?node=ZZZ`, `?month=abc`, dates illisibles, entiers géants)
sur les endpoints qui lisent un paramètre sans validation évidente.

Règle : un paramètre invalide ne doit JAMAIS produire de 500 (attendu : 400,
ignoré, ou résultat vide), pour un gérant ET pour le siège.
Un test par module : `ECHECS_<module>` liste les (rôle, méthode, url) en 500.
Données fictives uniquement.
"""

from rest_framework.test import APIClient

from core.tests.test_verif_isolation_a_c import IsoBase

HUGE = '99999999999999999999999999'

PROBES = {
    # BUG-526 : dates / mois / année illisibles -> 500 (liste des sessions, flour_history)
    'production_526': [
        ('get', '/api/production/sessions/?date_from=abc'),
        ('get', '/api/production/sessions/?date_to=2026-13-45'),
        ('get', '/api/production/movements/flour_history/?month=abc'),
        ('get', '/api/production/movements/flour_history/?year=abc'),
        ('get', '/api/production/movements/flour_history/?month=13&year=99999'),
    ],
    'production': [
        ('get', '/api/production/sessions/?node=ZZZ'),
        ('get', f'/api/production/sessions/?node={HUGE}'),
        ('get', '/api/production/sessions/reconciliation/?node=ZZZ&date_from=abc'),
        ('get', f'/api/production/sessions/reconciliation/?node={HUGE}'),
        ('get', '/api/production/movements/flour_history/?node=ZZZ'),
        ('get', f'/api/production/movements/flour_history/?node={HUGE}'),
        ('get', '/api/production/movements/?node=ZZZ'),
        ('get', '/api/production/stocks/?node=ZZZ'),
        ('get', f'/api/production/stocks/?node={HUGE}'),
        ('get', '/api/production/counts/?node=ZZZ&count_date=abc'),
        ('get', '/api/production/transfers/?from_node=ZZZ'),
        ('get', '/api/production/disposals/?node=ZZZ'),
        ('get', '/api/production/bread-stocks/?node=ZZZ'),
        ('get', '/api/production/bread-stocks/by-date/?node=ZZZ'),
        ('get', f'/api/production/bread-stocks/by-date/?node={HUGE}&date=abc'),
        ('get', '/api/production/daily-closure/?node=ZZZ&date=2026-11-18'),
        ('get', f'/api/production/daily-closure/?node={HUGE}&date=2026-11-18'),
        ('get', '/api/production/daily-closure/clients/?node=ZZZ&date=2026-11-18&page=abc'),
        ('get', '/api/production/opening-confirmation/?node=ZZZ'),
        ('get', f'/api/production/opening-confirmation/?node={HUGE}'),
    ],
    'sales': [
        ('get', '/api/sales/invoices/bread_summary/?node=ZZZ'),
        ('get', '/api/sales/invoices/bread_summary/?date=abc'),
        ('get', f'/api/sales/invoices/bread_summary/?node={HUGE}'),
        ('get', '/api/sales/invoices/daily_summary/?node=ZZZ'),
        ('get', '/api/sales/invoices/daily_summary/?date=abc'),
        ('get', '/api/sales/invoices/?node=ZZZ'),
    ],
    'finance': [
        ('get', '/api/finance/years/summary/?node=ZZZ'),
        ('get', '/api/finance/years/summary/?year=abc'),
        ('get', '/api/finance/years/summary/?month=abc&year=2026'),
        ('get', '/api/finance/years/doc1_report/?node=ZZZ&month=1&year=2026'),
        ('get', '/api/finance/years/doc1_report/?node=1&month=abc&year=abc'),
        ('get', '/api/finance/years/doc1_export/?node=ZZZ&month=1&year=2026'),
        ('get', '/api/finance/years/doc1_export/?node=1&month=abc&year=abc'),
    ],
    'blockchain': [
        ('get', '/api/blockchain/alerts/?node=ZZZ'),
        ('get', '/api/blockchain/snapshots/?node=ZZZ'),
        ('post', '/api/blockchain/snapshots/run_check/?node=ZZZ'),
        ('post', '/api/blockchain/snapshots/run_check/'),  # corps {"node": "ZZZ"} ajouté ci-dessous
    ],
    'commissions': [
        ('get', '/api/commissions/periods/history/?node=ZZZ'),
        ('get', '/api/commissions/periods/history/?months=abc'),
        ('get', '/api/commissions/periods/?node=ZZZ'),
        ('get', '/api/commissions/commissions/?node=ZZZ'),
        ('get', '/api/commissions/commissions/?period=abc'),
    ],
}


class ParamsInvalides(IsoBase):
    maxDiff = None

    def _client(self, user):
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(user)
        return c

    def sweep(self, module):
        echecs = []
        for role in ('GERANT', 'DIRECTION'):
            c = self._client(self.u[role])
            for method, url in PROBES[module]:
                if method == 'post':
                    r = c.post(url, {'node': 'ZZZ'}, format='json')
                else:
                    r = c.get(url)
                if r.status_code >= 500:
                    echecs.append((role, method, url, r.status_code))
        return echecs

    def test_production_aucun_500(self):
        self.assertEqual(self.sweep('production'), [])

    def test_BUG_526_production_dates_mois_illisibles(self):
        self.assertEqual(self.sweep('production_526'), [])

    def test_BUG_527_sales_aucun_500(self):
        self.assertEqual(self.sweep('sales'), [])

    def test_BUG_528_finance_aucun_500(self):
        self.assertEqual(self.sweep('finance'), [])

    def test_BUG_529_blockchain_aucun_500(self):
        self.assertEqual(self.sweep('blockchain'), [])

    def test_BUG_530_commissions_aucun_500(self):
        self.assertEqual(self.sweep('commissions'), [])
