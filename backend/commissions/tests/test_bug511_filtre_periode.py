"""BUG-511 : ClientCommissionViewSet filtrable par period__month et period__year."""
from django.test import TestCase
from rest_framework.test import APIClient

from commissions.models import ClientCommission, CommissionPeriod
from core.testing import make_node, make_user, make_client


class Bug511(TestCase):
    def setUp(self):
        self.k1 = make_node('K1')
        self.k2 = make_node('K2')
        self.direction = make_user(role='DIRECTION', username='b511_dir')
        self.gerant = make_user(role='GERANT', node=self.k1, username='b511_g')
        self.cm = {}
        for node in (self.k1, self.k2):
            c = make_client(node)
            for (m, y) in ((10, 2026), (11, 2026), (11, 2025)):
                p = CommissionPeriod.objects.create(node=node, month=m, year=y)
                self.cm[(node.code, m, y)] = ClientCommission.objects.create(period=p, client=c)

    def ids(self, user, qs):
        c = APIClient()
        c.force_authenticate(user)
        r = c.get('/api/commissions/commissions/' + qs)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        return {str(x['id']) for x in data}

    def test_filter_month_year(self):
        got = self.ids(self.direction, '?period__month=11&period__year=2026')
        self.assertEqual(got, {str(self.cm[('K1', 11, 2026)].pk), str(self.cm[('K2', 11, 2026)].pk)})

    def test_filter_year_only_and_month_only(self):
        self.assertEqual(len(self.ids(self.direction, '?period__year=2025')), 2)
        self.assertEqual(len(self.ids(self.direction, '?period__month=10')), 2)

    def test_combined_with_node(self):
        got = self.ids(self.direction, f'?period__node={self.k2.pk}&period__month=11&period__year=2026')
        self.assertEqual(got, {str(self.cm[('K2', 11, 2026)].pk)})

    def test_scope_node_preserved_for_gerant(self):
        got = self.ids(self.gerant, '?period__month=11&period__year=2026')
        self.assertEqual(got, {str(self.cm[('K1', 11, 2026)].pk)})
