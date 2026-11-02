"""
BUG-086 (extension de BUG-083, remarque.md l.362, demande client complémentaire) :

En plus du volet « Clôture & Caisse » (voir
`test_bug086_closure_date_validation.py`), le client demande que l'écran
§5.1.1 « Niveau 1 · Rapports Journaliers des Facturiers » permette aussi de
choisir une date avant de générer le rapport —
`FacturierReportViewSet.generate` ne lisait auparavant que les factures
livrées DU JOUR (date du serveur), sans aucun moyen de régénérer le rapport
d'un jour passé.

Même règle que pour la clôture (`core.utils.validate_requested_date`) :
- une date future est TOUJOURS refusée, quel que soit le réglage ;
- une date passée n'est acceptée que si `Config.allow_backdated_sales` est
  actif ;
- en l'absence de `date` dans le payload, comportement par défaut inchangé
  (date du jour).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice, InvoiceLine
from treasury.models import FacturierReport


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_delivered_invoice(node, facturier, team, client, bread, qty, payment_amount, delivered_at):
    inv = Invoice.objects.create(
        node=node, client=client, facturier=facturier, team=team,
        status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
        node_origin=node.code, debt_before=Decimal('0.00'),
    )
    InvoiceLine.objects.create(invoice=inv, bread_price=bread, quantity=qty)
    inv.compute_order_total()
    inv.payment_amount = payment_amount
    inv.compute_debt_after()
    inv.save()
    inv.deliver(livreur=facturier, delivered_at=delivered_at)
    return inv


class ReportDateRejectedWhenBackdatedSalesDisabledTests(TestCase):
    """(a) Réglage désactivé (comportement par défaut) → toute date de
    génération différente d'aujourd'hui est refusée."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086r_1')
        config = Config.get_instance()
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])
        self.api_gerant = _api_for(self.gerant)
        self.yesterday = date.today() - timedelta(days=1)

    def test_gerant_cannot_generate_report_for_a_past_date_when_setting_disabled(self):
        resp = self.api_gerant.post('/api/treasury/reports/generate/', {
            'date': str(self.yesterday),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.json())

    def test_today_still_works_when_setting_disabled(self):
        """Non-régression : générer le rapport du jour reste permis, même
        réglage désactivé — et sans `date` fourni, comportement inchangé."""
        facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_b086r_1')
        client_obj = make_client(self.node)
        bread = make_bread_price(category='MOYEN', label='Pain 300 FC B086R1', unit_price=300)
        _make_delivered_invoice(
            self.node, facA, 'A', client_obj, bread, 2, Decimal('600.00'),
            delivered_at=None,
        )
        resp = self.api_gerant.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)


class ReportFutureDateAlwaysRejectedTests(TestCase):
    """(b) Une date future est TOUJOURS refusée, même réglage activé."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086r_2')
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])
        self.api_gerant = _api_for(self.gerant)
        self.tomorrow = date.today() + timedelta(days=1)

    def test_future_report_date_rejected_even_with_setting_enabled(self):
        resp = self.api_gerant.post('/api/treasury/reports/generate/', {
            'date': str(self.tomorrow),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('future', resp.json().get('detail', '').lower())
        self.assertFalse(
            FacturierReport.objects.filter(node=self.node, date=self.tomorrow).exists()
        )


class ReportOnPastDateUsesThatDaysOwnInvoicesTests(TestCase):
    """(c) Réglage activé → la génération d'un rapport pour un jour passé
    reflète bien les factures livrées CE jour-là — un piège de données
    (factures livrées aujourd'hui, montants très différents) ne doit PAS
    contaminer le rapport du jour passé demandé."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_b086r_3')
        self.facA = make_user(role='FACTURIER', node=self.node, team='A', username='fact_b086r_3')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 FC B086R3', unit_price=300)

        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

        self.api_gerant = _api_for(self.gerant)
        self.past_day = date.today() - timedelta(days=5)
        self.past_delivered_at = date.today() - timedelta(days=5)

    def test_past_report_reflects_only_that_days_deliveries(self):
        from datetime import datetime, time
        from django.utils import timezone as djtz

        past_dt = djtz.make_aware(datetime.combine(self.past_day, time(10, 0)))
        today_dt = djtz.make_aware(datetime.combine(date.today(), time(10, 0)))

        # Facture livrée le jour PASSÉ (celle qu'on veut voir dans le rapport).
        _make_delivered_invoice(
            self.node, self.facA, 'A', self.client_obj, self.bread, 5, Decimal('1500.00'),
            delivered_at=past_dt,
        )
        # Piège : facture livrée AUJOURD'HUI, montant très différent — ne
        # doit PAS contaminer le rapport du jour passé demandé.
        _make_delivered_invoice(
            self.node, self.facA, 'A', self.client_obj, self.bread, 50, Decimal('99999.00'),
            delivered_at=today_dt,
        )

        resp = self.api_gerant.post('/api/treasury/reports/generate/', {
            'date': str(self.past_day),
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

        report = FacturierReport.objects.get(node=self.node, team='A', date=self.past_day)
        self.assertEqual(report.total_cash_sales, Decimal('1500.00'))
        self.assertEqual(report.theoretical_cash, Decimal('1500.00'))

        # Aucun rapport parasite créé pour aujourd'hui par cet appel.
        self.assertFalse(
            FacturierReport.objects.filter(node=self.node, team='A', date=date.today()).exists()
        )

    def test_invalid_date_format_is_rejected_cleanly(self):
        resp = self.api_gerant.post('/api/treasury/reports/generate/', {
            'date': 'not-a-date',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('detail', resp.json())
