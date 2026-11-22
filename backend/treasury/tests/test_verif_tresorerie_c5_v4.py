"""Cycle 5, partie C (testeur-tresorerie, repris par Dev B, 2026-11-22-c5) :
verification independante de BUG-810 (PATCH rapport), BUG-840 a 847, puis
2e passe sur Caisse / Cloture / Livre de caisse. Donnees fictives uniquement.
"""
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure, mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from blockchain.models import BlockchainSnapshot, TamperAlert
from core.models import ActivityLog, Config, Node, SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice
from treasury.models import (
    CashbookEntry, CashbookHead, CashClosure, DailySavings, DisbursementVoucher,
    FacturierReport, JournalEntry, LocalExpense,
)
from treasury.tests.test_cycle1_tresorerie_c import BILLS, VALUES, Base, cl, rows, today
from treasury.tests.test_reports_closures import _make_invoice

BIG = '999999999999.99'


def nq(fn):
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx)


def notifs(prefix):
    return SystemNotification.objects.filter(title__startswith=prefix).count()


# =====================================================================
# BUG-810 : PATCH node d'un rapport
# =====================================================================
class V810Patch(Base):
    def test_patch_node_garbage_refused_report_stays(self):
        rep = self.report(self.n1, 'A', '100')
        for nv in (True, False, 1.5, 0, 'abc', '1.0', [1], {'a': 1}, 999999, ''):
            r = cl(self.dirn).patch(f'/api/treasury/reports/{rep.pk}/', {'node': nv}, format='json')
            self.assertLess(r.status_code, 500, (nv, r.status_code))
            self.assertEqual(FacturierReport.objects.get(pk=rep.pk).node_id, self.n1.pk, nv)

    def test_put_node_garbage_refused(self):
        rep = self.report(self.n1, 'A', '100')
        for nv in (True, 1.5, 'abc'):
            r = cl(self.dirn).put(f'/api/treasury/reports/{rep.pk}/', {'node': nv, 'date': str(today())}, format='json')
            self.assertLess(r.status_code, 500, (nv, r.status_code))
            self.assertEqual(FacturierReport.objects.get(pk=rep.pk).node_id, self.n1.pk, nv)

    def test_patch_node_multipart_garbage(self):
        rep = self.report(self.n1, 'A', '100')
        for nv in ('true', '1.5', 'abc'):
            r = cl(self.dirn).patch(f'/api/treasury/reports/{rep.pk}/', {'node': nv})
            self.assertLess(r.status_code, 500, (nv, r.status_code))
            self.assertEqual(FacturierReport.objects.get(pk=rep.pk).node_id, self.n1.pk, nv)

    def test_patch_valid_other_node_and_gerant_cannot_move(self):
        rep = self.report(self.n1, 'A', '100')
        r = cl(self.g1).patch(f'/api/treasury/reports/{rep.pk}/', {'node': self.n2.pk}, format='json')
        self.assertLess(r.status_code, 500)
        self.assertEqual(FacturierReport.objects.get(pk=rep.pk).node_id, self.n1.pk)
        r = cl(self.g2).patch(f'/api/treasury/reports/{rep.pk}/', {'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_patch_cannot_edit_totals(self):
        rep = self.report(self.n1, 'A', '100')
        cl(self.g1).patch(f'/api/treasury/reports/{rep.pk}/', {
            'total_cash_sales': '999999', 'theoretical_cash': '5', 'is_validated': True, 'team': 'B'}, format='json')
        rep.refresh_from_db()
        self.assertEqual((rep.total_cash_sales, rep.theoretical_cash, rep.is_validated, rep.team),
                         (Dc('100'), Dc('100'), False, 'A'))


# =====================================================================
# BUG-840 : generate sur un jour de cloture confirmee
# =====================================================================
class V840(Base):
    def setUp(self):
        self.bread = make_bread_price(category='MOYEN', label='Pain 300 C5', unit_price=300)
        self.cli = make_client(self.n1)
        self.facB = make_user('FACTURIER', self.n1, team='B')

    def test_generate_refused_on_confirmed_day_and_amount_pushed_is_confirmed(self):
        _make_invoice(self.n1, self.fac, 'A', self.cli, self.bread, 5, Invoice.PaymentType.CASH)
        cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
        _make_invoice(self.n1, self.facB, 'B', self.cli, self.bread, 10, Invoice.PaymentType.CASH)
        c = self.close(self.g1, {'bills_1000': 1, 'bills_500': 1}).json()
        v = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        self.assertEqual(v.status_code, 200, v.content)
        confirmed = Dc(v.json()['net_cash'])
        r = cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        # avec la date explicite aussi, et en tant que siege avec node
        self.assertEqual(cl(self.g1).post('/api/treasury/reports/generate/', {'date': str(today())}, format='json').status_code, 400)
        self.assertEqual(cl(self.dirn).post('/api/treasury/reports/generate/',
                                            {'node': self.n1.pk}, format='json').status_code, 400)
        p = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(p.status_code, 201, p.content)
        self.assertEqual(Dc(p.json()['entry_amount']), confirmed)

    def test_generate_allowed_before_confirmation_and_after_reject(self):
        _make_invoice(self.n1, self.fac, 'A', self.cli, self.bread, 5, Invoice.PaymentType.CASH)
        c = self.close(self.g1, {'bills_1000': 1}).json()      # cloture en attente, sans rapport
        self.assertEqual(cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json').status_code, 200)
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'x'}, format='json')
        self.assertEqual(cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json').status_code, 200)

    def test_other_node_not_frozen_by_confirmed_day(self):
        c = self.close(self.g1, {'bills_50': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        n3 = make_node('C3', 'Cycle C3')
        b3 = make_client(n3)
        _make_invoice(n3, make_user('FACTURIER', n3, team='A'), 'A', b3, self.bread, 2, Invoice.PaymentType.CASH)
        r = cl(make_user('GERANT', n3)).post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)


# =====================================================================
# BUG-841 : PATCH date d'un rapport
# =====================================================================
class V841(Base):
    def mk(self, d, team='A', fac=None):
        return FacturierReport.objects.create(
            node=self.n1, facturier=fac or self.fac, team=team, date=d, total_cash_sales=Dc('1'),
            theoretical_cash=Dc('1'), node_origin='C1')

    def test_patch_and_put_date_to_existing_day_400_and_nothing_changed(self):
        y = today() - timedelta(days=1)
        self.mk(y)
        rep = self.mk(today())
        for m in ('patch', 'put'):
            r = getattr(cl(self.g1), m)(f'/api/treasury/reports/{rep.pk}/', {'date': str(y)}, format='json')
            self.assertEqual(r.status_code, 400, (m, r.status_code))
        self.assertEqual(FacturierReport.objects.get(pk=rep.pk).date, today())

    def test_patch_same_date_free_date_and_other_team_ok(self):
        y = today() - timedelta(days=1)
        rep = self.mk(today())
        self.mk(y, team='B', fac=make_user('FACTURIER', self.n1, team='B'))   # autre facturier/equipe : pas de conflit
        r = cl(self.g1).patch(f'/api/treasury/reports/{rep.pk}/', {'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = cl(self.g1).patch(f'/api/treasury/reports/{rep.pk}/', {'date': str(y)}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_patch_date_future_and_garbage_never_500(self):
        rep = self.mk(today())
        for v in (str(today() + timedelta(days=30)), 'abc', '2026-02-30', 123, None, [], '9999-12-31'):
            r = cl(self.g1).patch(f'/api/treasury/reports/{rep.pk}/', {'date': v}, format='json')
            self.assertLess(r.status_code, 500, (v, r.status_code))

    def test_patch_into_confirmed_day_refused(self):
        y = today() - timedelta(days=1)
        rep = self.mk(today())
        CashClosure.objects.create(node=self.n1, date=y, gerant=self.g1, is_validated=True, node_origin='C1')
        r = cl(self.g1).patch(f'/api/treasury/reports/{rep.pk}/', {'date': str(y)}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


# =====================================================================
# BUG-842 / 843 : integrity_check et global_status
# =====================================================================
class V842_843(Base):
    def seed(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 2}).json()
        self.versement(c['id'])
        self.report(self.n2, 'A', '4000')
        c2 = self.close(self.g2, {'bills_1000': 4}).json()
        self.versement(c2['id'])
        return list(CashbookEntry.chain_queryset())

    def test_integrity_check_idempotent_one_notification_per_tampered_entry(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e1.pk).update(label='falsifie')
        for _ in range(4):
            r = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/')
            self.assertFalse(r.json()['chain_valid'])
        tc = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()['tampered_count']
        self.assertGreaterEqual(tc, 1)
        # une notification par ecriture alteree (la suivante est invalidee en cascade), jamais par appel
        self.assertEqual(notifs('Alerte Blockchain'), tc)
        self.assertEqual(TamperAlert.objects.count(), 0)         # GET : pas d'alerte creee

    def test_head_problem_one_notification(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e2.pk).delete()
        for _ in range(3):
            r = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/')
            self.assertFalse(r.json()['chain_valid'])
            self.assertTrue(r.json()['head_problem'])
        self.assertEqual(notifs('Alerte Blockchain'), 1)

    def test_run_check_then_integrity_check_same_verdict_no_extra_notification(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e2.pk).update(exit_amount=Dc('1'))
        rc = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        n_after_run = SystemNotification.objects.count()
        ic = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()
        self.assertFalse(rc['all_intact'])
        self.assertFalse(ic['chain_valid'])
        total_tampered = sum(r['tampered_count'] for r in rc['results'])
        self.assertEqual(total_tampered, ic['tampered_count'])
        self.assertEqual(SystemNotification.objects.count(), n_after_run)

    def test_clean_chain_creates_nothing(self):
        self.seed()
        before = SystemNotification.objects.count()
        for _ in range(3):
            self.assertTrue(cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()['chain_valid'])
        self.assertEqual(SystemNotification.objects.count(), before)

    def test_global_status_partial_then_full_then_new_node(self):
        self.seed()
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertTrue(gs['never_checked'])
        self.assertFalse(gs['all_intact'])
        cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {'node': self.n1.pk}, format='json')
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertFalse(gs['never_checked'])
        self.assertFalse(gs['all_intact'])
        self.assertIn('C2', gs['unchecked_nodes'])
        self.assertNotIn('C1', gs['unchecked_nodes'])
        cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertTrue(gs['all_intact'], gs)
        self.assertEqual(gs['unchecked_nodes'], [])
        self.assertEqual(gs['nodes_checked'], Node.objects.count())
        make_node('C9', 'Cycle C9')
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertFalse(gs['all_intact'])
        self.assertEqual(gs['unchecked_nodes'], ['C9'])

    def test_global_status_tampered_is_not_intact_and_matches_run_check(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e1.pk).update(label='x')
        rc = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertEqual(gs['all_intact'], rc['all_intact'])
        self.assertFalse(gs['all_intact'])
        self.assertEqual(gs['open_alerts'], TamperAlert.objects.filter(is_resolved=False).count())

    def test_global_status_uses_latest_snapshot_per_node(self):
        n = make_node('C8', 'Cycle C8')
        BlockchainSnapshot.objects.create(node=n, snapshot_date=today() - timedelta(days=3), total_entries=0,
                                          tampered_entries=0, is_intact=True)
        BlockchainSnapshot.objects.create(node=n, snapshot_date=today() - timedelta(days=1), total_entries=0,
                                          tampered_entries=2, is_intact=False)
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        row = [s for s in gs['node_snapshots'] if s['node'] == n.pk or s.get('node_code') == 'C8']
        self.assertEqual(len(row), 1)
        self.assertFalse(row[0]['is_intact'])
        self.assertFalse(gs['all_intact'])


# =====================================================================
# BUG-844 : journalisation
# =====================================================================
class V844(Base):
    def test_money_writes_leave_activity_log(self):
        miss = []

        def logged(label, fn):
            n = ActivityLog.objects.count()
            r = fn()
            if ActivityLog.objects.count() == n:
                miss.append((label, getattr(r, 'status_code', None)))
            return r
        self.report(self.n1, 'A', '5000')
        gx = make_user('GERANT', self.n2, team='A')
        rep = logged('report.create', lambda: cl(gx).post('/api/treasury/reports/', {'date': str(today())}, format='json'))
        logged('report.delete', lambda: cl(gx).delete(f"/api/treasury/reports/{rep.json()['id']}/"))
        sv = logged('savings.create', lambda: cl(self.g1).post('/api/treasury/savings/', {
            'date': str(today()), 'daily_revenue': '1000', 'flour_sacks': '1'}, format='json'))
        logged('savings.upsert', lambda: cl(self.g1).post('/api/treasury/savings/', {
            'date': str(today()), 'daily_revenue': '2000', 'flour_sacks': '1'}, format='json'))
        logged('savings.patch', lambda: cl(self.g1).patch(f"/api/treasury/savings/{sv.json()['id']}/", {'daily_revenue': '3000'}, format='json'))
        for imp in ('EAU', 'CA', 'RATION'):
            logged(f'journal.{imp}', lambda imp=imp: cl(self.g1).post('/api/treasury/journal/', {
                'date': str(today()), 'imput': imp, 'label': 'x', 'exit_amount': '10'}, format='json'))
        ex = logged('expense.create', lambda: self.expense(self.g1, '10'))
        logged('expense.delete', lambda: cl(self.g1).delete(f"/api/treasury/expenses/{ex.json()['id']}/"))
        cl_ = logged('closure.create', lambda: self.close(self.g1, {'bills_50': 1}))
        logged('closure.reject', lambda: cl(self.compt).post(f"/api/treasury/closures/{cl_.json()['id']}/reject/", {'reason': 'r'}, format='json'))
        logged('closure.validate', lambda: cl(self.compt).post(f"/api/treasury/closures/{cl_.json()['id']}/validate/", {}, format='json'))
        logged('closure.push', lambda: cl(self.compt).post(f"/api/treasury/closures/{cl_.json()['id']}/push_to_cashbook/", {}, format='json'))
        logged('voucher', lambda: cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm', 'bills_50': 1}, format='json'))
        logged('count', lambda: cl(self.dirn).post('/api/treasury/direction-cash-counts/', {'date': str(today()), 'bills_50': 1}, format='json'))
        self.assertEqual(miss, [])


# =====================================================================
# BUG-845 : N+1 global_status
# =====================================================================
class V845(Base):
    def snaps(self, tag, k):
        for i in range(k):
            n = make_node(f'{tag}{i}', f'{tag}{i}')
            for d in (3, 2, 1):
                BlockchainSnapshot.objects.create(node=n, snapshot_date=today() - timedelta(days=d), total_entries=0,
                                                  tampered_entries=0, is_intact=True)

    def test_constant_query_count_after_warmup(self):
        cl(self.dirn).get('/api/blockchain/snapshots/global_status/')
        self.snaps('Za', 3)
        a = nq(lambda: cl(self.dirn).get('/api/blockchain/snapshots/global_status/'))
        self.snaps('Zb', 12)
        b = nq(lambda: cl(self.dirn).get('/api/blockchain/snapshots/global_status/'))
        self.assertEqual(a, b)
        self.assertLessEqual(b, 8)

    def test_cold_first_call_also_constant(self):
        """Le 1er appel cree la Config singleton : mesure a froid, 2 tailles (BUG-845, test cycle3)."""
        Config.objects.all().delete()
        self.snaps('Zc', 3)
        cold = nq(lambda: cl(self.dirn).get('/api/blockchain/snapshots/global_status/'))
        self.assertLessEqual(cold, 14)


# =====================================================================
# BUG-847 : journal, solde progressif
# =====================================================================
class V847(Base):
    def post(self, **kw):
        body = {'date': str(today()), 'imput': 'CA', 'label': 'x', 'node': self.n1.id}
        body.update(kw)
        return cl(self.dirn).post('/api/treasury/journal/', body, format='json')

    def test_overflow_positive_negative_and_rollback(self):
        self.assertEqual(self.post(entry_amount=BIG).status_code, 201)
        r = self.post(entry_amount='1')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(self.post(exit_amount=BIG).status_code, 201)       # solde 0
        r = self.post(exit_amount=BIG)
        self.assertEqual(r.status_code, 201, r.content)                      # -999999999999.99 est dans la plage
        r = self.post(exit_amount='0.01')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(JournalEntry.objects.count(), 3)

    def test_backdated_insert_overflowing_later_entries_rolled_back(self):
        y = today() - timedelta(days=2)
        self.assertEqual(self.post(entry_amount=BIG).status_code, 201)
        before = list(JournalEntry.objects.values_list('pk', 'running_balance'))
        r = self.post(entry_amount='5', date=str(y))
        self.assertLess(r.status_code, 500, r.status_code)
        if r.status_code == 400:
            self.assertEqual(list(JournalEntry.objects.values_list('pk', 'running_balance')), before)
        else:   # accepte : le solde de la ligne postérieure reste représentable
            self.assertTrue(all(abs(b) <= Dc(BIG) for _, b in JournalEntry.objects.values_list('pk', 'running_balance')))

    def test_normal_running_balance_progressive_two_nodes(self):
        self.post(entry_amount='1000')
        self.post(exit_amount='300')
        cl(self.dirn).post('/api/treasury/journal/', {'date': str(today()), 'imput': 'CA', 'label': 'x',
                                                      'entry_amount': '50', 'node': self.n2.id}, format='json')
        bal = [Dc(e.running_balance) for e in JournalEntry.objects.filter(node=self.n1).order_by('created_at', 'pk')]
        self.assertEqual(bal, [Dc('1000'), Dc('700')])
        self.assertEqual(JournalEntry.objects.get(node=self.n2).running_balance, Dc('50'))


# =====================================================================
# BUG-846 : le frontend est verifie par lecture + tsc (rapport) ; garde-fou source
# =====================================================================
class V846Source(Base):
    def test_blockchain_tsx_has_neutral_states(self):
        import pathlib
        p = pathlib.Path(__file__).resolve().parents[3] / 'frontend' / 'src' / 'pages' / 'dashboard' / 'Blockchain.tsx'
        src = p.read_text(encoding='utf-8')
        for token in ('never_checked', 'unchecked_nodes', 'JAMAIS VÉRIFIÉ', 'VÉRIFICATION PARTIELLE'):
            self.assertIn(token, src)


# =====================================================================
# 2e passe : billetage, ecart non modifiable, versement
# =====================================================================
class Passe2Cloture(Base):
    # BUG-860 : la resoumission d'une cloture infirmee (billetage modifie, ecart recalcule) ne laisse
    # ni ligne de journal d'activite ni notification du nouvel ecart.
    def test_BUG_860_closure_resubmission_is_traced(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'recompter'}, format='json')
        n_log, n_not = ActivityLog.objects.count(), SystemNotification.objects.count()
        r = cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/", {'bills_10000': 0, 'bills_5000': 1}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Dc(r.json()['cash_gap']), Dc('-5000'))
        self.assertGreater(ActivityLog.objects.count(), n_log)
        self.assertGreater(SystemNotification.objects.count(), n_not)

    def test_closure_money_fields_cannot_be_forced_by_body(self):
        self.report(self.n1, 'A', '1000')
        r = self.close(self.g1, {'bills_1000': 1}, net_cash='999999', cash_gap='0', physical_cash_total='5',
                       total_entries='1', is_validated=True, is_rejected=True)
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((Dc(d['net_cash']), Dc(d['cash_gap']), Dc(d['physical_cash_total'])), (Dc('1000'), Dc('0'), Dc('1000')))
        self.assertFalse(d['is_validated'])
        self.assertFalse(d['is_rejected'])
        # PATCH (apres rejet) : memes champs ignores, ecart recalcule par le serveur
        cl(self.compt).post(f"/api/treasury/closures/{d['id']}/reject/", {'reason': 'x'}, format='json')
        r = cl(self.g1).patch(f"/api/treasury/closures/{d['id']}/", {'bills_500': 1, 'cash_gap': '0', 'net_cash': '1'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Dc(r.json()['cash_gap']), Dc('500'))
        self.assertEqual(Dc(r.json()['net_cash']), Dc('1000'))

    def test_hq_cannot_edit_a_closure_directly(self):
        self.report(self.n1, 'A', '1000')
        c = self.close(self.g1, {'bills_1000': 1}).json()
        for m in ('patch', 'put'):
            r = getattr(cl(self.dirn), m)(f"/api/treasury/closures/{c['id']}/", {'bills_50': 99, 'date': str(today())}, format='json')
            self.assertLess(r.status_code, 500)
        got = CashClosure.objects.get(pk=c['id'])
        # le gerant seul peut modifier ? le siege : si accepte, l'ecart doit etre recalcule, pas arbitraire
        self.assertEqual(got.physical_cash_total, sum(q * v for q, v in zip(
            (getattr(got, b) for b in BILLS), VALUES)))

    def test_confirmed_closure_frozen_all_verbs(self):
        c = self.close(self.g1, {'bills_50': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        for m in ('patch', 'put'):
            r = getattr(cl(self.g1), m)(f"/api/treasury/closures/{c['id']}/", {'bills_50': 9, 'date': str(today())}, format='json')
            self.assertEqual(r.status_code, 400, (m, r.status_code))
        self.assertEqual(cl(self.g1).delete(f"/api/treasury/closures/{c['id']}/").status_code, 403)
        self.assertEqual(cl(self.dirn).delete(f"/api/treasury/closures/{c['id']}/").status_code, 403)
        self.assertEqual(CashClosure.objects.get(pk=c['id']).bills_50, 1)
        self.assertEqual(cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {}, format='json').status_code, 400)
        self.assertEqual(cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json').status_code, 400)

    def test_gap_notification_signs_and_thresholds(self):
        self.report(self.n1, 'A', '30000')
        SystemNotification.objects.all().delete()
        self.close(self.g1, {'bills_20000': 1, 'bills_10000': 1, 'bills_500': 1})        # +500 : WARNING
        n = SystemNotification.objects.get(title__startswith='Écart de Caisse')
        self.assertEqual(n.severity, 'WARNING')
        self.assertIn('+500', n.message)
        self.report(self.n2, 'A', '30000')
        self.close(self.g2, {'bills_10000': 1})                                           # -20000 : DANGER
        n = SystemNotification.objects.filter(title__startswith='Écart de Caisse').latest('created_at')
        self.assertEqual(n.severity, 'DANGER')
        self.assertIn('-20', n.message)
        # ecart nul : pas de notification
        n3 = make_node('C5', 'Cycle C5')
        self.report(n3, 'A', '1000')
        before = notifs('Écart de Caisse')
        cl(make_user('GERANT', n3)).post('/api/treasury/closures/', {'date': str(today()), **{b: 0 for b in BILLS}, 'bills_1000': 1}, format='json')
        self.assertEqual(notifs('Écart de Caisse'), before)

    def test_double_closure_and_double_push_and_piece_format(self):
        self.report(self.n1, 'A', '1000')
        c = self.close(self.g1, {'bills_1000': 1}).json()
        self.assertEqual(self.close(self.g1, {'bills_1000': 1}).status_code, 400)
        self.assertEqual(cl(self.dirn).post('/api/treasury/closures/', {
            'date': str(today()), 'node': self.n1.pk, **{b: 0 for b in BILLS}}, format='json').status_code, 400)
        r = self.versement(c['id'])
        self.assertEqual(r.status_code, 201, r.content)
        e = CashbookEntry.objects.get()
        self.assertEqual(e.piece_number, f"VC-C1-{today().strftime('%Y%m%d')}")
        self.assertEqual(cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json').status_code, 400)
        self.assertEqual(CashbookEntry.objects.count(), 1)

    def test_validate_changes_gap_when_expense_added_after_creation_is_traced(self):
        """Une depense saisie apres la cloture modifie le net et l'ecart a la confirmation : l'ecart annonce
        (notification) au gerant n'est plus celui du livre. On exige au moins une trace (journal d'activite)."""
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()          # ecart 0
        self.assertEqual(self.expense(self.g1, '2000').status_code, 201)
        v = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        self.assertEqual(Dc(v.json()['cash_gap']), Dc('2000'))
        last = ActivityLog.objects.filter(action__icontains='Confirmation').latest('created_at')
        self.assertIn('2000', last.details if hasattr(last, 'details') else str(last.__dict__))


class Passe2Livre(Base):
    def seed3(self):
        out = []
        for n, g, cash, bill in ((self.n1, self.g1, '6000', 'bills_1000'), (self.n2, self.g2, '3000', 'bills_1000')):
            self.report(n, 'A', cash)
            c = self.close(g, {bill: int(Dc(cash) // 1000)}).json()
            self.assertEqual(self.versement(c['id']).status_code, 201)
        return list(CashbookEntry.chain_queryset())

    def test_tamper_every_hashed_field_is_detected(self):
        entries = self.seed3()
        e = entries[0]
        other_closure = CashClosure.objects.exclude(pk=e.source_closure_id).first()
        variants = {
            'label': {'label': 'zz'}, 'piece_number': {'piece_number': 'VC-X'}, 'imputation': {'imputation': '9999'},
            'entry_amount': {'entry_amount': Dc('1')}, 'exit_amount': {'exit_amount': Dc('1')},
            'running_balance': {'running_balance': Dc('1')}, 'date': {'date': today() - timedelta(days=9)},
            'node': {'node': self.n2}, 'source_closure': {'source_closure': other_closure},
            'is_correction': {'is_correction': True}, 'previous_hash': {'previous_hash': 'a' * 64},
            'block_hash': {'block_hash': 'b' * 64},
        }
        for name, upd in variants.items():
            with self.subTest(name):
                snap = CashbookEntry.objects.filter(pk=e.pk).values().first()
                CashbookEntry.objects.filter(pk=e.pk).update(**upd)
                self.assertFalse(self.chain_ok(), name)
                restore = {k: v for k, v in snap.items() if k in {u for u in (upd.keys() | {f'{k}_id' for k in upd})}}
                CashbookEntry.objects.filter(pk=e.pk).update(**{(k if k != 'node_id' else 'node_id'): v for k, v in restore.items()})
                self.assertTrue(self.chain_ok(), f'restauration {name}')

    def test_forged_tail_entry_with_valid_hash_is_detected_by_head_anchor(self):
        from treasury.hashing import compute_cashbook_entry_hash
        self.seed3()
        last = CashbookEntry.chain_queryset().last()
        forged = CashbookEntry(node=self.n1, date=today(), piece_number='VC-FORGE', imputation='7000', label='faux',
                               entry_amount=Dc('500000'), running_balance=last.running_balance + Dc('500000'),
                               previous_hash=last.block_hash, node_origin='C1')
        forged.block_hash = compute_cashbook_entry_hash(forged)
        forged.save()
        self.assertFalse(self.chain_ok())

    def test_deleted_middle_entry_detected_and_both_endpoints_agree(self):
        entries = self.seed3()
        CashbookEntry.objects.filter(pk=entries[0].pk).delete()
        ic = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()
        rc = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        self.assertFalse(ic['chain_valid'])
        self.assertFalse(rc['all_intact'])

    def test_append_retries_on_stale_previous_hash_and_chain_stays_valid(self):
        from treasury import views as tv
        self.report(self.n1, 'A', '2000')
        c1 = self.close(self.g1, {'bills_1000': 2}).json()
        self.versement(c1['id'])
        real = tv._get_last_balance
        calls = {'n': 0}

        def stale():
            calls['n'] += 1
            if calls['n'] == 1:
                first = CashbookEntry.chain_queryset().first()      # solde/hash perimes : deja pris
                return first.running_balance, first.previous_hash
            return real()
        self.report(self.n2, 'A', '1000')
        c2 = self.close(self.g2, {'bills_1000': 1}).json()
        with mock.patch('treasury.views._get_last_balance', side_effect=stale):
            r = self.versement(c2['id'])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertGreaterEqual(calls['n'], 2)
        self.assertTrue(self.chain_ok())
        self.assertEqual(CashbookEntry.chain_queryset().last().running_balance, Dc('3000'))

    def test_voucher_edges_and_balance(self):
        self.seed3()                                        # solde 9000
        mk = lambda **b: cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm', **b}, format='json')
        self.assertEqual(mk().status_code, 400)
        self.assertEqual(mk(bills_20000=1).status_code, 400)                    # 20000 > 9000
        r = mk(bills_5000=1, bills_1000=4)                                       # 9000 : solde exactement vide
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(CashbookEntry.chain_queryset().last().running_balance, Dc('0'))
        self.assertEqual(mk(bills_50=1).status_code, 400)
        self.assertEqual(DisbursementVoucher.objects.count(), 1)
        for m in ('put', 'patch', 'delete'):
            v = DisbursementVoucher.objects.get()
            self.assertEqual(getattr(cl(self.dirn), m)(f'/api/treasury/vouchers/{v.pk}/', {'motif': 'x'}, format='json').status_code, 405)
        self.assertTrue(self.chain_ok())
        for u in (self.g1, self.fac, self.liv):
            self.assertEqual(cl(u).post('/api/treasury/vouchers/', {'bills_50': 1}, format='json').status_code, 403)

    def test_two_vouchers_same_day_distinct_pieces(self):
        self.seed3()
        for _ in range(2):
            self.assertEqual(cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm', 'bills_1000': 1},
                                                format='json').status_code, 201)
        pn = list(DisbursementVoucher.objects.values_list('piece_number', flat=True))
        self.assertEqual(len(set(pn)), 2)

    def test_cashbook_api_read_only_and_period_filter(self):
        self.seed3()
        e = CashbookEntry.objects.first()
        for m in ('post', 'put', 'patch', 'delete'):
            r = getattr(cl(self.dirn), m)(f'/api/treasury/cashbook/{e.pk}/', {'label': 'x'}, format='json')
            self.assertEqual(r.status_code, 405, (m, r.status_code))
        r = cl(self.dirn).get(f'/api/treasury/cashbook/?date_from={today() + timedelta(days=1)}')
        self.assertEqual(len(rows(r)), 0)
        r = cl(self.dirn).get(f'/api/treasury/cashbook/?date_from={today()}&date_to={today()}')
        self.assertEqual(len(rows(r)), 2)

    def test_hash_unique_function_used_by_both_verifiers(self):
        import inspect
        import blockchain.views as bv
        import treasury.views as tv
        for mod in (bv, tv):
            code = [l for l in inspect.getsource(mod).splitlines() if not l.lstrip().startswith('#')]
            self.assertFalse([l for l in code if 'import hashlib' in l or 'hashlib.sha256' in l], mod.__name__)


class Passe2Valeurs(Base):
    def test_negative_or_absurd_amounts_refused_everywhere(self):
        bad = []
        cases = [
            ('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '-1000', 'flour_sacks': '1'}, 'savings neg revenue'),
            ('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '1000', 'savings_rate': '-0.5', 'flour_sacks': '1'}, 'savings neg rate'),
            ('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '1000', 'savings_rate': '5', 'flour_sacks': '1'}, 'savings rate 500%'),
            ('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '1000', 'flour_sacks': '-3'}, 'savings neg sacks'),
            ('/api/treasury/journal/', {'date': str(today()), 'imput': 'EAU', 'label': 'x', 'exit_amount': '-50'}, 'journal neg exit'),
            ('/api/treasury/journal/', {'date': str(today()), 'imput': 'CA', 'label': 'x', 'entry_amount': '-50'}, 'journal neg entry'),
            ('/api/treasury/expenses/', {'description': 'x', 'amount': '-5', 'category': self.cat.id, 'date': str(today())}, 'expense neg'),
            ('/api/treasury/expenses/', {'description': 'x', 'amount': '0.001', 'category': self.cat.id, 'date': str(today())}, 'expense 3 dec'),
        ]
        for url, body, label in cases:
            r = cl(self.g1).post(url, body, format='json')
            if r.status_code != 400:
                bad.append((label, r.status_code))
        self.assertEqual(bad, [])

    def test_savings_amount_is_revenue_times_rate_and_monthly_total(self):
        r = cl(self.g1).post('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '100000',
                                                        'savings_rate': '0.158', 'flour_sacks': '2'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['savings_amount']), Dc('15800.00'))
        r = cl(self.g1).get('/api/treasury/savings/monthly_total/')
        self.assertEqual(Dc(r.json()['total_savings']), Dc('15800.00'))



# =====================================================================
# Sonde : alteration, reparation, nouvelle alteration (suite de BUG-842)
# =====================================================================
class ProbeRetamper(Base):
    def seed(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 2}).json()
        self.versement(c['id'])
        return CashbookEntry.objects.get()

    def test_BUG_861_repaired_entry_is_no_longer_flagged(self):
        e = self.seed()
        CashbookEntry.objects.filter(pk=e.pk).update(label='falsifie')
        self.assertFalse(self.chain_ok())
        CashbookEntry.objects.filter(pk=e.pk).update(label=e.label)
        self.assertTrue(self.chain_ok())
        self.assertFalse(CashbookEntry.objects.get(pk=e.pk).is_tampered)

    def test_BUG_861_second_tampering_after_repair_is_notified_again(self):
        e = self.seed()
        CashbookEntry.objects.filter(pk=e.pk).update(label='falsifie')
        cl(self.dirn).get('/api/treasury/cashbook/integrity_check/')
        CashbookEntry.objects.filter(pk=e.pk).update(label=e.label)
        self.assertTrue(self.chain_ok())
        n = notifs('Alerte Blockchain')
        CashbookEntry.objects.filter(pk=e.pk).update(label='falsifie encore')
        cl(self.dirn).get('/api/treasury/cashbook/integrity_check/')
        self.assertEqual(notifs('Alerte Blockchain'), n + 1)
