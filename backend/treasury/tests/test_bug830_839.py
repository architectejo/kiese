"""Non-regression BUG-830 a 839 + rouverts BUG-810 / 815 / 818 (dev-backend, 2026-11-22c8).
Donnees fictives uniquement. Chaque test echouait avant la correction."""
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import mock

from django.db import OperationalError, connection
from django.test.utils import CaptureQueriesContext

from blockchain.models import BlockchainSnapshot, TamperAlert
from core.models import ActivityLog, Config
from core.testing import make_user
from treasury.models import (
    CashbookEntry, CashClosure, DailySavings, DisbursementVoucher, FacturierReport,
    JournalEntry, LocalExpense,
)
from treasury.services import ClosureAlreadyPromotedError, promote_closure_to_cashbook
from treasury.tests.test_cycle1_tresorerie_c import BILLS, Base, cl, today
from treasury.views import append_cashbook_entry

BIG = '999999999999.99'


class Bug830Reports(Base):
    def test_team_cannot_be_patched(self):
        g = make_user('GERANT', self.n2, team='B')
        rid = cl(g).post('/api/treasury/reports/', {'date': str(today())}, format='json').json()['id']
        r = cl(g).patch(f'/api/treasury/reports/{rid}/', {'team': 'Z'}, format='json')
        self.assertLess(r.status_code, 500)
        self.assertEqual(FacturierReport.objects.get(pk=rid).team, 'B')

    def test_patch_date_into_confirmed_day_refused(self):
        y = today() - timedelta(days=1)
        rep = self.report(self.n1, 'A', '5000', date=y)
        self.report(self.n1, 'B', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        r = cl(self.g1).patch(f'/api/treasury/reports/{rep.id}/', {'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(FacturierReport.objects.get(pk=rep.id).date, y)

    def test_patch_date_out_of_confirmed_day_and_delete_refused(self):
        rep = self.report(self.n1, 'A', '5000')
        c = self.close(self.g1, {'bills_5000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        y = str(today() - timedelta(days=1))
        self.assertEqual(cl(self.g1).patch(f'/api/treasury/reports/{rep.id}/', {'date': y}, format='json').status_code, 400)
        self.assertEqual(cl(self.g1).delete(f'/api/treasury/reports/{rep.id}/').status_code, 400)
        self.assertTrue(FacturierReport.objects.filter(pk=rep.id).exists())

    def test_unconfirmed_day_report_can_still_be_deleted(self):
        rep = self.report(self.n1, 'A', '5000')
        self.assertEqual(cl(self.g1).delete(f'/api/treasury/reports/{rep.id}/').status_code, 204)


class Bug831FutureDates(Base):
    def test_savings_and_voucher_future_date_refused(self):
        fut = str(today() + timedelta(days=40))
        r = cl(self.g1).post('/api/treasury/savings/', {'date': fut, 'daily_revenue': '1000', 'flour_sacks': '1'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        append_cashbook_entry(node=self.n1, date=today(), piece_number='VC-C1-1', imputation='7000',
                              label='seed', entry_amount=Dc('100000'), node_origin='C1')
        r = cl(self.dirn).post('/api/treasury/vouchers/', {'date': fut, 'motif': 'm', 'bills_5000': 1}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(DailySavings.objects.exists() or DisbursementVoucher.objects.exists())
        self.assertEqual(CashbookEntry.objects.count(), 1)

    def test_savings_patch_to_future_refused(self):
        d = cl(self.g1).post('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '1000', 'flour_sacks': '1'}, format='json').json()
        r = cl(self.g1).patch(f"/api/treasury/savings/{d['id']}/", {'date': str(today() + timedelta(days=3))}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class Bug832Alerts(Base):
    def test_alerts_are_read_and_resolve_only(self):
        a = TamperAlert.objects.create(node=self.n1, affected_model='CashbookEntry', description='alerte')
        u = f'/api/blockchain/alerts/{a.id}/'
        self.assertEqual(cl(self.dirn).delete(u).status_code, 405)
        self.assertEqual(cl(self.dirn).patch(u, {'is_resolved': True}, format='json').status_code, 405)
        self.assertEqual(cl(self.dirn).put(u, {}, format='json').status_code, 405)
        self.assertEqual(cl(self.dirn).post('/api/blockchain/alerts/', {
            'node': self.n1.id, 'affected_model': 'X', 'description': 'f'}, format='json').status_code, 405)
        a.refresh_from_db()
        self.assertFalse(a.is_resolved)
        self.assertEqual(cl(self.dirn).get(u).status_code, 200)
        self.assertEqual(cl(self.dirn).post(u + 'resolve/').status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.resolved_by_id, self.dirn.id)
        self.assertEqual(cl(self.g1).get('/api/blockchain/alerts/').status_code, 403)


class Bug833MonthlyReport(Base):
    def test_hq_without_node_aggregates_consistently(self):
        for g, amt in ((self.g1, '1000'), (self.g2, '400')):
            cl(g).post('/api/treasury/journal/', {'date': str(today()), 'imput': 'AUTRE', 'label': 'x',
                                                   'entry_amount': amt, 'exit_amount': '0'}, format='json')
        d = today()
        r = cl(self.dirn).get(f'/api/treasury/journal/monthly_report/?month={d.month}&year={d.year}').json()
        self.assertEqual((Dc(r['total_entries']), Dc(r['final_balance']), Dc(r['month_carried'])),
                         (Dc('1400'), Dc('1400'), Dc('0')))
        r1 = cl(self.dirn).get(f'/api/treasury/journal/monthly_report/?month={d.month}&year={d.year}&node={self.n2.id}').json()
        self.assertEqual(Dc(r1['final_balance']), Dc('400'))


class Bug834Overflow(Base):
    def test_gap_overflow_is_400_and_nothing_written(self):
        self.assertEqual(self.expense(self.g1, BIG).status_code, 201)
        r = self.close(self.g1, {'bills_50': 1})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(CashClosure.objects.exists())

    def test_running_balance_overflow_is_400_chain_intact(self):
        self.report(self.n1, 'A', BIG); self.report(self.n2, 'A', BIG)
        c1 = self.close(self.g1, {'bills_50': 0}).json()
        c2 = self.close(self.g2, {'bills_50': 0}).json()
        self.assertEqual(self.versement(c1['id']).status_code, 201)
        r = self.versement(c2['id'])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashbookEntry.objects.count(), 1)
        self.assertTrue(self.chain_ok())


class Bug835DirectionCount(Base):
    def test_theoretical_balance_follows_chain_order(self):
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        d1, d0 = today(), today() - timedelta(days=1)
        for d, g, n, amt in ((d1, self.g1, self.n1, '10000'), (d0, self.g2, self.n2, '5000')):
            self.report(n, 'A', amt, date=d, facturier=make_user('FACTURIER', n, team='A'))
            c = cl(g).post('/api/treasury/closures/', {'date': str(d), **{b: 0 for b in BILLS}}, format='json')
            self.assertEqual(self.versement(c.json()['id']).status_code, 201)
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/',
                               {'date': str(d1), 'bills_10000': 1, 'bills_5000': 1}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['theoretical_balance']), Dc('15000'))
        self.assertEqual(Dc(r.json()['cash_gap']), Dc('0'))


class Bug836Blockchain(Base):
    def chain3(self):
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        for i, (n, g) in enumerate(((self.n1, self.g1), (self.n2, self.g2), (self.n1, self.g1))):
            d = today() - timedelta(days=3 - i)
            self.report(n, 'A', str(10000 * (i + 1)), date=d, facturier=make_user('FACTURIER', n, team='A'))
            c = cl(g).post('/api/treasury/closures/', {'date': str(d), **{b: 0 for b in BILLS}}, format='json')
            self.assertEqual(self.versement(c.json()['id']).status_code, 201)

    def test_node_filter_does_not_blame_unrelated_node(self):
        self.chain3()
        last = CashbookEntry.chain_queryset().last()
        CashbookEntry.objects.filter(pk=last.pk).delete()
        other = [n for n in (self.n1, self.n2) if n.pk != last.node_id][0]
        r = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {'node': other.id}, format='json').json()
        self.assertTrue(r['results'][0]['is_intact'], r)
        self.assertFalse(TamperAlert.objects.filter(node=other).exists())

    def test_repeated_checks_do_not_duplicate_open_alert(self):
        self.chain3()
        e = CashbookEntry.chain_queryset()[0]
        CashbookEntry.objects.filter(pk=e.pk).update(label='falsifie')
        for _ in range(3):
            cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(TamperAlert.objects.filter(is_resolved=False, node=e.node).count(), 1)

    def test_global_status_never_checked_is_not_intact(self):
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertEqual(gs['nodes_checked'], 0)
        self.assertIs(gs['all_intact'], False)
        self.assertIs(gs['never_checked'], True)


class Bug837ActivityLog(Base):
    def test_actions_are_logged(self):
        def n():
            return ActivityLog.objects.count()
        self.report(self.n1, 'A', '10000')
        missing = []
        b = n(); e = self.expense(self.g1, '100').json()
        if n() == b: missing.append('expense create')
        b = n(); cl(self.g1).delete(f"/api/treasury/expenses/{e['id']}/")
        if n() == b: missing.append('expense delete')
        b = n(); c = self.close(self.g1, {'bills_5000': 1}).json()
        if n() == b: missing.append('closure create')
        b = n(); cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        if n() == b: missing.append('run_check')
        a = TamperAlert.objects.create(node=self.n1, affected_model='X', description='x')
        b = n(); cl(self.dirn).post(f'/api/blockchain/alerts/{a.id}/resolve/')
        if n() == b: missing.append('alert resolve')
        self.assertEqual(missing, [])


class Bug838NPlusOne(Base):
    def test_lists_have_constant_query_count(self):
        urls = ['/api/treasury/expenses/', '/api/blockchain/alerts/', '/api/blockchain/snapshots/']

        def count(url):
            with CaptureQueriesContext(connection) as q:
                self.assertEqual(cl(self.dirn).get(url).status_code, 200)
            return len(q)

        def grow(k0, k1):
            for i in range(k0, k1):
                d = today() - timedelta(days=i + 1)
                cl(self.g1).post('/api/treasury/expenses/', {'description': 'e', 'amount': '5',
                                                              'category': self.cat.id, 'date': str(d)}, format='json')
                TamperAlert.objects.create(node=self.n1, affected_model='X', description='x')
                BlockchainSnapshot.objects.create(node=self.n1, snapshot_date=d)
        grow(0, 3)
        small = {u: count(u) for u in urls}
        grow(3, 12)
        big = {u: count(u) for u in urls}
        self.assertEqual(small, big)


class Bug839Versement(Base):
    def confirmed(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        return c

    def test_stale_second_push_is_refused(self):
        c = self.confirmed()
        stale = CashClosure.objects.prefetch_related('cashbook_entries').get(pk=c['id'])
        list(stale.cashbook_entries.all())
        promote_closure_to_cashbook(CashClosure.objects.get(pk=c['id']), acting_user=self.compt)
        with self.assertRaises(ClosureAlreadyPromotedError):
            promote_closure_to_cashbook(stale, acting_user=self.compt)
        self.assertEqual(CashbookEntry.objects.filter(source_closure_id=c['id']).count(), 1)

    def test_failed_append_leaves_closure_untouched(self):
        c = self.confirmed()
        LocalExpense.objects.create(node=self.n1, gerant=self.g1, description='sync', amount=Dc('2000'),
                                    category=self.cat, date=today(), node_origin='C1')
        with mock.patch('treasury.services.append_cashbook_entry', side_effect=OperationalError('x')):
            with self.assertRaises(OperationalError):
                promote_closure_to_cashbook(CashClosure.objects.get(pk=c['id']), acting_user=self.compt)
        cc = CashClosure.objects.get(pk=c['id'])
        self.assertFalse(cc.cashbook_entries.exists())
        self.assertEqual((cc.net_cash, cc.total_expenses), (Dc('10000'), Dc('0')))

    def test_confirmed_amount_equals_inscribed_amount(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(self.expense(self.g1, '2500').status_code, 201)
        v = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json').json()
        self.assertEqual(Dc(v['net_cash']), Dc('7500'))
        e = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json').json()
        self.assertEqual(Dc(e['entry_amount']), Dc(v['net_cash']))

    def test_failed_append_leaves_no_orphan_voucher(self):
        append_cashbook_entry(node=self.n1, date=today(), piece_number='VC-C1-1', imputation='7000',
                              label='seed', entry_amount=Dc('100000'), node_origin='C1')
        with mock.patch('treasury.views.append_cashbook_entry', side_effect=OperationalError('verrou')):
            cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm', 'bills_5000': 2}, format='json')
        self.assertEqual(DisbursementVoucher.objects.count(), 0)

    def test_refused_voucher_leaves_no_orphan(self):
        r = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm', 'bills_5000': 2}, format='json')
        self.assertEqual(r.status_code, 400)  # solde insuffisant
        self.assertEqual(DisbursementVoucher.objects.count(), 0)


class Bug810Reopened(Base):
    BADNODE = ('abc', [], {}, [1], {'a': 1}, True, 1.5, '1.5', '9' * 30, -1)

    def test_bool_float_node_in_body_never_creates(self):
        calls = [
            ('/api/treasury/closures/', {'date': str(today()), 'bills_50': 1}),
            ('/api/treasury/expenses/', {'description': 'x', 'amount': '10', 'category': self.cat.id, 'date': str(today())}),
            ('/api/treasury/reports/generate/', {}),
            ('/api/treasury/reports/', {'date': str(today())}),
            ('/api/treasury/journal/', {'date': str(today()), 'imput': 'EAU', 'label': 'x', 'exit_amount': '1'}),
            ('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '10', 'flour_sacks': '1'}),
        ]
        bad = []
        for url, body in calls:
            for nv in self.BADNODE:
                r = cl(self.dirn).post(url, {**body, 'node': nv}, format='json')
                if r.status_code >= 500 or r.status_code == 201:
                    bad.append((url, nv, r.status_code))
        self.assertEqual(bad, [])
        self.assertEqual(CashClosure.objects.count() + LocalExpense.objects.count() + JournalEntry.objects.count()
                         + DailySavings.objects.count() + FacturierReport.objects.count(), 0)


class Bug815Reopened(Base):
    def test_hq_patch_savings_node_to_node_with_same_date(self):
        body = {'date': str(today()), 'daily_revenue': '100000', 'flour_sacks': '2'}
        cl(self.g1).post('/api/treasury/savings/', body, format='json')
        d2 = cl(self.g2).post('/api/treasury/savings/', body, format='json').json()
        r = cl(self.dirn).patch(f"/api/treasury/savings/{d2['id']}/", {'node': self.n1.id}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(DailySavings.objects.count(), 2)

    def test_closure_patch_date_to_existing_day(self):
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        y = today() - timedelta(days=1)
        cl(self.g1).post('/api/treasury/closures/', {'date': str(y), 'bills_50': 1}, format='json')
        c1 = self.close(self.g1, {'bills_50': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c1['id']}/reject/", {'reason': 'r'}, format='json')
        r = cl(self.g1).patch(f"/api/treasury/closures/{c1['id']}/", {'date': str(y)}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashClosure.objects.filter(node=self.n1).count(), 2)


class Bug818Reopened(Base):
    def test_generate_report_impossible_date_is_400(self):
        for b in ('2026-02-30', '2026-13-45', '2026-02-30T10:00', 20261301, True, 'garbage'):
            r = cl(self.g1).post('/api/treasury/reports/generate/', {'date': b}, format='json')
            self.assertEqual(r.status_code, 400, (b, r.status_code))
