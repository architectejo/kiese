"""BUG-331/332 : `_push_invoice_line` valide strictement la quantité (REJECTED, jamais 500)."""
from decimal import Decimal

from django.db import transaction
from django.test import TestCase

from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine
from sync.services import MAX_LINE_QUANTITY, _push_invoice_line


class InvoiceLineQuantityTests(TestCase):
    def setUp(self):
        self.node = make_node(code='QB1')
        self.bp = make_bread_price('QB331', 'Pain 500', 500)
        fa = make_user('FACTURIER', node=self.node, team='A', username='qb_fa')
        cl = make_client(self.node, credit_limit=Decimal('50000.00'))
        self.inv = Invoice.objects.create(
            node=self.node, client=cl, facturier=fa, team='A', status='PENDING',
            payment_type='CREDIT', payment_amount=Decimal('0'), order_total=Decimal('2000'),
            initial_order_total=Decimal('2000'))
        self.line = InvoiceLine.objects.create(invoice=self.inv, bread_price=self.bp, quantity=4)

    def _push(self, **kw):
        rec = {'id': self.line.pk, 'invoice': str(self.inv.pk), 'bread_price': self.bp.pk}
        rec.update(kw)
        with transaction.atomic():
            return _push_invoice_line(self.node, rec)

    def _state(self):
        return InvoiceLine.objects.values_list('quantity', 'ordered_quantity').get(pk=self.line.pk)

    def test_valeurs_invalides_rejetees_sans_exception(self):
        bads = [-3, '-3', float('inf'), float('-inf'), float('nan'), 10 ** 30,
                MAX_LINE_QUANTITY + 1, 2 ** 40, 2.5, True, False, 'abc', '2.5', '1e3', [1], {'a': 1}]
        for status in ('PENDING', 'DELIVERED'):
            Invoice.objects.filter(pk=self.inv.pk).update(status=status)
            for field in ('quantity', 'ordered_quantity'):
                for bad in bads:
                    before = self._state()
                    r = self._push(**{field: bad})
                    self.assertEqual(r['status'], 'REJECTED', (status, field, bad))
                    self.assertEqual(before, self._state(), (status, field, bad))

    def test_valeurs_valides_acceptees(self):
        self.assertEqual(self._push(quantity=7)['status'], 'ACCEPTED')
        self.assertEqual(self._push(quantity='6')['status'], 'ACCEPTED')
        self.assertEqual(self._push(quantity=3.0)['status'], 'ACCEPTED')
        self.assertEqual(self._push(quantity=MAX_LINE_QUANTITY)['status'], 'ACCEPTED')
        self.assertEqual(self._push(quantity=0)['status'], 'ACCEPTED')

    def test_creation_de_ligne_valide_aussi_la_quantite(self):
        for bad in (-1, 2.5, True, 10 ** 30, 'x'):
            rec = {'invoice': str(self.inv.pk), 'bread_price': self.bp.pk, 'quantity': bad}
            with transaction.atomic():
                r = _push_invoice_line(self.node, rec)
            self.assertEqual(r['status'], 'REJECTED', bad)
        self.assertEqual(InvoiceLine.objects.filter(invoice=self.inv).count(), 1)
