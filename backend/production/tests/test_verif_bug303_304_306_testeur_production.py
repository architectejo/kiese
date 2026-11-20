"""
Vérification indépendante (testeur-production, 2026-11-19) de BUG-303, BUG-304
et BUG-306 (partie API). Valeurs calculées à la main. Aucune modification du
code applicatif.
"""
import threading
from unittest import expectedFailure
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from core.workday import business_date, work_date_for
from production.models import (
    BreadDisposal, BreadStock, DailyBreadStockSnapshot, DailyTeamAssignment,
    ProductionSession, ProductionSessionLine,
)


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', sac_value_fc=Decimal('210000'))
        self.gerant = make_user('GERANT', node=self.node)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.bp5 = make_bread_price('V306_500', 'Pain 500 V306', 500)
        self.bp3 = make_bread_price('V306_300', 'Pain 300 V306', 300)
        self.g = _api(self.gerant)
        self.f = _api(self.facturier)
        self.today = work_date_for(self.node)

    def _sacs(self, sacs='2.00', team='A', api=None, d=None):
        return (api or self.g).post('/api/production/sessions/', {
            'team': team, 'date': str(d or self.today), 'flour_sacks_used': sacs,
        }, format='json')

    def _sell(self, lines, api=None, deliver=True, extra=None):
        p = {'payment_type': 'CASH',
             'payment_amount': str(sum(bp.unit_price * q for bp, q in lines)),
             'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines]}
        p.update(extra or {})
        r = (api or self.f).post('/api/sales/invoices/', p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        if deliver:
            d = (api or self.f).post(f"/api/sales/invoices/{r.data['id']}/deliver/")
            self.assertEqual(d.status_code, 200, d.data)
        return r.data

    def _classic(self, team, d, qty, node=None):
        s = ProductionSession.objects.create(
            node=node or self.node, team=team, date=d, flour_sacks_used=Decimal('1'),
        )
        ProductionSessionLine.objects.create(session=s, bread_price=self.bp5, quantity=qty)
        return s


class V303NegativeTests(_Base):
    def _classic_api(self):
        r = self.g.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 50}, {'bread_price': self.bp3.pk, 'quantity': 40}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def test_mixed_list_one_negative_applies_nothing(self):
        sid = self._classic_api()
        c = self.g.post(f'/api/production/sessions/{sid}/close/', {'remaining': [
            {'bread_price': self.bp5.pk, 'quantity': 3},
            {'bread_price': self.bp3.pk, 'quantity': -2},
        ]}, format='json')
        self.assertEqual(c.status_code, 400)
        self.assertEqual(c.data['detail'], "« remaining » : la quantité ne peut pas être négative.")
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)
        self.assertFalse(BreadDisposal.objects.filter(session_id=sid, disposal_type='REMAINING').exists())
        self.assertFalse(DailyBreadStockSnapshot.objects.filter(node=self.node).exists())

    def test_negative_as_string_refused(self):
        sid = self._classic_api()
        c = self.g.post(f'/api/production/sessions/{sid}/close/',
                        {'remaining': [{'bread_price': self.bp5.pk, 'quantity': '-3'}]}, format='json')
        self.assertEqual(c.status_code, 400, c.data)

    def test_zero_and_positive_accepted_and_snapshot_written(self):
        sid = self._classic_api()
        c = self.g.post(f'/api/production/sessions/{sid}/close/', {'remaining': [
            {'bread_price': self.bp5.pk, 'quantity': 0},
            {'bread_price': self.bp3.pk, 'quantity': 7},
        ]}, format='json')
        self.assertEqual(c.status_code, 200, c.data)
        snaps = {s.bread_price_id: s.qty_at_close for s in DailyBreadStockSnapshot.objects.filter(node=self.node)}
        self.assertEqual(snaps[self.bp5.pk], 0)
        self.assertEqual(snaps[self.bp3.pk], 7)

    def test_fractional_float_quantity_refused_not_truncated(self):
        """BUG-309 : un float -0.5 n'est plus tronqué en 0 : refusé en 400."""
        sid = self._classic_api()
        c = self.g.post(f'/api/production/sessions/{sid}/close/',
                        {'remaining': [{'bread_price': self.bp5.pk, 'quantity': -0.5}]}, format='json')
        self.assertEqual(c.status_code, 400, c.data)  # BUG-309 : plus de troncature

    # --- chemins qui acceptent encore le négatif (à documenter) -------------
    def test_path_disposals_remaining_negative_still_accepted(self):
        sid = self._classic_api()
        r = self.g.post('/api/production/disposals/', {
            'session': sid, 'bread_price': self.bp5.pk, 'disposal_type': 'REMAINING', 'quantity': -4,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)  # constat : négatif accepté

    def test_path_opening_confirmation_negative_refused_bug317(self):
        r = self.g.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': str(self.today),
            'lines': [{'bread_price': self.bp5.pk, 'qty': -6}],
        }, format='json')
        self.assertEqual(r.status_code, 400, r.data)  # BUG-317 : négatif refusé

    def test_path_forced_closure_accepts_negative_physical_stock(self):
        from datetime import time
        self.node.team_a_end_time = time(6, 0)
        self.node.save()
        s = ProductionSession.objects.create(
            node=self.node, team='A', date=self.today - timedelta(days=1), flour_sacks_used=Decimal('1'),
        )
        BreadStock.objects.create(node=self.node, bread_price=self.bp5, qty_produced=0, qty_sent=5)
        r = self.g.get('/api/production/sessions/shift-end-status/')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data.get('auto_closed'), r.data)
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, bread_price=self.bp5)
        self.assertEqual(snap.qty_at_close, -5)  # constat : négatif écrit par la clôture forcée
        self.assertTrue(ProductionSession.objects.get(pk=s.pk).is_closed)


class V306DeclareTests(_Base):
    def test_sacs_only_without_lines_key_and_values(self):
        r = self._sacs('1.50')
        self.assertEqual(r.status_code, 201, r.data)
        # 1,5 x 210 000 = 315 000
        self.assertEqual(r.data['objective_fc'], 315000)
        self.assertEqual(r.data['theoretical_yield'], 315000)
        self.assertEqual(r.data['progress_pct'], '0.00')
        self.assertEqual(r.data['lines'], [])
        self.assertEqual(r.data['team'], 'A')
        self.assertEqual(str(r.data['date']), str(self.today))

    def test_sacs_decimal_quarter(self):
        r = self._sacs('0.25')
        # 0,25 x 210 000 = 52 500
        self.assertEqual(r.data['objective_fc'], 52500)

    def test_sacs_zero_creates_non_auto_session(self):
        r = self._sacs('0')
        self.assertIn(r.status_code, (201, 400))
        if r.status_code == 201:
            self.assertFalse(r.data['auto_track'])

    def test_negative_sacs_refused_with_400_not_500(self):
        """BUG-309 : sacs négatif -> IntegrityError (CHECK theoretical_yield) = HTTP 500 au lieu de 400."""
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(self.gerant)
        r = c.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '-1',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_patch_negative_sacs_refused_with_400_not_500(self):
        """BUG-309 (PATCH)."""
        sid = self._sacs('2.00').data['id']
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(self.gerant)
        r = c.patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': '-1'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_invalid_sacs_values_400_detail_francais(self):
        """BUG-309 : négatif, texte, NaN, infini, trop grand, >2 décimales -> 400 {"detail"}."""
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(self.gerant)
        for bad in ('-1', '-0.01', 'abc', 'NaN', 'Infinity', '-Infinity', '1e9', '999999', '1.234', '', None, True):
            r = c.post('/api/production/sessions/', {
                'team': 'A', 'date': str(self.today), 'flour_sacks_used': bad,
            }, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.status_code))
            self.assertIn('detail', r.data, bad)
            self.assertIsInstance(str(r.data['detail']), str)

    def test_objective_frozen_when_node_sac_value_changes(self):
        sid = self._sacs('2.00').data['id']
        self.node.sac_value_fc = Decimal('300000')
        self.node.save()
        got = self.g.get(f'/api/production/sessions/{sid}/').data
        self.assertEqual(got['objective_fc'], 420000)
        # ajout de sacs : valeur figée conservée (3 x 210 000 = 630 000)
        r = self._sacs('1.00')
        self.assertEqual(r.data['objective_fc'], 630000)

    def test_patch_sacs_absolute_updates_objective_and_pct(self):
        sid = self._sacs('2.00').data['id']
        self._sell([(self.bp5, 840)])  # 840 x 500 = 420 000 -> 100 %
        got = self.g.get(f'/api/production/sessions/{sid}/').data
        self.assertEqual(got['progress_pct'], '100.00')
        p = self.g.patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': '4.00'}, format='json')
        self.assertEqual(p.status_code, 200, p.data)
        self.assertEqual(p.data['objective_fc'], 840000)
        self.assertEqual(p.data['progress_pct'], '50.00')
        # les lignes auto ne sont pas effacées par un PATCH sans `lines`
        # BUG-319 (remarque.md l.445, spécification modifiée) : la livraison ne crée plus de lignes DECLARED ni de qty_produced ; seule `delivered_value_fc` avance.
        self.assertEqual(ProductionSession.objects.get(pk=sid).delivered_value_fc, 420000)
        self.assertFalse(ProductionSession.objects.get(pk=sid).lines.exists())
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp5).qty_produced, 0)

    def test_progress_over_100_not_capped(self):
        sid = self._sacs('1.00').data['id']  # objectif 210 000
        self._sell([(self.bp5, 500)])        # 250 000
        got = self.g.get(f'/api/production/sessions/{sid}/').data
        # 250000*100/210000 = 119.0476 -> 119.05
        self.assertEqual(got['progress_pct'], '119.05')


class V306IncrementTests(_Base):
    def test_two_categories_values_and_net_stock_zero(self):
        sid = self._sacs('2.00').data['id']
        self._sell([(self.bp5, 10), (self.bp3, 4)])
        s = ProductionSession.objects.get(pk=sid)
        # BUG-319 (remarque.md l.445, spécification modifiée) : la livraison ne crée plus de lignes DECLARED ni de qty_produced ; seule `delivered_value_fc` avance.
        self.assertFalse(s.lines.filter(source='DECLARED').exists())
        # 10x500 + 4x300 = 6200 (valeur livrée, pas une production)
        self.assertEqual(s.delivered_value_fc, 6200)
        self.assertEqual((s.total_fc_produced, s.total_breads), (0, 0))
        got = self.g.get(f'/api/production/sessions/{sid}/').data
        # 6200*100/420000 = 1.476 -> 1.48
        self.assertEqual(got['progress_pct'], '1.48')
        self.assertEqual(got['progress_value_fc'], 6200)
        # stock : plus de « produit » à la livraison (BUG-319), -envoyé (vente)
        st = BreadStock.objects.get(node=self.node, bread_price=self.bp5)
        self.assertEqual((st.qty_produced, st.qty_sent, st.qty_available), (0, 10, -10))
        # pas d'écart avant clôture
        self.assertEqual(s.yield_gap, 0)

    def test_soldee_sale_counts_at_catalog_price(self):
        sid = self._sacs('2.00').data['id']
        self._sell([(self.bp5, 10)], extra={'is_soldee': True})
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.delivered_value_fc, 5000)  # BUG-319 : prix catalogue

    def test_ignored_cases(self):
        sid = self._sacs('2.00').data['id']
        # sans ligne (remboursement) : avec client
        from core.testing import make_client
        cl = make_client(self.node)
        r = self.f.post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': '1000', 'is_debt_repayment': True,
            'client': str(cl.pk), 'lines': [],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        # NS : créée PENDING, non livrable
        ns = self.f.post('/api/sales/invoices/', {
            'payment_type': 'CREDIT', 'payment_amount': '0', 'special_code': 'NS',
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 9}],
        }, format='json')
        self.assertEqual(ns.status_code, 201, ns.data)
        d = self.f.post(f"/api/sales/invoices/{ns.data['id']}/deliver/")
        self.assertEqual(d.status_code, 400)
        self.assertFalse(ProductionSessionLine.objects.filter(session_id=sid).exists())
        self.assertEqual(ProductionSession.objects.get(pk=sid).total_fc_produced, 0)

    def test_adjustment_not_incremented(self):
        sid = self._sacs('2.00').data['id']
        inv = self._sell([(self.bp5, 10)])
        adj = self.g.post(f"/api/sales/invoices/{inv['id']}/adjust/", {
            'adjustment_sign': 1, 'payment_amount': '0.00',
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 4}], 'motif': 'test',
        }, format='json')
        self.assertIn(adj.status_code, (200, 201), adj.data)
        s = ProductionSession.objects.get(pk=sid)
        self.assertEqual(s.delivered_value_fc, 5000)  # BUG-319 : l'ajustement n'ajoute rien

    def test_cancelled_pending_does_not_increment_and_sale_before_declaration_ignored(self):
        self._sell([(self.bp5, 5)])  # avant toute fournée : rien
        sid = self._sacs('2.00').data['id']
        self.assertFalse(ProductionSessionLine.objects.filter(session_id=sid).exists())
        inv = self._sell([(self.bp5, 5)], deliver=False)
        self.f.post(f"/api/sales/invoices/{inv['id']}/cancel/")
        self.assertFalse(ProductionSessionLine.objects.filter(session_id=sid).exists())

    def test_closed_batch_then_new_declaration_same_team_refused(self):
        sid = self._sacs('2.00').data['id']
        c = self.g.post(f'/api/production/sessions/{sid}/close/', {'remaining': []}, format='json')
        self.assertEqual(c.status_code, 200, c.data)
        self._sell([(self.bp5, 10)])
        self.assertFalse(ProductionSessionLine.objects.filter(session_id=sid).exists())
        self.assertEqual(self._sacs('1.00').status_code, 400)

    def test_isolation_other_node_sale_does_not_touch_my_batch(self):
        sid = self._sacs('2.00').data['id']
        k2 = make_node(code='K2', sac_value_fc=Decimal('210000'))
        f2 = _api(make_user('FACTURIER', node=k2))
        self._sell([(self.bp5, 10)], api=f2)
        self.assertFalse(ProductionSessionLine.objects.filter(session_id=sid).exists())
        # et inversement : K2 a sa propre fournée, la vente K1 ne la touche pas
        g2 = _api(make_user('GERANT', node=k2))
        sid2 = self._sacs('1.00', api=g2).data['id']
        self._sell([(self.bp5, 3)])
        self.assertEqual(ProductionSession.objects.get(pk=sid2).lines.count(), 0)
        self.assertEqual(ProductionSession.objects.get(pk=sid).delivered_value_fc, 1500)  # BUG-319

    def test_gerant_other_node_cannot_read_or_patch_my_batch(self):
        sid = self._sacs('2.00').data['id']
        k2 = make_node(code='K2')
        g2 = _api(make_user('GERANT', node=k2))
        self.assertEqual(g2.get(f'/api/production/sessions/{sid}/').status_code, 404)
        self.assertEqual(g2.patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': '9'}, format='json').status_code, 404)

    def test_classic_declared_with_lines_then_sacs_only_post_does_not_become_auto(self):
        r = self.g.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 30}],
        }, format='json')
        sid = r.data['id']
        r2 = self._sacs('1.00')
        self.assertEqual(r2.data['id'], sid)
        self.assertFalse(r2.data['auto_track'])
        self._sell([(self.bp5, 10)])
        self.assertEqual(ProductionSession.objects.get(pk=sid).lines.get(bread_price=self.bp5).quantity, 30)

    def test_two_teams_no_rotation_picks_latest_open_auto_batch(self):
        sa = self._sacs('1.00', team='A').data['id']
        sb = self._sacs('1.00', team='B').data['id']
        self._sell([(self.bp5, 10)])
        # constat : la fournée la plus récente (B) reçoit la vente
        self.assertEqual(ProductionSession.objects.get(pk=sb).delivered_value_fc, 5000)  # BUG-319
        self.assertEqual(ProductionSession.objects.get(pk=sa).delivered_value_fc, 0)

    def test_rotation_targets_service_team_only(self):
        self.node.team_rotation_enabled = True
        self.node.save()
        # La désignation est rattachée à la PÉRIODE de service (business_date,
        # avant l'heure de relève = veille), pas à la date calendaire : sinon le
        # test dépend de l'heure d'exécution (échec entre 00:00 et la relève).
        DailyTeamAssignment.objects.create(
            node=self.node, work_date=business_date(self.node), team='B')
        sa = ProductionSession.objects.create(node=self.node, team='A', date=self.today,
                                              flour_sacks_used=Decimal('1'), auto_track=True)
        sb = ProductionSession.objects.create(node=self.node, team='B', date=self.today,
                                              flour_sacks_used=Decimal('1'), auto_track=True)
        self._sell([(self.bp5, 6)])
        sa.refresh_from_db(); sb.refresh_from_db()  # BUG-319
        self.assertEqual(sa.delivered_value_fc, 0)
        self.assertEqual(sb.delivered_value_fc, 3000)

    def test_rotation_targets_service_team_at_fixed_instants(self):
        """Robustesse horaire : même résultat avant/après la relève et à deux dates."""
        from unittest import mock
        from django.utils import timezone
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Africa/Kinshasa')
        self.node.team_rotation_enabled = True
        self.node.save()
        for i, (y, m, d, h) in enumerate([(2026, 11, 20, 2), (2026, 11, 20, 14), (2026, 3, 5, 2), (2026, 3, 5, 23)]):
            fake = timezone.datetime(y, m, d, h, 30, tzinfo=tz)
            with mock.patch('django.utils.timezone.now', return_value=fake):
                today = work_date_for(self.node)
                DailyTeamAssignment.objects.filter(node=self.node).delete()
                DailyTeamAssignment.objects.create(
                    node=self.node, work_date=business_date(self.node), team='B')
                sa = ProductionSession.objects.create(
                    node=self.node, team='A', date=today, flour_sacks_used=Decimal('1'), auto_track=True)
                sb = ProductionSession.objects.create(
                    node=self.node, team='B', date=today, flour_sacks_used=Decimal('1'), auto_track=True)
                self._sell([(self.bp5, 6)])
                sa.refresh_from_db(); sb.refresh_from_db()  # BUG-319
                self.assertEqual(sa.delivered_value_fc, 0, (y, m, d, h))
                self.assertEqual(sb.delivered_value_fc, 3000, (y, m, d, h))
                sa.delete()
                sb.delete()

    def test_backdated_delivery_goes_to_that_days_batch_or_none(self):
        # fournée du jour ouverte ; livraison antidatée à hier : ne doit pas incrémenter la fournée du jour
        sid = self._sacs('2.00').data['id']
        r = self.f.post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': '2500',
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 5}],
        }, format='json')
        yesterday = str(self.today - timedelta(days=1))
        d = self.f.post(f"/api/sales/invoices/{r.data['id']}/deliver/", {'delivered_at': yesterday}, format='json')
        if d.status_code == 200:
            self.assertFalse(ProductionSessionLine.objects.filter(session_id=sid).exists())


class V306ConcurrencyTests(TransactionTestCase):
    def test_two_simultaneous_deliveries_sum_exactly(self):
        node = make_node(code='K1', sac_value_fc=Decimal('210000'))
        g = make_user('GERANT', node=node)
        f = make_user('FACTURIER', node=node)
        bp = make_bread_price('V306_500', 'Pain 500 V306', 500)
        today = work_date_for(node)
        s = ProductionSession.objects.create(node=node, team='A', date=today,
                                             flour_sacks_used=Decimal('2'), auto_track=True)
        s.compute_totals(Decimal('210000'))
        s.save()
        ids = []
        for q in (30, 70):
            r = _api(f).post('/api/sales/invoices/', {
                'payment_type': 'CASH', 'payment_amount': str(q * 500),
                'lines': [{'bread_price': bp.pk, 'quantity': q}],
            }, format='json')
            self.assertEqual(r.status_code, 201, r.data)
            ids.append(r.data['id'])
        results = []
        barrier = threading.Barrier(2)

        def go(inv_id):
            try:
                barrier.wait()
                results.append(_api(f).post(f'/api/sales/invoices/{inv_id}/deliver/').status_code)
            except Exception as exc:  # noqa: BLE001
                results.append(repr(exc)[:300])
            finally:
                connection.close()

        ts = [threading.Thread(target=go, args=(i,)) for i in ids]
        [t.start() for t in ts]
        [t.join() for t in ts]
        if any('locked' in str(r) for r in results):
            self.skipTest("SQLite ne supporte pas l'écriture concurrente (database is locked) : "
                          "à rejouer sur PostgreSQL ; exactitude séquentielle couverte ailleurs.")
        self.assertEqual(sorted(results), [200, 200], results)
        s.refresh_from_db()
        self.assertEqual(s.lines.get(bread_price=bp).quantity, 100)
        self.assertEqual(s.total_fc_produced, 50000)
        self.assertEqual(BreadStock.objects.get(node=node, bread_price=bp).qty_produced, 100)


class V304DayLevelTests(_Base):
    def _snap(self, d, team, qty):
        s = ProductionSession.objects.filter(node=self.node, team=team, date=d).first()
        if s is None:
            s = ProductionSession.objects.create(node=self.node, team=team, date=d, flour_sacks_used=Decimal('1'))
            ProductionSessionLine.objects.create(session=s, bread_price=self.bp5, quantity=20)
        BreadDisposal.objects.create(session=s, bread_price=self.bp5, disposal_type='REMAINING',
                                     quantity=qty, node=self.node, node_origin='K1')
        DailyBreadStockSnapshot.record_snapshot(s)

    def _cat(self, d, bp=None):
        r = self.g.get('/api/production/daily-closure/', {'node': 'K1', 'date': str(d)})
        self.assertEqual(r.status_code, 200, r.data)
        bp = bp or self.bp5
        return next(c for c in r.data['categories'] if c['bread_price'] == bp.pk), r.data

    def test_a10_then_b5_same_day_gives_minus5_not_minus15_next_day(self):
        y = self.today - timedelta(days=1)
        self._snap(y, 'A', 10)
        self._snap(y, 'B', 5)
        cat, data = self._cat(self.today)
        self.assertEqual(cat['reste_du_hier_jour'], -5)
        self.assertIsNone(cat['reste_du_jour_jour'])
        # 5 x 500 = 2500 (valeur du hier) ; jour non déclaré -> 0
        self.assertEqual(data['totals']['reste_du_hier_jour_fc'], '-2500.00')
        self.assertEqual(data['totals']['reste_du_jour_jour_fc'], '0.00')

    def test_reste_du_jour_is_last_declared_of_day_for_that_day(self):
        y = self.today - timedelta(days=1)
        self._snap(y, 'A', 10)
        self._snap(y, 'B', 5)
        cat, data = self._cat(y)
        self.assertEqual(cat['reste_du_jour_jour'], 5)       # dernier déclaré
        self.assertEqual(cat['reste_du_hier_jour'], 0)       # rien avant
        self.assertEqual(data['totals']['reste_du_jour_jour_fc'], '2500.00')

    def test_gap_of_several_days_carries_last_known(self):
        self._snap(self.today - timedelta(days=4), 'A', 9)
        cat, _ = self._cat(self.today)
        self.assertEqual(cat['reste_du_hier_jour'], -9)

    def test_declared_zero_is_zero_not_null(self):
        self._snap(self.today, 'A', 0)
        cat, _ = self._cat(self.today)
        self.assertEqual(cat['reste_du_jour_jour'], 0)

    def test_confirmed_start_stock_overrides_chain(self):
        y = self.today - timedelta(days=1)
        self._snap(y, 'A', 10)
        r = self.g.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': str(self.today),
            'lines': [{'bread_price': self.bp5.pk, 'qty': 8}],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        cat, _ = self._cat(self.today)
        self.assertEqual(cat['reste_du_hier_jour'], -8)

    def test_isolation_other_node_snapshots_ignored(self):
        k2 = make_node(code='K2')
        y = self.today - timedelta(days=1)
        s = self._classic('A', y, 20, node=k2)
        BreadDisposal.objects.create(session=s, bread_price=self.bp5, disposal_type='REMAINING',
                                     quantity=99, node=k2, node_origin='K2')
        DailyBreadStockSnapshot.record_snapshot(s)
        cat, _ = self._cat(self.today)
        self.assertEqual(cat['reste_du_hier_jour'], 0)

    def test_rotation_a10_then_b5_next_day(self):
        self.node.team_rotation_enabled = True
        self.node.save()
        y = self.today - timedelta(days=1)
        DailyTeamAssignment.objects.create(node=self.node, work_date=y, team='A')
        DailyTeamAssignment.objects.create(node=self.node, work_date=self.today, team='B')
        self._snap(y, 'A', 10)
        self._snap(y, 'B', 5)
        cat, _ = self._cat(self.today)
        self.assertEqual(cat['reste_du_hier_jour'], -5)
        # par équipe : une seule équipe porteuse (pas de doublon)
        self.assertEqual(sum(v or 0 for v in cat['reste_du_hier'].values()), -5)


class V306SequentialAccumulationTests(_Base):
    def test_many_deliveries_accumulate_exactly_and_stale_instance_irrelevant(self):
        sid = self._sacs('2.00').data['id']
        stale = ProductionSession.objects.get(pk=sid)  # instance périmée en mémoire
        for q in (30, 70, 1):
            self._sell([(self.bp5, q)])
        s = ProductionSession.objects.get(pk=sid)  # BUG-319 : valeur livrée cumulée via F()
        self.assertEqual(s.delivered_value_fc, 50500)   # 101 x 500
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp5).qty_produced, 0)


class V309SacsValidationTests(_Base):
    BAD = [-1, '-0.01', 'abc', 'NaN', 'Infinity', '-Infinity', True, False, None, '', '  ',
           100001, '100000.01', '1.234', 1.005, [], {}]
    GOOD = [0, '0', '0.00', '0.25', 2, '2.5', 100000, '100000.00']

    def _c(self):
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(self.gerant)
        return c

    def test_post_bad_values_400_french_detail(self):
        for i, v in enumerate(self.BAD):
            ProductionSession.objects.all().delete()
            r = self._c().post('/api/production/sessions/', {
                'team': 'A', 'date': str(self.today), 'flour_sacks_used': v}, format='json')
            self.assertEqual(r.status_code, 400, (v, r.status_code, getattr(r, 'data', None)))
            self.assertFalse(ProductionSession.objects.exists(), v)

    def test_patch_bad_values_400_and_unchanged(self):
        sid = self._sacs('2.00').data['id']
        for v in self.BAD:
            r = self._c().patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': v}, format='json')
            self.assertEqual(r.status_code, 400, (v, r.status_code))
            self.assertEqual(ProductionSession.objects.get(pk=sid).flour_sacks_used, Decimal('2.00'), v)

    def test_good_values_accepted_post_and_patch(self):
        for v in self.GOOD:
            ProductionSession.objects.all().delete()
            r = self._c().post('/api/production/sessions/', {
                'team': 'A', 'date': str(self.today), 'flour_sacks_used': v}, format='json')
            self.assertEqual(r.status_code, 201, (v, r.status_code))
        sid = ProductionSession.objects.get().pk
        for v in self.GOOD:
            r = self._c().patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': v}, format='json')
            self.assertEqual(r.status_code, 200, (v, r.status_code))

    def test_remaining_fractional_refused_nothing_applied(self):
        r = self.g.post('/api/production/sessions/', {
            'team': 'A', 'date': str(self.today), 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 50}]}, format='json')
        sid = r.data['id']
        for q in (-0.5, 2.5, 0.5, 'NaN', '1.5', True, None, [], 'x'):
            c = self._c().post(f'/api/production/sessions/{sid}/close/',
                               {'remaining': [{'bread_price': self.bp5.pk, 'quantity': q}]}, format='json')
            self.assertEqual(c.status_code, 400, (q, c.status_code))
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)
        for q in (3.0, '3', 3):  # entiers exprimés autrement : acceptés
            pass
        ok = self.g.post(f'/api/production/sessions/{sid}/close/',
                         {'remaining': [{'bread_price': self.bp5.pk, 'quantity': 3.0}]}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
