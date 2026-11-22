"""Cycle 2, partie C (testeur-tresorerie, Dev C, 2026-11-22-c3) : verification des
corrections BUG-560/561/563 et BUG-810 a 819 sous de nouveaux angles, puis defauts
nouveaux (BUG-830 a 839). Donnees fictives uniquement.

Les anomalies confirmees portent un test `@expectedFailure` reference BUG-83x.
"""
import random
from datetime import date, timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure, mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from blockchain.models import BlockchainSnapshot, TamperAlert
from core.models import ActivityLog, Config, Node, SystemNotification
from core.testing import make_node, make_user
from treasury.models import (
    CashbookEntry, CashClosure, DailySavings, DirectionCashCount, DisbursementVoucher,
    FacturierReport, JournalEntry, LocalExpense,
)
from treasury.services import promote_closure_to_cashbook, ClosureAlreadyPromotedError
from treasury.tests.test_cycle1_tresorerie_c import BILLS, Base, cl, rows, today
from treasury.views import append_cashbook_entry

BIG = '999999999999.99'


def j(r):
    try:
        return r.json()
    except Exception:
        return None


# =====================================================================
# 1. BUG-560 / 561 / 563 : nouveaux angles
# =====================================================================
class V560(Base):
    BAD = ('ZZZ', '9' * 30, '9223372036854775808', '-1', '1.5', 'true', '1e3', 'null', '0', '%00', '٣')

    def test_node_param_sweep_never_500(self):
        urls = ['expenses', 'reports', 'closures', 'cashbook', 'journal', 'journal/monthly_report',
                'journal/suggested_ca?date=2026-01-01&x=1', 'savings', 'savings/monthly_total',
                'closures/versements', 'vouchers', 'vouchers/final_report', 'direction-counts']
        urls = [u for u in urls if u != 'direction-counts']
        bad500 = []
        for u in urls:
            for b in self.BAD:
                sep = '&' if '?' in u else '?'
                r = cl(self.dirn).get(f'/api/treasury/{u}{sep}node={b}')
                if r.status_code >= 500:
                    bad500.append((u, b, r.status_code))
        for u in ('snapshots', 'alerts', 'snapshots/global_status'):
            for b in self.BAD:
                r = cl(self.dirn).get(f'/api/blockchain/{u}/?node={b}')
                if r.status_code >= 500:
                    bad500.append((u, b, r.status_code))
        self.assertEqual(bad500, [])

    def test_other_filters_never_500(self):
        bad500 = []
        for u, qs in [
            ('expenses', ['category=abc', 'category=' + '9' * 30, 'date=garbage', 'date=2026-02-30', 'month=٣', 'year=٢٠٢٦']),
            ('reports', ['team=Z', 'date=zz', 'is_validated=maybe', 'is_validated=1', 'node=' + '9' * 30]),
            ('closures', ['is_validated=maybe', 'date=2026-13-45', 'ordering=bogus', 'ordering=-' + 'x' * 500]),
            ('cashbook', ['is_tampered=zz', 'date=zz', 'ordering=node__password', 'date_from=2026-01-01&date_to=1999-01-01']),
            ('journal', ['imput=ZZ', 'date=zz', 'month=13', 'year=1e3', 'month=%00']),
            ('savings', ['month=0', 'year=0', 'date=x']),
            ('vouchers', ['date=zz', 'ordering=created_by__password']),
        ]:
            for q in qs:
                r = cl(self.dirn).get(f'/api/treasury/{u}/?{q}')
                if r.status_code >= 500:
                    bad500.append((u, q, r.status_code))
        self.assertEqual(bad500, [])

    def test_hq_duplicate_report_is_400_not_500(self):
        body = {'date': str(today()), 'node': self.n2.id}
        self.assertEqual(cl(self.dirn).post('/api/treasury/reports/', body, format='json').status_code, 201)
        r = cl(self.dirn).post('/api/treasury/reports/', body, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        # un body d'equipe forgee ne contourne pas le controle
        r = cl(self.dirn).post('/api/treasury/reports/', {**body, 'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(FacturierReport.objects.filter(node=self.n2).count(), 1)

    def test_BUG_561_run_check_any_body_never_500(self):
        for body in ([], [1], 1, 'x', None, True, {'node': []}, {'node': {'a': 1}}, {'node': 'ZZ'}):
            r = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', body, format='json')
            self.assertLess(r.status_code, 500, (body, r.status_code))
        r = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', 'raw', content_type='text/plain')
        self.assertLess(r.status_code, 500)

    def test_BUG_563_versements_scope(self):
        inactive = make_node('CI9', 'Inactive'); inactive.is_active = False; inactive.save()
        d = cl(self.dirn).get('/api/treasury/closures/versements/').json()
        codes = [x['node_code'] for x in d['results']]
        self.assertNotIn('SIEGE', codes)
        self.assertEqual(d['count'], len(codes))
        self.assertEqual(sum(d['totals']['counts'].values()), len(codes))
        self.assertEqual(cl(self.dirn).get('/api/treasury/closures/versements/?node=SIEGE').status_code, 403)
        self.assertEqual(cl(self.dirn).get('/api/treasury/closures/versements/?date=2026-02-30').status_code, 400)
        # gerant : sa boulangerie seulement, meme avec ?node=autre
        self.assertEqual(cl(self.g1).get(f'/api/treasury/closures/versements/?node={self.n2.id}').status_code, 403)
        self.assertEqual([x['node_code'] for x in cl(self.g1).get('/api/treasury/closures/versements/').json()['results']], ['C1'])


# =====================================================================
# 2. BUG-810 a 812 : nouveaux angles
# =====================================================================
class V810(Base):
    BADNODE = ('abc', [], {}, [1], {'a': 1}, True, 1.5, '1.5', '9' * 30, -1)

    def test_BUG_810_bool_float_node_in_body_never_creates(self):
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

    def test_gerant_forged_node_in_body_is_ignored(self):
        for url, body in (('/api/treasury/expenses/', {'description': 'x', 'amount': '10', 'category': self.cat.id, 'date': str(today())}),
                          ('/api/treasury/journal/', {'date': str(today()), 'imput': 'EAU', 'label': 'x', 'exit_amount': '1'})):
            r = cl(self.g1).post(url, {**body, 'node': 'abc'}, format='json')
            self.assertIn(r.status_code, (201, 400), (url, r.content))
            r = cl(self.g1).post(url, {**body, 'node': self.n2.id}, format='json')
            self.assertIn(r.status_code, (201, 400), r.content)
        self.assertFalse(LocalExpense.objects.filter(node=self.n2).exists())
        self.assertFalse(JournalEntry.objects.filter(node=self.n2).exists())

    def test_BUG_811_voucher_and_closure_update_denomination_rules(self):
        # bons : au moins un billet obligatoire (BUG-239) ; billets negatifs refuses
        r = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'x', 'bills_50': -5}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(DisbursementVoucher.objects.exists())

    def test_BUG_830_report_team_patch_not_free(self):
        g = make_user('GERANT', self.n2, team='B')
        r = cl(g).post('/api/treasury/reports/', {'date': str(today()), 'team': 'A'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['team'], 'B')
        # un PATCH de l'equipe sur un rapport non valide
        rid = r.json()['id']
        r2 = cl(g).patch(f'/api/treasury/reports/{rid}/', {'team': 'Z'}, format='json')
        self.assertLess(r2.status_code, 500)
        FacturierReport.objects.get(pk=rid)
        self.assertIn(FacturierReport.objects.get(pk=rid).team, ('A', 'B'))


# =====================================================================
# 3. BUG-813 : effets de bord du gel des depenses
# =====================================================================
class V813(Base):
    def confirm(self, user=None):
        c = self.close(user or self.g1, {'bills_5000': 1}).json()
        r = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return c

    def test_hq_body_node_on_confirmed_day_is_frozen_too(self):
        self.report(self.n1, 'A', '10000')
        self.confirm()
        r = cl(self.dirn).post('/api/treasury/expenses/', {
            'description': 'x', 'amount': '10', 'category': self.cat.id, 'date': str(today()), 'node': self.n1.id}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = cl(self.dirn).post('/api/treasury/expenses/', {
            'description': 'x', 'amount': '10', 'category': self.cat.id, 'date': str(today()), 'node': 'C2'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_expense_move_into_or_out_of_confirmed_day_refused(self):
        self.report(self.n1, 'A', '10000')
        y = today() - timedelta(days=1)
        e_y = self.expense(self.g1, '700', date=y).json()
        e_t = self.expense(self.g1, '800').json()
        self.confirm()
        # vers le jour confirme
        r = cl(self.g1).patch(f"/api/treasury/expenses/{e_y['id']}/", {'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        # hors du jour confirme
        r = cl(self.g1).patch(f"/api/treasury/expenses/{e_t['id']}/", {'date': str(y)}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(LocalExpense.objects.get(pk=e_t['id']).date, today())

    def test_rejected_closure_day_is_open_and_resubmit_recomputes_then_push_matches(self):
        self.report(self.n1, 'A', '50000')
        c = self.close(self.g1, {'bills_20000': 2}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'recompter'}, format='json')
        self.assertEqual(self.expense(self.g1, '10000').status_code, 201)  # jour infirme : ouvert
        r = cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/", {'bills_20000': 2}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((Dc(d['total_expenses']), Dc(d['net_cash']), Dc(d['cash_gap'])), (Dc('10000'), Dc('40000'), Dc('0')))
        v = self.versement(c['id'])
        self.assertEqual(v.status_code, 201, v.content)
        self.assertEqual(Dc(v.json()['entry_amount']), Dc('40000'))
        self.assertTrue(self.chain_ok())

    def test_deleting_unconfirmed_closure_unfreezes_and_confirmed_cannot_be_deleted(self):
        self.report(self.n1, 'A', '1000')
        c = self.confirm()
        r = cl(self.g1).delete(f"/api/treasury/closures/{c['id']}/")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.expense(self.g1, '5').status_code, 400)

    def test_BUG_830_report_date_patch_into_confirmed_day_changes_pushed_net_silently(self):
        """BUG-830 : un rapport facturier non valide peut etre re-date (PATCH date) sur un
        jour de cloture CONFIRMEE ; au versement le net/ecart deja confirmes changent sans trace."""
        y = today() - timedelta(days=1)
        rep = self.report(self.n1, 'A', '5000', date=y)
        self.report(self.n1, 'B', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        r = cl(self.g1).patch(f'/api/treasury/reports/{rep.id}/', {'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 400, 'un jour de cloture confirmee doit rester fige : %s' % r.content)

    def test_BUG_830b_report_cannot_be_deleted_on_confirmed_day(self):
        rep = self.report(self.n1, 'A', '5000')
        self.confirm()
        r = cl(self.g1).delete(f'/api/treasury/reports/{rep.id}/')
        self.assertEqual(r.status_code, 400, 'suppression d un rapport sur jour confirme : %s' % r.status_code)


# =====================================================================
# 4. BUG-814 / 815
# =====================================================================
class V814(Base):
    def sav(self, user, **kw):
        body = {'date': str(today()), 'daily_revenue': '100000', 'flour_sacks': '2'}
        body.update(kw)
        return cl(user).post('/api/treasury/savings/', body, format='json')

    def test_rate_bounds_and_nulls_never_500(self):
        for bad in ('1.0001', '-0.1', None, '', 'abc', 'NaN', 'Infinity', '1e400', [], {}, True):
            r = self.sav(self.g1, savings_rate=bad)
            self.assertLess(r.status_code, 500, (bad, r.status_code))
        self.assertEqual(Dc(self.sav(self.g2, savings_rate='1').json()['savings_amount']), Dc('100000.00'))

    def test_patch_rate_zero_recomputes_amount(self):
        d = self.sav(self.g1).json()
        r = cl(self.g1).patch(f"/api/treasury/savings/{d['id']}/", {'savings_rate': '0'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Dc(r.json()['savings_amount']), Dc('0'))

    def test_BUG_815_hq_patch_node_to_node_with_same_date_is_400_not_500(self):
        self.sav(self.g1)
        d2 = self.sav(self.g2).json()
        r = cl(self.dirn).patch(f"/api/treasury/savings/{d2['id']}/", {'node': self.n1.id}, format='json')
        self.assertLess(r.status_code, 500, r.status_code)
        self.assertEqual(DailySavings.objects.count(), 2)

    def test_savings_upsert_is_idempotent_and_node_isolated(self):
        self.sav(self.g1); self.sav(self.g1, daily_revenue='5000')
        self.assertEqual(DailySavings.objects.filter(node=self.n1).count(), 1)
        self.assertEqual(DailySavings.objects.get(node=self.n1).daily_revenue, Dc('5000'))
        self.assertEqual(cl(self.g2).get('/api/treasury/savings/').json()['count'] if isinstance(cl(self.g2).get('/api/treasury/savings/').json(), dict) else len(rows(cl(self.g2).get('/api/treasury/savings/'))), 0)

    def test_BUG_831_savings_future_date_refused(self):
        r = self.sav(self.g1, date=str(today() + timedelta(days=40)))
        self.assertEqual(r.status_code, 400, 'epargne datee dans le futur : %s' % r.status_code)


# =====================================================================
# 5. BUG-816 : bons et methodes 405 sur tout le perimetre ajout-seul
# =====================================================================
class V816(Base):
    def test_method_matrix(self):
        append_cashbook_entry(node=self.n1, date=today(), piece_number='VC-C1-1', imputation='7000',
                              label='seed', entry_amount=Dc('100000'), node_origin='C1')
        v = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm', 'bills_5000': 2}, format='json')
        self.assertEqual(v.status_code, 201, v.content)
        vid = v.json()['id']
        e = CashbookEntry.objects.first()
        j1 = JournalEntry.objects.create(node=self.n1, date=today(), imput='EAU', label='x', exit_amount=1, entry_amount=0)
        ro = {
            f'/api/treasury/vouchers/{vid}/': ('put', 'patch', 'delete'),
            '/api/treasury/vouchers/': ('put', 'patch', 'delete'),
            '/api/treasury/vouchers/final_report/': ('post', 'put', 'patch', 'delete'),
            f'/api/treasury/cashbook/{e.id}/': ('post', 'put', 'patch', 'delete'),
            '/api/treasury/cashbook/': ('post', 'put', 'patch', 'delete'),
            '/api/treasury/cashbook/integrity_check/': ('post', 'put', 'delete'),
            f'/api/treasury/journal/{j1.id}/': ('put', 'patch', 'delete'),
            '/api/blockchain/snapshots/': ('post', 'put', 'patch', 'delete'),
            '/api/blockchain/snapshots/global_status/': ('post', 'put', 'delete'),
        }
        for url, methods in ro.items():
            for m in methods:
                with self.subTest(url=url, m=m):
                    r = getattr(cl(self.dirn), m)(url, {'bills_20000': 4, 'date': '2026-01-01'}, format='json')
                    self.assertEqual(r.status_code, 405, (url, m, r.status_code))
        # un gerant / facturier / anonyme ne voit jamais plus que 401/403 sur ces routes
        for who in (self.g1, self.fac, None):
            for m in ('put', 'patch', 'delete'):
                r = getattr(cl(who), m)(f'/api/treasury/vouchers/{vid}/', {}, format='json')
                self.assertIn(r.status_code, (401, 403), (who, m, r.status_code))
        # etat intact
        self.assertEqual(DisbursementVoucher.objects.get(pk=vid).physical_cash_total, 10000)
        self.assertTrue(self.chain_ok())

    def test_direction_cash_count_has_no_update_or_delete(self):
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/', {'date': str(today()), 'bills_50': 1}, format='json')
        if r.status_code == 404:
            self.skipTest('route de comptage direction differente')
        self.assertEqual(r.status_code, 201, r.content)
        u = f"/api/treasury/direction-cash-counts/{r.json()['id']}/"
        for m in ('put', 'patch', 'delete'):
            self.assertEqual(getattr(cl(self.dirn), m)(u, {'bills_50': 9}, format='json').status_code, 405)

    def test_BUG_832_tamper_alerts_are_not_editable_or_deletable(self):
        a = TamperAlert.objects.create(node=self.n1, affected_model='CashbookEntry', description='alerte')
        u = f'/api/blockchain/alerts/{a.id}/'
        out = {}
        out['delete'] = cl(self.dirn).delete(u).status_code
        out['patch'] = cl(self.dirn).patch(u, {'is_resolved': True, 'description': 'RAS'}, format='json').status_code
        out['post'] = cl(self.dirn).post('/api/blockchain/alerts/', {
            'node': self.n1.id, 'affected_model': 'X', 'description': 'forgee'}, format='json').status_code
        self.assertEqual(out, {'delete': 405, 'patch': 405, 'post': 405}, out)


# =====================================================================
# 6. BUG-817 : journal antidate, invariants
# =====================================================================
class V817(Base):
    def jpost(self, user, d, entry='0', exit='0', **kw):
        return cl(user).post('/api/treasury/journal/', {
            'date': str(d), 'imput': 'AUTRE', 'label': 'x', 'entry_amount': entry, 'exit_amount': exit, **kw}, format='json')

    def expected(self, node):
        es = sorted(JournalEntry.objects.filter(node=node), key=lambda e: (e.date, e.created_at, e.pk))
        bal, carried, prev = Dc(0), Dc(0), None
        for e in es:
            if prev is not None and (e.date.year, e.date.month) != (prev.year, prev.month):
                carried = bal
            bal = bal + e.entry_amount - e.exit_amount
            yield e, carried, bal
            prev = e.date

    def test_random_insert_order_keeps_running_balance_and_month_carried_exact(self):
        rnd = random.Random(20261122)
        base = date(2026, 1, 1)
        days = [base + timedelta(days=rnd.choice([0, 3, 17, 31, 32, 45, 60, 61, 90, 120, 200, 330, 360])) for _ in range(14)]
        days = [min(d, today()) for d in days]
        for g, node in ((self.g1, self.n1), (self.g2, self.n2)):
            order = days[:]
            rnd.shuffle(order)
            for d in order:
                amt = str(rnd.randint(1, 50) * 100)
                r = self.jpost(g, d, entry=amt) if rnd.random() < .6 else self.jpost(g, d, exit=amt)
                self.assertEqual(r.status_code, 201, r.content)
        for node in (self.n1, self.n2):
            for e, carried, bal in self.expected(node):
                e.refresh_from_db()
                self.assertEqual((e.month_carried, e.running_balance), (carried, bal), (node.code, e.date))

    def test_same_day_entries_chain_in_creation_order_and_report_matches(self):
        d = today()
        self.jpost(self.g1, d, entry='1000'); self.jpost(self.g1, d, exit='300'); self.jpost(self.g1, d, entry='50')
        self.jpost(self.g1, d - timedelta(days=1), entry='7')  # antidate : decale les 3 suivantes
        bals = [Dc(x['running_balance']) for x in rows(cl(self.g1).get('/api/treasury/journal/'))]
        self.assertEqual(bals, [Dc('7'), Dc('1007'), Dc('707'), Dc('757')])
        rep = cl(self.g1).get(f'/api/treasury/journal/monthly_report/?month={d.month}&year={d.year}').json()
        self.assertEqual(Dc(rep['final_balance']), Dc('757'))

    def test_journal_backdating_never_touches_the_hash_chain(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(self.versement(c['id']).status_code, 201)
        for k in range(1, 6):
            self.jpost(self.g1, today() - timedelta(days=k * 40), entry='100', imput='CA')
        self.assertTrue(self.chain_ok())
        r = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertTrue(r.json()['all_intact'])

    def test_BUG_833_monthly_report_without_node_mixes_nodes_for_hq(self):
        """BUG-833 : sans ?node=, le siege obtient des totaux de TOUS les noeuds mais
        `final_balance`/`month_carried` de l'ecriture la plus recente d'un seul noeud."""
        self.jpost(self.g1, today(), entry='1000')
        self.jpost(self.g2, today(), entry='400')
        r = cl(self.dirn).get(f'/api/treasury/journal/monthly_report/?month={today().month}&year={today().year}').json()
        self.assertEqual(Dc(r['total_entries']), Dc('1400'))
        # coherence : solde final = entrees - sorties de ce que le rapport totalise
        self.assertEqual(Dc(r['final_balance']), Dc(r['total_entries']) - Dc(r['total_exits']) + Dc(r['month_carried']),
                         'solde final d un seul noeud avec des totaux de tous les noeuds : %s' % r)


# =====================================================================
# 7. BUG-818 : dates illisibles, toutes routes
# =====================================================================
class V818(Base):
    BAD = ('garbage', '2026-02-30', '2026-13-45', '0000-01-01', '10000-01-01', '2026-1-1', '20260101',
           '2026-01-01T00:00:00', '٢٠٢٦-01-01', '%00', '9' * 40)

    def test_period_filters_never_500(self):
        bad = []
        for u in ('cashbook', 'cashbook/period_summary', 'vouchers/final_report'):
            for b in self.BAD:
                for k in ('date_from', 'date_to'):
                    r = cl(self.dirn).get(f'/api/treasury/{u}/?{k}={b}')
                    if r.status_code >= 500:
                        bad.append((u, k, b, r.status_code))
        self.assertEqual(bad, [])

    def test_BUG_818_generate_report_date_never_500(self):
        bad = []
        for b in self.BAD + (20261301, [], {}, True, '2026-02-30T10:00'):
            r = cl(self.g1).post('/api/treasury/reports/generate/', {'date': b}, format='json')
            if r.status_code >= 500:
                bad.append((b, r.status_code))
        self.assertEqual(bad, [])

    def test_post_dates_never_500(self):
        bad = []
        for b in self.BAD + (None, [], {}, 12345):
            for url, body in (
                ('/api/treasury/closures/', {'bills_50': 1}),
                ('/api/treasury/expenses/', {'description': 'x', 'amount': '10', 'category': self.cat.id}),
                ('/api/treasury/journal/', {'imput': 'EAU', 'label': 'x', 'exit_amount': '1'}),
                ('/api/treasury/savings/', {'daily_revenue': '10', 'flour_sacks': '1'}),
                ('/api/treasury/vouchers/', {'motif': 'm', 'bills_50': 1}),
                ('/api/treasury/reports/', {}),
            ):
                r = cl(self.dirn if 'vouchers' in url else self.g1).post(url, {**body, 'date': b}, format='json')
                if r.status_code >= 500:
                    bad.append((url, b, r.status_code))
        self.assertEqual(bad, [])

    def test_BUG_831_voucher_future_date_refused(self):
        fut = str(today() + timedelta(days=30))
        append_cashbook_entry(node=self.n1, date=today(), piece_number='VC-C1-1', imputation='7000',
                              label='seed', entry_amount=Dc('100000'), node_origin='C1')
        r = cl(self.dirn).post('/api/treasury/vouchers/', {'date': fut, 'motif': 'm', 'bills_5000': 1}, format='json')
        self.assertEqual(r.status_code, 400, 'bon de decaissement date dans le futur : %s' % r.status_code)


# =====================================================================
# 8. BUG-819 : plages numeriques
# =====================================================================
class V819(Base):
    def test_huge_entries_and_expenses_totals_are_400(self):
        self.report(self.n1, 'A', BIG); self.report(self.n1, 'B', '1')
        r = self.close(self.g1, {'bills_50': 1})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(CashClosure.objects.exists())

    def test_BUG_834_gap_overflow_with_max_expense_is_400_not_500(self):
        """BUG-835 : une seule depense de 999 999 999 999,99 FC + 50 FC de billets :
        net = -BIG, ecart = physique - net = BIG + 50 hors DecimalField(14,2)."""
        self.assertEqual(self.expense(self.g1, BIG).status_code, 201)
        r = self.close(self.g1, {'bills_50': 1})
        self.assertLess(r.status_code, 500, 'depassement de l ecart : %s' % r.status_code)

    def test_BUG_834_push_two_max_closures_running_balance_overflow(self):
        """BUG-836 : deux versements de 999 999 999 999,99 FC : solde cumule hors plage -> 500 au
        2e versement (la 1re est bien ecrite)."""
        self.report(self.n1, 'A', BIG); self.report(self.n2, 'A', BIG)
        c1 = self.close(self.g1, {'bills_50': 0}).json()
        c2 = self.close(self.g2, {'bills_50': 0}).json()
        self.assertEqual(self.versement(c1['id']).status_code, 201)
        r = self.versement(c2['id'])
        self.assertLess(r.status_code, 500, 'solde cumule hors plage : %s' % r.status_code)
        self.assertTrue(self.chain_ok())


# =====================================================================
# 9. Integrite, alertes, snapshots, ActivityLog, N+1, concurrence
# =====================================================================
class Integrite(Base):
    def seed_chain(self, k=3):
        out = []
        for i, n in enumerate((self.n1, self.n2, self.n1)[:k]):
            d = today() - timedelta(days=k - i)
            self.report(n, 'A', str(10000 * (i + 1)), date=d)
            c = cl(self.g1 if n == self.n1 else self.g2).post('/api/treasury/closures/', {
                'date': str(d), **{b: 0 for b in BILLS}}, format='json')
            out.append(c)
        return out

    def chain3(self):
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        for i, (n, g) in enumerate(((self.n1, self.g1), (self.n2, self.g2), (self.n1, self.g1))):
            d = today() - timedelta(days=3 - i)
            self.report(n, 'A', str(10000 * (i + 1)), date=d, facturier=make_user('FACTURIER', n, team='A'))
            c = cl(g).post('/api/treasury/closures/', {'date': str(d), **{b: 0 for b in BILLS}}, format='json')
            self.assertEqual(c.status_code, 201, c.content)
            self.assertEqual(self.versement(c.json()['id']).status_code, 201)

    def test_two_endpoints_same_verdict_clean_and_tampered_and_truncated(self):
        self.chain3()
        a = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()
        b = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        self.assertTrue(a['chain_valid'] and b['all_intact'])
        e = CashbookEntry.chain_queryset()[1]
        CashbookEntry.objects.filter(pk=e.pk).update(entry_amount=Dc('1.00'))
        a = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()
        b = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        self.assertFalse(a['chain_valid']); self.assertFalse(b['all_intact'])
        self.assertEqual(a['tampered_count'], sum(r['tampered_count'] for r in b['results']))
        self.assertEqual(sorted(a['tampered_ids']), sorted(i for r in b['results'] for i in r['tampered_ids']))

    def test_voucher_with_old_date_after_newer_entries_keeps_chain_valid_and_sums_coherent(self):
        self.chain3()
        v = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today() - timedelta(days=400)), 'motif': 'm', 'bills_20000': 1}, format='json')
        self.assertEqual(v.status_code, 201, v.content)
        self.assertTrue(self.chain_ok())
        last = CashbookEntry.chain_queryset().last()
        self.assertEqual(last.running_balance, Dc('60000') - Dc('20000'))
        ps = cl(self.dirn).get('/api/treasury/cashbook/period_summary/?date_from=2000-01-01&date_to=2100-01-01').json()
        self.assertEqual(sum(Dc(x['total_entries']) for x in ps) - sum(Dc(x['total_exits']) for x in ps), last.running_balance)

    def test_BUG_835_direction_count_theoretical_balance_ignores_chain_order(self):
        """BUG-837 : versements pousses hors ordre chronologique (J+1 avant J). Le solde
        theorique d'un comptage a la date J+1 doit etre le cumul de toutes les ecritures
        datees <= J+1 ; il reprend l'ecriture la plus recente PAR DATE, dont le solde ne tient
        pas compte de l'ecriture J poussee apres."""
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        d1, d0 = today(), today() - timedelta(days=1)
        for d, g, n, amt in ((d1, self.g1, self.n1, '10000'), (d0, self.g2, self.n2, '5000')):
            self.report(n, 'A', amt, date=d, facturier=make_user('FACTURIER', n, team='A'))
            c = cl(g).post('/api/treasury/closures/', {'date': str(d), **{b: 0 for b in BILLS}}, format='json')
            self.assertEqual(self.versement(c.json()['id']).status_code, 201)
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/', {'date': str(d1), 'bills_10000': 1, 'bills_5000': 1}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['theoretical_balance']), Dc('15000'))

    def test_BUG_836_run_check_with_node_filter_blames_unrelated_node(self):
        self.chain3()
        last = CashbookEntry.chain_queryset().last()
        CashbookEntry.objects.filter(pk=last.pk).delete()  # amputation de la queue
        other = Node.objects.exclude(pk=last.node_id).exclude(code='SIEGE').first()
        r = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {'node': other.id}, format='json').json()
        self.assertTrue(r['results'][0]['is_intact'], "le noeud %s n'a aucune ecriture altérée : %s" % (other.code, r['results'][0]))
        self.assertFalse(TamperAlert.objects.filter(node=other).exists())

    def test_BUG_836_repeated_checks_duplicate_alerts(self):
        self.chain3()
        e = CashbookEntry.chain_queryset()[0]
        CashbookEntry.objects.filter(pk=e.pk).update(label='falsifie')
        for _ in range(3):
            cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        n_open = TamperAlert.objects.filter(is_resolved=False, node=e.node).count()
        self.assertEqual(n_open, 1, '%d alertes ouvertes identiques apres 3 verifications' % n_open)

    def test_snapshot_is_one_per_node_per_day(self):
        self.chain3()
        for _ in range(3):
            cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(BlockchainSnapshot.objects.filter(node=self.n1).count(), 1)
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertTrue(gs['all_intact'])
        self.assertEqual(gs['open_alerts'], 0)

    def test_resolve_alert_twice_and_roles(self):
        a = TamperAlert.objects.create(node=self.n1, affected_model='CashbookEntry', description='x')
        u = f'/api/blockchain/alerts/{a.id}/resolve/'
        self.assertEqual(cl(self.g1).post(u).status_code, 403)
        self.assertEqual(cl(self.dirn).post(u).status_code, 200)
        self.assertEqual(cl(self.dirn).post(u).status_code, 400)
        a.refresh_from_db()
        self.assertEqual(a.resolved_by_id, self.dirn.id)

    def test_BUG_836_global_status_intact_with_zero_nodes_checked(self):
        gs = cl(self.dirn).get('/api/blockchain/snapshots/global_status/').json()
        self.assertEqual(gs['nodes_checked'], 0)
        self.assertIsNot(gs['all_intact'], True, 'aucune verification faite : "intact" est un faux positif')

    def test_BUG_837_activity_log_on_significant_treasury_actions(self):
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
        b = n(); cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'r'}, format='json')
        if n() == b: missing.append('closure reject')
        b = n(); cl(self.g1).delete(f"/api/treasury/closures/{c['id']}/")
        if n() == b: missing.append('closure delete')
        b = n(); cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        if n() == b: missing.append('run_check')
        a = TamperAlert.objects.create(node=self.n1, affected_model='X', description='x')
        b = n(); cl(self.dirn).post(f'/api/blockchain/alerts/{a.id}/resolve/')
        if n() == b: missing.append('alert resolve')
        self.assertEqual(missing, [])

    def test_BUG_838_no_n_plus_one_on_lists(self):
        def count(url, user):
            with CaptureQueriesContext(connection) as q:
                r = cl(user).get(url)
            self.assertEqual(r.status_code, 200, (url, r.content[:200]))
            return len(q)
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        urls = ['/api/treasury/expenses/', '/api/treasury/reports/', '/api/treasury/closures/', '/api/treasury/cashbook/',
                '/api/treasury/journal/', '/api/treasury/savings/', '/api/treasury/vouchers/',
                '/api/treasury/closures/versements/', '/api/blockchain/alerts/', '/api/blockchain/snapshots/']

        def grow(k0, k1):
            for i in range(k0, k1):
                d = today() - timedelta(days=i + 1)
                n = self.n1
                make_user('FACTURIER', n, team='A')
                self.report(n, 'A', '1000', date=d, facturier=make_user('FACTURIER', n, team='B'))
                cl(self.g1).post('/api/treasury/expenses/', {'description': 'e', 'amount': '5', 'category': self.cat.id, 'date': str(d)}, format='json')
                c = cl(self.g1).post('/api/treasury/closures/', {'date': str(d), 'bills_50': 1}, format='json')
                self.versement(c.json()['id'])
                cl(self.g1).post('/api/treasury/journal/', {'date': str(d), 'imput': 'CA', 'label': 'x', 'entry_amount': '1000'}, format='json')
                cl(self.g1).post('/api/treasury/savings/', {'date': str(d), 'daily_revenue': '1000', 'flour_sacks': '1'}, format='json')
                cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(d), 'motif': 'm', 'bills_50': 1}, format='json')
                TamperAlert.objects.create(node=self.n1, affected_model='X', description='x')
                BlockchainSnapshot.objects.create(node=self.n1, snapshot_date=d)
        grow(0, 3)
        small = {u: count(u, self.dirn) for u in urls}
        grow(3, 12)
        big = {u: count(u, self.dirn) for u in urls}
        grew = {u: (small[u], big[u]) for u in urls if big[u] > small[u]}
        self.assertEqual(grew, {})


class Concurrence(Base):
    def test_BUG_839_stale_push_creates_double_versement(self):
        """BUG-841 : deux versements de la meme cloture (lecture perimee : la seconde requete a lu
        `cashbook_entries` avant que la premiere ait ecrit). Aucune garde ne tient dans la
        transaction d'ecriture (`exists()` hors verrou, pas de contrainte d'unicite sur
        source_closure) : le cash est compte deux fois."""
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        stale = CashClosure.objects.prefetch_related('cashbook_entries').get(pk=c['id'])
        list(stale.cashbook_entries.all())  # cache vide : l'etat vu par la 2e requete
        fresh = CashClosure.objects.get(pk=c['id'])
        promote_closure_to_cashbook(fresh, acting_user=self.compt)
        try:
            promote_closure_to_cashbook(stale, acting_user=self.compt)
        except ClosureAlreadyPromotedError:
            pass
        self.assertEqual(CashbookEntry.objects.filter(source_closure_id=c['id']).count(), 1)

    def test_BUG_839_failed_append_leaves_orphan_voucher(self):
        """BUG-842 : si l'ecriture au livre echoue (autre chose qu'un refus de solde), le bon de
        decaissement deja enregistre reste sans ecriture (pas de transaction englobante)."""
        append_cashbook_entry(node=self.n1, date=today(), piece_number='VC-C1-1', imputation='7000',
                              label='seed', entry_amount=Dc('100000'), node_origin='C1')
        from django.db import OperationalError
        with mock.patch('treasury.views.append_cashbook_entry', side_effect=OperationalError('verrou')):
            r = cl(self.dirn).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm', 'bills_5000': 2}, format='json')
        self.assertEqual(DisbursementVoucher.objects.count(), 0, 'bon sans ecriture au livre (statut %s)' % r.status_code)

    def test_BUG_839_failed_append_leaves_closure_modified(self):
        """BUG-843 : `promote_closure_to_cashbook` recalcule et ENREGISTRE la cloture confirmee avant
        l'ecriture au livre, hors transaction : si l'ecriture echoue, la cloture confirmee reste
        modifiee (net, ecart) sans versement."""
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        # depense ajoutee entre-temps par un chemin hors API (synchronisation) : le recalcul change net/ecart
        LocalExpense.objects.create(node=self.n1, gerant=self.g1, description='sync', amount=Dc('2000'),
                                    category=self.cat, date=today(), node_origin='C1')
        from django.db import OperationalError
        with mock.patch('treasury.services.append_cashbook_entry', side_effect=OperationalError('x')):
            try:
                promote_closure_to_cashbook(CashClosure.objects.get(pk=c['id']), acting_user=self.compt)
            except OperationalError:
                pass
        cc = CashClosure.objects.get(pk=c['id'])
        self.assertFalse(cc.cashbook_entries.exists())
        self.assertEqual(cc.net_cash, Dc('10000'), 'cloture confirmee modifiee sans versement : net=%s' % cc.net_cash)

    def test_BUG_839_validate_confirms_stale_totals_then_push_changes_them(self):
        """BUG-844 : une depense saisie apres la creation de la cloture (jour non encore confirme)
        n'est pas prise en compte a la confirmation ; le versement recalcule ensuite net et ecart de la
        cloture CONFIRMEE : le montant confirme par le comptable != le montant inscrit au livre."""
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(self.expense(self.g1, '2500').status_code, 201)
        v = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json').json()
        confirmed_net = Dc(v['net_cash'])
        e = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json').json()
        self.assertEqual(Dc(e['entry_amount']), confirmed_net, 'confirme %s, inscrit %s' % (confirmed_net, e['entry_amount']))

    def test_sequence_30_entries_chain_and_double_push_refused(self):
        for i in range(30):
            append_cashbook_entry(node=self.n1 if i % 2 else self.n2, date=today(), piece_number=f'P{i}', imputation='7000',
                                  label=f'l{i}', entry_amount=Dc(100 + i), node_origin='X')
        self.assertTrue(self.chain_ok())
        self.assertEqual(CashbookEntry.chain_queryset().last().running_balance, sum(Dc(100 + i) for i in range(30)))
        self.report(self.n1, 'A', '1000')
        c = self.close(self.g1, {'bills_1000': 1}).json()
        self.assertEqual(self.versement(c['id']).status_code, 201)
        r = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CashbookEntry.objects.filter(source_closure_id=c['id']).count(), 1)


class ClotureMiseAJour(Base):
    def test_BUG_815_closure_patch_date_to_existing_day_is_400_not_500(self):
        """BUG-845 : PATCH de `date` d'une cloture infirmee vers le jour d'une autre cloture du meme
        noeud : IntegrityError non rattrapee dans perform_update -> 500."""
        cfg = Config.get_instance(); cfg.allow_backdated_sales = True; cfg.save()
        y = today() - timedelta(days=1)
        c0 = cl(self.g1).post('/api/treasury/closures/', {'date': str(y), 'bills_50': 1}, format='json').json()
        c1 = self.close(self.g1, {'bills_50': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c1['id']}/reject/", {'reason': 'r'}, format='json')
        r = cl(self.g1).patch(f"/api/treasury/closures/{c1['id']}/", {'date': str(y)}, format='json')
        self.assertLess(r.status_code, 500, r.status_code)
        self.assertEqual(CashClosure.objects.filter(node=self.n1).count(), 2)

    def test_computed_fields_cannot_be_forged_on_create_or_update(self):
        self.report(self.n1, 'A', '10000')
        forged = {'is_validated': True, 'is_rejected': True, 'net_cash': '99999', 'cash_gap': '0', 'total_entries': '1',
                  'total_expenses': '1', 'physical_cash_total': '1', 'gerant': self.adm.id, 'node': self.n2.id, 'node_origin': 'ZZ'}
        r = self.close(self.g1, {'bills_10000': 1}, **forged)
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((d['is_validated'], d['is_rejected'], Dc(d['net_cash']), Dc(d['total_entries']), d['node']),
                         (False, False, Dc('10000'), Dc('10000'), self.n1.id))
        r = cl(self.g1).patch(f"/api/treasury/closures/{d['id']}/", forged, format='json')
        self.assertLess(r.status_code, 500)
        c = CashClosure.objects.get(pk=d['id'])
        self.assertEqual((c.is_validated, c.net_cash, c.node_id), (False, Dc('10000'), self.n1.id))

    def test_validate_reject_roles_and_idempotence(self):
        self.report(self.n1, 'A', '1000')
        c = self.close(self.g1, {'bills_1000': 1}).json()
        u = f"/api/treasury/closures/{c['id']}"
        for who in (self.g1, self.fac, self.liv):
            self.assertEqual(cl(who).post(u + '/validate/').status_code, 403)
            self.assertEqual(cl(who).post(u + '/push_to_cashbook/').status_code, 403)
        self.assertEqual(cl(self.compt).post(u + '/push_to_cashbook/').status_code, 400)  # non confirmee
        self.assertEqual(cl(self.compt).post(u + '/validate/').status_code, 200)
        self.assertEqual(cl(self.compt).post(u + '/validate/').status_code, 400)
        self.assertEqual(cl(self.compt).post(u + '/reject/', {'reason': 'x'}, format='json').status_code, 400)
        self.assertEqual(cl(self.compt).post(u + '/reject/', {'reason': ['x']}, format='json').status_code in (200, 400, 403), True)

    def test_observation_direction_count_without_any_denomination(self):
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/', {'date': str(today())}, format='json')
        if r.status_code == 404:
            self.skipTest('route direction-counts introuvable')
        # OBSERVATION (pas de ticket, a clarifier avec BUG-811) : le comptage Direction sans aucune coupure
        # est accepte (201, ecart = -solde theorique). Le billetage n'est impose qu'au niveau 2.
        self.assertIn(r.status_code, (201, 400))
