"""
Vérification indépendante (testeur-production, 2026-11-20) de BUG-319 (volet
backend : « Stock Pains du Jour » = vendus seuls en cours de journée, produit
DÉRIVÉ à la clôture) et de BUG-322 (notation scientifique géante).

Valeurs calculées à la main. Données entièrement fictives (`core.testing`).
Aucune modification du code applicatif.

Formule vérifiée (hypothèses R1 à R5 du registre) :
    produit = vendus + reste du jour - reste d'hier
              + soldés/déclassés/invendus/gratuits + envoyés - reçus
"""
import time
from contextlib import contextmanager
from datetime import date, datetime, time as dtime
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price, make_client
from core.workday import work_date_for
from production.models import (
    BreadDisposal, BreadStock, BreadTransfer, DailyBreadStockSnapshot,
    DailyOpeningConfirmation, DailyOpeningConfirmationLine, ProductionSession,
    ProductionSessionLine, _adjust_bread_stock,
)

D1 = date(2026, 10, 14)
D2 = date(2026, 10, 15)
D3 = date(2026, 10, 16)


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _aware(d, hour=11, minute=0):
    return timezone.make_aware(
        datetime(d.year, d.month, d.day, hour, minute), timezone.get_current_timezone(),
    )


@contextmanager
def at(d, hour=11, minute=0):
    """Horloge figée à `d` heure:minute (jour de travail = jour calendaire hors rotation)."""
    with patch('django.utils.timezone.now', return_value=_aware(d, hour, minute)):
        yield


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', sac_value_fc=Decimal('210000'))
        self.k2 = make_node(code='K2', sac_value_fc=Decimal('210000'))
        self.gerant = make_user('GERANT', node=self.node)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.gerant2 = make_user('GERANT', node=self.k2)
        self.facturier2 = make_user('FACTURIER', node=self.k2)
        self.bp5 = make_bread_price('V319T_500', 'Pain 500 V319T', 500)
        self.bp3 = make_bread_price('V319T_300', 'Pain 300 V319T', 300)
        self.bp10 = make_bread_price('V319T_1000', 'Pain 1000 V319T', 1000)
        self.g = _api(self.gerant)
        self.f = _api(self.facturier)
        self.g2 = _api(self.gerant2)
        self.f2 = _api(self.facturier2)
        self.today = work_date_for(self.node)

    # -- helpers ------------------------------------------------------------
    def sacs(self, sacs='2.00', team='A', d=None, api=None):
        r = (api or self.g).post('/api/production/sessions/', {
            'team': team, 'date': str(d or self.today), 'flour_sacks_used': sacs,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def invoice(self, lines, api=None, extra=None):
        p = {'payment_type': 'CASH',
             'payment_amount': str(sum(bp.unit_price * q for bp, q in lines)),
             'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines]}
        p.update(extra or {})
        r = (api or self.f).post('/api/sales/invoices/', p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def sell(self, lines, api=None):
        iid = self.invoice(lines, api)
        d = (api or self.f).post(f'/api/sales/invoices/{iid}/deliver/')
        self.assertEqual(d.status_code, 200, d.data)
        return iid

    def close(self, sid, remaining=None, api=None):
        body = {} if remaining is None else {
            'remaining': [{'bread_price': b.pk, 'quantity': q} for b, q in remaining]}
        r = (api or self.g).post(f'/api/production/sessions/{sid}/close/', body, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def by_date(self, d=None, node='K1', api=None):
        params = {'node': node}
        if d:
            params['date'] = str(d)
        r = (api or self.g).get('/api/production/bread-stocks/by-date/', params)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def cat(self, data, bp):
        for c in data['categories']:
            if c['bread_price'] == bp.pk:
                return c
        return None

    def confirm_opening(self, qty_by_bp, d=None, team='A', node=None):
        conf = DailyOpeningConfirmation.objects.create(
            node=node or self.node, team=team, date=d or self.today, confirmed_by=self.gerant)
        for bp, q in qty_by_bp:
            DailyOpeningConfirmationLine.objects.create(confirmation=conf, bread_price=bp, qty_confirmed=q)
        return conf

    def report(self, d=None, node='K1'):
        r = self.g.get('/api/production/daily-closure/', {'node': node, 'date': str(d or self.today)})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def transfer(self, to_api, from_api, from_node, bp, sent, received=None):
        """K(to) demande à K(from) ; from répond ; to confirme (received défaut = sent)."""
        c = to_api.post('/api/production/transfers/', {
            'from_node': from_node.pk, 'lines': [{'bread_price': bp.pk, 'quantity_sent': sent}],
        }, format='json')
        self.assertEqual(c.status_code, 201, c.data)
        tid = c.data['id']
        # BUG-652 : la réponse positive exige le stock (comme send/) ; on complète le déficit éventuel.
        _bs = BreadStock.objects.filter(node=from_node, bread_price=bp).first()
        _dispo = _bs.qty_available if _bs else 0
        if _dispo < sent:
            _adjust_bread_stock(from_node, bp, produced=sent - _dispo)
        r = from_api.post(f'/api/production/transfers/{tid}/respond_to_request/', {
            'approved': True, 'lines': [{'bread_price': bp.pk, 'quantity_sent': sent}],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        k = to_api.post(f'/api/production/transfers/{tid}/confirm_reception/', {
            'lines': [{'bread_price': bp.pk, 'quantity_received': sent if received is None else received}],
        }, format='json')
        self.assertEqual(k.status_code, 200, k.data)
        return k.data


# ---------------------------------------------------------------------------
# 1. En cours de journée : « vendus » seuls
# ---------------------------------------------------------------------------
class EnCoursDeJourneeTests(_Base):
    def test_only_sold_counted_and_nothing_produced(self):
        sid = self.sacs('1.50')  # objectif 315 000 FC
        self.sell([(self.bp5, 40)])
        # livraison partielle : 20 commandés, 12 servis
        iid = self.invoice([(self.bp5, 20)])
        line_id = self.f.get(f'/api/sales/invoices/{iid}/').data['lines'][0]['id']
        d = self.f.post(f'/api/sales/invoices/{iid}/deliver/', {'lines': [{'id': line_id, 'quantity': 12}]}, format='json')
        self.assertEqual(d.status_code, 200, d.data)
        # en attente : non comptée
        self.invoice([(self.bp3, 10)])
        # NS : créée mais non livrable
        ns = self.f.post('/api/sales/invoices/', {
            'payment_type': 'CREDIT', 'payment_amount': '0', 'special_code': 'NS',
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 9}]}, format='json')
        self.assertEqual(ns.status_code, 201, ns.data)
        # remboursement : sans ligne
        cl = make_client(self.node)
        rb = self.f.post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': '1000', 'is_debt_repayment': True,
            'client': str(cl.pk), 'lines': []}, format='json')
        self.assertEqual(rb.status_code, 201, rb.data)
        # NOT_SERVED
        nid = self.invoice([(self.bp5, 7)])
        m = self.f.post(f'/api/sales/invoices/{nid}/mark-not-served/', {'reason': 'x'}, format='json')
        self.assertIn(m.status_code, (200, 201), m.data)

        data = self.by_date()
        self.assertFalse(data['closed'])
        self.assertEqual(data['source'], 'live')
        self.assertEqual(self.cat(data, self.bp5)['sold_qty'], 52)  # 40 + 12
        c3 = self.cat(data, self.bp3)
        self.assertTrue(c3 is None or c3['sold_qty'] == 0)
        for c in data['categories']:
            self.assertIsNone(c['remaining_qty'])
            self.assertIsNone(c['produced_total'])
            self.assertFalse(c['closed'])
            self.assertIn('qty_available', c)
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.delivered_value_fc, 26000)  # 52 x 500
        self.assertEqual((s.total_fc_produced, s.total_breads, s.yield_gap), (0, 0, 0))
        self.assertFalse(s.lines.filter(source='DECLARED').exists())
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp5).qty_produced, 0)

    def test_progress_bar_unchanged_delivered_value(self):
        sid = self.sacs('1.50')
        self.sell([(self.bp5, 52), (self.bp3, 10)])  # 26 000 + 3 000
        got = self.g.get(f'/api/production/sessions/{sid}/').data
        self.assertEqual(got['objective_fc'], 315000)
        self.assertEqual(got['progress_value_fc'], 29000)
        self.assertEqual(got['progress_pct'], '9.21')  # 29000*100/315000 = 9.2063
        self.assertEqual(got['total_fc_produced'], 0)
        self.assertEqual(got['yield_gap'], 0)
        lst = self.g.get('/api/production/sessions/').data
        lst = lst['results'] if isinstance(lst, dict) else lst
        row = next(x for x in lst if x['id'] == sid)
        self.assertEqual(row['progress_value_fc'], 29000)

    def test_bread_stocks_list_contract(self):
        self.sacs()
        self.sell([(self.bp5, 25)])
        r = self.g.get('/api/production/bread-stocks/')
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        row = next(x for x in rows if x['bread_price'] == self.bp5.pk)
        self.assertEqual(row['sold_qty'], 25)
        self.assertIsNone(row['remaining_qty'])
        self.assertIsNone(row['produced_total'])
        self.assertFalse(row['closed'])
        for key in ('qty_produced', 'qty_received', 'qty_sent', 'qty_disposed', 'qty_adjusted', 'qty_available'):
            self.assertIn(key, row)

    def test_daily_closure_contract_before_closure(self):
        self.sacs()
        self.sell([(self.bp5, 25)])
        rep = self.report()
        c = next(x for x in rep['categories'] if x['bread_price'] == self.bp5.pk)
        self.assertEqual(c['vendu_jour']['quantity'], 25)
        self.assertEqual(c['produit']['quantity'], 0)
        self.assertEqual(c['produit']['fc'], '0.00')
        self.assertEqual(c['produit_derive'], {'derived': True, 'closed': False})
        self.assertEqual(Decimal(str(rep['totals']['ecart_production_fc'])), 0)

    def test_no_session_means_nothing_derived_and_unchanged_contract(self):
        self.sell([(self.bp5, 5)])
        rep = self.report()
        c = next(x for x in rep['categories'] if x['bread_price'] == self.bp5.pk)
        self.assertEqual(c['produit_derive'], {'derived': False, 'closed': False})
        self.assertEqual(c['vendu_jour']['quantity'], 5)
        self.assertEqual(c['produit']['quantity'], 0)

    def test_by_date_is_idempotent_read(self):
        self.sacs()
        self.sell([(self.bp5, 25)])
        a, b, c = self.by_date(), self.by_date(), self.by_date(self.today)
        for x in (a, b, c):
            x.pop('server_now', None)
        self.assertEqual(a, b)
        self.assertEqual(c, a)

    def test_future_date_refused_past_date_without_data_is_empty(self):
        r = self.g.get('/api/production/bread-stocks/by-date/', {'node': 'K1', 'date': '2999-01-01'})
        self.assertEqual(r.status_code, 400)
        data = self.by_date(date(2026, 1, 5))
        self.assertFalse(data['closed'])
        for c in data['categories']:
            self.assertEqual(c['sold_qty'], 0)
            self.assertIsNone(c['produced_total'])


# ---------------------------------------------------------------------------
# 2. Clôture : produit dérivé, écart, R1 à R5
# ---------------------------------------------------------------------------
class ClotureDeriveeTests(_Base):
    def test_all_rules_combined_r1_to_r5(self):
        sid = self.sacs('2.00')  # 420 000
        r = self.g.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': str(self.today), 'lines': [{'bread_price': self.bp5.pk, 'qty': 12}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)                 # R1 : -12 (lignes CARRYOVER)
        self.sell([(self.bp5, 60)])                                   # vendus 60
        for t, q in (('UNSOLD', 2), ('DECLASSED', 1), ('FREE_DIST', 3)):  # R5 : +6 via l'API
            r = self.g.post('/api/production/disposals/', {
                'session': sid, 'bread_price': self.bp5.pk, 'disposal_type': t, 'quantity': q}, format='json')
            self.assertEqual(r.status_code, 201, r.data)
        # « soldé » : l'API de Production le refuse (BUG : vente soldée via Facturation) -> ORM, +4
        BreadDisposal.objects.create(
            session=ProductionSession.objects.get(pk=sid), bread_price=self.bp5, disposal_type='SOLD_DISCOUNT',
            quantity=4, unit_price_sold=400, node=self.node, node_origin='K1')
        _adjust_bread_stock(self.k2, self.bp5, produced=50)
        _adjust_bread_stock(self.node, self.bp5, produced=50)
        self.transfer(self.g2, self.g, self.node, self.bp5, 5)       # K1 -> K2 : envoyés +5 (R2)
        self.transfer(self.g, self.g2, self.k2, self.bp5, 9)         # K2 -> K1 : reçus -9 (R2)
        out = self.close(sid, [(self.bp5, 7)])                       # reste du jour 7
        # 60 + 7 - 12 + 10 + 5 - 9 = 61
        c = self.cat(self.by_date(), self.bp5)
        self.assertEqual((c['sold_qty'], c['remaining_qty'], c['produced_total'], c['closed']), (60, 7, 61, True))
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.total_fc_produced, 30500)                 # 61 x 500
        self.assertEqual(s.total_breads, 12 + 61 + 9)                # reste d'hier (CARRYOVER) + produit + reçus
        self.assertEqual(s.yield_gap, 30500 - 420000)                # manquant
        self.assertEqual(out['yield_gap'], 30500 - 420000)
        pd = s.closure_summary['production_derivee']
        self.assertEqual((pd['produit_fc'], pd['produit_pains'], pd['theorique_jour_fc'], pd['ecart_fc']),
                         (30500, 61, 420000, -389500))
        self.assertTrue(SystemNotification.objects.filter(title__startswith='Manquant de Rendement').exists())

    def test_excess_and_zero_gap_signs(self):
        sid = self.sacs('0.10')  # 21 000
        self.sell([(self.bp5, 100)])
        self.close(sid, [(self.bp5, 0)])
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.yield_gap, 50000 - 21000)  # excédent +29 000
        self.assertFalse(SystemNotification.objects.filter(title__startswith='Manquant de Rendement').exists())

    def test_zero_gap_exact_sac(self):
        sid = self.sacs('1.00')  # 210 000 = 420 pains de 500
        self.sell([(self.bp5, 400)])
        self.close(sid, [(self.bp5, 20)])
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual((s.total_fc_produced, s.yield_gap), (210000, 0))
        self.assertFalse(SystemNotification.objects.filter(title__startswith='Manquant de Rendement').exists())

    def test_mixed_categories_remaining_without_sales_and_sales_without_remaining(self):
        sid = self.sacs('1.00')
        self.sell([(self.bp5, 30), (self.bp10, 5)])
        self.close(sid, [(self.bp5, 4), (self.bp3, 9)])
        data = self.by_date()
        self.assertEqual(self.cat(data, self.bp5)['produced_total'], 34)
        self.assertEqual(self.cat(data, self.bp3)['produced_total'], 9)   # reste seul
        self.assertEqual(self.cat(data, self.bp10)['produced_total'], 5)  # vendu seul, reste = 0
        self.assertEqual(self.cat(data, self.bp10)['remaining_qty'], 0)
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.total_fc_produced, 34 * 500 + 9 * 300 + 5 * 1000)  # 24 700

    def test_r4_remaining_not_declared_counts_zero(self):
        for body in (None, []):
            with self.subTest(body=body):
                ProductionSession.objects.all().delete()
                BreadStock.objects.all().delete()
                from sales.models import Invoice
                Invoice.objects.all().delete()
                DailyBreadStockSnapshot.objects.all().delete()
                sid = self.sacs('1.00')
                self.sell([(self.bp5, 40)])
                self.close(sid, body)
                c = self.cat(self.by_date(), self.bp5)
                self.assertEqual((c['remaining_qty'], c['produced_total']), (0, 40))

    def test_negative_derived_clamped_on_session_raw_on_by_date_no_500(self):
        sid = self.sacs('1.00')
        self.confirm_opening([(self.bp5, 50)])
        self.sell([(self.bp5, 10)])
        self.close(sid, [(self.bp5, 0)])  # 10 + 0 - 50 = -40
        c = self.cat(self.by_date(), self.bp5)
        self.assertEqual(c['produced_total'], -40)  # brut (documenté)
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.total_fc_produced, 0)
        self.assertEqual(s.yield_gap, 0 - 210000)
        rep = self.report()
        self.assertGreaterEqual(Decimal(str(rep['totals']['ecart_production_fc'])), -210000)
        for row in rep['repartition_pct_par_quantite'] if 'repartition_pct_par_quantite' in rep else []:
            self.assertGreaterEqual(Decimal(row['pct']), 0)

    def test_double_close_refused_and_state_unchanged(self):
        sid = self.sacs()
        self.sell([(self.bp5, 10)])
        self.close(sid, [(self.bp5, 3)])
        before = ProductionSession.objects.get(pk=sid)
        r = self.g.post(f'/api/production/sessions/{sid}/close/', {'remaining': [
            {'bread_price': self.bp5.pk, 'quantity': 99}]}, format='json')
        self.assertIn(r.status_code, (400, 409), r.data)
        after = ProductionSession.objects.get(pk=sid)
        self.assertEqual((before.total_fc_produced, before.yield_gap), (after.total_fc_produced, after.yield_gap))
        self.assertEqual(BreadDisposal.objects.get(session=sid, bread_price=self.bp5, disposal_type='REMAINING').quantity, 3)

    def test_reconciliation_gap_equals_remaining_without_transfers(self):
        # sémantique historique : reliquat = production - (ventes + retours hors REMAINING) = reste du jour
        sid = self.sacs()
        r = self.g.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': str(self.today), 'lines': [{'bread_price': self.bp5.pk, 'qty': 12}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.sell([(self.bp5, 60)])
        self.close(sid, [(self.bp5, 7)])
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.total_breads, 12 + 55)
        self.assertEqual(s.closure_summary['gap']['breads'], 7)
        self.assertFalse(s.closure_summary['anomaly'])

    def test_classic_session_unchanged(self):
        r = self.g.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 300}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        sid = r.data['id']
        self.assertFalse(r.data['auto_track'])
        self.assertEqual(r.data['total_fc_produced'], 150000)
        self.assertEqual(r.data['yield_gap'], 150000 - 210000)  # écart déjà calculé (classique)
        self.sell([(self.bp5, 10)])
        self.assertEqual(ProductionSession.objects.get(pk=sid).delivered_value_fc, 0)  # pas de suivi auto
        self.close(sid, [(self.bp5, 20)])
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual((s.total_breads, s.total_fc_produced, s.yield_gap), (300, 150000, -60000))
        self.assertNotIn('production_derivee', s.closure_summary)
        self.assertEqual(s.closure_summary['production_declared']['breads'], 300)
        c = self.cat(self.by_date(), self.bp5)
        self.assertEqual(c['produced_total'], 300)

    def test_daily_closure_report_after_closure(self):
        sid = self.sacs('2.00')
        self.sell([(self.bp5, 100)])
        self.close(sid, [(self.bp5, 30)])
        rep = self.report()
        c = next(x for x in rep['categories'] if x['bread_price'] == self.bp5.pk)
        self.assertEqual(c['vendu_jour']['quantity'], 100)
        self.assertEqual((c['produit']['quantity'], c['produit']['fc']), (130, '65000.00'))
        self.assertEqual(c['produit_derive'], {'derived': True, 'closed': True})
        self.assertEqual(Decimal(str(rep['totals']['ecart_production_fc'])), 65000 - 420000)


# ---------------------------------------------------------------------------
# 3. Transferts non confirmés, livraison tardive : observations
# ---------------------------------------------------------------------------
class ObservationsTests(_Base):
    def test_disputed_transfer_not_counted_in_sent(self):
        sid = self.sacs()
        self.sell([(self.bp5, 100)])
        _adjust_bread_stock(self.node, self.bp5, produced=50)
        out = self.transfer(self.g2, self.g, self.node, self.bp5, 20, received=18)  # écart -> DISPUTED
        self.assertEqual(out['transfer_status'], 'DISPUTED')
        self.close(sid, [(self.bp5, 10)])
        c = self.cat(self.by_date(), self.bp5)
        # constat : un transfert DISPUTED n'est ni dans envoyés ni dans reçus (R2 ne le dit pas)
        self.assertEqual(c['produced_total'], 110)

    def test_snapshot_chain_next_day_opening_and_stale_remaining(self):
        # J1 : reste 30 ; J2 : vendu sans reste -> instantané 0 ; J3 : pas de reste périmé
        with at(D1):
            s1 = self.sacs('1.00', d=D1)
            self.sell([(self.bp5, 100)])
            self.close(s1, [(self.bp5, 30)])
        snap1 = DailyBreadStockSnapshot.objects.get(node=self.node, bread_price=self.bp5, date=D1)
        self.assertEqual(snap1.qty_at_close, 30)
        with at(D2):
            s2 = self.sacs('1.00', d=D2)
            self.sell([(self.bp5, 50)])
            self.close(s2, [(self.bp5, 10)])
            c = self.cat(self.by_date(D2), self.bp5)
            # R1 : reste d'hier = dernier reste déclaré (30) -> 50 + 10 - 30 = 30
            self.assertEqual(c['produced_total'], 30)
        with at(D3):
            s3 = self.sacs('1.00', d=D3)
            self.sell([(self.bp5, 20), (self.bp10, 4)])
            self.close(s3, [])
            data = self.by_date(D3)
            # reste d'hier (10 déclaré en J2) ; 20 + 0 - 10 = 10
            self.assertEqual(self.cat(data, self.bp5)['produced_total'], 10)
            self.assertEqual(self.cat(data, self.bp10)['produced_total'], 4)
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, bread_price=self.bp5, date=D3)
        self.assertEqual(snap.qty_at_close, 0)

    def test_late_delivery_after_closure_moves_derived_total(self):
        sid = self.sacs('1.00')
        pending = self.invoice([(self.bp5, 10)])
        self.sell([(self.bp5, 20)])
        self.close(sid, [(self.bp5, 5)])
        before = self.cat(self.by_date(), self.bp5)['produced_total']
        self.assertEqual(before, 25)
        d = self.f.post(f'/api/sales/invoices/{pending}/deliver/')
        self.assertEqual(d.status_code, 200, d.data)
        after = self.cat(self.by_date(), self.bp5)['produced_total']
        s = ProductionSession.objects.get(pk=sid)
        # constat : la valeur affichée bouge après clôture (35), la fournée reste figée (25 x 500)
        self.assertEqual(after, 35)
        self.assertEqual(s.total_fc_produced, 12500)
        self.assertEqual(s.delivered_value_fc, 10000)  # la livraison tardive n'avance pas la barre d'une fournée close


# ---------------------------------------------------------------------------
# 4. Plusieurs fournées / équipes / nœuds
# ---------------------------------------------------------------------------
class PlusieursFourneesTests(_Base):
    def test_two_auto_batches_same_day_no_double_count(self):
        a = self.sacs('1.00', team='A')           # 210 000
        self.sell([(self.bp5, 20)])               # -> A (la plus récente)
        b = self.sacs('0.50', team='B')           # 105 000
        self.sell([(self.bp5, 30)])               # -> B
        self.assertEqual(ProductionSession.objects.get(pk=a).delivered_value_fc, 10000)
        self.assertEqual(ProductionSession.objects.get(pk=b).delivered_value_fc, 15000)
        self.close(a, [(self.bp5, 5)])
        data = self.by_date()
        self.assertFalse(data['closed'])          # B encore ouverte
        self.assertIsNone(self.cat(data, self.bp5)['produced_total'])
        self.assertIsNone(self.cat(data, self.bp5)['remaining_qty'])
        self.assertEqual(self.cat(data, self.bp5)['sold_qty'], 50)
        self.close(b, [(self.bp5, 8)])
        data = self.by_date()
        self.assertTrue(data['closed'])
        c = self.cat(data, self.bp5)
        self.assertEqual((c['sold_qty'], c['remaining_qty'], c['produced_total']), (50, 8, 58))
        sa = ProductionSession.objects.get(pk=a)
        sb = ProductionSession.objects.get(pk=b)
        self.assertEqual((sa.total_fc_produced, sa.yield_gap), (0, 0))
        self.assertEqual(sb.total_fc_produced, 29000)
        self.assertEqual(sb.yield_gap, 29000 - 315000)
        self.assertEqual(sa.total_fc_produced + sb.total_fc_produced, 29000)
        self.assertEqual(sa.yield_gap + sb.yield_gap, 29000 - 315000)

    def test_second_batch_declared_after_first_closed_reopens_day(self):
        a = self.sacs('1.00', team='A')
        self.sell([(self.bp5, 20)])
        self.close(a, [(self.bp5, 5)])
        self.assertTrue(self.by_date()['closed'])
        b = self.sacs('0.50', team='B')
        self.assertFalse(self.by_date()['closed'])
        self.sell([(self.bp5, 30)])
        self.close(b, [(self.bp5, 8)])
        sa = ProductionSession.objects.get(pk=a)
        sb = ProductionSession.objects.get(pk=b)
        self.assertEqual(sa.total_fc_produced + sb.total_fc_produced, (50 + 8) * 500)
        self.assertEqual(sa.yield_gap + sb.yield_gap, 29000 - 315000)

    def test_node_isolation(self):
        a = self.sacs('1.00')
        k2s = self.sacs('1.00', api=self.g2)
        self.sell([(self.bp5, 20)])
        self.sell([(self.bp5, 70)], api=self.f2)
        self.assertEqual(ProductionSession.objects.get(pk=a).delivered_value_fc, 10000)
        self.assertEqual(ProductionSession.objects.get(pk=k2s).delivered_value_fc, 35000)
        self.close(k2s, [(self.bp5, 3)], api=self.g2)
        d1 = self.by_date()
        self.assertFalse(d1['closed'])
        self.assertEqual(self.cat(d1, self.bp5)['sold_qty'], 20)
        d2 = self.by_date(node='K2', api=self.g2)
        self.assertTrue(d2['closed'])
        self.assertEqual(self.cat(d2, self.bp5)['produced_total'], 73)
        # un gérant K1 qui demande K2 : le paramètre node est ignoré (BUG-144)
        other = self.by_date(node='K2')
        self.assertEqual(other['node'], self.node.pk)
        self.assertEqual(self.cat(other, self.bp5)['sold_qty'], 20)
        rows = self.g.get('/api/production/bread-stocks/').data
        rows = rows['results'] if isinstance(rows, dict) else rows
        self.assertTrue(all(r['node'] == self.node.pk for r in rows))
        self.assertEqual(next(r for r in rows if r['bread_price'] == self.bp5.pk)['sold_qty'], 20)
        # la clôture K1 ne change pas K2
        self.close(a, [(self.bp5, 1)])
        self.assertEqual(ProductionSession.objects.get(pk=k2s).total_fc_produced, 36500)

    def test_closure_k1_does_not_touch_other_node_snapshots_or_opening(self):
        a = self.sacs('1.00')
        k2s = self.sacs('1.00', api=self.g2)
        self.sell([(self.bp5, 10)])
        self.confirm_opening([(self.bp5, 99)], node=self.k2)
        self.close(a, [(self.bp5, 2)])
        self.assertFalse(DailyBreadStockSnapshot.objects.filter(node=self.k2).exists())
        self.sell([(self.bp5, 1)], api=self.f2)
        self.close(k2s, [(self.bp5, 0)], api=self.g2)
        c = self.cat(self.by_date(node='K2', api=self.g2), self.bp5)
        self.assertEqual(c['produced_total'], 1 + 0 - 99)  # K2 : son propre stock de départ
        self.assertEqual(self.cat(self.by_date(), self.bp5)['produced_total'], 12)


# ---------------------------------------------------------------------------
# 5. Clôture forcée (shift-end-status)
# ---------------------------------------------------------------------------
class ClotureForceeTests(_Base):
    def setUp(self):
        super().setUp()
        self.node.team_a_end_time = dtime(13, 0)
        self.node.save(update_fields=['team_a_end_time'])

    def _status(self, hour, minute=0, api=None):
        with at(D1, hour, minute):
            return (api or self.g).get('/api/production/sessions/shift-end-status/', {'node': 'K1'})

    def test_forced_closure_auto_batch_capped_at_zero(self):
        with at(D1, 9):
            sid = self.sacs('1.00', d=D1)
            self.sell([(self.bp5, 10)])
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp5)
        self.assertEqual(stock.qty_available, -10)  # produit non crédité : départ - vendus
        r = self._status(14)  # 60 min après 13:00
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data.get('auto_closed'), r.data)
        d = BreadDisposal.objects.get(session=sid, bread_price=self.bp5, disposal_type='REMAINING')
        self.assertEqual(d.quantity, 0)  # plafonné, pas -10
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, bread_price=self.bp5, date=D1)
        self.assertEqual(snap.qty_at_close, 0)
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.total_fc_produced, 5000)  # 10 + 0 - 0 = 10 pains
        self.assertEqual(s.yield_gap, 5000 - 210000)
        self.assertFalse(SystemNotification.objects.filter(title__startswith='Stock de pain négatif').exists())

    def test_pending_validation_suggests_zero_for_auto_negative_for_classic(self):
        with at(D1, 9):
            sid = self.sacs('1.00', d=D1)
            self.sell([(self.bp5, 10)])
        r = self._status(13, 10)  # 10 min : dans le délai de grâce
        self.assertTrue(r.data['pending_validation'], r.data)
        sug = {x['bread_price']: x['quantity_suggested'] for x in r.data['remaining']}
        self.assertEqual(sug[self.bp5.pk], 0)
        self.assertGreaterEqual(min(sug.values()), 0)
        # fournée classique (BUG-158) : valeur réelle négative conservée
        ProductionSession.objects.filter(pk=sid).delete()
        BreadStock.objects.all().update(qty_produced=0)
        with at(D1, 9):
            c = self.g.post('/api/production/sessions/', {
                'team': 'A', 'date': str(D1), 'flour_sacks_used': '1.00',
                'lines': [{'bread_price': self.bp5.pk, 'quantity': 2}]}, format='json')
            self.assertEqual(c.status_code, 201, c.data)
        r = self._status(13, 10)
        sug = {x['bread_price']: x['quantity_suggested'] for x in r.data['remaining']}
        self.assertEqual(sug[self.bp5.pk], BreadStock.objects.get(node=self.node, bread_price=self.bp5).qty_available)

    def test_forced_closure_with_confirmed_opening_balances_out(self):
        _adjust_bread_stock(self.node, self.bp5, produced=30)
        self.confirm_opening([(self.bp5, 30)], d=D1)
        with at(D1, 9):
            sid = self.sacs('1.00', d=D1)
            self.sell([(self.bp5, 10)])
        r = self._status(14)
        self.assertTrue(r.data.get('auto_closed'), r.data)
        d = BreadDisposal.objects.get(session=sid, bread_price=self.bp5, disposal_type='REMAINING')
        self.assertEqual(d.quantity, 20)
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.total_fc_produced, 0)  # 10 + 20 - 30 = 0 : rien fabriqué

    def test_next_morning_proposal_reuses_declared_remaining(self):
        """Hors rotation, `qty_proposed` du lendemain doit reprendre le reste du jour déclaré."""
        with at(D1, 9):
            sid = self.sacs('1.00', d=D1)
            self.sell([(self.bp5, 100)])
            self.close(sid, [(self.bp5, 30)])
        r = self.g.get('/api/production/opening-confirmation/', {'node': 'K1', 'date': str(self.today)})
        self.assertEqual(r.status_code, 200, r.data)
        prop = next(c['qty_proposed'] for c in r.data['categories'] if c['bread_price'] == self.bp5.pk)
        self.assertEqual(prop, 30)


# ---------------------------------------------------------------------------
# 6. Migrations 0025 / 0026
# ---------------------------------------------------------------------------
class Migration0026Tests(TransactionTestCase):
    migrate_from = [('production', '0025_bug319_delivered_value_fc')]
    migrate_to = [('production', '0026_bug319_reprise_fournees_en_cours')]

    def _migrate(self, targets):
        ex = MigrationExecutor(connection)
        ex.loader.build_graph()
        ex.migrate(targets)
        return MigrationExecutor(connection).loader.project_state(targets).apps

    def tearDown(self):
        ex = MigrationExecutor(connection)
        ex.loader.build_graph()
        ex.migrate(ex.loader.graph.leaf_nodes())

    def _seed(self, apps_):
        Node = apps_.get_model('core', 'Node')
        BreadPrice = apps_.get_model('core', 'BreadPrice')
        PS = apps_.get_model('production', 'ProductionSession')
        PL = apps_.get_model('production', 'ProductionSessionLine')
        BS = apps_.get_model('production', 'BreadStock')
        n1 = Node.objects.create(code='M1', name='M1')
        n2 = Node.objects.create(code='M2', name='M2')
        b5 = BreadPrice.objects.create(category='MIG5', label='Mig 500', unit_price=500)
        b3 = BreadPrice.objects.create(category='MIG3', label='Mig 300', unit_price=300)
        d = date(2026, 10, 14)
        # fournée auto ouverte avec ventes auto-incrémentées + un reste d'hier
        s = PS.objects.create(node=n1, team='A', date=d, flour_sacks_used=Decimal('2'), auto_track=True,
                              total_fc_produced=21000, yield_gap=-399000, total_breads=57)
        PL.objects.create(session=s, bread_price=b5, quantity=30, source='DECLARED')
        PL.objects.create(session=s, bread_price=b3, quantity=20, source='DECLARED')
        PL.objects.create(session=s, bread_price=b5, quantity=7, source='CARRYOVER')
        BS.objects.create(node=n1, bread_price=b5, qty_produced=30)
        BS.objects.create(node=n1, bread_price=b3, qty_produced=25)
        # fournée auto ouverte à vide (aucune vente)
        empty = PS.objects.create(node=n2, team='A', date=d, flour_sacks_used=Decimal('1'), auto_track=True)
        # fournée auto ouverte sans ligne de stock correspondante
        nostock = PS.objects.create(node=n2, team='B', date=d, flour_sacks_used=Decimal('1'), auto_track=True,
                                    total_fc_produced=500, total_breads=1)
        PL.objects.create(session=nostock, bread_price=b5, quantity=1, source='DECLARED')
        # fournée auto clôturée : intacte
        closed = PS.objects.create(node=n1, team='B', date=d, flour_sacks_used=Decimal('1'), auto_track=True,
                                   is_closed=True, total_fc_produced=4500, total_breads=9, yield_gap=-205500)
        PL.objects.create(session=closed, bread_price=b5, quantity=9, source='DECLARED')
        # fournée classique ouverte : intacte
        classic = PS.objects.create(node=n2, team='A', date=date(2026, 10, 15), flour_sacks_used=Decimal('1'),
                                    auto_track=False, total_fc_produced=150000, total_breads=300)
        PL.objects.create(session=classic, bread_price=b5, quantity=300, source='DECLARED')
        return dict(s=s.pk, empty=empty.pk, nostock=nostock.pk, closed=closed.pk, classic=classic.pk,
                    n1=n1.pk, b5=b5.pk, b3=b3.pk)

    def test_forward_migration_reclassifies_open_auto_batches_only(self):
        old = self._migrate(self.migrate_from)
        ids = self._seed(old)
        new = self._migrate(self.migrate_to)
        PS = new.get_model('production', 'ProductionSession')
        PL = new.get_model('production', 'ProductionSessionLine')
        BS = new.get_model('production', 'BreadStock')
        s = PS.objects.get(pk=ids['s'])
        self.assertEqual(s.delivered_value_fc, 30 * 500 + 20 * 300)  # 21 000
        self.assertEqual((s.total_fc_produced, s.yield_gap), (0, 0))
        self.assertEqual(s.total_breads, 7)  # reste d'hier conservé
        self.assertFalse(PL.objects.filter(session_id=ids['s'], source='DECLARED').exists())
        self.assertEqual(PL.objects.get(session_id=ids['s'], source='CARRYOVER').quantity, 7)
        self.assertEqual(BS.objects.get(node_id=ids['n1'], bread_price_id=ids['b5']).qty_produced, 0)
        self.assertEqual(BS.objects.get(node_id=ids['n1'], bread_price_id=ids['b3']).qty_produced, 5)
        e = PS.objects.get(pk=ids['empty'])
        self.assertEqual((e.delivered_value_fc, e.total_fc_produced, e.yield_gap, e.total_breads), (0, 0, 0, 0))
        ns = PS.objects.get(pk=ids['nostock'])  # pas de BreadStock correspondant : pas d'erreur
        self.assertEqual((ns.delivered_value_fc, ns.total_fc_produced), (500, 0))
        c = PS.objects.get(pk=ids['closed'])
        self.assertEqual((c.delivered_value_fc, c.total_fc_produced, c.total_breads, c.yield_gap), (0, 4500, 9, -205500))
        self.assertTrue(PL.objects.filter(session_id=ids['closed'], source='DECLARED').exists())
        k = PS.objects.get(pk=ids['classic'])
        self.assertEqual((k.delivered_value_fc, k.total_fc_produced, k.total_breads), (0, 150000, 300))
        self.assertTrue(PL.objects.filter(session_id=ids['classic'], source='DECLARED').exists())

    def test_migration_on_empty_database_and_reverse_is_noop(self):
        old = self._migrate(self.migrate_from)
        PS = old.get_model('production', 'ProductionSession')
        self.assertEqual(PS.objects.count(), 0)
        self._migrate(self.migrate_to)       # base vide : aucune erreur
        self._migrate(self.migrate_from)     # retour arrière 0026 : no-op
        self._migrate(self.migrate_to)       # rejouable
        # retour arrière de 0025 : la colonne disparaît puis revient
        self._migrate([('production', '0024_productionsession_auto_track')])
        self._migrate(self.migrate_to)


# ---------------------------------------------------------------------------
# 7. BUG-322
# ---------------------------------------------------------------------------
class Bug322Tests(_Base):
    BAD = ('1E+999999', '-1E+999999', '1e+99999999999', '9E+999999999999999999',
           '1E-999999', '9' * 5000, '-' + '9' * 5000, 'Infinity', 'NaN', '1' + '0' * 4400)

    def _confirm(self, qty):
        return self.g.post('/api/production/opening-confirmation/', {
            'node': 'K1', 'team': 'A', 'date': str(self.today),
            'lines': [{'bread_price': self.bp5.pk, 'qty': qty}]}, format='json')

    def _timed(self, fn, *a):
        t = time.monotonic()
        r = fn(*a)
        self.assertLess(time.monotonic() - t, 2.0, a)
        return r

    def test_opening_confirmation_huge_values_fast_400(self):
        for bad in self.BAD:
            with self.subTest(bad=bad[:25]):
                r = self._timed(self._confirm, bad)
                self.assertEqual(r.status_code, 400, (bad[:25], r.data))
                self.assertIn('detail', r.data)
        self.assertFalse(DailyOpeningConfirmation.objects.exists())
        self.assertEqual(sum(abs(b.qty_adjusted) for b in BreadStock.objects.all()), 0)

    def test_opening_confirmation_bounds(self):
        for ok in (0, '0', 2_000_000_000, '2000000000', '+7', ' 5 '):
            with self.subTest(ok=ok):
                r = self._timed(self._confirm, ok)
                self.assertEqual(r.status_code, 200, (ok, r.data))
        # BUG-896/BUG-1012 : formes exponentielles ASCII refusées.
        for ko in ('0E+999999', '2E+9', '2.000E+9', '7E0', '1e3', 2_000_000_001, '2000000001', '2.0000001E+9', -1, '-1', '-0.5', 1.5, True, None, '', 'abc'):
            with self.subTest(ko=ko):
                r = self._timed(self._confirm, ko)
                self.assertEqual(r.status_code, 400, (ko, r.data))

    def test_close_remaining_huge_values_fast_400_session_stays_open(self):
        sid = self.sacs('1.00')
        for bad in self.BAD:
            with self.subTest(bad=bad[:25]):
                r = self._timed(lambda: self.g.post(f'/api/production/sessions/{sid}/close/', {
                    'remaining': [{'bread_price': self.bp5.pk, 'quantity': bad}]}, format='json'))
                self.assertEqual(r.status_code, 400, (bad[:25], r.data))
        s = ProductionSession.objects.get(pk=sid)
        self.assertFalse(s.is_closed)
        self.assertFalse(BreadDisposal.objects.filter(session=s).exists())

    def test_close_remaining_bounds_no_server_error(self):
        sid = self.sacs('1.00')
        r = self._timed(lambda: self.g.post(f'/api/production/sessions/{sid}/close/', {
            'remaining': [{'bread_price': self.bp5.pk, 'quantity': 2_000_000_001}]}, format='json'))
        self.assertEqual(r.status_code, 400, r.data)
        r = self._timed(lambda: self.g.post(f'/api/production/sessions/{sid}/close/', {
            'remaining': [{'bread_price': self.bp5.pk, 'quantity': -2_000_000_001}]}, format='json'))
        self.assertEqual(r.status_code, 400, r.data)

    def test_close_remaining_upper_bound_included_does_not_crash(self):
        sid = self.sacs('1.00')
        r = self.g.post(f'/api/production/sessions/{sid}/close/', {
            'remaining': [{'bread_price': self.bp10.pk, 'quantity': 2_000_000_000}]}, format='json')
        self.assertLess(r.status_code, 500, getattr(r, 'data', None))

    def test_other_numeric_inputs_answer_fast(self):
        sid = self.sacs('1.00')
        big = '1E+999999'
        calls = [
            lambda: self.g.post('/api/production/sessions/', {
                'team': 'B', 'date': str(self.today), 'flour_sacks_used': big}, format='json'),
            lambda: self.g.post('/api/production/sessions/', {
                'team': 'B', 'date': str(self.today), 'flour_sacks_used': '1',
                'lines': [{'bread_price': self.bp5.pk, 'quantity': big}]}, format='json'),
            lambda: self.g.patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': big}, format='json'),
            lambda: self.g.post('/api/production/disposals/', {
                'session': sid, 'bread_price': self.bp5.pk, 'disposal_type': 'DECLASSED', 'quantity': big}, format='json'),
            lambda: self.g.post('/api/production/transfers/', {
                'from_node': self.k2.pk, 'lines': [{'bread_price': self.bp5.pk, 'quantity_sent': big}]}, format='json'),
            lambda: self.g.post('/api/production/movements/', {
                'quantity': big, 'movement_type': 'IN', 'unit_price': big}, format='json'),
            lambda: self.g.post('/api/production/counts/', {
                'consumable_type': 'SEL', 'physical_quantity': big, 'count_date': str(self.today)}, format='json'),
        ]
        for i, fn in enumerate(calls):
            with self.subTest(call=i):
                r = self._timed(fn)
                self.assertLess(r.status_code, 500, (i, getattr(r, 'data', None)))
        self.assertEqual(ProductionSession.objects.get(pk=sid).flour_sacks_used, Decimal('1.00'))
