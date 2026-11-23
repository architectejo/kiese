"""Cycle 13 (testeur-tresorerie, 2026-11-23-c13) : verification independante de BUG-959 a 963 (d34),
decision sur la question ouverte de BUG-960 (cloture poussee deja validee), puis balayage des
chemins de push qui contournent les validations REST de la tresorerie (rapport apres cloture,
modification d'un rapport valide, rejeu apres confirmation, JournalEntry / DailySavings, rapport
d'un autre noeud) et journee complete sur 2 postes via sync_now.
Donnees fictives. Code applicatif non modifie.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.testing import make_bread_price, make_user
from production.models import BreadTransfer, BreadTransferLine
from sync.management.commands.sync_now import apply_push_response, build_outbound_payload
from sync.models import NodeAuthToken
from treasury.models import (CashbookEntry, CashClosure, DailySavings, DisbursementVoucher,
                             FacturierReport, JournalEntry, LocalExpense)
from treasury.tests.test_cycle1_tresorerie_c import BILLS, cl, today
from treasury.tests.test_verif_tresorerie_c10_v9 import CLO, RAP, VOU, Base10
from treasury.tests.test_verif_tresorerie_c8_v7 import PUSH, push_client

EXP = 'treasury.LocalExpense'


class Base13(Base10):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _, cls.raw2 = NodeAuthToken.issue_for_node(cls.n2)
        cls.bp = make_bread_price()

    def exp_rec(self, node='C1', **kw):
        d = {'id': str(uuid.uuid4()), 'node': node, 'description': 'Eau', 'amount': '1000',
             'category': self.cat.pk, 'date': str(today())}
        d.update(kw)
        return d

    def results_of(self, r):
        return [x for rows in r.data['results'].values() for x in rows]

    def status_of(self, r):
        rows = self.results_of(r)
        return rows[0]['status'] if rows else None

    def cycle(self, raw, code):
        payload = build_outbound_payload(code)
        node_pk = {'C1': self.n1.pk, 'C2': self.n2.pk}[code]
        CashClosure.objects.filter(node_id=node_pk).delete()
        FacturierReport.objects.filter(node_id=node_pk).delete()
        LocalExpense.objects.filter(node_id=node_pk).delete()
        r = push_client(raw).post(PUSH, payload, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        apply_push_response(r.data)
        return payload, r.data['results']

    def refused(self, results):
        return [(lbl, x) for lbl, rows in results.items() for x in rows if x['status'] != 'ACCEPTED']

    def valider(self, closure_id, user=None):
        return cl(user or self.compt).post(f'/api/treasury/closures/{closure_id}/validate/', {}, format='json')

    def verser(self, closure_id):
        return cl(self.compt).post(f'/api/treasury/closures/{closure_id}/push_to_cashbook/', {}, format='json')

    def transfer(self, sent, received, status='DISPUTED', frm=None, to=None):
        t = BreadTransfer.objects.create(from_node=frm or self.n2, to_node=to or self.n1,
                                         transfer_status=status, node_origin=(frm or self.n2).code)
        BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=sent,
                                         quantity_received=received)
        return t


# ======================================================================================
# Verification independante de BUG-959 a 963
# ======================================================================================
class V959_963(Base13):
    def test_959_facturier_exporte_et_stocke(self):
        fa, fb = make_user('FACTURIER', self.n1, 'A'), make_user('FACTURIER', self.n1, 'A')
        for f, cash in ((fa, '7000'), (fb, '3000')):
            FacturierReport.objects.create(node=self.n1, facturier=f, team='A', date=today(),
                                           total_cash_sales=Dc(cash), total_credit_sales=Dc('0'),
                                           theoretical_cash=Dc(cash), node_origin='C1')
        payload = build_outbound_payload('C1')
        self.assertEqual({x['facturier'] for x in payload['records'][RAP]}, {str(fa.pk), str(fb.pk)})
        _, res = self.cycle(self.raw1, 'C1')
        self.assertEqual(self.refused(res), [])
        got = {r.facturier_id: r.total_cash_sales for r in FacturierReport.objects.filter(node=self.n1)}
        self.assertEqual(got, {fa.pk: Dc('7000'), fb.pk: Dc('3000')})

    def test_959_poste_ancien_sans_cle_facturier_inchange(self):
        r1 = self.rep()
        r1.pop('facturier', None)
        self.push(self.raw1, RAP, r1)
        self.assertTrue(self.has(FacturierReport, r1))
        r2 = self.rep()  # meme equipe/jour sans facturier : doublon (BUG-911)
        r2.pop('facturier', None)
        self.push(self.raw1, RAP, r2)
        self.assertFalse(self.has(FacturierReport, r2))

    def test_959_facturier_supprime_ou_forge_refuse(self):
        rec = self.rep(facturier=str(uuid.uuid4()))
        self.push(self.raw1, RAP, rec)
        self.assertFalse(self.has(FacturierReport, rec))

    def test_960_creation_validee_avec_ecart_refusee(self):
        self.transfer(100, 98)
        rec = self.clo(is_validated=True)
        r = self.push(self.raw1, CLO, rec)
        self.assertEqual(self.status_of(r), 'REJECTED')
        self.assertFalse(self.has(CashClosure, rec))
        self.assertFalse(CashbookEntry.objects.exists())

    def test_960_ecart_direct_sans_protocole_et_statut_pending_cancelled(self):
        self.transfer(100, 98, status='CONFIRMED')           # ecart saisi directement
        self.assertEqual(self.status_of(self.push(self.raw1, CLO, self.clo(is_validated=True))), 'REJECTED')
        BreadTransfer.objects.all().delete()
        self.transfer(100, 98, status='CANCELLED')           # annule : sans effet
        self.transfer(100, None, status='PENDING')           # en attente : sans effet
        self.transfer(100, 98, status='DISPUTED', frm=self.n1, to=self.n2)  # sortant : sans effet
        rec = self.clo(is_validated=True)
        self.assertEqual(self.status_of(self.push(self.raw1, CLO, rec)), 'ACCEPTED')

    def test_960_cloture_validee_puis_ecart_puis_rejeu_pas_de_versement(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(self.valider(d['id']).status_code, 200)
        self.transfer(100, 98)
        rec = self.clo(id=d['id'], is_validated=True)
        self.push(self.raw1, CLO, rec)
        self.assertFalse(CashbookEntry.objects.exists())
        self.assertEqual(self.verser(d['id']).status_code, 400)  # REST : meme verdict
        BreadTransfer.objects.all().delete()
        self.push(self.raw1, CLO, rec)
        self.assertEqual(CashbookEntry.objects.count(), 1)       # ecart resolu : versement
        self.push(self.raw1, CLO, rec)
        self.assertEqual(CashbookEntry.objects.count(), 1)       # rejeu : pas de double versement

    def test_961_depense_jour_confirme_refusee_rejeu_idempotent(self):
        self.report(self.n1, 'A', '10000')
        exp_before = self.exp_rec(amount='2000')
        self.push(self.raw1, EXP, exp_before)
        d = self.close(self.g1, {'bills_5000': 1, 'bills_1000': 3}).json()
        self.assertEqual(self.valider(d['id']).status_code, 200)
        exp_after = self.exp_rec(amount='500')
        r = self.push(self.raw1, EXP, exp_after)
        self.assertEqual(self.status_of(r), 'REJECTED')
        self.assertFalse(self.has(LocalExpense, exp_after))
        # rejeu de la depense deja acceptee apres confirmation : ACCEPTED, pas de doublon
        r = self.push(self.raw1, EXP, exp_before)
        self.assertEqual(self.status_of(r), 'ACCEPTED')
        self.assertEqual(LocalExpense.objects.filter(pk=exp_before['id']).count(), 1)
        # autre jour : accepte
        other = self.exp_rec(date=str(today() - timedelta(days=2)))
        self.assertEqual(self.status_of(self.push(self.raw1, EXP, other)), 'ACCEPTED')
        # autre boulangerie, meme jour : accepte
        o2 = self.exp_rec(node='C2')
        self.assertEqual(self.status_of(self.push(self.raw2, EXP, o2)), 'ACCEPTED')

    def test_961_depense_avant_confirmation_recalcule_le_net(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.push(self.raw1, EXP, self.exp_rec(amount='1000'))
        self.assertEqual(self.valider(d['id']).status_code, 200)
        c = CashClosure.objects.get(pk=d['id'])
        self.assertEqual((c.total_expenses, c.net_cash, c.cash_gap), (Dc('1000'), Dc('9000'), Dc('1000')))

    def test_962_dates_futures_invalides_motifs_precis(self):
        for dte, mot in ((str(today() + timedelta(days=3)), 'futur'), ('2026-02-30', 'invalide'),
                         ('２０２６-01-01', 'invalide'), (20261101, 'invalide')):
            rec = self.exp_rec(date=dte)
            r = self.push(self.raw1, EXP, rec)
            rows = self.results_of(r)
            self.assertEqual(rows[0]['status'], 'REJECTED', dte)
            self.assertNotIn('non traité', rows[0].get('reason', rows[0].get('detail', '')).lower(), dte)
        self.assertEqual(self.status_of(self.push(self.raw1, EXP, self.exp_rec(date=str(today())))), 'ACCEPTED')
        self.assertEqual(self.status_of(self.push(
            self.raw1, EXP, self.exp_rec(date=str(today() - timedelta(days=30))))), 'ACCEPTED')

    def test_963_roles_sans_rattachement_acceptes_facturier_autre_noeud_refuse(self):
        for role in ('COMPTABLE', 'DIRECTION', 'ADMIN'):
            rec = self.rep(facturier=str(make_user(role).pk), team='A', date=str(today() - timedelta(days=5)))
            self.push(self.raw1, RAP, rec)
            self.assertTrue(self.has(FacturierReport, rec), role)
            FacturierReport.objects.all().delete()
        other = make_user('FACTURIER', self.n2, 'A')
        rec = self.rep(facturier=str(other.pk))
        self.push(self.raw1, RAP, rec)
        self.assertFalse(self.has(FacturierReport, rec))
        g_other = make_user('GERANT', self.n2)
        rec = self.rep(facturier=str(g_other.pk))
        self.push(self.raw1, RAP, rec)
        self.assertFalse(self.has(FacturierReport, rec))


# ======================================================================================
# Question ouverte BUG-960 : cloture poussee deja validee (decision : DEFAUT, BUG-971)
# ======================================================================================
class V960_Decision(Base13):
    def test_BUG_969_cloture_poussee_validee_ne_s_auto_confirme_pas(self):
        """remarque.md l.156 : « seul le comptable direction generale peut confirmer ou infirmer ».
        REST : validate/reject/push_to_cashbook = IsHeadquarters (BUG-200). Un jeton de boulangerie
        qui pousse is_validated=True cree une cloture CONFIRMEE puis le cloud la verse lui-meme au
        livre direction : aucun controle du comptable."""
        rec = self.clo(is_validated=True)
        self.push(self.raw1, CLO, rec)
        c = CashClosure.objects.filter(pk=rec['id']).first()
        self.assertTrue(c is None or not c.is_validated, "cloture confirmee sans comptable")
        self.assertFalse(CashbookEntry.objects.exists(), "livre direction credite sans comptable")

    def test_montants_declares_recalcules_au_versement_meme_si_poussee_validee(self):
        """Non-regression (BUG-839) : le versement relit les ventes et depenses du cloud ; un total
        declare de 5 000 000 FC n'est jamais inscrit tel quel (le defaut est le statut, BUG-971)."""
        self.report(self.n1, 'A', '10000')
        rec = self.clo(is_validated=True, total_entries='5000000', total_expenses='0', bills_10000=500)
        self.push(self.raw1, CLO, rec)
        self.assertEqual(CashbookEntry.objects.count(), 0)  # BUG-971 : adapte, poussee non confirmee
        self.assertEqual(self.valider(rec['id']).status_code, 200)
        self.assertEqual(self.verser(rec['id']).status_code, 201)
        self.assertEqual(sum(e.entry_amount for e in CashbookEntry.objects.all()), Dc('10000'))

    def test_poussee_non_validee_puis_confirmation_rest_recalcule(self):
        """Voie nominale : le poste pousse non confirmee, le comptable confirme, totaux relus."""
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='9999', total_expenses='0', bills_10000=1)
        self.push(self.raw1, CLO, rec)
        self.assertEqual(self.valider(rec['id']).status_code, 200)
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual(c.total_entries, Dc('10000.00'))
        self.assertEqual(self.verser(rec['id']).status_code, 201)
        self.assertEqual(CashbookEntry.objects.get().entry_amount, Dc('10000.00'))

    def test_validation_par_gerant_ou_facturier_rest_refusee(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        for u in (self.g1, self.fac, self.liv):
            self.assertEqual(self.valider(d['id'], u).status_code, 403)

    def test_rejeu_cloture_existante_ne_change_ni_montants_ni_statut(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(self.valider(d['id']).status_code, 200)
        before = CashClosure.objects.values().get(pk=d['id'])
        self.push(self.raw1, CLO, self.clo(id=d['id'], total_entries='1', bills_50=9, is_validated=False))
        self.assertEqual(CashClosure.objects.values().get(pk=d['id']), before)

    def test_double_cloture_meme_jour_autre_id_refusee_sans_500(self):
        a, b = self.clo(), self.clo()
        self.assertEqual(self.status_of(self.push(self.raw1, CLO, a)), 'ACCEPTED')
        r = self.push(self.raw1, CLO, b)
        self.assertEqual(self.status_of(r), 'REJECTED')
        self.assertEqual(CashClosure.objects.filter(node=self.n1, date=today()).count(), 1)


# ======================================================================================
# Autres chemins de push
# ======================================================================================
class V13_Chemins(Base13):
    def test_rapport_apres_cloture_non_confirmee_accepte_et_recalcule_a_la_confirmation(self):
        rec0 = self.rep(total_cash_sales='4000', theoretical_cash='4000', team='A')
        self.push(self.raw1, RAP, rec0)
        c = self.clo(total_entries='4000', bills_10000=0, bills_1000=4)
        self.push(self.raw1, CLO, c)
        late = self.rep(total_cash_sales='6000', theoretical_cash='6000', team='B')
        self.assertEqual(self.status_of(self.push(self.raw1, RAP, late)), 'ACCEPTED')
        self.assertEqual(self.valider(c['id']).status_code, 200)
        self.assertEqual(CashClosure.objects.get(pk=c['id']).total_entries, Dc('10000.00'))

    def test_rapport_apres_cloture_confirmee_refuse(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(self.valider(d['id']).status_code, 200)
        late = self.rep(team='B')
        self.assertEqual(self.status_of(self.push(self.raw1, RAP, late)), 'REJECTED')
        self.assertFalse(self.has(FacturierReport, late))

    def test_modification_rapport_valide_ou_non_par_rejeu_ignoree(self):
        rec = self.rep(total_cash_sales='10000', theoretical_cash='10000')
        self.push(self.raw1, RAP, rec)
        FacturierReport.objects.filter(pk=rec['id']).update(is_validated=True)
        self.push(self.raw1, RAP, dict(rec, total_cash_sales='1', theoretical_cash='1', is_validated=False))
        r = FacturierReport.objects.get(pk=rec['id'])
        self.assertEqual((r.total_cash_sales, r.theoretical_cash, r.is_validated), (Dc('10000.00'), Dc('10000.00'), True))

    def test_rapport_existant_non_modifiable_par_montants_rejeu(self):
        rec = self.rep(total_cash_sales='10000', theoretical_cash='10000')
        self.push(self.raw1, RAP, rec)
        self.push(self.raw1, RAP, dict(rec, total_cash_sales='999999', theoretical_cash='999999'))
        self.assertEqual(FacturierReport.objects.get(pk=rec['id']).total_cash_sales, Dc('10000.00'))

    def test_rapport_d_un_autre_noeud_non_validable_par_jeton_etranger(self):
        """Un jeton C2 ne doit pas pouvoir confirmer un rapport de C1 (id connu)."""
        rec = self.rep()
        self.push(self.raw1, RAP, rec)
        self.push(self.raw2, RAP, {'id': rec['id'], 'is_validated': True})
        self.assertFalse(FacturierReport.objects.get(pk=rec['id']).is_validated)

    def test_rapport_d_un_autre_noeud_non_valide_par_node_forge(self):
        rec = self.rep()
        self.push(self.raw1, RAP, rec)
        self.push(self.raw2, RAP, {'id': rec['id'], 'node': 'C1', 'is_validated': True})
        self.assertFalse(FacturierReport.objects.get(pk=rec['id']).is_validated)

    def test_depense_existante_non_modifiable_par_jeton_etranger(self):
        e = self.exp_rec(amount='1000')
        self.push(self.raw1, EXP, e)
        self.push(self.raw2, EXP, dict(e, amount='1', node='C2'))
        self.assertEqual(LocalExpense.objects.get(pk=e['id']).amount, Dc('1000.00'))
        self.assertEqual(LocalExpense.objects.get(pk=e['id']).node, self.n1)

    def test_journal_et_epargne_non_acceptes_par_le_sync(self):
        before = (JournalEntry.objects.count(), DailySavings.objects.count(), CashbookEntry.objects.count())
        for raw in (self.raw1, self.raws):
            for label, rec in (('treasury.JournalEntry', {'id': str(uuid.uuid4()), 'node': 'C1', 'date': str(today()),
                                                          'amount': '1000', 'label': 'x'}),
                               ('treasury.DailySavings', {'id': str(uuid.uuid4()), 'node': 'C1',
                                                          'date': str(today()), 'amount': '1000'}),
                               ('treasury.CashbookEntry', {'id': str(uuid.uuid4()), 'entry_amount': '1000000'})):
                r = push_client(raw).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {label: [rec]}}, format='json')
                self.assertLess(r.status_code, 500, r.content)
                for x in self.results_of(r):
                    self.assertNotEqual(x['status'], 'ACCEPTED', (label, x))
        self.assertEqual((JournalEntry.objects.count(), DailySavings.objects.count(),
                          CashbookEntry.objects.count()), before)

    def test_bordereau_jeton_boulangerie_refuse_siege_accepte_rejeu_sans_double_debit(self):
        self.fund_livre('20000')
        v = self.vou(bills_1000=5)
        self.assertEqual(self.status_of(self.push(self.raw1, VOU, v)), 'REJECTED')
        self.assertFalse(self.has(DisbursementVoucher, v))
        self.assertEqual(self.status_of(self.push(self.raws, VOU, v)), 'ACCEPTED')
        self.push(self.raws, VOU, v)
        self.push(self.raws, VOU, dict(v, bills_1000=50))
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(last.running_balance, Dc('15000'))
        self.assertEqual(CashbookEntry.objects.count(), 2)
        self.assertTrue(self.chain_ok())

    def test_bordereau_solde_insuffisant_sans_orphelin(self):
        self.fund_livre('10000')
        v = self.vou(bills_10000=3)
        self.push(self.raws, VOU, v)
        self.assertFalse(self.has(DisbursementVoucher, v))
        self.assertEqual(CashbookEntry.objects.count(), 1)


# ======================================================================================
# Journee complete sur 2 postes via sync_now
# ======================================================================================
class V13_Journee(Base13):
    def _poste(self, node, code, specs, depense):
        for team, cash, credit in specs:
            f = make_user('FACTURIER', node, team)
            FacturierReport.objects.create(node=node, facturier=f, team=team, date=today(),
                                           total_cash_sales=Dc(cash), total_credit_sales=Dc(credit),
                                           theoretical_cash=Dc(cash), node_origin=code)
        LocalExpense.objects.create(node=node, description='Eau', amount=Dc(depense), category=self.cat,
                                    date=today(), node_origin=code)

    def _closure(self, node, code, entries, expenses, **bills):
        c = CashClosure(node=node, date=today(), node_origin=code, total_entries=Dc(entries),
                        total_expenses=Dc(expenses), **bills)
        c.compute_physical_cash()
        c.save()

    def test_journee_complete_2_postes(self):
        # C1 : deux facturiers de l'equipe A (7000 + 3000) et un de l'equipe B (5000) ; depense 2000
        self._poste(self.n1, 'C1', (('A', '7000', '1000'), ('A', '3000', '0'), ('B', '5000', '500')), '2000')
        # C2 : un facturier A (20000) ; depense 5000
        self._poste(self.n2, 'C2', (('A', '20000', '1000'),), '5000')
        self._closure(self.n1, 'C1', '15000', '2000', bills_10000=1, bills_1000=3)
        self._closure(self.n2, 'C2', '20000', '5000', bills_10000=1, bills_5000=1)

        p1, res1 = self.cycle(self.raw1, 'C1')
        p2, res2 = self.cycle(self.raw2, 'C2')
        self.assertEqual(self.refused(res1), [], res1)
        self.assertEqual(self.refused(res2), [], res2)
        self.assertEqual(FacturierReport.objects.filter(node=self.n1, date=today()).count(), 3)
        self.assertEqual(sum(r.total_cash_sales for r in FacturierReport.objects.filter(node=self.n1)), Dc('15000'))
        for code in ('C1', 'C2'):
            left = {k: v for k, v in build_outbound_payload(code)['records'].items() if v}
            self.assertEqual(left, {}, code)
        c1 = CashClosure.objects.get(node=self.n1, date=today())
        c2 = CashClosure.objects.get(node=self.n2, date=today())
        self.assertFalse(c1.is_validated or c2.is_validated)
        self.assertEqual((c1.net_cash, c1.physical_cash_total, c1.cash_gap), (Dc('13000'), Dc('13000'), Dc('0')))

        # depense poussee AVANT confirmation (poste hors ligne) : relue a la confirmation
        before = self.exp_rec(amount='1000')
        self.assertEqual(self.status_of(self.push(self.raw1, EXP, before)), 'ACCEPTED')

        # C2 : transfert entrant en ecart -> confirmation REST bloquee, puis resolu
        t = self.transfer(100, 98, status='DISPUTED', frm=self.n1, to=self.n2)
        self.assertEqual(self.valider(c2.pk).status_code, 400)
        self.assertEqual(self.verser(c2.pk).status_code, 400)
        self.assertFalse(CashbookEntry.objects.exists())
        t.lines.update(quantity_received=100)
        BreadTransfer.objects.filter(pk=t.pk).update(transfer_status='CONFIRMED')

        r1, r2 = self.valider(c1.pk), self.valider(c2.pk)
        self.assertEqual((r1.status_code, r2.status_code), (200, 200), (r1.content, r2.content))
        c1.refresh_from_db()
        self.assertEqual((c1.total_expenses, c1.net_cash, c1.cash_gap), (Dc('3000'), Dc('12000'), Dc('1000')))

        # depense APRES confirmation : refusee ; rapport tardif : refuse ; rejeu : sans effet
        after = self.exp_rec(amount='700')
        self.assertEqual(self.status_of(self.push(self.raw1, EXP, after)), 'REJECTED')
        late = self.rep(team='B', facturier=str(make_user('FACTURIER', self.n1, 'B').pk))
        self.assertEqual(self.status_of(self.push(self.raw1, RAP, late)), 'REJECTED')
        self.assertEqual(self.status_of(self.push(self.raw1, EXP, before)), 'ACCEPTED')
        self.assertEqual(LocalExpense.objects.filter(node=self.n1).count(), 2)

        # versements (REST comptable) ; le cloud rejoue le lot : pas de double versement
        for c in (c1, c2):
            self.assertEqual(self.verser(c.pk).status_code, 201)
        for code, raw in (('C1', self.raw1), ('C2', self.raw2)):
            self.push(raw, CLO, self.clo(id=str(CashClosure.objects.get(node__code=code, date=today()).pk),
                                         node=code, is_validated=True))
        self.assertEqual(CashbookEntry.objects.count(), 2)
        e = {x.source_closure.node.code: x for x in CashbookEntry.objects.select_related('source_closure__node')}
        self.assertEqual(e['C1'].piece_number, f"VC-C1-{today():%Y%m%d}")
        self.assertEqual((e['C1'].entry_amount, e['C2'].entry_amount), (Dc('12000'), Dc('15000')))

        # bordereau du siege (jeton siege) puis chaine
        v = self.vou(bills_1000=5)
        self.assertEqual(self.status_of(self.push(self.raws, VOU, v)), 'ACCEPTED')
        self.push(self.raws, VOU, v)
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(last.running_balance, Dc('22000'))
        self.assertTrue(self.chain_ok())
        rc = cl(self.adm).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(rc.status_code, 200, rc.content)
        self.assertIn('intact', rc.content.decode().lower())
        # alteration directe en base detectee par les deux endpoints
        CashbookEntry.objects.filter(pk=last.pk).update(entry_amount=Dc('1'))
        self.assertFalse(self.chain_ok())
