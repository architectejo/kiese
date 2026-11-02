"""
Vérification indépendante — testeur-ventes — BUG-083 (« ventes passées »),
volet Ventes/Facturation uniquement (le volet Trésorerie — correction du
livre de caisse — est vérifié en parallèle par testeur-tresorerie).

Objectifs explicites de cette session de vérification (ne duplique pas les
tests déjà écrits par dev-backend dans `test_bug083_backdated_sales.py`,
mais les recoupe sous un angle légèrement différent) :

(a) Réglage désactivé : toute date différente d'aujourd'hui est refusée
    (400), y compris pour un rôle HQ (DIRECTION) — le réglage ne doit pas
    être contournable simplement en changeant de rôle.
(b) Une date future est TOUJOURS refusée, même réglage activé — le
    garde-fou le plus facile à oublier, testé explicitement ici pour
    `invoice_date` ET pour `delivered_at` dans le même test.
(c) Réglage activé : une facture ET sa livraison rétroactives fonctionnent
    de bout en bout, et les champs stockés correspondent EXACTEMENT aux
    dates demandées (pas la date du jour).
(d) Commission déjà verrouillée (`CommissionPeriod.is_closed=True`) touchée
    par une facture rétroactive : une `SystemNotification` est bien créée,
    et le montant de la commission déjà calculée (`net_payable`) n'a PAS
    changé.
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


class SettingDisabledAppliesEvenToHQRoleTests(TestCase):
    """(a) Le réglage désactivé bloque la date rétroactive même pour DIRECTION."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.direction_user = make_user('DIRECTION', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.direction_user)
        # Réglage explicitement désactivé (défaut, mais on le force pour être
        # certain qu'aucun état laissé par un autre test ne fausse celui-ci).
        config = Config.get_instance()
        config.allow_backdated_sales = False
        config.save(update_fields=['allow_backdated_sales'])

    def test_direction_role_cannot_bypass_disabled_setting(self):
        yesterday = date.today() - timedelta(days=1)
        payload = {
            'node': str(self.node.pk),
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(yesterday),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(
            resp.status_code, 400,
            f"Un rôle HQ (DIRECTION) ne doit pas pouvoir contourner "
            f"Config.allow_backdated_sales=False simplement par son rôle. Réponse : {resp.data}"
        )
        self.assertFalse(Invoice.objects.filter(invoice_date=yesterday).exists())

    def test_today_invoice_date_still_works_for_direction_when_disabled(self):
        """Contrôle négatif : le blocage ne doit pas être un blocage général du rôle."""
        payload = {
            'node': str(self.node.pk),
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)


class FutureDateAlwaysRefusedEvenWhenEnabledTests(TestCase):
    """(b) Garde-fou le plus facile à oublier : jamais de date future, réglage activé ou pas."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.facturier)
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def test_future_invoice_date_and_future_delivery_date_both_refused(self):
        tomorrow = date.today() + timedelta(days=1)

        # 1) Création avec invoice_date future -> refusée
        create_payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(tomorrow),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        create_resp = self.api.post('/api/sales/invoices/', create_payload, format='json')
        self.assertEqual(create_resp.status_code, 400, create_resp.data)
        self.assertFalse(Invoice.objects.filter(invoice_date=tomorrow).exists())

        # 2) Création valide (date du jour), puis livraison avec delivered_at
        #    future -> refusée également, et le statut reste PENDING.
        valid_payload = dict(create_payload, invoice_date=str(date.today()))
        valid_resp = self.api.post('/api/sales/invoices/', valid_payload, format='json')
        self.assertEqual(valid_resp.status_code, 201, valid_resp.data)
        invoice_id = valid_resp.data['id']

        deliver_resp = self.api.post(
            f'/api/sales/invoices/{invoice_id}/deliver/',
            {'delivered_at': str(tomorrow)}, format='json',
        )
        self.assertEqual(deliver_resp.status_code, 400, deliver_resp.data)
        invoice = Invoice.objects.get(pk=invoice_id)
        self.assertEqual(
            invoice.status, Invoice.Status.PENDING,
            "Une tentative de livraison à une date future refusée ne doit pas "
            "laisser la facture dans un état intermédiaire incohérent."
        )
        self.assertIsNone(invoice.delivered_at)


class BackdatedInvoiceAndDeliveryEndToEndTests(TestCase):
    """(c) Réglage activé : facture ET livraison rétroactives, champs exacts."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node)
        self.api = _api_for(self.facturier)
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def test_backdated_invoice_and_delivery_store_exact_requested_dates(self):
        invoice_day = date.today() - timedelta(days=7)
        delivery_day = date.today() - timedelta(days=3)  # différent de invoice_day

        create_payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(invoice_day),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        create_resp = self.api.post('/api/sales/invoices/', create_payload, format='json')
        self.assertEqual(create_resp.status_code, 201, create_resp.data)
        invoice_id = create_resp.data['id']

        invoice = Invoice.objects.get(pk=invoice_id)
        self.assertEqual(
            invoice.invoice_date, invoice_day,
            "La date stockée doit être exactement la date demandée, pas la date du jour."
        )
        self.assertNotEqual(invoice.invoice_date, date.today())

        deliver_resp = self.api.post(
            f'/api/sales/invoices/{invoice_id}/deliver/',
            {'delivered_at': str(delivery_day)}, format='json',
        )
        self.assertEqual(deliver_resp.status_code, 200, deliver_resp.data)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.DELIVERED)
        # `delivered_at` est un datetime aware stocké en UTC (USE_TZ=True) :
        # il faut le reconvertir à l'heure locale (Africa/Kinshasa) avant
        # d'en extraire la date calendaire. Un `.date()` nu sur un datetime
        # aware UTC donne la date UTC, qui retarde d'un jour sur la date
        # locale pendant la fenêtre minuit-1h locale (Kinshasa = UTC+1) —
        # ce n'est pas un défaut applicatif, `_combine_date_with_now_time`
        # construit déjà le datetime en heure locale.
        self.assertEqual(
            timezone.localtime(invoice.delivered_at).date(), delivery_day,
            "La date de livraison stockée doit être exactement la date demandée "
            "(distincte de invoice_date dans ce scénario), pas la date du jour."
        )
        self.assertEqual(invoice.invoice_date, invoice_day, "invoice_date ne doit pas être affecté par deliver().")


class RetroactiveInvoiceIntoLockedCommissionPeriodTests(TestCase):
    """
    (d) Scénario explicite : CommissionPeriod.is_closed=True avec une
    ClientCommission déjà calculée et marquée payée. Une facture rétroactive
    tombant dans cette période doit déclencher une SystemNotification et NE
    JAMAIS modifier net_payable déjà figé.
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

        today = date.today()
        year, month = today.year, today.month - 2
        while month <= 0:
            month += 12
            year -= 1
        self.period = CommissionPeriod.objects.create(node=self.node, month=month, year=year)
        self.invoice_date = date(year, month, 10)

        self.commission = ClientCommission.objects.create(
            period=self.period, client=self.client_obj,
            order_value=Decimal('20000.00'), commission_rate=Decimal('0.25'),
        )
        self.commission.compute()
        self.commission.save()
        self.commission.mark_paid(paid_by='Comptable Test BUG-083')
        self.period.close()
        self.net_payable_before = self.commission.net_payable

    def test_notification_created_and_commission_amount_unchanged(self):
        notif_count_before = SystemNotification.objects.count()

        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(self.invoice_date),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, f"Jamais bloquée — seulement avertie. Réponse : {resp.data}")

        self.assertGreater(
            SystemNotification.objects.count(), notif_count_before,
            "Une SystemNotification doit être créée pour une facture rétroactive "
            "tombant dans une période de commission déjà close."
        )

        self.commission.refresh_from_db()
        self.assertTrue(self.commission.is_paid, "La commission reste marquée payée.")
        self.assertEqual(
            self.commission.net_payable, self.net_payable_before,
            "Le montant de la commission déjà calculée/payée ne doit JAMAIS être "
            "recalculé silencieusement par l'ajout d'une facture rétroactive."
        )
        self.assertTrue(
            self.period.is_closed,
            "La période ne doit pas être rouverte automatiquement."
        )
