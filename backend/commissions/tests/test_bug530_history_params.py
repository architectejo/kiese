"""BUG-530 : periods/history avec parametres invalides -> 400 francais (et non 500)."""
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk

URL = '/api/commissions/periods/history/'


class HistoryParams(Base):
    def setUp(self):
        self.hq_user = mk('bug530_hq', 'DIRECTION', None)

    def hq(self):
        return cl(self.hq_user)

    def test_invalid_node_is_400(self):
        for bad in ('ZZZ', '9' * 40, '0'):
            r = self.hq().get(f'{URL}?node={bad}')
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('detail', r.data)

    def test_invalid_months_is_400(self):
        for bad in ('abc', '0', '-2'):
            r = self.hq().get(f'{URL}?months={bad}')
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('detail', r.data)

    def test_valid_params_ok(self):
        r = self.hq().get(f'{URL}?node={self.k1.pk}&months=6')
        self.assertEqual(r.status_code, 200)
