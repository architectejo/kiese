"""
BUG-142 (remarque.md, ligne ajoutée par le client juste après l.394) :

« Lors de la confirmation de reste des pains, une fournée doit être créée
pour l'équipe en question dans "Production & Stocks" pour l'équipe choisie
et lors de la déclaration de fournée dans "Production & Stocks" les nombres
des pains déclarés doit s'ajouter à la fournée selon l'équipe, en cas de
plusieurs déclarations dans la journée on ne crée pas plusieurs fournées
mais on ajoute à la fournée existante de la journée selon l'équipe. »

Deux comportements couverts :
  A) Deux déclarations de fournée (`ProductionSessionViewSet`) le même jour
     pour la même équipe s'ADDITIONNENT dans une seule `ProductionSession`
     (au lieu du rejet 400 d'avant, sur `unique_together`).
  B) La confirmation du stock de départ (BUG-133/136) crée/alimente la
     `ProductionSession` du jour avec des lignes `source=CARRYOVER`.

Contrainte financière tranchée avec le client (CLAUDE.md §7 règle 6 : pas de
redemande) : les lignes CARRYOVER (reste d'hier, aucune farine consommée)
sont exclues de `total_fc_produced`/`theoretical_yield`/`yield_gap` (pas de
fausse alerte « Manquant de Rendement »), mais comptent dans `total_breads`
(total réel de pains disponibles ce jour). Et `BreadStock.qty_available` ne
doit jamais être ajusté deux fois (une fois par BUG-136, jamais une seconde
fois par la création des lignes CARRYOVER).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import ProductionSession, ProductionSessionLine, BreadStock


class FourneeAccumulationSameDayTeamTests(TestCase):
    """Cas A — plusieurs déclarations le même jour/équipe s'additionnent."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.user = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.bp1000 = make_bread_price(category='GRAND', label='Pain 1000 FC', unit_price=1000)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def _declare(self, flour_sacks, lines, team='A', date='2026-11-10'):
        return self.api.post('/api/production/sessions/', {
            'team': team, 'date': date,
            'flour_sacks_used': str(flour_sacks),
            'lines': lines,
        }, format='json')

    def test_second_declaration_same_day_team_adds_instead_of_rejecting(self):
        resp1 = self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 100}])
        self.assertEqual(resp1.status_code, 201, resp1.data)

        resp2 = self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 50}])
        self.assertEqual(
            resp2.status_code, 201,
            f"Une 2e déclaration le même jour/équipe doit s'ajouter (201), pas être rejetée (400) : {resp2.data}",
        )

        self.assertEqual(
            ProductionSession.objects.filter(node=self.node, team='A', date='2026-11-10').count(), 1,
            "Une seule ProductionSession doit exister pour (node, team, date), jamais un doublon.",
        )
        session = ProductionSession.objects.get(node=self.node, team='A', date='2026-11-10')
        self.assertEqual(session.flour_sacks_used, Decimal('2.00'))
        line = session.lines.get(bread_price=self.bp500, source=ProductionSessionLine.Source.DECLARED)
        self.assertEqual(line.quantity, 150)
        self.assertEqual(session.total_breads, 150)
        self.assertEqual(session.total_fc_produced, 150 * 500)

    def test_second_declaration_creates_new_line_for_a_new_category(self):
        self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 100}])
        resp2 = self._declare(1, [{'bread_price': self.bp1000.pk, 'quantity': 20}])
        self.assertEqual(resp2.status_code, 201, resp2.data)

        session = ProductionSession.objects.get(node=self.node, team='A', date='2026-11-10')
        self.assertEqual(session.lines.count(), 2)
        self.assertEqual(
            session.lines.get(bread_price=self.bp1000, source=ProductionSessionLine.Source.DECLARED).quantity,
            20,
        )

    def test_sac_value_used_stays_fixed_to_first_declaration_of_the_day(self):
        """BUG-038 : un ajout ultérieur ne doit jamais réécrire sac_value_fc_used,
        même si Node.sac_value_fc change entre les deux déclarations."""
        resp1 = self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 100}])
        self.assertEqual(resp1.data['sac_value_fc_used'], 200000)

        self.node.sac_value_fc = Decimal('230000')
        self.node.save(update_fields=['sac_value_fc'])

        resp2 = self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 50}])
        self.assertEqual(resp2.status_code, 201, resp2.data)
        self.assertEqual(resp2.data['sac_value_fc_used'], 200000)

        session = ProductionSession.objects.get(node=self.node, team='A', date='2026-11-10')
        self.assertEqual(session.sac_value_fc_used, 200000)
        self.assertEqual(session.theoretical_yield, 2 * 200000)

    def test_bread_stock_is_incremented_by_each_declaration_not_double_counted(self):
        self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 100}])
        self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 50}])

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_produced, 150)
        self.assertEqual(stock.qty_available, 150)

    def test_different_team_same_day_still_creates_a_separate_session(self):
        self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 100}], team='A')
        resp_b = self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 60}], team='B')
        self.assertEqual(resp_b.status_code, 201, resp_b.data)
        self.assertEqual(
            ProductionSession.objects.filter(node=self.node, date='2026-11-10').count(), 2,
        )

    def test_closed_session_rejects_further_declaration(self):
        resp1 = self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 100}])
        session_id = resp1.data['id']
        close_resp = self.api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)

        resp2 = self._declare(1, [{'bread_price': self.bp500.pk, 'quantity': 50}])
        self.assertEqual(
            resp2.status_code, 400,
            f"Une session clôturée ne doit jamais accepter d'ajout silencieux : {resp2.data}",
        )
        self.assertEqual(
            ProductionSession.objects.filter(node=self.node, team='A', date='2026-11-10').count(), 1,
        )


class OpeningConfirmationFeedsProductionSessionTests(TestCase):
    """Cas B — la confirmation du stock de départ crée/alimente la fournée du jour."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _confirm(self, team, qty, date='2026-11-10'):
        return self.api.post('/api/production/opening-confirmation/', {
            'team': team, 'date': date,
            'lines': [{'bread_price': self.bp500.pk, 'qty': qty}],
        }, format='json')

    def test_confirmation_alone_creates_a_production_session_with_carryover_line(self):
        resp = self._confirm('A', 80)
        self.assertEqual(resp.status_code, 200, resp.data)

        session = ProductionSession.objects.get(node=self.node, team='A', date='2026-11-10')
        line = session.lines.get(bread_price=self.bp500)
        self.assertEqual(line.source, ProductionSessionLine.Source.CARRYOVER)
        self.assertEqual(line.quantity, 80)

    def test_confirmation_only_session_has_no_false_yield_shortage(self):
        """Sanity : une session alimentée uniquement de reste d'hier ne doit
        jamais déclencher une fausse alerte « Manquant de Rendement » —
        aucune farine n'a été consommée, ce n'est pas une production."""
        self._confirm('A', 80)
        session = ProductionSession.objects.get(node=self.node, team='A', date='2026-11-10')
        self.assertEqual(session.flour_sacks_used, Decimal('0.00'))
        self.assertEqual(session.theoretical_yield, 0)
        self.assertEqual(session.total_fc_produced, 0)
        self.assertEqual(session.yield_gap, 0)
        self.assertEqual(session.total_breads, 80)  # reste d'hier compté comme pains disponibles

    def test_resubmitting_confirmation_replaces_carryover_line_not_additive(self):
        """La confirmation est idempotente (resoumission remplace, BUG-136) —
        la ligne CARRYOVER doit suivre la même sémantique, pas s'additionner."""
        self._confirm('A', 80)
        self._confirm('A', 60)  # correction avant de quitter la boîte modale

        session = ProductionSession.objects.get(node=self.node, team='A', date='2026-11-10')
        line = session.lines.get(bread_price=self.bp500, source=ProductionSessionLine.Source.CARRYOVER)
        self.assertEqual(line.quantity, 60)
        self.assertEqual(session.lines.filter(source=ProductionSessionLine.Source.CARRYOVER).count(), 1)

    def test_confirmation_then_real_fournee_same_day_team_accumulates_in_same_session(self):
        """Confirmation PUIS vraie fournée : une seule session, total_breads
        = carryover + déclaré, mais total_fc_produced/yield_gap ne comptent
        que le déclaré."""
        self._confirm('A', 80)

        decl_resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-11-10', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 200}],
        }, format='json')
        self.assertEqual(decl_resp.status_code, 201, decl_resp.data)

        self.assertEqual(
            ProductionSession.objects.filter(node=self.node, team='A', date='2026-11-10').count(), 1,
        )
        session = ProductionSession.objects.get(node=self.node, team='A', date='2026-11-10')
        self.assertEqual(session.lines.count(), 2)
        self.assertEqual(session.total_breads, 80 + 200)
        self.assertEqual(session.total_fc_produced, 200 * 500)  # carryover exclu
        self.assertEqual(session.theoretical_yield, 200000)  # 1 sac × 200 000
        self.assertEqual(session.yield_gap, (200 * 500) - 200000)

    def test_real_fournee_then_confirmation_same_day_team_accumulates_in_same_session(self):
        """Ordre inverse : vraie fournée PUIS confirmation — même résultat final."""
        decl_resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-11-10', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 200}],
        }, format='json')
        self.assertEqual(decl_resp.status_code, 201, decl_resp.data)

        confirm_resp = self._confirm('A', 80)
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.data)

        self.assertEqual(
            ProductionSession.objects.filter(node=self.node, team='A', date='2026-11-10').count(), 1,
        )
        session = ProductionSession.objects.get(node=self.node, team='A', date='2026-11-10')
        self.assertEqual(session.lines.count(), 2)
        self.assertEqual(session.total_breads, 200 + 80)
        self.assertEqual(session.total_fc_produced, 200 * 500)
        self.assertEqual(session.theoretical_yield, 200000)

    def test_no_double_counting_on_bread_stock_when_confirmation_and_declaration_combine(self):
        """BUG-136 ajuste `BreadStock` une fois à la confirmation — la
        création de la ligne CARRYOVER ne doit jamais déclencher un second
        ajustement (`_adjust_bread_stock(produced=...)`)."""
        from production.models import _adjust_bread_stock
        _adjust_bread_stock(self.node, self.bp500, produced=80)  # stock physique réel préexistant

        confirm_resp = self._confirm('A', 80)  # valide tel quel (delta nul, no-op BUG-136)
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.data)
        self.assertEqual(confirm_resp.data['stock_adjustments'], [])

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_available, 80, "Le reste d'hier ne doit jamais être compté deux fois.")

        decl_resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-11-10', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 200}],
        }, format='json')
        self.assertEqual(decl_resp.status_code, 201, decl_resp.data)

        stock.refresh_from_db()
        self.assertEqual(
            stock.qty_available, 80 + 200,
            "La vraie déclaration doit ajouter 200 au stock réel — ni double comptage du reste "
            "d'hier, ni absence d'ajout de la vraie fournée.",
        )

    def test_closed_session_rejects_confirmation_for_same_day_team(self):
        decl_resp = self.api.post('/api/production/sessions/', {
            'team': 'A', 'date': '2026-11-10', 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp500.pk, 'quantity': 200}],
        }, format='json')
        session_id = decl_resp.data['id']
        close_resp = self.api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)

        confirm_resp = self._confirm('A', 50)
        self.assertEqual(
            confirm_resp.status_code, 400,
            f"Une confirmation ne doit jamais contourner une session déjà clôturée : {confirm_resp.data}",
        )
        # Ni la confirmation elle-même, ni l'ajustement BUG-136 n'ont été
        # appliqués (transaction annulée dans son ensemble).
        from production.models import DailyOpeningConfirmation
        self.assertFalse(
            DailyOpeningConfirmation.objects.filter(node=self.node, team='A', date='2026-11-10').exists()
        )
