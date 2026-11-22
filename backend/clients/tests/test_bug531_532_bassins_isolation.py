"""BUG-531 (bassins : isolation par noeud) et BUG-532 (?node= entier geant). Donnees fictives."""
from decimal import Decimal as Dc

from commissions.models import ClientCommission, CommissionPeriod
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk

BASSINS = '/api/clients/clients/bassins/'
DEFICIT = '/api/clients/clients/deficit_report/'
HUGE = '9' * 40


class BassinsIsolation(Base):
    def setUp(self):
        for node, client, origin in ((self.k1, self.c1, 'P1'), (self.k2, self.c2, 'P2')):
            p = CommissionPeriod.objects.create(node=node, month=10, year=2026, node_origin=origin)
            ClientCommission.objects.create(
                period=p, client=client, order_value=Dc('100'), commission_gross=Dc('10'),
                node_origin=origin)

    def q(self, node):
        return f'{BASSINS}?node={node}&month=10&year=2026'

    def codes(self, r):
        return {x['client_code'] for x in r.data['rows']}

    def test_gerant_cannot_read_other_node(self):
        r = cl(self.u['GERANT']).get(self.q(self.k2.pk))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.codes(r), {self.c1.code})

    def test_gerant_without_node_param_gets_own_node(self):
        r = cl(self.u['GERANT']).get(f'{BASSINS}?month=10&year=2026')
        self.assertEqual(self.codes(r), {self.c1.code})

    def test_node_less_gerant_gets_empty(self):
        r = cl(mk('bug531_orph', 'GERANT', None)).get(self.q(self.k1.pk))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['rows'], [])

    def test_hq_can_choose_node(self):
        hq = cl(mk('bug531_hq', 'DIRECTION', None))
        self.assertEqual(self.codes(hq.get(self.q(self.k2.pk))), {self.c2.code})

    def test_invalid_and_huge_node_is_400_french(self):
        hq = cl(mk('bug531_hq2', 'DIRECTION', None))
        for bad in ('ZZZ', HUGE, '0', '-3'):
            r = hq.get(self.q(bad))
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('detail', r.data)

    def test_invalid_month_is_400(self):
        hq = cl(mk('bug531_hq3', 'DIRECTION', None))
        r = hq.get(f'{BASSINS}?node={self.k1.pk}&month=abc&year=2026')
        self.assertEqual(r.status_code, 400)

    def test_facturier_refused(self):
        self.assertEqual(cl(self.u['FACTURIER']).get(self.q(self.k1.pk)).status_code, 403)

    def test_deficit_report_huge_node_is_400(self):
        r = cl(mk('bug532_hq', 'DIRECTION', None)).get(f'{DEFICIT}?node={HUGE}')
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)
