"""Cycle 6, partie C (testeur-tresorerie, 2026-11-22-c6) : verification independante de
BUG-860, BUG-861, BUG-862, puis recherche de nouveaux defauts (confirmation avec ecart
recalcule, generate sur rapport valide, bons, epargne, chaine). Donnees fictives.
"""
import pathlib
import re
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.models import ActivityLog, SystemNotification
from core.testing import make_bread_price, make_client, make_user
from treasury.models import CashbookEntry, CashClosure, DailySavings, DisbursementVoucher, FacturierReport
from treasury.tests.test_cycle1_tresorerie_c import Base, cl, today
from treasury.tests.test_reports_closures import _make_invoice


def notifs(prefix):
    return SystemNotification.objects.filter(title__startswith=prefix).count()


def acts(prefix):
    return ActivityLog.objects.filter(action__startswith=prefix).count()


def last_notif():
    return SystemNotification.objects.filter(title__startswith='Écart de Caisse').latest('created_at')


# =====================================================================
# BUG-860
# =====================================================================
class V860(Base):
    def rejected(self, cash='10000', bills=None):
        self.report(self.n1, 'A', cash)
        c = self.close(self.g1, bills or {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'recompter'}, format='json')
        return c

    def patch(self, c, body):
        return cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/", body, format='json')

    def test_resubmission_logged_and_notified_warning(self):
        c = self.rejected()
        n_log, n_not = acts('Resoumission'), notifs('Écart de Caisse')
        r = self.patch(c, {'bills_10000': 0, 'bills_5000': 1})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Dc(r.json()['cash_gap']), Dc('-5000'))
        self.assertEqual(acts('Resoumission'), n_log + 1)
        self.assertEqual(notifs('Écart de Caisse'), n_not + 1)
        n = last_notif()
        self.assertEqual((n.severity, n.node_origin), ('WARNING', 'C1'))
        log = ActivityLog.objects.filter(action__startswith='Resoumission').latest('created_at')
        self.assertEqual(log.node_origin, 'C1')

    def test_resubmission_big_gap_is_danger(self):
        c = self.rejected()
        self.patch(c, {'bills_10000': 0, 'bills_20000': 1})
        self.assertEqual(last_notif().severity, 'DANGER')

    def test_resubmission_exact_count_logged_but_not_notified(self):
        c = self.rejected()
        n_not = notifs('Écart de Caisse')
        r = self.patch(c, {'bills_10000': 0, 'bills_5000': 2})
        self.assertEqual(Dc(r.json()['cash_gap']), 0)
        self.assertEqual(acts('Resoumission'), 1)
        self.assertEqual(notifs('Écart de Caisse'), n_not)

    def test_two_resubmissions_two_traces(self):
        c = self.rejected()
        self.patch(c, {'bills_10000': 0, 'bills_5000': 1})
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'encore'}, format='json')
        self.patch(c, {'bills_5000': 3})
        self.assertEqual(acts('Resoumission'), 2)

    def test_refused_resubmission_leaves_no_trace(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        n_log, n_not = acts('Resoumission'), notifs('Écart de Caisse')
        r = self.patch(c, {'bills_50': 1})
        self.assertEqual(r.status_code, 400)
        self.assertEqual((acts('Resoumission'), notifs('Écart de Caisse')), (n_log, n_not))

    def test_resubmission_clears_rejection_and_recomputes(self):
        c = self.rejected()
        d = self.patch(c, {'bills_10000': 0, 'bills_1000': 3}).json()
        self.assertFalse(d['is_rejected'])
        self.assertEqual(Dc(d['physical_cash_total']), Dc('3000'))
        self.assertEqual(Dc(d['cash_gap']), Dc('-7000'))


# =====================================================================
# BUG-861
# =====================================================================
class V861(Base):
    def seed(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 2}).json()
        self.versement(c['id'])
        self.report(self.n2, 'A', '4000')
        c2 = self.close(self.g2, {'bills_1000': 4}).json()
        self.versement(c2['id'])
        return list(CashbookEntry.chain_queryset())

    def flag(self, e):
        return CashbookEntry.objects.get(pk=e.pk).is_tampered

    def test_integrity_check_resets_flag_and_renotifies(self):
        e1, e2 = self.seed()
        for cycle in range(3):
            n = notifs('Alerte Blockchain')
            CashbookEntry.objects.filter(pk=e2.pk).update(label=f'falsifie {cycle}')
            for _ in range(2):
                self.assertFalse(self.chain_ok())
            self.assertTrue(self.flag(e2))
            self.assertEqual(notifs('Alerte Blockchain'), n + 1, cycle)   # BUG-842 intact
            CashbookEntry.objects.filter(pk=e2.pk).update(label=e2.label)
            self.assertTrue(self.chain_ok())
            self.assertFalse(self.flag(e2))
            self.assertEqual(notifs('Alerte Blockchain'), n + 1)         # reparation : pas de bruit

    def test_run_check_resets_flag(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e2.pk).update(label='falsifie')
        rc = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        self.assertTrue(any(not r['is_intact'] for r in rc['results']))
        self.assertTrue(self.flag(e2))
        CashbookEntry.objects.filter(pk=e2.pk).update(label=e2.label)
        rc = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        self.assertTrue(all(r['is_intact'] for r in rc['results']))
        self.assertFalse(self.flag(e2))
        self.assertTrue(self.chain_ok())

    def test_repair_via_run_check_then_retamper_notified_by_integrity_check(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e2.pk).update(label='falsifie')
        self.assertFalse(self.chain_ok())
        CashbookEntry.objects.filter(pk=e2.pk).update(label=e2.label)
        cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertFalse(self.flag(e2))
        n = notifs('Alerte Blockchain')
        CashbookEntry.objects.filter(pk=e2.pk).update(label='falsifie bis')
        self.assertFalse(self.chain_ok())
        self.assertEqual(notifs('Alerte Blockchain'), n + 1)

    def test_cascade_flags_reset_only_for_valid_entries(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e1.pk).update(label='falsifie')   # cascade sur e2
        self.assertFalse(self.chain_ok())
        self.assertTrue(self.flag(e1) and self.flag(e2))
        CashbookEntry.objects.filter(pk=e1.pk).update(label=e1.label)
        CashbookEntry.objects.filter(pk=e2.pk).update(label='autre')       # e2 reste altere
        self.assertFalse(self.chain_ok())
        self.assertFalse(self.flag(e1))
        self.assertTrue(self.flag(e2))

    def test_clean_chain_never_flags_and_no_notification(self):
        self.seed()
        for _ in range(3):
            self.assertTrue(self.chain_ok())
        self.assertFalse(CashbookEntry.objects.filter(is_tampered=True).exists())
        self.assertEqual(notifs('Alerte Blockchain'), 0)

    def test_api_filter_is_tampered_follows_repair(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e2.pk).update(label='falsifie')
        self.chain_ok()
        d = cl(self.dirn).get('/api/treasury/cashbook/?is_tampered=true').json()
        d = d['results'] if isinstance(d, dict) else d
        self.assertEqual(len(d), 1)
        CashbookEntry.objects.filter(pk=e2.pk).update(label=e2.label)
        self.chain_ok()
        d = cl(self.dirn).get('/api/treasury/cashbook/?is_tampered=true').json()
        d = d['results'] if isinstance(d, dict) else d
        self.assertEqual(d, [])

    def test_repair_does_not_hide_deletion(self):
        e1, e2 = self.seed()
        CashbookEntry.objects.filter(pk=e2.pk).delete()
        self.assertFalse(self.chain_ok())


# =====================================================================
# BUG-862 : lecture de code
# =====================================================================
class V862(Base):
    def test_border_uses_tone(self):
        p = pathlib.Path(__file__).resolve().parents[3] / 'frontend' / 'src' / 'pages' / 'dashboard' / 'Blockchain.tsx'
        src = p.read_text(encoding='utf-8')
        self.assertIn("borderLeft: `4px solid hsl(var(--${tone}))`", src)
        self.assertIsNone(re.search(r"borderLeft:[^\n]*allIntact", src))
        self.assertIn("const tone = neutral ? 'color-warning' : allIntact ? 'color-success' : 'color-danger';", src)


# =====================================================================
# Nouveaux angles
# =====================================================================
class Nouveaux(Base):
    def test_BUG_863_confirmation_with_recalculated_gap_is_notified(self):
        # Cloture exacte (ecart 0, aucune notification), depense saisie apres : a la confirmation
        # l'ecart devient non nul (+500) : il est confirme sans notification au gerant/siege.
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(Dc(c['cash_gap']), 0)
        self.assertEqual(self.expense(self.g1, '500').status_code, 201)
        n = notifs('Écart de Caisse')
        r = cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Dc(r.json()['cash_gap']), Dc('500'))
        self.assertGreater(notifs('Écart de Caisse'), n)

    def test_confirmation_recalculated_gap_in_activity_log(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        self.expense(self.g1, '500')
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        log = ActivityLog.objects.filter(action__startswith='Confirmation').latest('created_at')
        self.assertIn('Écart: 500', log.description)

    def test_versement_after_recalculated_confirmation_equals_confirmed_net(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        self.expense(self.g1, '500')
        r = self.versement(c['id'])
        self.assertEqual(r.status_code, 201, r.content)
        e = CashbookEntry.objects.get()
        self.assertEqual(e.entry_amount, Dc('9500'))
        self.assertEqual(CashClosure.objects.get(pk=c['id']).net_cash, Dc('9500'))
        self.assertTrue(self.chain_ok())

    # -- generate -----------------------------------------------------
    def _delivered(self):
        fac = make_user('FACTURIER', self.n1, team='A', username='facgen')
        client = make_client(self.n1)
        bread = make_bread_price(category='MOYEN', label='Pain 300 FC', unit_price=300)
        _make_invoice(self.n1, fac, 'A', client, bread, 10, 'CASH')
        return fac

    def test_generate_twice_idempotent(self):
        self._delivered()
        for _ in range(2):
            r = cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(FacturierReport.objects.filter(node=self.n1).count(), 1)
        self.assertEqual(FacturierReport.objects.get().total_cash_sales, Dc('3000'))

    def test_generate_on_validated_report_keeps_flag_and_totals_when_nothing_changed(self):
        self._delivered()
        cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
        rep = FacturierReport.objects.get()
        cl(self.g1).post(f'/api/treasury/reports/{rep.pk}/validate/', {}, format='json')
        r = cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        rep.refresh_from_db()
        self.assertTrue(rep.is_validated)
        self.assertEqual(rep.total_cash_sales, Dc('3000'))
        self.assertEqual(FacturierReport.objects.count(), 1)

    def test_delivery_after_validation_is_refused_on_that_vacation(self):
        fac = self._delivered()
        cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
        rep = FacturierReport.objects.get()
        cl(self.g1).post(f'/api/treasury/reports/{rep.pk}/validate/', {}, format='json')
        client = make_client(self.n1)
        bread = make_bread_price(category='GRAND', label='Pain 500 FC', unit_price=500)
        with self.assertRaises(Exception):
            _make_invoice(self.n1, fac, 'A', client, bread, 5, 'CASH')
        rep.refresh_from_db()
        self.assertEqual(rep.total_cash_sales, Dc('3000'))

    # -- bons, epargne, livre ----------------------------------------
    def fund(self, bills):
        self.report(self.n1, 'A', '100000')
        c = self.close(self.g1, bills).json()
        self.versement(c['id'])

    def test_voucher_reduces_balance_and_chain_stays_valid(self):
        self.fund({'bills_20000': 5})
        r = cl(self.dirn).post('/api/treasury/vouchers/', {
            'date': str(today()), 'motif': 'Achat', 'bills_20000': 1, 'bills_5000': 2}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        last = CashbookEntry.chain_queryset().last()
        self.assertEqual((last.running_balance, last.exit_amount), (Dc('70000'), Dc('30000')))
        self.assertTrue(self.chain_ok())
        self.assertEqual(DisbursementVoucher.objects.count(), 1)

    def test_voucher_refused_leaves_no_voucher_and_no_entry(self):
        self.fund({'bills_20000': 1})
        n = CashbookEntry.objects.count()
        r = cl(self.dirn).post('/api/treasury/vouchers/', {
            'date': str(today()), 'motif': 'x', 'bills_20000': 6}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashbookEntry.objects.count(), n)
        self.assertEqual(DisbursementVoucher.objects.count(), 0)

    def test_savings_does_not_touch_cashbook(self):
        self.fund({'bills_20000': 5})
        before = list(CashbookEntry.objects.values_list('running_balance', 'block_hash'))
        r = cl(self.g1).post('/api/treasury/savings/', {
            'date': str(today()), 'daily_revenue': '100000', 'savings_rate': '0.1', 'flour_sacks': '1'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(before, list(CashbookEntry.objects.values_list('running_balance', 'block_hash')))
        self.assertEqual(DailySavings.objects.get().savings_amount, Dc('10000.00'))

    def test_savings_same_day_twice_does_not_duplicate(self):
        body = {'date': str(today()), 'daily_revenue': '100000', 'savings_rate': '0.1', 'flour_sacks': '1'}
        cl(self.g1).post('/api/treasury/savings/', body, format='json')
        r = cl(self.g1).post('/api/treasury/savings/', dict(body, daily_revenue='200000'), format='json')
        self.assertLess(r.status_code, 500)
        self.assertEqual(DailySavings.objects.filter(node=self.n1, date=today()).count(), 1)

    def test_last_balance_read_under_lock(self):
        import inspect
        import treasury.views as tv
        self.assertIn('select_for_update', inspect.getsource(tv._get_last_balance))

    def test_single_hash_function(self):
        import inspect
        import blockchain.views as bv
        import treasury.views as tv
        for mod in (tv, bv):
            code = [l for l in inspect.getsource(mod).splitlines() if not l.lstrip().startswith('#')]
            self.assertFalse([l for l in code if 'hashlib.sha256' in l or 'import hashlib' in l], mod.__name__)
