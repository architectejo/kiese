"""Cycle 3, partie C (testeur-tresorerie, Dev C, 2026-11-22-c4) : verification de
BUG-810/815/818 (rouverts) et BUG-830 a 839 sous de nouveaux angles, puis defauts
nouveaux (BUG-840 a 843). Donnees fictives uniquement.

Les anomalies confirmees portent un test `@expectedFailure` reference BUG-84x.
"""
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure, mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from blockchain.models import BlockchainSnapshot, TamperAlert
from core.models import ActivityLog, Node, SystemNotification
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice
from treasury.models import (
    CashbookEntry, CashClosure, DailySavings, DisbursementVoucher, FacturierReport,
    JournalEntry, LocalExpense,
)
from treasury.tests.test_cycle1_tresorerie_c import BILLS, Base, cl, rows, today
from treasury.tests.test_reports_closures import _make_invoice


def n_queries(fn):
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx)


# =====================================================================
# 1. BUG-810 / 815 / 818 : nouveaux angles
# =====================================================================
class V810(Base):
    BAD = (True, False, 1.5, 0, [], [1], {'a': 1}, '1.0', 'abc', ' ', '999999', '[1]')

    def test_body_node_garbage_sweep_on_all_hq_posts(self):
        calls = [
            ('/api/treasury/closures/', {'date': str(today()), **{b: 0 for b in BILLS}}),
            ('/api/treasury/expenses/', {'description': 'x', 'amount': '10', 'category': self.cat.id, 'date': str(today())}),
            ('/api/treasury/reports/', {'date': str(today())}),
            ('/api/treasury/reports/generate/', {}),
            ('/api/treasury/journal/', {'date': str(today()), 'imput': 'EAU', 'label': 'x', 'exit_amount': '1'}),
            ('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '10', 'flour_sacks': '1'}),
        ]
        bad = []
        for url, body in calls:
            for nv in self.BAD:
                r = cl(self.dirn).post(url, {**body, 'node': nv}, format='json')
                if r.status_code != 400:
                    bad.append((url, nv, r.status_code))
        self.assertEqual(bad, [])
        self.assertEqual(CashClosure.objects.count() + LocalExpense.objects.count() + JournalEntry.objects.count()
                         + DailySavings.objects.count() + FacturierReport.objects.count(), 0)

    def test_multipart_node_garbage_never_500(self):
        for nv in ('abc', 'true', '1.5', ''):
            r = cl(self.dirn).post('/api/treasury/expenses/', {
                'description': 'x', 'amount': '10', 'category': self.cat.id, 'date': str(today()), 'node': nv})
            self.assertLess(r.status_code, 500, (nv, r.status_code))

    def test_hq_patch_savings_node_bool_float_refused(self):
        sv = DailySavings.objects.create(node=self.n1, date=today(), daily_revenue=Dc('10'),
                                         savings_rate=Dc('0.1'), savings_amount=Dc('1'))
        for nv in (True, 1.5, 'abc'):
            r = cl(self.dirn).patch(f'/api/treasury/savings/{sv.pk}/', {'node': nv}, format='json')
            self.assertLess(r.status_code, 500, (nv, r.content))
        self.assertEqual(DailySavings.objects.get(pk=sv.pk).node_id, self.n1.pk)

    # BUG-810 (reouvert 2) : PATCH `node: true` d'un rapport = nœud de pk 1 (perform_update sans _body_node)
    def test_BUG_810_report_patch_node_bool_float_moves_report(self):
        rep = self.report(self.n1, 'A', '100')
        self.assertNotEqual(self.n1.pk, 1)
        for nv in (True, 1.5):
            cl(self.dirn).patch(f'/api/treasury/reports/{rep.pk}/', {'node': nv}, format='json')
        self.assertEqual(FacturierReport.objects.get(pk=rep.pk).node_id, self.n1.pk)


class V815(Base):
    def test_closure_patch_same_date_and_other_keeps_ok(self):
        c = self.close(self.g1, {'bills_50': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'x'}, format='json')
        r = cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/", {'date': str(today()), 'bills_100': 2}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Dc(r.json()['physical_cash_total']), Dc('250'))

    def test_savings_patch_self_date_ok_and_other_node_same_day_400(self):
        a = DailySavings.objects.create(node=self.n1, date=today(), daily_revenue=Dc('10'),
                                        savings_rate=Dc('0.1'), savings_amount=Dc('1'))
        DailySavings.objects.create(node=self.n2, date=today(), daily_revenue=Dc('10'),
                                    savings_rate=Dc('0.1'), savings_amount=Dc('1'))
        r = cl(self.g1).patch(f'/api/treasury/savings/{a.pk}/', {'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = cl(self.dirn).put(f'/api/treasury/savings/{a.pk}/', {
            'node': self.n2.id, 'date': str(today()), 'daily_revenue': '10', 'flour_sacks': '1'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    # BUG-841 : meme defaut que BUG-815 sur le rapport facturier
    def test_BUG_841_report_patch_date_to_existing_day_is_400_not_500(self):
        y = today() - timedelta(days=1)
        fac = self.fac
        for d in (y, today()):
            FacturierReport.objects.create(node=self.n1, facturier=fac, team='A', date=d,
                                           total_cash_sales=Dc('1'), theoretical_cash=Dc('1'), node_origin='C1')
        rep = FacturierReport.objects.get(node=self.n1, facturier=fac, date=today())
        r = cl(self.g1).patch(f'/api/treasury/reports/{rep.pk}/', {'date': str(y)}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)


class V818(Base):
    def test_period_params_sweep_all_endpoints(self):
        bad = []
        garbage = ('garbage', '2026-02-30', '2026-13-45', '99999-01-01', '0000-00-00', '%00', '٢٠٢٦-٠١-٠١', '2026-1-1x')
        urls = ['cashbook', 'cashbook/period_summary', 'vouchers/final_report', 'vouchers', 'closures',
                'reports', 'expenses', 'journal', 'savings', 'direction-cash-counts']
        for u in urls:
            for g in garbage:
                for p in ('date_from', 'date_to', 'date'):
                    r = cl(self.dirn).get(f'/api/treasury/{u}/?{p}={g}')
                    if r.status_code >= 500:
                        bad.append((u, p, g, r.status_code))
        for g in garbage:
            r = cl(self.dirn).get(f'/api/treasury/journal/suggested_ca/?node={self.n1.id}&date={g}')
            if r.status_code >= 500:
                bad.append(('suggested_ca', g, r.status_code))
        self.assertEqual(bad, [])

    def test_generate_date_variants_never_500(self):
        for v in (True, 123, 20260101, [], {}, '2026-02-30xyz', '0001-01-01', '9999-12-31', '2026-02-30'):
            r = cl(self.g1).post('/api/treasury/reports/generate/', {'date': v}, format='json')
            self.assertLess(r.status_code, 500, (v, r.status_code))

    def test_post_body_dates_never_500(self):
        for v in ('zz', '2026-02-30', 123, [], None):
            for url, body in (
                ('/api/treasury/closures/', {b: 0 for b in BILLS}),
                ('/api/treasury/expenses/', {'description': 'x', 'amount': '1', 'category': self.cat.id}),
                ('/api/treasury/vouchers/', {'motif': 'x', 'bills_50': 1}),
                ('/api/treasury/savings/', {'daily_revenue': '1'}),
                ('/api/treasury/journal/', {'imput': 'EAU', 'label': 'x', 'exit_amount': '1'}),
                ('/api/treasury/direction-cash-counts/', {'bills_50': 1}),
            ):
                r = cl(self.dirn).post(url, {**body, 'date': v, 'node': self.n1.id}, format='json')
                self.assertLess(r.status_code, 500, (url, v, r.status_code))


# =====================================================================
# 2. BUG-830 : voisinage (generate sur un jour confirme)
# =====================================================================
class V830(Base):
    def setUp(self):
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 C3', unit_price=300)
        self.client_obj = make_client(self.n1)
        self.facB = make_user('FACTURIER', self.n1, team='B')

    # BUG-840 : generate recree/recalcule des rapports un jour dont la cloture est CONFIRMEE
    def test_BUG_840_generate_on_confirmed_day_changes_pushed_amount(self):
        _make_invoice(self.n1, self.fac, 'A', self.client_obj, self.bread, 5, Invoice.PaymentType.CASH)   # 1500
        r = cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        _make_invoice(self.n1, self.facB, 'B', self.client_obj, self.bread, 10, Invoice.PaymentType.CASH)  # 3000
        FacturierReport.objects.filter(team='B').delete()
        c = self.close(self.g1, {'bills_1000': 1, 'bills_500': 1}).json()
        v = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        self.assertEqual(v.status_code, 200, v.content)
        confirmed = Dc(v.json()['net_cash'])
        r = cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
        pushed = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(pushed.status_code, 201, pushed.content)
        # soit generate est refuse (400), soit le montant inscrit reste le montant confirme
        self.assertTrue(r.status_code == 400 or Dc(pushed.json()['entry_amount']) == confirmed,
                        (r.status_code, confirmed, pushed.json()['entry_amount']))


# =====================================================================
# 3. BUG-832 / 836 : blockchain
# =====================================================================
class V832(Base):
    def tamper(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 2}).json()
        self.versement(c['id'])
        e = CashbookEntry.objects.get()
        CashbookEntry.objects.filter(pk=e.pk).update(label='falsifie')
        return e

    def test_alerts_and_snapshots_write_methods_405_for_all_hq_and_403_for_others(self):
        e = self.tamper()
        cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        a = TamperAlert.objects.first()
        self.assertIsNotNone(a)
        s = BlockchainSnapshot.objects.first()
        for u in (self.adm, self.dirn, self.compt):
            for m in ('post', 'put', 'patch', 'delete'):
                for url in (f'/api/blockchain/alerts/{a.pk}/', '/api/blockchain/alerts/',
                            f'/api/blockchain/snapshots/{s.pk}/', '/api/blockchain/snapshots/'):
                    r = getattr(cl(u), m)(url, {'is_resolved': True}, format='json')
                    self.assertEqual(r.status_code, 405, (u.role, m, url, r.status_code))
        for u in (self.g1, self.fac, self.liv):
            self.assertEqual(cl(u).get('/api/blockchain/alerts/').status_code, 403)
            self.assertEqual(cl(u).post(f'/api/blockchain/alerts/{a.pk}/resolve/').status_code, 403)
            self.assertEqual(cl(u).post('/api/blockchain/snapshots/run_check/', {}, format='json').status_code, 403)
            self.assertEqual(cl(u).get('/api/blockchain/snapshots/global_status/').status_code, 403)
        self.assertEqual(cl(self.dirn).get('/api/blockchain/snapshots/run_check/').status_code, 405)
        self.assertTrue(TamperAlert.objects.filter(pk=a.pk, is_resolved=False).exists())

    def test_resolve_is_traced_once_and_double_resolve_400(self):
        self.tamper()
        cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        a = TamperAlert.objects.get(is_resolved=False)
        r = cl(self.compt).post(f'/api/blockchain/alerts/{a.pk}/resolve/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(cl(self.compt).post(f'/api/blockchain/alerts/{a.pk}/resolve/').status_code, 400)
        a.refresh_from_db()
        self.assertEqual(a.resolved_by_id, self.compt.pk)
        self.assertEqual(cl(self.compt).post('/api/blockchain/alerts/00000000-0000-0000-0000-000000000000/resolve/').status_code, 404)

    def test_run_check_and_integrity_check_same_verdict_and_alert_dedup(self):
        self.tamper()
        for _ in range(3):
            r = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
            self.assertFalse(r.json()['all_intact'])
        self.assertEqual(TamperAlert.objects.filter(is_resolved=False).count(), 1)
        self.assertFalse(cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()['chain_valid'])
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertFalse(gs['all_intact'])
        self.assertFalse(gs['never_checked'])

    # BUG-842 : integrity_check (GET) cree une notification DANGER a CHAQUE appel
    def test_BUG_842_integrity_check_get_duplicates_notifications(self):
        self.tamper()
        for _ in range(3):
            cl(self.dirn).get('/api/treasury/cashbook/integrity_check/')
        n = SystemNotification.objects.filter(title__startswith='Alerte Blockchain').count()
        self.assertLessEqual(n, 1, n)

    # BUG-843 : global_status ne signale pas les boulangeries jamais verifiees
    def test_BUG_843_global_status_intact_while_some_nodes_never_checked(self):
        self.report(self.n2, 'A', '5000')
        c = self.close(self.g2, {'bills_5000': 1}).json()
        self.versement(c['id'])
        cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {'node': self.n1.id}, format='json')
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        # une seule boulangerie verifiee sur toutes : pas « intact » sans reserve
        self.assertFalse(gs['all_intact'] and Node.objects.count() > gs['nodes_checked'], gs)


# =====================================================================
# 4. BUG-839 : versement
# =====================================================================
class V839(Base):
    def test_failed_append_leaves_closure_and_ledger_untouched_then_replay_ok(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 2}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        before = CashClosure.objects.get(pk=c['id'])
        with mock.patch('treasury.services.append_cashbook_entry', side_effect=RuntimeError('boom')):
            r = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual(CashbookEntry.objects.count(), 0)
        after = CashClosure.objects.get(pk=c['id'])
        self.assertEqual((before.net_cash, before.cash_gap, before.is_validated),
                         (after.net_cash, after.cash_gap, after.is_validated))
        ok = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json').status_code, 400)
        self.assertEqual(CashbookEntry.objects.count(), 1)

    def test_out_of_order_versements_keep_chain_and_balance(self):
        self.report(self.n1, 'A', '7000')
        self.report(self.n2, 'A', '3000')
        c2 = self.close(self.g2, {'bills_1000': 3}).json()
        c1 = self.close(self.g1, {'bills_1000': 7}).json()
        self.versement(c1['id'])
        self.versement(c2['id'])
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(last.running_balance, Dc('10000'))
        self.assertTrue(self.chain_ok())
        vr = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x', 'bills_5000': 1}, format='json')
        self.assertEqual(vr.status_code, 201, vr.content)
        over = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x', 'bills_20000': 1}, format='json')
        self.assertEqual(over.status_code, 400)
        self.assertEqual(DisbursementVoucher.objects.count(), 1)
        self.assertTrue(self.chain_ok())

    def test_push_rolled_back_when_net_exceeds_range_and_closure_not_versee(self):
        c = self.close(self.g1, {'bills_50': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        r = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(r.status_code, 201, r.content)      # net = 0 -> ecriture a 0 FC
        self.assertEqual(CashbookEntry.objects.get().entry_amount, Dc('0'))


# =====================================================================
# 5. BUG-837 / 838 : voisinage (journalisation, N+1)
# =====================================================================
class V837(Base):
    # BUG-844 : rapports, epargne, journal et resoumission de cloture sans log_activity
    def test_BUG_844_activity_log_on_money_writes_of_neighbours(self):
        missing = []

        def logged(label, fn):
            before = ActivityLog.objects.count()
            fn()
            if ActivityLog.objects.count() == before:
                missing.append(label)

        g = make_user('GERANT', self.n2, team='A')
        rep = {}
        logged('report.create', lambda: rep.update(r=cl(g).post('/api/treasury/reports/', {'date': str(today())}, format='json').json()))
        logged('report.delete', lambda: cl(g).delete(f"/api/treasury/reports/{rep['r']['id']}/"))
        sv = {}
        logged('savings.create', lambda: sv.update(r=cl(self.g1).post('/api/treasury/savings/', {
            'date': str(today()), 'daily_revenue': '1000', 'flour_sacks': '1'}, format='json').json()))
        logged('savings.patch', lambda: cl(self.g1).patch(f"/api/treasury/savings/{sv['r']['id']}/", {'daily_revenue': '2000'}, format='json'))
        logged('journal.create', lambda: cl(self.g1).post('/api/treasury/journal/', {
            'date': str(today()), 'imput': 'EAU', 'label': 'x', 'exit_amount': '10'}, format='json'))
        self.assertEqual(missing, [])


class V838(Base):
    def test_lists_have_constant_query_count(self):
        urls = ['expenses', 'reports', 'closures', 'cashbook', 'journal', 'savings', 'vouchers',
                'direction-cash-counts', 'closures/versements']
        # 2 jeux de donnees de tailles differentes
        for i in range(3):
            n = make_node(f'Q{i}', f'Q{i}')
            self.report(n, 'A', '1000')
            self.expense(make_user('GERANT', n), '10')
        small = {u: n_queries(lambda u=u: cl(self.dirn).get(f'/api/treasury/{u}/')) for u in urls}
        for i in range(3, 12):
            n = make_node(f'Q{i}', f'Q{i}')
            self.report(n, 'A', '1000')
            self.expense(make_user('GERANT', n), '10')
        big = {u: n_queries(lambda u=u: cl(self.dirn).get(f'/api/treasury/{u}/')) for u in urls}
        self.assertEqual(small, big)

    # BUG-845 : global_status = 1 + 1 requete (+ serializer) par boulangerie
    def test_BUG_845_global_status_n_plus_one(self):
        def snaps(k):
            for i in range(k):
                n = make_node(f'G{k}{i}', f'G{k}{i}')
                BlockchainSnapshot.objects.create(node=n, snapshot_date=today(), total_entries=0,
                                                  tampered_entries=0, is_intact=True)
        cl(self.dirn).get('/api/blockchain/snapshots/global_status/')  # chauffe : cree la Config singleton
        snaps(3)
        a = n_queries(lambda: cl(self.dirn).get('/api/blockchain/snapshots/global_status/'))
        snaps(9)
        b = n_queries(lambda: cl(self.dirn).get('/api/blockchain/snapshots/global_status/'))
        self.assertEqual(a, b)


# =====================================================================
# 6. BUG-831 / 833 / 834 / 835 : nouveaux angles
# =====================================================================
BIG = '999999999999.99'


class V831to835(Base):
    def test_BUG_831_tomorrow_refused_today_and_past_accepted(self):
        t = today()
        for url, body in (('/api/treasury/savings/', {'daily_revenue': '10', 'flour_sacks': '1'}),
                          ('/api/treasury/vouchers/', {'motif': 'x', 'bills_50': 1})):
            r = cl(self.dirn).post(url, {**body, 'date': str(t + timedelta(days=1)), 'node': self.n1.id}, format='json')
            self.assertEqual(r.status_code, 400, (url, r.content))
        r = cl(self.dirn).post('/api/treasury/savings/', {'daily_revenue': '10', 'flour_sacks': '1',
                                                           'date': str(t), 'node': self.n1.id}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        # PATCH vers le futur
        sid = r.json()['id']
        r = cl(self.dirn).patch(f'/api/treasury/savings/{sid}/', {'date': str(t + timedelta(days=2))}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_BUG_833_monthly_report_two_nodes_consistent(self):
        for n, a in ((self.n1, '1000'), (self.n2, '400')):
            JournalEntry.objects.create(node=n, date=today(), imput='CA', label='x', entry_amount=Dc(a),
                                        running_balance=Dc(a), month_carried=Dc('0'))
        d = cl(self.dirn).get('/api/treasury/journal/monthly_report/').json()
        self.assertEqual((Dc(d['total_entries']), Dc(d['final_balance'])), (Dc('1400'), Dc('1400')))
        d = cl(self.dirn).get(f'/api/treasury/journal/monthly_report/?node={self.n2.id}').json()
        self.assertEqual(Dc(d['final_balance']), Dc('400'))

    # BUG-847 : meme defaut que BUG-834 sur le journal de caisse (solde progressif hors plage)
    def test_BUG_847_journal_running_balance_overflow_is_400_not_500(self):
        codes = []
        for _ in range(2):
            r = cl(self.dirn).post('/api/treasury/journal/', {
                'date': str(today()), 'imput': 'CA', 'label': 'x', 'entry_amount': BIG, 'node': self.n1.id}, format='json')
            codes.append(r.status_code)
        self.assertLess(max(codes), 500, codes)

    def test_BUG_834_neighbours_overflow_never_500(self):
        bad = []
        r = cl(self.dirn).post('/api/treasury/savings/', {
            'date': str(today()), 'daily_revenue': BIG, 'savings_rate': '1', 'flour_sacks': '1', 'node': self.n1.id}, format='json')
        if r.status_code >= 500:
            bad.append(('savings', r.status_code))
        r = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x', 'bills_20000': 100000,
                                                           'bills_10000': 100000, 'bills_5000': 100000}, format='json')
        if r.status_code >= 500:
            bad.append(('voucher', r.status_code))
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/', {'date': str(today()), 'bills_20000': 100000,
                                                                        'bills_10000': 100000}, format='json')
        if r.status_code >= 500:
            bad.append(('count', r.status_code))
        self.assertEqual(bad, [])

    def test_BUG_835_count_with_voucher_and_out_of_order(self):
        self.report(self.n1, 'A', '9000')
        self.report(self.n2, 'A', '4000')
        c1 = self.close(self.g1, {'bills_1000': 9}).json()
        c2 = self.close(self.g2, {'bills_1000': 4}).json()
        self.versement(c2['id'])
        self.versement(c1['id'])
        cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x', 'bills_1000': 3}, format='json')
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/', {'date': str(today()), 'bills_10000': 1}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['theoretical_balance']), Dc('10000'))
        self.assertEqual(Dc(r.json()['cash_gap']), Dc('0'))
        self.assertTrue(self.chain_ok())
