"""
BUG-1130 (Q-018, réponse client 2026-11-24) : la journée comptable va de MIDI À
MIDI (heure de clôture `Node.handover_time`, 12:00 par défaut). Une vente à
D+1 09:00 appartient à la journée D. Données fictives.

Couvre : helper (`business_day_for`/`business_day_bounds`), verrou de vente et
`closure-status`, rapport facturier, `daily_summary`, ventes rétroactives,
clôture automatique des fournées, contrôle de dates de la synchronisation.
"""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_client, make_node, make_user
from core.workday import (
    business_day_bounds, business_day_for, closure_time_for, delivered_on_work_date_filter,
    instant_in_business_day, work_date_for,
)
from sales.models import Invoice
from treasury.closure_lock import closure_status, sales_blocked_for
from treasury.models import CashClosure, FacturierReport
from treasury.services import regenerate_facturier_reports

D = date(2026, 11, 24)
NEXT = D + timedelta(days=1)
PREV = D - timedelta(days=1)


def at(d, h, m=0, s=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m, s), timezone.get_current_timezone())


def clock(d, h, m=0):
    return patch('django.utils.timezone.now', return_value=at(d, h, m).astimezone(dt_timezone.utc))


def api(user):
    c = APIClient()
    c.raise_request_exception = False
    c.force_authenticate(user)
    return c


class HelperTests(TestCase):
    def setUp(self):
        self.node = make_node(code='KM1')

    def test_defaut_midi(self):
        self.assertEqual(closure_time_for(self.node), time(12, 0))
        self.assertEqual(closure_time_for(None), time(12, 0))

    def test_une_vente_du_matin_suivant_appartient_a_la_veille(self):
        self.assertEqual(business_day_for(self.node, at(NEXT, 9, 0)), D)
        self.assertEqual(business_day_for(self.node, at(NEXT, 11, 59, 59)), D)
        self.assertEqual(business_day_for(self.node, at(NEXT, 12, 0)), NEXT)
        self.assertEqual(business_day_for(self.node, at(D, 12, 0)), D)
        self.assertEqual(business_day_for(self.node, at(D, 23, 59)), D)
        self.assertEqual(business_day_for(self.node, at(NEXT, 0, 30)), D)  # après minuit : toujours D

    def test_work_date_for_suit_la_journee_comptable(self):
        self.assertEqual(work_date_for(self.node, at(NEXT, 3, 0)), D)
        self.assertEqual(work_date_for(None, at(NEXT, 3, 0)), D)  # siège : 12:00
        with clock(D, 8):
            self.assertEqual(work_date_for(self.node), PREV)

    def test_bornes(self):
        start, end = business_day_bounds(self.node, D)
        self.assertEqual((start, end), (at(D, 12), at(NEXT, 12)))
        filt = delivered_on_work_date_filter(self.node, D)
        self.assertEqual(filt, {'delivered_at__gte': start, 'delivered_at__lt': end})

    def test_heure_de_cloture_personnalisee(self):
        self.node.handover_time = time(6, 0)
        self.node.save()
        self.assertEqual(business_day_for(self.node, at(D, 5, 59)), PREV)
        self.assertEqual(business_day_for(self.node, at(D, 6, 0)), D)
        self.assertEqual(business_day_bounds(self.node, D), (at(D, 6), at(NEXT, 6)))

    def test_instant_retroactif_tombe_dans_la_journee_demandee(self):
        # À 09:00 le 25 (journée du 24), une vente « du 23 » doit tomber dans la journée du 23.
        with clock(NEXT, 9):
            inst = instant_in_business_day(self.node, PREV)
        self.assertEqual(business_day_for(self.node, inst), PREV)


class VenteEtVerrouTests(TestCase):
    def setUp(self):
        self.node = make_node(code='KM2')
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='km2_fa')
        self.bp = make_bread_price('KM2P', 'Pain 300', 300)
        self.client_ = make_client(self.node)

    def _deliver(self, instant):
        """Facture livrée à l'instant donné (insertion directe, journée comptable calculée comme la vue)."""
        inv = Invoice.objects.create(
            node=self.node, client=self.client_, facturier=self.fa, team='A',
            payment_type='CASH', payment_amount=Decimal('1000'), order_total=Decimal('1000'),
            status=Invoice.Status.DELIVERED, delivered_at=instant,
            invoice_date=work_date_for(self.node, instant), node_origin=self.node.code,
            receipt_number=f"KM2-{instant:%Y%m%d%H%M}",
        )
        return inv

    def test_rapport_facturier_regroupe_midi_a_midi(self):
        self._deliver(at(D, 13))        # journée D
        self._deliver(at(NEXT, 9))      # journée D aussi
        self._deliver(at(NEXT, 13))     # journée D+1
        reports_d = regenerate_facturier_reports(self.node, D)
        self.assertEqual(sum(r.total_cash_sales for r in reports_d), Decimal('2000'))
        reports_n = regenerate_facturier_reports(self.node, NEXT)
        self.assertEqual(sum(r.total_cash_sales for r in reports_n), Decimal('1000'))
        self.assertEqual(FacturierReport.objects.filter(node=self.node, date=D).count(), len(reports_d))

    def test_daily_summary_midi_a_midi(self):
        self._deliver(at(D, 13))
        self._deliver(at(NEXT, 9))
        self._deliver(at(NEXT, 13))
        with clock(NEXT, 14):
            r = api(self.fa).get('/api/sales/invoices/daily_summary/', {'date': D.isoformat()})
        self.assertEqual(r.status_code, 200)
        cash = [row['total'] for row in r.json() if row['payment_type'] == 'CASH' and row['node__code'] == 'KM2']
        self.assertEqual(Decimal(str(cash[0])), Decimal('2000'))

    def test_verrou_exige_la_cloture_de_la_journee_terminee(self):
        self.node.block_sales_after_closure = True
        self.node.save()
        # Journée D en cours (D 15:00) : la journée précédente doit être validée.
        self.assertTrue(sales_blocked_for(self.node, at(D, 15)))
        CashClosure.objects.create(node=self.node, date=PREV, is_validated=True, node_origin='KM2')
        self.assertFalse(sales_blocked_for(self.node, at(D, 15)))
        # Le lendemain matin (09:00) la journée courante est toujours D : pas de nouveau blocage.
        self.assertFalse(sales_blocked_for(self.node, at(NEXT, 9)))
        # À 12:00 le lendemain, la journée D se termine : sa clôture est exigée.
        self.assertTrue(sales_blocked_for(self.node, at(NEXT, 12)))
        st = closure_status(self.node, at(NEXT, 12))
        self.assertEqual(st['closure_date'], D.isoformat())
        self.assertEqual(st['closure_hour'], '12:00')
        CashClosure.objects.create(node=self.node, date=D, is_validated=True, node_origin='KM2')
        self.assertFalse(sales_blocked_for(self.node, at(NEXT, 12, 1)))

    def test_vente_a_9h_est_datee_de_la_veille(self):
        with clock(NEXT, 9):
            r = api(self.fa).post('/api/sales/invoices/', {
                'payment_type': 'CASH', 'payment_amount': 600, 'client': str(self.client_.pk),
                'lines': [{'bread_price': self.bp.pk, 'quantity': 2}],
            }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Invoice.objects.get(pk=r.json()['id']).invoice_date, D)


class ClotureDeLaJourneeTerminee(TestCase):
    """BUG-1130 : la journée D se termine à D+1 12:00 ; sa clôture se fait ensuite sans réglage
    « ventes passées » (sinon le verrou de vente et la clôture de la veille se bloqueraient)."""

    def setUp(self):
        self.node = make_node(code='KM3')
        self.node.block_sales_after_closure = True
        self.node.save()
        self.gerant = make_user('GERANT', node=self.node, username='km3_g')
        self.dirn = make_user('DIRECTION', node=None, username='km3_d')

    def _close(self, day):
        return api(self.gerant).post('/api/treasury/closures/', {'date': day.isoformat(), 'bills_50': 0}, format='json')

    def test_veille_acceptee_avant_veille_refusee_sans_reglage(self):
        with clock(NEXT, 13):  # journée comptable courante = NEXT, la journée D vient de se terminer
            self.assertEqual(self._close(D).status_code, 201)
            self.assertEqual(self._close(PREV).status_code, 400)

    def test_verrou_puis_cloture_de_la_veille_puis_deblocage(self):
        bp = make_bread_price('KM3P', 'Pain 300', 300)
        cli = make_client(self.node)
        fa = make_user('FACTURIER', node=self.node, team='A', username='km3_fa')
        body = {'payment_type': 'CREDIT', 'payment_amount': 0, 'client': str(cli.pk),
                'lines': [{'bread_price': bp.pk, 'quantity': 1}]}
        with clock(NEXT, 13):
            self.assertEqual(api(fa).post('/api/sales/invoices/', body, format='json').status_code, 403)
            r = self._close(D)
            self.assertEqual(r.status_code, 201, r.content)
            v = api(self.dirn).post(f"/api/treasury/closures/{r.json()['id']}/validate/", {}, format='json')
            self.assertEqual(v.status_code, 200, v.content)
            self.assertEqual(api(fa).post('/api/sales/invoices/', body, format='json').status_code, 201)
