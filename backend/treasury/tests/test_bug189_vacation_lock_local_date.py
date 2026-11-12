"""
BUG-189 : le verrou de vacation BUG-036 (`treasury.signals`) comparait
`delivered_at.date()` (date UTC d'un datetime aware) à la date locale du
rapport : entre 00:00 et 01:00 à Kinshasa (UTC+1) il ne bloquait plus. Corrigé
par `core.workday.work_date_for` (date locale du calendrier, avec ou sans
rotation depuis la décision client du 2026-11-12, BUG-247).

Tests déterministes : l'horloge est simulée (`timezone.now`) à 00:30 locale
(= 23:30 UTC la veille), à midi, et en mode rotation à 03:00 / 13:00.
"""
from datetime import timezone as dt_timezone
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client, get_config
from sales.models import Invoice, InvoiceLine
from treasury.models import FacturierReport

D = date(2026, 11, 12)
PREV = date(2026, 11, 11)


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    # Comme `timezone.now()` réel : datetime aware en UTC (BUG-189 : `.date()` = date UTC).
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class VacationLockLocalDateTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.gerant = make_user('GERANT', node=self.node)
        self.fact = make_user('FACTURIER', node=self.node, team='A')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price('MOYEN', 'Pain 300 FC', 300)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _delivered_sale(self, invoice_date=None, team='A'):
        inv = Invoice.objects.create(
            node=self.node, client=self.client_obj, facturier=self.fact, team=team,
            status=Invoice.Status.PENDING, payment_type=Invoice.PaymentType.CASH,
            node_origin=self.node.code, debt_before=Decimal('0.00'),
            invoice_date=invoice_date or timezone.localdate(),
        )
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bread, quantity=5)
        inv.compute_order_total()
        inv.payment_amount = inv.order_total
        inv.compute_debt_after()
        inv.save()
        return inv

    def _generate(self):
        resp = self.api.post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def _assert_second_sale_blocked(self):
        first = self._delivered_sale()
        first.deliver(livreur=self.fact)
        self._generate()
        self.assertTrue(FacturierReport.objects.filter(node=self.node, team='A').exists())
        second = self._delivered_sale()
        with self.assertRaises(ValidationError):
            second.deliver(livreur=self.fact)

    def test_lock_blocks_second_sale_at_00_30_local(self):
        with _now(0, 30):
            self._assert_second_sale_blocked()
            # le rapport porte la date LOCALE (12/11), pas la date UTC (11/11)
            self.assertEqual(FacturierReport.objects.get(node=self.node).date, D)

    def test_lock_blocks_second_sale_at_noon(self):
        with _now(12, 0):
            self._assert_second_sale_blocked()

    def test_lock_blocks_second_sale_at_23_30_local(self):
        with _now(23, 30):
            self._assert_second_sale_blocked()

    def test_same_day_delivery_not_treated_as_backdated_at_00_30(self):
        """
        Avec `allow_backdated_sales` actif, une re-livraison du JOUR MÊME déjà
        rapportée reste bloquée : à 00:30 locale elle n'est pas « rétroactive »
        (avant le correctif, la date UTC la faisait passer pour passée).
        """
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        with _now(0, 30):
            self._assert_second_sale_blocked()

    def test_rotation_node_lock_uses_calendar_date(self):
        """
        BUG-247 : rotation (relève 12:00) : à 03:00 locale la date de travail est
        le jour CALENDAIRE (12/11) ; le rapport porte cette date, le verrou
        bloque la 2e livraison de l'équipe A ; à 13:00 la même date calendaire
        reste verrouillée pour A, mais l'équipe B (relève) livre librement :
        un rapport par (équipe, date), la relève ne change pas la date.
        """
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])
        with _now(3, 0):
            first = self._delivered_sale(invoice_date=D)
            first.deliver(livreur=self.fact)
            self._generate()
            report = FacturierReport.objects.get(node=self.node, team='A')
            self.assertEqual(report.date, D)
            second = self._delivered_sale(invoice_date=D)
            with self.assertRaises(ValidationError):
                second.deliver(livreur=self.fact)
        with _now(13, 0):
            third = self._delivered_sale(invoice_date=D, team='B')
            third.deliver(livreur=self.fact)  # équipe B : pas de rapport B pour le 12/11
            self.assertEqual(third.status, Invoice.Status.DELIVERED)

    def test_report_generation_groups_by_work_date_in_rotation(self):
        """BUG-247 : livraison à 03:00 locale (rotation) : comptée dans le jour calendaire (12/11)."""
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])
        with _now(3, 0):
            inv = self._delivered_sale(invoice_date=D)
            inv.deliver(livreur=self.fact)
        from treasury.services import regenerate_facturier_reports
        self.assertEqual(len(regenerate_facturier_reports(self.node, D)), 1)
        self.assertEqual(regenerate_facturier_reports(self.node, PREV), [])

    def test_report_generation_without_rotation_uses_local_calendar_day(self):
        """Hors rotation : livraison à 00:30 locale -> jour calendaire local (12/11), pas UTC."""
        with _now(0, 30):
            inv = self._delivered_sale()
            inv.deliver(livreur=self.fact)
        from treasury.services import regenerate_facturier_reports
        self.assertEqual(len(regenerate_facturier_reports(self.node, D)), 1)
        self.assertEqual(regenerate_facturier_reports(self.node, PREV), [])
