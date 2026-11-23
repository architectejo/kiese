"""Verification adversariale BUG-331/332 (testeur-charge, 2026-11-21e-b)."""
from decimal import Decimal

from django.db import transaction
from django.test import TestCase

from clients.models import Client
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice, InvoiceLine
from sync.services import MAX_LINE_QUANTITY, _push_invoice_line

INVALID = [-1, '-1', 2.5, '2.5', '3.0', ' 3.5 ', True, False, float('nan'), float('inf'),
           float('-inf'), 1e30, 10 ** 30, MAX_LINE_QUANTITY + 1, '1000001', [3], {'q': 3},
           '', 'abc', '1e3', (1,)]


class Base(TestCase):
    status = 'PENDING'

    def setUp(self):
        self.node = make_node(code='QC1')
        self.bp = make_bread_price('QC331', 'Pain QC', 500)
        fa = make_user('FACTURIER', node=self.node, team='A', username='qc_fa')
        self.cl = make_client(self.node, current_debt=Decimal('1000.00'))
        self.inv = Invoice.objects.create(
            node=self.node, client=self.cl, facturier=fa, team='A', status=self.status,
            payment_type='CREDIT', payment_amount=Decimal('0'), order_total=Decimal('2000'),
            initial_order_total=Decimal('2000'))
        self.line = InvoiceLine.objects.create(invoice=self.inv, bread_price=self.bp, quantity=4)

    def push(self, with_id=True, **kw):
        rec = {'invoice': str(self.inv.pk), 'bread_price': self.bp.pk}
        if with_id:
            rec['id'] = self.line.pk
        rec.update(kw)
        with transaction.atomic():
            return _push_invoice_line(self.node, rec)

    def snapshot(self):
        return (
            list(InvoiceLine.objects.order_by('pk').values_list('pk', 'quantity', 'ordered_quantity', 'line_total')),
            Client.objects.values_list('current_debt', flat=True).get(pk=self.cl.pk),
            Invoice.objects.values_list('order_total', 'status').get(pk=self.inv.pk),
            list(BreadStock.objects.values_list('pk', 'qty_produced', 'qty_received', 'qty_sent', 'qty_disposed', 'qty_adjusted')),
        )


class ExistingLine(Base):
    def _all(self):
        for field in ('quantity', 'ordered_quantity'):
            for bad in INVALID:
                before = self.snapshot()
                r = self.push(**{field: bad})
                self.assertEqual(r['status'], 'REJECTED', (self.status, field, repr(bad)))
                self.assertEqual(before, self.snapshot(), (self.status, field, repr(bad)))

    def test_invalides_pending(self):
        self._all()

    def test_invalides_delivered(self):
        Invoice.objects.filter(pk=self.inv.pk).update(status='DELIVERED')
        self._all()

    def test_bornes_valides(self):
        for v in (0, 1, '3', 3.0, MAX_LINE_QUANTITY):
            self.assertEqual(self.push(quantity=v)['status'], 'ACCEPTED', repr(v))
        self.assertEqual(InvoiceLine.objects.get(pk=self.line.pk).quantity, MAX_LINE_QUANTITY)

    def test_none_ignore(self):
        before = self.snapshot()
        self.assertEqual(self.push(quantity=None)['status'], 'ACCEPTED')
        self.assertEqual(before, self.snapshot())

    def test_idempotence(self):
        self.push(quantity=9)
        s = self.snapshot()
        for _ in range(3):
            self.assertEqual(self.push(quantity=9)['status'], 'ACCEPTED')
        self.assertEqual(s, self.snapshot())

    def test_line_total_aux_bornes(self):
        self.push(quantity=MAX_LINE_QUANTITY)
        self.assertEqual(InvoiceLine.objects.get(pk=self.line.pk).line_total,
                         Decimal(MAX_LINE_QUANTITY) * 500)


class Creation(Base):
    def test_creation_invalides(self):
        for bad in INVALID:
            before = self.snapshot()
            r = self.push(with_id=False, quantity=bad)
            self.assertEqual(r['status'], 'REJECTED', repr(bad))
            self.assertEqual(before, self.snapshot(), repr(bad))

    def test_creation_bornes(self):
        # BUG-919/938/940 : sans id, une ligne de meme (facture, categorie) est retrouvee par cle
        # naturelle et mise a jour (idempotence) ; une CREATION exige donc une categorie libre.
        for i, v in enumerate((0, 1, '3', MAX_LINE_QUANTITY)):
            bp = make_bread_price(f'QC{i}', f'Pain QC{i}', 500 + i)
            n = InvoiceLine.objects.count()
            self.assertEqual(self.push(with_id=False, quantity=v, bread_price=bp.pk)['status'], 'ACCEPTED', repr(v))
            self.assertEqual(InvoiceLine.objects.count(), n + 1)
            self.assertEqual(InvoiceLine.objects.get(invoice=self.inv, bread_price=bp).quantity, int(v))

    def test_creation_sans_quantite(self):
        rec = {'invoice': str(self.inv.pk), 'bread_price': self.bp.pk}
        with transaction.atomic():
            self.assertEqual(_push_invoice_line(self.node, rec)['status'], 'ACCEPTED')
