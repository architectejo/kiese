"""Non-régression BUG-524 (recompute_cump, entrées de même instant sur stock négatif)
et BUG-525 (?node= invalide -> 400). Données fictives."""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.testing import make_node
from core.tests.test_permissions_regression_2026_11_19 import cl
from core.tests.test_verif_isolation_a_c import IsoBase
from production.management.commands.recompute_cump import count_ambiguous_movements
from production.models import ConsumableMovement, ConsumableStock


def run(*args):
    out = StringIO()
    call_command('recompute_cump', *args, stdout=out)
    return out.getvalue()


class Bug524(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.t0 = timezone.now().replace(microsecond=0)

    def mv(self, st, kind, qty, price, ts, pk=None):
        extra = {'id': pk} if pk else {}
        m = ConsumableMovement.objects.create(node=st.node, stock=st, movement_type=kind,
                                              quantity=Dc(qty), unit_price=Dc(price), **extra)
        ConsumableMovement.objects.filter(pk=m.pk).update(created_at=ts)
        return m

    def build(self, neg=True, order=0, p1='100.00', p2='200.00'):
        ConsumableMovement.objects.all().delete()
        ConsumableStock.objects.all().delete()
        st = ConsumableStock.objects.create(node=self.k1, consumable_type='FLOUR', quantity=Dc('8.000'), unit='sac')
        if neg:
            self.mv(st, 'EXIT', '5.000', '0.00', self.t0 - timedelta(seconds=5))
        lo, hi = uuid.UUID(int=1), uuid.UUID(int=2)
        ids = (lo, hi) if order == 0 else (hi, lo)
        self.mv(st, 'ENTRY', '3.000', p1, self.t0, pk=ids[0])
        self.mv(st, 'ENTRY', '10.000', p2, self.t0, pk=ids[1])
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('1'), quantity=Dc('8.000'))
        return st

    def test_negative_stock_same_instant_entries_flagged_in_simulation(self):
        self.build()
        out = run()
        self.assertIn('même instant', out)

    def test_apply_ignores_stock_without_force(self):
        st = self.build()
        out = run('--apply')
        self.assertIn('IGNORÉ', out)
        st.refresh_from_db()
        self.assertEqual(st.average_unit_cost, Dc('1'))

    def test_force_result_independent_of_pk_order(self):
        res = []
        for order in (0, 1):
            st = self.build(order=order)
            run('--apply', '--force')
            st.refresh_from_db()
            res.append(st.average_unit_cost)
        self.assertEqual(res[0], res[1])

    def test_positive_stock_same_instant_entries_not_flagged(self):
        self.build(neg=False)
        self.assertNotIn('même instant', run())

    def test_same_price_entries_on_negative_stock_not_flagged(self):
        self.build(p1='100.00', p2='100.00')
        self.assertNotIn('même instant', run())

    def test_count_helper(self):
        st = self.build()
        mvs = list(ConsumableMovement.objects.filter(stock=st).order_by('created_at', 'pk'))
        self.assertEqual(count_ambiguous_movements(mvs), 2)


class Bug525(IsoBase):
    URL = '/api/production/sessions/reconciliation/'
    FLOUR = '/api/production/movements/flour_history/'

    def test_reconciliation_non_numeric_node_is_400(self):
        r = cl(self.u['DIRECTION']).get(f'{self.URL}?node=ZZZ')
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)

    def test_reconciliation_unknown_numeric_node_is_400(self):
        self.assertEqual(cl(self.u['DIRECTION']).get(f'{self.URL}?node=999999').status_code, 400)

    def test_reconciliation_accepts_pk_and_code(self):
        r1 = cl(self.u['DIRECTION']).get(f'{self.URL}?node={self.k2.pk}')
        r2 = cl(self.u['DIRECTION']).get(f'{self.URL}?node={self.k2.code}')
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        self.assertEqual(r1.data['node'], self.k2.pk)
        self.assertEqual(r2.data['node'], self.k2.pk)

    def test_gerant_ignored_param_never_400(self):
        r = cl(self.u['GERANT']).get(f'{self.URL}?node=ZZZ')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['node'], self.k1.pk)

    def test_flour_history_non_numeric_node_is_400(self):
        r = cl(self.u['DIRECTION']).get(f'{self.FLOUR}?node=ZZZ')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(cl(self.u['DIRECTION']).get(f'{self.FLOUR}?node={self.k2.code}').status_code, 200)
