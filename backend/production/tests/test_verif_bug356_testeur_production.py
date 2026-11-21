"""
Vérification indépendante (testeur-production, 2026-11-21) de BUG-356 (volet
backend : « Non servi » par STATUT dans la Clôture journalière) et du volet
tests de BUG-350 (rotation, horloge simulée : lacunes complémentaires).

Écrit sans réutiliser les fabriques du fichier du développeur ; valeurs
calculées à la main. Données fictives (`core.testing`). Aucune modification du
code applicatif.

Contrat vérifié : categories[].non_servi_jour {quantity:int, fc:"x.00"} ;
totals.non_servi_fc, totals.non_servi_quantity, totals.non_servi_total_fc.
"""
from contextlib import contextmanager
from datetime import date, datetime, time as dtime, timedelta, timezone as dt_utc
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import DailyOpeningConfirmation, DailyTeamAssignment
from sales.models import Invoice

CLOSURE = '/api/production/daily-closure/'
CLIENTS = '/api/production/daily-closure/clients/'
OPENING = '/api/production/opening-confirmation/'


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _local(d, h=10, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


class _V(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', sac_value_fc=Decimal('200000'))
        self.k2 = make_node(code='K2', sac_value_fc=Decimal('200000'))
        self.bp2 = make_bread_price('V356_200', 'Pain 200 V356', 200)
        self.bp7 = make_bread_price('V356_700', 'Pain 700 V356', 700)
        self.gerant = make_user('GERANT', node=self.k1)
        self.fa = make_user('FACTURIER', node=self.k1, team='A')
        self.fb = make_user('FACTURIER', node=self.k1, team='B')
        self.cli = make_client(self.k1, credit_limit=Decimal('9000000.00'))
        self.g = _api(self.gerant)
        self.today = timezone.localdate()

    def inv(self, lines, user=None, **extra):
        p = {'payment_type': 'CREDIT', 'payment_amount': '0.00', 'client': str(self.cli.pk),
             'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines]}
        p.update(extra)
        r = _api(user or self.fa).post('/api/sales/invoices/', p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def ns(self, iid, user=None):
        r = _api(user or self.fa).post(f'/api/sales/invoices/{iid}/mark-not-served/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def deliver(self, iid, user=None):
        r = _api(user or self.fa).post(f'/api/sales/invoices/{iid}/deliver/')
        self.assertEqual(r.status_code, 200, r.data)

    def rep(self, d=None, api=None, node=None):
        params = {'date': str(d or self.today)}
        if node:
            params['node'] = node
        r = (api or self.g).get(CLOSURE, params)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    @staticmethod
    def cat(data, bp):
        return next(c for c in data['categories'] if c['bread_price'] == bp.pk)


class Bug356Verification(_V):
    def test_contract_types_and_empty_day(self):
        data = self.rep()
        for c in data['categories']:
            self.assertEqual(c['non_servi_jour'], {'quantity': 0, 'fc': '0.00'})
            self.assertIsInstance(c['non_servi_jour']['quantity'], int)
        t = data['totals']
        self.assertEqual((t['non_servi_fc'], t['non_servi_quantity'], t['non_servi_total_fc']), ('0.00', 0, '0.00'))

    def test_hand_computed_multi_category_total_and_sum_of_rows(self):
        self.ns(self.inv([(self.bp2, 15), (self.bp7, 3)]))      # 3000 + 2100
        self.ns(self.inv([(self.bp7, 1)], user=self.fb), user=self.fb)  # 700
        data = self.rep()
        self.assertEqual(self.cat(data, self.bp2)['non_servi_jour'], {'quantity': 15, 'fc': '3000.00'})
        self.assertEqual(self.cat(data, self.bp7)['non_servi_jour'], {'quantity': 4, 'fc': '2800.00'})
        t = data['totals']
        self.assertEqual((t['non_servi_fc'], t['non_servi_quantity'], t['non_servi_total_fc']), ('5800.00', 19, '5800.00'))
        self.assertEqual(sum(Decimal(c['non_servi_jour']['fc']) for c in data['categories']), Decimal(t['non_servi_fc']))
        self.assertEqual(sum(c['non_servi_jour']['quantity'] for c in data['categories']), t['non_servi_quantity'])

    def test_frozen_price_survives_catalog_change_and_category_deactivation(self):
        self.ns(self.inv([(self.bp7, 2)]))
        self.bp7.unit_price = 1234
        self.bp7.is_active = False
        self.bp7.save()
        row = self.cat(self.rep(), self.bp7)    # la catégorie reste listée (valeur figée)
        self.assertEqual(row['non_servi_jour'], {'quantity': 2, 'fc': '1400.00'})

    def test_ordered_quantity_wins_over_zeroed_quantity_and_fallback(self):
        iid = self.inv([(self.bp2, 8), (self.bp7, 5)])
        self.ns(iid)
        lines = Invoice.objects.get(pk=iid).lines.all()
        for ln in lines:
            self.assertEqual(ln.quantity, 0)                  # servi = 0
        data = self.rep()
        self.assertEqual(self.cat(data, self.bp2)['non_servi_jour']['quantity'], 8)
        self.assertEqual(self.cat(data, self.bp7)['non_servi_jour']['quantity'], 5)
        # ancienne ligne sans ordered_quantity : repli sur quantity
        lines.filter(bread_price=self.bp7).update(ordered_quantity=None, quantity=2)
        self.assertEqual(self.cat(self.rep(), self.bp7)['non_servi_jour'], {'quantity': 2, 'fc': '1400.00'})

    def test_zero_ordered_quantity_is_not_replaced_by_fallback(self):
        iid = self.inv([(self.bp2, 8)])
        self.ns(iid)
        Invoice.objects.get(pk=iid).lines.update(ordered_quantity=0, quantity=6)
        self.assertEqual(self.cat(self.rep(), self.bp2)['non_servi_jour'], {'quantity': 0, 'fc': '0.00'})

    def test_date_uses_not_served_at_local_midnight_frontier(self):
        iid = self.inv([(self.bp2, 10)])
        self.ns(iid)
        d = date(2026, 3, 9)
        # 22:30 UTC le 8 = 23:30 local (UTC+1) le 8 ; 23:30 UTC le 8 = 00:30 local le 9
        Invoice.objects.filter(pk=iid).update(not_served_at=datetime(2026, 3, 8, 22, 30, tzinfo=dt_utc.utc))
        self.assertEqual(self.rep(date(2026, 3, 8))['totals']['non_servi_quantity'], 10)
        self.assertEqual(self.rep(d)['totals']['non_servi_quantity'], 0)
        Invoice.objects.filter(pk=iid).update(not_served_at=datetime(2026, 3, 8, 23, 30, tzinfo=dt_utc.utc))
        self.assertEqual(self.rep(date(2026, 3, 8))['totals']['non_servi_quantity'], 0)
        self.assertEqual(self.rep(d)['totals']['non_servi_quantity'], 10)

    def test_not_served_at_null_legacy_row_is_ignored_without_error(self):
        iid = self.inv([(self.bp2, 10)])
        self.ns(iid)
        Invoice.objects.filter(pk=iid).update(not_served_at=None)
        self.assertEqual(self.rep()['totals']['non_servi_quantity'], 0)

    def test_status_filter_pending_cancelled_delivered_not_counted(self):
        self.inv([(self.bp2, 10)])                                 # PENDING
        c = self.inv([(self.bp2, 4)])
        _api(self.fa).post(f'/api/sales/invoices/{c}/cancel/')    # annulée
        self.deliver(self.inv([(self.bp2, 3)]))                   # livrée
        self.assertEqual(self.rep()['totals']['non_servi_quantity'], 0)

    def test_refund_and_adjustment_flags_excluded(self):
        a = self.inv([(self.bp2, 10)])
        b = self.inv([(self.bp2, 6)])
        self.ns(a)
        self.ns(b)
        Invoice.objects.filter(pk=a).update(is_debt_repayment=True)
        Invoice.objects.filter(pk=b).update(is_adjustment=True)
        self.assertEqual(self.rep()['totals']['non_servi_quantity'], 0)

    def test_ns_special_code_not_double_counted_even_if_status_not_served(self):
        n = self.inv([(self.bp2, 10)], special_code='NS')         # code NS, PENDING
        Invoice.objects.filter(pk=n).update(status=Invoice.Status.NOT_SERVED, not_served_at=timezone.now())
        data = self.rep()
        c = self.cat(data, self.bp2)
        self.assertEqual(c['non_servi_jour'], {'quantity': 0, 'fc': '0.00'})
        self.assertEqual(c['non_servi']['quantity'], 10)          # une seule source (code NS)
        self.assertEqual(data['totals']['non_servi_total_fc'], '2000.00')
        cl = self.g.get(CLIENTS, {'date': str(self.today)})
        self.assertEqual(cl.data['non_servis']['count'], 1)       # une facture = une ligne

    def test_cumulative_status_plus_code_total(self):
        self.inv([(self.bp7, 2)], special_code='NS')              # code : 1400
        self.ns(self.inv([(self.bp2, 5)]))                        # statut : 1000
        t = self.rep()['totals']
        self.assertEqual((t['non_servi_fc'], t['non_servi_total_fc']), ('1000.00', '2400.00'))

    def test_no_effect_on_sales_stock_production_and_totals(self):
        self.deliver(self.inv([(self.bp2, 5)]))
        before = self.rep()
        stock_before = self.g.get('/api/production/bread-stocks/by-date/', {'node': 'K1'}).data
        self.ns(self.inv([(self.bp2, 40), (self.bp7, 9)]))
        after = self.rep()
        for k in ('total_du_jour_fc', 'total_breads_billed', 'ecart_facture_fc', 'net_produit_fc',
                  'total_breads_produced', 'reste_du_hier_jour_fc', 'reste_du_jour_jour_fc'):
            self.assertEqual(after['totals'][k], before['totals'][k], k)
        for b, a in zip(before['categories'], after['categories']):
            for k in ('produit', 'produit_derive', 'vendu_jour', 'facture_jr', 'commission_jr',
                      'regularisation', 'vente_cash_soldee', 'facture_mvm_interne', 'non_servi',
                      'reste_du_jour', 'reste_du_hier'):
                self.assertEqual(a[k], b[k], f"{a['label']}.{k}")
        # le stock disponible n'a pas bougé (pains restitués)
        stock_after = self.g.get('/api/production/bread-stocks/by-date/', {'node': 'K1'}).data
        qty = lambda d: {c['bread_price']: c['qty_available'] for c in d['categories'] if c['qty_available'] or c['sold_qty']}
        self.assertEqual(qty(stock_after), qty(stock_before))

    def test_bug319_derived_production_unchanged_on_closed_day(self):
        r = self.g.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.deliver(self.inv([(self.bp2, 30)]))
        self.ns(self.inv([(self.bp2, 11)]))
        c = self.g.post(f"/api/production/sessions/{r.data['id']}/close/",
                        {'remaining': [{'bread_price': self.bp2.pk, 'quantity': 4}]}, format='json')
        self.assertEqual(c.status_code, 200, c.data)
        row = self.cat(self.rep(), self.bp2)
        self.assertTrue(row['produit_derive']['derived'] and row['produit_derive']['closed'])
        self.assertEqual(row['vendu_jour']['quantity'], 30)
        self.assertEqual(row['produit']['quantity'], 34)           # 30 vendus + 4 reste ; les 11 NS n'y sont pas
        self.assertEqual(row['non_servi_jour']['quantity'], 11)

    def test_bug177_ns_rg_regularisation_unchanged(self):
        self.inv([(self.bp2, 10)], special_code='NS')
        rg = self.inv([(self.bp2, 6)], special_code='RG')
        self.deliver(rg)
        self.ns(self.inv([(self.bp2, 20)]))
        c = self.cat(self.rep(), self.bp2)
        self.assertEqual(c['non_servi'], {'quantity': 10, 'fc': '2000.00', 'fc_signe': '-2000.00'})
        self.assertEqual(c['regularisation'], {'quantity': 6, 'fc': '1200.00'})
        self.assertEqual(c['facture_mvm_interne'], {'fc': '-800.00'})   # -2000 + 1200, statut hors total
        self.assertEqual(c['non_servi_jour'], {'quantity': 20, 'fc': '4000.00'})

    def test_node_isolation_and_hq_view(self):
        cli2 = make_client(self.k2, credit_limit=Decimal('9000000.00'))
        f2 = make_user('FACTURIER', node=self.k2, team='A')
        r = _api(f2).post('/api/sales/invoices/', {
            'payment_type': 'CREDIT', 'payment_amount': '0', 'client': str(cli2.pk),
            'lines': [{'bread_price': self.bp2.pk, 'quantity': 50}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.ns(r.data['id'], user=f2)
        self.ns(self.inv([(self.bp2, 2)]))
        self.assertEqual(self.rep()['totals']['non_servi_quantity'], 2)
        hq = _api(make_user('DIRECTION'))
        self.assertEqual(self.rep(api=hq, node='K2')['totals']['non_servi_quantity'], 50)
        self.assertEqual(self.rep(api=hq, node='K1')['totals']['non_servi_quantity'], 2)
        # un gérant K1 qui réclame K2 reste sur K1
        self.assertEqual(self.rep(node='K2')['node'], 'K1')

    def test_consistency_with_clients_endpoint_per_team_and_totals(self):
        self.ns(self.inv([(self.bp2, 2)], user=self.fa), user=self.fa)
        self.ns(self.inv([(self.bp7, 3)], user=self.fb), user=self.fb)
        self.ns(self.inv([(self.bp7, 1)], user=self.fb), user=self.fb)
        self.assertEqual(self.rep()['totals']['non_servi_quantity'], 6)
        tot = self.g.get(CLIENTS, {'date': str(self.today)}).data
        self.assertEqual(tot['non_servis']['count'], 3)
        for team, n in (('A', 1), ('B', 2)):
            self.assertEqual(self.g.get(CLIENTS, {'date': str(self.today), 'team': team}).data['non_servis']['count'], n)
        self.assertEqual(tot['totals']['order_value'], Decimal('0.00'))   # aucune vente

    def test_payment_kept_does_not_alter_non_servi_value(self):
        self.ns(self.inv([(self.bp2, 10)], payment_amount='500.00'))
        self.assertEqual(self.cat(self.rep(), self.bp2)['non_servi_jour'], {'quantity': 10, 'fc': '2000.00'})

    def test_other_day_is_zero_and_read_only(self):
        self.ns(self.inv([(self.bp2, 10)]))
        before = Invoice.objects.count()
        self.assertEqual(self.rep(self.today - timedelta(days=1))['totals']['non_servi_quantity'], 0)
        self.assertEqual(self.rep(self.today + timedelta(days=1))['totals']['non_servi_quantity'], 0)
        self.rep()
        self.assertEqual(Invoice.objects.count(), before)


# ---------------------------------------------------------------------------
# BUG-350 : scénarios complémentaires (volet tests)
# ---------------------------------------------------------------------------
D = date(2026, 11, 12)
PREV = D - timedelta(days=1)
NEXT = D + timedelta(days=1)


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_local(d, h, m).astimezone(dt_utc.utc))


class Bug350Complements(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.bp = make_bread_price('V350_500', 'Pain 500 V350', 500)
        self.api = _api(self.gerant)

    def rot(self, on=True, at=None):
        self.node.team_rotation_enabled = on
        if at:
            self.node.handover_time = at
        self.node.save()

    def assign(self, d, team):
        DailyTeamAssignment.objects.create(node=self.node, work_date=d, team=team)

    def get(self):
        r = self.api.get(OPENING)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def post(self, qty=5, **kw):
        return self.api.post(OPENING, {'lines': [{'bread_price': self.bp.pk, 'qty': qty}], **kw}, format='json')

    def test_early_custom_handover_0600(self):
        self.rot(at=dtime(6, 0))
        self.assign(PREV, 'A')
        self.assign(D, 'B')
        with _now(5, 59):
            r = self.get()
            self.assertEqual(r['team'], 'A')                       # période de la veille
            self.assertTrue(r['needs_confirmation'])
        with _now(6, 0):
            r = self.get()
            self.assertEqual((r['team'], r['date']), ('B', '2026-11-12'))
            self.assertTrue(r['needs_confirmation'])

    def test_handover_time_is_ignored_without_rotation(self):
        self.node.handover_time = dtime(14, 30)
        self.rot(on=False)
        with _now(14, 29):
            before = self.get()
        with _now(14, 30):
            after = self.get()
        self.assertFalse(before.get('rotation', False) or after.get('rotation', False))
        self.assertEqual(before['needs_confirmation'], after['needs_confirmation'])
        with _now(9, 0):
            rr = self.post(team='A')
            self.assertEqual(rr.status_code, 200, rr.data)
        with _now(14, 30):
            self.assertFalse(self.get()['needs_confirmation'])     # pas de seconde boîte à la « relève »
        self.assertEqual(DailyOpeningConfirmation.objects.count(), 1)

    def test_team_change_mid_period_does_not_leak_to_next_period(self):
        self.rot()
        self.assign(D, 'A')
        with _now(12, 10):
            self.assertEqual(self.post().status_code, 200)         # A confirme
            self.assertEqual(self.api.post('/api/production/team-assignment/', {'team': 'B'}, format='json').status_code, 200)
        self.assign(NEXT, 'B')
        with _now(11, 59, d=NEXT):
            self.assertFalse(self.get()['needs_confirmation'])     # même période, rien de dû
        with _now(12, 0, d=NEXT):
            r = self.get()
            self.assertEqual((r['team'], r['date']), ('B', '2026-11-13'))
            self.assertTrue(r['needs_confirmation'])               # la correction A->B n'a pas pré-confirmé B demain

    def test_skipped_period_does_not_block_next_handover(self):
        self.rot()
        self.assign(D, 'A')                                        # jamais confirmée
        self.assign(NEXT, 'B')
        with _now(12, 0, d=NEXT):
            r = self.get()
            self.assertEqual(r['team'], 'B')
            self.assertTrue(r['needs_confirmation'])
            self.assertEqual(self.post().status_code, 200)
            self.assertFalse(self.get()['needs_confirmation'])
        self.assertFalse(DailyOpeningConfirmation.objects.filter(node=self.node, team='A').exists())

    def test_opening_confirmation_raises_stock_to_declared_value_on_handover(self):
        from production.models import BreadStock
        self.rot()
        self.assign(D, 'B')
        BreadStock.objects.update_or_create(node=self.node, bread_price=self.bp, defaults={'qty_produced': 9})
        with _now(12, 5):
            self.assertEqual(self.post(qty=7).status_code, 200)
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available, 7)
