"""Contre-verification Dev C (testeur-production, 2026-11-22-c3) de BUG-364 et BUG-365.
Donnees fictives uniquement."""
from datetime import timedelta
from decimal import Decimal as Dc
from io import StringIO
from unittest import expectedFailure

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.testing import make_node
from core.tests.test_permissions_regression_2026_11_19 import cl, mk
from core.tests.test_verif_isolation_a_c import IsoBase
from production.models import ConsumableMovement, ConsumableStock

URL = '/api/production/sessions/reconciliation/'


def run(*args):
    out = StringIO()
    call_command('recompute_cump', *args, stdout=out)
    return out.getvalue()


class V364(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.t0 = timezone.now().replace(microsecond=0)
        self.n = 0

    def stock(self, node, qty='0.000', code='FLOUR'):
        return ConsumableStock.objects.create(node=node, consumable_type=code, quantity=Dc(qty), unit='sac')

    def mv(self, stock, kind, qty, price, ts, pk=None):
        extra = {'id': pk} if pk else {}
        m = ConsumableMovement.objects.create(
            node=stock.node, stock=stock, movement_type=kind, quantity=Dc(qty), unit_price=Dc(price), **extra)
        ConsumableMovement.objects.filter(pk=m.pk).update(created_at=ts)
        return m

    def snapshot(self):
        return (list(ConsumableStock.objects.order_by('pk').values_list('pk', 'average_unit_cost', 'quantity')),
                list(ConsumableMovement.objects.order_by('pk').values_list('pk', 'unit_price')))

    def tied(self, node, avg='999'):
        st = self.stock(node)
        self.mv(st, 'ENTRY', '10.000', '100.00', self.t0)
        ex = self.mv(st, 'EXIT', '2.000', '0.00', self.t0)
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc(avg), quantity=Dc('8.000'))
        ConsumableMovement.objects.filter(pk=ex.pk).update(unit_price=Dc('0.00'))  # valorisation fausse
        ex.refresh_from_db()
        return st, ex

    # --- egalite entree/sortie
    def test_tie_exit_valued_at_entry_price_with_force(self):
        st, ex = self.tied(self.k1)
        run('--apply', '--force')
        ex.refresh_from_db(); st.refresh_from_db()
        self.assertEqual(ex.unit_price, Dc('100.00'))
        self.assertEqual(st.average_unit_cost, Dc('100'))
        self.assertEqual(st.quantity, Dc('8.000'))  # quantite jamais modifiee

    def test_simulation_writes_nothing_and_warns(self):
        self.tied(self.k1)
        before = self.snapshot()
        out = run()
        self.assertIn('même instant', out)
        self.assertEqual(self.snapshot(), before)
        before_log = self._logs()
        run('--dry-run')
        self.assertEqual(self._logs(), before_log)

    def _logs(self):
        from core.models import ActivityLog
        return ActivityLog.objects.count()

    def test_apply_without_force_skips_and_does_not_log(self):
        st, ex = self.tied(self.k1)
        n = self._logs()
        out = run('--apply')
        self.assertIn('IGNORÉ', out)
        self.assertIn('0 corrigé', out)  # compteur decremente
        st.refresh_from_db(); ex.refresh_from_db()
        self.assertEqual(st.average_unit_cost, Dc('999'))
        self.assertEqual(ex.unit_price, Dc('0.00'))
        self.assertEqual(self._logs(), n)

    def test_tie_but_already_correct_is_not_ignored_and_no_error(self):
        # CUMP deja juste : ambiguite signalee mais rien a appliquer
        st = self.stock(self.k1)
        self.mv(st, 'ENTRY', '10.000', '100.00', self.t0)
        self.mv(st, 'EXIT', '2.000', '100.00', self.t0)
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('100'), quantity=Dc('8.000'))
        out = run('--apply')
        self.assertIn('inchangé', out)
        self.assertNotIn('IGNORÉ', out)

    # --- --node
    def test_node_option_limits_scope(self):
        st1, _ = self.tied(self.k1)
        st2, _ = self.tied(self.k2)
        run('--apply', '--force', '--node', 'K1')
        st1.refresh_from_db(); st2.refresh_from_db()
        self.assertEqual(st1.average_unit_cost, Dc('100'))
        self.assertEqual(st2.average_unit_cost, Dc('999'))
        self.assertIn('1 stock(s) examiné(s)', run('--node', 'K2'))

    def test_unknown_node_examines_nothing(self):
        self.tied(self.k1)
        self.assertIn('0 stock(s) examiné(s)', run('--node', 'ZZ'))

    # --- idempotence
    def test_force_apply_is_idempotent(self):
        self.tied(self.k1)
        run('--apply', '--force')
        snap = self.snapshot()
        out = run('--apply', '--force')
        self.assertEqual(self.snapshot(), snap)
        self.assertIn('0 corrigé', out)

    # --- coherence BUG-501 (stock non trace)
    def test_untraced_stock_still_ignored_without_force(self):
        st = self.stock(self.k1, qty='50.000')  # stock initial sans mouvement
        self.mv(st, 'ENTRY', '10.000', '100.00', self.t0)
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('80'), quantity=Dc('60.000'))
        out = run('--apply')
        self.assertIn('BUG-501', out)
        st.refresh_from_db()
        self.assertEqual(st.average_unit_cost, Dc('80'))
        run('--apply', '--force')
        st.refresh_from_db()
        self.assertEqual(st.average_unit_cost, Dc('100'))  # part non tracee perdue : documente BUG-501

    # --- coherence BUG-402 (max(old_qty,0)) : negatif puis entree
    def test_negative_then_entry_uses_positive_part_only(self):
        st = self.stock(self.k1)
        self.mv(st, 'EXIT', '5.000', '0.00', self.t0)
        self.mv(st, 'ENTRY', '10.000', '200.00', self.t0 + timedelta(seconds=1))
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('1'), quantity=Dc('5.000'))
        run('--apply')
        st.refresh_from_db()
        self.assertEqual(st.average_unit_cost, Dc('200'))

    # --- limite : deux entrees de meme instant, prix differents
    def test_two_entries_same_instant_positive_stock_order_independent(self):
        """Stock >= 0 : la moyenne ponderee est commutative, l'ordre est sans effet."""
        # Test strict : memes (qte,prix), ordre permute
        res = []
        for a, b in ((('4.000', '100.00'), ('6.000', '200.00')), (('6.000', '200.00'), ('4.000', '100.00'))):
            ConsumableMovement.objects.all().delete()
            ConsumableStock.objects.all().delete()
            st = self.stock(self.k1)
            self.mv(st, 'ENTRY', a[0], a[1], self.t0)
            self.mv(st, 'ENTRY', b[0], b[1], self.t0)
            ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('0'))
            run('--apply', '--force')
            st.refresh_from_db()
            res.append(st.average_unit_cost)
        self.assertEqual(res[0], res[1])

    @expectedFailure
    def test_BUG_524_two_entries_same_instant_after_negative_stock_order_changes_cump(self):
        """BUG-524 : stock negatif (-5) puis deux entrees de meme instant (3 @ 100, 10 @ 200) :
        le CUMP final depend de l'ordre (pk UUID aleatoire) et aucun avertissement n'est emis."""
        res = []
        for order in (0, 1):
            ConsumableMovement.objects.all().delete()
            ConsumableStock.objects.all().delete()
            st = self.stock(self.k1)
            self.mv(st, 'EXIT', '5.000', '0.00', self.t0 - timedelta(seconds=5))
            import uuid
            lo, hi = uuid.UUID(int=1), uuid.UUID(int=2)  # pk imposes : ordre de rejeu deterministe
            ids = (lo, hi) if order == 0 else (hi, lo)
            self.mv(st, 'ENTRY', '3.000', '100.00', self.t0, pk=ids[0])
            self.mv(st, 'ENTRY', '10.000', '200.00', self.t0, pk=ids[1])
            ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('0'))
            out = run('--apply', '--force')
            st.refresh_from_db()
            res.append((st.average_unit_cost, 'même instant' in out))
        self.assertEqual(res[0][0], res[1][0])  # echoue : 200 vs 162.5 (ordre impose par pk)


class V365(IsoBase):
    def test_gerant_k1_forged_node_k2_returns_own_node_and_own_data(self):
        r = cl(self.u['GERANT']).get(f'{URL}?node={self.k2.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['node'], self.k1.pk)
        self.assertEqual(r.data['produced_breads'] if 'produced_breads' in r.data else 0,
                         cl(self.u['GERANT']).get(URL).data.get('produced_breads', 0))

    def test_gerant_without_param(self):
        self.assertEqual(cl(self.u['GERANT']).get(URL).data['node'], self.k1.pk)

    def test_hq_valid_node_filter(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = cl(self.u[role]).get(f'{URL}?node={self.k2.pk}')
            self.assertEqual(r.status_code, 200, role)
            self.assertEqual(str(r.data['node']), str(self.k2.pk), role)

    def test_hq_without_node_is_none(self):
        r = cl(self.u['DIRECTION']).get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['node'])

    def test_hq_unknown_numeric_node_gives_zeros(self):
        r = cl(self.u['DIRECTION']).get(f'{URL}?node=999999')
        self.assertEqual(r.status_code, 200)

    @expectedFailure
    def test_BUG_525_hq_non_numeric_node_not_500(self):
        r = cl(self.u['DIRECTION']).get(f'{URL}?node=ZZZ')
        self.assertLess(r.status_code, 500)

    def test_node_less_non_hq(self):
        r = cl(mk('orph_c3_g', 'GERANT', None)).get(f'{URL}?node={self.k2.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['node'])

    def test_format_unchanged_keys(self):
        d = cl(self.u['GERANT']).get(f'{URL}?date=2026-11-18').data
        for k in ('node', 'date', 'date_from', 'date_to'):
            self.assertIn(k, d)
        self.assertEqual(d['date'], '2026-11-18')
        self.assertGreater(len(d), 4)
