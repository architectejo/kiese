"""Testeur-production (Dev A, cycle 2026-11-22-a3) : nouveaux angles.

Transferts (somme nulle du groupe sur une SEQUENCE de validations, lignes
manquantes, roles, 3e boulangerie), fournees (valeur du sac figee, levure
0,25, lignes dupliquees, collisions, depassements), consommables direction
(approvisionnement SIEGE BUG-388, envoi, CUMP, inventaire), disposals.
Les tests @expectedFailure referencent leur ticket BUG-60x ; le testeur
retire la marque apres VERIFIE. Donnees fictives uniquement.
"""
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import BreadPrice, Node, User
from core.tests.test_permissions_regression_2026_11_19 import mk
from production.models import (BreadStock, BreadTransfer, ConsumableMovement, ConsumableStock,
                               ConsumableType, ProductionSession, _adjust_bread_stock)


def cl(user):
    """Client qui renvoie 500 au lieu de lever l'exception (detection des 500)."""
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(User.objects.get(pk=user.pk))  # utilisateur et noeud relus (pas de cache)
    return c


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code='Q1', name='Q K1', sac_value_fc=Dc('200000'), team_rotation_enabled=False)
        cls.k2 = Node.objects.create(code='Q2', name='Q K2', sac_value_fc=Dc('200000'), team_rotation_enabled=False)
        cls.k3 = Node.objects.create(code='Q3', name='Q K3', sac_value_fc=Dc('200000'), team_rotation_enabled=False)
        cls.g1 = mk('q_g1', 'GERANT', cls.k1)
        cls.g2 = mk('q_g2', 'GERANT', cls.k2)
        cls.g3 = mk('q_g3', 'GERANT', cls.k3)
        cls.fac = mk('q_fac', 'FACTURIER', cls.k1)
        cls.liv = mk('q_liv', 'LIVREUR', cls.k1)
        cls.adm = mk('q_adm', 'ADMIN', None)
        cls.dir = mk('q_dir', 'DIRECTION', None)
        cls.cpt = mk('q_cpt', 'COMPTABLE', None)
        cls.b3 = BreadPrice.objects.get_or_create(category='MINI', defaults={'label': 'P300', 'unit_price': 300})[0]
        cls.b5 = BreadPrice.objects.get_or_create(category='MOYEN', defaults={'label': 'P500', 'unit_price': 500})[0]
        for code, unit in (('FLOUR', 'sac'), ('YEAST', 'paquet')):
            ConsumableType.objects.get_or_create(code=code, defaults={'label': code, 'unit': unit})

    def stock(self, node, bp):
        s = BreadStock.objects.filter(node=node, bread_price=bp).first()
        return s.qty_available if s else 0

    def group(self, bp):
        return sum(s.qty_available for s in BreadStock.objects.filter(bread_price=bp))


class TransfersV2(Base):
    def setUp(self):
        _adjust_bread_stock(self.k1, self.b3, produced=100)
        _adjust_bread_stock(self.k1, self.b5, produced=100)

    def request(self, lines):
        r = cl(self.g2).post('/api/production/transfers/', {'from_node': self.k1.pk, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def respond(self, t, lines, user=None):
        return cl(user or self.g1).post(f'/api/production/transfers/{t}/respond_to_request/',
                                        {'approved': True, 'lines': lines}, format='json')

    def confirm(self, t, lines, user=None):
        return cl(user or self.g2).post(f'/api/production/transfers/{t}/confirm_reception/',
                                        {'lines': lines}, format='json')

    def test_sequence_98_105_98_100_keeps_group_sum(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 100}])
        self.respond(t, [{'bread_price': self.b3.pk, 'quantity_sent': 100}])
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k2, self.b3)), (0, 0))
        for q in (98, 105, 98, 100):
            r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': q}])
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.data['transfer_status'], 'CONFIRMED' if q == 100 else 'DISPUTED')
            self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k2, self.b3)), (0, q))
        self.assertEqual(self.group(self.b3), 100)
        r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 50}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.stock(self.k2, self.b3), 100)

    def test_dispute_blocks_closure_then_resolve_by_hq_only(self):
        from treasury.views import _unresolved_incoming_transfer_gap
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 100}])
        self.respond(t, [{'bread_price': self.b3.pk, 'quantity_sent': 100}])
        self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 98}])
        self.assertTrue(_unresolved_incoming_transfer_gap(self.k2))
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k3))
        body = {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'recompte'}
        url = f'/api/production/transfers/{t}/resolve_dispute/'
        self.assertEqual(cl(self.g2).post(url, body, format='json').status_code, 403)
        self.assertIn(cl(self.g3).post(url, body, format='json').status_code, (403, 404))
        self.assertEqual(cl(self.fac).post(url, body, format='json').status_code, 403)
        self.assertEqual(cl(self.adm).post(url, body, format='json').status_code, 200)
        self.assertEqual(self.group(self.b3), 100)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k2, self.b3)), (2, 98))
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k2))

    def test_roles_and_third_bakery_on_transfer_actions(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        url = f'/api/production/transfers/{t}/respond_to_request/'
        for u in (self.fac, self.liv):
            self.assertEqual(cl(u).post(url, {'approved': False}, format='json').status_code, 403, u.role)
        self.assertIn(cl(self.g3).post(url, {'approved': False}, format='json').status_code, (403, 404))
        self.assertEqual(cl(self.g2).post(url, {'approved': False}, format='json').status_code, 403)
        self.assertEqual(self.stock(self.k1, self.b3), 100)

    def test_invalid_quantities_on_confirm_are_400(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        self.respond(t, [{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        for q in (-1, 10 ** 12, '1e3', 2.5, True):
            r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': q}])
            self.assertEqual(r.status_code, 400, q)
        self.assertEqual(self.stock(self.k2, self.b3), 0)

    def test_request_to_invalid_supplier_is_400(self):
        for fn in (self.k2.pk, 999999, 'abc', None, True, [1]):
            r = cl(self.g2).post('/api/production/transfers/', {
                'from_node': fn, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 1}]}, format='json')
            self.assertEqual(r.status_code, 400, fn)

    def test_double_response_deducts_once(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        lines = [{'bread_price': self.b3.pk, 'quantity_sent': 10}]
        self.assertEqual(self.respond(t, lines).status_code, 200)
        self.assertEqual(self.respond(t, lines).status_code, 400)
        self.assertEqual(self.stock(self.k1, self.b3), 90)

    # ---- BUG-620 : lignes absentes / inconnues a la validation -------------
    def test_BUG_620_confirm_with_missing_line_keeps_group_sum(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}, {'bread_price': self.b5.pk, 'quantity_sent': 7}])
        self.respond(t, [{'bread_price': self.b3.pk, 'quantity_sent': 10}, {'bread_price': self.b5.pk, 'quantity_sent': 7}])
        r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 10}])  # b5 omise
        # BUG-620 (Dev A) : refus 400, aucun effet ; les 7 pains restent « en transit » (non credites)
        # et le transfert reste a valider, jusqu'a une validation COMPLETE qui restaure la somme 100.
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'RESPONDED')
        self.assertEqual(self.stock(self.k2, self.b5), 0)
        r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 10}, {'bread_price': self.b5.pk, 'quantity_received': 7}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.group(self.b5), 100)

    def test_BUG_620_confirm_with_unknown_bread_price_is_refused(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        self.respond(t, [{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        r = self.confirm(t, [{'bread_price': 999999, 'quantity_received': 10}])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.k2, self.b3), 0)  # aucun credit ; 10 pains en transit (K1 = 90)
        r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 10}])
        self.assertEqual(self.group(self.b3), 100)

    def test_BUG_620_direct_flow_partial_confirm_keeps_group_sum(self):
        r = cl(self.g1).post('/api/production/transfers/send/', {'to_node': self.k2.pk, 'lines': [
            {'bread_price': self.b3.pk, 'quantity_sent': 10}, {'bread_price': self.b5.pk, 'quantity_sent': 7}]},
            format='json')
        t = r.data['id']
        r = self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 10}])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.k2, self.b5), 0)
        self.confirm(t, [{'bread_price': self.b3.pk, 'quantity_received': 10}, {'bread_price': self.b5.pk, 'quantity_received': 7}])
        self.assertEqual(self.group(self.b5), 100)

    # ---- BUG-621 : `approved` non booleen -----------------------------------
    def test_BUG_621_approved_string_false_is_not_an_approval(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        cl(self.g1).post(f'/api/production/transfers/{t}/respond_to_request/', {
            'approved': 'false', 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 10}]}, format='json')
        self.assertEqual(self.stock(self.k1, self.b3), 100, "« false » traite comme une acceptation")

    # ---- BUG-624 : le fournisseur edite / supprime la demande d'autrui -----
    def test_BUG_624_supplier_cannot_delete_requesters_pending_request(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        r = cl(self.g1).delete(f'/api/production/transfers/{t}/')
        self.assertIn(r.status_code, (403, 404))
        self.assertTrue(BreadTransfer.objects.filter(pk=t).exists())

    def test_BUG_624_supplier_cannot_edit_requesters_pending_request(self):
        t = self.request([{'bread_price': self.b3.pk, 'quantity_sent': 10}])
        r = cl(self.g1).patch(f'/api/production/transfers/{t}/', {'notes': 'modifie par le fournisseur'}, format='json')
        self.assertIn(r.status_code, (403, 404))


class SessionsV2(Base):
    URL = '/api/production/sessions/'

    def body(self, **kw):
        b = {'team': 'A', 'date': '2026-11-10', 'flour_sacks_used': '1',
             'lines': [{'bread_price': self.b3.pk, 'quantity': 5}]}
        b.update(kw)
        return b

    def test_value_of_sac_frozen_and_levure_decimal(self):
        c = cl(self.g1)
        r = c.post(self.URL, self.body(
            team='B', date='2026-11-12', flour_sacks_used='1.5',
            lines=[{'bread_price': self.b5.pk, 'quantity': 20}],
            consumables_used=[{'consumable_type': 'YEAST', 'quantity': '0.25'},
                              {'consumable_type': 'YEAST', 'quantity': '0.25'}]), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.data['id']
        self.assertEqual((r.data['theoretical_yield'], r.data['total_fc_produced']), (300000, 10000))
        self.assertEqual(r.data['yield_gap'], 10000 - 300000)  # manquant signe negatif
        Node.objects.filter(pk=self.k1.pk).update(sac_value_fc=Dc('250000'))
        c = cl(self.g1)  # noeud relu : nouvelle valeur du sac
        r = c.patch(f'{self.URL}{sid}/', {'flour_sacks_used': '2'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['theoretical_yield'], 400000)  # valeur figee 200 000 x 2
        self.assertEqual(ConsumableStock.objects.get(node=self.k1, consumable_type='FLOUR').quantity, Dc('-2'))
        self.assertEqual(ConsumableStock.objects.get(node=self.k1, consumable_type='YEAST').quantity, Dc('-0.50'))
        r = c.post(self.URL, self.body(date='2026-11-13', lines=[{'bread_price': self.b5.pk, 'quantity': 5}]), format='json')
        self.assertEqual(r.data['theoretical_yield'], 250000)
        self.assertEqual(c.get(f'{self.URL}{sid}/').data['sac_value_fc_used'], 200000)

    def test_invalid_team_negative_and_unknown_lines_are_400(self):
        for t in ('C', 'a', 'JOUR', '', None):
            self.assertEqual(cl(self.g1).post(self.URL, self.body(team=t), format='json').status_code, 400, t)
        self.assertEqual(cl(self.g1).post(self.URL, self.body(
            lines=[{'bread_price': self.b3.pk, 'quantity': -5}]), format='json').status_code, 400)
        self.assertEqual(cl(self.g1).post(self.URL, self.body(
            lines=[{'bread_price': 999999, 'quantity': 5}]), format='json').status_code, 400)
        for lines in ('abc', {'a': 1}, 5, [1, 2], [None]):
            self.assertEqual(cl(self.g1).post(self.URL, self.body(lines=lines), format='json').status_code, 400, lines)
        self.assertFalse(ProductionSession.objects.exists())

    # ---- BUG-622 : contraintes d'unicite -> 500 -----------------------------
    def test_BUG_622_duplicate_category_lines_on_create(self):
        r = cl(self.g1).post(self.URL, self.body(lines=[
            {'bread_price': self.b3.pk, 'quantity': 5}, {'bread_price': self.b3.pk, 'quantity': 3}]), format='json')
        self.assertLess(r.status_code, 500)

    def test_BUG_622_duplicate_category_lines_on_patch(self):
        c = cl(self.g1)
        sid = c.post(self.URL, self.body(), format='json').data['id']
        r = c.patch(f'{self.URL}{sid}/', {'lines': [
            {'bread_price': self.b3.pk, 'quantity': 5}, {'bread_price': self.b3.pk, 'quantity': 2}]}, format='json')
        self.assertLess(r.status_code, 500)

    def test_BUG_622_patch_date_onto_existing_session(self):
        c = cl(self.g1)
        c.post(self.URL, self.body(date='2026-11-10'), format='json')
        sid = c.post(self.URL, self.body(date='2026-11-11'), format='json').data['id']
        r = c.patch(f'{self.URL}{sid}/', {'date': '2026-11-10'}, format='json')
        self.assertLess(r.status_code, 500)

    # ---- BUG-623 : depassements numeriques -> 500 ---------------------------
    def test_BUG_623_huge_line_quantity(self):
        r = cl(self.g1).post(self.URL, self.body(lines=[{'bread_price': self.b5.pk, 'quantity': 10 ** 17}]), format='json')
        self.assertLess(r.status_code, 500)

    def test_BUG_623_disposal_total_value_overflow(self):
        sess = ProductionSession.objects.create(node=self.k1, team='A', date='2026-11-10', flour_sacks_used=Dc('1'))
        r = cl(self.g1).post('/api/production/disposals/', {
            'session': str(sess.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD',
            'quantity': 10 ** 9, 'unit_price_sold': 5000}, format='json')
        self.assertLess(r.status_code, 500)
        self.assertEqual(self.stock(self.k1, self.b5), 0 if r.status_code >= 400 else -10 ** 9)


class DisposalsV2(Base):
    def test_disposal_types_decrement_stock_remaining_does_not(self):
        sess = ProductionSession.objects.create(node=self.k1, team='A', date='2026-11-10', flour_sacks_used=Dc('1'))
        _adjust_bread_stock(self.k1, self.b5, produced=50)
        ids = {}
        for t, q in (('DECLASSED', 5), ('UNSOLD', 3), ('FREE_DIST', 2), ('REMAINING', 7)):
            r = cl(self.g1).post('/api/production/disposals/', {
                'session': str(sess.pk), 'bread_price': self.b5.pk, 'disposal_type': t, 'quantity': q,
                'unit_price_sold': 0}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
            ids[t] = r.data['id']
        self.assertEqual(self.stock(self.k1, self.b5), 40)
        r = cl(self.g1).delete(f'/api/production/disposals/{ids["UNSOLD"]}/')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.stock(self.k1, self.b5), 43)
        r = cl(self.g1).patch(f'/api/production/disposals/{ids["DECLASSED"]}/', {'quantity': 1}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.stock(self.k1, self.b5), 47)
        # roles et autre boulangerie
        self.assertEqual(cl(self.fac).delete(f'/api/production/disposals/{ids["FREE_DIST"]}/').status_code, 403)
        self.assertEqual(cl(self.g2).delete(f'/api/production/disposals/{ids["FREE_DIST"]}/').status_code, 404)
        # un soldee ne se cree plus ici (BUG-092) ; negatif refuse hors reste
        r = cl(self.g1).post('/api/production/disposals/', {
            'session': str(sess.pk), 'bread_price': self.b5.pk, 'disposal_type': 'SOLD_DISCOUNT', 'quantity': 1}, format='json')
        self.assertEqual(r.status_code, 400)
        r = cl(self.g1).post('/api/production/disposals/', {
            'session': str(sess.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD', 'quantity': -1}, format='json')
        self.assertEqual(r.status_code, 400)


class ConsumablesDirectionV2(Base):
    def siege_stock(self, code='YEAST'):
        from production.consumables_direction import siege_node
        s, _ = ConsumableStock.objects.get_or_create(node=siege_node(), consumable_type=code, defaults={'unit': 'paquet'})
        return s

    # ---- BUG-388 : contrat backend de l'ecran « Approvisionner le stock direction »
    def test_bug388_contract_list_then_entry_by_admin_and_direction(self):
        from production.consumables_direction import siege_node
        sn = siege_node()
        for u, price, qty, expected_total, expected_avg in (
                (self.adm, '1000', '10', Dc('10'), Dc('1000')),
                (self.dir, '2000', '10', Dc('20'), Dc('1500'))):
            c = cl(u)
            r = c.get('/api/production/stocks/', {'node': sn.pk, 'consumable_type': 'YEAST'})
            self.assertEqual(r.status_code, 200)
            rows = r.data['results'] if isinstance(r.data, dict) else r.data
            self.assertEqual(len(rows), 1)
            r = c.post('/api/production/movements/', {
                'node': sn.pk, 'stock': rows[0]['id'], 'movement_type': 'ENTRY', 'quantity': qty,
                'unit_price': price, 'description': 'Approvisionnement stock direction'}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
            s = ConsumableStock.objects.get(pk=rows[0]['id'])
            self.assertEqual((s.quantity, s.average_unit_cost), (expected_total, expected_avg))
        g = cl(self.dir).get('/api/production/consumables/global/')
        self.assertEqual(g.data['direction']['stocks']['YEAST'], '20.000')
        self.assertEqual(g.data['totals_group']['YEAST'], '20.000')

    def test_bug388_gerant_cannot_touch_direction_stock(self):
        s = self.siege_stock()
        r = cl(self.g1).post('/api/production/movements/', {
            'node': s.node_id, 'stock': s.pk, 'movement_type': 'ENTRY', 'quantity': '5'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(cl(self.fac).post('/api/production/movements/', {
            'stock': s.pk, 'movement_type': 'ENTRY', 'quantity': '5'}, format='json').status_code, 403)
        s.refresh_from_db()
        self.assertEqual(s.quantity, 0)

    # ---- BUG-625 (A CLARIFIER) : COMPTABLE ecrit dans le stock direction --
    def test_BUG_625_comptable_cannot_supply_direction_stock(self):
        s = self.siege_stock()
        r = cl(self.cpt).post('/api/production/movements/', {
            'node': s.node_id, 'stock': s.pk, 'movement_type': 'ENTRY', 'quantity': '5', 'unit_price': '100'},
            format='json')
        self.assertEqual(r.status_code, 403, r.content)

    def test_dispatch_sequence_atomic_refusal_then_success_cump_kept(self):
        s = self.siege_stock()
        cl(self.dir).post('/api/production/movements/', {
            'stock': s.pk, 'movement_type': 'ENTRY', 'quantity': '10', 'unit_price': '1000'}, format='json')
        c = cl(self.dir)
        r = c.post('/api/production/consumables/dispatch/', {'consumable_type': 'YEAST', 'allocations': [
            {'node': self.k1.pk, 'quantity': '4.25'}, {'node': 'Q2', 'quantity': '7'}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        s.refresh_from_db()
        self.assertEqual(s.quantity, Dc('10'))
        self.assertFalse(ConsumableMovement.objects.filter(node=self.k1).exists())
        r = c.post('/api/production/consumables/dispatch/', {'consumable_type': 'YEAST', 'allocations': [
            {'node': self.k1.pk, 'quantity': '4.25'}, {'node': 'Q2', 'quantity': '5.75'}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        s.refresh_from_db()
        self.assertEqual(s.quantity, Dc('0'))
        k1s = ConsumableStock.objects.get(node=self.k1, consumable_type='YEAST')
        self.assertEqual((k1s.quantity, k1s.average_unit_cost), (Dc('4.25'), Dc('1000')))
        self.assertEqual(c.get('/api/production/consumables/global/').data['totals_group']['YEAST'], '10.000')
        r = c.post('/api/production/consumables/dispatch/', {'consumable_type': 'YEAST', 'allocations': [
            {'node': self.k1.pk, 'quantity': '0.001'}]}, format='json')
        self.assertEqual(r.status_code, 400)  # stock direction epuise
        for u in (self.g1, self.cpt, self.fac):
            r = cl(u).post('/api/production/consumables/dispatch/', {'consumable_type': 'YEAST', 'allocations': [
                {'node': self.k1.pk, 'quantity': '1'}]}, format='json')
            self.assertEqual(r.status_code, 403, u.role)

    def test_inventory_roles_gap_once_a_day_and_isolation(self):
        ConsumableStock.objects.update_or_create(node=self.k1, consumable_type='YEAST',
                                                 defaults={'quantity': Dc('3.5'), 'unit': 'paquet'})
        body = {'lines': [{'consumable_type': 'YEAST', 'physical_quantity': '3.25'}], 'comment': 'ok'}
        for u in (self.fac, self.dir, self.cpt, self.adm):
            self.assertEqual(cl(u).post('/api/production/inventories/', body, format='json').status_code, 403, u.role)
        r = cl(self.g1).post('/api/production/inventories/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['lines'][0]['gap'], '-0.250')
        self.assertEqual(cl(self.g1).post('/api/production/inventories/', body, format='json').status_code, 400)
        inv_id = r.data['id']
        self.assertEqual(cl(self.g2).get(f'/api/production/inventories/{inv_id}/').status_code, 404)
        self.assertEqual(cl(self.dir).get(f'/api/production/inventories/{inv_id}/').status_code, 200)
        # une ligne d'inventaire n'est ni modifiable ni supprimable par /counts/
        line = r.data['lines'][0]['id']
        self.assertEqual(cl(self.g1).delete(f'/api/production/counts/{line}/').status_code, 400)

    def test_inventory_invalid_lines_are_400_and_write_nothing(self):
        for ln in ({'consumable_type': 'YEAST', 'physical_quantity': '1e400'},
                   {'consumable_type': 'YEAST', 'physical_quantity': '-1'},
                   {'consumable_type': 'YEAST', 'physical_quantity': '0.0001'},
                   {'consumable_type': 'ZZZ', 'physical_quantity': '1'},
                   {'consumable_type': ['x'], 'physical_quantity': '1'},
                   {'consumable_type': 'YEAST', 'physical_quantity': [1]}, 'abc', None):
            r = cl(self.g1).post('/api/production/inventories/', {'lines': [ln]}, format='json')
            self.assertEqual(r.status_code, 400, ln)
        self.assertEqual(self.k1.consumable_counts.count(), 0)

    def test_movement_sequence_stock_equals_signed_sum(self):
        s = ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='YEAST', defaults={'unit': 'paquet'})[0]
        c = cl(self.g1)
        ids = []
        for typ, q in (('ENTRY', '2.5'), ('EXIT', '0.25'), ('ENTRY', '1'), ('EXIT', '0.75')):
            r = c.post('/api/production/movements/', {'stock': s.pk, 'movement_type': typ, 'quantity': q,
                                                       'unit_price': '100'}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
            ids.append(r.data['id'])
        s.refresh_from_db()
        self.assertEqual(s.quantity, Dc('2.5') - Dc('0.25') + 1 - Dc('0.75'))
        self.assertEqual(c.patch(f'/api/production/movements/{ids[1]}/', {'quantity': '0.50'}, format='json').status_code, 200)
        self.assertEqual(c.delete(f'/api/production/movements/{ids[0]}/').status_code, 204)
        s.refresh_from_db()
        total = sum((m._signed_effect() for m in ConsumableMovement.objects.filter(stock=s)), Dc('0'))
        self.assertEqual(s.quantity, total)
        self.assertEqual(total, Dc('1') - Dc('0.50') - Dc('0.75'))
