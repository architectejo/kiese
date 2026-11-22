"""Testeur-production (Dev A, cycle 2026-11-22-a4) : verification des correctifs
BUG-540/541/562/612/620/621/622/623/624/627 et nouveaux angles. Donnees fictives.
Les tests `@expectedFailure` referencent leur ticket BUG-65x ; le testeur retire la
marque apres VERIFIE.
"""
from datetime import date as ddate, timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.models import Node
from production.models import (BreadDisposal, BreadStock, BreadTransfer, ProductionSession,
                               ProductionSessionLine, _adjust_bread_stock)
from production.tests.test_production_v2_a3 import Base, cl

T = '/api/production/transfers/'


class TBase(Base):
    def setUp(self):
        _adjust_bread_stock(self.k1, self.b3, produced=100)
        _adjust_bread_stock(self.k1, self.b5, produced=100)

    def request(self, lines, user=None, frm=None):
        r = cl(user or self.g2).post(T, {'from_node': (frm or self.k1).pk, 'lines': lines}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def respond(self, t, lines=None, user=None, approved=True):
        body = {'approved': approved}
        if lines is not None:
            body['lines'] = lines
        return cl(user or self.g1).post(f'{T}{t}/respond_to_request/', body, format='json')

    def confirm(self, t, lines, user=None):
        return cl(user or self.g2).post(f'{T}{t}/confirm_reception/', {'lines': lines}, format='json')

    def send(self, lines, user=None, to=None):
        return cl(user or self.g1).post(f'{T}send/', {'to_node': (to or self.k2).pk, 'lines': lines}, format='json')

    def L(self, bp, q, key='quantity_sent'):
        return {'bread_price': bp.pk, key: q}


class Bug620Neighbourhood(TBase):
    """Voisinage de BUG-620 : ligne a 0, doublons, categories, flux direct, expediteur."""

    def test_all_lines_zero_is_dispute_blocks_closure_and_resolves(self):
        from treasury.views import _unresolved_incoming_transfer_gap
        t = self.request([self.L(self.b3, 10), self.L(self.b5, 7)])
        self.respond(t, [self.L(self.b3, 10), self.L(self.b5, 7)])
        r = self.confirm(t, [self.L(self.b3, 0, 'quantity_received'), self.L(self.b5, 0, 'quantity_received')])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['transfer_status'], 'DISPUTED')
        self.assertTrue(_unresolved_incoming_transfer_gap(self.k2))
        self.assertEqual((self.group(self.b3), self.group(self.b5)), (90, 93))
        url = f'{T}{t}/resolve_dispute/'
        r = cl(self.dir).post(url, {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'rien recu'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self.group(self.b3), self.group(self.b5)), (100, 100))  # ALIGN_ON_RECEIVED : K1 retrouve ses pains
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (100, 100))
        self.assertFalse(_unresolved_incoming_transfer_gap(self.k2))
        # transfert resolu : plus de re-validation ni de second credit
        self.assertEqual(self.confirm(t, [self.L(self.b3, 10, 'quantity_received'),
                                          self.L(self.b5, 7, 'quantity_received')]).status_code, 400)
        self.assertEqual(self.stock(self.k2, self.b3), 0)

    def test_line_without_quantity_received_counts_as_zero_dispute(self):
        t = self.request([self.L(self.b3, 10)])
        self.respond(t, [self.L(self.b3, 10)])
        r = self.confirm(t, [{'bread_price': self.b3.pk}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['transfer_status'], 'DISPUTED')
        self.assertEqual(self.stock(self.k2, self.b3), 0)

    def test_duplicates_string_and_int_ids_and_none_refused_without_effect(self):
        t = self.request([self.L(self.b3, 10)])
        self.respond(t, [self.L(self.b3, 10)])
        for lines in (
            [self.L(self.b3, 5, 'quantity_received'), {'bread_price': str(self.b3.pk), 'quantity_received': 5}],
            [{'quantity_received': 10}], [{'bread_price': None, 'quantity_received': 10}],
            [self.L(self.b3, 10, 'quantity_received'), self.L(self.b5, 1, 'quantity_received')],
            [], 'abc', {'bread_price': self.b3.pk}, [None], [5],
        ):
            r = self.confirm(t, lines)
            self.assertEqual(r.status_code, 400, (lines, r.content))
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'RESPONDED')
        self.assertEqual(self.stock(self.k2, self.b3), 0)

    def test_huge_negative_and_weird_received_quantities(self):
        t = self.request([self.L(self.b3, 10)])
        self.respond(t, [self.L(self.b3, 10)])
        for q in (-1, 10 ** 12, 2_000_000_001, '1e3', 2.5, True, None, [], {}):
            r = self.confirm(t, [self.L(self.b3, q, 'quantity_received')])
            self.assertEqual(r.status_code, 400, (q, r.content))
        self.assertEqual(self.stock(self.k2, self.b3), 0)

    def test_overreception_then_exact_keeps_group_sum(self):
        t = self.request([self.L(self.b3, 10)])
        self.respond(t, [self.L(self.b3, 10)])
        r = self.confirm(t, [self.L(self.b3, 2_000_000_000, 'quantity_received')])
        self.assertEqual(r.status_code, 200, r.content)  # sur-reception : litige
        self.assertEqual(r.data['transfer_status'], 'DISPUTED')
        r = self.confirm(t, [self.L(self.b3, 10, 'quantity_received')])
        self.assertEqual(r.data['transfer_status'], 'CONFIRMED')
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k2, self.b3), self.group(self.b3)), (90, 10, 100))

    def test_direct_flow_sender_cannot_confirm_third_party_neither(self):
        r = self.send([self.L(self.b3, 10), self.L(self.b5, 7)])
        self.assertEqual(r.status_code, 201, r.content)
        t = r.data['id']
        full = [self.L(self.b3, 10, 'quantity_received'), self.L(self.b5, 7, 'quantity_received')]
        self.assertEqual(self.confirm(t, full, user=self.g1).status_code, 403)  # l'emetteur
        self.assertIn(self.confirm(t, full, user=self.g3).status_code, (403, 404))
        self.assertEqual(self.confirm(t, full, user=self.fac).status_code, 403)
        self.assertEqual(self.confirm(t, full, user=self.liv).status_code, 403)
        self.assertEqual(self.stock(self.k2, self.b3), 0)
        self.assertEqual(self.confirm(t, full).status_code, 200)
        self.assertEqual(self.confirm(t, full).status_code, 400)  # double validation
        self.assertEqual((self.stock(self.k2, self.b3), self.stock(self.k2, self.b5)), (10, 7))
        self.assertEqual((self.group(self.b3), self.group(self.b5)), (100, 100))

    def test_hq_can_confirm_and_sum_is_preserved(self):
        r = self.send([self.L(self.b3, 10)])
        t = r.data['id']
        self.assertEqual(self.confirm(t, [self.L(self.b3, 10, 'quantity_received')], user=self.dir).status_code, 200)
        self.assertEqual(self.group(self.b3), 100)

    def test_confirm_on_pending_or_cancelled_request_refused(self):
        t = self.request([self.L(self.b3, 10)])
        self.assertEqual(self.confirm(t, [self.L(self.b3, 10, 'quantity_received')]).status_code, 400)
        self.respond(t, approved=False)
        self.assertEqual(self.confirm(t, [self.L(self.b3, 10, 'quantity_received')]).status_code, 400)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k2, self.b3)), (100, 0))

    def test_multiline_three_categories_sequence_group_sum(self):
        from core.models import BreadPrice
        b2 = BreadPrice.objects.get_or_create(category='GRAND', defaults={'label': 'P200', 'unit_price': 200})[0]
        _adjust_bread_stock(self.k1, b2, produced=50)
        r = self.send([self.L(self.b3, 10), self.L(self.b5, 20), self.L(b2, 30)])
        t = r.data['id']
        for q3, q5, q2 in ((10, 19, 30), (0, 20, 31), (10, 20, 30)):
            self.confirm(t, [self.L(self.b3, q3, 'quantity_received'), self.L(self.b5, q5, 'quantity_received'),
                             self.L(b2, q2, 'quantity_received')])
            # pendant un litige, le manquant (envoye - recu) est le seul ecart du groupe
            self.assertEqual((self.group(self.b3), self.group(self.b5), self.group(b2)),
                             (100 - (10 - q3), 100 - (20 - q5), 50 - (30 - q2)))
        self.assertEqual((self.group(self.b3), self.group(self.b5), self.group(b2)), (100, 100, 50))
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'CONFIRMED')


class Bug621Neighbourhood(TBase):
    def test_approved_exotic_values(self):
        t = self.request([self.L(self.b3, 10)])
        for bad in (None, {}, 'null', ' ', 'yes', 'vrai', 2, -1, 0.0, 1.0, ['true'], '١'):
            r = self.respond(t, [self.L(self.b3, 10)], approved=bad)
            self.assertEqual(r.status_code, 400, (bad, r.content))
        self.assertEqual(self.stock(self.k1, self.b3), 100)
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')
        r = self.respond(t, [self.L(self.b3, 10)], approved=' TRUE ')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.stock(self.k1, self.b3), 90)

    def test_approved_form_encoded(self):
        t = self.request([self.L(self.b3, 10)])
        c = cl(self.g1)
        r = c.post(f'{T}{t}/respond_to_request/', {'approved': '0'})  # multipart
        self.assertEqual(r.status_code, 400, r.content)
        r = c.post(f'{T}{t}/respond_to_request/', {'approved': 'false'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['transfer_status'], 'CANCELLED')
        self.assertEqual(self.stock(self.k1, self.b3), 100)

    def test_refusal_then_second_response_refused(self):
        t = self.request([self.L(self.b3, 10)])
        self.assertEqual(self.respond(t, approved=False).status_code, 200)
        self.assertEqual(self.respond(t, [self.L(self.b3, 10)]).status_code, 400)
        self.assertEqual(self.stock(self.k1, self.b3), 100)

    def test_respond_bad_quantities_and_lines_no_effect(self):
        t = self.request([self.L(self.b3, 10)])
        for q in (-1, 10 ** 12, 2.5, '1e3', True, None):
            r = self.respond(t, [self.L(self.b3, q)])
            self.assertEqual(r.status_code, 400, (q, r.content))
        for lines in ('abc', {'a': 1}, [None], [5], []):
            r = self.respond(t, lines)
            self.assertEqual(r.status_code, 400, (lines, r.content))
        self.assertEqual(self.stock(self.k1, self.b3), 100)
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')

    @expectedFailure  # BUG-652
    def test_BUG_652_respond_with_unknown_category_is_not_silently_ignored(self):
        """Reponse positive avec une categorie absente de la demande : ignoree en silence
        (`continue`) puis les quantites DEMANDEES sont deduites : l'emettrice croit avoir
        corrige. Attendu 400 (comme BUG-620 a la reception)."""
        t = self.request([self.L(self.b3, 10)])
        r = self.respond(t, [self.L(self.b5, 99)])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.k1, self.b3), 100)

    @expectedFailure  # BUG-652
    def test_BUG_652_respond_with_all_quantities_zero_is_not_a_positive_response(self):
        t = self.request([self.L(self.b3, 10)])
        r = self.respond(t, [self.L(self.b3, 0)])
        self.assertEqual(r.status_code, 400, r.content)


class Bug624Neighbourhood(TBase):
    def test_pending_request_actors(self):
        t = self.request([self.L(self.b3, 10)])
        u = f'{T}{t}/'
        for who, code in ((self.g1, 403), (self.fac, 403), (self.liv, 403)):
            self.assertEqual(cl(who).patch(u, {'notes': 'x'}, format='json').status_code, code, who.role)
            self.assertEqual(cl(who).delete(u).status_code, code, who.role)
        for who in (self.g3,):
            self.assertEqual(cl(who).patch(u, {'notes': 'x'}, format='json').status_code, 404)
            self.assertEqual(cl(who).delete(u).status_code, 404)
        self.assertEqual(cl(self.g2).patch(u, {'notes': 'ok'}, format='json').status_code, 200)
        self.assertEqual(cl(self.dir).patch(u, {'notes': 'siege'}, format='json').status_code, 200)
        self.assertEqual(cl(self.adm).delete(u).status_code, 204)

    def test_pending_request_immutable_fields_and_status(self):
        t = self.request([self.L(self.b3, 10)])
        u = f'{T}{t}/'
        siege = Node.objects.get(code='SIEGE')
        for body in ({'from_node': siege.pk}, {'from_node': self.k3.pk}, {'to_node': self.k1.pk},
                     {'initiated_by': self.g1.pk}, {'from_node': self.k2.pk}):
            self.assertEqual(cl(self.g2).patch(u, body, format='json').status_code, 400, body)
        r = cl(self.g2).patch(u, {'transfer_status': 'CONFIRMED', 'flow': 'DIRECT', 'confirmed_by': self.g2.pk,
                                  'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 99}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        tr = BreadTransfer.objects.get(pk=t)
        self.assertEqual((tr.transfer_status, tr.flow, tr.lines.get().quantity_sent), ('PENDING', 'REQUEST', 10))

    def test_direct_flow_actors(self):
        r = self.send([self.L(self.b3, 10)])
        t = r.data['id']
        u = f'{T}{t}/'
        # RESPONDED : plus modifiable ni supprimable par personne (BUG-223), meme l'emettrice / le siege
        for who in (self.g1, self.g2, self.dir):
            self.assertEqual(cl(who).patch(u, {'notes': 'x'}, format='json').status_code, 400, who.role)
            self.assertEqual(cl(who).delete(u).status_code, 400, who.role)
        self.assertTrue(BreadTransfer.objects.filter(pk=t).exists())
        self.assertEqual(self.stock(self.k1, self.b3), 90)

    def test_cancelled_request_delete_rules(self):
        t = self.request([self.L(self.b3, 10)])
        self.respond(t, approved=False)
        self.assertEqual(cl(self.g1).delete(f'{T}{t}/').status_code, 403)
        self.assertEqual(cl(self.g2).delete(f'{T}{t}/').status_code, 204)
        self.assertEqual((self.stock(self.k1, self.b3), self.group(self.b3)), (100, 100))


class Bug540627Neighbourhood(TBase):
    def test_send_destinations_and_lines(self):
        siege = Node.objects.get(code='SIEGE')
        k9 = Node.objects.create(code='P9', name='Ferme', is_active=False)
        for to in (siege.pk, 'SIEGE', 'siege', ' SIEGE ', k9.pk, 'P9', self.k1.pk, 'Q1', 0, -1, True, 1.0, '1.0', None,
                   '', [], {}, '१', 2 ** 31, 10 ** 40, 'DROP TABLE'):
            r = cl(self.g1).post(f'{T}send/', {'to_node': to, 'lines': [self.L(self.b3, 1)]}, format='json')
            self.assertEqual(r.status_code, 400, (to, r.content))
        self.assertEqual(self.stock(self.k1, self.b3), 100)
        self.assertFalse(BreadTransfer.objects.exists())

    def test_send_lines_negative_huge_duplicate_overstock(self):
        for lines in ([self.L(self.b3, -5)], [self.L(self.b3, 0)], [self.L(self.b3, 10 ** 12)], [self.L(self.b3, 101)],
                      [self.L(self.b3, 60), self.L(self.b3, 60)], [self.L(self.b3, 1.5)], [self.L(self.b3, '1e2')],
                      [], 'x', [None], [self.L(self.b3, 5), self.L(self.b5, 101)]):
            r = cl(self.g1).post(f'{T}send/', {'to_node': self.k2.pk, 'lines': lines}, format='json')
            self.assertEqual(r.status_code, 400, (lines, r.content))
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (100, 100))
        r = self.send([self.L(self.b3, 40), self.L(self.b3, 60)])  # doublons cumules, exactement le stock
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.stock(self.k1, self.b3), 0)
        self.assertEqual(self.send([self.L(self.b3, 1)]).status_code, 400)  # stock epuise

    def test_send_roles_and_nodeless_users(self):
        for who in (self.fac, self.liv):
            self.assertEqual(self.send([self.L(self.b3, 1)], user=who).status_code, 403, who.role)
        for who in (self.adm, self.dir, self.cpt):  # siege : pas de boulangerie emettrice
            self.assertEqual(self.send([self.L(self.b3, 1)], user=who).status_code, 400, who.role)
        self.assertEqual(self.stock(self.k1, self.b3), 100)

    def test_send_body_not_object_and_notes_types(self):
        c = cl(self.g1)
        for body in ([], 'x', 5, None):
            self.assertLess(c.post(f'{T}send/', body, format='json').status_code, 500, body)
        for notes in (5, ['a'], {'a': 1}):
            r = c.post(f'{T}send/', {'to_node': self.k2.pk, 'lines': [self.L(self.b3, 1)], 'notes': notes}, format='json')
            self.assertEqual(r.status_code, 400, notes)
        r = c.post(f'{T}send/', {'to_node': self.k2.pk, 'lines': [self.L(self.b3, 1)], 'notes': 'x' * 100000}, format='json')
        self.assertLess(r.status_code, 500)

    def test_request_supplier_exotic_ids(self):
        siege = Node.objects.get(code='SIEGE')
        k9 = Node.objects.create(code='P9', name='Ferme', is_active=False)
        for fn in (siege.pk, k9.pk, 'SIEGE', 'Q1', self.k2.pk, '', 0, -1, 2 ** 40, '1e1', 'null'):
            r = cl(self.g2).post(T, {'from_node': fn, 'lines': [self.L(self.b3, 1)]}, format='json')
            self.assertEqual(r.status_code, 400, (fn, r.content))
        self.assertFalse(BreadTransfer.objects.exists())

    def test_request_lines_invalid(self):
        for lines in ([self.L(self.b3, -1)], [self.L(self.b3, 0)], [self.L(self.b3, 10 ** 12)], [self.L(self.b3, 2.5)],
                      [self.L(self.b3, None)], [], None, 'a', [None], [{'quantity_sent': 3}]):
            r = cl(self.g2).post(T, {'from_node': self.k1.pk, 'lines': lines}, format='json')
            self.assertEqual(r.status_code, 400, (lines, r.content))
        self.assertFalse(BreadTransfer.objects.exists())

    def test_inactive_bread_category_in_request_documented(self):
        from core.models import BreadPrice
        bp = BreadPrice.objects.create(category='AUTRE', label='P100X', unit_price=100, is_active=False) \
            if 'is_active' in [f.name for f in BreadPrice._meta.fields] else None
        if bp is None:
            self.skipTest('BreadPrice sans is_active')
        _adjust_bread_stock(self.k1, bp, produced=10)
        r = self.send([self.L(bp, 5)])
        self.assertIn(r.status_code, (201, 400))  # admis par BUG-540 (ecouler un reliquat)

    def test_isolation_third_bakery_sees_nothing(self):
        r = self.send([self.L(self.b3, 10)])
        t = r.data['id']
        self.assertEqual(cl(self.g3).get(T).data['count'] if isinstance(cl(self.g3).get(T).data, dict) and 'count' in cl(self.g3).get(T).data
                         else len(cl(self.g3).get(T).data), 0)
        self.assertEqual(cl(self.g3).get(f'{T}{t}/').status_code, 404)
        self.assertEqual(cl(self.g3).post(f'{T}{t}/resolve_dispute/', {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'},
                                          format='json').status_code, 404)
        self.assertEqual(self.stock(self.k3, self.b3), 0)

    def test_siege_node_user_cannot_request(self):
        # un compte de siege (sans boulangerie) ne peut ni demander ni envoyer
        r = cl(self.dir).post(T, {'from_node': self.k1.pk, 'lines': [self.L(self.b3, 1)]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class SessionCeilings(Base):
    URL = '/api/production/sessions/'

    def body(self, **kw):
        b = {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': '1',
             'lines': [{'bread_price': self.b5.pk, 'quantity': 5}]}
        b.update(kw)
        return b

    def test_exact_ceiling_accepted_and_one_more_refused(self):
        c = cl(self.g1)
        # 4 000 000 x 500 FC = 2 000 000 000 FC (plafond exact)
        r = c.post(self.URL, self.body(lines=[{'bread_price': self.b5.pk, 'quantity': 4_000_000}]), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['total_fc_produced'], 2_000_000_000)
        sid = r.data['id']
        # ajout du jour (cumul) : +1 pain au-dela du plafond
        r = c.post(self.URL, self.body(lines=[{'bread_price': self.b3.pk, 'quantity': 1}]), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = c.patch(f'{self.URL}{sid}/', {'lines': [{'bread_price': self.b5.pk, 'quantity': 4_000_001}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.total_fc_produced, 2_000_000_000)
        self.assertEqual(self.stock(self.k1, self.b5), 4_000_000)

    def test_many_lines_summing_over_ceiling_refused(self):
        r = cl(self.g1).post(self.URL, self.body(lines=[
            {'bread_price': self.b5.pk, 'quantity': 3_000_000}, {'bread_price': self.b3.pk, 'quantity': 2_000_000}]),
            format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(ProductionSession.objects.exists())
        self.assertEqual(self.stock(self.k1, self.b5), 0)

    def test_weird_line_quantities(self):
        for q in (-1, 1.5, '1e3', 10 ** 40, 2 ** 63, None, True, 'NaN'):
            r = cl(self.g1).post(self.URL, self.body(lines=[{'bread_price': self.b5.pk, 'quantity': q}]), format='json')
            self.assertLess(r.status_code, 500, (q, r.content))
        self.assertEqual(self.stock(self.k1, self.b5), 0)

    def test_flour_sacks_edges_and_repeated_cumul(self):
        for v in ('100000.01', '-0.01', '0.001', 'NaN', 'Infinity', True, None, []):
            r = cl(self.g1).post(self.URL, self.body(flour_sacks_used=v, date='2026-01-05'), format='json')
            self.assertLess(r.status_code, 500, (v, r.content))
            self.assertEqual(r.status_code, 400, (v, r.content))
        for i in range(3):  # cumul d'un meme jour au plafond de sacs
            r = cl(self.g1).post(self.URL, self.body(flour_sacks_used='100000', lines=[], date='2026-01-06'), format='json')
            self.assertLess(r.status_code, 500, (i, r.content))

    def test_consumables_used_hostile_values(self):
        for cu in ([{'consumable_type': 'YEAST', 'quantity': q}] for q in (
                '1e400', '-1', '0.0004', 'NaN', 'Infinity', '9' * 50, True, [], {}, 10 ** 30, '٣', '0,25')):
            r = cl(self.g1).post(self.URL, self.body(consumables_used=cu, date='2026-02-01'), format='json')
            self.assertLess(r.status_code, 500, (cu, r.content))
            ProductionSession.objects.all().delete()
        r = cl(self.g1).post(self.URL, self.body(consumables_used=[{'consumable_type': 'ZZZ', 'quantity': 1}]), format='json')
        self.assertEqual(r.status_code, 400)

    def test_unique_date_team_and_isolation(self):
        c = cl(self.g1)
        sid = c.post(self.URL, self.body(date='2026-03-01'), format='json').data['id']
        other = c.post(self.URL, self.body(date='2026-03-01', team='B'), format='json').data['id']
        self.assertNotEqual(sid, other)
        r = c.patch(f'{self.URL}{other}/', {'team': 'A'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = c.put(f'{self.URL}{other}/', self.body(date='2026-03-01', team='A'), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        # 2e POST meme (equipe, date) : cumule, une seule session
        r = c.post(self.URL, self.body(date='2026-03-01'), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(ProductionSession.objects.filter(node=self.k1, team='A', date='2026-03-01').count(), 1)
        # autre boulangerie : memes (equipe, date) independants, jamais de fuite
        self.assertEqual(cl(self.g2).post(self.URL, self.body(date='2026-03-01'), format='json').status_code, 201)
        self.assertEqual(cl(self.g2).get(f'{self.URL}{sid}/').status_code, 404)
        self.assertEqual(cl(self.g2).patch(f'{self.URL}{sid}/', {'notes': 'x'}, format='json').status_code, 404)
        self.assertEqual(cl(self.g2).delete(f'{self.URL}{sid}/').status_code, 404)
        # le siege qui deplace une session vers un noeud ayant deja (equipe, date)
        r = cl(self.dir).patch(f'{self.URL}{sid}/', {'node': self.k2.pk}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        self.assertEqual(r.status_code, 400, r.content)

    def test_patch_with_carryover_line_respects_int32(self):
        """Valeur de la session = lignes DECLARED + CARRYOVER : le plafond doit couvrir le total."""
        s = ProductionSession.objects.create(node=self.k1, team='A', date='2026-04-01', flour_sacks_used=Dc('1'))
        ProductionSessionLine.objects.create(session=s, bread_price=self.b5, quantity=3_000_000,
                                             source=ProductionSessionLine.Source.CARRYOVER)
        r = cl(self.g1).patch(f'{self.URL}{s.pk}/', {'lines': [{'bread_price': self.b3.pk, 'quantity': 6_000_000}]},
                              format='json')
        s.refresh_from_db()
        self.assertLessEqual(s.total_fc_produced, 2_147_483_647, (r.status_code, s.total_fc_produced))

    def test_invalid_dates(self):
        for d in ('2026-13-45', '0000-00-00', 'abc', None, 20260101, '', '99999-01-01'):
            r = cl(self.g1).post(self.URL, self.body(date=d), format='json')
            self.assertEqual(r.status_code, 400, (d, r.content))

    @expectedFailure  # BUG-653
    def test_BUG_653_future_date_session_refused(self):
        r = cl(self.g1).post(self.URL, self.body(date=str(ddate.today() + timedelta(days=400))), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.k1, self.b5), 0)


class DisposalsA4(Base):
    URL = '/api/production/disposals/'

    def setUp(self):
        self.sess = ProductionSession.objects.create(node=self.k1, team='A', date='2026-05-01', flour_sacks_used=Dc('1'))
        _adjust_bread_stock(self.k1, self.b5, produced=10)

    def post(self, user=None, **kw):
        b = {'session': str(self.sess.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD',
             'quantity': 3, 'unit_price_sold': 0}
        b.update(kw)
        return cl(user or self.g1).post(self.URL, b, format='json')

    def test_isolation_and_roles(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.content)
        d = r.data['id']
        self.assertEqual(self.stock(self.k1, self.b5), 7)
        self.assertEqual(cl(self.g2).get(f'{self.URL}{d}/').status_code, 404)
        self.assertEqual(cl(self.g2).delete(f'{self.URL}{d}/').status_code, 404)
        self.assertIn(self.post(user=self.g2).status_code, (400, 404))  # session d'un autre noeud
        self.assertEqual(self.post(user=self.fac).status_code, 403)
        self.assertEqual(self.stock(self.k1, self.b5), 7)

    def test_all_types_and_hostile_values(self):
        for bad in ({'quantity': -1}, {'quantity': 10 ** 7}, {'quantity': 1.5}, {'quantity': None}, {'quantity': True},
                    {'unit_price_sold': 10 ** 10}, {'disposal_type': 'XYZ'}, {'bread_price': 999999},
                    {'session': 'abc'}, {'quantity': '1e3'}, {'unit_price_sold': 'NaN'}, {'unit_price_sold': '1e400'}):
            r = self.post(**bad)
            self.assertLess(r.status_code, 500, (bad, r.content))
        self.assertEqual(self.stock(self.k1, self.b5), 10)

    def test_negative_unit_price_refused(self):
        r = self.post(unit_price_sold=-500)
        self.assertEqual(r.status_code, 400, r.content)

    def test_delete_restores_stock_and_remaining_does_not_touch(self):
        d = self.post(quantity=4).data['id']
        self.assertEqual(self.stock(self.k1, self.b5), 6)
        self.assertEqual(cl(self.g1).delete(f'{self.URL}{d}/').status_code, 204)
        self.assertEqual(self.stock(self.k1, self.b5), 10)
        self.assertEqual(self.post(disposal_type='REMAINING', quantity=-5).status_code, 201)
        self.assertEqual(self.stock(self.k1, self.b5), 10)


class UnicodeDigits(TBase):
    @expectedFailure  # BUG-654
    def test_BUG_654_unicode_digit_quantities_are_refused(self):
        """`_strict_int` accepte les chiffres Unicode (« ٣ » = 3) alors que `_strict_pk` les refuse
        (BUG-612) : incoherence ; saisie ambigue et non reproductible hors Python."""
        t = self.request([self.L(self.b3, 10)])
        self.respond(t, [self.L(self.b3, 10)])
        r = self.confirm(t, [self.L(self.b3, '٣', 'quantity_received')])
        self.assertEqual(r.status_code, 400, r.content)
        r = cl(self.g1).post(T + 'send/', {'to_node': self.k2.pk, 'lines': [self.L(self.b3, '٣')]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    @expectedFailure  # BUG-654
    def test_BUG_654_unicode_digit_flour_sacks_refused(self):
        r = cl(self.g1).post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-01-05', 'flour_sacks_used': '٣', 'lines': []}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
