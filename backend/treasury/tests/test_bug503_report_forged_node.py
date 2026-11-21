"""BUG-503 : POST /api/treasury/reports/ avec `node` forge."""
from core.tests.test_permissions_regression_2026_11_19 import Base, cl
from treasury.models import FacturierReport


class ReportForgedNodeTests(Base):
    def body(self, **kw):
        b = {'date': '2026-11-11', 'total_cash_sales': '1000', 'total_credit_sales': '0'}
        b.update(kw)
        return b

    def test_non_hq_forged_node_never_creates_for_other_node(self):
        for user, other in ((self.u['GERANT'], self.k2), (self.u2['GERANT'], self.k1)):
            n0 = FacturierReport.objects.filter(node=other).count()
            r = cl(user).post('/api/treasury/reports/', self.body(node=other.pk), format='json')
            self.assertEqual(FacturierReport.objects.filter(node=other).count(), n0, r.content)
            if r.status_code == 201:
                self.assertEqual(r.data['node'], user.node_id)

    def test_own_node_ok_with_or_without_node(self):
        r = cl(self.u['GERANT']).post('/api/treasury/reports/', self.body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['node'], self.k1.pk)
        r = cl(self.u['GERANT']).post('/api/treasury/reports/', self.body(node=self.k1.pk, date='2026-11-12'),
                                      format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_hq_can_target_any_node_and_needs_one(self):
        r = cl(self.u['DIRECTION']).post('/api/treasury/reports/', self.body(node=self.k2.pk), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['node'], self.k2.pk)
        r = cl(self.u['DIRECTION']).post('/api/treasury/reports/', self.body(date='2026-11-13'), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertTrue('detail' in r.data or 'node' in r.data)

    def test_facturier_livreur_forged_and_anonymous(self):
        n0 = FacturierReport.objects.filter(node=self.k2).count()
        for role in ('FACTURIER', 'LIVREUR'):
            cl(self.u[role]).post('/api/treasury/reports/', self.body(node=self.k2.pk), format='json')
        self.assertEqual(FacturierReport.objects.filter(node=self.k2).count(), n0)
        self.assertEqual(cl().post('/api/treasury/reports/', self.body(), format='json').status_code, 401)
