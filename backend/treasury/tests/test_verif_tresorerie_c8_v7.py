"""Cycle 8 (testeur-tresorerie, 2026-11-23-c8) : verification independante de BUG-897 (chiffres
non ASCII sur les montants de la tresorerie via AsciiDigitsMixin '__numeric__'), BUG-898 et
BUG-899 (push sync LocalExpense), absence de refus a tort (billetage, decimaux), flux complet
cloture -> versement -> chaine, bons de decaissement, epargne, journal, etats financiers N/N-1,
effet des transferts (BUG-675) sur la caisse. Donnees fictives. Code applicatif non modifie.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.utils import timezone
from rest_framework.test import APIClient

from core.models import ExpenseCategory
from finance.models import FinancialYear
from sync.models import NodeAuthToken
from treasury.models import (
    CashbookEntry, CashClosure, DailySavings, DirectionCashCount, DisbursementVoucher,
    JournalEntry, LocalExpense,
)
from treasury.tests.test_cycle1_tresorerie_c import BILLS, VALUES, Base, cl, rows, today

ARAB = '٣'
FULL = '１２'
PUSH = '/api/sync/push/'


def push_client(raw):
    c = APIClient()
    c.raise_request_exception = False
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return c


# ---------------------------------------------------------------------------
# BUG-897 : REST, chiffres non ASCII refuses / valeurs legitimes acceptees
# ---------------------------------------------------------------------------
class V897(Base):
    def exp(self, amount, user=None, **kw):
        return cl(user or self.g1).post('/api/treasury/expenses/', {
            'description': 'Eau accentuee é', 'amount': amount, 'category': self.cat.id,
            'date': str(today()), **kw}, format='json')

    def test_depense_chiffres_non_ascii_refuses(self):
        for v in (ARAB, FULL, '１２.５'):
            r = self.exp(v)
            self.assertEqual(r.status_code, 400, (v, r.content))
        self.assertFalse(LocalExpense.objects.exists())

    def test_depense_valeurs_legitimes_acceptees(self):
        for v, exp in (('12500.50', '12500.50'), (500, '500'), ('0.01', '0.01'), (1500.5, '1500.5'),
                       ('99999999999.99', '99999999999.99')):
            r = self.exp(v)
            self.assertEqual(r.status_code, 201, (v, r.content))
            self.assertEqual(LocalExpense.objects.latest('created_at').amount, Dc(exp))

    def test_depense_patch_non_ascii_refuse_et_montant_inchange(self):
        e = self.exp('500').json()
        r = cl(self.g1).patch(f"/api/treasury/expenses/{e['id']}/", {'amount': FULL}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(LocalExpense.objects.get(pk=e['id']).amount, Dc('500'))
        r = cl(self.g1).patch(f"/api/treasury/expenses/{e['id']}/", {'amount': '750.25'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_depense_multipart_acceptee(self):
        r = cl(self.g1).post('/api/treasury/expenses/', {
            'description': 'x', 'amount': '300', 'category': self.cat.id, 'date': str(today())})
        self.assertEqual(r.status_code, 201, r.content)

    def test_billetage_non_ascii_refuse_sur_cloture(self):
        self.report(self.n1, 'A', '1000')
        for v in (ARAB, FULL):
            r = self.close(self.g1, {'bills_1000': v})
            self.assertEqual(r.status_code, 400, (v, r.content))
        self.assertFalse(CashClosure.objects.exists())

    def test_billetage_chaines_ascii_et_entiers_acceptes(self):
        self.report(self.n1, 'A', '1000')
        r = self.close(self.g1, {'bills_1000': '1'})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['physical_cash_total']), Dc('1000'))

    def test_billetage_8_coupures_total_exact_et_ecart_signe(self):
        self.report(self.n1, 'A', '10000')
        b = dict(zip(BILLS, (0, 0, 0, 0, 0, 0, 0, 1)))
        for gap_bills, gap in (({'bills_10000': 1}, '0'), ({'bills_10000': 1, 'bills_50': 3}, '150'),
                               ({'bills_5000': 1, 'bills_1000': 4}, '-1000')):
            CashClosure.objects.all().delete()
            body = {k: 0 for k in BILLS}
            body.update(gap_bills)
            r = self.close(self.g1, body)
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(Dc(r.json()['cash_gap']), Dc(gap))
        del b

    def test_cloture_patch_billetage_non_ascii(self):
        self.report(self.n1, 'A', '1000')
        c = self.close(self.g1, {'bills_1000': 1}).json()
        r = cl(self.g1).patch(f"/api/treasury/closures/{c['id']}/", {'bills_500': ARAB}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashClosure.objects.get(pk=c['id']).bills_500, 0)

    def test_journal_non_ascii_refuse_legitime_accepte(self):
        for f in ('entry_amount', 'exit_amount'):
            for v in (ARAB, FULL):
                r = cl(self.g1).post('/api/treasury/journal/', {
                    'date': str(today()), 'imput': 'CA', 'label': 'x', f: v}, format='json')
                self.assertEqual(r.status_code, 400, (f, v, r.content))
        self.assertFalse(JournalEntry.objects.exists())
        r = cl(self.g1).post('/api/treasury/journal/', {
            'date': str(today()), 'imput': 'CA', 'label': 'Vente é', 'entry_amount': '10000.50'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_epargne_non_ascii_refuse_legitime_acceptee(self):
        for f in ('daily_revenue', 'flour_sacks', 'savings_rate'):
            r = cl(self.g1).post('/api/treasury/savings/', {
                'date': str(today()), 'daily_revenue': '1000', 'flour_sacks': '2', f: ARAB}, format='json')
            self.assertEqual(r.status_code, 400, (f, r.content))
        self.assertFalse(DailySavings.objects.exists())
        r = cl(self.g1).post('/api/treasury/savings/', {
            'date': str(today()), 'daily_revenue': '100000', 'flour_sacks': '2.5', 'savings_rate': '0.05'},
            format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Dc(r.json()['savings_amount']), Dc('5000.00'))

    def test_bordereau_non_ascii_refuse(self):
        for v in (ARAB, FULL):
            r = cl(self.compt).post('/api/treasury/vouchers/', {
                'date': str(today()), 'motif': 'm', 'bills_1000': v}, format='json')
            self.assertEqual(r.status_code, 400, (v, r.content))
        self.assertFalse(DisbursementVoucher.objects.exists())

    def test_comptage_direction_non_ascii_refuse(self):
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/', {
            'date': str(today()), 'bills_1000': ARAB}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(DirectionCashCount.objects.exists())

    def test_rapport_facturier_post_valeur_non_ascii_sur_champ_ecrit(self):
        """Rapport : seuls node/date sont inscriptibles ; un total forge (meme non ASCII) est ignore ou refuse."""
        r = cl(self.g1).post('/api/treasury/reports/', {
            'date': str(today()), 'total_cash_sales': FULL}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        from treasury.models import FacturierReport
        for fr in FacturierReport.objects.all():
            self.assertEqual(fr.total_cash_sales, 0)

    def test_note_pk_pleine_largeur_accepte_sans_ticket(self):
        """OBSERVATION (pas de ticket) : une cle etrangere (categorie) en chiffres pleine largeur est resolue
        comme l'identifiant ASCII equivalent (int() Python). Aucun montant n'est concerne ; l'effet est
        identique a la saisie de l'id normal. Documente."""
        full_cat = ''.join(chr(0xFF10 + int(ch)) for ch in str(self.cat.id))
        r = self.exp('100', category=full_cat)
        self.assertEqual(r.status_code, 201, r.content[:200])
        self.assertEqual(LocalExpense.objects.get().category_id, self.cat.id)


# ---------------------------------------------------------------------------
# BUG-898 / 899 : push LocalExpense
# ---------------------------------------------------------------------------
class V898(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _, cls.raw1 = NodeAuthToken.issue_for_node(cls.n1)
        _, cls.raws = NodeAuthToken.issue_for_node(cls.siege)
        cls.cat_off = ExpenseCategory.objects.get_or_create(
            code='C8OFF', defaults={'label': 'Off c8', 'is_active': False})[0]
        cls.cat_dir = ExpenseCategory.objects.get_or_create(
            code='C8DIR', defaults={'label': 'Dir c8', 'scope': 'DIRECTION'})[0]
        cls.cat_bak = ExpenseCategory.objects.get_or_create(
            code='C8BAK', defaults={'label': 'Bak c8', 'scope': 'BAKERY'})[0]

    def p(self, raw, amount='500', cat=None, node='C1', **kw):
        rid = str(uuid.uuid4())
        rec = {'id': rid, 'node': node, 'description': 'push c8 é', 'amount': amount,
               'category': (cat or self.cat).pk, 'date': str(today()), **kw}
        r = push_client(raw).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {'treasury.LocalExpense': [rec]}},
                                  format='json')
        self.assertLess(r.status_code, 500, (amount, r.content))
        return rid, r

    def stored(self, rid):
        return LocalExpense.objects.filter(pk=rid).first()

    def test_montants_legitimes_acceptes(self):
        for v, exp in (('500', '500'), (500, '500'), ('12500.50', '12500.50'), (1500.5, '1500.5'),
                       ('0.01', '0.01'), (' 700 ', '700'), ('1e3', '1000'), ('99999999999.99', '99999999999.99')):
            rid, _ = self.p(self.raw1, v)
            e = self.stored(rid)
            self.assertIsNotNone(e, v)
            self.assertEqual(e.amount, Dc(exp), v)

    def test_montants_invalides_refuses(self):
        for v in ('-500', -1, '0', 0, None, 'abc', '', ARAB, FULL, 'NaN', 'Infinity', '-Infinity', True, False,
                  [5], {'a': 1}, '1E12', '1e30', '--5'):
            rid, _ = self.p(self.raw1, v)
            self.assertIsNone(self.stored(rid), repr(v))

    def test_montant_absent_refuse(self):
        rid = str(uuid.uuid4())
        rec = {'id': rid, 'node': 'C1', 'description': 'x', 'category': self.cat.pk, 'date': str(today())}
        push_client(self.raw1).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {'treasury.LocalExpense': [rec]}},
                                    format='json')
        self.assertIsNone(self.stored(rid))

    def test_BUG_900_sous_centime_ne_cree_pas_de_depense_a_zero(self):
        """BUG-900 : REST refuse '0.001' (2 decimales max) ; le push l'accepte et stocke 0.00 FC. '0.001' > 0 mais est arrondi a 0.00 en base (DecimalField 2 decimales)."""
        rid, _ = self.p(self.raw1, '0.001')
        e = self.stored(rid)
        self.assertTrue(e is None or e.amount > 0, e and str(e.amount))

    def test_amount_trop_de_decimales_est_normalise(self):
        rid, _ = self.p(self.raw1, '10.555')
        e = self.stored(rid)
        self.assertTrue(e is None or e.amount in (Dc('10.55'), Dc('10.56')), e and str(e.amount))

    def test_categorie_direction_refusee_pour_boulangerie_acceptee_pour_siege(self):
        rid, _ = self.p(self.raw1, cat=self.cat_dir)
        self.assertIsNone(self.stored(rid))
        rid, r = self.p(self.raws, cat=self.cat_dir, node='SIEGE')
        self.assertIsNotNone(self.stored(rid), r.content)

    def test_autres_categories_acceptees(self):
        for cat in (self.cat, self.cat_bak, self.cat_off):
            rid, _ = self.p(self.raw1, cat=cat)
            self.assertIsNotNone(self.stored(rid), cat.code)

    def test_idempotence_et_autre_boulangerie(self):
        rid, _ = self.p(self.raw1)
        rec = {'id': rid, 'node': 'C1', 'description': 'x', 'amount': '9', 'category': self.cat.pk, 'date': str(today())}
        push_client(self.raw1).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {'treasury.LocalExpense': [rec]}},
                                    format='json')
        self.assertEqual(self.stored(rid).amount, Dc('500'))
        rid2, _ = self.p(self.raw1, node='C2')
        e = self.stored(rid2)
        self.assertTrue(e is None or e.node_id == self.n1.pk)

    def test_depense_poussee_impacte_la_cloture(self):
        self.report(self.n1, 'A', '10000')
        self.p(self.raw1, '2500.50')
        r = self.close(self.g1, {'bills_5000': 1, 'bills_1000': 2, 'bills_500': 1}).json()
        self.assertEqual(Dc(r['total_expenses']), Dc('2500.50'))
        self.assertEqual(Dc(r['net_cash']), Dc('7499.50'))

    def test_rejet_massif_dans_un_lot_ne_bloque_pas_les_valides(self):
        recs = []
        for v in ('100', '-5', '200', 'x', '300'):
            recs.append({'id': str(uuid.uuid4()), 'node': 'C1', 'description': 'x', 'amount': v,
                         'category': self.cat.pk, 'date': str(today())})
        r = push_client(self.raw1).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {'treasury.LocalExpense': recs}},
                                        format='json')
        self.assertLess(r.status_code, 500)
        self.assertEqual(LocalExpense.objects.filter(node=self.n1).count(), 3)


# ---------------------------------------------------------------------------
# Flux complet, bons de decaissement, journal, epargne
# ---------------------------------------------------------------------------
class Flux(Base):
    def test_journee_complete_cloture_versement_chaine_finance(self):
        for team in ('A', 'B'):
            self.report(self.n1, team, '25000.50', credit='4000')
        self.assertEqual(self.expense(self.g1, '3000.50').status_code, 201)
        net = Dc('50001.00') - Dc('3000.50')
        # billetage exact : 46 000.50 -> impossible avec billets ; ecart de -0.50 attendu
        r = self.close(self.g1, {'bills_20000': 2, 'bills_5000': 1, 'bills_1000': 1})
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(Dc(d['net_cash']), net)
        self.assertEqual(Dc(d['physical_cash_total']), Dc('46000'))
        self.assertEqual(Dc(d['cash_gap']), Dc('46000') - net)
        res = self.versement(d['id'])
        self.assertEqual(res.status_code, 201, res.content)
        e = CashbookEntry.objects.get(source_closure_id=d['id'])
        self.assertEqual(e.piece_number, f"VC-C1-{today().strftime('%Y%m%d')}")
        self.assertEqual(e.entry_amount, net)  # le livre recoit la caisse nette theorique
        self.assertEqual(e.running_balance, net)
        self.assertTrue(self.chain_ok())
        # bordereau : sortie, solde, chaine
        v = cl(self.compt).post('/api/treasury/vouchers/', {
            'date': str(today()), 'motif': 'Achat é', 'beneficiary': 'Fournisseur',
            'bills_20000': 1, 'bills_5000': '2', 'bills_100': 5}, format='json')
        self.assertEqual(v.status_code, 201, v.content)
        self.assertEqual(Dc(v.json()['physical_cash_total']), Dc('30500'))
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(last.running_balance, net - Dc('30500'))
        self.assertEqual(last.exit_amount, Dc('30500'))
        self.assertTrue(self.chain_ok())
        # finance : flux de tresorerie de l'exercice
        fy = FinancialYear.objects.create(year=today().year)
        cf = cl(self.dirn).get(f'/api/finance/years/{fy.pk}/cashflow/').json()
        self.assertEqual(Dc(str(cf['total_entries'])), net)
        self.assertEqual(Dc(str(cf['total_exits'])), Dc('30500'))
        self.assertEqual(Dc(str(cf['closing_balance'])), net - Dc('30500'))
        inc = cl(self.dirn).get(f'/api/finance/years/{fy.pk}/income_statement/').json()
        self.assertEqual(Dc(str(inc['operational_expenses'])), Dc('3000.50'))

    def test_double_versement_refuse_chaine_intacte(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertIn(self.versement(d['id']).status_code, (200, 201))
        r = cl(self.compt).post(f"/api/treasury/closures/{d['id']}/push_to_cashbook/", {}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(CashbookEntry.objects.filter(source_closure_id=d['id']).count(), 1)
        self.assertTrue(self.chain_ok())

    def test_bordereau_superieur_au_solde_refuse_et_aucun_bon_cree(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.versement(d['id'])
        r = cl(self.compt).post('/api/treasury/vouchers/', {
            'date': str(today()), 'motif': 'trop', 'bills_20000': 1}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertFalse(DisbursementVoucher.objects.exists())
        self.assertEqual(CashbookEntry.objects.count(), 1)
        # solde exactement egal : accepte
        r = cl(self.compt).post('/api/treasury/vouchers/', {
            'date': str(today()), 'motif': 'tout', 'bills_10000': 1}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first().running_balance, 0)

    def test_bordereau_zero_billet_et_mutations_refuses(self):
        r = cl(self.compt).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.report(self.n1, 'A', '10000')
        self.versement(self.close(self.g1, {'bills_10000': 1}).json()['id'])
        v = cl(self.compt).post('/api/treasury/vouchers/', {
            'date': str(today()), 'motif': 'm', 'bills_1000': 2}, format='json').json()
        for m in ('put', 'patch', 'delete'):
            r = getattr(cl(self.adm), m)(f"/api/treasury/vouchers/{v['id']}/", {'motif': 'z'}, format='json')
            self.assertEqual(r.status_code, 405, (m, r.status_code))
        for u in (self.g1, self.fac):
            self.assertEqual(cl(u).post('/api/treasury/vouchers/', {
                'date': str(today()), 'motif': 'm', 'bills_50': 1}, format='json').status_code, 403)

    def test_comptage_direction_ecart_sur_solde_du_livre(self):
        self.report(self.n1, 'A', '10000')
        self.versement(self.close(self.g1, {'bills_10000': 1}).json()['id'])
        r = cl(self.dirn).post('/api/treasury/direction-cash-counts/', {
            'date': str(today()), 'bills_5000': 1, 'bills_1000': '4', 'bills_50': 2}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual(Dc(d['physical_cash_total']), Dc('9100'))
        self.assertEqual(Dc(d['theoretical_balance']), Dc('10000'))
        self.assertEqual(Dc(d['cash_gap']), Dc('-900'))
        self.assertEqual(CashbookEntry.objects.count(), 1)  # sans effet sur le livre
        self.assertTrue(self.chain_ok())

    def test_journal_solde_progressif_immuable_et_sans_effet_livre(self):
        c = cl(self.g1)
        a = c.post('/api/treasury/journal/', {'date': str(today()), 'imput': 'CA', 'label': 'a',
                                              'entry_amount': '10000.50'}, format='json')
        b = c.post('/api/treasury/journal/', {'date': str(today()), 'imput': 'EAU', 'label': 'b',
                                              'exit_amount': '2500.25'}, format='json')
        self.assertEqual((a.status_code, b.status_code), (201, 201), (a.content, b.content))
        self.assertEqual(Dc(b.json()['running_balance']), Dc('7500.25'))
        for m in ('put', 'patch', 'delete'):
            r = getattr(c, m)(f"/api/treasury/journal/{b.json()['id']}/", {'label': 'z'}, format='json')
            self.assertEqual(r.status_code, 405, (m, r.status_code))
        self.assertEqual(CashbookEntry.objects.count(), 0)
        neg = c.post('/api/treasury/journal/', {'date': str(today()), 'imput': 'EAU', 'label': 'n',
                                                'exit_amount': '-5'}, format='json')
        self.assertEqual(neg.status_code, 400)

    def test_epargne_upsert_taux_zero_et_sans_effet_sur_le_livre(self):
        c = cl(self.g1)
        r = c.post('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '33333.33',
                                              'flour_sacks': '1', 'savings_rate': '0.05'}, format='json')
        self.assertEqual(Dc(r.json()['savings_amount']), Dc('1666.67'))
        r = c.post('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '33333.33',
                                              'flour_sacks': '1', 'savings_rate': '0'}, format='json')
        self.assertLess(r.status_code, 300, r.content)
        self.assertEqual(DailySavings.objects.filter(node=self.n1).count(), 1)
        self.assertEqual(DailySavings.objects.get().savings_amount, Dc('0'))
        self.assertEqual(CashbookEntry.objects.count(), 0)
        self.assertEqual(c.post('/api/treasury/savings/', {'date': str(today()), 'daily_revenue': '1',
                                                           'savings_rate': '1.5'}, format='json').status_code, 400)

    def test_journal_des_ecarts_cash_gap_non_modifiable(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_5000': 1}).json()
        for body in ({'cash_gap': '0'}, {'net_cash': '5000'}, {'physical_cash_total': '10000'},
                     {'total_entries': '5000'}):
            cl(self.g1).patch(f"/api/treasury/closures/{d['id']}/", body, format='json')
        c = CashClosure.objects.get(pk=d['id'])
        self.assertEqual((c.cash_gap, c.net_cash, c.physical_cash_total, c.total_entries),
                         (Dc('-5000'), Dc('10000'), Dc('5000'), Dc('10000')))
        cl(self.compt).post(f"/api/treasury/closures/{d['id']}/validate/", {}, format='json')
        r = cl(self.g1).delete(f"/api/treasury/closures/{d['id']}/")
        self.assertIn(r.status_code, (400, 403, 405), r.status_code)
        self.assertTrue(CashClosure.objects.filter(pk=d['id']).exists())


# ---------------------------------------------------------------------------
# Finance N / N-1 et BUG-675 (transferts) sur la caisse
# ---------------------------------------------------------------------------
class FinanceNN1(Base):
    def test_depenses_et_flux_separes_par_exercice(self):
        y = today().year
        for yr, amt in ((y - 1, '1000'), (y, '2500.50')):
            LocalExpense.objects.create(node=self.n1, description='x', amount=Dc(amt), category=self.cat,
                                        date=today().replace(year=yr, month=1, day=15), node_origin='C1')
        CashbookEntry.objects.create  # noqa (existence)
        fy = FinancialYear.objects.create(year=y)
        r = cl(self.dirn).get(f'/api/finance/years/{fy.pk}/comparative/')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(Dc(str(d['income_statement']['operational_expenses'])), Dc('2500.50'))
        self.assertEqual(Dc(str(d['income_statement_prev']['operational_expenses'])), Dc('1000'))
        self.assertEqual(Dc(str(d['income_statement']['net_result'])), Dc('-2500.50'))
        self.assertEqual(Dc(str(d['income_statement_prev']['net_result'])), Dc('-1000'))

    def test_acces_finance_refuse_hors_siege(self):
        fy = FinancialYear.objects.create(year=today().year)
        for u in (self.g1, self.fac, self.liv):
            self.assertEqual(cl(u).get(f'/api/finance/years/{fy.pk}/comparative/').status_code, 403)

    def test_transfert_inter_boulangeries_sans_effet_sur_la_caisse(self):
        """BUG-675 : le signe de l'appro recu concerne le total du jour de production, pas la caisse."""
        from production.models import BreadTransfer
        from core.testing import make_bread_price
        bp = make_bread_price()
        self.report(self.n1, 'A', '10000'); self.report(self.n2, 'A', '10000')
        before = (self.close(self.g1, {'bills_10000': 1}).json(), self.close(self.g2, {'bills_10000': 1}).json())
        CashClosure.objects.all().delete()
        BreadTransfer.objects.create(from_node=self.n1, to_node=self.n2, bread_price=bp, quantity_sent=100,
                                     quantity_received=100, transfer_status='CONFIRMED', node_origin='C1')
        after = (self.close(self.g1, {'bills_10000': 1}).json(), self.close(self.g2, {'bills_10000': 1}).json())
        for b, a in zip(before, after):
            self.assertEqual((b['net_cash'], b['cash_gap']), (a['net_cash'], a['cash_gap']))
