"""Controle independant de BUG-508/363 : `InvoiceLine.full_unit_price` (testeur ventes, 2026-11-22)."""
from decimal import Decimal

from django.test import TestCase

from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine

D = Decimal


class FullUnitPrice(TestCase):
    def setUp(self):
        self.node = make_node(code='VF')
        self.bp = make_bread_price('VF150', 'Pain 150', 150)
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='vf_fa')
        self.cl = make_client(self.node)

    def inv(self, **kw):
        return Invoice.objects.create(node=self.node, client=self.cl, facturier=self.fa, team='A',
                                      status='PENDING', payment_type='CREDIT', **kw)

    def retarif(self, price):
        self.bp.unit_price = price
        self.bp.save()

    def test_normale_figee(self):
        l = InvoiceLine.objects.create(invoice=self.inv(), bread_price=self.bp, quantity=10)
        self.assertEqual((l.unit_price, l.full_unit_price, l.line_total), (150, 150, 1500))
        self.retarif(400)
        l.quantity = 8
        l.save()
        l.refresh_from_db()
        self.assertEqual((l.unit_price, l.full_unit_price, l.line_total, l.loss), (150, 150, 1200, 0))

    def test_soldee_figee_et_perte_stable(self):
        l = InvoiceLine.objects.create(invoice=self.inv(is_soldee=True), bread_price=self.bp, quantity=10)
        self.assertEqual((l.unit_price, l.full_unit_price), (113, 150))
        self.assertEqual(l.loss, D(370))
        self.retarif(400)
        l.save()
        l.refresh_from_db()
        self.assertEqual((l.unit_price, l.full_unit_price, l.loss), (113, 150, D(370)))

    def test_rg_soldee(self):
        l = InvoiceLine.objects.create(invoice=self.inv(is_soldee=True, special_code='RG'), bread_price=self.bp,
                                       quantity=4)
        self.assertEqual((l.unit_price, l.full_unit_price), (113, 150))

    def test_ligne_ancienne_sans_champ(self):
        l = InvoiceLine.objects.create(invoice=self.inv(), bread_price=self.bp, quantity=2)
        InvoiceLine.objects.filter(pk=l.pk).update(full_unit_price=None)
        l.refresh_from_db()
        self.assertEqual(l.loss, 0)

    def test_sync_push_creation_et_rejeu_ancien_evenement(self):
        from sync.services import _push_invoice_line
        i = self.inv()
        rec = {'id': 987654, 'invoice': str(i.pk),
               'bread_price': self.bp.pk, 'quantity': 3, 'unit_price': 150}  # sans full_unit_price
        self.assertTrue(_push_invoice_line(self.node, rec)['status'] != 'REJECTED')
        l = InvoiceLine.objects.get(pk=rec['id'])
        self.assertEqual((l.unit_price, l.full_unit_price), (150, 150))
        self.retarif(400)
        rec['quantity'] = 2
        self.assertNotEqual(_push_invoice_line(self.node, rec)['status'], 'REJECTED')
        l.refresh_from_db()
        self.assertEqual((l.quantity, l.unit_price, l.full_unit_price, l.line_total), (2, 150, 150, 300))
        # champ present dans l'evenement (nouveau format) : ignore sans erreur
        rec2 = dict(rec, quantity=1, full_unit_price=999)
        self.assertNotEqual(_push_invoice_line(self.node, rec2)['status'], 'REJECTED')
        l.refresh_from_db()
        self.assertEqual(l.full_unit_price, 150)
