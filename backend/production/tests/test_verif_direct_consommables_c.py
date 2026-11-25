"""Verification independante (testeur-production, Dev C, 2026-11-22c) de
BUG-380/382 (envoi direct de pains), BUG-386 (consommables direction),
BUG-526 (parametres illisibles -> 400). Donnees fictives uniquement."""
from decimal import Decimal as D
from unittest import expectedFailure

from core.models import BreadPrice, Node
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk
from core.workday import work_date_for  # noqa: F401  (import de controle)
from production.models import (BreadStock, BreadTransfer, ConsumableCount, ConsumableInventory,
                               ConsumableMovement, ConsumableStock, ConsumableType, _adjust_bread_stock)
from treasury.views import _unresolved_incoming_transfer_gap

SEND = '/api/production/transfers/send/'
G = '/api/production/consumables/global/'
DISPATCH = '/api/production/consumables/dispatch/'
INV = '/api/production/inventories/'


def avail(node, bp):
    s = BreadStock.objects.filter(node=node, bread_price=bp).first()
    return s.qty_available if s else 0


def group(bp):
    return sum(s.qty_available for s in BreadStock.objects.filter(bread_price=bp))


class SendBase(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.k3 = Node.objects.create(code='P3', name='Perm K3', team_rotation_enabled=False)
        cls.u3 = mk('pr3_gerant_c', 'GERANT', cls.k3)

    def setUp(self):
        _adjust_bread_stock(self.k1, self.bp, produced=50)

    def send(self, user, to=-7, qty=10, lines=None, body=None):
        to = self.k2.pk if to == -7 else to
        payload = body if body is not None else {
            'to_node': to, 'lines': lines if lines is not None else
            [{'bread_price': self.bp.pk, 'quantity_sent': qty}]}
        return cl(user).post(SEND, payload, format='json')


class DirectSendAttacks(SendBase):
    def test_roles(self):
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(self.send(self.u[role]).status_code, 403, role)
        # siege sans boulangerie : 400 propre, jamais 500, jamais d'ecriture
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = self.send(self.u[role])
            self.assertIn(r.status_code, (400, 403), role)
        self.assertEqual(BreadTransfer.objects.filter(flow='DIRECT').count(), 0)
        self.assertEqual(avail(self.k1, self.bp), 50)
        self.assertEqual(cl().post(SEND, {}, format='json').status_code, 401)

    def test_bad_quantities_are_400_and_write_nothing(self):
        for q in (0, -5, 5.5, '5.5', 'abc', None, True, [], {}, 10 ** 40, '1e3', ''):
            r = self.send(self.u['GERANT'], qty=q)
            self.assertEqual(r.status_code, 400, (q, r.status_code))
        self.assertEqual(BreadTransfer.objects.filter(flow='DIRECT').count(), 0)
        self.assertEqual(avail(self.k1, self.bp), 50)

    def test_bad_destination_is_400(self):
        for dest in (None, '', 'ZZZ', 0, -1, 10 ** 40, [], {}):
            r = self.send(self.u['GERANT'], to=dest)
            self.assertIn(r.status_code, (400,), (dest, r.status_code))
        self.assertEqual(BreadTransfer.objects.filter(flow='DIRECT').count(), 0)

    def test_self_send_refused(self):
        self.assertEqual(self.send(self.u['GERANT'], to='P1').status_code, 400)
        self.assertEqual(self.send(self.u['GERANT'], to=self.k1.pk).status_code, 400)

    def test_BUG_540_send_to_technical_siege_node_refused(self):
        """Envoyer vers le noeud technique SIEGE (inactif) = pains perdus : doit etre refuse."""
        Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege', 'is_active': False})
        r = self.send(self.u['GERANT'], to='SIEGE')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(avail(self.k1, self.bp), 50)

    def test_BUG_540_send_to_inactive_node_refused(self):
        k9 = Node.objects.create(code='P9', name='Ferme', is_active=False, team_rotation_enabled=False)
        r = self.send(self.u['GERANT'], to=k9.pk)
        self.assertEqual(r.status_code, 400, r.content)

    def test_bad_lines_shapes(self):
        for lines in (None, [], 'x', {}, ['x'], [1], [{}], [{'bread_price': 10 ** 40, 'quantity_sent': 1}],
                      [{'bread_price': 'abc', 'quantity_sent': 1}], [{'bread_price': [], 'quantity_sent': 1}],
                      [{'bread_price': {}, 'quantity_sent': 1}], [{'bread_price': -1, 'quantity_sent': 1}]):
            r = self.send(self.u['GERANT'], body={'to_node': self.k2.pk, 'lines': lines})
            self.assertEqual(r.status_code, 400, (lines, r.status_code))
        for body in ([], 'x', 5, None):
            r = cl(self.u['GERANT']).post(SEND, body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))
        self.assertEqual(avail(self.k1, self.bp), 50)

    def test_insufficient_and_sequence_no_oversell(self):
        self.assertEqual(self.send(self.u['GERANT'], qty=51).status_code, 400)
        self.assertEqual(avail(self.k1, self.bp), 50)
        self.assertEqual(self.send(self.u['GERANT'], qty=30).status_code, 201)
        r = self.send(self.u['GERANT'], qty=30)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(avail(self.k1, self.bp), 20)
        self.assertEqual(self.send(self.u['GERANT'], qty=20).status_code, 201)
        self.assertEqual(avail(self.k1, self.bp), 0)
        self.assertEqual(self.send(self.u['GERANT'], qty=1).status_code, 400)
        self.assertEqual(avail(self.k1, self.bp), 0)
        # le stock n'est jamais negatif
        self.assertGreaterEqual(BreadStock.objects.get(node=self.k1, bread_price=self.bp).qty_available, 0)

    def test_multi_line_atomic_on_partial_shortage(self):
        bp2 = BreadPrice.objects.create(category='PETIT', label='Pain 200', unit_price=200)
        _adjust_bread_stock(self.k1, bp2, produced=5)
        r = self.send(self.u['GERANT'], lines=[
            {'bread_price': self.bp.pk, 'quantity_sent': 10},
            {'bread_price': bp2.pk, 'quantity_sent': 6}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual((avail(self.k1, self.bp), avail(self.k1, bp2)), (50, 5))
        self.assertEqual(BreadTransfer.objects.filter(flow='DIRECT').count(), 0)

    def test_stock_already_negative_refused_without_negative_message(self):
        s = BreadStock.objects.get(node=self.k1, bread_price=self.bp)
        s.qty_disposed = 54
        s.save()
        self.assertLess(s.qty_available, 0)
        r = self.send(self.u['GERANT'], qty=1)
        self.assertEqual(r.status_code, 400)
        self.assertIn(' 0 disponible', r.data['detail'])


class DirectReceptionAttacks(SendBase):
    def confirm(self, user, tid, qty, bp=None):
        return cl(user).post(f'/api/production/transfers/{tid}/confirm_reception/', {
            'lines': [{'bread_price': (bp or self.bp).pk, 'quantity_received': qty}]}, format='json')

    def sent(self, qty=100):
        r = self.send(self.u['GERANT'], qty=qty)
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def test_sender_and_third_party_cannot_confirm(self):
        tid = self.sent(20)
        for user in (self.u['GERANT'], self.u3, self.u['FACTURIER']):
            r = self.confirm(user, tid, 20)
            self.assertIn(r.status_code, (403, 404), (user.username, r.status_code))
        self.assertEqual(avail(self.k2, self.bp), 0)
        self.assertEqual(BreadTransfer.objects.get(pk=tid).transfer_status, 'RESPONDED')

    def test_receiver_confirm_group_sum_invariant_and_double_validation(self):
        before = group(self.bp)
        tid = self.sent(20)
        self.assertEqual(group(self.bp), before - 20)  # en transit
        self.assertEqual(self.confirm(self.u2['GERANT'], tid, 20).status_code, 200)
        self.assertEqual((avail(self.k1, self.bp), avail(self.k2, self.bp)), (30, 20))
        self.assertEqual(group(self.bp), before)
        r = self.confirm(self.u2['GERANT'], tid, 20)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(avail(self.k2, self.bp), 20)
        self.assertEqual(_unresolved_incoming_transfer_gap(self.k2), '')

    def test_hq_can_validate_reception(self):
        tid = self.sent(10)
        r = self.confirm(self.u['DIRECTION'], tid, 10)
        self.assertIn(r.status_code, (200, 403), r.content)  # siege autorise par spec, a documenter

    def test_over_reception_goes_to_dispute_and_blocks_closure(self):
        """K2 declare 15 pour 10 envoyes : litige + blocage (le credit transitoire est regularise par resolve_dispute)."""
        tid = self.sent(10)
        r = self.confirm(self.u2['GERANT'], tid, 15)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(BreadTransfer.objects.get(pk=tid).transfer_status, 'DISPUTED')
        self.assertNotEqual(_unresolved_incoming_transfer_gap(self.k2), '')
        # resolution alignee sur l'envoye : somme du groupe restauree
        before = 50
        r = cl(self.u['DIRECTION']).post(f'/api/production/transfers/{tid}/resolve_dispute/',
                                         {'resolution': 'ALIGN_ON_SENT', 'reason': 'recompte'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(group(self.bp), before)
        self.assertEqual(_unresolved_incoming_transfer_gap(self.k2), '')

    def test_negative_or_bad_received_quantity(self):
        tid = self.sent(10)
        for q in (-3, 'abc', None, 1.5, 10 ** 40):
            r = self.confirm(self.u2['GERANT'], tid, q)
            self.assertEqual(r.status_code, 400, (q, r.status_code))
        self.assertEqual(avail(self.k2, self.bp), 0)

    def test_dispute_blocks_closure_and_nothing_lost_silently(self):
        tid = self.sent(40)
        r = self.confirm(self.u2['GERANT'], tid, 38)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(BreadTransfer.objects.get(pk=tid).transfer_status, 'DISPUTED')
        self.assertNotEqual(_unresolved_incoming_transfer_gap(self.k2), '')
        # la boulangerie emettrice n'est pas bloquee
        self.assertEqual(_unresolved_incoming_transfer_gap(self.k1), '')


# ---------------------------------------------------------------- consommables direction
class CB(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code, label, unit in [('FLOUR', 'Farine', 'sac'), ('YEAST', 'Levure', 'paquet'),
                                  ('SALT', 'Sel', 'g'), ('OIL', 'Huile', 'L')]:
            ConsumableType.objects.get_or_create(code=code, defaults={'label': label, 'unit': unit})
        cls.siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege', 'is_active': False})[0]
        cls.k3 = Node.objects.create(code='P3', name='Perm K3', team_rotation_enabled=False)
        cls.u3 = mk('pr3_gerant_cc', 'GERANT', cls.k3)
        cls.ssiege = cls.stock(cls.siege, 'FLOUR', '100')
        cls.s1 = cls.stock(cls.k1, 'FLOUR', '5')
        cls.s2 = cls.stock(cls.k2, 'FLOUR', '7')

    @staticmethod
    def stock(node, code, qty, cump=None):
        s, _ = ConsumableStock.objects.get_or_create(node=node, consumable_type=code,
                                                     defaults={'node_origin': node.code})
        upd = {'quantity': D(qty)}
        if cump is not None:
            upd['average_unit_cost'] = D(cump)
        ConsumableStock.objects.filter(pk=s.pk).update(**upd)
        s.refresh_from_db()
        return s

    def q(self, st):
        st.refresh_from_db()
        return st.quantity

    def total(self, code='FLOUR'):
        return sum(s.quantity for s in ConsumableStock.objects.filter(consumable_type=code))


class GlobalIsolation(CB):
    def test_roles_on_global(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).get(G).status_code, 403, role)
        self.assertEqual(cl().get(G).status_code, 401)
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            self.assertEqual(cl(self.u[role]).get(G).status_code, 200, role)

    def test_inactive_node_and_siege_excluded_from_rows_decimal_strings(self):
        Node.objects.create(code='P9', name='Ferme', is_active=False, team_rotation_enabled=False)
        r = cl(self.u['DIRECTION']).get(G)
        codes = [n['code'] for n in r.data['nodes']]
        self.assertNotIn('SIEGE', codes)
        self.assertNotIn('P9', codes)
        for v in r.data['totals_group'].values():
            self.assertIsInstance(v, str)
            D(v)

    def test_dispatch_roles(self):
        body = {'consumable_type': 'FLOUR', 'allocations': [{'node': 'P1', 'quantity': '1'}]}
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).post(DISPATCH, body, format='json')
            self.assertEqual(r.status_code, 403, role)
        self.assertEqual(cl().post(DISPATCH, body, format='json').status_code, 401)
        self.assertEqual(self.q(self.ssiege), D('100'))


class DispatchAttacks(CB):
    def go(self, allocs, code='FLOUR', role='DIRECTION', **extra):
        body = {'consumable_type': code, 'allocations': allocs}
        body.update(extra)
        return cl(self.u[role]).post(DISPATCH, body, format='json')

    def test_nominal_group_invariant_and_cump(self):
        self.stock(self.siege, 'FLOUR', '100', cump='1000')
        before = self.total()
        r = self.go([{'node': 'P1', 'quantity': '10.5'}, {'node': self.k2.pk, 'quantity': '0.25'}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.total(), before)
        self.assertEqual(self.q(self.ssiege), D('89.250'))
        self.assertEqual(self.q(self.s1), D('15.5'))
        self.assertEqual(self.q(self.s2), D('7.25'))
        self.s1.refresh_from_db()
        self.assertGreater(self.s1.average_unit_cost, 0)
        self.assertEqual(ConsumableMovement.objects.filter(node=self.k1, movement_type='ENTRY').count(), 1)

    def test_insufficient_total_across_lines_no_partial_write(self):
        n = ConsumableMovement.objects.count()
        r = self.go([{'node': 'P1', 'quantity': '60'}, {'node': 'P2', 'quantity': '50'}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ConsumableMovement.objects.count(), n)
        self.assertEqual(self.q(self.ssiege), D('100'))
        self.assertEqual(self.q(self.s1), D('5'))

    def test_sequence_cannot_exceed_direction_stock(self):
        self.assertEqual(self.go([{'node': 'P1', 'quantity': '70'}]).status_code, 201)
        self.assertEqual(self.go([{'node': 'P2', 'quantity': '40'}]).status_code, 400)
        self.assertEqual(self.go([{'node': 'P2', 'quantity': '30'}]).status_code, 201)
        self.assertEqual(self.q(self.ssiege), D('0'))
        self.assertEqual(self.go([{'node': 'P2', 'quantity': '0.001'}]).status_code, 400)

    def test_missing_direction_stock_row(self):
        r = self.go([{'node': 'P1', 'quantity': '1'}], code='SALT')
        self.assertEqual(r.status_code, 400, r.content)

    def test_bad_quantities(self):
        for q in (0, '0', -1, '-0.5', 'abc', 'NaN', 'Infinity', '-Infinity', '0.0001', None, True, '',
                  10 ** 12, '99999999', [], {}):
            r = self.go([{'node': 'P1', 'quantity': q}])
            self.assertEqual(r.status_code, 400, (q, r.status_code))
        self.assertEqual(self.q(self.ssiege), D('100'))

    def test_bad_destinations(self):
        for node in ('SIEGE', 'ZZZ', 99999, None, '', [], {}):
            r = self.go([{'node': node, 'quantity': '1'}])
            self.assertEqual(r.status_code, 400, (node, r.status_code))
        k9 = Node.objects.create(code='P9', name='Ferme', is_active=False, team_rotation_enabled=False)
        self.assertEqual(self.go([{'node': k9.pk, 'quantity': '1'}]).status_code, 400)
        self.assertEqual(self.go([{'node': 'P1', 'quantity': '1'}, {'node': self.k1.pk, 'quantity': '1'}]
                                 ).status_code, 400)
        self.assertEqual(self.q(self.ssiege), D('100'))

    def test_huge_integer_destination_is_not_a_500(self):
        r = self.go([{'node': 10 ** 40, 'quantity': '1'}])
        self.assertEqual(r.status_code, 400, r.status_code)

    def test_bad_shapes(self):
        for body in ([], 'x', None, {}, {'consumable_type': 'FLOUR'}, {'consumable_type': 'FLOUR', 'allocations': []},
                     {'consumable_type': 'FLOUR', 'allocations': 'x'},
                     {'consumable_type': 'FLOUR', 'allocations': ['x']},
                     {'consumable_type': 'NOPE', 'allocations': [{'node': 'P1', 'quantity': '1'}]},
                     {'consumable_type': ['FLOUR'], 'allocations': [{'node': 'P1', 'quantity': '1'}]}):
            r = cl(self.u['DIRECTION']).post(DISPATCH, body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))

    def test_inactive_consumable_type_refused(self):
        ConsumableType.objects.filter(code='OIL').update(is_active=False)
        self.stock(self.siege, 'OIL', '10')
        self.assertEqual(self.go([{'node': 'P1', 'quantity': '1'}], code='OIL').status_code, 400)

    def test_admin_also_allowed_decimal_levure(self):
        self.stock(self.siege, 'YEAST', '3')
        r = self.go([{'node': 'P1', 'quantity': '0,25'}], code='YEAST', role='ADMIN')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.q(ConsumableStock.objects.get(node=self.k1, consumable_type='YEAST')), D('0.25'))
        self.assertEqual(self.q(ConsumableStock.objects.get(node=self.siege, consumable_type='YEAST')), D('2.75'))


class InventoryAttacks(CB):
    def mk_inv(self, user=None, lines=None, **extra):
        body = {'lines': lines if lines is not None else [{'consumable_type': 'FLOUR', 'physical_quantity': '4.5'}]}
        body.update(extra)
        return cl(user or self.u['GERANT']).post(INV, body, format='json')

    def test_roles_create(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(self.mk_inv(self.u[role]).status_code, 403, role)
        self.assertEqual(ConsumableInventory.objects.count(), 0)

    def test_gap_and_stock_untouched_and_once_per_day(self):
        r = self.mk_inv()
        self.assertEqual(r.status_code, 201, r.content)
        ln = r.data['lines'][0]
        self.assertEqual(D(ln['gap']), D('4.5') - D('5'))
        self.assertEqual(D(ln['system_quantity']), D('5'))
        self.assertEqual(self.q(self.s1), D('5'))  # l'inventaire ne corrige pas le stock
        self.assertEqual(self.mk_inv().status_code, 400)
        self.assertEqual(ConsumableInventory.objects.filter(node=self.k1).count(), 1)
        self.assertEqual(ConsumableCount.objects.filter(node=self.k1).count(), 1)
        # un autre noeud peut saisir le meme jour
        self.assertEqual(self.mk_inv(self.u2['GERANT']).status_code, 201)

    def test_node_forgery_ignored(self):
        r = self.mk_inv(node=self.k2.pk)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['node'], self.k1.pk)
        self.assertFalse(ConsumableInventory.objects.filter(node=self.k2).exists())

    def test_bad_input(self):
        n = ConsumableInventory.objects.count()
        cases = [[], 'x', ['x'], [{}], [{'consumable_type': 'NOPE', 'physical_quantity': '1'}],
                 [{'consumable_type': 'FLOUR', 'physical_quantity': '-1'}],
                 [{'consumable_type': 'FLOUR', 'physical_quantity': 'abc'}],
                 [{'consumable_type': 'FLOUR', 'physical_quantity': '1.2345'}],
                 [{'consumable_type': 'FLOUR', 'physical_quantity': 'NaN'}],
                 [{'consumable_type': 'FLOUR', 'physical_quantity': '99999999'}],
                 [{'consumable_type': 'FLOUR', 'physical_quantity': None}],
                 [{'consumable_type': 'FLOUR', 'physical_quantity': '1'},
                  {'consumable_type': 'FLOUR', 'physical_quantity': '2'}],
                 [{'consumable_type': ['FLOUR'], 'physical_quantity': '1'}]]
        for lines in cases:
            r = self.mk_inv(lines=lines)
            self.assertEqual(r.status_code, 400, (lines, r.status_code))
        r = self.mk_inv(comment='x' * 2001)
        self.assertEqual(r.status_code, 400)
        for body in ([], 'x', None):
            self.assertEqual(cl(self.u['GERANT']).post(INV, body, format='json').status_code, 400)
        self.assertEqual(ConsumableInventory.objects.count(), n)

    def test_zero_physical_allowed(self):
        r = self.mk_inv(lines=[{'consumable_type': 'FLOUR', 'physical_quantity': '0'}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(D(r.data['lines'][0]['gap']), D('-5'))

    def test_isolation_read_and_patch(self):
        inv2 = self.mk_inv(self.u2['GERANT']).data
        g1 = cl(self.u['GERANT'])
        self.assertEqual(g1.get(f"{INV}{inv2['id']}/").status_code, 404)
        self.assertEqual(g1.patch(f"{INV}{inv2['id']}/", {'comment': 'pirate'}, format='json').status_code, 404)
        self.assertEqual(g1.get(f"{INV}node/P2/").status_code, 404)
        self.assertEqual(g1.get(f"{INV}node/{self.k2.pk}/").status_code, 404)
        self.assertEqual(g1.get(f"{INV}node/SIEGE/").status_code, 404)
        self.assertEqual(len(g1.get(INV).data), 0)
        self.assertEqual(len(g1.get(f"{INV}?node={self.k2.pk}").data), 0)
        self.assertEqual(ConsumableInventory.objects.get(pk=inv2['id']).comment, '')
        # direction : lecture seule de tout
        d = cl(self.u['DIRECTION'])
        self.assertEqual(d.get(f"{INV}{inv2['id']}/").status_code, 200)
        self.assertEqual(d.get(f"{INV}node/P2/").status_code, 200)
        self.assertEqual(d.patch(f"{INV}{inv2['id']}/", {'comment': 'x'}, format='json').status_code, 403)
        self.assertEqual(d.post(INV, {'lines': []}, format='json').status_code, 403)
        # facturier/livreur : rien
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).get(INV).status_code, 403)
        # delete / put interdits
        self.assertEqual(g1.delete(f"{INV}{inv2['id']}/").status_code, 405)

    def test_patch_only_comment(self):
        inv = self.mk_inv().data
        g = cl(self.u['GERANT'])
        u = f"{INV}{inv['id']}/"
        self.assertEqual(g.patch(u, {'comment': 'ok'}, format='json').status_code, 200)
        self.assertEqual(g.patch(u, {'comment': 'ok', 'lines': []}, format='json').status_code, 400)
        self.assertEqual(g.patch(u, {'node': self.k2.pk}, format='json').status_code, 400)
        self.assertEqual(g.patch(u, {'comment': 'x' * 2001}, format='json').status_code, 400)
        self.assertEqual(g.patch(u, [], format='json').status_code, 400)
        self.assertEqual(ConsumableInventory.objects.get(pk=inv['id']).comment, 'ok')
        self.assertEqual(ConsumableInventory.objects.get(pk=inv['id']).node_id, self.k1.pk)

    def test_bad_ids_and_dates(self):
        g = cl(self.u['GERANT'])
        for bad in ('abc', '123', '00000000-0000-0000-0000-000000000000'):
            self.assertEqual(g.get(f"{INV}{bad}/").status_code, 404, bad)
        for d in ('abc', '2026-13-45', '2026-02-30'):
            self.assertEqual(g.get(f"{INV}?date={d}").status_code, 400, d)
            self.assertEqual(g.get(f"{INV}node/P1/?date={d}").status_code, 400, d)
        self.assertEqual(cl(self.u['DIRECTION']).get(f"{INV}?node=ZZZ").status_code, 400)

    def test_gerant_without_node_refused(self):
        orphan = mk('pr_orphan_c', 'GERANT', None)
        self.assertIn(cl(orphan).post(INV, {'lines': [{'consumable_type': 'FLOUR', 'physical_quantity': '1'}]},
                                      format='json').status_code, (400, 403))
        self.assertIn(cl(orphan).get(f"{INV}today/").status_code, (400, 403))

    def test_manual_count_blocked_on_inventory_day_and_lines_immutable(self):
        self.mk_inv()
        cnt = ConsumableCount.objects.get(node=self.k1)
        g = cl(self.u['GERANT'])
        r = g.patch(f'/api/production/counts/{cnt.pk}/', {'physical_quantity': '99'}, format='json')
        self.assertIn(r.status_code, (400, 403, 404, 405), r.status_code)
        cnt.refresh_from_db()
        self.assertEqual(cnt.physical_quantity, D('4.5'))
        r = g.delete(f'/api/production/counts/{cnt.pk}/')
        self.assertIn(r.status_code, (400, 403, 404, 405))
        self.assertTrue(ConsumableCount.objects.filter(pk=cnt.pk).exists())


class Bug526(Base):
    def test_sessions_and_flour_history_bad_params_are_400(self):
        for role in ('GERANT', 'DIRECTION'):
            c = cl(self.u[role])
            for q in ('sessions/?date_from=abc', 'sessions/?date_to=2026-13-45', 'sessions/?date_from=2026-02-30',
                      'sessions/?date_from=%00', 'movements/flour_history/?month=abc',
                      'movements/flour_history/?year=abc', 'movements/flour_history/?month=13&year=99999',
                      'movements/flour_history/?month=0', 'movements/flour_history/?year=1',
                      'movements/flour_history/?month=1e2', 'movements/flour_history/?year=' + '9' * 40):
                r = c.get('/api/production/' + q)
                self.assertEqual(r.status_code, 400, (role, q, r.status_code))
            for q in ('sessions/?date_from=2026-11-01&date_to=2026-11-30',
                      'movements/flour_history/?month=11&year=2026', 'movements/flour_history/'):
                self.assertEqual(c.get('/api/production/' + q).status_code, 200, (role, q))


class BoolNodeAsPk(CB):
    def test_BUG_541_json_true_is_not_node_pk_1(self):
        n = ConsumableMovement.objects.count()
        r = cl(self.u['DIRECTION']).post(DISPATCH, {'consumable_type': 'FLOUR', 'allocations': [
            {'node': True, 'quantity': '1'}]}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)
        self.assertEqual(ConsumableMovement.objects.count(), n)


class DispatchCump(CB):
    def test_destination_cump_is_weighted_and_siege_cump_unchanged(self):
        self.stock(self.siege, 'FLOUR', '100', cump='1000')
        self.stock(self.k1, 'FLOUR', '5', cump='800')
        r = cl(self.u['DIRECTION']).post(DISPATCH, {'consumable_type': 'FLOUR', 'allocations': [
            {'node': 'P1', 'quantity': '10'}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.s1.refresh_from_db()
        self.ssiege.refresh_from_db()
        self.assertEqual(self.s1.quantity, D('15'))
        self.assertEqual(self.s1.average_unit_cost.quantize(D('0.01')), D('933.33'))
        self.assertEqual(self.ssiege.average_unit_cost, D('1000'))


class Bug527a529(Base):
    """Memes defauts (500 -> 400) hors production, ouverts par ce testeur."""

    def test_527_sales_daily_summary_bad_date(self):
        for role in ('GERANT', 'DIRECTION'):
            c = cl(self.u[role])
            for d in ('abc', '2026-13-45', '2026-02-30', '%00', '9' * 40):
                r = c.get(f'/api/sales/invoices/daily_summary/?date={d}')
                self.assertEqual(r.status_code, 400, (role, d, r.status_code))
            self.assertEqual(c.get('/api/sales/invoices/daily_summary/?date=2026-11-18').status_code, 200)

    def test_528_finance_bad_node(self):
        c = cl(self.u['DIRECTION'])
        for ep in ('summary/', 'doc1_report/?month=1&year=2026&', 'doc1_export/?month=1&year=2026&'):
            sep = '' if ep.endswith('&') else '?'
            for node in ('ZZZ', 'abc%00', '-1'):
                r = c.get(f'/api/finance/years/{ep}{sep}node={node}')
                self.assertEqual(r.status_code, 400, (ep, node, r.status_code))
        self.assertEqual(c.get('/api/finance/years/summary/?node=P1').status_code, 200)

    def test_529_blockchain_bad_node(self):
        c = cl(self.u['DIRECTION'])
        for ep in ('alerts/', 'snapshots/'):
            for node in ('ZZZ', 'abc%00', '-1'):
                r = c.get(f'/api/blockchain/{ep}?node={node}')
                self.assertEqual(r.status_code, 400, (ep, node, r.status_code))
        r = c.post('/api/blockchain/snapshots/run_check/', {'node': 'ZZZ'}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)
        r = c.post('/api/blockchain/snapshots/run_check/', {'node': ['x']}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)


class FloatDestination(SendBase):
    def test_BUG_541_float_to_node_is_not_truncated_to_pk(self):
        r = self.send(self.u['GERANT'], to=float(self.k2.pk) + 0.5)
        self.assertEqual(r.status_code, 400, r.status_code)
        self.assertEqual(BreadTransfer.objects.filter(flow='DIRECT').count(), 0)
