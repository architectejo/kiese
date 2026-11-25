"""Cycle 1, partie C (testeur-tresorerie, Dev C, 2026-11-22-c2) : nouveaux angles
d'attaque sur la tresorerie (cloture, rapports facturier, depenses, bons de
decaissement, epargne, journal, livre de caisse). Donnees fictives uniquement.

Ne rouvre pas : BUG-560 (?node= invalide, double POST reports), BUG-563.
Les anomalies trouvees portent un test `@expectedFailure` reference BUG-81x.
"""
from decimal import Decimal as Dc
from unittest import expectedFailure
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import ExpenseCategory, Node
from core.testing import make_node, make_user
from treasury.models import (
    CashbookEntry, CashClosure, DailySavings, DisbursementVoucher, FacturierReport,
    JournalEntry, LocalExpense,
)
from treasury.views import append_cashbook_entry

BILLS = ('bills_20000', 'bills_10000', 'bills_5000', 'bills_1000', 'bills_500', 'bills_200', 'bills_100', 'bills_50')
VALUES = (20000, 10000, 5000, 1000, 500, 200, 100, 50)


def today():
    # BUG-1130 : journée comptable de midi à midi (12:00 par défaut), pas le jour calendaire
    # (sinon les tests lancés entre 00:00 et 12:00 daterait « aujourd'hui » dans le futur).
    from core.workday import work_date_for
    return work_date_for(None)


def cl(user=None):
    c = APIClient()
    c.raise_request_exception = False  # un 500 doit apparaitre comme un statut, pas une exception
    if user is not None:
        c.force_authenticate(user)
    return c


def rows(r):
    d = r.json() if hasattr(r, 'json') else r.data
    return d['results'] if isinstance(d, dict) and 'results' in d else d


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.n1 = make_node('C1', 'Cycle C1')
        cls.n2 = make_node('C2', 'Cycle C2')
        cls.siege, _ = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege'})
        cls.adm = make_user('ADMIN')
        cls.dirn = make_user('DIRECTION')
        cls.compt = make_user('COMPTABLE')
        cls.g1 = make_user('GERANT', cls.n1)
        cls.g2 = make_user('GERANT', cls.n2)
        cls.fac = make_user('FACTURIER', cls.n1, team='A')
        cls.liv = make_user('LIVREUR', cls.n1, team='B')
        cls.cat, _ = ExpenseCategory.objects.get_or_create(code='EAUC', defaults={'label': 'Eau C'})

    # -- fabriques -------------------------------------------------
    def report(self, node, team, cash, credit=0, date=None, facturier=None):
        return FacturierReport.objects.create(
            node=node, facturier=facturier or make_user('FACTURIER', node, team=team), team=team,
            date=date or today(), total_cash_sales=Dc(cash), total_credit_sales=Dc(credit),
            theoretical_cash=Dc(cash), node_origin=node.code)

    def expense(self, user, amount, date=None, **kw):
        return cl(user).post('/api/treasury/expenses/', {
            'description': 'Eau', 'amount': amount, 'category': self.cat.id,
            'date': str(date or today()), **kw}, format='json')

    def close(self, user, bills=None, **kw):
        body = {'date': str(today())}
        body.update({b: 0 for b in BILLS})
        body.update(bills or {})
        body.update(kw)
        return cl(user).post('/api/treasury/closures/', body, format='json')

    def versement(self, closure_id):
        r = cl(self.compt).post(f'/api/treasury/closures/{closure_id}/validate/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return cl(self.compt).post(f'/api/treasury/closures/{closure_id}/push_to_cashbook/', {}, format='json')

    def chain_ok(self):
        r = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['chain_valid']


# =====================================================================
# Cloture journaliere (niveau 2)
# =====================================================================
class Cloture(Base):
    def test_billetage_total_is_sum_qty_x_value_all_8(self):
        b = dict(zip(BILLS, (3, 2, 1, 4, 5, 6, 7, 8)))
        r = self.close(self.g1, b)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['physical_cash_total']), Dc(sum(q * v for q, v in zip(b.values(), VALUES))))

    def test_net_is_cash_minus_local_expenses_and_gap_signs(self):
        self.report(self.n1, 'A', '50000'); self.report(self.n1, 'B', '30000.50', credit='9999')
        self.assertEqual(self.expense(self.g1, '12500.50').status_code, 201)
        self.expense(self.g2, '999')  # autre boulangerie : ignoree
        net = Dc('80000.50') - Dc('12500.50')  # 67500.00
        # compte exact -> ecart nul
        exact = {'bills_20000': 3, 'bills_5000': 1, 'bills_1000': 2, 'bills_500': 1}
        r = self.close(self.g1, exact)
        d = r.json()
        self.assertEqual((Dc(d['total_entries']), Dc(d['total_expenses']), Dc(d['net_cash'])),
                         (Dc('80000.50'), Dc('12500.50'), net))
        self.assertEqual(Dc(d['cash_gap']), Dc('0'))  # 60000+5000+2000+500 = 67500

    def test_gap_positive_and_negative(self):
        self.report(self.n1, 'A', '10000'); self.report(self.n2, 'A', '10000')
        pos = self.close(self.g1, {'bills_10000': 1, 'bills_500': 1}).json()
        neg = self.close(self.g2, {'bills_5000': 1}).json()
        self.assertEqual(Dc(pos['cash_gap']), Dc('500'))
        self.assertEqual(Dc(neg['cash_gap']), Dc('-5000'))

    def test_BUG_811_all_denominations_omitted_is_not_accepted_silently(self):
        """BUG-811 (b). Billetage obligatoire (CLAUDE.md 5.5) : un corps sans aucune coupure est refuse."""
        self.report(self.n1, 'A', '10000')
        r = cl(self.g1).post('/api/treasury/closures/', {'date': str(today())}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_bad_bill_values_are_400(self):
        for bad in (-1, 1.5, 'abc', None, 100001, True, [1], {'a': 1}, '1e9', 10 ** 30):
            with self.subTest(bad=bad):
                r = self.close(self.g1, {'bills_50': bad})
                self.assertEqual(r.status_code, 400, (bad, r.status_code))
        self.assertFalse(CashClosure.objects.exists())

    def test_double_closure_same_day_refused_other_node_ok(self):
        self.assertEqual(self.close(self.g1).status_code, 201)
        r = self.close(self.g1)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashClosure.objects.filter(node=self.n1).count(), 1)
        self.assertEqual(self.close(self.g2).status_code, 201)
        # gerant qui force node=n2 pour une 2e cloture : ecrase par son noeud -> refuse
        self.assertEqual(self.close(self.g1, node=self.n2.id).status_code, 400)
        self.assertEqual(CashClosure.objects.filter(node=self.n2).count(), 1)

    def test_other_day_future_and_past(self):
        from datetime import timedelta
        self.assertEqual(self.close(self.g1, date=str(today() + timedelta(days=1))).status_code, 400)
        self.assertEqual(self.close(self.g1, date='2026-02-30').status_code, 400)
        for d in ('', 'abc', 20261122, None, [1]):
            with self.subTest(d=d):
                self.assertLess(self.close(self.g1, date=d).status_code, 500)

    def test_hq_closure_for_given_node_and_forged_ids(self):
        r = self.close(self.dirn, node=self.n2.id)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['node'], self.n2.id)
        self.assertEqual(self.close(self.dirn).status_code, 400)           # sans noeud
        self.assertEqual(self.close(self.dirn, node=999999).status_code, 400)

    def test_BUG_810_non_numeric_node_in_body_is_400_not_500(self):
        """BUG-810 : `node: "abc"` (corps POST, siege) -> ValueError -> 500."""
        self.report(self.n1, 'A', '1000')
        for url, body in (('/api/treasury/closures/', {'date': str(today())}),
                          ('/api/treasury/expenses/', {'description': 'x', 'amount': '10',
                                                       'category': self.cat.id, 'date': str(today())}),
                          ('/api/treasury/reports/generate/', {})):
            with self.subTest(url=url):
                r = cl(self.dirn).post(url, {**body, 'node': 'abc'}, format='json')
                self.assertEqual(r.status_code, 400, (url, r.status_code))

    def test_gerant_cannot_move_closure_to_other_node_and_gap_readonly(self):
        c = self.close(self.g1, {'bills_50': 1}).json()
        r = cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/",
                              {'node': self.n2.id, 'cash_gap': '0', 'net_cash': '999', 'is_validated': True,
                               'total_entries': '5'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o = CashClosure.objects.get(pk=c['id'])
        self.assertEqual((o.node_id, o.is_validated, o.total_entries), (self.n1.id, False, 0))
        self.assertEqual(o.cash_gap, Dc('50'))
        self.assertEqual(cl(self.g2).patch(f"/api/treasury/closures/{c['id']}/", {'bills_50': 9}, format='json').status_code, 404)

    @expectedFailure
    def test_BUG_811_pending_closure_gap_cannot_be_silently_rewritten(self):
        """BUG-811 : une cloture NON infirmee/NON confirmee est modifiable par le gerant (billetage
        change -> ecart recalcule, aucune notification ni trace), alors que `perform_update` annonce
        « seule une cloture infirmee peut etre modifiee » (remarque.md l.156)."""
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 1}).json()
        self.assertEqual(Dc(c['cash_gap']), Dc('-5000'))
        r = cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/", {'bills_10000': 1, 'bills_5000': 0}, format='json')
        self.assertIn(r.status_code, (400, 403), r.content)
        self.assertEqual(CashClosure.objects.get(pk=c['id']).cash_gap, Dc('-5000'))

    def test_validated_closure_is_frozen_and_roles(self):
        c = self.close(self.g1, {'bills_50': 1}).json()
        u = f"/api/treasury/closures/{c['id']}/"
        self.assertEqual(cl(self.g1).post(u + 'validate/', {}, format='json').status_code, 403)
        self.assertEqual(cl(self.fac).get(u).status_code, 403)
        self.assertEqual(cl(self.liv).get('/api/treasury/closures/').status_code, 403)
        self.assertEqual(cl().get('/api/treasury/closures/').status_code, 401)
        self.assertEqual(cl(self.compt).post(u + 'validate/', {}, format='json').status_code, 200)
        self.assertEqual(cl(self.compt).post(u + 'validate/', {}, format='json').status_code, 400)
        self.assertEqual(cl(self.compt).post(u + 'reject/', {'reason': 'x'}, format='json').status_code, 400)
        for m in ('put', 'patch'):
            self.assertIn(getattr(cl(self.g1), m)(u, {'bills_50': 99, 'date': str(today())}, format='json').status_code, (400, 403))
        self.assertEqual(cl(self.g1).delete(u).status_code, 403)
        self.assertEqual(cl(self.dirn).delete(u).status_code, 403)
        self.assertEqual(CashClosure.objects.get(pk=c['id']).bills_50, 1)

    def test_reject_then_resubmit_recomputes_and_clears_flag(self):
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 1}).json()
        u = f"/api/treasury/closures/{c['id']}/"
        self.assertEqual(cl(self.compt).post(u + 'reject/', {'reason': 'recompter'}, format='json').status_code, 200)
        r = cl(self.g1).patch(u, {'bills_10000': 1, 'bills_5000': 0}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual((Dc(d['cash_gap']), d['is_rejected']), (Dc('0'), False))

    def test_expenses_after_creation_recomputed_on_push(self):
        """Ventes/depenses arrivees apres la preparation : recalcul au versement."""
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        self.report(self.n1, 'B', '5000')
        self.expense(self.g1, '2000')
        r = self.versement(c['id'])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['entry_amount']), Dc('13000'))
        o = CashClosure.objects.get(pk=c['id'])
        self.assertEqual(o.cash_gap, Dc('10000') - Dc('13000'))

    def test_disputed_transfer_blocks_create_validate_push(self):
        from production.models import BreadTransfer, BreadTransferLine
        from core.testing import make_bread_price
        bread = make_bread_price('MOYEN', 'Pain 300 C', 300)
        c = self.close(self.g1).json()  # cloture creee avant le litige
        t = BreadTransfer.objects.create(from_node=self.n2, to_node=self.n1, node_origin='C2')
        BreadTransferLine.objects.create(transfer=t, bread_price=bread, quantity_sent=100, quantity_received=80)
        self.assertEqual(self.close(self.g1, date=str(today())).status_code, 400)
        u = f"/api/treasury/closures/{c['id']}/"
        self.assertEqual(cl(self.compt).post(u + 'validate/', {}, format='json').status_code, 400)
        CashClosure.objects.filter(pk=c['id']).update(is_validated=True)
        self.assertEqual(cl(self.compt).post(u + 'push_to_cashbook/', {}, format='json').status_code, 400)
        self.assertFalse(CashbookEntry.objects.exists())
        # une cloture de l'AUTRE boulangerie n'est pas bloquee (litige = noeud recepteur)
        self.assertEqual(self.close(self.g2).status_code, 201)

    def test_BUG_819_huge_expenses_do_not_make_closure_500_or_vanish(self):
        """BUG-819 : deux depenses de 999 999 999 999,99 FC (chacune valide) le meme jour : la somme
        depasse DecimalField(14,2) ; la cloture est ENREGISTREE puis la reponse leve
        `InvalidOperation` (500) ; la ligne devient invisible (exclue de la liste par BUG-201) et
        un nouvel essai donne « cloture existante ». Attendu : 400 avant ecriture."""
        self.expense(self.g1, '999999999999.99')
        self.expense(self.g1, '999999999999.99')
        r = self.close(self.g1)
        self.assertLess(r.status_code, 500, r.content)
        if r.status_code == 201:
            ids = [x['id'] for x in rows(cl(self.g1).get('/api/treasury/closures/'))]
            self.assertIn(r.json()['id'], ids)


# =====================================================================
# Rapports facturier (niveau 1)
# =====================================================================
class Rapports(Base):
    def test_gerant_report_team_is_forced_and_totals_readonly(self):
        r = cl(self.g1).post('/api/treasury/reports/', {
            'node': self.n2.id, 'date': str(today()), 'team': 'Z',
            'total_cash_sales': '999999', 'is_validated': True}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        o = FacturierReport.objects.get(pk=r.json()['id'])
        self.assertEqual((o.node_id, o.total_cash_sales, o.is_validated), (self.n1.id, 0, False))

    def test_BUG_812_report_team_must_be_A_or_B(self):
        """BUG-812 : `perform_create` enregistre `team=user.team` sans controle : un gerant sans
        equipe (``''``) ou d'une equipe hors A/B (ex. `C`) cree un rapport d'equipe `''`/`C`."""
        for team in ('', 'C'):
            with self.subTest(team=team):
                g = make_user('GERANT', self.n2, team=team)
                r = cl(g).post('/api/treasury/reports/', {'date': str(today())}, format='json')
                self.assertEqual(r.status_code, 400, (team, r.status_code, r.content))
        self.assertFalse(FacturierReport.objects.exclude(team__in=('A', 'B')).exists())

    def test_generate_only_team_A_B_and_idempotent_from_invoices(self):
        from sales.models import Invoice
        from core.testing import make_client, make_bread_price
        from treasury.tests.test_reports_closures import _make_invoice
        bread = make_bread_price('MOYEN', 'Pain 300 C', 300)
        cli = make_client(self.n1)
        _make_invoice(self.n1, self.fac, 'A', cli, bread, 5, Invoice.PaymentType.CASH)
        _make_invoice(self.n1, self.liv, 'B', cli, bread, 2, Invoice.PaymentType.CASH)
        for _ in range(2):
            r = cl(self.g1).post('/api/treasury/reports/generate/', {}, format='json')
            self.assertEqual(r.status_code, 200, r.content)
        got = {x.team: x.total_cash_sales for x in FacturierReport.objects.filter(node=self.n1)}
        self.assertEqual(got, {'A': Dc('1500'), 'B': Dc('600')})
        self.assertEqual(cl(self.g1).post('/api/treasury/reports/generate/', {'date': 'abc'}, format='json').status_code, 400)
        self.assertEqual(cl(self.fac).post('/api/treasury/reports/generate/', {}, format='json').status_code, 403)

    def test_validated_report_is_frozen_and_lists_scoped(self):
        rp = self.report(self.n1, 'A', '100')
        other = self.report(self.n2, 'A', '100')
        u = f'/api/treasury/reports/{rp.id}/'
        self.assertEqual(cl(self.g1).post(u + 'validate/', {}, format='json').status_code, 200)
        self.assertEqual(cl(self.g1).post(u + 'validate/', {}, format='json').status_code, 400)
        self.assertEqual(cl(self.g1).patch(u, {'date': str(today())}, format='json').status_code, 400)
        self.assertEqual(cl(self.g1).delete(u).status_code, 403)
        self.assertEqual(cl(self.g1).get(f'/api/treasury/reports/{other.id}/').status_code, 404)
        self.assertEqual(cl(self.g1).post(f'/api/treasury/reports/{other.id}/validate/', {}, format='json').status_code, 404)
        for who in (self.fac, self.liv):
            ids = {x['id'] for x in rows(cl(who).get('/api/treasury/reports/', {'node': self.n2.id}))}
            self.assertNotIn(str(other.id), {str(i) for i in ids})
            self.assertEqual(cl(who).post(u + 'validate/', {}, format='json').status_code, 403)
            self.assertEqual(cl(who).delete(f'/api/treasury/reports/{other.id}/').status_code, 403)


# =====================================================================
# Depenses locales
# =====================================================================
class Depenses(Base):
    def test_bad_amounts_are_400(self):
        for bad in ('0', 0, '-1', '-0.01', '100.005', '1e20', '99999999999999', '1000000000000.00', 'NaN',
                    'Infinity', 'abc', None, [1], True, '', ' ', '1,5'):
            with self.subTest(bad=bad):
                r = self.expense(self.g1, bad)
                self.assertEqual(r.status_code, 400, (bad, r.status_code))
        self.assertFalse(LocalExpense.objects.exists())
        self.assertEqual(self.expense(self.g1, '999999999999.99').status_code, 201)

    def test_category_and_date_invalid(self):
        for cat in (0, 999999, 'abc', None, [1], -1):
            with self.subTest(cat=cat):
                r = cl(self.g1).post('/api/treasury/expenses/', {'description': 'x', 'amount': '5',
                                     'category': cat, 'date': str(today())}, format='json')
                self.assertEqual(r.status_code, 400, (cat, r.status_code))
        for d in ('2026-13-01', 'abc', '', None, 20261122, [1]):
            with self.subTest(d=d):
                r = cl(self.g1).post('/api/treasury/expenses/', {'description': 'x', 'amount': '5',
                                     'category': self.cat.id, 'date': d}, format='json')
                self.assertEqual(r.status_code, 400, (d, r.status_code))

    def test_forged_node_and_roles(self):
        r = self.expense(self.g1, '10', node=self.n2.id)
        self.assertEqual(r.status_code, 201)
        o = LocalExpense.objects.get(pk=r.json()['id'])
        self.assertEqual((o.node_id, o.gerant_id), (self.n1.id, self.g1.id))
        u = f'/api/treasury/expenses/{o.id}/'
        self.assertEqual(cl(self.g2).patch(u, {'amount': '1'}, format='json').status_code, 404)
        self.assertEqual(cl(self.g2).delete(u).status_code, 404)
        cl(self.g1).patch(u, {'node': self.n2.id}, format='json')
        o.refresh_from_db(); self.assertEqual(o.node_id, self.n1.id)
        for who in (self.fac, self.liv):
            self.assertEqual(self.expense(who, '5').status_code, 403)
            self.assertEqual(cl(who).get('/api/treasury/expenses/').status_code, 403)
        nodeless = make_user('GERANT', None)
        self.assertEqual(self.expense(nodeless, '5').status_code, 403)
        self.assertEqual(rows(cl(nodeless).get('/api/treasury/expenses/')), [])
        # filtre ?node= force : un gerant reste confine
        self.expense(self.g2, '7')
        got = rows(cl(self.g1).get('/api/treasury/expenses/', {'node': self.n2.id}))
        self.assertEqual({x['node'] for x in got}, set())

    def test_expense_list_params_never_500(self):
        for q in ({'month': 13}, {'month': 'x'}, {'year': 99999}, {'year': 'x'}, {'category': 'abc'},
                  {'date': 'garbage'}, {'node': 'abc'}, {'category': 10 ** 30}):
            with self.subTest(q=q):
                for u in (self.g1, self.dirn):
                    self.assertLess(cl(u).get('/api/treasury/expenses/', q).status_code, 500, (q, u.role))

    def test_BUG_813_expense_future_date_refused(self):
        """BUG-813 (a) : `LocalExpense.date` n'est validee par aucune regle (contrairement a la
        cloture, BUG-086) : une date future est acceptee."""
        from datetime import timedelta
        self.assertEqual(self.expense(self.g1, '10', date=today() + timedelta(days=30)).status_code, 400)

    def test_BUG_813_expense_on_confirmed_closure_day_refused(self):
        """BUG-813 (b) : depense creee, puis supprimee, sur un jour dont la cloture est CONFIRMEE :
        acceptee sans mise a jour de la cloture (`total_expenses`/net perimes ; au versement le
        recalcul modifie silencieusement net et ecart deja confirmes par le comptable)."""
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{c['id']}/validate/", {}, format='json')
        late = self.expense(self.g1, '4000')
        self.assertIn(late.status_code, (400, 403), 'depense sur jour confirme acceptee')

    # -- epargne journaliere ---------------------------------------------
    def sav(self, user, **kw):
        body = {'date': str(today()), 'daily_revenue': '100000', 'flour_sacks': '2'}
        body.update(kw)
        return cl(user).post('/api/treasury/savings/', body, format='json')

    def test_savings_amount_rate_and_upsert(self):
        r = self.sav(self.g1, savings_rate='0.1580', daily_revenue='123456.78')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['savings_amount']), (Dc('123456.78') * Dc('0.1580')).quantize(Dc('0.01')))
        self.sav(self.g1, daily_revenue='1000')
        self.assertEqual(DailySavings.objects.filter(node=self.n1).count(), 1)
        self.sav(self.g1, node=self.n2.id)
        self.assertFalse(DailySavings.objects.filter(node=self.n2).exists())

    def test_savings_bad_values_400(self):
        for kw in ({'daily_revenue': '-1'}, {'daily_revenue': '10.005'}, {'daily_revenue': '1e20'},
                   {'daily_revenue': 'abc'}, {'daily_revenue': None}, {'savings_rate': '1.5'},
                   {'savings_rate': '-0.1'}, {'savings_rate': '0.12345'}, {'flour_sacks': '10000'},
                   {'flour_sacks': '-1'}, {'date': 'abc'}, {'date': None}, {'node': 'abc'}, {'node': 0}):
            with self.subTest(kw=kw):
                self.assertEqual(self.sav(self.g1, **kw).status_code, 400, kw)

    def test_BUG_814_savings_rate_zero_is_honoured(self):
        """BUG-814 : `savings_rate = ... or Config.savings_rate` : un taux explicite 0 est falsy et
        remplace silencieusement par le taux de configuration (15,8 %) -> epargne non nulle."""
        r = self.sav(self.g1, savings_rate='0', daily_revenue='100000')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['savings_amount']), Dc('0'))

    def test_BUG_815_savings_put_to_existing_date_is_400_not_500(self):
        """BUG-815 : PUT/PATCH de `date` vers un jour deja saisi (unique node+date, validateur
        retire par `validators = []`) -> IntegrityError -> 500."""
        from datetime import timedelta
        self.sav(self.g1, date=str(today() - timedelta(days=1)))
        r2 = self.sav(self.g1)
        r = cl(self.g1).patch(f"/api/treasury/savings/{r2.json()['id']}/",
                              {'date': str(today() - timedelta(days=1))}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)

    def test_savings_roles_and_scope(self):
        o = self.sav(self.g1).json()
        for who in (self.fac, self.liv):
            self.assertEqual(cl(who).get('/api/treasury/savings/').status_code, 403)
            self.assertEqual(self.sav(who).status_code, 403)
        self.assertEqual(cl(self.g2).patch(f"/api/treasury/savings/{o['id']}/", {'daily_revenue': '1'}, format='json').status_code, 404)
        self.assertEqual(rows(cl(self.g2).get('/api/treasury/savings/', {'node': self.n1.id})), [])
        for q in ({'month': 0}, {'month': 13}, {'year': 1}, {'year': 'x'}):
            self.assertEqual(cl(self.g1).get('/api/treasury/savings/monthly_total/', q).status_code, 400)
            self.assertEqual(cl(self.g1).get('/api/treasury/savings/', q).status_code, 400)


# =====================================================================
# Bons de decaissement + livre de caisse
# =====================================================================
class LivreDeCaisse(Base):
    def seed(self, amount, node=None, d=None):
        node = node or self.n1
        return append_cashbook_entry(node=node, date=d or today(), piece_number=f'VC-{node.code}-{CashbookEntry.objects.count()}',
                                     imputation='7000', label='seed', entry_amount=Dc(amount), node_origin=node.code)

    def voucher(self, user, **bills):
        b = {k: 0 for k in BILLS}; b.update(bills)
        return cl(user).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'Achat', **b}, format='json')

    def test_balance_progressive_entry_exit_across_nodes_and_voucher(self):
        self.seed('100000', self.n1); self.seed('50000.50', self.n2)
        r = self.voucher(self.dirn, bills_20000=2, bills_500=1)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()['piece_number'].startswith('BV-'))
        bal = [e.running_balance for e in CashbookEntry.chain_queryset()]
        self.assertEqual(bal, [Dc('100000'), Dc('150000.50'), Dc('109500.50')])
        self.assertTrue(self.chain_ok())
        # plus que le solde -> refuse, sans residu
        n = DisbursementVoucher.objects.count()
        self.assertEqual(self.voucher(self.dirn, bills_20000=100000).status_code, 400)
        self.assertEqual(self.voucher(self.dirn).status_code, 400)  # 0 billet
        self.assertEqual(DisbursementVoucher.objects.count(), n)
        self.assertEqual(CashbookEntry.objects.count(), 3)

    def test_voucher_bad_bills_and_roles(self):
        self.seed('100000')
        for bad in (-1, 1.5, 'abc', None, 100001, True):
            self.assertEqual(self.voucher(self.dirn, bills_50=bad).status_code, 400, bad)
        for who in (self.g1, self.fac, self.liv):
            self.assertEqual(self.voucher(who, bills_50=1).status_code, 403)
            self.assertEqual(cl(who).get('/api/treasury/vouchers/').status_code, 403)
            self.assertEqual(cl(who).get('/api/treasury/cashbook/').status_code, 403)
            self.assertEqual(cl(who).get('/api/treasury/direction-cash-counts/').status_code, 403)
        self.assertEqual(cl().get('/api/treasury/cashbook/').status_code, 401)

    def test_BUG_816_voucher_edit_or_delete_must_not_break_ledger(self):
        """BUG-816 : `DisbursementVoucherViewSet` est un ModelViewSet : un siege peut DELETE un bon
        (`CashbookEntry.source_bordereau` = SET_NULL, champ COUVERT par le hash -> chaine rompue)
        ou PATCH ses billets/date (le montant `physical_cash_total` n'est pas recalcule : bon et
        ecriture divergent). Attendu : 405/403 (ajout seul, comme le journal et le livre)."""
        self.seed('100000')
        v = self.voucher(self.dirn, bills_20000=1).json()
        u = f"/api/treasury/vouchers/{v['id']}/"
        r1 = cl(self.dirn).patch(u, {'bills_20000': 4}, format='json')
        r2 = cl(self.dirn).delete(u)
        self.assertIn(r1.status_code, (403, 405), r1.status_code)
        self.assertIn(r2.status_code, (403, 405), r2.status_code)
        self.assertTrue(self.chain_ok())

    def test_cashbook_is_read_only_for_everyone(self):
        e = self.seed('1000')
        for who in (self.adm, self.dirn, self.compt):
            c = cl(who)
            self.assertEqual(c.post('/api/treasury/cashbook/', {'piece_number': 'X'}, format='json').status_code, 405)
            for m in ('put', 'patch', 'delete'):
                self.assertEqual(getattr(c, m)(f'/api/treasury/cashbook/{e.id}/', {'label': 'x'}, format='json').status_code, 405)
            for a in ('integrity_check', 'period_summary'):
                self.assertEqual(c.post(f'/api/treasury/cashbook/{a}/', {}, format='json').status_code, 405)
            for m in ('put', 'patch', 'delete'):
                self.assertEqual(getattr(c, m)(f'/api/treasury/direction-cash-counts/{e.id}/', {}, format='json').status_code, 405)
        self.assertEqual(CashbookEntry.objects.get(pk=e.pk).label, 'seed')

    def test_hash_covers_node_imputation_closure_and_every_accounting_field(self):
        c = CashClosure.objects.create(node=self.n1, date=today(), node_origin='C1')
        c2 = CashClosure.objects.create(node=self.n2, date=today(), node_origin='C2')
        v = DisbursementVoucher.objects.create(date=today(), motif='m')
        self.seed('1000', self.n1)
        e = append_cashbook_entry(node=self.n1, date=today(), piece_number='VC-C1-X', imputation='7000',
                                  label='v', entry_amount=Dc('500'), source_closure=c, node_origin='C1')
        self.assertTrue(self.chain_ok())
        base = CashbookEntry.objects.filter(pk=e.pk)
        changes = {'node_id': self.n2.id, 'imputation': '6000', 'source_closure_id': c2.id,
                   'source_bordereau_id': v.id, 'piece_number': 'VC-C1-Y', 'label': 'x', 'entry_amount': Dc('501'),
                   'exit_amount': Dc('1'), 'running_balance': Dc('1'), 'is_correction': True,
                   'date': today().replace(day=1) if today().day != 1 else today().replace(day=2)}
        orig = {k: getattr(CashbookEntry.objects.get(pk=e.pk), k) for k in changes}
        for k, val in changes.items():
            with self.subTest(field=k):
                base.update(**{k: val})
                body = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()
                self.assertFalse(body['chain_valid'], f'alteration de {k} non detectee')
                snap = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
                self.assertLess(snap.status_code, 500)
                base.update(**{k: orig[k]})
                CashbookEntry.objects.filter(pk=e.pk).update(is_tampered=False)
                self.assertTrue(self.chain_ok(), f'restauration de {k}')

    def test_append_retries_on_stale_parent_and_sequence_stays_linear(self):
        from treasury import views
        first = self.seed('1000')
        real = views._get_last_balance
        calls = {'n': 0}

        def stale():
            calls['n'] += 1
            if calls['n'] == 1:  # deux ecritures concurrentes liraient le meme parent
                return Dc('0'), views.GENESIS_HASH
            return real()
        with mock.patch.object(views, '_get_last_balance', side_effect=stale):
            e = self.seed('500')
        self.assertGreaterEqual(calls['n'], 2)
        self.assertEqual(e.running_balance, Dc('1500'))
        self.assertEqual(e.previous_hash, first.block_hash)
        seq = list(CashbookEntry.chain_queryset().values_list('chain_seq', flat=True))
        self.assertEqual(seq, sorted(set(seq)))
        self.assertTrue(self.chain_ok())
        with self.assertRaises(IntegrityError):  # un doublon de rang ou de parent est impossible en base
            CashbookEntry.objects.create(node=self.n1, date=today(), piece_number='D', label='d',
                                         previous_hash=first.block_hash, chain_seq=99)

    def test_versement_double_non_validated_rejected_and_negative_net(self):
        c = self.close(self.g1, {'bills_50': 1}).json()
        u = f"/api/treasury/closures/{c['id']}/"
        self.assertEqual(cl(self.compt).post(u + 'push_to_cashbook/', {}, format='json').status_code, 400)
        self.assertEqual(cl(self.g1).post(u + 'push_to_cashbook/', {}, format='json').status_code, 403)
        # depenses > ventes : net negatif -> sortie
        self.expense(self.g2, '3000')
        c2 = self.close(self.g2).json()
        self.seed('10000', self.n1)
        r = self.versement(c2['id'])
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((Dc(d['entry_amount']), Dc(d['exit_amount']), d['piece_number']),
                         (Dc('0'), Dc('3000'), f"VC-C2-{today():%Y%m%d}"))
        self.assertEqual(cl(self.compt).post(u.replace(c['id'], c2['id']) + 'push_to_cashbook/', {}, format='json').status_code, 400)
        self.assertEqual(CashbookEntry.objects.filter(source_closure_id=c2['id']).count(), 1)
        self.assertTrue(self.chain_ok())

    def test_period_filters_and_params_never_500(self):
        self.seed('100', d=today())
        for q in ({'node': 'abc'}, {'is_tampered': 'maybe'}, {'date': 'x'}, {'date_from': ''}, {'date_to': ''}):
            with self.subTest(q=q):
                self.assertLess(cl(self.dirn).get('/api/treasury/cashbook/', q).status_code, 500, q)

    def test_BUG_818_date_period_params_are_400_not_500(self):
        """BUG-818 : `date_from`/`date_to` illisibles (« garbage », 2026-02-30, 99999-01-01) ->
        500 sur `cashbook/`, `cashbook/period_summary/`, `vouchers/final_report/` ; et
        `journal/suggested_ca/?node=abc` (siege) -> 500 (filtre brut sans validation)."""
        self.seed('100', d=today())
        bad = []
        for u in ('/api/treasury/cashbook/', '/api/treasury/cashbook/period_summary/', '/api/treasury/vouchers/final_report/'):
            for q in ({'date_from': 'garbage'}, {'date_to': '99999-01-01'}, {'date_from': '2026-02-30'}):
                if cl(self.dirn).get(u, q).status_code >= 500:
                    bad.append((u, q))
        if cl(self.dirn).get('/api/treasury/journal/suggested_ca/', {'node': 'abc', 'date': str(today())}).status_code >= 500:
            bad.append(('suggested_ca', 'node=abc'))
        self.assertEqual(bad, [])

    def test_direction_cash_count_gap_and_duplicates(self):
        self.seed('10000')
        body = {'date': str(today()), **{b: 0 for b in BILLS}, 'bills_5000': 2}
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['cash_gap']), Dc('0'))
        self.assertEqual(cl(self.dirn).post('/api/treasury/direction-cash-counts/', body, format='json').status_code, 400)
        self.assertEqual(cl(self.dirn).post('/api/treasury/direction-cash-counts/', {**body, 'date': 'x'}, format='json').status_code, 400)


# =====================================================================
# Journal de caisse par boulangerie
# =====================================================================
class Journal(Base):
    def post(self, user, imput='CA', **kw):
        body = {'date': str(today()), 'imput': imput, 'label': 'x', 'entry_amount': '0', 'exit_amount': '0'}
        body.update(kw)
        return cl(user).post('/api/treasury/journal/', body, format='json')

    def test_progressive_balance_and_read_only_methods(self):
        r1 = self.post(self.g1, entry_amount='1000.50'); r2 = self.post(self.g1, imput='APPRO', exit_amount='300.25')
        self.assertEqual(Dc(r2.json()['running_balance']), Dc('700.25'))
        for m in ('put', 'patch', 'delete'):
            self.assertEqual(getattr(cl(self.g1), m)(f"/api/treasury/journal/{r1.json()['id']}/", {}, format='json').status_code, 405)
        self.assertEqual(rows(cl(self.g2).get('/api/treasury/journal/', {'node': self.n1.id})), [])

    def test_bad_values_400(self):
        for kw in ({'entry_amount': '-1'}, {'exit_amount': '-1'}, {'entry_amount': '1.005'}, {'entry_amount': '1e20'},
                   {'entry_amount': 'abc'}, {'imput': 'ZZZ'}, {'imput': None}, {'date': 'abc'}, {'node': 'abc'},
                   {'label': 'x' * 201}, {'entry_amount': '10000000000000'}):
            with self.subTest(kw=kw):
                self.assertEqual(self.post(self.g1, **kw).status_code, 400, kw)

    def test_BUG_817_journal_future_date_refused(self):
        """BUG-817 (a) : `JournalEntryViewSet.perform_create` ne valide pas la date : une date future
        est acceptee (et un jour passe l'est sans `allow_backdated_sales`)."""
        from datetime import timedelta
        self.assertEqual(self.post(self.g1, entry_amount='5', date=str(today() + timedelta(days=40))).status_code, 400)

    def test_BUG_817_journal_backdated_entry_balance_follows_date_order(self):
        """BUG-817 (b) : le solde est calcule a partir de l'ecriture la plus RECENTE du mois : une
        saisie datee du 5 apres une du 10 recoit « solde du 10 + montant » alors que le journal est
        trie par date (solde progressif faux, 1100 au lieu de 100)."""
        r10 = self.post(self.g1, entry_amount='1000', date='2026-03-10')
        r05 = self.post(self.g1, entry_amount='100', date='2026-03-05')
        self.assertEqual((r10.status_code, r05.status_code), (201, 201))
        self.assertEqual(Dc(r05.json()['running_balance']), Dc('100'))

    def test_month_carry_over(self):
        JournalEntry.objects.create(node=self.n1, date=today().replace(day=1) - timezone.timedelta(days=1), imput='CA',
                                    entry_amount=Dc('500'), running_balance=Dc('500'))
        r = self.post(self.g1, entry_amount='100')
        self.assertEqual((Dc(r.json()['month_carried']), Dc(r.json()['running_balance'])), (Dc('500'), Dc('600')))

    def test_suggested_ca_dates_and_scope(self):
        for d in ('abc', '2026-02-30', ''):
            self.assertEqual(cl(self.g1).get('/api/treasury/journal/suggested_ca/', {'date': d}).status_code, 400)
        self.report(self.n2, 'A', '777')
        c = CashClosure.objects.create(node=self.n2, date=today(), total_entries=Dc('777'), node_origin='C2')
        r = cl(self.g1).get('/api/treasury/journal/suggested_ca/', {'node': self.n2.id, 'date': str(today())})
        self.assertFalse(r.json()['available'])  # node force ignore : cloture de n2 invisible a g1
        for who in (self.fac, self.liv):
            self.assertEqual(cl(who).get('/api/treasury/journal/').status_code, 403)
            self.assertEqual(self.post(who, entry_amount='1').status_code, 403)

    def test_journal_param_matrix_never_500_for_gerant(self):
        for q in ({'month': 'x'}, {'month': 99}, {'year': 1}, {'date': 'x'}, {'imput': 'ZZ'}):
            with self.subTest(q=q):
                self.assertLess(cl(self.g1).get('/api/treasury/journal/', q).status_code, 500)
                self.assertLess(cl(self.g1).get('/api/treasury/journal/monthly_report/', q).status_code, 500)


# =====================================================================
# Journee complete : 2 equipes, cloture, versement, chaine
# =====================================================================
class JourneeComplete(Base):
    def test_two_teams_expenses_billetage_versement_chain(self):
        self.report(self.n1, 'A', '120000', credit='30000'); self.report(self.n1, 'B', '80000.50', credit='1000')
        self.expense(self.g1, '15000'); self.expense(self.g1, '2500.50')
        net = Dc('200000.50') - Dc('17500.50')
        self.assertEqual(net, Dc('182500.00'))
        c = self.close(self.g1, {'bills_20000': 9, 'bills_1000': 2, 'bills_500': 1}).json()
        self.assertEqual((Dc(c['net_cash']), Dc(c['cash_gap'])), (net, Dc('0')))
        r = self.versement(c['id'])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['running_balance']), net)
        self.assertTrue(self.chain_ok())
        snap = cl(self.dirn).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertLess(snap.status_code, 300, snap.content)
