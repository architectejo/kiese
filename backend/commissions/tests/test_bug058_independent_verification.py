"""
Vérification INDÉPENDANTE de BUG-058 par testeur-clients-commissions (2026-10-23).

Objectif : recalculer, séparément des tests déjà écrits par
dev-backend/auditeur-comptable, le Net à Payer attendu d'après la formule
Excel réelle (K1, août 2026 — cf. docs/qa/REGISTRE_BUGS.md, fiche BUG-058 /
rapport dev-backend-phase4-residuel2-2026-10-23.md), et le comparer à
`ClientCommission.compute()` après correction.

Montants fictifs (aucune donnée réelle de `data_kiese/` reproduite), mais
construits pour reproduire l'agrégat de CM cumulé d'août 2026 cité pour
TABORA K1 dans le rapport d'audit (~6 557 500 FC de CM cumulé).

Formule Excel réelle (lue directement dans les 3 classeurs, cf. ticket) :
    NET A PAYER = CM - BP_ACTUEL(dette) - SOCIAL - CARTE_réelle - RETENUE
    avec CARTE_réelle = 0 sur les 3 classeurs pour août 2026 (colonne vide),
    et REMISE jamais soustraite (calculée/affichée seulement).

Décision client du 2026-10-23 (relayée par le coordinateur) : seule REMISE
sort de la déduction automatique de l'application ; CARTE reste déduite par
l'application (gap résiduel connu et accepté, documenté ci-dessous).
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.testing import make_node, make_client
from commissions.models import CommissionPeriod, ClientCommission


class Bug058IndependentVerificationTests(TestCase):
    def setUp(self):
        self.node = make_node(code='ZVERI', name='Zone Vérification Indépendante')
        self.client = make_client(self.node, commission_rate=Decimal('0.25'))
        self.period = CommissionPeriod.objects.create(
            node=self.node, month=timezone.now().month, year=timezone.now().year,
        )

    def test_annual_bonus_untouched_by_bug058_fix(self):
        """La remise annuelle de fidélité (mécanisme distinct, CLAUDE.md
        §5.1/§5.3) ne doit pas avoir été modifiée par la correction de
        BUG-058 : toujours 0,025 x volume livré, et toujours incorporable
        ou non via `annual_bonus_incorporated`, indépendamment de REMISE
        (0,1% du CM, champ `deduction_remise`, sans lien avec `annual_bonus`)."""
        cc = ClientCommission(
            period=self.period, client=self.client,
            total_breads=8000, order_value=Decimal('100000.00'), commission_rate=Decimal('0.25'),
            annual_bonus_incorporated=True,
        )
        cc.compute(annual_bonus_rate=0.025)
        # 8000 x 0.025 = 200, mécanisme totalement indépendant de deduction_remise
        self.assertEqual(cc.annual_bonus, Decimal('200.000'))
        self.assertNotEqual(cc.annual_bonus, cc.deduction_remise)
        # net_payable doit inclure annual_bonus (incorporé) mais jamais deduction_remise
        cm = Decimal('100000.00') * Decimal('0.25')  # 25000
        carte = round(cm * Decimal('0.01'), 2)  # 250.00
        expected_net = (cm - carte) + cc.annual_bonus
        self.assertEqual(cc.net_payable, expected_net)

    def test_k1_august_2026_aggregate_reproduction_independent_calc(self):
        """
        Reproduit, avec un montant agrégé fictif calé sur l'ordre de grandeur
        cité par l'auditeur-comptable pour TABORA K1 (CM cumulé août 2026
        ~6 557 500 FC — agrégat seul, aucun nom/montant individuel de client
        réel), le calcul du Net à Payer, recalculé ici à la main et comparé
        indépendamment à `compute()`.
        """
        # Choisi pour obtenir commission_gross == 6 557 500.00 exactement :
        order_value = Decimal('26230000.00')
        rate = Decimal('0.25')
        cc = ClientCommission(
            period=self.period, client=self.client,
            order_value=order_value, commission_rate=rate,
        )
        cc.compute()

        cm = order_value * rate
        self.assertEqual(cm, Decimal('6557500.00'))
        self.assertEqual(cc.commission_gross, cm)

        # --- Calcul à la main, indépendant, formule Excel réelle K1 août 2026 ---
        # NET A PAYER réel = CM - dette(0 ici) - social(0) - CARTE_réelle(0,
        # colonne vide sur les 3 classeurs vérifiés) - retenue(0) = CM.
        real_net_a_payer = cm
        self.assertEqual(real_net_a_payer, Decimal('6557500.00'))

        # --- Calcul à la main, indépendant, de ce que l'app produit désormais ---
        carte_app = round(cm * Decimal('0.01'), 2)
        remise_app = round(cm * Decimal('0.001'), 2)
        self.assertEqual(carte_app, Decimal('65575.00'))
        self.assertEqual(remise_app, Decimal('6557.50'))
        expected_app_net = cm - carte_app  # pas de dette/social/prints/other ici
        self.assertEqual(cc.net_payable, expected_app_net)
        self.assertEqual(cc.net_payable, Decimal('6491925.00'))

        # --- Écart résiduel documenté ---
        ecart = real_net_a_payer - cc.net_payable
        # L'écart résiduel ne vient plus QUE de CARTE (1% du CM) : la
        # correction BUG-058 a bien éliminé la contribution de REMISE
        # (0,1% du CM) à l'écart, qui valait avant correction CARTE+REMISE
        # = 1,1% du CM (~72 133 FC sur cet agrégat ; ici 72 132,50 FC exact
        # avec ce montant rond). Après correction : 1% du CM = 65 575 FC.
        self.assertEqual(ecart, carte_app)
        self.assertEqual(ecart, Decimal('65575.00'))
        # REMISE n'intervient plus du tout dans net_payable, bien qu'elle
        # soit toujours calculée/affichée (deduction_remise non nul) :
        self.assertNotEqual(cc.deduction_remise, Decimal('0.00'))
        self.assertEqual(
            cc.net_payable + ecart + remise_app,
            real_net_a_payer + remise_app,  # identité triviale, juste pour
            # documenter que remise_app n'entre dans aucun des deux membres
            # de l'écart ci-dessus — elle est bien hors formule des deux côtés
            # à l'exception de son propre affichage.
        )

        # Gap résiduu CARTE reste connu et accepté par décision explicite du
        # client du 2026-10-23 : seule REMISE est retirée de la déduction
        # automatique, CARTE est conservée. Documenté ici, non qualifié de
        # bug (cf. ticket BUG-058, statut CORRIGÉ).
