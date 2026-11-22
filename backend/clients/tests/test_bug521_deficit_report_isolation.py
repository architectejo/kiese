"""BUG-521 : `deficit_report` doit etre borne au noeud de l'appelant. Donnees fictives."""
from decimal import Decimal as Dc

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk

URL = '/api/clients/clients/deficit_report/'


class DeficitReportIsolation(Base):
    def setUp(self):
        for node, client, origin in ((self.k1, self.c1, 'P1'), (self.k2, self.c2, 'P2')):
            p = CommissionPeriod.objects.create(node=node, month=10, year=2026, node_origin=origin)
            ClientCommission.objects.create(
                period=p, client=client, order_value=Dc('100'), commission_gross=Dc('10'),
                node_origin=origin)
            Client.objects.filter(pk=client.pk).update(current_debt=Dc('90000'))

    def codes(self, r):
        return {x['client_code'] for x in r.data}

    def test_gerant_sees_only_own_node_even_with_node_param(self):
        for q in ('', f'?node={self.k2.pk}'):
            r = cl(self.u['GERANT']).get(URL + q)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(self.codes(r), {self.c1.code}, q)

    def test_facturier_and_livreur_refused(self):
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).get(URL).status_code, 403, role)

    def test_node_less_gerant_gets_empty(self):
        r = cl(mk('bug521_orph', 'GERANT', None)).get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.data), [])

    def test_invalid_node_param_is_400_french_for_hq(self):
        r = cl(mk('bug521_hq', 'DIRECTION', None)).get(URL + '?node=P2')
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)

    def test_hq_can_filter_by_node(self):
        hq = cl(mk('bug521_hq2', 'DIRECTION', None))
        self.assertEqual(self.codes(hq.get(URL + f'?node={self.k2.pk}')), {self.c2.code})
        self.assertEqual(self.codes(hq.get(URL + f'?node={self.k1.pk}')), {self.c1.code})
