"""
BUG-122 (Q-002) : report de dette entre deux périodes de commission.

Réponse du client (2026-11-02, via le coordinateur) : quand le net à payer
d'un client est négatif (retenues > CM) à l'issue d'une période, ce montant
n'est jamais remis à zéro ni réclamé immédiatement — il doit être repris
comme déduction supplémentaire sur la commission du MÊME client à la
période SUIVANTE, cumulatif, même logique que BP_client (CLAUDE.md §5.2).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from core.testing import make_node, make_user, make_client, make_bread_price
from commissions.models import CommissionPeriod, ClientCommission
from sales.models import Invoice, InvoiceLine


def _make_delivered_invoice(node, client, bread_price, quantity, invoice_date=None):
    invoice = Invoice.objects.create(
        node=node, client=client,
        payment_type=Invoice.PaymentType.CASH,
        status=Invoice.Status.DELIVERED,
        payment_amount=Decimal('0.00'),
        node_origin=node.code,
        invoice_date=invoice_date or date.today(),
    )
    InvoiceLine.objects.create(invoice=invoice, bread_price=bread_price, quantity=quantity)
    invoice.compute_order_total()
    invoice.save(update_fields=['order_total'])
    return invoice


class CarriedCommissionDebtTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.bp = make_bread_price(category='MOYEN', unit_price=500)
        self.client_obj = make_client(self.node, commission_rate=Decimal('0.25'))
        self.direction = make_user(role='DIRECTION', node=None)
        self.api = APIClient()
        self.api.force_authenticate(user=self.direction)

    def _generate(self, month, year):
        resp = self.api.post('/api/commissions/periods/generate/', {
            'node': str(self.node.pk), 'month': month, 'year': year,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        return CommissionPeriod.objects.get(node=self.node, month=month, year=year)

    def test_negative_net_payable_is_carried_to_the_next_period_as_a_deduction(self):
        # Mois 1 : CM brute faible (1 pain à 500 FC x 0.25 = 125 FC) mais une
        # grosse dette retenue (deduction_debt) → net_payable très négatif.
        _make_delivered_invoice(
            self.node, self.client_obj, self.bp, quantity=1, invoice_date=date(2026, 1, 15)
        )  # CM = 125 FC
        period1 = self._generate(month=1, year=2026)

        commission1 = ClientCommission.objects.get(period=period1, client=self.client_obj)
        commission1.deduction_debt = Decimal('10000.00')
        commission1.compute(0.025)
        commission1.save()
        commission1.refresh_from_db()
        self.assertLess(
            commission1.net_payable, Decimal('0'),
            "Le scénario doit produire un net à payer négatif pour tester le report."
        )
        expected_debt_to_carry = -commission1.net_payable

        # Mois 2 : nouvelle facture, nouvelle génération → la dette du mois 1
        # (négative) doit être reprise comme `carried_debt_in` et déduite du
        # net à payer du mois 2, sans jamais être remise à zéro ni réclamée
        # directement au client (aucune facture de remboursement créée ici).
        _make_delivered_invoice(
            self.node, self.client_obj, self.bp, quantity=100, invoice_date=date(2026, 2, 15)
        )  # order 50000, CM = 12500
        period2 = self._generate(month=2, year=2026)
        commission2 = ClientCommission.objects.get(period=period2, client=self.client_obj)

        self.assertEqual(
            commission2.carried_debt_in, expected_debt_to_carry,
            "La dette négative de la période précédente n'a pas été reportée "
            "(carried_debt_in) sur la commission de la période suivante."
        )
        self.assertEqual(
            commission2.net_payable,
            commission2.net_carte - commission2.deduction_social
            - commission2.deduction_prints - commission2.deduction_other
            - commission2.carried_debt_in,
        )

        # Le montant reporté n'a pas disparu de l'historique : la commission
        # du mois 1 garde son net_payable négatif d'origine (jamais remis à 0).
        commission1.refresh_from_db()
        self.assertLess(commission1.net_payable, Decimal('0'))

    def test_no_carry_when_previous_period_net_payable_is_positive(self):
        _make_delivered_invoice(
            self.node, self.client_obj, self.bp, quantity=100, invoice_date=date(2026, 3, 15)
        )
        period1 = self._generate(month=3, year=2026)
        commission1 = ClientCommission.objects.get(period=period1, client=self.client_obj)
        self.assertGreaterEqual(commission1.net_payable, Decimal('0'))

        _make_delivered_invoice(
            self.node, self.client_obj, self.bp, quantity=50, invoice_date=date(2026, 4, 15)
        )
        period2 = self._generate(month=4, year=2026)
        commission2 = ClientCommission.objects.get(period=period2, client=self.client_obj)

        self.assertEqual(commission2.carried_debt_in, Decimal('0.00'))
