"""
BUG-247 (décision client 2026-11-12) puis BUG-1130 (décision client Q-018 du
2026-11-24, qui la REMPLACE) : le Rapport Journalier suit la JOURNÉE COMPTABLE de
midi à midi (heure de clôture du nœud, 12:00 par défaut), plus le jour calendaire.
UN SEUL rapport par boulangerie et par date de journée ; une vente à 03:00 est de
la journée de la veille ; minuit ne change rien (ni date, ni équipe, ni clôture).
Tests de datation et de passage de minuit adaptés en BUG-1130.
"""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyTeamAssignment, ProductionSession,
    ProductionSessionLine,
)
from production.views import _build_daily_closure_report
from sales.models import Invoice

D = date(2026, 11, 12)
PREV = date(2026, 11, 11)
INV = '/api/sales/invoices/'
CLOSURE = '/api/production/daily-closure/'
SHIFT = '/api/production/sessions/shift-end-status/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.node.team_rotation_enabled = True
        self.node.handover_time = time(12, 0)
        self.node.save()
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.facturier = make_user('FACTURIER', node=self.node, team='A')
        self.client_obj = make_client(self.node)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        self.fapi = APIClient()
        self.fapi.force_authenticate(self.facturier)
        # Période démarrée le 11/11 à 12:00 : A ; démarrée le 12/11 à 12:00 : B.
        DailyTeamAssignment.objects.create(node=self.node, work_date=PREV, team='A')
        DailyTeamAssignment.objects.create(node=self.node, work_date=D, team='B')

    def _session(self, team, qty, created, closed=True):
        s = ProductionSession.objects.create(
            node=self.node, team=team, date=D, declared_by=self.gerant, node_origin='K1',
            is_closed=closed,
        )
        ProductionSession.objects.filter(pk=s.pk).update(created_at=created)
        ProductionSessionLine.objects.create(session=s, bread_price=self.bp, quantity=qty)
        s.compute_totals(200000)
        s.save()
        return s

    def _snap(self, d, team, qty):
        return DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp, date=d, team=team, qty_at_close=qty,
        )

    def _sale(self, qty=1):
        payload = {
            'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': 500 * qty,
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }
        r = self.fapi.post(INV, payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return Invoice.objects.get(pk=r.data['id'])


class OneReportPerCalendarDayTests(_Base):
    def test_two_teams_same_calendar_date_one_consolidated_report(self):
        self._session('A', 10, _at(D, 2))     # équipe A (période du 11/11), après minuit
        self._session('B', 5, _at(D, 12, 30))  # équipe B (période du 12/11), après la relève
        self._snap(PREV, 'A', 7)
        a = self._snap(D, 'A', 3)              # reste de A à la relève
        b = self._snap(D, 'B', 4)              # reste de B en fin de journée (le plus récent)
        DailyBreadStockSnapshot.objects.filter(pk=a.pk).update(updated_at=_at(D, 12, 5))
        DailyBreadStockSnapshot.objects.filter(pk=b.pk).update(updated_at=_at(D, 23, 50))
        with _now(23, 55):
            r = self.api.get(CLOSURE, {'date': str(D)})
        self.assertEqual(r.status_code, 200, r.data)
        row = next(c for c in r.data['categories'] if c['bread_price'] == self.bp.pk)
        # Production des DEUX équipes dans le même rapport.
        self.assertEqual(row['produit']['quantity'], 15)
        self.assertEqual(r.data['date'], '2026-11-12')
        # Début de journée porté par l'équipe en service au début de la journée (BUG-1130 :
        # midi, relève du 12/11 = équipe B ; avant, à minuit : A), une seule fois.
        self.assertEqual(row['reste_du_hier'], {'A': 0, 'B': -7})
        # Fin de journée = dernier reste déclaré (B), pas la somme A + B ; le reste de
        # A à la relève est le départ de B (transfert interne, jamais additionné).
        self.assertEqual(row['reste_du_jour'], {'A': 3, 'B': 4})
        self.assertEqual(row['reste_du_jour_fin_journee'], 4)
        self.assertEqual(row['facture_mvm_interne']['fc'], str(Decimal(4 * 500 - 7 * 500)) + '.00')

    def test_confirmation_of_incoming_team_is_not_added_to_day_start(self):
        from production.models import DailyOpeningConfirmation, DailyOpeningConfirmationLine
        self._snap(PREV, 'A', 7)
        c = DailyOpeningConfirmation.objects.create(node=self.node, team='B', date=D, confirmed_by=self.gerant)
        DailyOpeningConfirmationLine.objects.create(confirmation=c, bread_price=self.bp, qty_confirmed=9)
        report = _build_daily_closure_report(self.node, D)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        # L'écart constaté par B (9 trouvés, 7 déclarés par A) est porté au départ de journée
        # (BUG-1130 : la journée du 12/11 démarre à 12:00 avec l'équipe B).
        self.assertEqual(row['reste_du_hier'], {'A': 0, 'B': -9})

    def test_node_without_rotation_keeps_per_team_sum(self):
        # CHANGEMENT DE SPECIFICATION VOULU (client, 2026-11-24, remarque.md
        # l.516, BUG-1073 / BUG-1202) : « les Reste d'Hier comme les Reste du
        # Jour sont pour toute la journee et ne dependent pas des equipes ».
        # Hors rotation, deux equipes ayant cloture le meme jour donnent UN SEUL
        # reste de journee (le dernier declare, ici l'equipe B = 4), et non plus
        # la somme par equipe (A3 + B4 = 3 500 FC). Le detail par equipe reste
        # expose (assertion inchangee) ; seul le montant FACTURE MVM INTERNE
        # change : 4 x 500 = 2 000 FC. Nom du test conserve pour la tracabilite.
        plain = make_node(code='K9')
        DailyBreadStockSnapshot.objects.create(node=plain, bread_price=self.bp, date=D, team='A', qty_at_close=3)
        DailyBreadStockSnapshot.objects.create(node=plain, bread_price=self.bp, date=D, team='B', qty_at_close=4)
        report = _build_daily_closure_report(plain, D)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        self.assertNotIn('reste_du_jour_fin_journee', row)
        self.assertEqual(row['reste_du_jour'], {'A': 3, 'B': 4})
        self.assertEqual(row['reste_du_jour_jour'], 4)
        self.assertEqual(row['facture_mvm_interne']['fc'], '2000.00')  # dernier reste de la journee : 4 x 500


class CalendarDatingTests(_Base):
    """Nom de classe conservé pour la traçabilité (BUG-247) ; règle BUG-1130 : midi à midi."""

    def test_sale_at_03_00_is_dated_previous_business_day(self):
        with _now(3, 0):
            inv = self._sale()
        self.assertEqual(inv.invoice_date, PREV)  # BUG-1130 : 03:00 = journée de la veille
        self.assertEqual(inv.team, 'A')  # équipe de la période démarrée le 11/11

    def test_team_and_report_date_change_together_at_noon(self):
        with _now(11, 59):
            before = self._sale()
        with _now(12, 0):
            after = self._sale()
        self.assertEqual((before.invoice_date, before.team), (PREV, 'A'))
        self.assertEqual((after.invoice_date, after.team), (D, 'B'))
        self.assertNotEqual(before.receipt_number[:12], after.receipt_number[:12])

    def test_window_midnight_to_one_o_clock_local_date(self):
        # 00:30 locale = 23:30 UTC la veille : jamais la date UTC ; journée comptable du 11/11.
        with _now(0, 30):
            inv = self._sale()
        self.assertEqual(inv.invoice_date, PREV)
        self.assertEqual(inv.team, 'A')

    def test_sales_across_midnight_land_in_one_report(self):
        # BUG-1130 : une vente à 13:00 et une vente à 03:00 le lendemain sont dans le même rapport.
        with _now(13, 0, PREV):
            a = self._sale(qty=2)
        with _now(3, 0):
            b = self._sale(qty=3)
        for inv in (a, b):
            Invoice.objects.filter(pk=inv.pk).update(status=Invoice.Status.DELIVERED, delivered_at=inv.created_at)
        report = _build_daily_closure_report(self.node, PREV)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(row['facture_jr']['quantity'], 5)
        self.assertEqual(row['facture_jr']['fc'], '2500.00')


class SingleReportAcrossMidnightTests(_Base):
    def test_midnight_closes_nothing_handover_closes_the_day(self):
        # BUG-1130 : plus de clôture silencieuse à minuit ; la journée (et la fournée) se
        # termine à l'heure de clôture (relève de 12:00).
        s = self._session('A', 10, _at(PREV, 14), closed=False)
        ProductionSession.objects.filter(pk=s.pk).update(date=PREV)
        BreadStock.objects.filter(node=self.node).delete()
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_produced=10, qty_disposed=4)
        with _now(0, 10):
            r = self.api.get(SHIFT, {'node': 'K1'})
        self.assertFalse(r.data.get('auto_closed'))
        self.assertTrue(ProductionSession.objects.filter(pk=s.pk, is_closed=False).exists())
        self.assertFalse(DailyBreadStockSnapshot.objects.filter(node=self.node, date=PREV, team='A').exists())
        # Après la relève et le délai de grâce : clôture forcée, reste du jour enregistré.
        with _now(12, 40):
            r = self.api.get(SHIFT, {'node': 'K1'})
        self.assertTrue(r.data['auto_closed'])
        self.assertEqual(
            DailyBreadStockSnapshot.objects.get(node=self.node, date=PREV, team='A').qty_at_close, 6)
