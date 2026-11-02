"""
BUG-083 (« ventes passées », remarque.md l.360) : saisie d'une date
antérieure pour `invoice_date` (facturation) et `delivered_at` (livraison).

Décisions client actées le 2026-10-29 (docs/qa/REGISTRE_BUGS.md) :
1. Désactivé par défaut (`Config.allow_backdated_sales=False`).
2. S'applique à `invoice_date` ET `delivered_at`. Jamais de date future,
   quel que soit le réglage.
3. Facture rétroactive dans une `CommissionPeriod` déjà close/payée :
   AUTORISÉE, mais avertit (notification) — jamais de recalcul silencieux.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Config, SystemNotification
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice
from commissions.models import CommissionPeriod, ClientCommission


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class BackdatedInvoiceDateDisabledByDefaultTests(TestCase):
    """Comportement par défaut (réglage désactivé) strictement inchangé."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.facturier)

    def test_omitting_invoice_date_still_defaults_to_today(self):
        """Non-régression : aucun `invoice_date` fourni -> date du jour, comme avant ce ticket."""
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(invoice.invoice_date, date.today())

    def test_backdated_invoice_date_refused_when_setting_disabled(self):
        yesterday = date.today() - timedelta(days=1)
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(yesterday),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertFalse(Invoice.objects.filter(invoice_date=yesterday).exists())

    def test_future_invoice_date_always_refused_even_with_setting_disabled(self):
        tomorrow = date.today() + timedelta(days=1)
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(tomorrow),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)


class BackdatedInvoiceDateEnabledTests(TestCase):
    """Réglage activé : date antérieure acceptée (mais jamais future)."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.facturier)
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def _payload(self, invoice_date=None):
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        if invoice_date is not None:
            payload['invoice_date'] = str(invoice_date)
        return payload

    def test_backdated_invoice_date_accepted(self):
        past = date.today() - timedelta(days=10)
        resp = self.api.post('/api/sales/invoices/', self._payload(past), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(invoice.invoice_date, past)

    def test_future_invoice_date_still_refused_even_with_setting_enabled(self):
        """Décision client §2 : jamais de date future, quel que soit le réglage."""
        tomorrow = date.today() + timedelta(days=1)
        resp = self.api.post('/api/sales/invoices/', self._payload(tomorrow), format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertFalse(Invoice.objects.filter(invoice_date=tomorrow).exists())

    def test_backdated_delivery_date_accepted_on_deliver_action(self):
        """`delivered_at` suit la même règle que `invoice_date` (décision client §2)."""
        past = date.today() - timedelta(days=5)
        create_resp = self.api.post('/api/sales/invoices/', self._payload(past), format='json')
        self.assertEqual(create_resp.status_code, 201, create_resp.data)
        invoice_id = create_resp.data['id']

        deliver_resp = self.api.post(
            f'/api/sales/invoices/{invoice_id}/deliver/', {'delivered_at': str(past)}, format='json'
        )
        self.assertEqual(deliver_resp.status_code, 200, deliver_resp.data)
        invoice = Invoice.objects.get(pk=invoice_id)
        self.assertEqual(invoice.status, Invoice.Status.DELIVERED)
        # `delivered_at` est stocké en UTC (USE_TZ=True) : il faut le
        # convertir à l'heure locale (Africa/Kinshasa) avant d'en extraire la
        # date calendaire, sinon la comparaison est fausse d'un jour pendant
        # la fenêtre où la date UTC est encore en retard sur la date locale
        # (entre minuit et 1h locales, Kinshasa = UTC+1). Appeler `.date()`
        # directement sur un datetime aware UTC n'est PAS un défaut
        # applicatif : `Invoice.deliver()`/`_combine_date_with_now_time`
        # construisent bien le datetime attendu en heure locale.
        self.assertEqual(timezone.localtime(invoice.delivered_at).date(), past)

    def test_future_delivery_date_refused_on_deliver_action(self):
        create_resp = self.api.post('/api/sales/invoices/', self._payload(), format='json')
        invoice_id = create_resp.data['id']
        tomorrow = date.today() + timedelta(days=1)
        deliver_resp = self.api.post(
            f'/api/sales/invoices/{invoice_id}/deliver/', {'delivered_at': str(tomorrow)}, format='json'
        )
        self.assertEqual(deliver_resp.status_code, 400, deliver_resp.data)
        invoice = Invoice.objects.get(pk=invoice_id)
        self.assertEqual(invoice.status, Invoice.Status.PENDING)

    def test_omitting_delivered_at_keeps_default_now_behaviour(self):
        """Non-régression : `deliver()` sans `delivered_at` reste horodaté à maintenant."""
        create_resp = self.api.post('/api/sales/invoices/', self._payload(), format='json')
        invoice_id = create_resp.data['id']
        deliver_resp = self.api.post(f'/api/sales/invoices/{invoice_id}/deliver/', {}, format='json')
        self.assertEqual(deliver_resp.status_code, 200, deliver_resp.data)
        invoice = Invoice.objects.get(pk=invoice_id)
        self.assertEqual(timezone.localtime(invoice.delivered_at).date(), date.today())


class CommissionPeriodLockedWarningTests(TestCase):
    """
    Décision client §3 : une facture rétroactive tombant dans une
    `CommissionPeriod` déjà close (ou avec une commission déjà payée pour ce
    client) doit être AUTORISÉE, avertir la Direction/le Comptable, et ne
    JAMAIS recalculer silencieusement la commission déjà figée.
    """

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.facturier)
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def _closed_period_in_the_past(self, months_ago=2):
        today = date.today()
        year, month = today.year, today.month - months_ago
        while month <= 0:
            month += 12
            year -= 1
        period = CommissionPeriod.objects.create(node=self.node, month=month, year=year)
        period.close()
        return period, date(year, month, 15)

    def test_backdated_invoice_into_closed_period_is_allowed_and_warns(self):
        period, invoice_date = self._closed_period_in_the_past()
        notif_count_before = SystemNotification.objects.count()

        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(invoice_date),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)  # jamais bloqué

        self.assertGreater(
            SystemNotification.objects.count(), notif_count_before,
            "Une notification doit être créée quand une vente rétroactive tombe dans "
            "une période de commission déjà close."
        )
        period.refresh_from_db()
        self.assertTrue(period.is_closed)  # jamais rouverte silencieusement

    def test_already_paid_commission_is_never_recomputed_silently(self):
        period, invoice_date = self._closed_period_in_the_past()
        commission = ClientCommission.objects.create(
            period=period, client=self.client_obj,
            order_value=Decimal('10000.00'), commission_rate=Decimal('0.25'),
        )
        commission.compute()
        commission.save()
        commission.mark_paid(paid_by='Comptable Test')
        net_payable_before = commission.net_payable

        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(invoice_date),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        commission.refresh_from_db()
        self.assertTrue(commission.is_paid)
        self.assertEqual(commission.net_payable, net_payable_before)

        danger_notifs = SystemNotification.objects.filter(severity='DANGER')
        self.assertTrue(
            danger_notifs.exists(),
            "Une commission déjà payée touchée par une vente rétroactive doit déclencher "
            "une alerte explicite (sévérité DANGER)."
        )
