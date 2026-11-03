"""
Vérification indépendante de BUG-122 (Q-002) — testeur-clients-commissions,
2026-11-02. Scénarios réels (pas une relecture) demandés par le coordinateur :

1. Le report fonctionne sur plusieurs périodes consécutives (chaîne de 3
   périodes), jamais remis à zéro, jamais réclamé immédiatement.
2. Un `manuel_adjustment` DIRECTION prévaut et n'est pas recombiné avec le
   report dans la période où il s'applique — et le report calculé pour la
   période SUIVANTE se base bien sur le `net_payable` effectif (post
   ajustement manuel), pas sur la formule normale écrasée.
3. Un trou de génération (période intermédiaire jamais générée pour le
   client) n'empêche pas le report de traverser ce trou.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from core.testing import make_node, make_user, make_client, make_bread_price
from commissions.models import CommissionPeriod, ClientCommission
from sales.models import Invoice, InvoiceLine


def _make_delivered_invoice(node, client, bread_price, quantity, invoice_date):
    invoice = Invoice.objects.create(
        node=node, client=client,
        payment_type=Invoice.PaymentType.CASH,
        status=Invoice.Status.DELIVERED,
        payment_amount=Decimal('0.00'),
        node_origin=node.code,
        invoice_date=invoice_date,
    )
    InvoiceLine.objects.create(invoice=invoice, bread_price=bread_price, quantity=quantity)
    invoice.compute_order_total()
    invoice.save(update_fields=['order_total'])
    return invoice


class CarriedDebtMultiPeriodChainTests(TestCase):
    """Scénario 1 : chaîne de 3 périodes consécutives."""

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

    def test_debt_carries_across_three_consecutive_negative_periods(self):
        config_bonus_rate = 0.025

        # Période 1 : CM faible (1 pain à 500 FC x 0.25 = 125 FC), grosse
        # dette retenue → net très négatif.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 1, date(2026, 1, 10))
        period1 = self._generate(1, 2026)
        c1 = ClientCommission.objects.get(period=period1, client=self.client_obj)
        c1.deduction_debt = Decimal('20000.00')
        c1.compute(config_bonus_rate)
        c1.save()
        c1.refresh_from_db()
        self.assertEqual(c1.carried_debt_in, Decimal('0.00'))
        self.assertLess(c1.net_payable, Decimal('0'))
        debt_after_1 = -c1.net_payable

        # Période 2 : CM encore faible (1 pain), pas de nouvelle dette
        # manuelle ajoutée — le seul passif vient du report de la période 1.
        # Le résultat doit rester négatif (CM 125 FC < dette reportée),
        # donc la chaîne continue de s'alourdir.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 1, date(2026, 2, 10))
        period2 = self._generate(2, 2026)
        c2 = ClientCommission.objects.get(period=period2, client=self.client_obj)
        self.assertEqual(c2.carried_debt_in, debt_after_1)
        self.assertEqual(
            c2.net_payable,
            c2.net_carte - c2.deduction_social - c2.deduction_prints
            - c2.deduction_other - c2.carried_debt_in,
        )
        self.assertLess(c2.net_payable, Decimal('0'))
        debt_after_2 = -c2.net_payable
        # La dette n'a pas été simplement recopiée : elle s'est accrue du
        # déficit propre à la période 2 (report jamais soldé en un coup).
        self.assertGreater(debt_after_2, debt_after_1)

        # Période 3 : grosse commande cette fois → la CM doit éponger tout
        # le passif cumulé des 2 périodes précédentes et redevenir positive.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 1000, date(2026, 3, 10))
        period3 = self._generate(3, 2026)
        c3 = ClientCommission.objects.get(period=period3, client=self.client_obj)
        self.assertEqual(c3.carried_debt_in, debt_after_2)
        self.assertEqual(
            c3.net_payable,
            c3.net_carte - c3.deduction_social - c3.deduction_prints
            - c3.deduction_other - c3.carried_debt_in,
        )
        self.assertGreater(c3.net_payable, Decimal('0'))

        # Les montants des périodes 1 et 2 restent inchangés dans l'historique
        # (jamais remis à zéro rétroactivement).
        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertLess(c1.net_payable, Decimal('0'))
        self.assertLess(c2.net_payable, Decimal('0'))

        # Période 4, sans aucun passif restant : carried_debt_in doit
        # retomber à 0 puisque period3.net_payable est désormais positif.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 10, date(2026, 4, 10))
        period4 = self._generate(4, 2026)
        c4 = ClientCommission.objects.get(period=period4, client=self.client_obj)
        self.assertEqual(c4.carried_debt_in, Decimal('0.00'))


class ManualAdjustmentOverridesCarryTests(TestCase):
    """Scénario 2 : manuel_adjustment DIRECTION prévaut et n'est pas recombiné."""

    def setUp(self):
        self.node = make_node(code='K2', name='K2 - COQ')
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

    def test_manual_override_is_not_recombined_with_carry_and_feeds_next_period(self):
        # Période 1 : net très négatif.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 1, date(2026, 1, 10))
        period1 = self._generate(1, 2026)
        c1 = ClientCommission.objects.get(period=period1, client=self.client_obj)
        c1.deduction_debt = Decimal('15000.00')
        c1.compute(0.025)
        c1.save()
        c1.refresh_from_db()
        self.assertLess(c1.net_payable, Decimal('0'))

        # Période 2 : report automatique confirmé avant tout ajustement manuel.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 2, date(2026, 2, 10))
        period2 = self._generate(2, 2026)
        c2 = ClientCommission.objects.get(period=period2, client=self.client_obj)
        self.assertGreater(c2.carried_debt_in, Decimal('0.00'))
        self.assertEqual(
            c2.net_payable,
            c2.net_carte - c2.deduction_social - c2.deduction_prints
            - c2.deduction_other - c2.carried_debt_in,
        )

        # La DIRECTION fixe un ajustement manuel positif sur la période 2 —
        # il doit écraser entièrement la formule normale : net_payable =
        # manuel_adjustment + bonus incorporé, SANS soustraire carried_debt_in
        # une seconde fois.
        resp = self.api.patch(
            f'/api/commissions/commissions/{c2.id}/set_manuel/',
            {'manuel_adjustment': '5000.00', 'manuel_notes': 'Décision DIRECTION test'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        c2.refresh_from_db()
        expected_bonus = c2.annual_bonus if c2.annual_bonus_incorporated else Decimal('0')
        self.assertEqual(c2.net_payable, Decimal('5000.00') + expected_bonus)
        # carried_debt_in reste visible/stocké pour information, mais n'est
        # plus soustrait de net_payable.
        self.assertGreater(c2.carried_debt_in, Decimal('0.00'))

        # Période 3 : le report doit se baser sur le net_payable EFFECTIF de
        # la période 2 (5 000 FC, positif après ajustement manuel) — donc
        # AUCUN report, même si la dette "naturelle" avant ajustement était
        # négative. L'ajustement manuel n'est pas recombiné après coup.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 2, date(2026, 3, 10))
        period3 = self._generate(3, 2026)
        c3 = ClientCommission.objects.get(period=period3, client=self.client_obj)
        self.assertEqual(c3.carried_debt_in, Decimal('0.00'))


class CarriedDebtSurvivesGenerationGapTests(TestCase):
    """Scénario 3 : trou de génération (période intermédiaire non générée)."""

    def setUp(self):
        self.node = make_node(code='K3', name='K3 - ATHENEE')
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

    def test_gap_period_without_invoice_does_not_break_the_carry(self):
        # Période 1 (janvier) : net négatif.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 1, date(2026, 1, 10))
        period1 = self._generate(1, 2026)
        c1 = ClientCommission.objects.get(period=period1, client=self.client_obj)
        c1.deduction_debt = Decimal('12000.00')
        c1.compute(0.025)
        c1.save()
        c1.refresh_from_db()
        self.assertLess(c1.net_payable, Decimal('0'))
        debt_after_1 = -c1.net_payable

        # Février : aucune facture pour ce client → aucune ClientCommission
        # n'est générée pour lui sur cette période (trou de génération).
        # On génère tout de même la période (d'autres clients pourraient
        # avoir des factures), mais sans impliquer notre client.
        other_client = make_client(self.node, commission_rate=Decimal('0.25'), first_name='Autre')
        _make_delivered_invoice(self.node, other_client, self.bp, 3, date(2026, 2, 10))
        self._generate(2, 2026)
        self.assertFalse(
            ClientCommission.objects.filter(
                period__node=self.node, period__month=2, period__year=2026,
                client=self.client_obj,
            ).exists(),
            "Aucune commission ne devrait exister pour ce client en février (pas de facture).",
        )

        # Mars : nouvelle facture pour notre client → la dette de janvier
        # doit traverser le trou de février et être reportée sur mars.
        _make_delivered_invoice(self.node, self.client_obj, self.bp, 200, date(2026, 3, 10))
        period3 = self._generate(3, 2026)
        c3 = ClientCommission.objects.get(period=period3, client=self.client_obj)
        self.assertEqual(c3.carried_debt_in, debt_after_1)
        self.assertEqual(
            c3.net_payable,
            c3.net_carte - c3.deduction_social - c3.deduction_prints
            - c3.deduction_other - c3.carried_debt_in,
        )
