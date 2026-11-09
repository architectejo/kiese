"""
BUG-133 (docs/qa/REGISTRE_BUGS.md ; demande client reformulée par le
coordinateur, suite de remarque.md l.396 / BUG-130/131) : boîte modale
« stock de départ » — à sa première connexion de la journée (et tant que la
confirmation n'existe pas, à chaque changement de page du dashboard côté
client), le gérant doit voir le stock physique actuellement disponible par
catégorie de pain (`BreadStock.qty_available`), pouvoir le modifier ou le
valider, et cette validation devient la valeur officielle de « RESTE DU
HIER » pour démarrer la journée dans le rapport de clôture (BUG-120).

Couvre :
  - GET propose `qty_available` (déjà net des ventes, voir sales/views.py
    `_adjust_bread_stock(..., sent=...)`) et signale l'absence de
    confirmation pour chaque équipe.
  - POST valide tel quel ou modifié ; idempotent (resoumission remplace).
  - La confirmation devient prioritaire sur `DailyBreadStockSnapshot.
    reste_du_hier()` dans `_build_daily_closure_report` (BUG-120) pour le
    jour/l'équipe confirmés, SANS jamais modifier `DailyBreadStockSnapshot`
    ni affecter les jours/équipes non confirmés (rétro-compatibilité).
  - Permissions : un GERANT non-HQ ne peut jamais forger `node`, même motif
    que BUG-022/025/056.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Node
from core.testing import make_node, make_user, make_bread_price
from production.models import (
    ProductionSession, BreadStock, DailyBreadStockSnapshot,
    DailyOpeningConfirmation, DailyOpeningConfirmationLine,
)


class DailyOpeningConfirmationTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.other_node = make_node()
        self.gerant = make_user(role='GERANT', node=self.node)
        self.other_gerant = make_user(role='GERANT', node=self.other_node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.bp1000 = make_bread_price(category='GRAND', label='Pain 1000 FC', unit_price=1000)

        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _produce(self, qty, bread_price, node=None):
        """Crée directement du stock physique disponible (production sans
        passer par une session, pour isoler le test de la mécanique BUG-118)."""
        from production.models import _adjust_bread_stock
        _adjust_bread_stock(node or self.node, bread_price, produced=qty)

    # ------------------------------------------------------------------
    # GET — proposition et détection de « déjà confirmé »
    # ------------------------------------------------------------------

    def test_get_proposes_current_available_stock_per_category(self):
        """`qty_proposed` = `BreadStock.qty_available` courant, net des
        ventes déjà déduites (confirmé par construction : ce test crée le
        stock directement via `_adjust_bread_stock`, le même mécanisme que
        `sales/views.py` utilise pour décrémenter à la livraison)."""
        self._produce(120, self.bp500)
        self._produce(40, self.bp1000)

        resp = self.api.get(f'/api/production/opening-confirmation/?date=2026-11-09')
        self.assertEqual(resp.status_code, 200, resp.data)
        by_bp = {row['bread_price']: row['qty_proposed'] for row in resp.data['categories']}
        self.assertEqual(by_bp[self.bp500.pk], 120)
        self.assertEqual(by_bp[self.bp1000.pk], 40)

    def test_get_reflects_sales_deduction_in_proposed_stock(self):
        """Une vente confirmée (sortie de stock) doit réduire `qty_proposed`
        — preuve que la proposition est bien le stock NET des ventes."""
        from production.models import _adjust_bread_stock
        self._produce(100, self.bp500)
        _adjust_bread_stock(self.node, self.bp500, sent=30)  # vente livrée

        resp = self.api.get('/api/production/opening-confirmation/?date=2026-11-09')
        by_bp = {row['bread_price']: row['qty_proposed'] for row in resp.data['categories']}
        self.assertEqual(by_bp[self.bp500.pk], 70)

    def test_get_reports_not_confirmed_for_both_teams_by_default(self):
        resp = self.api.get('/api/production/opening-confirmation/?date=2026-11-09')
        self.assertFalse(resp.data['teams']['A']['confirmed'])
        self.assertFalse(resp.data['teams']['B']['confirmed'])

    def test_get_defaults_to_today_when_date_omitted(self):
        from django.utils import timezone
        resp = self.api.get('/api/production/opening-confirmation/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['date'], str(timezone.localdate()))

    def test_get_invalid_date_returns_400(self):
        resp = self.api.get('/api/production/opening-confirmation/?date=not-a-date')
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    # POST — confirmation (validation telle que proposée, ou modifiée)
    # ------------------------------------------------------------------

    def test_post_confirms_proposed_values_as_is(self):
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 120}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        confirmation = DailyOpeningConfirmation.objects.get(
            node=self.node, team='A', date='2026-11-09',
        )
        self.assertEqual(confirmation.confirmed_by, self.gerant)
        line = DailyOpeningConfirmationLine.objects.get(confirmation=confirmation, bread_price=self.bp500)
        self.assertEqual(line.qty_confirmed, 120)

    def test_post_confirms_modified_value_not_the_proposed_one(self):
        """Le gérant peut corriger le nombre proposé avant de valider — la
        valeur SAISIE est celle qui doit être retenue, pas la proposition."""
        self._produce(120, self.bp500)
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 115}],  # corrigé, pas 120
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        line = DailyOpeningConfirmationLine.objects.get(
            confirmation__node=self.node, confirmation__team='A',
            confirmation__date='2026-11-09', bread_price=self.bp500,
        )
        self.assertEqual(line.qty_confirmed, 115)

    def test_get_after_post_shows_confirmed_true_with_lines(self):
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'B', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 10}],
        }, format='json')

        resp = self.api.get('/api/production/opening-confirmation/?date=2026-11-09')
        self.assertTrue(resp.data['teams']['B']['confirmed'])
        self.assertFalse(resp.data['teams']['A']['confirmed'])
        self.assertEqual(resp.data['teams']['B']['lines'], [{'bread_price': self.bp500.pk, 'qty_confirmed': 10}])

    def test_post_is_idempotent_resubmission_replaces_previous_values(self):
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
        }, format='json')
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 90}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        self.assertEqual(
            DailyOpeningConfirmation.objects.filter(node=self.node, team='A', date='2026-11-09').count(),
            1,
        )
        line = DailyOpeningConfirmationLine.objects.get(
            confirmation__node=self.node, confirmation__team='A', confirmation__date='2026-11-09',
            bread_price=self.bp500,
        )
        self.assertEqual(line.qty_confirmed, 90)

    def test_post_resubmission_drops_removed_category_lines(self):
        """Une catégorie confirmée puis retirée lors d'une resoumission ne
        doit pas laisser de ligne obsolète."""
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [
                {'bread_price': self.bp500.pk, 'qty': 100},
                {'bread_price': self.bp1000.pk, 'qty': 20},
            ],
        }, format='json')
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
        }, format='json')

        confirmation = DailyOpeningConfirmation.objects.get(node=self.node, team='A', date='2026-11-09')
        self.assertEqual(confirmation.lines.count(), 1)
        self.assertFalse(confirmation.lines.filter(bread_price=self.bp1000).exists())

    def test_post_rejects_negative_quantity(self):
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': -5}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_post_rejects_invalid_team(self):
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'C', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 5}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_post_rejects_empty_lines(self):
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09', 'lines': [],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_post_rejects_unknown_bread_price(self):
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': 999999, 'qty': 5}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    # Intégration avec BUG-120 : priorité sur le calcul auto-dérivé,
    # sans jamais corrompre DailyBreadStockSnapshot.
    # ------------------------------------------------------------------

    def test_confirmed_value_overrides_reste_du_hier_in_daily_closure_report(self):
        """Quand une confirmation existe pour (node, équipe, date), le
        rapport de clôture journalier (BUG-120) doit utiliser la valeur
        CONFIRMÉE comme `reste_du_hier` pour cette équipe/catégorie, au lieu
        du calcul auto-dérivé de `DailyBreadStockSnapshot` — mais avec LA
        MÊME convention de signe (BUG-135) : `DailyOpeningConfirmationLine.
        qty_confirmed` reste stocké positif (voulu, BUG-133/134), mais
        l'agrégation du rapport doit le néger pour rester cohérente avec
        `DailyBreadStockSnapshot.reste_du_hier()` (négatif par construction,
        BUG-118) et ne pas fausser `facture_mvm_interne`/`total_du_jour`
        (BUG-120, déjà vérifiés formule à formule contre les Excel réels)."""
        # Produit, clôture une session la veille (crée un snapshot BUG-118
        # qui, SANS confirmation, donnerait un reste_du_hier auto-dérivé).
        resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-11-08', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 200}],
        }, format='json')
        session_id = resp.data['id']
        self.api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': self.bp500.pk,
            'disposal_type': 'REMAINING', 'quantity': 200,
        }, format='json')
        self.api.post(f'/api/production/sessions/{session_id}/close/')

        auto_value = DailyBreadStockSnapshot.reste_du_hier(self.node, self.bp500, '2026-11-09', 'A')
        self.assertEqual(auto_value, -200)  # calcul auto-dérivé existant (BUG-118), inchangé

        # Le gérant confirme explicitement 150 (valeur corrigée) pour le 09.
        # Stockage toujours positif (qty_confirmed = 150, voulu — BUG-134).
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 150}],
        }, format='json')
        line = DailyOpeningConfirmationLine.objects.get(
            confirmation__node=self.node, confirmation__team='A',
            confirmation__date='2026-11-09', bread_price=self.bp500,
        )
        self.assertEqual(line.qty_confirmed, 150)  # stockage positif inchangé (BUG-134)

        from production.views import _build_daily_closure_report
        report = _build_daily_closure_report(self.node, __import__('datetime').date(2026, 11, 9))
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row['reste_du_hier']['A'], -150)  # BUG-135 : négué dans l'agrégation, pas +150
        self.assertEqual(row['reste_du_hier']['B'], 0)  # équipe B non confirmée, jamais clôturée : auto-dérivé = 0

        # DailyBreadStockSnapshot n'a jamais été modifié par la confirmation.
        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_hier(self.node, self.bp500, '2026-11-09', 'A'),
            -200,
        )

    def test_confirmed_reste_du_hier_matches_auto_derived_in_total_du_jour(self):
        """BUG-135 : un jour/équipe confirmé (BUG-133) doit produire le même
        `reste_du_hier_fc`/`facture_mvm_interne`/`total_du_jour` (BUG-120,
        formule-vérifiée contre l'Excel réel) qu'un jour équivalent purement
        auto-dérivé via `DailyBreadStockSnapshot` — même grandeur, même
        signe. Avant le correctif, le jour confirmé donnait un total FAUX
        (signe inversé sur la contribution `reste_du_hier`)."""
        # Boulangerie "témoin" : purement auto-dérivée, aucune confirmation.
        resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-11-08', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 150}],
        }, format='json')
        session_id = resp.data['id']
        self.api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': self.bp500.pk,
            'disposal_type': 'REMAINING', 'quantity': 150,
        }, format='json')
        self.api.post(f'/api/production/sessions/{session_id}/close/')

        from production.views import _build_daily_closure_report
        import datetime
        auto_report = _build_daily_closure_report(self.node, datetime.date(2026, 11, 9))
        auto_row = next(c for c in auto_report['categories'] if c['bread_price'] == self.bp500.pk)

        # Boulangerie "confirmée" (autre nœud, pour éviter tout conflit de
        # contrainte d'unicité session node+team+date) : même situation
        # réelle (150 pains restants pour l'équipe A), mais déclarée via la
        # boîte modale BUG-133 plutôt que recalculée depuis une session
        # auto-dérivée.
        other_api = APIClient()
        other_api.force_authenticate(self.other_gerant)
        resp2 = other_api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-11-08', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 999}],
        }, format='json')
        session2_id = resp2.data['id']
        other_api.post('/api/production/disposals/', {
            'session': session2_id, 'bread_price': self.bp500.pk,
            'disposal_type': 'REMAINING', 'quantity': 999,
        }, format='json')
        other_api.post(f'/api/production/sessions/{session2_id}/close/')
        other_api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 150}],
        }, format='json')

        confirmed_report = _build_daily_closure_report(self.other_node, datetime.date(2026, 11, 9))
        confirmed_row = next(c for c in confirmed_report['categories'] if c['bread_price'] == self.bp500.pk)

        # Même signe, même grandeur pour la contribution reste_du_hier.
        self.assertEqual(auto_row['reste_du_hier']['A'], -150)
        self.assertEqual(confirmed_row['reste_du_hier']['A'], -150)
        self.assertEqual(confirmed_row['reste_du_hier']['A'], auto_row['reste_du_hier']['A'])

        # Et donc le même `facture_mvm_interne` (BUG-120) pour cette
        # catégorie, puisque toutes les autres rubriques sont identiques.
        self.assertEqual(
            confirmed_row['facture_mvm_interne']['fc'],
            auto_row['facture_mvm_interne']['fc'],
        )

    def test_unconfirmed_day_keeps_auto_derived_value_unchanged(self):
        """Un jour/équipe sans confirmation explicite doit continuer à
        utiliser exactement le calcul auto-dérivé existant (BUG-118) —
        non-régression totale."""
        resp = self.api.post('/api/production/sessions/', {
            'team': 'B', 'date': '2026-11-08', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 60}],
        }, format='json')
        session_id = resp.data['id']
        self.api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': self.bp500.pk,
            'disposal_type': 'REMAINING', 'quantity': 60,
        }, format='json')
        self.api.post(f'/api/production/sessions/{session_id}/close/')

        # Aucune confirmation BUG-133 n'est créée pour le 09.
        from production.views import _build_daily_closure_report
        report = _build_daily_closure_report(self.node, __import__('datetime').date(2026, 11, 9))
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row['reste_du_hier']['B'], -60)

    # ------------------------------------------------------------------
    # Permissions — même motif que BUG-022/025/056
    # ------------------------------------------------------------------

    def test_gerant_cannot_forge_node_on_get(self):
        resp = self.api.get(f'/api/production/opening-confirmation/?node={self.other_node.code}&date=2026-11-09')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['node'], self.node.code)  # ignoré, jamais l'autre nœud

    def test_gerant_cannot_forge_node_on_post(self):
        resp = self.api.post('/api/production/opening-confirmation/', {
            'node': self.other_node.code, 'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 5}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['node'], self.node.code)
        self.assertFalse(
            DailyOpeningConfirmation.objects.filter(node=self.other_node, team='A', date='2026-11-09').exists()
        )
        self.assertTrue(
            DailyOpeningConfirmation.objects.filter(node=self.node, team='A', date='2026-11-09').exists()
        )

    def test_headquarters_must_specify_node(self):
        hq = make_user(role='DIRECTION', node=None)
        api = APIClient()
        api.force_authenticate(hq)
        resp = api.get('/api/production/opening-confirmation/?date=2026-11-09')
        self.assertEqual(resp.status_code, 400)

    def test_headquarters_can_select_any_node(self):
        hq = make_user(role='DIRECTION', node=None)
        api = APIClient()
        api.force_authenticate(hq)
        resp = api.get(f'/api/production/opening-confirmation/?node={self.other_node.code}&date=2026-11-09')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['node'], self.other_node.code)

    def test_facturier_can_access_opening_confirmation_on_own_node(self):
        """BUG-138 (remarque.md l.398, « le facturier peut aussi faire ça »,
        tranché directement par le client) : un FACTURIER peut désormais
        consulter et soumettre la confirmation, mais jamais sur un autre
        nœud que le sien (même garantie que GERANT, BUG-022/025/056)."""
        facturier = make_user(role='FACTURIER', node=self.node, team='A')
        api = APIClient()
        api.force_authenticate(facturier)

        resp = api.get('/api/production/opening-confirmation/?date=2026-11-09')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['node'], self.node.code)

        post_resp = api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 5}],
        }, format='json')
        self.assertEqual(post_resp.status_code, 200, post_resp.data)
        self.assertTrue(
            DailyOpeningConfirmation.objects.filter(node=self.node, team='A', date='2026-11-09').exists()
        )

        # Toujours bloqué sur un autre nœud que le sien (node forgé ignoré,
        # même motif BUG-022/025/056 que pour GERANT).
        other_resp = api.get(f'/api/production/opening-confirmation/?node={self.other_node.code}&date=2026-11-09')
        self.assertEqual(other_resp.status_code, 200, other_resp.data)
        self.assertEqual(other_resp.data['node'], self.node.code)  # ignoré, jamais l'autre nœud

    def test_unauthenticated_request_rejected(self):
        api = APIClient()
        resp = api.get('/api/production/opening-confirmation/?date=2026-11-09')
        self.assertIn(resp.status_code, (401, 403))

    # ------------------------------------------------------------------
    # BUG-136 — la validation doit TOUJOURS synchroniser BreadStock.
    # ------------------------------------------------------------------

    def test_post_with_corrected_value_adjusts_real_stock_exactly(self):
        """Corriger la valeur proposée (120 -> 115) doit faire passer
        `BreadStock.qty_available` exactement à 115, pas rester à 120."""
        self._produce(120, self.bp500)
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 115}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_available, 115)
        self.assertEqual(resp.data['stock_adjustments'], [
            {'bread_price_id': self.bp500.pk, 'before': 120, 'after': 115, 'delta': -5},
        ])

    def test_post_validating_proposed_value_as_is_is_a_stock_noop(self):
        """Valider le nombre proposé tel quel ne doit rien changer à
        `BreadStock.qty_available` (delta nul, aucun ajustement journalisé)."""
        self._produce(120, self.bp500)
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 120}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_available, 120)
        self.assertEqual(resp.data['stock_adjustments'], [])

    def test_post_with_higher_value_than_proposed_increases_real_stock(self):
        """Déclarer PLUS de pains que ce que le système calculait (excédent
        constaté) doit augmenter `BreadStock.qty_available` en conséquence."""
        self._produce(50, self.bp500)
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 70}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_available, 70)

    def test_resubmission_does_not_double_apply_adjustment(self):
        """Resoumettre (correction avant de quitter la boîte modale) ne doit
        jamais cumuler l'ajustement : le delta est recalculé par rapport à
        l'état COURANT de `BreadStock`, pas par rapport à l'ancienne valeur
        confirmée mémorisée."""
        self._produce(120, self.bp500)
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
        }, format='json')
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_available, 100)

        # Le gérant corrige encore avant de quitter la boîte modale.
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 90}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        stock.refresh_from_db()
        self.assertEqual(stock.qty_available, 90)  # pas 80 (100 - 10 appliqué deux fois sur l'ancienne base)

    def test_second_team_get_reflects_first_team_adjustment(self):
        """Si l'équipe A confirme (et ajuste le stock réel) puis l'équipe B
        consulte le GET le même jour, `qty_proposed` pour B doit déjà
        refléter l'ajustement fait par A (qty_proposed lit `BreadStock.
        qty_available` au moment du GET, qui est désormais synchronisé)."""
        self._produce(120, self.bp500)
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 90}],
        }, format='json')

        resp = self.api.get('/api/production/opening-confirmation/?date=2026-11-09')
        by_bp = {row['bread_price']: row['qty_proposed'] for row in resp.data['categories']}
        self.assertEqual(by_bp[self.bp500.pk], 90)

    def test_adjustment_does_not_affect_other_category_stock(self):
        """Confirmer une catégorie ne doit jamais toucher au stock d'une
        autre catégorie non soumise dans la même requête."""
        self._produce(120, self.bp500)
        self._produce(40, self.bp1000)
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
        }, format='json')

        stock_1000 = BreadStock.objects.get(node=self.node, bread_price=self.bp1000)
        self.assertEqual(stock_1000.qty_available, 40)

    def test_adjustment_does_not_affect_other_node_stock(self):
        """Confirmer le stock de départ d'une boulangerie ne doit jamais
        toucher au stock d'une autre boulangerie (même catégorie)."""
        self._produce(120, self.bp500)
        self._produce(300, self.bp500, node=self.other_node)
        self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
        }, format='json')

        other_stock = BreadStock.objects.get(node=self.other_node, bread_price=self.bp500)
        self.assertEqual(other_stock.qty_available, 300)


class OpeningConfirmationNeedsConfirmationTests(TestCase):
    """
    BUG-139 (client, tranché directement avec le coordinateur, 2026-11-09,
    remarque.md l.398 « on le fait une fois le matin, [...] juste une fois
    au créneau d'ouverture (premier créneau) ») : UNE SEULE confirmation
    dans la journée (celle de l'équipe du créneau d'ouverture quand elle
    est déterminable) doit suffire à faire disparaître la boîte modale —
    PAS une confirmation distincte exigée pour A ET B.

    BUG-141 : « l'équipe du créneau d'ouverture » est déterminée de façon
    STRUCTURELLE à partir des horaires configurés du nœud
    (`Node.opening_team()` = l'équipe dont le créneau démarre le plus tôt
    dans la journée), **indépendamment de l'heure actuelle** — PAS via
    `Node.active_team_at()` (qui répond à « qui travaille EN CE MOMENT ? »,
    une question différente, utilisée ailleurs, BUG-130). Les tests
    ci-dessous configurent donc directement les horaires du nœud plutôt
    que de simuler une heure courante pour piloter `opening_team`.

    Le seul contrat testé ici est `needs_confirmation` (et `opening_team`)
    dans la réponse du GET — le stockage par équipe
    (`DailyOpeningConfirmation`) et `_build_daily_closure_report`/BUG-135
    ne changent pas (couverts par ailleurs, non dupliqués ici).
    """

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _get(self):
        resp = self.api.get('/api/production/opening-confirmation/?date=2026-11-09')
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data

    def _confirm(self, team, qty=10):
        resp = self.api.post('/api/production/opening-confirmation/', {
            'team': team, 'date': '2026-11-09',
            'lines': [{'bread_price': self.bp500.pk, 'qty': qty}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_with_configured_slots_only_the_opening_team_confirmation_is_required(self):
        """Créneaux configurés avec B en premier dans la journée (B démarre
        avant A) : la confirmation de A seule ne doit PAS suffire — mais la
        confirmation de B (équipe d'ouverture), seule, doit suffire, même si
        A n'a jamais confirmé ce jour."""
        from datetime import time
        self.node.team_b_start_time = time(5, 0)
        self.node.team_b_end_time = time(10, 0)
        self.node.team_a_start_time = time(14, 0)
        self.node.team_a_end_time = time(20, 0)
        self.node.save()

        data = self._get()
        self.assertEqual(data['opening_team'], 'B')
        self.assertTrue(data['needs_confirmation'])

        self._confirm('A')  # confirme A, pas l'équipe d'ouverture (B)
        data = self._get()
        self.assertTrue(data['teams']['A']['confirmed'])
        self.assertFalse(data['teams']['B']['confirmed'])
        self.assertTrue(data['needs_confirmation'])  # B (équipe d'ouverture) toujours pas confirmée

        self._confirm('B')  # B (équipe d'ouverture) confirme à son tour
        data = self._get()
        self.assertFalse(data['needs_confirmation'])  # suffit, même si A ne s'est jamais reconnectée

    def test_with_configured_slots_opening_team_confirmation_alone_suffices(self):
        """Créneaux configurés avec A en premier (A démarre avant B, cas K1
        réel) : SA SEULE confirmation (sans que B confirme jamais) doit
        suffire à faire disparaître la boîte modale."""
        from datetime import time
        self.node.team_a_start_time = time(6, 0)
        self.node.team_a_end_time = time(11, 30)
        self.node.team_b_start_time = time(14, 30)
        self.node.team_b_end_time = time(20, 0)
        self.node.save()

        self._confirm('A')
        data = self._get()
        self.assertEqual(data['opening_team'], 'A')
        self.assertFalse(data['needs_confirmation'])
        self.assertFalse(data['teams']['B']['confirmed'])  # jamais confirmée, et ce n'est pas requis

    def test_without_configured_slots_either_team_confirmation_suffices(self):
        """Filet de sécurité : nœud sans créneaux configurés
        (`opening_team()` renvoie `None`, cas réel tant que BUG-130/131
        n'est pas rempli pour certaines boulangeries) — UNE confirmation, A
        OU B, suffit ; on n'exige jamais les deux."""
        data = self._get()
        self.assertIsNone(data['opening_team'])
        self.assertTrue(data['needs_confirmation'])

        self._confirm('B')  # peu importe laquelle
        data = self._get()
        self.assertIsNone(data['opening_team'])
        self.assertFalse(data['needs_confirmation'])
        self.assertFalse(data['teams']['A']['confirmed'])  # jamais confirmée, et ce n'est pas requis

    def test_without_configured_slots_no_confirmation_at_all_needs_confirmation_true(self):
        data = self._get()
        self.assertIsNone(data['opening_team'])
        self.assertTrue(data['needs_confirmation'])

    def test_bug141_opening_team_is_first_slot_regardless_of_current_time(self):
        """BUG-141 : l'équipe du créneau d'ouverture est déterminée par les
        horaires CONFIGURÉS du nœud (le plus tôt dans la journée), jamais par
        l'heure actuelle de connexion. Avant le correctif, à 21h (hors des
        deux créneaux K1 réels : A 06:00-11:30, B 14:30-20:00),
        `Node.active_team_at()` renvoyait `None` et la boîte modale ne
        présélectionnait plus aucune équipe — alors que le premier créneau
        de la journée est toujours A, peu importe l'heure de connexion
        (remarque.md l.398 : un gérant/facturier peut rattraper une
        confirmation oubliée le soir)."""
        from datetime import time, datetime as _datetime
        self.node.team_a_start_time = time(6, 0)
        self.node.team_a_end_time = time(11, 30)
        self.node.team_b_start_time = time(14, 30)
        self.node.team_b_end_time = time(20, 0)
        self.node.save()

        # Preuve du contraste : à 21h (hors des deux créneaux), l'ancienne
        # base de calcul (`active_team_at()`, toujours utilisée ailleurs
        # pour « qui travaille EN CE MOMENT ? », BUG-130) ne reconnaît aucune
        # équipe active — ce n'est PAS la question posée par `opening_team`.
        with patch.object(
            timezone, 'localtime',
            return_value=timezone.make_aware(_datetime(2026, 11, 9, 21, 0)),
        ):
            self.assertIsNone(self.node.active_team_at())

        # `opening_team` (utilisé par la vue), lui, reste 'A' : purement
        # structurel, jamais affecté par l'heure courante.
        data = self._get()
        self.assertEqual(data['opening_team'], 'A')
        self.assertTrue(data['needs_confirmation'])
