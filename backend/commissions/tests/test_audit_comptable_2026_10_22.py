"""
Recoupement auditeur-comptable (2026-10-22) avec les fiches de répartition
CM réelles d'août 2026 (K1, K2, K3 — `data_kiese/daja_analysé/*.xlsx`,
onglets "DOC 2 REPARTITION" / "clients cite").

**Aucune donnée réelle n'est reproduite ici** (noms de clients, montants
individuels) : les montants ci-dessous sont fictifs, choisis pour isoler
la formule en cause. Le constat qui suit est établi en lisant directement
les *formules Excel* (pas seulement les valeurs) des 3 classeurs cités,
qui sont strictement identiques entre boulangeries :

    NET A PAYER = CM − BP_ACTUEL(dette) − SOCIAL − CARTE − RETENUE

La colonne "REMISE" (= COMMANDE × 0,25 % = CM × 1 %, selon le taux de
commission 25 % en vigueur) est bien calculée dans le classeur, mais
**n'apparaît jamais dans la formule du NET A PAYER** — elle n'est donc
jamais déduite dans la réalité de gestion d'août 2026, sur les 3
boulangeries vérifiées (K1 : ~198 clients-mois, K2, K3). La colonne
"CARTE" (1 % du CM), elle, est systématiquement vide/à 0 sur les 3
classeurs pour cette période (aucune carte revendeur facturée).

`ClientCommission.compute()` (backend/commissions/models.py), au contraire,
déduit **systématiquement** `deduction_carte` (CM × 1 %) ET
`deduction_remise` (CM × 0,1 %) du `net_payable` — une charge que la
pratique réelle de gestion ne prélève pas. Voir BUG-058.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.testing import make_node, make_client
from commissions.models import CommissionPeriod, ClientCommission


class RemiseCarteNotDeductedInRealLedgerTests(TestCase):
    """
    Reproduit, avec des montants fictifs, la formule réellement observée
    dans les classeurs de répartition CM d'août 2026 (K1/K2/K3), et la
    compare à `ClientCommission.compute()`.
    """

    def setUp(self):
        self.node = make_node(code='ZAUD1', name='Zone Audit Test')
        self.client = make_client(self.node, commission_rate=Decimal('0.25'), current_debt=Decimal('95000.00'))
        self.period = CommissionPeriod.objects.create(node=self.node, month=timezone.now().month, year=timezone.now().year)

    @staticmethod
    def _real_ledger_net_a_payer(order_value: Decimal, debt: Decimal, rate: Decimal,
                                  social: Decimal = Decimal('0'), retenue: Decimal = Decimal('0')) -> Decimal:
        """
        Reproduit fidèlement la formule Excel observée (CM - BP - SOCIAL - CARTE - RETENUE),
        avec CARTE = 0 dans la pratique réelle d'août 2026 (colonne systématiquement vide
        sur les 3 boulangeries vérifiées) et REMISE absente de la formule.
        """
        cm = order_value * rate
        carte_reellement_appliquee = Decimal('0')  # colonne CARTE toujours vide dans les classeurs vérifiés
        return cm - debt - social - carte_reellement_appliquee - retenue

    def test_app_net_payable_no_longer_deducts_remise_after_bug058_fix(self):
        """
        BUG-058 — décision client du 2026-10-23 (M. NDUNGA NSAYI PIERRE) :
        REMISE (0,1 % du CM) ne doit plus être déduite automatiquement du Net
        à Payer, conformément à la formule NET A PAYER réellement observée
        dans les classeurs Excel K1/K2/K3 d'août 2026. CARTE (1 % du CM)
        reste déduite (décision explicite : seule REMISE est retirée de la
        déduction automatique).

        Avant la correction, l'écart entre le grand livre réel et
        `ClientCommission.compute()` valait CARTE + REMISE = 1,1 % du CM.
        Après la correction, l'écart résiduel ne vient plus que de CARTE
        (1 % du CM) — gap connu et volontairement conservé (CARTE reste
        déductible par décision du client), REMISE n'y contribue plus.
        """
        order_value = Decimal('1138000.00')  # grandeur réaliste (cf. agrégats du rapport d'audit)
        cc = ClientCommission(
            period=self.period, client=self.client,
            order_value=order_value, commission_rate=Decimal('0.25'),
            deduction_debt=self.client.current_debt,  # BP_ACTUEL réellement déduite (dette du client)
        )
        cc.compute()

        real_net = self._real_ledger_net_a_payer(order_value, debt=self.client.current_debt, rate=Decimal('0.25'))
        cm = order_value * Decimal('0.25')

        # Le grand livre réel (K1/K2/K3, août 2026) ne déduit ni CARTE ni REMISE :
        # NET A PAYER réel = CM - dette = 284 500 - 95 000 = 189 500.
        self.assertEqual(real_net, Decimal('189500.00'))

        # REMISE est désormais calculée/affichée mais plus déduite : l'écart
        # restant entre le grand livre réel et l'application ne vient plus
        # que de CARTE (1 % du CM), plus de REMISE (0,1 % du CM).
        ecart = real_net - cc.net_payable
        self.assertEqual(ecart, cc.deduction_carte)
        self.assertEqual(ecart, cm * Decimal('0.01'))
        self.assertLess(cc.net_payable, real_net)
