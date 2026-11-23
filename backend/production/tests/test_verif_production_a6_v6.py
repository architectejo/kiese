"""Testeur-production (Dev A, cycle 4 / a6) : verification independante de
BUG-652/653/654/626/674/675/676/677 et nouveaux angles. Donnees fictives.
Les tests `@expectedFailure` referencent leur ticket BUG-68x.
"""
from datetime import date as ddate, timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.models import ExpenseCategory
from core.testing import make_client
from production.models import (BreadDisposal, BreadStock, BreadTransfer, ConsumableCount,
                               ConsumableStock, ConsumableType, ProductionSession, _adjust_bread_stock)
from production.tests.test_verif_a4_testeur_production import T, TBase, cl

S = '/api/production/sessions/'
D = '/api/production/disposals/'


def rows(r):
    return r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data


# ---------------------------------------------------------------- BUG-652
class V652(TBase):
    def test_unknown_category_refused_without_effect(self):
        t = self.request([self.L(self.b3, 10)])
        r = self.respond(t, [self.L(self.b5, 5)])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (100, 100))

    def test_unknown_mixed_with_valid_line_no_partial_write(self):
        t = self.request([self.L(self.b3, 10)])
        r = self.respond(t, [self.L(self.b3, 4), self.L(self.b5, 5)])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(BreadTransfer.objects.get(pk=t).lines.get().quantity_sent, 10)
        self.assertEqual(self.stock(self.k1, self.b3), 100)

    def test_all_zero_refused_and_refusal_path_still_works(self):
        t = self.request([self.L(self.b3, 10), self.L(self.b5, 5)])
        r = self.respond(t, [self.L(self.b3, 0), self.L(self.b5, 0)])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')
        r = self.respond(t, approved=False)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['transfer_status'], 'CANCELLED')

    def test_zero_one_line_other_requested_kept_and_group_sum(self):
        t = self.request([self.L(self.b3, 10), self.L(self.b5, 5)])
        r = self.respond(t, [self.L(self.b3, 0)])  # b5 garde la quantite demandee
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (100, 95))
        c = self.confirm(t, [self.L(self.b3, 0, 'quantity_received'), self.L(self.b5, 5, 'quantity_received')])
        self.assertEqual(c.status_code, 200, c.content)
        self.assertEqual((self.group(self.b3), self.group(self.b5)), (100, 100))

    def test_over_stock_on_non_body_line_refused_atomically(self):
        t = self.request([self.L(self.b3, 10), self.L(self.b5, 150)])  # b5 demande > stock 100
        r = self.respond(t, [self.L(self.b3, 10)])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (100, 100))
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')

    def test_negative_and_hostile_quantities(self):
        t = self.request([self.L(self.b3, 10)])
        for bad in (-1, 1.5, True, None, 'abc', '1e3', 10 ** 12):
            r = self.respond(t, [self.L(self.b3, bad)])
            self.assertEqual(r.status_code, 400, (bad, r.content))
        self.assertEqual(self.stock(self.k1, self.b3), 100)

    def test_roles_and_double_respond_deduct_once(self):
        t = self.request([self.L(self.b3, 10)])
        self.assertEqual(self.respond(t, [self.L(self.b3, 10)], user=self.g2).status_code, 403)
        self.assertIn(self.respond(t, [self.L(self.b3, 10)], user=self.g3).status_code, (403, 404))
        self.assertEqual(self.respond(t, [self.L(self.b3, 10)], user=self.fac).status_code, 403)
        self.assertEqual(self.respond(t, [self.L(self.b3, 10)]).status_code, 200)
        self.assertEqual(self.respond(t, [self.L(self.b3, 10)]).status_code, 400)
        self.assertEqual(self.stock(self.k1, self.b3), 90)

    def test_BUG_680_respond_duplicate_category_lines_refused(self):
        """BUG-680 : deux lignes de meme categorie dans la reponse : la derniere ecrase la
        premiere en silence (la reception refuse les doublons, BUG-620/622)."""
        t = self.request([self.L(self.b3, 10)])
        r = self.respond(t, [self.L(self.b3, 3), self.L(self.b3, 8)])
        self.assertEqual(r.status_code, 400, r.content)


# ---------------------------------------------------------------- BUG-653
class V653(TBase):
    body = {'team': 'A', 'flour_sacks_used': '1', 'lines': []}

    def test_today_past_ok_future_refused_invalid_400(self):
        today = ddate.today()
        for d, code in ((today, 201), (today - timedelta(days=3), 201), (today + timedelta(days=1), 400),
                        (today + timedelta(days=400), 400)):
            b = dict(self.body, date=str(d), team='B' if d == today else 'A')
            r = cl(self.g1).post(S, b, format='json')
            self.assertEqual(r.status_code, code, (d, r.content))
        for bad in ('2026-13-45', 'hier', '', '99999-01-01'):
            r = cl(self.g1).post(S, dict(self.body, date=bad), format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content))

    def test_future_refused_leaves_no_stock_no_session(self):
        before = self.stock(self.k1, self.b3)
        r = cl(self.g1).post(S, dict(self.body, date=str(ddate.today() + timedelta(days=2)),
                                     lines=[{'bread_price': self.b3.pk, 'quantity': 10}]), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.k1, self.b3), before)
        self.assertFalse(ProductionSession.objects.filter(node=self.k1).exists())

    def test_hq_future_refused_too(self):
        r = cl(self.dir).post(S, dict(self.body, node=self.k1.pk, date=str(ddate.today() + timedelta(days=5))),
                              format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_681_patch_session_date_to_future_refused(self):
        """BUG-681 : le PATCH de la date d'une fournee vers le futur est accepte (BUG-653 ne
        controle que la creation)."""
        r = cl(self.g1).post(S, dict(self.body, date=str(ddate.today())), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        r2 = cl(self.g1).patch(f"{S}{r.data['id']}/", {'date': str(ddate.today() + timedelta(days=30))}, format='json')
        self.assertEqual(r2.status_code, 400, r2.content)


# ---------------------------------------------------------------- BUG-654
class V654(TBase):
    def test_unicode_refused_in_transfers_flour_respond(self):
        for bad in ('٣', '１２', '٣٤', '-٣'):
            r = cl(self.g2).post(T, {'from_node': self.k1.pk, 'lines': [self.L(self.b3, bad)]}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content))
            r = cl(self.g1).post(S, {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': bad,
                                     'lines': []}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content))
        t = self.request([self.L(self.b3, 10)])
        self.assertEqual(self.respond(t, [self.L(self.b3, '٣')]).status_code, 400)
        self.assertEqual(self.stock(self.k1, self.b3), 100)
        r = cl(self.g1).post(S, {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': '1',
                                 'lines': [{'bread_price': self.b3.pk, 'quantity': '12'}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.stock(self.k1, self.b3), 112)

    def test_BUG_654_session_line_quantity_unicode_refused(self):
        """BUG-654 (REJETE a6) : la quantite d'une LIGNE de fournee (serializer DRF) accepte
        encore « ٣ » (201, 3 pains ajoutes au stock) ; seul `_strict_int` a ete corrige."""
        r = cl(self.g1).post(S, {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': '1',
                                 'lines': [{'bread_price': self.b3.pk, 'quantity': '٣'}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_682_unicode_digits_in_consumables_used(self):
        """BUG-682 : `consumables_used` (Decimal(str())) accepte « ٣ »."""
        ConsumableType.objects.get_or_create(code='SALT', defaults={'label': 'Sel', 'unit': 'g'})
        r = cl(self.g1).post(S, {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': '1', 'lines': [],
                                 'consumables_used': [{'consumable_type': 'SALT', 'quantity': '٣'}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_682_unicode_digits_in_disposal_quantity(self):
        """BUG-682 : quantite d'une disposition (DRF IntegerField) acceptee avec « ٣ »."""
        ses = ProductionSession.objects.create(node=self.k1, date=ddate.today() - timedelta(days=1), team='B',
                                               flour_sacks_used=Dc('1'))
        r = cl(self.g1).post(D, {'session': str(ses.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD',
                                 'quantity': '٣', 'unit_price_sold': 0}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


# ---------------------------------------------------------------- BUG-626
class V626(TBase):
    def test_api_count_flagged_unsynced_and_gap(self):
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')
        r = cl(self.g1).post('/api/production/counts/', {
            'consumable_type': 'FLOUR', 'count_date': str(ddate.today()), 'physical_quantity': '4.5'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        c = ConsumableCount.objects.get(pk=r.data['id'])
        self.assertFalse(c.is_synced)
        self.assertIsNone(c.inventory_id)
        self.assertEqual(c.gap, c.physical_quantity - c.system_quantity)

    def test_BUG_683_patch_count_synced_must_be_resent_and_gap_recomputed(self):
        """BUG-683 : une ligne de comptage synchronisee puis modifiee par PATCH reste
        `is_synced=True` : la modification n'est jamais renvoyee au Cloud."""
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')
        r = cl(self.g1).post('/api/production/counts/', {
            'consumable_type': 'FLOUR', 'count_date': str(ddate.today()), 'physical_quantity': '4.5'}, format='json')
        ConsumableCount.objects.filter(pk=r.data['id']).update(is_synced=True)
        p = cl(self.g1).patch(f"/api/production/counts/{r.data['id']}/", {'physical_quantity': '7'}, format='json')
        self.assertEqual(p.status_code, 200, p.content)
        c = ConsumableCount.objects.get(pk=r.data['id'])
        self.assertFalse(c.is_synced)

    def test_BUG_683_patch_count_recomputes_gap(self):
        """BUG-683 : le PATCH de `physical_quantity` ne recalcule pas `gap` (ecart d'inventaire faux)."""
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')
        r = cl(self.g1).post('/api/production/counts/', {
            'consumable_type': 'FLOUR', 'count_date': str(ddate.today()), 'physical_quantity': '4.5'}, format='json')
        p = cl(self.g1).patch(f"/api/production/counts/{r.data['id']}/", {'physical_quantity': '7'}, format='json')
        self.assertEqual(p.status_code, 200, p.content)
        c = ConsumableCount.objects.get(pk=r.data['id'])
        self.assertEqual(c.gap, c.physical_quantity - c.system_quantity)

    def test_outbound_extracts_only_unsynced_legacy_counts(self):
        from sync.management.commands.sync_now import build_outbound_payload
        from sync.tests.test_consumable_inventory_sync import CNT
        ConsumableCount.objects.create(node=self.k1, consumable_type='FLOUR', count_date=ddate(2026, 1, 5),
                                       system_quantity=Dc('1'), physical_quantity=Dc('1'), gap=Dc('0'),
                                       is_synced=False)
        ConsumableCount.objects.create(node=self.k1, consumable_type='YEAST', count_date=ddate(2026, 1, 5),
                                       system_quantity=Dc('1'), physical_quantity=Dc('1'), gap=Dc('0'),
                                       is_synced=True)
        recs = build_outbound_payload(self.k1.code)['records'][CNT]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]['consumable_type'], 'FLOUR')
        # isolation de noeud : K2 n'extrait rien de K1
        self.assertEqual(build_outbound_payload(self.k2.code)['records'][CNT], [])


# ---------------------------------------------------------------- BUG-674
class V674(TBase):
    def _disp(self, node, d, qty, bp=None, team='A', typ='UNSOLD'):
        s, _ = ProductionSession.objects.get_or_create(node=node, date=d, team=team,
                                                       defaults={'flour_sacks_used': Dc('1')})
        return BreadDisposal.objects.create(node=node, session=s, bread_price=bp or self.b3,
                                            disposal_type=typ, quantity=qty, unit_price_sold=300)

    def test_filters_range_bounds_inclusive_and_isolation(self):
        t, y, a = ddate.today(), ddate.today() - timedelta(days=1), ddate.today() - timedelta(days=9)
        self._disp(self.k1, t, 1)
        self._disp(self.k1, y, 2)
        self._disp(self.k1, a, 4)
        self._disp(self.k2, y, 99)  # autre boulangerie
        q = lambda **p: sorted(x['quantity'] for x in rows(cl(self.g1).get(D, p)))
        self.assertEqual(q(), [1, 2, 4])
        self.assertEqual(q(date=str(y)), [2])
        self.assertEqual(q(date_from=str(y)), [1, 2])
        self.assertEqual(q(date_to=str(y)), [2, 4])
        self.assertEqual(q(date_from=str(a), date_to=str(y)), [2, 4])
        self.assertEqual(q(date_from=str(t), date_to=str(a)), [])  # plage inversee : vide, pas 500
        self.assertEqual(q(date=str(y), date_from=str(t)), [])  # combinaison conjonctive
        self.assertEqual(q(date=str(ddate.today() + timedelta(days=30))), [])
        self.assertEqual(q(date=''), [1, 2, 4])  # vide ignore
        self.assertEqual(sorted(x['quantity'] for x in rows(cl(self.g2).get(D, {'date': str(y)}))), [99])
        self.assertEqual(sorted(x['quantity'] for x in rows(cl(self.dir).get(D, {'date': str(y)}))), [2, 99])

    def test_invalid_dates_400_not_500(self):
        for bad in ('2026-13-45', 'abc', '23/11/2026', '2026-11-23T10:00:00', '1e3', "2026-11-23' OR 1=1"):
            for key in ('date', 'date_from', 'date_to'):
                r = cl(self.g1).get(D, {key: bad})
                self.assertIn(r.status_code, (200, 400), (key, bad, r.content))
                if r.status_code == 200:
                    self.fail(f'{key}={bad} accepte')

    def test_filter_combined_with_type_and_category_and_permissions(self):
        y = ddate.today() - timedelta(days=1)
        self._disp(self.k1, y, 2, bp=self.b3, typ='UNSOLD')
        self._disp(self.k1, y, 5, bp=self.b5, typ='FREE_DIST', team='B')
        got = rows(cl(self.g1).get(D, {'date': str(y), 'disposal_type': 'FREE_DIST'}))
        self.assertEqual([x['quantity'] for x in got], [5])
        got = rows(cl(self.g1).get(D, {'date': str(y), 'bread_price': self.b3.pk}))
        self.assertEqual([x['quantity'] for x in got], [2])
        self.assertEqual(cl(self.fac).get(D, {'date': str(y)}).status_code, 403)

    def test_remaining_negative_listed_by_date(self):
        y = ddate.today() - timedelta(days=1)
        self._disp(self.k1, y, -5, typ='REMAINING')
        self.assertEqual([x['quantity'] for x in rows(cl(self.g1).get(D, {'date': str(y)}))], [-5])


# ---------------------------------------------------------------- BUG-675
class V675(TBase):
    def _row(self, user, bp, d=None):
        r = cl(user).get('/api/production/daily-closure/', {'date': str(d or ddate.today())})
        self.assertEqual(r.status_code, 200, r.content)
        return r.data, next(c for c in r.data['categories'] if c['bread_price'] == bp.pk)

    def _total(self, user):
        data, _ = self._row(user, self.b3)
        return Dc(data['totals']['total_du_jour_fc'])

    def test_total_du_jour_sign_and_group_sum_zero(self):
        a1, a2 = self._total(self.g1), self._total(self.g2)
        r = self.send([self.L(self.b3, 10), self.L(self.b5, 4)])
        self.assertEqual(r.status_code, 201, r.content)
        before = (self._total(self.g1), self._total(self.g2))
        self.assertEqual(before, (a1, a2))  # en attente : aucun effet sur la cloture
        c = self.confirm(r.data['id'], [self.L(self.b3, 10, 'quantity_received'), self.L(self.b5, 4, 'quantity_received')])
        self.assertEqual(c.status_code, 200, c.content)
        self.assertEqual(self._total(self.g1) - a1, Dc('5000'))   # 10*300 + 4*500
        self.assertEqual(self._total(self.g2) - a2, Dc('-5000'))
        self.assertEqual((self._total(self.g1) - a1) + (self._total(self.g2) - a2), 0)
        _, row1 = self._row(self.g1, self.b3)
        _, row2 = self._row(self.g2, self.b3)
        self.assertEqual((row1['appro_effectue']['quantity'], row1['appro_recu']['quantity']), (10, 0))
        self.assertEqual((row2['appro_effectue']['quantity'], row2['appro_recu']['quantity']), (0, 10))
        self.assertEqual(Dc(row1['facture_mvm_interne']['fc']), Dc('3000'))
        self.assertEqual(Dc(row2['facture_mvm_interne']['fc']), Dc('-3000'))

    def test_request_flow_respond_confirm_same_sign(self):
        t = self.request([self.L(self.b3, 10)])
        self.respond(t, [self.L(self.b3, 10)])
        a1, a2 = self._total(self.g1), self._total(self.g2)
        self.confirm(t, [self.L(self.b3, 10, 'quantity_received')])
        self.assertEqual((self._total(self.g1) - a1, self._total(self.g2) - a2), (Dc('3000'), Dc('-3000')))

    def test_disputed_98_not_counted_until_resolved_then_both_sides(self):
        a1, a2 = self._total(self.g1), self._total(self.g2)
        r = self.send([self.L(self.b3, 100)])
        c = self.confirm(r.data['id'], [self.L(self.b3, 98, 'quantity_received')])
        self.assertEqual(c.data['transfer_status'], 'DISPUTED')
        d1, d2 = self._total(self.g1) - a1, self._total(self.g2) - a2
        # Observation : tant que l'ecart n'est pas resolu aucun cote n'est compte (coherent).
        self.assertEqual((d1, d2), (0, 0))
        res = cl(self.dir).post(f"{T}{r.data['id']}/resolve_dispute/",
                                {'resolution': 'ALIGN_ON_RECEIVED', 'reason': '2 pains perdus'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        d1, d2 = self._total(self.g1) - a1, self._total(self.g2) - a2
        self.assertEqual(d1 + d2, 0, (d1, d2))  # somme du groupe nulle apres resolution

    def test_other_day_not_affected(self):
        y = ddate.today() - timedelta(days=1)
        b1, b2 = self._row(self.g1, self.b3, y)[0]['totals']['total_du_jour_fc'], \
            self._row(self.g2, self.b3, y)[0]['totals']['total_du_jour_fc']
        r = self.send([self.L(self.b3, 10)])
        self.confirm(r.data['id'], [self.L(self.b3, 10, 'quantity_received')])
        self.assertEqual(self._row(self.g1, self.b3, y)[0]['totals']['total_du_jour_fc'], b1)
        self.assertEqual(self._row(self.g2, self.b3, y)[0]['totals']['total_du_jour_fc'], b2)


# ---------------------------------------------------------------- BUG-676
class V676(TBase):
    def _sell(self, lines, pay='0', ptype='CREDIT', deliver=True):
        client = make_client(self.k1, credit_limit=Dc('9000000'))
        r = cl(self.fac).post('/api/sales/invoices/', {
            'payment_type': ptype, 'payment_amount': pay, 'client': str(client.pk),
            'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        if deliver:
            self.assertEqual(cl(self.fac).post(f"/api/sales/invoices/{r.data['id']}/deliver/").status_code, 200)
        return r.data['id']

    def _tot(self):
        r = cl(self.g1).get('/api/production/daily-closure/', {'date': str(ddate.today())})
        self.assertEqual(r.status_code, 200, r.content)
        return r.data['totals']

    def test_no_activity_all_zero_and_base_present(self):
        t = self._tot()
        self.assertIn('repartition_base', t)
        self.assertTrue(all(Dc(x['pct']) == 0 for x in t['repartition_pct_par_quantite']))

    def test_fallback_sums_to_100_and_base_label(self):
        self._sell([(self.b3, 3), (self.b5, 7)], pay='0')
        t = self._tot()
        q = {x['bread_price']: Dc(x['pct']) for x in t['repartition_pct_par_quantite']}
        self.assertEqual((q[self.b3.pk], q[self.b5.pk]), (Dc('30.00'), Dc('70.00')))
        v = {x['bread_price']: Dc(x['pct']) for x in t['repartition_pct_par_valeur']}
        # 900 / 4400 = 20.45 ; 3500 / 4400 = 79.55
        self.assertEqual((v[self.b3.pk], v[self.b5.pk]), (Dc('20.45'), Dc('79.55')))
        self.assertIn(t['repartition_base'], ('vendu_jour', 'facture'))
        self.assertLessEqual(abs(sum(Dc(x['pct']) for x in t['repartition_pct_par_valeur']) - 100), Dc('0.02'))

    def test_declared_production_wins_over_sales(self):
        r = cl(self.g1).post(S, {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': '1',
                                 'lines': [{'bread_price': self.b3.pk, 'quantity': 50}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self._sell([(self.b5, 10)])
        t = self._tot()
        q = {x['bread_price']: Dc(x['pct']) for x in t['repartition_pct_par_quantite']}
        if t['repartition_base'] == 'produit':
            self.assertEqual(q[self.b3.pk], Dc('100.00'))
            self.assertEqual(q[self.b5.pk], Dc('0.00'))
        else:  # production non derivee avant cloture : repli documente
            self.assertIn(t['repartition_base'], ('vendu_jour', 'facture'))

    def test_negative_never_shown_and_refund_only_day(self):
        client = make_client(self.k1, credit_limit=Dc('9000000'))
        r = cl(self.fac).post('/api/sales/invoices/', {'payment_type': 'CASH', 'payment_amount': '1000',
                                                       'client': str(client.pk), 'lines': []}, format='json')
        t = self._tot()
        for x in t['repartition_pct_par_quantite'] + t['repartition_pct_par_valeur']:
            self.assertGreaterEqual(Dc(x['pct']), 0)


# ---------------------------------------------------------------- BUG-677
class V677(TBase):
    def _mk(self, code, scope):
        return ExpenseCategory.objects.create(code=code, label=code, scope=scope)

    def _exp(self, user, cat, **kw):
        b = {'description': 'x', 'amount': '1000', 'date': str(ddate.today()), 'category': cat.pk}
        b.update(kw)
        return cl(user).post('/api/treasury/expenses/', b, format='json')

    def test_visibility_by_role_and_scope_filter(self):
        both, bak, dr = self._mk('V1', 'BOTH'), self._mk('V2', 'BAKERY'), self._mk('V3', 'DIRECTION')
        ids = lambda u, **p: {x['id'] for x in rows(cl(u).get('/api/core/expense-categories/', p))}
        for u in (self.g1, self.fac, self.liv):
            got = ids(u)
            self.assertTrue({both.pk, bak.pk} <= got, u)
            self.assertNotIn(dr.pk, got, u)
        for u in (self.dir, self.adm, self.cpt):
            self.assertTrue({both.pk, bak.pk, dr.pk} <= ids(u), u)
        self.assertEqual(ids(self.dir, scope='DIRECTION') & {both.pk, bak.pk, dr.pk}, {both.pk, dr.pk})
        self.assertEqual(ids(self.dir, scope='BAKERY') & {both.pk, bak.pk, dr.pk}, {both.pk, bak.pk})
        self.assertNotIn(dr.pk, ids(self.g1, scope='DIRECTION'))
        self.assertEqual(cl(self.g1).get(f'/api/core/expense-categories/{dr.pk}/').status_code, 404)
        self.assertEqual(cl(self.dir).get(f'/api/core/expense-categories/{dr.pk}/').status_code, 200)

    def test_expense_create_and_patch_rules(self):
        both, dr = self._mk('V4', 'BOTH'), self._mk('V5', 'DIRECTION')
        r = self._exp(self.g1, both)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self._exp(self.g1, dr).status_code, 400)
        p = cl(self.g1).patch(f"/api/treasury/expenses/{r.data['id']}/", {'category': dr.pk}, format='json')
        self.assertEqual(p.status_code, 400, p.content)
        # une categorie passee DIRECTION apres coup ne bloque pas la modification d'autres champs
        both.scope = 'DIRECTION'
        both.save()
        p = cl(self.g1).patch(f"/api/treasury/expenses/{r.data['id']}/", {'description': 'maj'}, format='json')
        self.assertEqual(p.status_code, 200, p.content)

    def test_scope_validation_and_writes(self):
        c = self._mk('V6', 'BOTH')
        u = f'/api/core/expense-categories/{c.pk}/'
        for bad in ('XX', '', None, 5):
            self.assertEqual(cl(self.dir).patch(u, {'scope': bad}, format='json').status_code, 400, bad)
        r = cl(self.dir).post('/api/core/expense-categories/', {'code': 'V7', 'label': 'V7', 'scope': 'DIRECTION'},
                              format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['scope'], 'DIRECTION')
        r = cl(self.dir).post('/api/core/expense-categories/', {'code': 'V8', 'label': 'V8'}, format='json')
        self.assertEqual(r.data['scope'], 'BOTH')
        for u2 in (self.g1, self.fac):
            self.assertEqual(cl(u2).post('/api/core/expense-categories/', {'code': 'V9', 'label': 'V9'},
                                         format='json').status_code, 403)

    @expectedFailure
    def test_BUG_684_hq_expense_for_node_with_direction_only_category(self):
        """BUG-684 : un compte siege peut rattacher a une depense LOCALE de boulangerie une
        categorie `DIRECTION` (la regle n'est appliquee qu'aux comptes de boulangerie) : la
        depense devient invisible/inclassable pour le gerant. Attendu : 400 (ou a clarifier)."""
        dr = self._mk('V10', 'DIRECTION')
        r = self._exp(self.dir, dr, node=self.k1.pk)
        self.assertEqual(r.status_code, 400, r.content)
