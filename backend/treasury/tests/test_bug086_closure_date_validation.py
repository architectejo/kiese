"""
BUG-086 (extension de BUG-083, remarque.md l.362, demande client) :

1. L'écran « Clôture & Caisse » doit, quand `Config.allow_backdated_sales`
   est actif, permettre de choisir la date à clôturer.
2. En creusant cette demande : `CashClosureViewSet.perform_create`
   acceptait DÉJÀ une `date` arbitraire dans le payload (trou préexistant,
   indépendant du réglage) — aucune date future n'était refusée, et aucune
   date passée n'exigeait `Config.allow_backdated_sales=True`. N'importe
   quel Gérant pouvait donc déjà clôturer n'importe quelle date, réglage
   désactivé ou non.

Ce fichier couvre la correction : même règle que
`sales.views._validate_requested_date` (désormais partagée via
`core.utils.validate_requested_date`), appliquée à `date` de `CashClosure`
— en création (`perform_create`) et en modification après infirmation
(`perform_update`).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import CashClosure, FacturierReport, LocalExpense
from core.models import ExpenseCategory


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class ClosureDateRejectedWhenBackdatedSalesDisabledTests(TestCase):
    """(a) Réglage désactivé (comportement par défaut) → toute date de
    clôture différente d'aujourd'hui est refusée, y compris pour un rôle
    Siège (`can_access_all_nodes`) — le réglage n'est pas un contournement
    de permission."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086_1')
        self.hq = make_user(role='DIRECTION', username='direction_b086_1')

        config = Config.get_instance()
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])

        self.api_gerant = _api_for(self.gerant)
        self.api_hq = _api_for(self.hq)
        self.yesterday = date.today() - timedelta(days=1)

    def test_gerant_cannot_close_a_past_date_when_setting_disabled(self):
        resp = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(self.yesterday),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.json())
        self.assertFalse(
            CashClosure.objects.filter(node=self.node, date=self.yesterday).exists()
        )

    def test_hq_role_cannot_bypass_the_setting_either(self):
        """Le réglage n'est pas une question de permission RBAC — un rôle
        Siège qui peut choisir le nœud ne doit pas pouvoir, via ce biais,
        clôturer une date passée alors que le réglage est désactivé."""
        resp = self.api_hq.post('/api/treasury/closures/', {
            'node': str(self.node.id),
            'date': str(self.yesterday),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertFalse(
            CashClosure.objects.filter(node=self.node, date=self.yesterday).exists()
        )

    def test_today_still_works_when_setting_disabled(self):
        """Non-régression : clôturer la date du jour reste permis, réglage
        désactivé ou pas."""
        resp = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(date.today()),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        closure = CashClosure.objects.get(pk=resp.json()['id'])
        self.assertEqual(closure.date, date.today())


class ClosureFutureDateAlwaysRejectedTests(TestCase):
    """(b) Une date future est TOUJOURS refusée, même réglage activé."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086_2')
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])
        self.api_gerant = _api_for(self.gerant)
        self.tomorrow = date.today() + timedelta(days=1)

    def test_future_closure_date_rejected_even_with_setting_enabled(self):
        resp = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(self.tomorrow),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('future', resp.json().get('detail', '').lower())
        self.assertFalse(
            CashClosure.objects.filter(node=self.node, date=self.tomorrow).exists()
        )


class ClosureOnPastDateUsesThatDaysOwnFiguresTests(TestCase):
    """(c) Réglage activé → la clôture d'un jour passé fonctionne et ses
    totaux reflètent les mouvements de CE jour-là (pas ceux d'aujourd'hui)."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086_3')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_b086_3')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        self.category, _ = ExpenseCategory.objects.get_or_create(
            code='TRANSPORT_B086', defaults={'label': 'Transport'}
        )

        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

        self.api_gerant = _api_for(self.gerant)
        self.past_day = date.today() - timedelta(days=5)

    def test_past_closure_totals_reflect_the_past_day_not_today(self):
        # Mouvements du jour PASSÉ (celui qu'on va clôturer).
        FacturierReport.objects.create(
            node=self.node, facturier=self.facA, team='A', date=self.past_day,
            total_cash_sales=Decimal('3000.00'), theoretical_cash=Decimal('3000.00'),
            node_origin=self.node.code,
        )
        LocalExpense.objects.create(
            node=self.node, gerant=self.gerant, description='Transport farine',
            amount=Decimal('500.00'), category=self.category, date=self.past_day,
            node_origin=self.node.code,
        )

        # Mouvements d'AUJOURD'HUI — ne doivent PAS contaminer la clôture
        # du jour passé si la correction fonctionne correctement.
        FacturierReport.objects.create(
            node=self.node, facturier=self.facA, team='A', date=date.today(),
            total_cash_sales=Decimal('99999.00'), theoretical_cash=Decimal('99999.00'),
            node_origin=self.node.code,
        )
        LocalExpense.objects.create(
            node=self.node, gerant=self.gerant, description='Dépense du jour',
            amount=Decimal('12345.00'), category=self.category, date=date.today(),
            node_origin=self.node.code,
        )

        resp = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(self.past_day),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        closure = CashClosure.objects.get(pk=resp.json()['id'])

        self.assertEqual(closure.date, self.past_day)
        self.assertEqual(closure.total_entries, Decimal('3000.00'))
        self.assertEqual(closure.total_expenses, Decimal('500.00'))
        self.assertEqual(closure.net_cash, Decimal('2500.00'))


class ClosureUpdateDateValidationTests(TestCase):
    """La même règle s'applique à `perform_update` (resoumission par le
    gérant après infirmation) — `date` n'est pas en lecture seule sur le
    serializer, donc le même trou existait côté modification."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086_4')
        self.comptable = make_user(role='COMPTABLE', username='comptable_b086_4')
        config = Config.get_instance()
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])
        self.api_gerant = _api_for(self.gerant)
        self.api_comptable = _api_for(self.comptable)

    def test_patch_cannot_change_date_to_a_future_date(self):
        create = self.api_gerant.post('/api/treasury/closures/', {
            'date': str(date.today()),
        }, format='json')
        self.assertEqual(create.status_code, 201, create.content)
        closure = CashClosure.objects.get(pk=create.json()['id'])

        reject = self.api_comptable.post(
            f'/api/treasury/closures/{closure.id}/reject/', {'reason': 'test'}, format='json'
        )
        self.assertEqual(reject.status_code, 200, reject.content)

        tomorrow = date.today() + timedelta(days=1)
        resp = self.api_gerant.patch(
            f'/api/treasury/closures/{closure.id}/', {'date': str(tomorrow)}, format='json'
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        closure.refresh_from_db()
        self.assertNotEqual(closure.date, tomorrow)
