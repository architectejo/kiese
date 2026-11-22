"""BUG-540 / BUG-541 / BUG-562 + durcissement des identifiants et quantités entrants
(production). Données fictives uniquement."""
from decimal import Decimal as Dc

from core.models import Node
from core.tests.test_permissions_regression_2026_11_19 import cl
from production.models import BreadStock, BreadTransfer, ConsumableStock, ConsumableMovement
from production.tests.test_transfert_envoi_direct_a import DirectBase, avail

DISPATCH = '/api/production/consumables/dispatch/'
HUGE = 10 ** 30


class DirectDestination(DirectBase):
    def test_BUG_540_send_to_siege_refused(self):
        siege, _ = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siège', 'is_active': False})
        siege.is_active = True  # même actif, le nœud technique n'est pas une boulangerie
        siege.save()
        for dest in (siege.pk, 'SIEGE'):
            r = self.send(self.u['GERANT'], dest)
            self.assertEqual(r.status_code, 400, r.content)
            self.assertIn('detail', r.data)
        self.assert_nothing_written()

    def test_BUG_540_send_to_inactive_node_refused(self):
        n = Node.objects.create(code='KIN9', name='Inactive', is_active=False)
        r = self.send(self.u['GERANT'], n.pk)
        self.assertEqual(r.status_code, 400, r.content)
        self.assert_nothing_written()

    def test_BUG_541_bool_float_list_giant_to_node_refused(self):
        for bad in (True, False, self.k2.pk + 0.5, float(self.k2.pk), [self.k2.pk], {'a': 1},
                    HUGE, str(HUGE), '1' * 5000, -1, '1e0'):
            r = self.send(self.u['GERANT'], bad)
            self.assertEqual(r.status_code, 400, (str(bad)[:30], r.status_code))
            self.assertIn('detail', r.data)
        self.assert_nothing_written()

    def test_valid_destination_still_accepted_by_pk_and_code(self):
        self.assertEqual(self.send(self.u['GERANT'], self.k2.pk).status_code, 201)
        self.assertEqual(self.send(self.u['GERANT'], str(self.k2.pk)).status_code, 201)
        self.assertEqual(self.send(self.u['GERANT'], self.k2.code.lower()).status_code, 201)

    def test_bread_price_id_strict_on_send(self):
        for bad in (True, self.bp.pk + 0.0, float(self.bp.pk), [self.bp.pk], HUGE, '1' * 5000, 0, -3):
            r = self.send(self.u['GERANT'], self.k2.pk, lines=[{'bread_price': bad, 'quantity_sent': 1}])
            self.assertEqual(r.status_code, 400, (str(bad)[:30], r.status_code))
        self.assert_nothing_written()


class DispatchInputs(DirectBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        siege, _ = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siège', 'is_active': False})
        cls.sst, _ = ConsumableStock.objects.get_or_create(
            node=siege, consumable_type='FLOUR', defaults={'unit': 'sac', 'node_origin': 'SIEGE'})
        ConsumableStock.objects.filter(pk=cls.sst.pk).update(quantity=Dc('50'))

    def post(self, node, qty):
        return cl(self.u['DIRECTION']).post(DISPATCH, {
            'consumable_type': 'FLOUR', 'allocations': [{'node': node, 'quantity': qty}]}, format='json')

    def test_BUG_562_huge_or_odd_quantities_are_400_in_french(self):
        for q in ('1e400', '1E+999999', '-1e400', '9' * 60, '1' * 5000, 'NaN', 'Infinity', '-Infinity',
                  '1e-400', True, [1], {'a': 1}, '0.0001', '-1', '0', ''):
            r = self.post(self.k1.pk, q)
            self.assertEqual(r.status_code, 400, (str(q)[:30], r.status_code))
            self.assertIn('detail', r.data)
        self.assertFalse(ConsumableMovement.objects.filter(node_origin='SIEGE').exists())

    def test_BUG_562_raw_json_exponent_number(self):
        for q in ('1e400', '-1e400', '1e999999999'):
            body = '{"consumable_type":"FLOUR","allocations":[{"node":%d,"quantity":%s}]}' % (self.k1.pk, q)
            r = cl(self.u['DIRECTION']).post(DISPATCH, body, content_type='application/json')
            self.assertEqual(r.status_code, 400, (q, r.status_code))
            self.assertIn('detail', r.data)

    def test_BUG_541_bool_float_node_refused(self):
        for bad in (True, False, float(self.k1.pk), self.k1.pk + 0.5, [self.k1.pk], HUGE, '1' * 5000):
            r = self.post(bad, '1')
            self.assertEqual(r.status_code, 400, (str(bad)[:30], r.status_code))
        self.assertFalse(ConsumableMovement.objects.filter(node_origin='SIEGE').exists())

    def test_valid_dispatch_still_works(self):
        self.assertEqual(self.post(self.k1.pk, '1.5').status_code, 201)
        self.assertEqual(self.post(self.k2.code, 2).status_code, 201)


class OtherEntryPoints(DirectBase):
    def test_request_bread_price_bool_refused(self):
        before = BreadTransfer.objects.count()
        r = cl(self.u2['GERANT']).post('/api/production/transfers/', {
            'from_node': self.k1.pk, 'lines': [{'bread_price': True, 'quantity_sent': 1}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(BreadTransfer.objects.count(), before)

    def test_opening_confirmation_float_bread_price_refused(self):
        r = cl(self.u['GERANT']).post('/api/production/opening-confirmation/', {
            'team': 'A', 'lines': [{'bread_price': self.bp.pk + 0.7, 'qty': 3}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
