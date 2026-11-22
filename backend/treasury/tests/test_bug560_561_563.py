"""Non-regression BUG-560 (?node= invalide treasury, doublon rapport facturier),
BUG-561 (run_check corps liste), BUG-563 (versements : nœud technique SIEGE).
Donnees fictives uniquement."""
from rest_framework.test import APIClient

from core.models import Node
from core.tests.test_verif_isolation_a_c import IsoBase
from treasury.models import FacturierReport

HUGE = '9' * 30


def api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


class Bug560561563(IsoBase):
    def test_560_invalid_node_param_is_400(self):
        c = api(self.u['DIRECTION'])
        for p in ('/api/treasury/journal/', '/api/treasury/journal/monthly_report/',
                  '/api/treasury/savings/', '/api/treasury/savings/monthly_total/'):
            for raw in ('ZZZ', HUGE, str(2 ** 63)):
                r = c.get(f'{p}?node={raw}')
                self.assertEqual(r.status_code, 400, (p, raw, r.content))
                self.assertIn('detail', r.json(), (p, raw))

    def test_560_valid_node_param_still_works(self):
        c = api(self.u['DIRECTION'])
        for p in ('/api/treasury/journal/', '/api/treasury/journal/monthly_report/',
                  '/api/treasury/savings/', '/api/treasury/savings/monthly_total/'):
            for raw in (str(self.k1.pk),):
                self.assertEqual(c.get(f'{p}?node={raw}').status_code, 200, (p, raw))

    def test_560_duplicate_report_is_400_without_duplicate(self):
        body = {'node': self.k1.pk, 'team': 'B', 'date': '2026-10-30'}
        g = api(self.u['GERANT'])
        first = g.post('/api/treasury/reports/', body, format='json')
        self.assertEqual(first.status_code, 201, first.content)
        r = g.post('/api/treasury/reports/', body, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('detail', r.json())
        self.assertEqual(FacturierReport.objects.filter(node=self.k1, date='2026-10-30').count(), 1)

    def test_561_run_check_non_object_body_is_400(self):
        c = api(self.u['DIRECTION'])
        for body in ([], [1], 'x', 5):
            r = c.post('/api/blockchain/snapshots/run_check/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.content))
        self.assertEqual(c.post('/api/blockchain/snapshots/run_check/', {}, format='json').status_code, 200)

    def test_563_versements_excludes_siege(self):
        siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege', 'is_active': False})[0]
        r = api(self.u['DIRECTION']).get('/api/treasury/closures/versements/?date=2026-11-18')
        self.assertEqual(r.status_code, 200, r.content)
        codes = [x['node_code'] for x in r.data['results']]
        self.assertNotIn('SIEGE', codes)
        self.assertIn(self.k1.code, codes)
        self.assertEqual(r.data['count'], len(codes))
        self.assertTrue(Node.objects.filter(pk=siege.pk).exists())
