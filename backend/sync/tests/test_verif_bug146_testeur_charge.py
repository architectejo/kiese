"""
Verification indépendante de BUG-146 (testeur-charge, 2026-11-21).

Sortie de consommable arrivée au Cloud avant son entrée : ré-estampillage du
prix, idempotence, atomicité, isolation par nœud, Decimal, charge.
Les tests de « limite » mesurent l'écart avec un CUMP chronologique exact.
"""
import random
import uuid
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.testing import make_node
from production.models import ConsumableMovement, ConsumableStock
from sync import services
from sync.models import NodeAuthToken, SyncConflictLog
from sync.services import ORPHAN_EXIT_CONFLICT, process_push_batch

LABEL = 'production.ConsumableMovement'
D = Decimal


def rec(mtype, qty, price='0', node='K1', ctype='FLOUR', unit='sacs', rid=None):
    return {
        'id': rid or str(uuid.uuid4()), 'node': node, 'consumable_type': ctype,
        'unit': unit, 'movement_type': mtype, 'quantity': qty,
        'unit_price': price, 'node_origin': node,
    }


def stock_of(node, ctype='FLOUR'):
    return ConsumableStock.objects.get(node=node, consumable_type=ctype)


class Base(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.sender = self.k1

    def push(self, *records, node=None):
        return process_push_batch(node or self.sender, {LABEL: list(records)})[LABEL]

    def price(self, rid):
        return ConsumableMovement.objects.get(pk=rid).unit_price

    def marker(self, rid):
        return SyncConflictLog.objects.get(object_id=rid, conflict_type=ORPHAN_EXIT_CONFLICT)


class OrderingTests(Base):
    def test_exit_then_entry_reversed_order(self):
        ex = rec('EXIT', '3.000')
        self.push(ex)
        self.assertEqual(self.price(ex['id']), D('0.00'))
        self.assertFalse(self.marker(ex['id']).is_resolved)
        self.push(rec('ENTRY', '10.000', '80000.00'))
        self.assertEqual(self.price(ex['id']), D('80000.00'))
        self.assertTrue(self.marker(ex['id']).is_resolved)
        self.assertEqual(stock_of(self.k1).quantity, D('7.000'))

    def test_several_orphan_exits_then_several_entries(self):
        exits = [rec('EXIT', '1.000') for _ in range(4)]
        self.push(*exits)
        for e in exits:
            self.assertEqual(self.price(e['id']), D('0.00'))
        # 1re entrée : toutes les sorties orphelines recoivent son prix
        self.push(rec('ENTRY', '10.000', '100000.00'))
        for e in exits:
            self.assertEqual(self.price(e['id']), D('100000.00'))
            self.assertTrue(self.marker(e['id']).is_resolved)
        # 2e entrée a un autre prix : les sorties résolues ne bougent plus
        self.push(rec('ENTRY', '10.000', '200000.00'))
        for e in exits:
            self.assertEqual(self.price(e['id']), D('100000.00'))
        self.assertEqual(stock_of(self.k1).quantity, D('16.000'))
        self.assertEqual(SyncConflictLog.objects.filter(conflict_type=ORPHAN_EXIT_CONFLICT).count(), 4)

    def test_entries_arriving_out_of_order_amongst_themselves(self):
        ex = rec('EXIT', '2.000')
        e_late_cheap = rec('ENTRY', '5.000', '60000.00')
        e_big = rec('ENTRY', '15.000', '100000.00')
        self.push(e_big, ex, e_late_cheap)
        self.assertEqual(self.price(ex['id']), D('100000.00'))  # 1re entrée valorisée vue
        self.assertEqual(stock_of(self.k1).quantity, D('18.000'))

    def test_zero_priced_entry_leaves_exit_pending(self):
        ex = rec('EXIT', '1.000')
        self.push(ex, rec('ENTRY', '4.000', '0'))
        self.assertEqual(self.price(ex['id']), D('0.00'))
        self.assertFalse(self.marker(ex['id']).is_resolved)
        self.push(rec('ENTRY', '4.000', '40000.00'))
        # moyenne pondérée de toutes les entrées reçues : (0*4 + 40000*4) / 8
        self.assertEqual(self.price(ex['id']), D('20000.00'))
        self.assertTrue(self.marker(ex['id']).is_resolved)

    def test_exit_after_entry_not_tracked(self):
        self.push(rec('ENTRY', '10.000', '50000.00'))
        ex = rec('EXIT', '1.000')
        self.push(ex)
        self.assertEqual(self.price(ex['id']), D('50000.00'))
        self.assertFalse(SyncConflictLog.objects.filter(object_id=ex['id']).exists())


class IdempotenceTests(Base):
    def test_replay_same_push_twice_counts_nothing_twice(self):
        ex, en = rec('EXIT', '3.000'), rec('ENTRY', '10.000', '80000.00')
        self.push(ex, en)
        snap = (stock_of(self.k1).quantity, stock_of(self.k1).average_unit_cost,
                ConsumableMovement.objects.count(), SyncConflictLog.objects.count(),
                self.price(ex['id']))
        for _ in range(3):
            res = self.push(ex, en)
            self.assertTrue(all(r['status'] == 'ACCEPTED' for r in res))
        snap2 = (stock_of(self.k1).quantity, stock_of(self.k1).average_unit_cost,
                 ConsumableMovement.objects.count(), SyncConflictLog.objects.count(),
                 self.price(ex['id']))
        self.assertEqual(snap, snap2)

    def test_replay_orphan_exit_alone_does_not_duplicate_marker_or_stock(self):
        ex = rec('EXIT', '3.000')
        self.push(ex)
        self.push(ex)
        self.assertEqual(stock_of(self.k1).quantity, D('-3.000'))
        self.assertEqual(SyncConflictLog.objects.filter(object_id=ex['id']).count(), 1)

    def test_replay_via_api_same_batch_id(self):
        _, raw = NodeAuthToken.issue_for_node(self.k1)
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
        payload = {'batch_id': str(uuid.uuid4()),
                   'records': {LABEL: [rec('EXIT', '2.000'), rec('ENTRY', '6.000', '30000.00')]}}
        r1 = api.post('/api/sync/push/', payload, format='json')
        r2 = api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(ConsumableMovement.objects.count(), 2)
        self.assertEqual(stock_of(self.k1).quantity, D('4.000'))


class AtomicityTests(Base):
    def test_failure_in_restamp_rolls_back_the_whole_record_only(self):
        ex = rec('EXIT', '2.000')
        ok1, bad, ok2 = rec('ENTRY', '1.000', '10000.00'), rec('ENTRY', '5.000', '90000.00'), rec('ENTRY', '2.000', '10000.00')
        self.push(ex)
        real = services._restamp_orphan_exits

        def boom(stock_id):
            if ConsumableMovement.objects.filter(pk=bad['id']).exists():
                raise RuntimeError('coupure simulée')
            return real(stock_id)

        with mock.patch.object(services, '_restamp_orphan_exits', side_effect=boom):
            res = self.push(ok1, bad, ok2)
        self.assertEqual([r['status'] for r in res], ['ACCEPTED', 'REJECTED', 'ACCEPTED'])
        self.assertFalse(ConsumableMovement.objects.filter(pk=bad['id']).exists())
        # stock : -2 + 1 + 2 = 1 ; l'entrée coupée n'a laissé aucune trace
        self.assertEqual(stock_of(self.k1).quantity, D('1.000'))
        self.assertEqual(self.price(ex['id']), D('10000.00'))

    def test_failure_inside_restamp_update_leaves_exit_unresolved(self):
        ex = rec('EXIT', '2.000')
        self.push(ex)
        en = rec('ENTRY', '4.000', '50000.00')
        with mock.patch.object(SyncConflictLog, 'save', side_effect=RuntimeError('coupure')):
            res = self.push(en)
        self.assertEqual(res[0]['status'], 'REJECTED')
        # ni l'entrée, ni le prix, ni le marqueur ne sont demi-appliqués
        self.assertFalse(ConsumableMovement.objects.filter(pk=en['id']).exists())
        self.assertEqual(self.price(ex['id']), D('0.00'))
        self.assertFalse(self.marker(ex['id']).is_resolved)
        self.assertEqual(stock_of(self.k1).quantity, D('-2.000'))
        # le rejeu de l'entrée après "reprise" aboutit
        self.push(en)
        self.assertEqual(self.price(ex['id']), D('50000.00'))
        self.assertTrue(self.marker(ex['id']).is_resolved)
        self.assertEqual(stock_of(self.k1).quantity, D('2.000'))


class IsolationAndDecimalTests(Base):
    def test_two_nodes_do_not_mix(self):
        ex1, ex2 = rec('EXIT', '1.000', node='K1'), rec('EXIT', '1.000', node='K2')
        # BUG-788 : chaque poste pousse ses propres mouvements (jeton du nœud).
        self.push(ex1)
        self.push(ex2, node=self.k2)
        self.push(rec('ENTRY', '5.000', '100000.00', node='K1'))
        self.assertEqual(self.price(ex1['id']), D('100000.00'))
        self.assertEqual(self.price(ex2['id']), D('0.00'))
        self.assertTrue(self.marker(ex1['id']).is_resolved)
        self.assertFalse(self.marker(ex2['id']).is_resolved)
        self.assertEqual(stock_of(self.k1).quantity, D('4.000'))
        self.assertEqual(stock_of(self.k2).quantity, D('-1.000'))
        self.push(rec('ENTRY', '2.000', '7000.00', node='K2'), node=self.k2)
        self.assertEqual(self.price(ex2['id']), D('7000.00'))
        self.assertEqual(self.price(ex1['id']), D('100000.00'))

    def test_two_consumables_same_node_do_not_mix(self):
        exf = rec('EXIT', '1.000', ctype='FLOUR')
        exs = rec('EXIT', '100.000', ctype='SALT', unit='g')
        self.push(exf, exs)
        self.push(rec('ENTRY', '5.000', '100000.00', ctype='FLOUR'))
        self.assertEqual(self.price(exf['id']), D('100000.00'))
        self.assertEqual(self.price(exs['id']), D('0.00'))

    def test_decimal_quantities_salt_yeast_oil(self):
        cases = [('SALT', 'g', '250.000', '1250.500', '0.40'),
                 ('YEAST', 'paquets', '0.250', '2.750', '4500.00'),
                 ('OIL', 'L', '0.125', '3.375', '5600.00')]
        for ctype, unit, out_q, in_q, price in cases:
            ex = rec('EXIT', out_q, ctype=ctype, unit=unit)
            self.push(ex)
            self.push(rec('ENTRY', in_q, price, ctype=ctype, unit=unit))
            st = stock_of(self.k1, ctype)
            self.assertIsInstance(st.quantity, Decimal)
            self.assertEqual(st.quantity, D(in_q) - D(out_q))  # exact, pas de dérive flottante
            self.assertEqual(self.price(ex['id']), D(price))

    def test_many_fractional_exits_sum_exactly(self):
        exits = [rec('EXIT', '0.250', ctype='YEAST', unit='paquets') for _ in range(40)]
        self.push(*exits)
        self.push(rec('ENTRY', '20.000', '4500.00', ctype='YEAST', unit='paquets'))
        self.assertEqual(stock_of(self.k1, 'YEAST').quantity, D('10.000'))

    def test_restamp_never_changes_stock_quantity_or_cump(self):
        self.push(rec('EXIT', '3.000'))
        self.push(rec('ENTRY', '10.000', '80000.00'))
        st = stock_of(self.k1)
        q, avg = st.quantity, st.average_unit_cost
        self.assertEqual(services._restamp_orphan_exits(st.pk), 0)
        st.refresh_from_db()
        self.assertEqual((st.quantity, st.average_unit_cost), (q, avg))


class LoadTests(Base):
    def _scenario(self, seed):
        rnd = random.Random(1234)
        recs = []
        for i in range(200):
            if rnd.random() < 0.4:
                price = rnd.choice(['90000.00', '95000.00', '100000.00', '105000.00'])
                recs.append(('ENTRY', str(D(rnd.randint(1, 8))) + '.000', price))
            else:
                recs.append(('EXIT', str(D(rnd.randint(1, 40)) / D(8)) + '00'[:0], '0'))
        # ids fixes pour comparer entre ordres
        ids = [str(uuid.UUID(int=i + 1)) for i in range(200)]
        items = [rec(t, f"{D(q):.3f}", p, rid=ids[i]) for i, (t, q, p) in enumerate(recs)]
        random.Random(seed).shuffle(items)
        return items

    def _final_state(self):
        st = stock_of(self.k1)
        return st.quantity

    def test_final_quantity_identical_whatever_the_arrival_order(self):
        results = []
        for seed in (1, 2, 3):
            ConsumableMovement.objects.all().delete()
            SyncConflictLog.objects.all().delete()
            ConsumableStock.objects.all().delete()
            items = self._scenario(seed)
            res = self.push(*items)
            self.assertTrue(all(r['status'] == 'ACCEPTED' for r in res))
            st = stock_of(self.k1)
            entries = sum((D(r['quantity']) for r in items if r['movement_type'] == 'ENTRY'), D(0))
            exits = sum((D(r['quantity']) for r in items if r['movement_type'] == 'EXIT'), D(0))
            self.assertEqual(st.quantity, entries - exits)
            self.assertEqual(ConsumableMovement.objects.count(), 200)
            # plus aucune sortie en attente dès qu'une entrée valorisée existe
            self.assertEqual(SyncConflictLog.objects.filter(
                conflict_type=ORPHAN_EXIT_CONFLICT, resolved_at__isnull=True).count(), 0)
            self.assertFalse(ConsumableMovement.objects.filter(
                movement_type='EXIT', unit_price__lte=0).exists())
            results.append((st.quantity, ConsumableMovement.objects.count()))
        self.assertEqual(len(set(results)), 1)

    def test_query_count_bounded_per_record(self):
        items = self._scenario(7)
        with CaptureQueriesContext(connection) as ctx:
            self.push(*items)
        per_record = len(ctx) / 200
        print(f"\n[CHARGE] 200 mouvements: {len(ctx)} requetes SQL, {per_record:.1f}/mouvement")
        self.assertLess(per_record, 30)

    def test_query_count_does_not_explode_with_history(self):
        """La ré-estampille relit toutes les ENTRY : le nombre de REQUETES doit rester constant."""
        def count_for_entry():
            with CaptureQueriesContext(connection) as ctx:
                self.push(rec('ENTRY', '1.000', '100000.00'))
            return len(ctx)
        self.push(rec('EXIT', '1.000'))
        first = count_for_entry()
        for _ in range(150):
            self.push(rec('ENTRY', '1.000', '100000.00'))
        later = count_for_entry()
        self.assertLessEqual(later, first + 2)


class CumpLimitQuantificationTests(Base):
    """
    Limite annoncée : prix = moyenne pondérée des entrées reçues, pas le CUMP chronologique.
    Cas réaliste : farine, 1 sac = 100 000 FC en janvier, 130 000 FC en juin (+30 %).
    Les 3 premiers mois : 10 sacs a 100 000 puis consommation ; sortie de 4 sacs en
    mars (CUMP exact 100 000), 4 sacs en juin apres la hausse.
    """

    def test_quantify_gap_vs_exact_chronological_cump(self):
        # ordre réel : E1 10 sacs @100k ; X1 4 sacs ; E2 10 sacs @130k ; X2 4 sacs
        e1, x1 = rec('ENTRY', '10.000', '100000.00'), rec('EXIT', '4.000')
        e2, x2 = rec('ENTRY', '10.000', '130000.00'), rec('EXIT', '4.000')
        # CUMP exact : X1 = 100 000 ; stock 6 @100k + 10 @130k = 16 -> 118 750 ; X2 = 118 750
        exact = {'x1': D('100000'), 'x2': D('118750')}
        exact_cogs = D('4') * exact['x1'] + D('4') * exact['x2']

        # Arrivée dans le désordre : sorties d'abord, entrées ensuite
        self.push(x1, x2)
        self.push(e1)
        self.push(e2)
        got1, got2 = self.price(x1['id']), self.price(x2['id'])
        got_cogs = D('4') * got1 + D('4') * got2
        gap = got_cogs - exact_cogs
        print(f"\n[LIMITE] COGS exact={exact_cogs} FC ; obtenu={got_cogs} FC ; "
              f"ecart={gap} FC ({gap / exact_cogs * 100:.2f} %) ; prix x1={got1}, x2={got2}")
        # Ces deux sorties sont résolues à l'arrivée de E1 seule (prix 100 000) :
        # E2 arrive après, le marqueur est déjà résolu -> pas de moyenne des 2 entrées.
        self.assertEqual(got1, D('100000.00'))
        self.assertEqual(got2, D('100000.00'))
        # Pire cas (toutes les sorties avant toutes les entrées, +30 % de prix) : écart < 10 %.
        self.assertLess(abs(gap) / exact_cogs, D('0.10'))

    def test_order_dependence_of_orphan_price(self):
        """Même jeu de mouvements, deux ordres d'arrivée : prix de la sortie orphelinne différent."""
        ex_a, ex_b = rec('EXIT', '1.000'), rec('EXIT', '1.000')
        e1, e2 = rec('ENTRY', '10.000', '100000.00'), rec('ENTRY', '10.000', '130000.00')
        self.push(ex_a, e1, e2)
        price_a = self.price(ex_a['id'])
        ConsumableMovement.objects.all().delete()
        SyncConflictLog.objects.all().delete()
        ConsumableStock.objects.all().delete()
        self.push(ex_b, e2, e1)
        price_b = self.price(ex_b['id'])
        print(f"\n[ORDRE] prix de la sortie orphelinne: ordre E1,E2 -> {price_a} ; ordre E2,E1 -> {price_b}")
        self.assertEqual(price_a, D('100000.00'))
        self.assertEqual(price_b, D('130000.00'))
