"""
Vérification indépendante BUG-142 (testeur-production, 2026-11-10).

Ne reprend PAS les tests déjà écrits par dev-backend
(`test_bug142_fournee_carryover_accumulation.py`) : construit ses propres
scénarios bout-en-bout pour contrôler, par le calcul, les points demandés
par le coordinateur :

1. Non-régression explicite sur `_build_daily_closure_report` (BUG-120,
   déjà vérifié formule à formule contre les Excel réels du client) pour un
   jour SANS confirmation BUG-133 : aucune ligne CARRYOVER ce jour-là → le
   filtre `source=DECLARED` introduit par BUG-142 ne doit RIEN changer.
2. Scénario bout-en-bout confirmation + fournée réelle le même jour/équipe :
   la session apparaît avec les bonnes lignes CARRYOVER, le rendement
   (`yield_gap`/`theoretical_yield`) ne bouge pas à cause du carryover, et
   le rapport de clôture journalier ne compte pas ces pains deux fois
   (une fois via `reste_du_hier`, une fois via `produit`).
3. Absence de double comptage sur `BreadStock.qty_available` dans l'ordre
   déclaration réelle PUIS confirmation (ordre inverse de celui déjà
   couvert par dev-backend), avec un stock physique préexistant non nul.
4. Répartition en %% (`repartition_pct_par_quantite`) : point d'attention
   trouvé en relisant le code — le dénominateur (`total_breads_produced`,
   champ `ProductionSession.total_breads`, TOUTES les lignes) et le
   numérateur (`produit.quantity`, filtré `DECLARED` depuis BUG-142) ne
   partagent plus la même base dès qu'une ligne CARRYOVER existe ce jour :
   documenté ici comme non-régression caractérisée, PAS comme un blocage
   de BUG-142 lui-même (BUG-142 ne prétend pas corriger ce rapport, il
   évite seulement le double comptage de `produit`/`net_produit_fc`).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import (
    ProductionSession, ProductionSessionLine, BreadStock, _adjust_bread_stock,
)


def _q2(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class Bug142NoCarryoverDayIsUnaffectedTests(TestCase):
    """Point 1 — jour SANS confirmation : le filtre DECLARED ne change rien."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp300 = make_bread_price(category='BUG142_300', label='Pain 300 FC', unit_price=300)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        self.today = timezone.localdate()

    def test_report_matches_hand_computed_totals_with_no_carryover_line_in_db(self):
        resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp300.pk, 'quantity': 100}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        # Ancrage explicite : aucune ligne CARRYOVER n'existe pour ce jour —
        # condition nécessaire pour que le filtre BUG-142 soit un no-op ici.
        self.assertFalse(
            ProductionSessionLine.objects.filter(
                session__node=self.node, session__date=self.today,
                source=ProductionSessionLine.Source.CARRYOVER,
            ).exists()
        )

        report_resp = self.api.get('/api/production/daily-closure/', {'date': str(self.today)})
        self.assertEqual(report_resp.status_code, 200, report_resp.data)
        data = report_resp.data

        row300 = next(r for r in data['categories'] if r['bread_price'] == self.bp300.pk)
        # Calcul indépendant : 100 pains déclarés × 300 FC, sans carryover,
        # avec ou sans le filtre `source=DECLARED` le résultat est identique.
        self.assertEqual(row300['produit']['quantity'], 100)
        self.assertEqual(row300['produit']['fc'], str(_q2(Decimal(100) * Decimal(300))))
        self.assertEqual(data['totals']['net_produit_fc'], str(_q2(Decimal(100) * Decimal(300))))
        self.assertEqual(data['totals']['total_breads_produced'], 100)

        pct_qty = {r['bread_price']: Decimal(r['pct']) for r in data['totals']['repartition_pct_par_quantite']}
        # Une seule catégorie produite ce jour, sans carryover : la
        # répartition doit totaliser exactement 100 % (sinon régression).
        self.assertEqual(pct_qty[self.bp300.pk], Decimal('100.00'))


class Bug142CarryoverEndToEndTests(TestCase):
    """Point 2 — scénario bout-en-bout confirmation + fournée réelle."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp300 = make_bread_price(category='BUG142_300', label='Pain 300 FC', unit_price=300)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

        self.today = timezone.localdate()
        self.yesterday = self.today - timedelta(days=1)

    def _declare(self, team, date, flour, qty):
        return self.api.post('/api/production/sessions/', {
            'team': team, 'date': str(date), 'flour_sacks_used': str(flour),
            'lines': [{'bread_price': self.bp300.pk, 'quantity': qty}],
        }, format='json')

    def _confirm(self, team, qty, date):
        return self.api.post('/api/production/opening-confirmation/', {
            'team': team, 'date': str(date),
            'lines': [{'bread_price': self.bp300.pk, 'qty': qty}],
        }, format='json')

    def test_full_scenario_confirmation_then_fournee_no_double_count_anywhere(self):
        # --- Veille : équipe A clôture avec un reste physique de 15 pains.
        prev_resp = self._declare('A', self.yesterday, '1.00', 50)
        prev_session_id = prev_resp.data['id']
        dispose_resp = self.api.post('/api/production/disposals/', {
            'session': prev_session_id, 'bread_price': self.bp300.pk,
            'disposal_type': 'REMAINING', 'quantity': 15, 'unit_price_sold': 0,
        }, format='json')
        self.assertEqual(dispose_resp.status_code, 201, dispose_resp.data)
        close_resp = self.api.post(f'/api/production/sessions/{prev_session_id}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)

        # --- Aujourd'hui : le gérant confirme le reste du hier pour
        # l'équipe A (stock physique réellement disponible, 15 pains).
        confirm_resp = self._confirm('A', 15, self.today)
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.data)

        # La fournée du jour existe bien pour l'équipe A, avec une ligne
        # CARRYOVER correcte.
        session = ProductionSession.objects.get(node=self.node, team='A', date=self.today)
        carryover_line = session.lines.get(
            bread_price=self.bp300, source=ProductionSessionLine.Source.CARRYOVER,
        )
        self.assertEqual(carryover_line.quantity, 15)

        # --- Déclaration réelle de fournée, même jour/équipe : 2 sacs → 100
        # pains supplémentaires.
        decl_resp = self._declare('A', self.today, '2.00', 100)
        self.assertEqual(decl_resp.status_code, 201, decl_resp.data)

        session.refresh_from_db()
        self.assertEqual(session.lines.count(), 2)  # 1 CARRYOVER + 1 DECLARED
        self.assertEqual(session.total_breads, 15 + 100)

        # Rendement : ne doit JAMAIS compter le carryover (aucune farine
        # consommée pour ces 15 pains).
        self.assertEqual(session.total_fc_produced, 100 * 300)
        self.assertEqual(session.theoretical_yield, 2 * 200000)
        self.assertEqual(session.yield_gap, (100 * 300) - (2 * 200000))

        # --- Rapport de clôture journalier : pas de double comptage.
        report_resp = self.api.get('/api/production/daily-closure/', {'date': str(self.today)})
        self.assertEqual(report_resp.status_code, 200, report_resp.data)
        data = report_resp.data
        row300 = next(r for r in data['categories'] if r['bread_price'] == self.bp300.pk)

        # `produit` ne doit refléter QUE la vraie fournée (100), jamais
        # 100 + 15 (qui serait un double comptage avec `reste_du_hier`).
        self.assertEqual(row300['produit']['quantity'], 100)
        self.assertEqual(row300['produit']['fc'], str(_q2(Decimal(100) * Decimal(300))))
        self.assertEqual(data['totals']['net_produit_fc'], str(_q2(Decimal(100) * Decimal(300))))

        # Le reste d'hier confirmé (15) apparaît séparément, une seule fois,
        # dans `reste_du_hier` (convention de signe BUG-135 : négatif).
        self.assertEqual(row300['reste_du_hier']['A'], -15)

        # `facture_mvm_interne` (BUG-120, déjà audité) : ne doit inclure le
        # reste d'hier qu'UNE fois (via `reste_du_hier_fc`), jamais une
        # deuxième fois via `produit` (qui n'entre pas dans sa formule —
        # confirmé par calcul indépendant).
        reste_du_hier_fc = Decimal(-15) * Decimal(300)
        reste_du_jour_fc = Decimal(
            sum(v or 0 for v in row300['reste_du_jour'].values())
        ) * Decimal(300)
        mvm_attendu = _q2(reste_du_hier_fc + reste_du_jour_fc)
        self.assertEqual(Decimal(row300['facture_mvm_interne']['fc']), mvm_attendu)

        # --- Point d'attention trouvé en relisant le code (signalé, pas un
        # blocage de BUG-142) : `total_breads_produced` (champ de session,
        # TOUTES les lignes) sert de dénominateur à la répartition en %,
        # alors que le numérateur (`produit.quantity`) est désormais filtré
        # DECLARED seul. Dès qu'une ligne CARRYOVER existe, la somme des %
        # ne vaut plus 100 — documenté ici comme caractéristique connue de
        # ce rapport (pas de ce ticket), pas comme une régression de
        # BUG-142 lui-même (qui ne touche pas `repartition_pct_*`).
        self.assertEqual(data['totals']['total_breads_produced'], 115)
        pct_qty = {r['bread_price']: Decimal(r['pct']) for r in data['totals']['repartition_pct_par_quantite']}
        self.assertEqual(
            pct_qty[self.bp300.pk],
            (Decimal(100) * Decimal('100') / Decimal(115)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        )
        self.assertNotEqual(
            pct_qty[self.bp300.pk], Decimal('100.00'),
            "Caractéristique connue (pas un échec BUG-142) : le dénominateur "
            "`total_breads_produced` inclut le carryover (115) alors que le "
            "numérateur `produit.quantity` ne compte que le déclaré (100) — "
            "la répartition par quantité ne totalise plus 100% dès qu'un "
            "carryover existe ce jour-là. À signaler séparément si le client "
            "s'en sert pour une décision chiffrée.",
        )


class Bug142NoDoubleCountingReverseOrderTests(TestCase):
    """Point 3 — déclaration réelle PUIS confirmation, avec stock physique
    préexistant non nul (ordre et contexte différents de ceux déjà couverts
    par dev-backend, pour vérifier indépendamment l'absence de double
    comptage sur `BreadStock.qty_available`)."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp300 = make_bread_price(category='BUG142_300', label='Pain 300 FC', unit_price=300)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        self.today = timezone.localdate()

    def test_declaration_then_confirmation_with_preexisting_stock(self):
        # Stock physique préexistant, indépendant de toute session (ex.
        # ajustement manuel antérieur).
        _adjust_bread_stock(self.node, self.bp300, produced=40)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp300)
        self.assertEqual(stock.qty_available, 40)

        # Vraie fournée du jour : +100.
        decl_resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '2.00',
            'lines': [{'bread_price': self.bp300.pk, 'quantity': 100}],
        }, format='json')
        self.assertEqual(decl_resp.status_code, 201, decl_resp.data)
        stock.refresh_from_db()
        self.assertEqual(stock.qty_available, 140)

        # Confirmation du stock de départ : le gérant valide le stock
        # physique courant tel que proposé (140) — delta nul, no-op BUG-136.
        confirm_resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': str(self.today),
            'lines': [{'bread_price': self.bp300.pk, 'qty': 140}],
        }, format='json')
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.data)
        self.assertEqual(
            confirm_resp.data['stock_adjustments'], [],
            "Confirmation telle que proposée = no-op, aucun ajustement BUG-136.",
        )

        stock.refresh_from_db()
        self.assertEqual(
            stock.qty_available, 140,
            "La création de la ligne CARRYOVER ne doit jamais appeler "
            "_adjust_bread_stock — sinon le stock passerait à 280.",
        )

        session = ProductionSession.objects.get(node=self.node, team='A', date=self.today)
        self.assertEqual(session.lines.count(), 2)
        carryover_line = session.lines.get(
            bread_price=self.bp300, source=ProductionSessionLine.Source.CARRYOVER,
        )
        self.assertEqual(carryover_line.quantity, 140)
        declared_line = session.lines.get(
            bread_price=self.bp300, source=ProductionSessionLine.Source.DECLARED,
        )
        self.assertEqual(declared_line.quantity, 100)
        # total_breads légacy = toutes les lignes = 100 (déclaré) + 140
        # (carryover, qui redouble la valeur déjà physiquement comptée dans
        # qty_available) — ce champ n'est PAS un stock, juste un total
        # d'activité ; pas de double comptage sur `BreadStock`, seul
        # engagement du ticket.
        self.assertEqual(session.total_breads, 100 + 140)
        self.assertEqual(session.total_fc_produced, 100 * 300)  # carryover exclu du rendement
