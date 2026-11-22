"""Non-régression BUG-821/822/824 (ajustement : base de CM, quantités signées, compteur de pains)."""
from decimal import Decimal as D

from commissions.models import ClientCommission
from finance.tests.test_audit_c_cycle1_c import _api
from finance.tests.test_audit_c_cycle2_c import Cycle2Base


class AdjustCounters(Cycle2Base):
    def _generate(self):
        r = _api(self.hq).post('/api/commissions/periods/generate/', {
            'node': self.k1.pk, 'month': self.d1.month, 'year': self.d1.year}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_positive_adjustment_increments_total_breads_received(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, 1, 4)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 14)

    def test_negative_adjustment_never_makes_counter_negative(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.cl.__class__.objects.filter(pk=self.cl.pk).update(total_breads_received=1)
        self.adjust(inv, -1, 3)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 0)

    def test_commission_total_breads_signed_and_regular_sale_still_paid(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_grand, 10)], 5000, 'CASH', self.d1)
        self.adjust(inv, -1, 2)
        self._generate()
        cm = ClientCommission.objects.get(client=self.cl)
        self.assertEqual((cm.total_breads, cm.order_value), (8, D('4000.00')))

    def test_rg_adjustment_excluded_from_commission_base(self):
        inv = self.sale(self.f1, self.cl, [(self.bp_mini, 10)], 0, 'CREDIT', self.d1, code='RG')
        self.adjust(inv, 1, 2, bp=self.bp_mini)
        self._generate()
        self.assertFalse(ClientCommission.objects.filter(client=self.cl).exists())
