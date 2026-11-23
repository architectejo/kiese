"""Testeur-production (Dev A, cycle 5 / a7) : re-verification independante de BUG-654 (ligne),
680, 681, 682, 683 et nouveaux defauts voisins (BUG-686, 687). Donnees fictives.
Les tests `@expectedFailure` referencent leur ticket.
"""
from datetime import date as ddate, timedelta
from decimal import Decimal as Dc

from production.models import (BreadDisposal, BreadTransfer, ConsumableCount, ConsumableMovement,
                               ConsumableStock, ConsumableType, ProductionSession)
from production.tests.test_verif_a4_testeur_production import T, TBase, cl

S = '/api/production/sessions/'
D = '/api/production/disposals/'
C = '/api/production/counts/'
M = '/api/production/movements/'
ARAB, FULL = '٣', '１２'


def FUT(n=30):
    return str(ddate.today() + timedelta(days=n))


class V680(TBase):
    def test_duplicate_refused_with_int_and_str_ids_no_effect(self):
        t = self.request([self.L(self.b3, 10), self.L(self.b5, 5)])
        for lines in ([self.L(self.b3, 3), self.L(self.b3, 8)],
                      [{'bread_price': str(self.b3.pk), 'quantity_sent': 3}, self.L(self.b3, 8)],
                      [self.L(self.b3, 0), self.L(self.b3, 0)]):
            r = self.respond(t, lines)
            self.assertEqual(r.status_code, 400, (lines, r.content))
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (100, 100))

    def test_distinct_categories_still_ok_group_sum_kept(self):
        t = self.request([self.L(self.b3, 10), self.L(self.b5, 5)])
        self.assertEqual(self.respond(t, [self.L(self.b3, 4), self.L(self.b5, 5)]).status_code, 200)
        c = self.confirm(t, [self.L(self.b3, 4, 'quantity_received'), self.L(self.b5, 5, 'quantity_received')])
        self.assertEqual(c.status_code, 200, c.content)
        self.assertEqual((self.group(self.b3), self.group(self.b5)), (100, 100))
        self.assertEqual((self.stock(self.k2, self.b3), self.stock(self.k2, self.b5)), (4, 5))


class V681(TBase):
    body = {'team': 'A', 'flour_sacks_used': '1', 'lines': []}

    def _mk(self, d=None, user=None, **kw):
        r = cl(user or self.g1).post(S, dict(self.body, date=str(d or ddate.today()), **kw), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def test_patch_future_refused_past_and_same_ok_value_unchanged(self):
        sid = self._mk()
        for n in (1, 30, 4000):
            r = cl(self.g1).patch(f'{S}{sid}/', {'date': FUT(n)}, format='json')
            self.assertEqual(r.status_code, 400, (n, r.content))
        self.assertEqual(ProductionSession.objects.get(pk=sid).date, ddate.today())
        for d in (ddate.today(), ddate.today() - timedelta(days=5)):
            r = cl(self.g1).patch(f'{S}{sid}/', {'date': str(d)}, format='json')
            self.assertEqual(r.status_code, 200, r.content)
        for bad in ('2026-13-45', 'x', '', None):
            self.assertEqual(cl(self.g1).patch(f'{S}{sid}/', {'date': bad}, format='json').status_code, 400, bad)

    def test_patch_without_date_still_ok_and_hq_future_refused(self):
        sid = self._mk()
        self.assertEqual(cl(self.g1).patch(f'{S}{sid}/', {'notes': 'ok'}, format='json').status_code, 200)
        r = cl(self.dir).patch(f'{S}{sid}/', {'date': FUT(3)}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_put_future_refused_and_stock_unchanged(self):
        sid = self._mk(lines=[{'bread_price': self.b3.pk, 'quantity': 10}])
        before = self.stock(self.k1, self.b3)
        r = cl(self.g1).put(f'{S}{sid}/', dict(self.body, date=FUT(2),
                                               lines=[{'bread_price': self.b3.pk, 'quantity': 12}]), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.k1, self.b3), before)


class V654_682(TBase):
    def _sess(self, **kw):
        b = {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': '1', 'lines': []}
        b.update(kw)
        return cl(self.g1).post(S, b, format='json')

    def test_line_quantity_non_ascii_refused_no_stock_no_session(self):
        before = self.stock(self.k1, self.b3)
        for bad in (ARAB, FULL, '٣٤', '-٣', '³', '५'):
            r = self._sess(lines=[{'bread_price': self.b3.pk, 'quantity': bad}])
            self.assertEqual(r.status_code, 400, (bad, r.content))
        self.assertEqual(self.stock(self.k1, self.b3), before)
        self.assertFalse(ProductionSession.objects.filter(node=self.k1).exists())

    def test_line_quantity_ascii_still_ok(self):
        r = self._sess(lines=[{'bread_price': self.b3.pk, 'quantity': '12'}, {'bread_price': self.b5.pk, 'quantity': 7}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (112, 107))

    def test_patch_lines_non_ascii_refused_stock_kept(self):
        r = self._sess(lines=[{'bread_price': self.b3.pk, 'quantity': 10}])
        self.assertEqual(r.status_code, 201, r.content)
        p = cl(self.g1).patch(f"{S}{r.data['id']}/", {'lines': [{'bread_price': self.b3.pk, 'quantity': ARAB}]},
                              format='json')
        self.assertEqual(p.status_code, 400, p.content)
        self.assertEqual(self.stock(self.k1, self.b3), 110)

    def test_consumables_used_non_ascii_refused_ascii_ok_stock_decremented(self):
        ConsumableType.objects.get_or_create(code='SALT', defaults={'label': 'Sel', 'unit': 'g'})
        for bad in (ARAB, FULL, '٠٫٢٥'):
            r = self._sess(consumables_used=[{'consumable_type': 'SALT', 'quantity': bad}])
            self.assertEqual(r.status_code, 400, (bad, r.content))
        self.assertFalse(ConsumableMovement.objects.filter(node=self.k1).exists())
        r = self._sess(consumables_used=[{'consumable_type': 'SALT', 'quantity': '250'}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(ConsumableStock.objects.get(node=self.k1, consumable_type='SALT').quantity, Dc('-250'))

    def test_disposal_quantity_non_ascii_refused_ascii_ok(self):
        ses = ProductionSession.objects.create(node=self.k1, date=ddate.today() - timedelta(days=1), team='B',
                                               flour_sacks_used=Dc('1'))
        for bad in (ARAB, FULL, '-٣'):
            r = cl(self.g1).post(D, {'session': str(ses.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD',
                                     'quantity': bad, 'unit_price_sold': 0}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content))
        r = cl(self.g1).post(D, {'session': str(ses.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD',
                                 'quantity': 3, 'unit_price_sold': 0}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(BreadDisposal.objects.filter(node=self.k1).count(), 1)


class V683(TBase):
    def _count(self, phys='4.5'):
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')
        r = cl(self.g1).post(C, {'consumable_type': 'FLOUR', 'count_date': str(ddate.today()),
                                 'physical_quantity': phys}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def test_patch_recomputes_gap_on_frozen_system_qty_and_unsyncs(self):
        cid = self._count()
        ConsumableCount.objects.filter(pk=cid).update(system_quantity=Dc('10'), gap=Dc('-5.5'), is_synced=True)
        p = cl(self.g1).patch(f'{C}{cid}/', {'physical_quantity': '12.25'}, format='json')
        self.assertEqual(p.status_code, 200, p.content)
        c = ConsumableCount.objects.get(pk=cid)
        self.assertEqual((c.system_quantity, c.gap, c.is_synced), (Dc('10'), Dc('2.25'), False))
        cl(self.g1).patch(f'{C}{cid}/', {'physical_quantity': '0'}, format='json')
        self.assertEqual(ConsumableCount.objects.get(pk=cid).gap, Dc('-10'))

    def test_patch_notes_only_keeps_gap_but_unsyncs(self):
        cid = self._count('4.5')
        ConsumableCount.objects.filter(pk=cid).update(is_synced=True)
        gap = ConsumableCount.objects.get(pk=cid).gap
        p = cl(self.g1).patch(f'{C}{cid}/', {'notes': 'recompte'}, format='json')
        self.assertEqual(p.status_code, 200, p.content)
        c = ConsumableCount.objects.get(pk=cid)
        self.assertEqual((c.gap, c.is_synced), (gap, False))

    def test_patch_invalid_refused_gap_untouched_other_node_refused(self):
        cid = self._count('4.5')
        gap = ConsumableCount.objects.get(pk=cid).gap
        for bad in ('abc', '1e400', None):
            self.assertEqual(cl(self.g1).patch(f'{C}{cid}/', {'physical_quantity': bad}, format='json').status_code,
                             400, bad)
        self.assertEqual(ConsumableCount.objects.get(pk=cid).gap, gap)
        self.assertIn(cl(self.g2).patch(f'{C}{cid}/', {'physical_quantity': '1'}, format='json').status_code,
                      (403, 404))

    def test_BUG_688_negative_physical_quantity_refused_on_patch(self):
        cid = self._count('4.5')
        r = cl(self.g1).patch(f'{C}{cid}/', {'physical_quantity': '-1'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_688_negative_physical_quantity_refused_on_create(self):
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')
        r = cl(self.g1).post(C, {'consumable_type': 'FLOUR', 'count_date': str(ddate.today()),
                                 'physical_quantity': '-5'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class V7NeighbourSync(TBase):
    """is_synced des modeles modifies : toute modification repasse a False (non-regression)."""

    def test_movement_and_session_patch_unsync(self):
        s = ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')[0]
        mid = cl(self.g1).post(M, {'stock': s.pk, 'movement_type': 'ENTRY', 'quantity': '3', 'unit_price': '100'},
                               format='json').data['id']
        ConsumableMovement.objects.filter(pk=mid).update(is_synced=True)
        self.assertEqual(cl(self.g1).patch(f'{M}{mid}/', {'description': 'x'}, format='json').status_code, 200)
        self.assertFalse(ConsumableMovement.objects.get(pk=mid).is_synced)
        sid = cl(self.g1).post(S, {'team': 'A', 'date': str(ddate.today()), 'flour_sacks_used': '1', 'lines': []},
                               format='json').data['id']
        ProductionSession.objects.filter(pk=sid).update(is_synced=True)
        self.assertEqual(cl(self.g1).patch(f'{S}{sid}/', {'notes': 'x'}, format='json').status_code, 200)
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_synced)


class V686NonAsciiDigits(TBase):
    """BUG-686 : champs DRF/`Decimal(str())` de production qui acceptent encore les chiffres non ASCII
    (meme cause que BUG-654/682, autres endpoints)."""

    def _stock(self, node=None):
        return ConsumableStock.objects.get_or_create(node=node or self.k1, consumable_type='FLOUR')[0]

    def test_BUG_686_movement_quantity_and_price(self):
        s = self._stock()
        for k in ('quantity', 'unit_price'):
            body = {'stock': s.pk, 'movement_type': 'ENTRY', 'quantity': '3', 'unit_price': '100'}
            body[k] = ARAB
            r = cl(self.g1).post(M, body, format='json')
            self.assertEqual(r.status_code, 400, (k, r.content))

    def test_BUG_686_movement_patch_quantity(self):
        s = self._stock()
        mid = cl(self.g1).post(M, {'stock': s.pk, 'movement_type': 'ENTRY', 'quantity': '3', 'unit_price': '100'},
                               format='json').data['id']
        r = cl(self.g1).patch(f'{M}{mid}/', {'quantity': ARAB}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_686_count_physical_quantity(self):
        self._stock()
        r = cl(self.g1).post(C, {'consumable_type': 'FLOUR', 'count_date': str(ddate.today()),
                                 'physical_quantity': ARAB}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_686_inventory_physical_quantity(self):
        self._stock()
        r = cl(self.g1).post('/api/production/inventories/',
                             {'lines': [{'consumable_type': 'FLOUR', 'physical_quantity': ARAB}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_686_dispatch_quantity(self):
        from production.consumables_direction import siege_node
        sg = self._stock(siege_node())
        cl(self.dir).post(M, {'stock': sg.pk, 'movement_type': 'ENTRY', 'quantity': '10', 'unit_price': '100'},
                          format='json')
        r = cl(self.dir).post('/api/production/consumables/dispatch/', {
            'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': ARAB}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_686_disposal_unit_price_sold(self):
        ses = ProductionSession.objects.create(node=self.k1, date=ddate.today() - timedelta(days=1), team='B',
                                               flour_sacks_used=Dc('1'))
        r = cl(self.g1).post(D, {'session': str(ses.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD',
                                 'quantity': 3, 'unit_price_sold': ARAB}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_transfer_send_non_ascii_refused_ok(self):  # non-regression : deja refuse
        r = cl(self.g1).post(f'{T}send/', {'to_node': self.k2.pk, 'lines': [self.L(self.b3, ARAB)]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class V687FutureDates(TBase):
    """BUG-687 : dates futures acceptees sur d'autres endpoints (BUG-653/681 ne couvrent que les fournees)."""

    def test_BUG_687_count_date_future_refused_on_create(self):
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')
        r = cl(self.g1).post(C, {'consumable_type': 'FLOUR', 'count_date': FUT(), 'physical_quantity': '2'},
                             format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_687_count_date_future_refused_on_patch(self):
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')
        cid = cl(self.g1).post(C, {'consumable_type': 'FLOUR', 'count_date': str(ddate.today()),
                                   'physical_quantity': '2'}, format='json').data['id']
        r = cl(self.g1).patch(f'{C}{cid}/', {'count_date': FUT()}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_687_opening_confirmation_future_date_refused(self):
        r = cl(self.g1).post('/api/production/opening-confirmation/', {
            'date': FUT(), 'team': 'A', 'lines': [{'bread_price': self.b3.pk, 'qty': 5}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_bread_stock_by_date_future_refused_ok(self):  # non-regression : deja 400
        r = cl(self.g1).get('/api/production/bread-stocks/by-date/', {'date': FUT()})
        self.assertEqual(r.status_code, 400, r.content)
