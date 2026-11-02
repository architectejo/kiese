"""
BUG-100 (dev-backend, 2026-10-30) : un remboursement/dépôt sans ligne
(BUG-090/098, `is_debt_repayment=True`), livré directement via l'API
`POST /api/sales/invoices/`, ne doit jamais être bloqué par le verrou de
vacation (BUG-036, `treasury.signals.block_delivery_on_already_reported_vacation`)
même quand un `FacturierReport` Niveau 1 a déjà été généré pour le même
(nœud, équipe, date) — jour courant. Un remboursement n'est explicitement
pas une vente (CLAUDE.md §5.2) : il ne modifie ni le stock de pains ni les
ventes cash théoriques déjà figées dans le rapport, il ajoute seulement un
versement, correctement capté si le rapport est régénéré ensuite.

En revanche, une vraie vente livrée après génération du rapport doit
continuer à être bloquée (non-régression BUG-036).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import FacturierReport


class RepaymentNotBlockedByVacationLockTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_probe_repay')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='factA_probe_repay')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.api_gerant = APIClient()
        self.api_gerant.force_authenticate(self.gerant)
        self.api_fact = APIClient()
        self.api_fact.force_authenticate(self.facA)

    def _deliver_normal_invoice_and_generate_report(self):
        inv = Invoice.objects.create(
            node=self.node, client=self.client_obj, facturier=self.facA, team='A',
            status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
            node_origin=self.node.code, debt_before=Decimal('0.00'),
        )
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bread, quantity=5)
        inv.compute_order_total()
        inv.payment_amount = inv.order_total
        inv.compute_debt_after()
        inv.save()
        inv.deliver(livreur=self.facA)

        resp = self.api_gerant.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        FacturierReport.objects.get(node=self.node, team='A')

    def test_repayment_via_api_after_report_generated_same_day_succeeds(self):
        # 1) Une facture normale est livrée et le rapport Niveau 1 est généré
        #    pour (K1, équipe A, aujourd'hui).
        self._deliver_normal_invoice_and_generate_report()

        # 2) Un client vient rembourser sa dette / déposer en épargne plus
        #    tard dans la même vacation (même jour, même équipe) : le
        #    facturier utilise le flux BUG-090/098 (`is_debt_repayment`),
        #    qui livre directement la facture (pas de ligne de pain à
        #    confirmer physiquement). Ce n'est pas une vente : le verrou de
        #    vacation ne doit pas s'appliquer (BUG-100).
        self.client_obj.current_debt = Decimal('1000.00')
        self.client_obj.save(update_fields=['current_debt'])

        resp2 = self.api_fact.post('/api/sales/invoices/', {
            'client': str(self.client_obj.id),
            'is_debt_repayment': True,
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'lines': [],
        }, format='json')

        self.assertEqual(resp2.status_code, 201, resp2.content)
        invoice_id = resp2.json()['id']
        repayment = Invoice.objects.get(pk=invoice_id)
        self.assertTrue(repayment.is_debt_repayment)
        self.assertEqual(repayment.status, Invoice.Status.DELIVERED)

        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('500.00'))

    def test_normal_sale_delivery_still_blocked_after_report_generated(self):
        # Non-régression BUG-036 : une vraie vente livrée après génération du
        # rapport Niveau 1 reste bloquée (le gérant doit régénérer le
        # rapport explicitement).
        self._deliver_normal_invoice_and_generate_report()

        inv2 = Invoice.objects.create(
            node=self.node, client=self.client_obj, facturier=self.facA, team='A',
            status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
            node_origin=self.node.code, debt_before=Decimal('0.00'),
        )
        InvoiceLine.objects.create(invoice=inv2, bread_price=self.bread, quantity=2)
        inv2.compute_order_total()
        inv2.payment_amount = inv2.order_total
        inv2.compute_debt_after()
        inv2.save()

        with self.assertRaises(Exception):
            inv2.deliver(livreur=self.facA)
