"""
Vérification indépendante (testeur-clients-commissions) du volet
Clients/Commissions de BUG-083 (« ventes passées », remarque.md l.360).

Objet : `sales.views._warn_if_commission_period_locked`, appelée à la
création d'une facture (`InvoiceViewSet._create_once`) quand
`invoice_date` est rétroactive (`Config.allow_backdated_sales=True`).

Décision client (docs/qa/REGISTRE_BUGS.md, fiche BUG-083, point 3) :
une vente rétroactive tombant dans une `CommissionPeriod` déjà `is_closed`
doit être AUTORISÉE, mais le système doit AVERTIR — jamais recalculer
silencieusement une commission déjà figée/payée.

Ces tests sont écrits indépendamment de
`sales/tests/test_bug083_backdated_sales.py::CommissionPeriodLockedWarningTests`
(déjà présents, écrits par dev-backend) : ils couvrent explicitement le cas
« période encore ouverte » (absent de la suite de dev-backend), vérifient le
contenu exploitable du message de notification, et confirment par
`refresh_from_db()` qu'aucun champ calculé de `ClientCommission` ne bouge
dans les deux cas verrouillés (non payé / déjà payé).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config, SystemNotification
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice
from commissions.models import CommissionPeriod, ClientCommission


def _api_for(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


class Bug083CommissionWarningVerificationTests(TestCase):
    """Vérification indépendante des 3 scénarios demandés par le coordinateur."""

    def setUp(self):
        self.node = make_node(code='K3')
        self.bp = make_bread_price('MOYEN', 'Pain Vérif 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.client_obj = make_client(self.node, first_name='Bug083Verif')
        self.api = _api_for(self.facturier)
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def _period_two_months_ago(self):
        today = date.today()
        year, month = today.year, today.month - 2
        while month <= 0:
            month += 12
            year -= 1
        return year, month, date(year, month, 10)

    def _post_backdated_invoice(self, invoice_date):
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': '500.00',
            'invoice_date': str(invoice_date),
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
        }
        return self.api.post('/api/sales/invoices/', payload, format='json')

    # (a) Période encore OUVERTE : aucune notification de ce type attendue.
    def test_a_open_period_triggers_no_warning_notification(self):
        year, month, invoice_date = self._period_two_months_ago()
        period = CommissionPeriod.objects.create(node=self.node, month=month, year=year)
        self.assertFalse(period.is_closed)

        before_ids = set(SystemNotification.objects.values_list('pk', flat=True))

        resp = self._post_backdated_invoice(invoice_date)
        self.assertEqual(resp.status_code, 201, resp.data)

        new_notifs = SystemNotification.objects.exclude(pk__in=before_ids)
        locked_warnings = new_notifs.filter(title__icontains='période close')
        self.assertEqual(
            locked_warnings.count(), 0,
            "Une période de commission encore OUVERTE ne doit déclencher aucune "
            "notification « période close » — c'est le cas normal, pas une anomalie."
        )
        period.refresh_from_db()
        self.assertFalse(period.is_closed)

    # (b) Période CLOSE, commission NON payée : WARNING, montant inchangé.
    def test_b_closed_but_unpaid_period_warns_and_leaves_commission_untouched(self):
        year, month, invoice_date = self._period_two_months_ago()
        period = CommissionPeriod.objects.create(node=self.node, month=month, year=year)
        period.close()

        commission = ClientCommission.objects.create(
            period=period, client=self.client_obj,
            total_breads=100, order_value=Decimal('20000.00'), commission_rate=Decimal('0.25'),
            deduction_debt=Decimal('1000.00'), deduction_social=Decimal('500.00'),
        )
        commission.compute()
        commission.save()
        self.assertFalse(commission.is_paid)
        net_payable_before = commission.net_payable
        total_cm_before = commission.commission_gross

        before_ids = set(SystemNotification.objects.values_list('pk', flat=True))
        resp = self._post_backdated_invoice(invoice_date)
        self.assertEqual(resp.status_code, 201, resp.data)

        new_notifs = list(SystemNotification.objects.exclude(pk__in=before_ids).filter(
            title__icontains='période close'
        ))
        self.assertEqual(len(new_notifs), 1, new_notifs)
        notif = new_notifs[0]
        self.assertEqual(notif.severity, 'WARNING')

        # Contenu exploitable : client, facture, période identifiables dans le message.
        self.assertIn(self.client_obj.full_name, notif.title)
        self.assertIn(f"{month:02d}/{year}", notif.message)
        self.assertIn(self.node.code, notif.message)
        invoice = Invoice.objects.get(invoice_date=invoice_date, client=self.client_obj)
        self.assertIn(invoice.receipt_number, notif.message)
        # Pas de mention erronée de paiement déjà effectué pour ce cas non payé.
        self.assertNotIn('PAYÉE', notif.message)

        commission.refresh_from_db()
        self.assertFalse(commission.is_paid)
        self.assertEqual(commission.net_payable, net_payable_before)
        self.assertEqual(commission.commission_gross, total_cm_before)

    # (c) Période CLOSE, commission DÉJÀ PAYÉE : DANGER, montant payé inchangé.
    def test_c_closed_and_paid_commission_raises_danger_and_stays_unchanged(self):
        year, month, invoice_date = self._period_two_months_ago()
        period = CommissionPeriod.objects.create(node=self.node, month=month, year=year)
        period.close()

        commission = ClientCommission.objects.create(
            period=period, client=self.client_obj,
            total_breads=200, order_value=Decimal('40000.00'), commission_rate=Decimal('0.30'),
            deduction_debt=Decimal('0.00'), deduction_social=Decimal('0.00'),
        )
        commission.compute()
        commission.save()
        commission.mark_paid(paid_by='Comptable Vérif')
        net_payable_before = commission.net_payable
        paid_at_before = commission.paid_at

        before_ids = set(SystemNotification.objects.values_list('pk', flat=True))
        resp = self._post_backdated_invoice(invoice_date)
        self.assertEqual(resp.status_code, 201, resp.data)

        new_notifs = list(SystemNotification.objects.exclude(pk__in=before_ids).filter(
            title__icontains='période close'
        ))
        self.assertEqual(len(new_notifs), 1, new_notifs)
        notif = new_notifs[0]
        self.assertEqual(
            notif.severity, 'DANGER',
            "Une commission déjà PAYÉE doit déclencher une sévérité strictement plus "
            "élevée (DANGER) qu'une période close mais non payée (WARNING)."
        )
        self.assertIn('PAYÉE', notif.message)
        self.assertIn(self.client_obj.full_name, notif.title)
        self.assertIn(f"{month:02d}/{year}", notif.message)

        commission.refresh_from_db()
        self.assertTrue(commission.is_paid)
        self.assertEqual(commission.net_payable, net_payable_before)
        self.assertEqual(commission.paid_at, paid_at_before)

    # Pas de création implicite de `ClientCommission` par le simple avertissement.
    def test_warning_never_creates_a_clientcommission_row_itself(self):
        year, month, invoice_date = self._period_two_months_ago()
        period = CommissionPeriod.objects.create(node=self.node, month=month, year=year)
        period.close()
        self.assertFalse(ClientCommission.objects.filter(period=period, client=self.client_obj).exists())

        resp = self._post_backdated_invoice(invoice_date)
        self.assertEqual(resp.status_code, 201, resp.data)

        self.assertFalse(
            ClientCommission.objects.filter(period=period, client=self.client_obj).exists(),
            "L'avertissement ne doit jamais créer de `ClientCommission` lui-même — "
            "seule une régénération manuelle explicite de la période "
            "(`CommissionPeriodViewSet.generate`) doit produire cette ligne."
        )
        self.assertTrue(
            SystemNotification.objects.filter(title__icontains='période close').exists()
        )
