"""
Vérification indépendante (testeur-production, 2026-11-10) de BUG-155.

Ces scénarios sont construits séparément de
`test_bug155_shift_end_auto_closure.py` (dev-backend) — ils ciblent des
angles non garantis par cette suite :

  1. Les deux équipes A et B en attente simultanément sur le même nœud/appel
     (`shift_end_status` ne traite qu'une équipe à la fois, A avant B — il
     faut vérifier que ce choix documenté est bien respecté, et que
     ré-appeler ensuite traite effectivement B).
  2. Clôture forcée (grâce dépassée) alors que le stock physique
     (`BreadStock.qty_available`) d'une catégorie est NÉGATIF (BUG-143 :
     sortie de stock autorisée au-delà du disponible) — contrairement à
     l'appel volontaire `close()` qui REJETTE explicitement toute quantité
     négative dans `remaining` (HTTP 400), la voie automatique construit
     `remaining_entries` directement depuis le stock physique, sans repasser
     par cette validation.
  3. Isolation : un utilisateur non-HQ ne peut jamais faire évaluer un AUTRE
     nœud que le sien via `?node=`, même si l'autre nœud a une fournée en
     attente de clôture.
  4. Multi-catégories de pain dans la clôture forcée (au moins 2 catégories,
     une seule des deux ayant une fournée produite — l'autre à 0 explicite).
  5. Non-régression de l'appel volontaire `close()` avec un `remaining`
     DIFFÉRENT du stock physique courant (le gérant déclare volontairement un
     reste qui ne correspond pas à `BreadStock.qty_available` — ce doit être
     accepté tel quel, sans être « corrigé » silencieusement par la logique
     factorisée issue de BUG-155).
"""
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import ProductionSession, BreadDisposal, BreadStock

SESSION_DATE = date(2026, 10, 12)


def _aware(d, hour, minute):
    return timezone.make_aware(
        datetime(d.year, d.month, d.day, hour, minute),
        timezone.get_current_timezone(),
    )


class BothTeamsPendingTests(TestCase):
    """Angle 1 : A et B simultanément en attente sur le même nœud."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.node.team_a_end_time = time(12, 0)
        self.node.team_b_end_time = time(13, 0)
        self.node.save(update_fields=['team_a_end_time', 'team_b_end_time'])

        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC QA1', unit_price=500)

        self.client_api = APIClient()
        self.client_api.force_authenticate(self.gerant)

        for team in ('A', 'B'):
            resp = self.client_api.post('/api/production/sessions/', {
                'team': team, 'date': SESSION_DATE.isoformat(), 'flour_sacks_used': '1.00',
                'lines': [{'bread_price': self.bp.pk, 'quantity': 150}],
            }, format='json')
            self.assertEqual(resp.status_code, 201, resp.data)

    def _status(self, mocked_now):
        with patch('django.utils.timezone.now', return_value=mocked_now):
            return self.client_api.get(
                '/api/production/sessions/shift-end-status/', {'node': self.node.code},
            )

    def test_both_teams_overdue_only_team_a_signaled_first_call(self):
        """
        13h30 : A dépasse son créneau de 1h30 (> grâce), B de 30 min (pile la
        limite). Un seul appel ne doit traiter/signaler QUE l'équipe A
        (ordre documenté A puis B, une équipe par appel) — B ne doit PAS
        être clôturée ni signalée par ce même appel.
        """
        resp = self._status(_aware(SESSION_DATE, 13, 30))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data.get('team'), 'A')
        self.assertTrue(resp.data.get('auto_closed'))

        session_a = ProductionSession.objects.get(node=self.node, team='A', date=SESSION_DATE)
        session_b = ProductionSession.objects.get(node=self.node, team='B', date=SESSION_DATE)
        self.assertTrue(session_a.is_closed)
        self.assertFalse(
            session_b.is_closed,
            "L'équipe B ne doit pas être affectée par le même appel que celui ayant traité A.",
        )

    def test_second_call_after_a_resolved_then_signals_b(self):
        """
        Une fois A clôturée (appel précédent), un second appel au même
        horodatage doit désormais traiter B (comportement attendu du
        « re-sondage immédiat » documenté côté frontend BUG-156).
        """
        self._status(_aware(SESSION_DATE, 13, 30))  # résout A
        resp = self._status(_aware(SESSION_DATE, 13, 30))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data.get('team'), 'B')
        self.assertTrue(resp.data.get('auto_closed'))

        session_b = ProductionSession.objects.get(node=self.node, team='B', date=SESSION_DATE)
        self.assertTrue(session_b.is_closed)


class NegativePhysicalStockAutoClosureTests(TestCase):
    """
    Angle 2 : clôture forcée avec un `BreadStock.qty_available` négatif
    (BUG-143, sortie de stock autorisée au-delà du disponible).
    """

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.node.team_a_end_time = time(13, 0)
        self.node.save(update_fields=['team_a_end_time'])

        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC QA2', unit_price=500)

        self.client_api = APIClient()
        self.client_api.force_authenticate(self.gerant)

        resp = self.client_api.post('/api/production/sessions/', {
            'team': 'A', 'date': SESSION_DATE.isoformat(), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 50}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.session_id = resp.data['id']

        # Dispositions dépassant le produit (DECLASSED, 70 > 50 produits) :
        # stock physique devient négatif (-20), comportement explicitement
        # autorisé côté consommables sous BUG-143 ; `BreadStock.qty_available`
        # n'a, lui, aucune garde connue l'empêchant de devenir négatif non
        # plus (`qty_disposed` est juste incrémenté, sans clamp, dans
        # `BreadDisposalViewSet.perform_create`).
        resp = self.client_api.post('/api/production/disposals/', {
            'session': self.session_id, 'bread_price': self.bp.pk,
            'disposal_type': 'DECLASSED', 'quantity': 70,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, -20, "Pré-requis du scénario : stock physique négatif.")

    def test_forced_closure_with_negative_available_stock(self):
        """
        BUG-158 : grâce dépassée (13h40, soit +40 min) avec stock physique
        négatif sur une catégorie (BUG-143 : sortie de stock/dispositions
        autorisées au-delà du disponible, sans clamp ailleurs dans le code).

        Comportement ATTENDU (documenté comme tel, pas encore garanti) : la
        clôture forcée doit s'exécuter sans lever d'exception serveur — au
        pire en clampant la quantité suggérée à 0, au mieux en appliquant la
        même garde HTTP 400 que `close()` volontaire pour une quantité
        négative (mais alors sans jamais pouvoir résoudre automatiquement
        cette fournée, ce qui demande une décision produit).

        Comportement RÉEL observé (2026-11-10) : `shift_end_status()` plante
        avec `django.db.utils.IntegrityError: CHECK constraint failed:
        quantity` (HTTP 500 non intercepté) en tentant de persister
        `BreadDisposal.quantity = -20` (`PositiveIntegerField`, contrainte
        CHECK ajoutée automatiquement par Django ≥4.1 au niveau base). La
        transaction étant atomique, la session N'EST PAS clôturée — le
        prochain polling retente la même opération et échoue à nouveau :
        blocage indéfini de la clôture automatique (et donc de la clôture
        journalière) de cette boulangerie tant que le stock négatif n'est
        pas corrigé manuellement, sans aucune notification ni message
        d'erreur exploitable côté frontend (juste un 500 générique au
        polling, silencieux pour l'utilisateur).
        """
        with patch('django.utils.timezone.now', return_value=_aware(SESSION_DATE, 13, 40)):
            resp = self.client_api.get(
                '/api/production/sessions/shift-end-status/', {'node': self.node.code},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data.get('auto_closed'))

        session = ProductionSession.objects.get(pk=self.session_id)
        self.assertTrue(session.is_closed)

        remaining = BreadDisposal.objects.filter(
            session=session, disposal_type=BreadDisposal.DisposalType.REMAINING,
        ).first()
        self.assertIsNotNone(remaining, "Une ligne REMAINING doit être créée même avec un stock négatif.")
        self.assertEqual(remaining.quantity, -20)


class ShiftEndStatusNodeIsolationTests(TestCase):
    """Angle 3 : un facturier non-HQ ne peut jamais interroger un autre nœud."""

    def setUp(self):
        self.own_node = make_node(sac_value_fc=Decimal('200000'))
        self.own_node.team_a_end_time = time(23, 59)  # jamais dépassé pendant le test
        self.own_node.save(update_fields=['team_a_end_time'])

        self.other_node = make_node(sac_value_fc=Decimal('150000'))
        self.other_node.team_a_end_time = time(0, 1)  # dépassé dès le début de journée
        self.other_node.save(update_fields=['team_a_end_time'])

        self.facturier = make_user(role='FACTURIER', node=self.own_node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC QA3', unit_price=500)

        other_gerant = make_user(role='GERANT', node=self.other_node)
        other_client = APIClient()
        other_client.force_authenticate(other_gerant)
        resp = other_client.post('/api/production/sessions/', {
            'team': 'A', 'date': SESSION_DATE.isoformat(), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 80}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        self.client_api = APIClient()
        self.client_api.force_authenticate(self.facturier)

    def test_non_hq_user_cannot_probe_other_node_via_query_param(self):
        """
        `?node=<autre boulangerie>` envoyé par un FACTURIER rattaché à un
        AUTRE nœud doit être ignoré : la vue doit évaluer SON nœud, jamais
        celui demandé en paramètre (même règle documentée que
        `BreadStockByDateView`/`DailyClosureReportView`).
        """
        with patch('django.utils.timezone.now', return_value=_aware(SESSION_DATE, 10, 0)):
            resp = self.client_api.get(
                '/api/production/sessions/shift-end-status/', {'node': self.other_node.code},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        # Le nœud du facturier (own_node) n'a pas de créneau dépassé à 10h :
        # rien à signaler. Si l'isolation était cassée, la fournée de
        # `other_node` (créneau dépassé depuis minuit) serait clôturée par un
        # utilisateur totalement étranger à cette boulangerie.
        self.assertEqual(resp.data, {'pending_validation': False})

        other_session = ProductionSession.objects.get(node=self.other_node, team='A', date=SESSION_DATE)
        self.assertFalse(
            other_session.is_closed,
            "Un facturier d'un autre nœud ne doit jamais pouvoir déclencher la clôture forcée "
            "de la boulangerie d'un autre via `?node=`.",
        )


class MultiCategoryForcedClosureTests(TestCase):
    """Angle 4 : clôture forcée avec plusieurs catégories de pain."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.node.team_a_end_time = time(13, 0)
        self.node.save(update_fields=['team_a_end_time'])

        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp_500 = make_bread_price(category='MOYEN', label='Pain 500 FC QA4', unit_price=500)
        self.bp_200 = make_bread_price(category='PETIT', label='Pain 200 FC QA4', unit_price=200)

        self.client_api = APIClient()
        self.client_api.force_authenticate(self.gerant)

        resp = self.client_api.post('/api/production/sessions/', {
            'team': 'A', 'date': SESSION_DATE.isoformat(), 'flour_sacks_used': '2.00',
            'lines': [
                {'bread_price': self.bp_500.pk, 'quantity': 100},
                {'bread_price': self.bp_200.pk, 'quantity': 60},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.session_id = resp.data['id']

        # Tout le pain à 200 FC a été vendu : son stock physique tombe à 0,
        # alors que le pain à 500 FC reste entièrement en stock (100).
        resp = self.client_api.post('/api/production/disposals/', {
            'session': self.session_id, 'bread_price': self.bp_200.pk,
            'disposal_type': 'UNSOLD', 'quantity': 60,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_forced_closure_creates_one_remaining_line_per_category_including_zero(self):
        with patch('django.utils.timezone.now', return_value=_aware(SESSION_DATE, 13, 35)):
            resp = self.client_api.get(
                '/api/production/sessions/shift-end-status/', {'node': self.node.code},
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data.get('auto_closed'))

        session = ProductionSession.objects.get(pk=self.session_id)
        self.assertTrue(session.is_closed)

        remaining = {
            d.bread_price_id: d.quantity
            for d in BreadDisposal.objects.filter(
                session=session, disposal_type=BreadDisposal.DisposalType.REMAINING,
            )
        }
        self.assertEqual(remaining.get(self.bp_500.pk), 100)
        self.assertEqual(
            remaining.get(self.bp_200.pk), 0,
            "La catégorie entièrement épuisée doit quand même produire une ligne REMAINING à 0, "
            "jamais une absence de ligne.",
        )


class VoluntaryCloseDivergingFromPhysicalStockTests(TestCase):
    """
    Angle 5 : non-régression BUG-152/154 — l'appel volontaire `close()` avec
    un `remaining` sciemment DIFFÉRENT du stock physique courant doit être
    accepté sans que la factorisation introduite sous BUG-155
    (`_close_production_session`) ne vienne « corriger » silencieusement la
    valeur en la remplaçant par `BreadStock.qty_available`.
    """

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC QA5', unit_price=500)

        self.client_api = APIClient()
        self.client_api.force_authenticate(self.gerant)

        resp = self.client_api.post('/api/production/sessions/', {
            'team': 'A', 'date': SESSION_DATE.isoformat(), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 300}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.session_id = resp.data['id']

    def test_declared_remaining_overrides_physical_stock_value(self):
        stock_before = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock_before.qty_available, 300)

        resp = self.client_api.post(
            f'/api/production/sessions/{self.session_id}/close/',
            {'remaining': [{'bread_price': self.bp.pk, 'quantity': 12}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        remaining = BreadDisposal.objects.get(
            session_id=self.session_id, disposal_type=BreadDisposal.DisposalType.REMAINING,
        )
        self.assertEqual(
            remaining.quantity, 12,
            "La valeur volontairement déclarée (12) doit primer, même si elle diverge "
            "largement du stock physique courant (300) — close() ne doit jamais substituer "
            "silencieusement le stock physique à une valeur explicitement fournie.",
        )
