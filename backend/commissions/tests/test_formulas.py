"""
Tests des formules de commission (CLAUDE.md §5.3, BUG-012) — valeurs
calculées à la main, résultats Decimal exacts (jamais de float).
"""
from decimal import Decimal

from django.test import TestCase

from core.testing import make_node, make_client
from commissions.models import CommissionPeriod, ClientCommission


def _make_period(node, month=10, year=2026):
    return CommissionPeriod.objects.create(node=node, month=month, year=year)


class CommissionGrossTests(TestCase):
    """CM brute = valeur commande × taux."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.period = _make_period(self.node)

    def test_commission_gross_at_25_percent(self):
        client = make_client(self.node, commission_rate=Decimal('0.25'))
        cc = ClientCommission(period=self.period, client=client, order_value=Decimal('200000.00'), commission_rate=Decimal('0.25'))
        cc.compute()
        self.assertEqual(cc.commission_gross, Decimal('50000.00'))  # 200000 x 0.25

    def test_commission_gross_at_30_percent(self):
        client = make_client(self.node, commission_rate=Decimal('0.30'))
        cc = ClientCommission(period=self.period, client=client, order_value=Decimal('200000.00'), commission_rate=Decimal('0.30'))
        cc.compute()
        self.assertEqual(cc.commission_gross, Decimal('60000.00'))  # 200000 x 0.30

    def test_commission_gross_is_decimal_not_float(self):
        client = make_client(self.node)
        cc = ClientCommission(period=self.period, client=client, order_value=Decimal('333333.33'), commission_rate=Decimal('0.25'))
        cc.compute()
        self.assertIsInstance(cc.commission_gross, Decimal)
        # 333333.33 x 0.25 = 83333.3325 exactement (pas d'arrondi flottant parasite)
        self.assertEqual(cc.commission_gross, Decimal('83333.3325'))


class DeductionAndAnnualBonusTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.period = _make_period(self.node)
        self.client = make_client(self.node, commission_rate=Decimal('0.25'))

    def test_annual_bonus_is_2_5_percent_of_volume_delivered(self):
        cc = ClientCommission(
            period=self.period, client=self.client,
            total_breads=4000, order_value=Decimal('0.00'), commission_rate=Decimal('0.25'),
        )
        cc.compute(annual_bonus_rate=0.025)
        # 4000 x 0.025 = 100 (exact)
        self.assertEqual(cc.annual_bonus, Decimal('100.000'))

    def test_net_payable_with_bonus_incorporated(self):
        """BUG-058 (décision client 2026-10-23) : REMISE (0,1 %) est calculée
        et affichée mais n'est plus déduite du Net à Payer — seule CARTE (1 %)
        l'est, conformément à la formule NET A PAYER réellement observée dans
        les classeurs Excel d'août 2026 (K1/K2/K3)."""
        cc = ClientCommission(
            period=self.period, client=self.client,
            total_breads=4000, order_value=Decimal('200000.00'), commission_rate=Decimal('0.25'),
            annual_bonus_incorporated=True,
        )
        cc.compute(annual_bonus_rate=0.025)
        self.assertEqual(cc.annual_bonus, Decimal('100.000'))
        self.assertEqual(cc.commission_gross, Decimal('50000.00'))
        # NET/ORDI = 50000 - 0 (pas de dette) = 50000
        self.assertEqual(cc.net_ordi, Decimal('50000.00'))
        # CARTE = 1% de 50000 = 500 ; NET/CARTE = 50000 - 500 = 49500
        self.assertEqual(cc.deduction_carte, Decimal('500.00'))
        self.assertEqual(cc.net_carte, Decimal('49500.00'))
        # REMISE(0.1%) = 50 — calculée/affichée, mais NON déduite (BUG-058)
        self.assertEqual(cc.deduction_remise, Decimal('50.00'))
        # net_payable = net_carte - social(0) - prints(0) - other(0) + bonus(100)
        expected = Decimal('49500.00') + Decimal('100.000')
        self.assertEqual(cc.net_payable, expected)

    def test_net_payable_without_bonus_incorporated_excludes_bonus(self):
        cc = ClientCommission(
            period=self.period, client=self.client,
            total_breads=4000, order_value=Decimal('200000.00'), commission_rate=Decimal('0.25'),
            annual_bonus_incorporated=False,
        )
        cc.compute(annual_bonus_rate=0.025)
        self.assertEqual(cc.annual_bonus, Decimal('100.000'))  # calculé mais non incorporé
        expected = Decimal('49500.00')
        self.assertEqual(cc.net_payable, expected)

    def test_total_deductions_sums_debt_social_prints_other_plus_carte(self):
        """CLAUDE.md §5.3 : Total retenues = dette + sociale + imprimés + autre.
        Le modèle réel ajoute aussi CARTE (1%) — mais plus REMISE (0.1%)
        depuis BUG-058 (décision client 2026-10-23, formule Excel réelle
        d'août 2026 : REMISE est calculée/affichée mais jamais déduite)."""
        cc = ClientCommission(
            period=self.period, client=self.client,
            order_value=Decimal('200000.00'), commission_rate=Decimal('0.25'),
            deduction_debt=Decimal('10000.00'), deduction_social=Decimal('3000.00'),
            deduction_prints=Decimal('500.00'), deduction_other=Decimal('1200.00'),
        )
        cc.compute()
        # commission_gross = 50000 ; carte = 500 ; remise = 50 (affichée, non déduite)
        self.assertEqual(cc.commission_gross, Decimal('50000.00'))
        self.assertEqual(cc.deduction_carte, Decimal('500.00'))
        self.assertEqual(cc.deduction_remise, Decimal('50.00'))
        expected_total = Decimal('10000.00') + Decimal('3000.00') + Decimal('500.00') + Decimal('1200.00') + Decimal('500.00')
        self.assertEqual(cc.total_deductions, expected_total)
        self.assertEqual(cc.total_deductions, Decimal('15200.00'))

    def test_net_payable_can_go_negative_when_deductions_exceed_cm(self):
        """Cas d'un net négatif — comportement non spécifié par le cahier des
        charges ni remarque.md pour ce cas précis (cf. docs/qa/QUESTIONS_CLIENT.md
        Q-002, déjà ouverte). L'application ne bloque ni n'affiche d'erreur :
        elle calcule un net_payable négatif tel quel. On documente ce
        comportement actuel sans le qualifier de bug (question client déjà
        suivie séparément)."""
        cc = ClientCommission(
            period=self.period, client=self.client,
            order_value=Decimal('10000.00'), commission_rate=Decimal('0.25'),
            deduction_debt=Decimal('50000.00'),
        )
        cc.compute()
        self.assertLess(cc.net_payable, Decimal('0'))

    def test_manual_adjustment_overrides_computed_net_payable(self):
        cc = ClientCommission(
            period=self.period, client=self.client,
            order_value=Decimal('200000.00'), commission_rate=Decimal('0.25'),
            manuel_adjustment=Decimal('42000.00'), annual_bonus_incorporated=False,
        )
        cc.compute()
        self.assertEqual(cc.net_payable, Decimal('42000.00'))
