"""Testeur-production (cycle 10 / a9) : verification independante de BUG-901 a 909 (push sync
production/ventes), non-regression des pushs legitimes, contournements de l'exception
`_batch_terminal_parents` et defauts voisins (transferts, consommables, comptages).
Donnees fictives. Les `@expectedFailure` referencent leur ticket.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc

from django.utils import timezone

from core.models import BreadPrice
from core.workday import work_date_for
from production.models import (BreadDisposal, BreadTransfer, BreadTransferLine, ConsumableCount,
                               ConsumableMovement, ConsumableStock, ProductionSession,
                               ProductionSessionLine)
from production.tests.test_verif_production_a8_v8 import PUSH, PushBase, api_for, push, uid
from sales.models import Invoice, InvoiceLine
from sync.models import SyncConflictLog  # noqa: F401  (disponible pour les diagnostics)

LBL_S, LBL_L = 'production.ProductionSession', 'production.ProductionSessionLine'
LBL_I, LBL_IL = 'sales.Invoice', 'sales.InvoiceLine'
LBL_T, LBL_TL = 'production.BreadTransfer', 'production.BreadTransferLine'
LBL_M, LBL_D = 'production.ConsumableMovement', 'production.BreadDisposal'


def lot(a, **by_label):
    """Pousse un lot multi-modeles ; cles `production__ProductionSession` -> label."""
    recs = {k.replace('__', '.'): v for k, v in by_label.items()}
    r = a.post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': recs}, format='json')
    assert r.status_code == 200, (r.status_code, r.content)
    return {k: [(x['status'], x.get('reason')) for x in v] for k, v in r.data['results'].items()}


class V9Base(PushBase):
    def today(self):
        return work_date_for(self.k1)

    def sess9(self, **kw):
        d = self.sess(**kw)
        return d


# ------------------------------------------------------------------ non-regression legitime
class V9Legitimate(V9Base):
    def test_closed_session_with_lines_in_same_lot_accepted(self):
        s = self.sess(is_closed=True, closed_at=timezone.now().isoformat())
        res = lot(self.a1, production__ProductionSession=[s], production__ProductionSessionLine=[
            {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 70},
            {'session': s['id'], 'bread_price': self.b5.pk, 'quantity': 30, 'source': 'CARRYOVER'}])
        self.assertTrue(all(x[0] == 'ACCEPTED' for v in res.values() for x in v), res)
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=s['id']).count(), 2)

    def test_open_session_closed_offline_then_lines_same_lot(self):
        s = self.sess()
        self.assertEqual(push(self.a1, LBL_S, s)[0], 'ACCEPTED')
        res = lot(self.a1, production__ProductionSession=[dict(s, is_closed=True, closed_at=timezone.now().isoformat())],
                  production__ProductionSessionLine=[{'session': s['id'],
                                                      'bread_price': self.b3.pk, 'quantity': 5}])
        self.assertTrue(all(x[0] == 'ACCEPTED' for v in res.values() for x in v), res)
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=s['id']).count(), 1)

    def test_delivered_invoice_with_lines_same_lot_accepted_and_replay_idempotent(self):
        inv = self.inv(status='DELIVERED', delivered_at=timezone.now().isoformat())
        lines = [{'id': '9001', 'invoice': inv['id'], 'bread_price': self.b3.pk, 'quantity': 10},
                 {'id': '9002', 'invoice': inv['id'], 'bread_price': self.b5.pk, 'quantity': 4}]
        res = lot(self.a1, sales__Invoice=[inv], sales__InvoiceLine=lines)
        self.assertTrue(all(x[0] == 'ACCEPTED' for v in res.values() for x in v), res)
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=inv['id']).count(), 2)
        # rejeu (nouveau batch_id) : accepte, aucun doublon, aucune ligne en plus
        res = lot(self.a1, sales__Invoice=[inv], sales__InvoiceLine=lines)
        self.assertTrue(all(x[0] == 'ACCEPTED' for v in res.values() for x in v), res)
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=inv['id']).count(), 2)
        self.assertEqual(Invoice.objects.filter(pk=inv['id']).count(), 1)

    def test_pending_invoice_delivered_offline_then_new_line_same_lot(self):
        inv = self.inv()
        push(self.a1, LBL_I, inv)
        res = lot(self.a1, sales__Invoice=[dict(inv, status='DELIVERED', delivered_at=timezone.now().isoformat())],
                  sales__InvoiceLine=[{'invoice': inv['id'], 'bread_price': self.b3.pk, 'quantity': 3}])
        self.assertTrue(all(x[0] == 'ACCEPTED' for v in res.values() for x in v), res)
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=inv['id']).count(), 1)

    def test_session_replay_idempotent_same_and_new_batch(self):
        s = self.sess()
        line = {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 9}
        for _ in range(3):
            res = lot(self.a1, production__ProductionSession=[s], production__ProductionSessionLine=[line])
            self.assertTrue(all(x[0] == 'ACCEPTED' for v in res.values() for x in v), res)
        self.assertEqual(ProductionSession.objects.filter(pk=s['id']).count(), 1)
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=s['id']).count(), 1)

    def test_mixed_lot_valid_and_invalid(self):
        good, bad = self.sess(), self.sess(flour_sacks_used='-1')
        res = lot(self.a1, production__ProductionSession=[bad, good])
        self.assertEqual([x[0] for x in res[LBL_S]], ['REJECTED', 'ACCEPTED'])
        self.assertTrue(ProductionSession.objects.filter(pk=good['id']).exists())
        self.assertFalse(ProductionSession.objects.filter(pk=bad['id']).exists())

    def test_boundaries_accepted(self):
        for fl in ('0', '0.00', '2.5', '100000', '100000.00', '12.25'):
            self.assertEqual(self.push_sess(flour_sacks_used=fl)[1][0], 'ACCEPTED', fl)
        s = self.sess()
        push(self.a1, LBL_S, s)
        for bp, q in ((self.b3, 0), (self.b4 if hasattr(self, 'b4') else self.b5, 2_000_000_000)):
            self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': bp.pk,
                                                   'quantity': q})[0], 'ACCEPTED', q)
        for rate in ('0', '0.00', '0.25', '0.3', '0.30', '0.300'):
            self.assertEqual(push(self.a1, LBL_I, self.inv(commission_rate=rate))[0], 'ACCEPTED', rate)
        for qty, unit in (('0.25', 'YEAST'), ('0.33', 'OIL'), ('0.333', 'SALT'), ('9999999.999', 'FLOUR')):
            self.assertEqual(push(self.a1, LBL_M, {'id': uid(), 'node': self.k1.code, 'consumable_type': unit,
                                                   'movement_type': 'ENTRY', 'quantity': qty,
                                                   'unit_price': '1.2345'})[0], 'ACCEPTED', qty)

    def test_just_above_boundaries_refused(self):
        for fl in ('100000.01', '100001', '1.234', '-0.01', '1e6'):
            self.assertEqual(self.push_sess(flour_sacks_used=fl)[1][0], 'REJECTED', fl)
        s = self.sess()
        push(self.a1, LBL_S, s)
        for q in (2_000_000_001, -1, '1.0e3', 1.5, 'NaN', 'Infinity'):
            self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk,
                                                   'quantity': q})[0], 'REJECTED', q)
        for rate in ('0.31', '0.301', '0.3001', '-0.01', 'NaN', '1'):
            self.assertEqual(push(self.a1, LBL_I, self.inv(commission_rate=rate))[0], 'REJECTED', rate)
        for qty in ('0.2500', '0.3333', '10000000', '-0.001', '1E+3'):
            res = push(self.a1, LBL_M, {'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT',
                                        'movement_type': 'ENTRY', 'quantity': qty})[0]
            # 0.2500 a 4 decimales mais quantize == valeur : accepte ; 1E+3 vaut 1000 : accepte
            if qty in ('0.2500', '1E+3'):
                self.assertEqual(res, 'ACCEPTED', qty)
            else:
                self.assertEqual(res, 'REJECTED', qty)

    def test_dates_today_accepted_tomorrow_refused_local_timezone(self):
        t = self.today()
        self.assertEqual(self.push_sess(date=str(t))[1][0], 'ACCEPTED')
        self.assertEqual(self.push_sess(date=str(t + timedelta(days=1)))[1][0], 'REJECTED')
        self.assertEqual(self.push_sess(date=str(t - timedelta(days=400)))[1][0], 'ACCEPTED')
        # delivered_at : maintenant accepte ; demain local refuse ; 23:59 locale du jour accepte
        now = timezone.now()
        self.assertEqual(push(self.a1, LBL_I, self.inv(status='DELIVERED', delivered_at=now.isoformat()))[0], 'ACCEPTED')
        self.assertEqual(push(self.a1, LBL_I, self.inv(status='DELIVERED',
                                                        delivered_at=(now + timedelta(days=1, hours=2)).isoformat()))[0],
                         'REJECTED')
        tz = timezone.get_current_timezone()
        eod = timezone.make_aware(timezone.datetime(t.year, t.month, t.day, 23, 59, 0), tz)
        self.assertEqual(push(self.a1, LBL_I, self.inv(status='DELIVERED', delivered_at=eod.isoformat()))[0], 'ACCEPTED')
        # chiffres arabes, date naive datetime, nombre : rejet propre
        for bad in ('٢٠٢٦-١١-٢٣', 20261123, '2026-13-01', '2026-11-23T10:00:00', None):
            res = self.push_sess(date=bad)[1][0]
            self.assertEqual(res, 'REJECTED', bad)


# ------------------------------------------------------------------ contournements batch_terminal
class V9BatchTerminal(V9Base):
    def test_closed_in_previous_lot_then_new_lot_replaying_close_cannot_add_line(self):
        s = self.sess()
        push(self.a1, LBL_S, dict(s, is_closed=True, closed_at=timezone.now().isoformat()))
        res = lot(self.a1, production__ProductionSession=[dict(s, is_closed=True)],
                  production__ProductionSessionLine=[{'session': s['id'],
                                                      'bread_price': self.b3.pk, 'quantity': 5, 'source': 'CARRYOVER'}])
        self.assertEqual(res[LBL_L][0][0], 'REJECTED')
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=s['id']).count(), 0)

    def test_thread_local_not_leaked_between_lots(self):
        s = self.sess()
        res = lot(self.a1, production__ProductionSession=[dict(s, is_closed=True, closed_at=timezone.now().isoformat())])
        self.assertEqual(res[LBL_S][0][0], 'ACCEPTED')
        # lot suivant, meme process/thread : la fournee n'est plus "terminee dans ce lot"
        res = lot(self.a1, production__ProductionSessionLine=[{'session': s['id'],
                                                               'bread_price': self.b3.pk, 'quantity': 5}])
        self.assertEqual(res[LBL_L][0][0], 'REJECTED')
        inv = self.inv(status='DELIVERED', delivered_at=timezone.now().isoformat())
        self.assertEqual(lot(self.a1, sales__Invoice=[inv])[LBL_I][0][0], 'ACCEPTED')
        res = lot(self.a1, sales__InvoiceLine=[{'invoice': inv['id'], 'bread_price': self.b3.pk, 'quantity': 5}])
        self.assertEqual(res[LBL_IL][0][0], 'REJECTED')
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=inv['id']).count(), 0)

    def test_thread_local_direct_service_calls_reset(self):
        from sync.services import process_push_batch
        s = self.sess()
        process_push_batch(self.k1, {LBL_S: [dict(s, is_closed=True, closed_at=timezone.now().isoformat())]})
        out = process_push_batch(self.k1, {LBL_L: [{'session': s['id'],
                                                    'bread_price': self.b3.pk, 'quantity': 5}]})
        self.assertEqual(out[LBL_L][0]['status'], 'REJECTED')

    def test_other_node_cannot_use_batch_exception(self):
        s = self.sess()
        push(self.a1, LBL_S, s)  # fournee ouverte de K1
        inv = self.inv()
        push(self.a1, LBL_I, inv)
        # K2 pousse, dans un meme lot, la "cloture" de la fournee de K1 puis une ligne
        res = lot(self.a2, production__ProductionSession=[{'id': s['id'], 'is_closed': True}],
                  production__ProductionSessionLine=[{'session': s['id'],
                                                      'bread_price': self.b3.pk, 'quantity': 5}])
        self.assertEqual(res[LBL_S][0][0], 'REJECTED')
        self.assertEqual(res[LBL_L][0][0], 'REJECTED')
        res = lot(self.a2, sales__Invoice=[dict(inv, status='DELIVERED', delivered_at=timezone.now().isoformat())],
                  sales__InvoiceLine=[{'invoice': inv['id'], 'bread_price': self.b3.pk, 'quantity': 5}])
        self.assertEqual(res[LBL_I][0][0], 'REJECTED')
        self.assertEqual(res[LBL_IL][0][0], 'REJECTED')
        self.assertEqual(Invoice.objects.get(pk=inv['id']).status, 'PENDING')
        self.assertFalse(ProductionSession.objects.get(pk=s['id']).is_closed)
        self.assertEqual(ProductionSessionLine.objects.count() + InvoiceLine.objects.count(), 0)

    def test_k1_closed_session_other_node_line_in_k1_lot_still_refused(self):
        """Le lot de K1 ferme sa fournee ; le lot de K2 (autre requete) ne profite de rien."""
        s = self.sess()
        lot(self.a1, production__ProductionSession=[dict(s, is_closed=True, closed_at=timezone.now().isoformat())])
        res = lot(self.a2, production__ProductionSessionLine=[{'session': s['id'],
                                                               'bread_price': self.b3.pk, 'quantity': 5}])
        self.assertEqual(res[LBL_L][0][0], 'REJECTED')

    def test_rejected_close_does_not_unlock_lines(self):
        s = self.sess()
        push(self.a1, LBL_S, dict(s, is_closed=True, closed_at=timezone.now().isoformat()))
        # cloture rejetee (closed_at illisible) puis ligne
        res = lot(self.a1, production__ProductionSession=[dict(s, closed_at='garbage', is_closed=True)],
                  production__ProductionSessionLine=[{'session': s['id'],
                                                      'bread_price': self.b5.pk, 'quantity': 5}])
        self.assertEqual(res[LBL_L][0][0], 'REJECTED')
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=s['id']).count(), 0)

    def test_forged_lot_new_closed_session_gap_after_other_statuses(self):
        """Facture CANCELLED poussee neuve dans un lot : ses lignes passent ; une AUTRE facture
        deja livree d'un lot precedent reste verrouillee dans le meme lot."""
        old = self.inv(status='DELIVERED', delivered_at=timezone.now().isoformat())
        push(self.a1, LBL_I, old)
        new = self.inv(status='CANCELLED')
        res = lot(self.a1, sales__Invoice=[new, old], sales__InvoiceLine=[
            {'invoice': new['id'], 'bread_price': self.b3.pk, 'quantity': 2},
            {'invoice': old['id'], 'bread_price': self.b3.pk, 'quantity': 2}])
        self.assertEqual([x[0] for x in res[LBL_IL]], ['ACCEPTED', 'REJECTED'])

    def test_uppercase_or_braced_uuid_reference_same_parent_semantics(self):
        s = self.sess()
        push(self.a1, LBL_S, dict(s, is_closed=True, closed_at=timezone.now().isoformat()))
        res = lot(self.a1, production__ProductionSessionLine=[
            {'session': s['id'].upper(), 'bread_price': self.b3.pk, 'quantity': 5}])
        self.assertEqual(res[LBL_L][0][0], 'REJECTED')


# ------------------------------------------------------------------ defauts voisins
class V9Neighbours(V9Base):
    # ---- lignes de fournee / transferts : doublon d'une autre id ----------------
    def test_BUG_920_duplicate_line_other_id_not_silently_accepted(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk,
                                               'quantity': 10})[0], 'ACCEPTED')
        st = push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 77})[0]
        q = list(ProductionSessionLine.objects.filter(session_id=s['id']).values_list('quantity', flat=True))
        # soit rejete, soit la quantite est la bonne ; jamais ACCEPTED avec une valeur perdue
        self.assertTrue(st == 'REJECTED' or q == [77], (st, q))

    def test_BUG_920_duplicate_transfer_line_other_id_not_silently_accepted(self):
        t = {'id': uid(), 'from_node': self.k1.code, 'to_node': self.k2.code}
        push(self.a1, LBL_T, t)
        push(self.a1, LBL_TL, {'transfer': t['id'], 'bread_price': self.b3.pk, 'quantity_sent': 10})
        st = push(self.a1, LBL_TL, {'transfer': t['id'], 'bread_price': self.b3.pk, 'quantity_sent': 55})[0]
        q = list(BreadTransferLine.objects.filter(transfer_id=t['id']).values_list('quantity_sent', flat=True))
        self.assertTrue(st == 'REJECTED' or q == [55], (st, q))

    # ---- transferts ------------------------------------------------------------
    def _transfer_with_line(self, status=None):
        t = {'id': uid(), 'from_node': self.k1.code, 'to_node': self.k2.code}
        self.assertEqual(push(self.a1, LBL_T, t)[0], 'ACCEPTED')
        ln = {'transfer': t['id'], 'bread_price': self.b3.pk, 'quantity_sent': 100}
        self.assertEqual(push(self.a1, LBL_TL, ln)[0], 'ACCEPTED')
        ln = dict(ln, id=str(BreadTransferLine.objects.get(transfer_id=t['id'], bread_price=self.b3).pk))
        if status:
            BreadTransfer.objects.filter(pk=t['id']).update(transfer_status=status)
        return t, ln

    def test_transfer_line_hostile_values_refused(self):
        t, _ = self._transfer_with_line()
        for q in (-1, '٣', 2.5, True, 'abc'):
            r = push(self.a1, LBL_TL, {'transfer': t['id'], 'bread_price': self.b5.pk, 'quantity_sent': q})[0]
            self.assertEqual(r, 'REJECTED', q)
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=t['id']).count(), 1)

    def test_transfer_foreign_node_and_receiver_rules_hold(self):
        t, ln = self._transfer_with_line()
        k3 = self.k3 if hasattr(self, 'k3') else None
        if k3 is not None:
            self.assertEqual(push(api_for(k3), LBL_TL, {'transfer': t['id'], 'bread_price': self.b5.pk,
                                                        'quantity_sent': 5})[0], 'REJECTED')
        # l'emettrice ne renseigne pas la quantite recue
        self.assertEqual(push(self.a1, LBL_TL, dict(ln, quantity_received=100))[0], 'ACCEPTED')  # no-op
        self.assertIsNone(BreadTransferLine.objects.get(pk=ln['id']).quantity_received)
        # la receptrice le peut
        self.assertEqual(push(self.a2, LBL_TL, dict(ln, quantity_received=98))[0], 'ACCEPTED')
        self.assertEqual(BreadTransferLine.objects.get(pk=ln['id']).quantity_received, 98)

    def test_BUG_921_line_added_to_confirmed_transfer_refused(self):
        t, _ = self._transfer_with_line('CONFIRMED')
        st = push(self.a1, LBL_TL, {'transfer': t['id'], 'bread_price': self.b5.pk, 'quantity_sent': 40})[0]
        self.assertEqual(st, 'REJECTED')
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=t['id']).count(), 1)

    def test_BUG_921_received_quantity_rewritten_after_confirmation_refused(self):
        t, ln = self._transfer_with_line('CONFIRMED')
        BreadTransferLine.objects.filter(pk=ln['id']).update(quantity_received=100)
        st = push(self.a2, LBL_TL, dict(ln, quantity_received=1))[0]
        self.assertEqual(BreadTransferLine.objects.get(pk=ln['id']).quantity_received, 100, st)

    def test_BUG_922_transfer_to_itself_refused(self):
        t = {'id': uid(), 'from_node': self.k1.code, 'to_node': self.k1.code}
        self.assertEqual(push(self.a1, LBL_T, t)[0], 'REJECTED')
        self.assertFalse(BreadTransfer.objects.filter(pk=t['id']).exists())

    def test_transfer_hostile_quantity_sent_refused(self):
        for q in (-5, '٣', 1.5):
            t = {'id': uid(), 'from_node': self.k1.code, 'to_node': self.k2.code, 'bread_price': self.b3.pk,
                 'quantity_sent': q}
            self.assertEqual(push(self.a1, LBL_T, t)[0], 'REJECTED', q)

    # ---- fournees ----------------------------------------------------------------
    def test_session_duplicate_vacation_other_id_refused(self):
        a = self.sess(team='A')
        b = self.sess(team='A', date=a['date'])
        self.assertEqual(push(self.a1, LBL_S, a)[0], 'ACCEPTED')
        self.assertEqual(push(self.a1, LBL_S, b)[0], 'REJECTED')
        self.assertEqual(ProductionSession.objects.filter(node=self.k1, date=a['date'], team='A').count(), 1)

    def test_BUG_923_future_closed_at_refused(self):
        rec, res = self.push_sess(is_closed=True, closed_at='2099-01-01T00:00:00Z')
        self.assertEqual(res[0], 'REJECTED')

    def test_BUG_923_future_closed_at_on_transition_refused(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        push(self.a1, LBL_S, dict(s, is_closed=True, closed_at='2099-01-01T00:00:00Z'))
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertTrue(c.closed_at is None or c.closed_at <= timezone.now() + timedelta(days=1), c.closed_at)

    def test_BUG_924_inconsistent_session_totals_not_stored_as_is(self):
        """total_breads / total_fc_produced / theoretical_yield sont recalcules par REST depuis les lignes ;
        le push les copie : un poste peut creer une fournee a 4 milliards de FC sans aucune ligne."""
        rec, res = self.push_sess(total_fc_produced=2_000_000_000, total_breads=2_000_000_000)
        s = ProductionSession.objects.filter(pk=rec['id']).first()
        self.assertTrue(res[0] == 'REJECTED' or (s and s.total_fc_produced == 0), (res, s and s.total_fc_produced))

    # ---- disposals / consommables -------------------------------------------------
    def test_BUG_925_disposal_value_overflow_refused(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        d = {'id': uid(), 'session': s['id'], 'bread_price': self.b3.pk, 'disposal_type': 'SOLD_DISCOUNT',
             'quantity': 2_000_000_000, 'unit_price_sold': 2_000_000_000}
        st = push(self.a1, LBL_D, d)[0]
        # exists() : la valeur stockee (4e18) n'est meme plus relisible par l'ORM (InvalidOperation)
        self.assertEqual(st, 'REJECTED')
        self.assertFalse(BreadDisposal.objects.filter(pk=d['id']).exists())

    def test_BUG_926_movement_unknown_or_oversized_consumable_type_refused(self):
        for ctype in ('X' * 60, 12345, ['SALT'], 'sel ' * 5, ' '):
            rec = {'id': uid(), 'node': self.k1.code, 'consumable_type': ctype, 'movement_type': 'ENTRY', 'quantity': '1'}
            st = push(self.a1, LBL_M, rec)[0]
            created = ConsumableStock.objects.filter(node=self.k1).exclude(consumable_type='SALT').count()
            self.assertEqual((st, created), ('REJECTED', 0), ctype)

    def test_movement_decimal_stock_sequence_exact(self):
        for q, mt in (('10', 'ENTRY'), ('0.25', 'EXIT'), ('0.333', 'EXIT'), ('1.5', 'ENTRY')):
            self.assertEqual(push(self.a1, LBL_M, {'id': uid(), 'node': self.k1.code, 'consumable_type': 'YEAST',
                                                   'movement_type': mt, 'quantity': q, 'unit_price': '100'})[0], 'ACCEPTED')
        self.assertEqual(ConsumableStock.objects.get(node=self.k1, consumable_type='YEAST').quantity, Dc('10.917'))

    # ---- comptages ----------------------------------------------------------------
    def test_count_rules_hold_and_unknown_type(self):
        d = str(self.today())
        base = {'node': self.k1.code, 'consumable_type': 'SALT', 'count_date': d,
                'system_quantity': '10', 'physical_quantity': '8.5', 'gap': '-1.5'}
        self.assertEqual(push(self.a1, 'production.ConsumableCount', base)[0], 'ACCEPTED')
        self.assertEqual(ConsumableCount.objects.get(node=self.k1, count_date=d).gap, Dc('-1.5'))
        for patch in ({'gap': '0'}, {'physical_quantity': '-1', 'gap': '-11'}, {'system_quantity': '٣', 'gap': '0'},
                      {'physical_quantity': '8.5555', 'gap': '-1.4445'}, {'consumable_type': 'X' * 11}):
            r = push(self.a1, 'production.ConsumableCount', dict(base, count_date=str(self.today() - timedelta(days=1)), **patch))[0]
            self.assertEqual(r, 'REJECTED', patch)

    def test_stock_and_derived_models_not_pushable(self):
        for lab in ('production.BreadStock', 'production.DailyBreadStockSnapshot', 'production.ConsumableStock',
                    'production.DailyOpeningConfirmation', 'treasury.CashbookEntry'):
            res = lot(self.a1, **{lab.replace('.', '__'): [{'id': uid(), 'node': self.k1.code, 'quantity': 999}]})
            self.assertEqual(res[lab][0][0], 'REJECTED', lab)

    # ---- factures ------------------------------------------------------------------
    def test_BUG_927_invoice_invalid_team_refused(self):
        for team in ('Z', 'J', 'AB', '1'):
            rec = self.inv(team=team)
            st = push(self.a1, LBL_I, rec)[0]
            self.assertEqual(st, 'REJECTED', team)
            self.assertFalse(Invoice.objects.filter(pk=rec['id']).exists(), team)

    def test_BUG_928_transfer_quantities_above_2e9_refused(self):
        t = {'id': uid(), 'from_node': self.k1.code, 'to_node': self.k2.code, 'bread_price': self.b3.pk,
             'quantity_sent': 3_000_000_000}
        self.assertEqual(push(self.a1, LBL_T, t)[0], 'REJECTED')
        self.assertFalse(BreadTransfer.objects.filter(pk=t['id']).exists())

    def test_BUG_928_transfer_line_quantity_above_2e9_refused(self):
        t, _ = self._transfer_with_line()
        st = push(self.a1, LBL_TL, {'transfer': t['id'], 'bread_price': self.b5.pk, 'quantity_sent': 3_000_000_000})[0]
        self.assertEqual(st, 'REJECTED')
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=t['id']).count(), 1)


# ------------------------------------------------------------------ ids entiers de lignes (sync_now envoie str(l.id))
class V9LineIdCollision(V9Base):
    """`sync_now` pousse `id: str(l.id)` (PK entiere locale) pour InvoiceLine / ProductionSessionLine /
    BreadTransferLine ; deux postes ont forcement les memes petits ids."""

    def test_BUG_919_invoice_lines_same_local_id_two_nodes(self):
        i1, i2 = self.inv(), self.inv(node=self.k2.code)
        push(self.a1, LBL_I, i1)
        push(self.a2, LBL_I, i2)
        r1 = push(self.a1, LBL_IL, {'id': '7', 'invoice': i1['id'], 'bread_price': self.b3.pk, 'quantity': 3})
        r2 = push(self.a2, LBL_IL, {'id': '7', 'invoice': i2['id'], 'bread_price': self.b3.pk, 'quantity': 4})
        self.assertEqual((r1[0], r2[0]), ('ACCEPTED', 'ACCEPTED'), (r1, r2))
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=i2['id']).count(), 1)

    def test_BUG_919_session_lines_same_local_id_two_nodes(self):
        s1, s2 = self.sess(), self.sess(node=self.k2.code)
        push(self.a1, LBL_S, s1)
        push(self.a2, LBL_S, s2)
        push(self.a1, LBL_L, {'id': '5', 'session': s1['id'], 'bread_price': self.b3.pk, 'quantity': 11})
        r2 = push(self.a2, LBL_L, {'id': '5', 'session': s2['id'], 'bread_price': self.b3.pk, 'quantity': 22})
        # jamais ACCEPTED sans que la ligne du second poste existe (perte silencieuse)
        self.assertEqual(r2[0], 'ACCEPTED')
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=s2['id']).count(), 1)
