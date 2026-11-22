"""BUG-519 : la ligne de vente recréée par le push garde les prix du nœud local."""
import itertools
from decimal import Decimal

from django.db import transaction
from django.test import TestCase

from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine
from sync.services import _push_invoice_line


class InvoiceLinePricesSyncTests(TestCase):
    _ids = itertools.count(900001)

    def setUp(self):
        self.node = make_node(code='QB5')
        self.bp = make_bread_price('QB519', 'Pain 300', 300)
        fa = make_user('FACTURIER', node=self.node, team='A', username='qb519_fa')
        cl = make_client(self.node, credit_limit=Decimal('50000.00'))
        self.inv = Invoice.objects.create(
            node=self.node, client=cl, facturier=fa, team='A', status='PENDING',
            payment_type='CREDIT', payment_amount=Decimal('0'), order_total=Decimal('0'),
            initial_order_total=Decimal('0'))

    def _push(self, **kw):
        rec = {'id': next(self._ids), 'invoice': str(self.inv.pk),
               'bread_price': self.bp.pk, 'quantity': 10}
        rec.update(kw)
        with transaction.atomic():
            res = _push_invoice_line(self.node, rec)
        return rec['id'], res

    def _change_cloud_tariff(self):
        self.bp.unit_price = 400
        self.bp.save()

    def test_prix_local_conserve_apres_changement_de_tarif_cloud(self):
        self._change_cloud_tariff()
        lid, res = self._push(unit_price='300', full_unit_price='300')
        self.assertEqual(res['status'], 'ACCEPTED')
        line = InvoiceLine.objects.get(pk=lid)
        self.assertEqual((line.unit_price, line.full_unit_price), (300, 300))
        self.assertEqual(line.line_total, Decimal('3000'))

    def test_prix_net_exact_du_noeud_local(self):
        self._change_cloud_tariff()
        lid, res = self._push(unit_price=225, full_unit_price=300)
        self.assertEqual(res['status'], 'ACCEPTED')
        line = InvoiceLine.objects.get(pk=lid)
        self.assertEqual((line.unit_price, line.full_unit_price), (225, 300))
        self.assertEqual(line.line_total, Decimal('2250'))

    def test_ancien_payload_sans_prix_utilise_le_tarif_courant(self):
        self._change_cloud_tariff()
        lid, res = self._push()
        self.assertEqual(res['status'], 'ACCEPTED')
        line = InvoiceLine.objects.get(pk=lid)
        self.assertEqual((line.unit_price, line.full_unit_price), (400, 400))
        self.assertEqual(line.line_total, Decimal('4000'))

    def test_prix_invalides_rejetes(self):
        for field in ('unit_price', 'full_unit_price'):
            for bad in (-1, '-5', 'abc', 2.5, '2.5', True, float('nan'), [1], '1e999999'):
                n = InvoiceLine.objects.count()
                _, res = self._push(**{field: bad})
                self.assertEqual(res['status'], 'REJECTED', (field, bad))
                self.assertEqual(InvoiceLine.objects.count(), n)
