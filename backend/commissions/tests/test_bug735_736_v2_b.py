"""BUG-735 / BUG-736 : non-regression (Dev B, commissions). Donnees fictives."""
from rest_framework.test import APIClient

from commissions.models import ClientCommission, CommissionPeriod
from commissions.tests.test_concurrence_volumetrie_v2 import _seed_commissions
from core.testing import make_node, make_user
from django.test import TestCase


class Bug735736Tests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.period = CommissionPeriod.objects.create(node=self.k1, month=10, year=2026)
        _seed_commissions(self.k1, self.period, 2)
        self.cm = ClientCommission.objects.filter(period=self.period).first()
        self.api = APIClient(raise_request_exception=False)
        self.api.force_authenticate(make_user('DIRECTION', node=None, username='b735_dir'))

    def test_set_manuel_refuse_sur_commission_payee(self):
        self.api.post(f'/api/commissions/commissions/{self.cm.pk}/mark_paid/', {}, format='json')
        resp = self.api.patch(f'/api/commissions/commissions/{self.cm.pk}/set_manuel/',
                              {'manuel_adjustment': '100'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())

    def test_generate_mois_et_annee_invalides_400_en_francais(self):
        for body in ({'node': self.k1.pk, 'month': 13, 'year': 2026},
                     {'node': self.k1.pk, 'month': 0, 'year': 2026},
                     {'node': self.k1.pk, 'month': 10, 'year': -5},
                     {'node': 'abc', 'month': 10, 'year': 2026}):
            resp = self.api.post('/api/commissions/periods/generate/', body, format='json')
            self.assertEqual(resp.status_code, 400, body)
            self.assertIn('detail', resp.json())
        self.assertFalse(CommissionPeriod.objects.filter(month=13).exists())
