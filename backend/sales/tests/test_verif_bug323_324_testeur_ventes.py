"""Verification independante BUG-323 (dates ISO au push sync) et BUG-324 (rejeu de lignes sur facture terminale).

Testeur ventes, 2026-11-21. Appelle directement `sync.services._push_invoice` / `_push_invoice_line`.
"""
from datetime import datetime, timezone as dt_tz
from decimal import Decimal
from unittest import expectedFailure

from django.test import TestCase
from django.utils import timezone

from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice, InvoiceLine

D = Decimal


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='VA')
        self.bpa = make_bread_price('V323A', 'Pain 500', 500)
        self.bpb = make_bread_price('V323B', 'Pain 300', 300)
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='v_fa')
        self.cl = make_client(self.node, credit_limit=D('50000.00'))

    def mk(self, qa=4, qb=2, pay='0.00'):
        inv = Invoice.objects.create(
            node=self.node, client=self.cl, facturier=self.fa, team='A', status='PENDING',
            payment_type='CREDIT', payment_amount=D(pay), order_total=D(qa * 500 + qb * 300),
            initial_order_total=D(qa * 500 + qb * 300))
        la = InvoiceLine.objects.create(invoice=inv, bread_price=self.bpa, quantity=qa)
        lb = InvoiceLine.objects.create(invoice=inv, bread_price=self.bpb, quantity=qb)
        return inv, la, lb

    def pinv(self, rec):
        from sync.services import _push_invoice
        return _push_invoice(self.node, rec)

    def pline(self, rec):
        from sync.services import _push_invoice_line
        return _push_invoice_line(self.node, rec)

    def lrec(self, inv, la, **kw):
        rec = {'id': la.pk, 'invoice': str(inv.pk), 'bread_price': la.bread_price_id}
        rec.update(kw)
        return rec


class Bug323Dates(Base):
    def deliver_with(self, value):
        inv, _, _ = self.mk()
        r = self.pinv({'id': str(inv.pk), 'status': 'DELIVERED', 'delivered_at': value})
        inv.refresh_from_db()
        return inv, r

    def test_iso_avec_offset(self):
        inv, r = self.deliver_with('2026-11-20T10:00:00+01:00')
        self.assertNotEqual(r['status'], 'REJECTED', r)
        self.assertEqual(inv.status, 'DELIVERED')
        self.assertEqual(inv.delivered_at, datetime(2026, 11, 20, 9, 0, tzinfo=dt_tz.utc))

    def test_iso_z(self):
        inv, _ = self.deliver_with('2026-11-20T10:00:00Z')
        self.assertEqual(inv.status, 'DELIVERED')
        self.assertEqual(inv.delivered_at, datetime(2026, 11, 20, 10, 0, tzinfo=dt_tz.utc))

    def test_iso_naif_devient_aware(self):
        inv, _ = self.deliver_with('2026-11-20T10:00:00')
        self.assertEqual(inv.status, 'DELIVERED')
        self.assertTrue(timezone.is_aware(inv.delivered_at))

    def test_iso_avec_microsecondes_et_espaces(self):
        inv, _ = self.deliver_with('  2026-11-20T10:00:00.123456+00:00 ')
        self.assertEqual(inv.status, 'DELIVERED')

    def test_datetime_objet(self):
        inv, _ = self.deliver_with(datetime(2026, 11, 20, 10, 0, tzinfo=dt_tz.utc))
        self.assertEqual(inv.status, 'DELIVERED')

    def test_none_et_vide(self):
        for v in (None, ''):
            inv, r = self.deliver_with(v)
            self.assertEqual(inv.status, 'DELIVERED', v)
            self.assertNotEqual(r.get('status'), 'REJECTED')

    def test_invalides_rejetes_sans_exception(self):
        for v in ('pas une date', '2026-13-45T99:99:99', '2026-02-30T10:00:00', 'x' * 100000,
                  '9' * 5000, '\x00', '2026-11-20T10:00:00+99:99', 12345, 1.5, True, False,
                  ['2026-11-20'], {'a': 1}):
            inv, r = self.deliver_with(v)
            self.assertEqual(r['status'], 'REJECTED', repr(v)[:40])
            self.assertIn('invalide', r['reason'], repr(v)[:40])
            self.assertEqual(inv.status, 'PENDING', repr(v)[:40])
            self.assertIsNone(inv.delivered_at, repr(v)[:40])

    def test_not_served_at_invalide_rejete(self):
        inv, _, _ = self.mk()
        r = self.pinv({'id': str(inv.pk), 'status': 'NOT_SERVED', 'not_served_at': 'hier soir'})
        self.assertEqual(r['status'], 'REJECTED')
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'PENDING')

    def test_not_served_at_iso_ok(self):
        inv, _, _ = self.mk()
        self.pinv({'id': str(inv.pk), 'status': 'NOT_SERVED', 'not_served_at': '2026-11-20T08:00:00Z',
                   'not_served_reason': 'absent'})
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'NOT_SERVED')
        self.assertEqual(inv.not_served_at, datetime(2026, 11, 20, 8, 0, tzinfo=dt_tz.utc))

    def test_creation_avec_delivered_at_iso_et_invalide(self):
        import uuid
        rid = str(uuid.uuid4())
        r = self.pinv({'id': rid, 'node': 'VA', 'client': str(self.cl.pk), 'status': 'DELIVERED',
                       'delivered_at': '2026-11-20T10:00:00Z', 'receipt_number': 'VA-ISO-1'})
        self.assertNotEqual(r['status'], 'REJECTED', r)
        self.assertTrue(timezone.is_aware(Invoice.objects.get(pk=rid).delivered_at))
        rid2 = str(uuid.uuid4())
        r = self.pinv({'id': rid2, 'node': 'VA', 'status': 'DELIVERED', 'delivered_at': 'zzz'})
        self.assertEqual(r['status'], 'REJECTED')
        self.assertFalse(Invoice.objects.filter(pk=rid2).exists())

    def test_idempotence_livraison_iso(self):
        inv, _, _ = self.mk()
        rec = {'id': str(inv.pk), 'status': 'DELIVERED', 'delivered_at': '2026-11-20T10:00:00Z'}
        for _ in range(3):
            r = self.pinv(rec)
            self.assertNotEqual(r['status'], 'REJECTED')
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'DELIVERED')
        self.assertEqual(inv.delivered_at, datetime(2026, 11, 20, 10, 0, tzinfo=dt_tz.utc))

    def test_signal_tolerant_chaine_directe(self):
        """Le signal pre_save ne plante pas si une chaine ISO atteint l'instance (defense en profondeur)."""
        inv, _, _ = self.mk()
        inv.status = 'DELIVERED'
        inv.delivered_at = '2026-11-20T10:00:00Z'
        from treasury.signals import block_delivery_on_already_reported_vacation as sig
        sig(sender=Invoice, instance=inv)
        inv.delivered_at = 'illisible'
        sig(sender=Invoice, instance=inv)


class Bug324Rejeu(Base):
    def test_rejeu_sur_statuts_terminaux(self):
        for terminal in ('NOT_SERVED', 'DELIVERED', 'CANCELLED'):
            inv, la, lb = self.mk()
            Invoice.objects.filter(pk=inv.pk).update(status=terminal)
            InvoiceLine.objects.filter(pk=la.pk).update(quantity=0, line_total=0, ordered_quantity=4)
            self.pline(self.lrec(inv, la, quantity=4, ordered_quantity=4))
            la.refresh_from_db()
            self.assertEqual((la.quantity, la.ordered_quantity, la.line_total), (0, 4, 0), terminal)

    def test_ordered_quantity_renseigne_une_seule_fois(self):
        inv, la, _ = self.mk()
        Invoice.objects.filter(pk=inv.pk).update(status='DELIVERED')
        InvoiceLine.objects.filter(pk=la.pk).update(quantity=2, line_total=1000, ordered_quantity=None)
        self.pline(self.lrec(inv, la, quantity=2, ordered_quantity=4))
        la.refresh_from_db()
        self.assertEqual(la.ordered_quantity, 4)
        self.pline(self.lrec(inv, la, quantity=2, ordered_quantity=9))
        self.pline(self.lrec(inv, la, quantity=2, ordered_quantity=1))
        la.refresh_from_db()
        self.assertEqual(la.ordered_quantity, 4)

    def test_ordered_quantity_vide_capte_ancienne_quantite_perimee(self):
        inv, la, _ = self.mk()
        Invoice.objects.filter(pk=inv.pk).update(status='NOT_SERVED')
        InvoiceLine.objects.filter(pk=la.pk).update(quantity=0, line_total=0, ordered_quantity=None)
        self.pline(self.lrec(inv, la, quantity=4))
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.ordered_quantity), (0, 4))

    def test_quantite_servie_ne_peut_que_baisser_sur_terminal(self):
        inv, la, _ = self.mk()
        Invoice.objects.filter(pk=inv.pk).update(status='DELIVERED')
        self.pline(self.lrec(inv, la, quantity=3))
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.line_total), (3, 1500))
        self.pline(self.lrec(inv, la, quantity=4))
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.line_total), (3, 1500))
        self.pline(self.lrec(inv, la, quantity=1))
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.line_total), (1, 500))

    def test_pending_reste_modifiable_dans_les_deux_sens(self):
        inv, la, _ = self.mk()
        self.pline(self.lrec(inv, la, quantity=2, ordered_quantity=4))
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.ordered_quantity, la.line_total), (2, 4, 1000))
        self.pline(self.lrec(inv, la, quantity=7, ordered_quantity=9))
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.ordered_quantity, la.line_total), (7, 9, 3500))

    def test_prix_fige(self):
        inv, la, _ = self.mk()
        self.bpa.unit_price = D('900')
        self.bpa.save()
        self.pline(self.lrec(inv, la, quantity=3, unit_price='1', line_total='3'))
        la.refresh_from_db()
        self.assertEqual((la.unit_price, la.line_total), (500, 1500))

    def _probe(self, terminal, fname, bad):
        from django.db import transaction
        inv, la, _ = self.mk()
        Invoice.objects.filter(pk=inv.pk).update(status=terminal)
        before = InvoiceLine.objects.values_list('quantity', 'ordered_quantity').get(pk=la.pk)
        with transaction.atomic():
            r = self.pline(self.lrec(inv, la, **{fname: bad}))
        after = InvoiceLine.objects.values_list('quantity', 'ordered_quantity').get(pk=la.pk)
        return r, before, after

    def _assert_rejected(self, bads):
        for terminal in ('PENDING', 'DELIVERED'):
            for fname in ('quantity', 'ordered_quantity'):
                for bad in bads:
                    r, before, after = self._probe(terminal, fname, bad)
                    self.assertEqual(r['status'], 'REJECTED', (terminal, fname, bad))
                    self.assertEqual(before, after, (terminal, fname, bad))

    def test_valeurs_non_numeriques_rejetees(self):
        self._assert_rejected(['abc', '2.5', [1], {'a': 1}, float('nan'), '1e3'])

    @expectedFailure
    def test_bug331_negatifs_et_enormes_rejetes_sans_exception(self):
        """BUG-331 : -3, inf, 10**30 -> IntegrityError/OverflowError/InvalidOperation (500)."""
        self._assert_rejected([-3, '-3', float('inf'), 10 ** 30])

    @expectedFailure
    def test_bug332_non_entiers_et_booleens_rejetes(self):
        """BUG-332 : 2.5 tronque en 2 (ACCEPTED), True ignore en silence (ACCEPTED)."""
        self._assert_rejected([2.5, True])

    def test_idempotence_rejeux_successifs(self):
        inv, la, _ = self.mk()
        Invoice.objects.filter(pk=inv.pk).update(status='NOT_SERVED')
        rec = self.lrec(inv, la, quantity=0, ordered_quantity=4)
        for _ in range(4):
            r = self.pline(rec)
            self.assertNotEqual(r['status'], 'REJECTED')
        self.pline(self.lrec(inv, la, quantity=4, ordered_quantity=4))
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.ordered_quantity, la.line_total), (0, 4, 0))
        self.assertEqual(InvoiceLine.objects.filter(invoice=inv).count(), 2)

    def test_ligne_inexistante_creee_et_dependances(self):
        inv, _, _ = self.mk()
        r = self.pline({'invoice': '00000000-0000-0000-0000-000000000000', 'bread_price': self.bpa.pk, 'quantity': 1})
        self.assertEqual(r['status'], 'REJECTED')


class SyncSansEffetBpStock(Base):
    def test_push_facture_et_lignes_ne_touche_ni_bp_ni_stock(self):
        inv, la, lb = self.mk(pay='1000.00')
        stock_before = list(BreadStock.objects.order_by('pk').values_list('pk', 'qty_produced', 'qty_sent', 'qty_received', 'qty_disposed'))
        self.cl.refresh_from_db()
        debt_before = self.cl.current_debt
        self.pinv({'id': str(inv.pk), 'status': 'NOT_SERVED', 'order_total': '0.00', 'payment_amount': '1000.00',
                   'debt_after': '-5000.00', 'not_served_at': '2026-11-20T08:00:00Z'})
        self.pline(self.lrec(inv, la, quantity=0, ordered_quantity=4))
        self.pline(self.lrec(inv, la, quantity=4, ordered_quantity=4))
        self.pinv({'id': str(inv.pk), 'status': 'DELIVERED', 'delivered_at': '2026-11-20T10:00:00Z'})
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, debt_before)
        self.assertEqual(stock_before,
                         list(BreadStock.objects.order_by('pk').values_list('pk', 'qty_produced', 'qty_sent', 'qty_received', 'qty_disposed')))
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'NOT_SERVED')

    def test_livraison_pending_vers_delivered_sans_destockage(self):
        inv, _, _ = self.mk()
        stock_before = list(BreadStock.objects.values_list('pk', 'qty_produced', 'qty_sent', 'qty_received', 'qty_disposed'))
        self.pinv({'id': str(inv.pk), 'status': 'DELIVERED', 'delivered_at': '2026-11-20T10:00:00Z'})
        self.assertEqual(sorted(stock_before),
                         sorted(BreadStock.objects.values_list('pk', 'qty_produced', 'qty_sent', 'qty_received', 'qty_disposed')))
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, 0)
