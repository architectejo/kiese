"""Non-regression BUG-840 a 845, 847 et BUG-810 (PATCH rapport). Donnees fictives."""
from datetime import timedelta
from decimal import Decimal as Dc

from blockchain.models import BlockchainSnapshot
from core.models import ActivityLog, SystemNotification
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice
from treasury.models import CashbookEntry, FacturierReport, JournalEntry
from treasury.tests.test_cycle1_tresorerie_c import Base, cl, today
from treasury.tests.test_cycle3_tresorerie_c import n_queries, BIG
from treasury.tests.test_reports_closures import _make_invoice


class Bug810ReportPatch(Base):
    def test_patch_node_bool_float_refused(self):
        rep = self.report(self.n1, 'A', '100')
        for nv in (True, 1.5, 'abc'):
            r = cl(self.dirn).patch(f'/api/treasury/reports/{rep.pk}/', {'node': nv}, format='json')
            self.assertEqual(r.status_code, 400, (nv, r.status_code))
        self.assertEqual(FacturierReport.objects.get(pk=rep.pk).node_id, self.n1.pk)


class Bug841(Base):
    def test_patch_date_to_existing_day_is_400(self):
        y = today() - timedelta(days=1)
        for d in (y, today()):
            FacturierReport.objects.create(node=self.n1, facturier=self.fac, team='A', date=d,
                                           total_cash_sales=Dc('1'), theoretical_cash=Dc('1'), node_origin='C1')
        rep = FacturierReport.objects.get(node=self.n1, facturier=self.fac, date=today())
        r = cl(self.g1).patch(f'/api/treasury/reports/{rep.pk}/', {'date': str(y)}, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class Bug840(Base):
    def test_generate_on_confirmed_day_refused_amount_unchanged(self):
        bread = make_bread_price(category='MOYEN', label='Pain 300 D', unit_price=300)
        cli = make_client(self.n1)
        facB = make_user('FACTURIER', self.n1, team='B')
        _make_invoice(self.n1, self.fac, 'A', cli, bread, 5, Invoice.PaymentType.CASH)
        self.assertEqual(cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json').status_code, 200)
        _make_invoice(self.n1, facB, 'B', cli, bread, 10, Invoice.PaymentType.CASH)
        c = self.close(self.g1, {'bills_1000': 1, 'bills_500': 1}).json()
        v = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        self.assertEqual(v.status_code, 200, v.content)
        confirmed = Dc(v.json()['net_cash'])
        r = cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(FacturierReport.objects.filter(team='B').exists())
        p = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(p.status_code, 201, p.content)
        self.assertEqual(Dc(p.json()['entry_amount']), confirmed)


class Bug842_843(Base):
    def tamper(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 2}).json()
        self.versement(c['id'])
        CashbookEntry.objects.update(label='falsifie')

    def test_integrity_check_one_notification(self):
        self.tamper()
        for _ in range(3):
            r = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/')
            self.assertFalse(r.json()['chain_valid'])
        self.assertEqual(SystemNotification.objects.filter(title__startswith='Alerte Blockchain').count(), 1)

    def test_global_status_partial_check(self):
        self.report(self.n2, 'A', '5000')
        c = self.close(self.g2, {'bills_5000': 1}).json()
        self.versement(c['id'])
        cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {'node': self.n1.id}, format='json')
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertFalse(gs['all_intact'])
        self.assertFalse(gs['never_checked'])
        self.assertIn(self.n2.code, gs['unchecked_nodes'])
        cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertEqual(gs['unchecked_nodes'], [])
        self.assertTrue(gs['all_intact'])


class Bug844(Base):
    def test_activity_log_on_writes(self):
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


class Bug845(Base):
    def test_global_status_constant_queries(self):
        def snaps(k):
            for i in range(k):
                n = make_node(f'H{k}{i}', f'H{k}{i}')
                BlockchainSnapshot.objects.create(node=n, snapshot_date=today(), total_entries=0,
                                                  tampered_entries=0, is_intact=True)
        # appel de chauffe : le 1er appel cree la Config singleton (+ log + notification)
        cl(self.dirn).get('/api/blockchain/snapshots/global_status/')
        snaps(3)
        a = n_queries(lambda: cl(self.dirn).get('/api/blockchain/snapshots/global_status/'))
        snaps(9)
        b = n_queries(lambda: cl(self.dirn).get('/api/blockchain/snapshots/global_status/'))
        self.assertEqual(a, b)


class Bug847(Base):
    def test_journal_overflow_is_400(self):
        codes = []
        for _ in range(2):
            r = cl(self.dirn).post('/api/treasury/journal/', {
                'date': str(today()), 'imput': 'CA', 'label': 'x', 'entry_amount': BIG, 'node': self.n1.id}, format='json')
            codes.append(r.status_code)
        self.assertEqual(codes, [201, 400])
        self.assertEqual(JournalEntry.objects.filter(node=self.n1).count(), 1)
