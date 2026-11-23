"""Cycle 9 (testeur-tresorerie, 2026-11-23-c9) : verification de BUG-900 (push LocalExpense,
sous-centime) et exploration du push sync des autres modeles de tresorerie (FacturierReport,
CashClosure, DisbursementVoucher ; JournalEntry et DailySavings non supportes) face aux regles
REST : montants > 0, 2 decimales, ASCII, bornes, equipes A/B, perimetre du noeud, etats valides
non modifiables, idempotence du rejeu, coherence de la chaine de hash. Donnees fictives.
Code applicatif non modifie.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc

from sync.models import NodeAuthToken
from treasury.models import (
    CashbookEntry, CashClosure, DisbursementVoucher, FacturierReport, LocalExpense,
)
from treasury.tests.test_cycle1_tresorerie_c import BILLS, Base, cl, today
from treasury.tests.test_verif_tresorerie_c8_v7 import ARAB, FULL, PUSH, push_client

ZERO = {b: 0 for b in BILLS}


class PushBase(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _, cls.raw1 = NodeAuthToken.issue_for_node(cls.n1)
        _, cls.raws = NodeAuthToken.issue_for_node(cls.siege)

    def push(self, raw, label, rec):
        r = push_client(raw).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {label: [rec]}}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        return r

    def rep(self, **kw):
        d = {'id': str(uuid.uuid4()), 'node': 'C1', 'team': 'A', 'date': str(today()),
             'total_cash_sales': '10000', 'total_credit_sales': '2000', 'theoretical_cash': '10000'}
        d.update(kw)
        return d

    def clo(self, **kw):
        d = {'id': str(uuid.uuid4()), 'node': 'C1', 'date': str(today()),
             'total_entries': '10000', 'total_expenses': '0', **ZERO, 'bills_10000': 1}
        d.update(kw)
        return d

    def vou(self, **kw):
        d = {'id': str(uuid.uuid4()), 'date': str(today()), 'motif': 'Achat', **ZERO, 'bills_1000': 2}
        d.update(kw)
        return d

    def fund_livre(self, amount='10000'):
        self.report(self.n1, 'A', amount)
        d = self.close(self.g1, {'bills_10000': int(Dc(amount) // 10000)}).json()
        self.assertIn(self.versement(d['id']).status_code, (200, 201))


class V900(PushBase):
    def p(self, amount):
        rid = str(uuid.uuid4())
        self.push(self.raw1, 'treasury.LocalExpense', {
            'id': rid, 'node': 'C1', 'description': 'x', 'amount': amount,
            'category': self.cat.pk, 'date': str(today())})
        return LocalExpense.objects.filter(pk=rid).first()

    def test_sous_centime_refuse(self):
        for v in ('0.001', '0.004', '0.005', '10.555', 0.001, '1.001', '5.0000001'):
            self.assertIsNone(self.p(v), v)

    def test_deux_decimales_et_zero_final_acceptes(self):
        for v, exp in (('0.01', '0.01'), ('12.50', '12.50'), ('12.500', '12.5'), ('12.5000', '12.5'),
                       ('1E2', '100'), (1500.5, '1500.5'), ('99999999999.99', '99999999999.99'),
                       (' 7.25 ', '7.25')):
            e = self.p(v)
            self.assertIsNotNone(e, v)
            self.assertEqual(e.amount, Dc(exp), v)

    def test_aucune_depense_a_zero_en_base(self):
        for v in ('0.001', '0.0049', '0', '-0.01'):
            self.p(v)
        self.assertFalse(LocalExpense.objects.filter(amount__lte=0).exists())


class PushRapport(PushBase):
    def stored(self, rec):
        return FacturierReport.objects.filter(pk=rec['id']).first()

    def test_rapport_valide_accepte_et_rejeu_idempotent(self):
        rec = self.rep()
        self.push(self.raw1, 'treasury.FacturierReport', rec)
        self.push(self.raw1, 'treasury.FacturierReport', {**rec, 'total_cash_sales': '99'})
        self.assertEqual(FacturierReport.objects.count(), 1)
        self.assertEqual(self.stored(rec).total_cash_sales, Dc('10000'))

    def test_rapport_valide_non_modifiable_par_rejeu(self):
        rec = self.rep(is_validated=True)
        self.push(self.raw1, 'treasury.FacturierReport', rec)
        self.push(self.raw1, 'treasury.FacturierReport', {**rec, 'is_validated': False, 'total_cash_sales': '1'})
        r = self.stored(rec)
        self.assertTrue(r.is_validated)
        self.assertEqual(r.total_cash_sales, Dc('10000'))

    def test_rapport_autre_boulangerie_refuse(self):
        rec = self.rep(node='C2')
        self.push(self.raw1, 'treasury.FacturierReport', rec)
        self.assertIsNone(self.stored(rec))

    def test_rapport_montants_non_ascii_refuses(self):
        bad = []
        for f in ('total_cash_sales', 'total_credit_sales', 'theoretical_cash', 'sacks_value_gap'):
            for v in (ARAB, FULL):
                rec = self.rep(**{f: v})
                self.push(self.raw1, 'treasury.FacturierReport', rec)
                if self.stored(rec) is not None:
                    bad.append((f, v))
        self.assertEqual(bad, [])

    def test_rapport_montants_negatifs_refuses(self):
        bad = []
        for f in ('total_cash_sales', 'total_credit_sales', 'theoretical_cash'):
            rec = self.rep(**{f: '-5000'})
            self.push(self.raw1, 'treasury.FacturierReport', rec)
            if self.stored(rec) is not None:
                bad.append(f)
        self.assertEqual(bad, [])

    def test_rapport_equipe_hors_A_B_refusee(self):
        bad = []
        for team in ('Z', 'J', 'N', '1'):
            rec = self.rep(team=team)
            self.push(self.raw1, 'treasury.FacturierReport', rec)
            if self.stored(rec) is not None:
                bad.append(team)
        self.assertEqual(bad, [])

    def test_rapport_sous_centime_refuse_ou_normalise(self):
        rec = self.rep(total_cash_sales='10.004')
        self.push(self.raw1, 'treasury.FacturierReport', rec)
        r = self.stored(rec)
        self.assertTrue(r is None or r.total_cash_sales == Dc('10.00'))

    def test_rapport_doublon_meme_vacation_autre_id(self):
        a, b = self.rep(), self.rep()
        self.push(self.raw1, 'treasury.FacturierReport', a)
        self.push(self.raw1, 'treasury.FacturierReport', b)
        n = FacturierReport.objects.filter(node=self.n1, team='A', date=today()).count()
        self.assertEqual(n, 1, "deux rapports pour la meme vacation (node, equipe, date)")

    def test_rapport_date_future_refusee(self):
        rec = self.rep(date=str(today() + timedelta(days=30)))
        self.push(self.raw1, 'treasury.FacturierReport', rec)
        self.assertIsNone(self.stored(rec))

    def test_rapport_date_invalide_pas_de_500(self):
        for d in ('2026-13-45', 'abc', 12345, ARAB):
            rec = self.rep(date=d)
            r = self.push(self.raw1, 'treasury.FacturierReport', rec)
            self.assertIsNone(self.stored(rec), d)
            self.assertEqual(r.status_code, 200, r.content)


class PushCloture(PushBase):
    def stored(self, rec):
        return CashClosure.objects.filter(pk=rec['id']).first()

    def test_cloture_valide_acceptee_totaux_recalcules(self):
        rec = self.clo(bills_10000=1, bills_500=3)
        self.push(self.raw1, 'treasury.CashClosure', rec)
        c = self.stored(rec)
        self.assertEqual(c.physical_cash_total, Dc('11500'))
        self.assertEqual(c.cash_gap, Dc('11500') - c.net_cash)

    def test_cloture_rejeu_idempotent_et_valide_non_modifiable(self):
        rec = self.clo(is_validated=True)
        self.push(self.raw1, 'treasury.CashClosure', rec)
        self.push(self.raw1, 'treasury.CashClosure', {**rec, 'bills_10000': 9, 'total_entries': '1'})
        c = self.stored(rec)
        self.assertEqual(c.bills_10000, 1)
        # BUG-971 : adapte, la cloture poussee n'est jamais confirmee ni versee par le sync
        self.assertFalse(c.is_validated)
        self.assertEqual(CashbookEntry.objects.filter(source_closure=c).count(), 0)

    def test_cloture_double_meme_jour_autre_id_refusee(self):
        a, b = self.clo(), self.clo()
        self.push(self.raw1, 'treasury.CashClosure', a)
        r = self.push(self.raw1, 'treasury.CashClosure', b)
        self.assertEqual(CashClosure.objects.filter(node=self.n1, date=today()).count(), 1)
        self.assertIsNone(self.stored(b))
        self.assertEqual(r.status_code, 200)

    def test_cloture_negatifs_et_non_ascii_refuses(self):
        bad = []
        for f, v in (('total_entries', '-1'), ('total_expenses', '-1'), ('total_entries', ARAB),
                     ('total_expenses', FULL), ('bills_10000', -1), ('bills_500', ARAB), ('bills_50', FULL),
                     ('bills_100', 1.5), ('bills_100', True)):
            rec = self.clo(**{f: v})
            self.push(self.raw1, 'treasury.CashClosure', rec)
            if self.stored(rec) is not None:
                bad.append((f, v))
            CashClosure.objects.all().delete()
        self.assertEqual(bad, [])

    def test_cloture_date_future_refusee(self):
        rec = self.clo(date=str(today() + timedelta(days=10)))
        self.push(self.raw1, 'treasury.CashClosure', rec)
        self.assertIsNone(self.stored(rec))

    def test_cloture_autre_boulangerie_refusee(self):
        rec = self.clo(node='C2')
        self.push(self.raw1, 'treasury.CashClosure', rec)
        self.assertIsNone(self.stored(rec))
        self.assertFalse(CashClosure.objects.exists())

    def test_cloture_valide_poussee_totaux_incoherents_avec_les_rapports(self):
        """REST : total_entries = somme des rapports du jour ; validation par un comptable. Un noeud
        qui pousse une cloture deja validee avec un total libre credite le livre direction sans controle."""
        self.report(self.n1, 'A', '1000')
        rec = self.clo(is_validated=True, total_entries='5000000', bills_10000=500)
        self.push(self.raw1, 'treasury.CashClosure', rec)
        total = sum((e.entry_amount for e in CashbookEntry.objects.all()), Dc('0'))
        self.assertLessEqual(total, Dc('1000'), f"livre credite de {total} FC pour 1000 FC de rapports")

    def test_cloture_poussee_non_validee_ne_touche_pas_le_livre(self):
        rec = self.clo()
        self.push(self.raw1, 'treasury.CashClosure', rec)
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_cloture_validee_poussee_chaine_valide_et_piece(self):
        rec = self.clo()
        self.push(self.raw1, 'treasury.CashClosure', rec)
        # BUG-971 : adapte, la confirmation vient du comptable (REST), simulee ici
        CashClosure.objects.filter(pk=rec['id']).update(is_validated=True)
        self.push(self.raw1, 'treasury.CashClosure', rec)
        e = CashbookEntry.objects.get()
        self.assertEqual(e.piece_number, f"VC-C1-{today().strftime('%Y%m%d')}")
        self.assertTrue(self.chain_ok())


class PushBordereau(PushBase):
    def stored(self, rec):
        return DisbursementVoucher.objects.filter(pk=rec['id']).first()

    def test_bordereau_boulangerie_refuse(self):
        rec = self.vou()
        self.push(self.raw1, 'treasury.DisbursementVoucher', rec)
        self.assertIsNone(self.stored(rec))

    def test_bordereau_siege_debite_le_livre_et_rejeu_idempotent(self):
        self.fund_livre('10000')
        rec = self.vou(bills_1000=2)
        self.push(self.raws, 'treasury.DisbursementVoucher', rec)
        self.push(self.raws, 'treasury.DisbursementVoucher', {**rec, 'bills_1000': 5})
        self.assertEqual(DisbursementVoucher.objects.count(), 1)
        self.assertEqual(CashbookEntry.objects.filter(source_bordereau_id=rec['id']).count(), 1)
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(last.running_balance, Dc('8000'))
        self.assertTrue(self.chain_ok())

    def test_bordereau_superieur_au_solde_ne_laisse_pas_de_bon_orphelin(self):
        self.fund_livre('10000')
        rec = self.vou(bills_20000=1, bills_1000=0)
        self.push(self.raws, 'treasury.DisbursementVoucher', rec)
        self.assertEqual(CashbookEntry.objects.count(), 1)
        self.assertIsNone(self.stored(rec), "bon cree sans ecriture au livre (REST : aucun bon cree)")

    def test_bordereau_zero_billet_refuse(self):
        rec = self.vou(bills_1000=0)
        self.push(self.raws, 'treasury.DisbursementVoucher', rec)
        self.assertIsNone(self.stored(rec))
        self.assertFalse(CashbookEntry.objects.exists())

    def test_bordereau_negatifs_non_ascii_refuses(self):
        bad = []
        self.fund_livre('10000')
        for f, v in (('bills_1000', -1), ('bills_1000', ARAB), ('bills_500', FULL), ('bills_100', 1.5)):
            rec = self.vou(**{f: v})
            self.push(self.raws, 'treasury.DisbursementVoucher', rec)
            if self.stored(rec) is not None:
                bad.append((f, v))
        self.assertEqual(bad, [])
        self.assertEqual(CashbookEntry.objects.count(), 1)
        self.assertTrue(self.chain_ok())

    def test_bordereau_date_future_refusee(self):
        self.fund_livre('10000')
        rec = self.vou(date=str(today() + timedelta(days=10)))
        self.push(self.raws, 'treasury.DisbursementVoucher', rec)
        self.assertIsNone(self.stored(rec))


class NonSupportes(PushBase):
    def test_journal_et_epargne_rejetes_sans_500(self):
        for label in ('treasury.JournalEntry', 'treasury.DailySavings', 'treasury.CashbookEntry'):
            r = self.push(self.raws, label, {'id': 1, 'amount': '5'})
            self.assertEqual(r.status_code, 200, r.content)
            self.assertIn('REJECTED', r.content.decode(), label)
        self.assertEqual(CashbookEntry.objects.count(), 0)


class ChaineApresPush(PushBase):
    def test_melange_rest_et_push_chaine_valide(self):
        self.fund_livre('20000')
        self.push(self.raw1, 'treasury.CashClosure', self.clo(
            date=str(today() - timedelta(days=1)), is_validated=True, bills_10000=1))
        self.push(self.raws, 'treasury.DisbursementVoucher', self.vou(bills_1000=3))
        r = cl(self.compt).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'm', 'bills_500': 2},
                                format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(self.chain_ok())
        e = list(CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()))
        self.assertEqual(e[0].running_balance, Dc('20000') - 3000 - 1000)
