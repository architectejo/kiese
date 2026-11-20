"""Non-regression BUG-313 (node/year forges en PATCH) et BUG-314 (valeurs negatives sur Node)."""
from decimal import Decimal as Dc

from rest_framework.test import APIClient

from clients.models import SocialContribution, SocialDistribution
from core.models import Node
from core.tests.test_permissions_regression_2026_11_19 import Base, cl


class Bug313(Base):
    def test_put_distribution_cannot_change_node(self):
        r = cl(self.u['GERANT']).put(f'/api/clients/distributions/{self.dist1.pk}/',
                                     {'node': self.k2.pk, 'year': 2031, 'tarif': '700'}, format='json')
        self.dist1.refresh_from_db()
        self.assertEqual(self.dist1.node_id, self.k1.pk, r.content)

    def test_contribution_put_and_patch_keep_node(self):
        g = cl(self.u['GERANT'])
        url = f'/api/clients/contributions/{self.contrib1.pk}/'
        g.patch(url, {'node': self.k2.pk, 'amount': '1234'}, format='json')
        self.contrib1.refresh_from_db()
        self.assertEqual(self.contrib1.node_id, self.k1.pk)
        self.assertEqual(self.contrib1.amount, Dc('1234'))  # les autres champs restent modifiables

    def test_closed_distribution_year_frozen(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        r = cl(self.u['GERANT']).patch(f'/api/clients/distributions/{self.dist1.pk}/',
                                       {'year': 2031}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)
        self.dist1.refresh_from_db()
        self.assertEqual(self.dist1.year, 2026)

    def test_hq_can_still_move_node(self):
        r = cl(self.u['DIRECTION']).patch(f'/api/clients/contributions/{self.contrib1.pk}/',
                                          {'node': self.k1.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)


class Bug314(Base):
    def test_negative_sac_value_rejected(self):
        r = cl(self.u['DIRECTION']).patch(f'/api/core/nodes/{self.k1.pk}/',
                                          {'sac_value_fc': '-5'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_zero_contribution_accepted(self):
        r = cl(self.u['DIRECTION']).patch(f'/api/core/nodes/{self.k1.pk}/',
                                          {'monthly_social_contribution': '0'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
