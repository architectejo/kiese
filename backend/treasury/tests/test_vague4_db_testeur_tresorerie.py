"""
Vague 4 (testeur-tresorerie, 2026-11-12) : décision client « JOUR CALENDAIRE »
(BUG-271/272). Une clôture de caisse par (boulangerie, date) additionnant les deux
équipes, un rapport facturier par (équipe, date), même si l'équipe change à la
relève ; fenêtre minuit-01:00 (Kinshasa = UTC+1) ; billetage ; chaîne de hash et
ancre `CashbookHead`.

Horloge simulée (`Clock`, avance de 1 ms par appel de `timezone.now`). Données
fictives uniquement.
"""
from datetime import date, time as dtime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.models import ExpenseCategory
from core.testing import make_node, make_user, make_bread_price, make_client, get_config
from sales.models import Invoice
from treasury.models import CashClosure, CashbookEntry, CashbookHead, FacturierReport, LocalExpense
from treasury.tests.test_verification_b3_tresorerie_2026_11_12 import Clock, _api, _sale

J = date(2026, 11, 12)
J1 = date(2026, 11, 13)


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K3')
        self.node.team_rotation_enabled = True
        self.node.handover_time = dtime(12, 0)
        self.node.save(update_fields=['team_rotation_enabled', 'handover_time'])
        self.gerant = make_user('GERANT', node=self.node, username='g_v4')
        self.facA = make_user('FACTURIER', node=self.node, team='A', username='fa_v4')
        self.facB = make_user('FACTURIER', node=self.node, team='B', username='fb_v4')
        self.comptable = make_user('COMPTABLE', username='c_v4')
        self.client_obj = make_client(self.node)
        self.bread = make_bread_price('MOYEN', 'Pain 300 FC', 300)
        self.api = _api(self.gerant)
        self.api_c = _api(self.comptable)
        self.cat, _ = ExpenseCategory.objects.get_or_create(code='EAU', defaults={'label': 'Eau'})
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()

    def gen(self, d):
        r = self.api.post('/api/treasury/reports/generate/', {'date': str(d)}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def close_push(self, d, bills):
        r = self.api.post('/api/treasury/closures/', {'date': str(d), **bills}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()['id']
        self.assertEqual(self.api_c.post(f'/api/treasury/closures/{cid}/validate/', {}, format='json').status_code, 200)
        p = self.api_c.post(f'/api/treasury/closures/{cid}/push_to_cashbook/', {}, format='json')
        self.assertEqual(p.status_code, 201, p.content)
        return r.json(), p.json()

    def verdicts(self):
        a = self.api_c.get('/api/treasury/cashbook/integrity_check/').json()
        b = self.api_c.post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        g = self.api_c.get('/api/blockchain/snapshots/global_status/').json()
        return a['chain_valid'], b['all_intact'], g['all_intact']


class CalendarDayClosureTests(_Base):
    def test_day_split_over_midnight_and_handover_is_one_closure_two_reports(self):
        with Clock(J, 0, 5) as clk:                              # 23:05 UTC la veille : jour local = J
            _sale(self.node, self.facA, self.client_obj, self.bread, 1, J)      # 300 (00:05)
            clk.set(J, 11, 59, 30)
            _sale(self.node, self.facA, self.client_obj, self.bread, 2, J)      # 600 (11:59)
            clk.set(J, 12, 0, 10)                                              # après la relève : équipe B
            _sale(self.node, self.facB, self.client_obj, self.bread, 4, J, team='B')   # 1200
            clk.set(J, 23, 59, 0)
            _sale(self.node, self.facB, self.client_obj, self.bread, 5, J, team='B')   # 1500 (23:59)
            reports = self.gen(J)
            by_team = {r['team']: r for r in reports}
            self.assertEqual(set(by_team), {'A', 'B'})
            self.assertEqual({r['date'] for r in reports}, {str(J)})
            self.assertEqual(Decimal(by_team['A']['total_cash_sales']), Decimal('900'))
            self.assertEqual(Decimal(by_team['B']['total_cash_sales']), Decimal('2700'))
            LocalExpense.objects.create(node=self.node, gerant=self.gerant, description='Eau',
                                        amount=Decimal('600'), category=self.cat, date=J)
            closure, entry = self.close_push(J, {'bills_1000': 3, 'bills_50': 2})
            self.assertEqual(Decimal(closure['total_entries']), Decimal('3600'))     # 900 + 2700
            self.assertEqual(Decimal(closure['net_cash']), Decimal('3000'))          # - 600
            self.assertEqual(Decimal(closure['physical_cash_total']), Decimal('3100'))
            self.assertEqual(Decimal(closure['cash_gap']), Decimal('100'))
            self.assertEqual(entry['piece_number'], 'VC-K3-20261112')
            self.assertEqual(Decimal(entry['running_balance']), Decimal('3000'))
            self.assertEqual(CashClosure.objects.filter(node=self.node, date=J).count(), 1)
            r2 = self.api.post('/api/treasury/closures/', {'date': str(J), 'bills_50': 1}, format='json')
            self.assertEqual(r2.status_code, 400, r2.content)

    def test_midnight_is_the_day_boundary_for_reports_and_closures(self):
        with Clock(J, 23, 59, 0) as clk:
            _sale(self.node, self.facA, self.client_obj, self.bread, 2, J)      # 600 -> J
            clk.set(J1, 0, 0, 30)                                              # 00:00:30 : jour J1
            _sale(self.node, self.facA, self.client_obj, self.bread, 3, J1)     # 900 -> J1
            rj = self.gen(J)
            self.assertEqual([Decimal(r['total_cash_sales']) for r in rj], [Decimal('600')])
            rj1 = self.gen(J1)
            self.assertEqual([Decimal(r['total_cash_sales']) for r in rj1], [Decimal('900')])
            self.assertEqual(FacturierReport.objects.filter(node=self.node, team='A').count(), 2)
            c1, _e1 = self.close_push(J, {'bills_500': 1, 'bills_100': 1})
            c2, _e2 = self.close_push(J1, {'bills_500': 1, 'bills_200': 2})
            self.assertEqual((Decimal(c1['net_cash']), Decimal(c2['net_cash'])), (Decimal('600'), Decimal('900')))
            self.assertEqual(Decimal(c1['cash_gap']), Decimal('0'))
            self.assertEqual(Decimal(c2['cash_gap']), Decimal('0'))
            self.assertEqual(CashbookEntry.objects.order_by('chain_seq').last().running_balance, Decimal('1500'))
            self.assertEqual(self.verdicts(), (True, True, True))

    def test_same_team_cannot_sell_again_after_report_but_other_team_can(self):
        with Clock(J, 3, 0) as clk:
            _sale(self.node, self.facA, self.client_obj, self.bread, 1, J)
            self.gen(J)
            late = _sale(self.node, self.facA, self.client_obj, self.bread, 1, J, deliver=False)
            with self.assertRaises(ValidationError):
                late.deliver(livreur=self.facA)
            clk.set(J, 13, 0)
            ok = _sale(self.node, self.facB, self.client_obj, self.bread, 1, J, team='B')
            self.assertEqual(ok.status, Invoice.Status.DELIVERED)
            self.assertEqual(len(self.gen(J)), 2)

    def test_closure_recomputed_when_other_team_sells_after_preparation(self):
        with Clock(J, 8, 0) as clk:
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J)
            self.gen(J)
            r = self.api.post('/api/treasury/closures/', {'date': str(J), 'bills_1000': 1, 'bills_500': 1}, format='json')
            cid = r.json()['id']
            clk.set(J, 15, 0)
            _sale(self.node, self.facB, self.client_obj, self.bread, 2, J, team='B')
            self.gen(J)
            p = self.api.patch(f'/api/treasury/closures/{cid}/', {'bills_500': 3}, format='json')
            self.assertEqual(p.status_code, 200, p.content)
            c = CashClosure.objects.get(pk=cid)
            self.assertEqual((c.total_entries, c.net_cash, c.physical_cash_total, c.cash_gap),
                             (Decimal('2100'), Decimal('2100'), Decimal('2500'), Decimal('400')))


class BillsTotalTests(_Base):
    def test_total_is_sum_quantity_times_value_for_all_denominations_and_bounds(self):
        faces = {20000: 3, 10000: 2, 5000: 1, 1000: 4, 500: 5, 200: 6, 100: 7, 50: 9}
        payload = {f'bills_{k}': v for k, v in faces.items()}
        expected = sum(k * v for k, v in faces.items())
        with Clock(J, 10, 0):
            r = self.api.post('/api/treasury/closures/', {'date': str(J), **payload}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(Decimal(r.json()['physical_cash_total']), Decimal(expected))
            cid = r.json()['id']
            for bad in (100001, -1, 'abc', 2.5, None):
                p = self.api.patch(f'/api/treasury/closures/{cid}/', {'bills_20000': bad}, format='json')
                self.assertEqual(p.status_code, 400, (bad, p.content))
                self.assertIn('bills_20000', p.json())
            self.assertEqual(CashClosure.objects.get(pk=cid).bills_20000, 3)
            ok = self.api.patch(f'/api/treasury/closures/{cid}/', {'bills_20000': 100000}, format='json')
            self.assertEqual(ok.status_code, 200, ok.content)
            self.assertEqual(Decimal(ok.json()['physical_cash_total']),
                             Decimal(expected - 3 * 20000 + 100000 * 20000))


class ChainAnchorTests(_Base):
    def test_anchor_follows_pushes_and_detects_tail_deletion(self):
        with Clock(J, 10, 0) as clk:
            _sale(self.node, self.facA, self.client_obj, self.bread, 5, J)
            self.gen(J)
            self.close_push(J, {'bills_1000': 1, 'bills_500': 1})
            clk.set(J1, 10, 0)
            _sale(self.node, self.facA, self.client_obj, self.bread, 3, J1)
            self.gen(J1)
            self.close_push(J1, {'bills_500': 1, 'bills_200': 2})
            head = CashbookHead.objects.get()
            last = CashbookEntry.objects.order_by('chain_seq').last()
            self.assertEqual((head.entry_count, head.last_hash), (2, last.block_hash))
            self.assertEqual(self.verdicts(), (True, True, True))
            CashbookEntry.objects.filter(pk=last.pk).delete()
            self.assertEqual(self.verdicts(), (False, False, False))
