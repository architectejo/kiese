"""Cycle 12 (testeur-tresorerie, 2026-11-23-c12) : verification independante de BUG-935 / 936
(controle du facturier au push FacturierReport, d30), relecture des tests adaptes, puis balayage de
la partie C avec 2 postes simules via build_outbound_payload / apply_push_response (sync_now) :
rapports, depenses, cloture, versement, chaine, etats financiers N / N-1, plus controles de
BUG-675 (signe des transferts), BUG-677 (scope des categories), BUG-871 (categorie inactive).
Donnees fictives. Code applicatif non modifie.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.models import ExpenseCategory
from core.testing import make_bread_price, make_user
from finance.models import FinancialYear
from production.models import BreadTransfer, BreadTransferLine
from sync.management.commands.sync_now import apply_push_response, build_outbound_payload
from sync.models import NodeAuthToken
from treasury.models import (CashbookEntry, CashClosure, DisbursementVoucher, FacturierReport,
                             LocalExpense)
from treasury.tests.test_cycle1_tresorerie_c import BILLS, cl, today
from treasury.tests.test_verif_tresorerie_c10_v9 import CLO, RAP, Base10
from treasury.tests.test_verif_tresorerie_c8_v7 import PUSH, push_client

EXP = 'treasury.LocalExpense'


class Base12(Base10):
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

    def cycle(self, raw, code, wipe=True):
        """Un cycle sync_now : export du poste, effacement de la copie locale (le poste n'est pas
        dans la base cloud), push, marquage des acceptes."""
        payload = build_outbound_payload(code)
        if wipe:
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

    def valider(self, closure_id):
        return cl(self.compt).post(f'/api/treasury/closures/{closure_id}/validate/', {}, format='json')

    def run_check(self):
        r = cl(self.adm).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()


# ======================================================================================
# Verification independante de BUG-935 / 936
# ======================================================================================
class V935_936(Base12):
    def test_935_roles_admis_du_noeud(self):
        refus = []
        for role in ('FACTURIER', 'GERANT', 'COMPTABLE', 'DIRECTION', 'ADMIN'):
            u = make_user(role, self.n1, 'A')
            rec = self.rep(facturier=str(u.pk), team='A', date=str(today() - timedelta(days=4)))
            self.push(self.raw1, RAP, rec)
            if not self.has(FacturierReport, rec):
                refus.append(role)
            FacturierReport.objects.all().delete()
        self.assertEqual(refus, [])

    def test_935_livreur_actif_ou_inactif_refuse(self):
        for actif in (True, False):
            l = make_user('LIVREUR', self.n1, 'B')
            l.is_active = actif
            l.save()
            rec = self.rep(facturier=str(l.pk), team='B')
            r = self.push(self.raw1, RAP, rec)
            self.assertFalse(self.has(FacturierReport, rec), actif)
            self.assertIn('facturier', r.content.decode().lower())

    def test_936_inactif_meme_noeud_accepte_et_cash_dans_la_cloture(self):
        f = make_user('FACTURIER', self.n1, 'A')
        rec = self.rep(facturier=str(f.pk), total_cash_sales='25000', theoretical_cash='25000')
        f.is_active = False
        f.save()
        self.push(self.raw1, RAP, rec)
        self.assertTrue(self.has(FacturierReport, rec))
        d = self.close(self.g1, {'bills_20000': 1, 'bills_5000': 1}).json()
        self.assertEqual(Dc(d['total_entries']), Dc('25000'))
        self.assertEqual(Dc(d['cash_gap']), Dc('0'))

    def test_936_inactif_autre_noeud_refuse_et_inconnu_refuse(self):
        e = make_user('FACTURIER', self.n2, 'A')
        e.is_active = False
        e.save()
        for val in (e.pk, uuid.uuid4()):
            rec = self.rep(facturier=str(val))
            self.push(self.raw1, RAP, rec)
            self.assertFalse(self.has(FacturierReport, rec))

    def test_936_dedoublonnage_conserve_pour_un_inactif(self):
        f = make_user('FACTURIER', self.n1, 'A')
        f.is_active = False
        f.save()
        a, b = self.rep(facturier=str(f.pk)), self.rep(facturier=str(f.pk))
        self.push(self.raw1, RAP, a)
        self.push(self.raw1, RAP, b)
        self.assertTrue(self.has(FacturierReport, a))
        self.assertFalse(self.has(FacturierReport, b))

    def test_936_reactivation_ou_changement_de_role_apres_acceptation_rejeu_idempotent(self):
        f = make_user('FACTURIER', self.n1, 'A')
        rec = self.rep(facturier=str(f.pk))
        self.push(self.raw1, RAP, rec)
        f.role = 'LIVREUR'
        f.is_active = False
        f.save()
        r = self.push(self.raw1, RAP, rec)
        self.assertNotIn('REJECTED', r.content.decode())
        self.assertEqual(FacturierReport.objects.filter(pk=rec['id']).count(), 1)

    def test_facturier_sans_noeud_supprime_ou_rapport_inconnu_ne_plante_pas(self):
        f = make_user('FACTURIER', None, 'A')
        rec = self.rep(facturier=str(f.pk))
        r = self.push(self.raw1, RAP, rec)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.has(FacturierReport, rec))

    def test_adaptation_c10_livreur_et_gerant_distincts(self):
        """Relecture des tests adaptes : le livreur reste refuse ; le gerant, comptable, direction,
        admin sont acceptes (verrou croise c10/c11)."""
        liv = self.push(self.raw1, RAP, self.rep(facturier=str(self.liv.pk), team='B',
                                                 date=str(today() - timedelta(days=3))))
        self.assertIn('REJECTED', liv.content.decode())
        ok = self.rep(facturier=str(self.g1.pk), team='B', date=str(today() - timedelta(days=3)))
        r = self.push(self.raw1, RAP, ok)
        self.assertNotIn('REJECTED', r.content.decode())

    def test_equipe_du_facturier_non_controlee_decision_937(self):
        """Test supprime (facturier d'une autre equipe refuse) : decision coordinateur = accepte.
        Le verrou subsiste via test_equipe_du_facturier_non_controlee_coherent_avec_REST (c11)."""
        fb = make_user('FACTURIER', self.n1, 'B')
        rec = self.rep(team='A', facturier=str(fb.pk))
        self.push(self.raw1, RAP, rec)
        self.assertTrue(self.has(FacturierReport, rec))
        # mais l'equipe elle-meme reste A ou B
        bad = self.rep(team='C', facturier=str(fb.pk))
        self.push(self.raw1, RAP, bad)
        self.assertFalse(self.has(FacturierReport, bad))

    # ---- defaut voisin : utilisateurs HQ sans boulangerie (cas reel de REST)
    @expectedFailure  # BUG-963
    def test_REST_rapport_cree_par_comptable_sans_noeud_puis_push(self):
        """REST : COMPTABLE/DIRECTION sans boulangerie cree un rapport (201, facturier = lui-meme).
        Au push avec ce facturier, le contrôle « meme noeud » le refuse (« n'appartient pas »)."""
        r = cl(self.compt).post('/api/treasury/reports/', {
            'node': str(self.n1.pk), 'date': str(today() - timedelta(days=6)),
            'total_cash_sales': '1000', 'total_credit_sales': '0'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNone(self.compt.node_id)
        rec = self.rep(facturier=str(self.compt.pk), team=r.json()['team'],
                       date=str(today() - timedelta(days=7)))
        self.push(self.raw1, RAP, rec)
        self.assertTrue(self.has(FacturierReport, rec))


# ======================================================================================
# 2 postes simules via sync_now : journee complete
# ======================================================================================
class V12_JourneeComplete(Base12):
    def _poste(self, node, code, specs, depense):
        f_a = make_user('FACTURIER', node, 'A')
        f_b = make_user('FACTURIER', node, 'B')
        for (team, cash, credit), f in zip(specs, (f_a, f_b)):
            FacturierReport.objects.create(
                node=node, facturier=f, team=team, date=today(), total_cash_sales=Dc(cash),
                total_credit_sales=Dc(credit), theoretical_cash=Dc(cash), node_origin=code)
        if depense:
            LocalExpense.objects.create(node=node, description='Eau', amount=Dc(depense), category=self.cat,
                                        date=today(), node_origin=code, gerant=None)

    def test_journee_complete_deux_postes_vers_chaine_et_etats(self):
        # N-1 : une journee du 31/12 de l'an dernier poussee par C1 (cloture confirmee plus tard)
        y1 = date(today().year - 1, 12, 31)
        f0 = make_user('FACTURIER', self.n1, 'A')
        FacturierReport.objects.create(node=self.n1, facturier=f0, team='A', date=y1,
                                       total_cash_sales=Dc('10000'), total_credit_sales=Dc('0'),
                                       theoretical_cash=Dc('10000'), node_origin='C1')
        LocalExpense.objects.create(node=self.n1, description='Eau N-1', amount=Dc('3000'),
                                    category=self.cat, date=y1, node_origin='C1')
        c_prev = CashClosure(node=self.n1, date=y1, total_entries=Dc('10000'), total_expenses=Dc('3000'),
                             bills_5000=1, bills_1000=2, node_origin='C1')
        c_prev.compute_physical_cash()
        c_prev.save()

        # jour J : C1 (A 50000, B 30000.50 ; depense 12500.50), C2 (A 20000 ; depense 5000)
        self._poste(self.n1, 'C1', (('A', '50000', '4000'), ('B', '30000.50', '0')), '12500.50')
        self._poste(self.n2, 'C2', (('A', '20000', '1000'),), '5000')
        FacturierReport.objects.filter(node=self.n2, team='B').delete()

        # clotures des postes (billetage exact C1 ; C2 : +500 de trop)
        for node, code, bills, net in ((self.n1, 'C1', {'bills_20000': 3, 'bills_5000': 1, 'bills_1000': 2,
                                                         'bills_500': 1}, Dc('67500')),
                                       (self.n2, 'C2', {'bills_10000': 1, 'bills_5000': 1, 'bills_500': 1},
                                        Dc('15000'))):
            c = CashClosure(node=node, date=today(), node_origin=code,
                            total_entries=net + (Dc('12500.50') if code == 'C1' else Dc('5000')),
                            total_expenses=Dc('12500.50') if code == 'C1' else Dc('5000'), **bills)
            c.compute_physical_cash()
            c.save()

        # envoi des deux postes (N-1 inclus pour C1)
        p1, res1 = self.cycle(self.raw1, 'C1')
        p2, res2 = self.cycle(self.raw2, 'C2')
        self.assertEqual(self.refused(res1), [], res1)
        self.assertEqual(self.refused(res2), [], res2)
        self.assertEqual({x['team'] for x in p1['records']['treasury.FacturierReport']}, {'A', 'B'})
        for code in ('C1', 'C2'):
            left = {k: v for k, v in build_outbound_payload(code)['records'].items() if v}
            self.assertEqual(left, {}, code)

        # cloud : sommes exactes (cumul des deux equipes, depenses locales)
        ids = {c.node.code + str(c.date): c for c in CashClosure.objects.all()}
        c1, c2, cp = ids['C1' + str(today())], ids['C2' + str(today())], ids['C1' + str(y1)]
        self.assertEqual((c1.total_entries, c1.total_expenses, c1.net_cash), (Dc('80000.50'), Dc('12500.50'), Dc('67500.00')))
        self.assertEqual(c1.physical_cash_total, Dc('67500'))
        self.assertEqual(c1.cash_gap, Dc('0'))
        self.assertEqual((c2.total_entries, c2.total_expenses, c2.net_cash, c2.cash_gap),
                         (Dc('20000'), Dc('5000'), Dc('15000'), Dc('500')))

        # confirmation (comptable) puis versement ; N-1 d'abord
        for c in (cp, c1, c2):
            self.assertEqual(self.valider(c.pk).status_code, 200)
            r = cl(self.compt).post(f'/api/treasury/closures/{c.pk}/push_to_cashbook/', {}, format='json')
            self.assertIn(r.status_code, (200, 201), r.content)
        e = {x.source_closure.node.code + str(x.date): x for x in CashbookEntry.objects.select_related('source_closure__node')}
        self.assertEqual(e['C1' + str(today())].piece_number, f"VC-C1-{today():%Y%m%d}")
        self.assertEqual(e['C1' + str(today())].entry_amount, Dc('67500.00'))
        self.assertEqual(e['C2' + str(today())].entry_amount, Dc('15000.00'))
        # bon de decaissement du siege
        r = cl(self.compt).post('/api/treasury/vouchers/', {'date': str(today()), 'motif': 'Achat farine',
                                                           'bills_10000': 3}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        last = list(CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()))[0]
        self.assertEqual(last.running_balance, Dc('7000') + Dc('67500') + Dc('15000') - Dc('30000'))
        # chaine + coherence treasury / blockchain
        self.assertTrue(self.chain_ok())
        rc = self.run_check()
        self.assertTrue(all(x.get('is_intact', True) for x in (rc if isinstance(rc, list) else rc.get('results', []))), rc)

        # etats financiers N et N-1
        fy = FinancialYear.objects.create(year=today().year)
        cf = cl(self.compt).get(f'/api/finance/years/{fy.pk}/cashflow/')
        self.assertEqual(cf.status_code, 200, cf.content)
        d = cf.json()
        self.assertEqual(Dc(str(d['total_entries'])), Dc('82500'))
        self.assertEqual(Dc(str(d['total_exits'])), Dc('30000'))
        self.assertEqual(Dc(str(d['previous_year']['total_entries'])), Dc('7000'))  # net N-1 = 10000-3000
        inc = cl(self.compt).get(f'/api/finance/years/{fy.pk}/income_statement/').json()
        self.assertEqual(Dc(str(inc['operational_expenses'])), Dc('17500.50'))
        self.assertEqual(Dc(str(inc['previous_year']['operational_expenses'])), Dc('3000'))

    @expectedFailure  # BUG-959
    def test_deux_facturiers_meme_equipe_meme_jour_via_sync_now(self):
        """REST autorise deux facturiers distincts dans une meme equipe ; le lot sortant de sync_now
        n'exporte pas `facturier` : le 2e rapport est refuse comme doublon et ses ventes cash sont
        perdues pour la cloture cloud."""
        fa, fb = make_user('FACTURIER', self.n1, 'A'), make_user('FACTURIER', self.n1, 'A')
        for f, cash in ((fa, '7000'), (fb, '3000')):
            FacturierReport.objects.create(node=self.n1, facturier=f, team='A', date=today(),
                                           total_cash_sales=Dc(cash), total_credit_sales=Dc('0'),
                                           theoretical_cash=Dc(cash), node_origin='C1')
        _, res = self.cycle(self.raw1, 'C1')
        self.assertEqual(self.refused(res), [])
        self.assertEqual(FacturierReport.objects.filter(node=self.n1, date=today()).count(), 2)

    def test_gerant_rapport_et_facturier_inactif_via_sync_now(self):
        """Rapport d'un gerant et d'un facturier desactive : ils transitent par le lot sortant."""
        f = make_user('FACTURIER', self.n1, 'B')
        FacturierReport.objects.create(node=self.n1, facturier=self.g1, team='A', date=today(),
                                       total_cash_sales=Dc('1000'), total_credit_sales=Dc('0'),
                                       theoretical_cash=Dc('1000'), node_origin='C1')
        FacturierReport.objects.create(node=self.n1, facturier=f, team='B', date=today(),
                                       total_cash_sales=Dc('2000'), total_credit_sales=Dc('0'),
                                       theoretical_cash=Dc('2000'), node_origin='C1')
        f.is_active = False
        f.save()
        _, res = self.cycle(self.raw1, 'C1')
        self.assertEqual(self.refused(res), [])
        self.assertEqual(sum(r.total_cash_sales for r in FacturierReport.objects.filter(node=self.n1)), Dc('3000'))

    def test_rejeu_apres_perte_de_reponse_ne_double_pas_les_totaux(self):
        FacturierReport.objects.create(node=self.n1, facturier=self.g1, team='A', date=today(),
                                       total_cash_sales=Dc('9000'), total_credit_sales=Dc('0'),
                                       theoretical_cash=Dc('9000'), node_origin='C1')
        payload = build_outbound_payload('C1')
        FacturierReport.objects.all().delete()
        for _ in range(3):
            r = push_client(self.raw1).post(PUSH, dict(payload, batch_id=str(uuid.uuid4())), format='json')
            self.assertEqual(r.status_code, 200)
        self.assertEqual(FacturierReport.objects.filter(node=self.n1).count(), 1)
        d = self.close(self.g1, {'bills_5000': 1, 'bills_1000': 4}).json()
        self.assertEqual(Dc(d['total_entries']), Dc('9000'))


# ======================================================================================
# Controles croises : BUG-675, BUG-677, BUG-871 dans les flux de cloture
# ======================================================================================
class V12_AjoutsPartieA(Base12):
    def _transfer(self, sent, received, status='CONFIRMED', frm=None, to=None):
        t = BreadTransfer.objects.create(from_node=frm or self.n2, to_node=to or self.n1,
                                         transfer_status=status, node_origin=(frm or self.n2).code)
        BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=sent,
                                         quantity_received=received)
        return t

    def test_675_transfert_equilibre_sans_effet_sur_la_caisse(self):
        self.report(self.n1, 'A', '10000')
        self.report(self.n2, 'A', '4000')
        self._transfer(100, 100)
        c1 = self.close(self.g1, {'bills_10000': 1}).json()
        c2 = self.close(self.g2, {'bills_1000': 4}).json()
        self.assertEqual((Dc(c1['net_cash']), Dc(c1['cash_gap'])), (Dc('10000'), Dc('0')))
        self.assertEqual((Dc(c2['net_cash']), Dc(c2['cash_gap'])), (Dc('4000'), Dc('0')))

    def test_675_ecart_non_resolu_bloque_cloture_creation_et_confirmation(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self._transfer(100, 98, status='DISPUTED')
        r = self.close(self.g1, {'bills_10000': 1}, date=str(today() - timedelta(days=0)))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.valider(d['id']).status_code, 400)
        # en attente / annule : n'empeche pas
        BreadTransfer.objects.all().delete()
        self._transfer(100, None, status='PENDING')
        self.assertEqual(self.valider(d['id']).status_code, 200)

    @expectedFailure  # BUG-960
    def test_675_cloture_poussee_validee_avec_ecart_de_transfert_non_resolu(self):
        """REST refuse la confirmation (BUG-277) ; un lot de sync portant is_validated=True inscrit
        la cloture au livre direction malgre l'ecart de transfert entrant non resolu."""
        self._transfer(100, 98, status='DISPUTED')
        rec = self.clo(is_validated=True)
        self.push(self.raw1, CLO, rec)
        self.assertFalse(CashbookEntry.objects.exists(),
                         "livre credite alors qu'un transfert entrant est en ecart non resolu")

    def test_677_depense_categorie_direction_ne_compte_pas_dans_la_cloture(self):
        cat_dir = ExpenseCategory.objects.create(code='DIR1', label='Direction', scope='DIRECTION')
        self.report(self.n1, 'A', '10000')
        r = self.expense(self.g1, '500', category=cat_dir.id)
        self.assertEqual(r.status_code, 400)
        r2 = self.push(self.raw1, EXP, self.exp_rec(category=cat_dir.pk))
        self.assertIn('REJECTED', r2.content.decode())
        self.assertEqual(self.expense(self.g1, '1000').status_code, 201)
        c = self.close(self.g1, {'bills_5000': 1, 'bills_1000': 4}).json()
        self.assertEqual((Dc(c['total_expenses']), Dc(c['cash_gap'])), (Dc('1000'), Dc('0')))

    def test_677_categorie_boulangerie_et_both_comptent(self):
        cb = ExpenseCategory.objects.create(code='BKR1', label='Boulangerie', scope='BAKERY')
        self.report(self.n1, 'A', '10000')
        self.assertEqual(self.expense(self.g1, '1000', category=cb.id).status_code, 201)
        self.assertEqual(self.expense(self.g1, '500').status_code, 201)
        c = self.close(self.g1, {'bills_5000': 1, 'bills_1000': 3, 'bills_500': 1}).json()
        self.assertEqual(Dc(c['total_expenses']), Dc('1500'))
        self.assertEqual(Dc(c['cash_gap']), Dc('0'))

    def test_871_categorie_inactive_refusee_en_REST_acceptee_hors_ligne(self):
        cat = ExpenseCategory.objects.create(code='OLD1', label='Ancienne')
        rec = self.exp_rec(category=cat.pk, amount='2500')
        cat.is_active = False
        cat.save()
        self.assertEqual(self.expense(self.g1, '100', category=cat.id).status_code, 400)
        self.push(self.raw1, EXP, rec)
        self.assertTrue(LocalExpense.objects.filter(pk=rec['id']).exists())
        self.report(self.n1, 'A', '10000')
        c = self.close(self.g1, {'bills_5000': 1, 'bills_1000': 2, 'bills_500': 1}).json()
        self.assertEqual(Dc(c['total_expenses']), Dc('2500'))

    # ---- defauts voisins : push LocalExpense
    @expectedFailure  # BUG-961
    def test_depense_poussee_sur_jour_de_cloture_confirmee(self):
        """REST (BUG-813) refuse toute depense sur un jour dont la cloture est confirmee ; le push
        l'accepte : net/ecart confirmes par le comptable deviennent perimes (dont le livre)."""
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(self.valider(d['id']).status_code, 200)
        self.assertEqual(self.expense(self.g1, '100').status_code, 400)
        rec = self.exp_rec(amount='4000')
        self.push(self.raw1, EXP, rec)
        self.assertFalse(LocalExpense.objects.filter(pk=rec['id']).exists())

    @expectedFailure  # BUG-962
    def test_depense_poussee_date_future_et_invalide_refusee(self):
        bad = []
        for dte in (str(today() + timedelta(days=3)), '2999-01-01', '2026-02-30', '１２-01-01', 20261101):
            rec = self.exp_rec(date=dte)
            r = self.push(self.raw1, EXP, rec)
            if LocalExpense.objects.filter(pk=rec['id']).exists():
                bad.append(dte)
        self.assertEqual(bad, [])


# ======================================================================================
# Lectures : permissions finance, tresorerie, exports
# ======================================================================================
class V12_Lectures(Base12):
    def setUp(self):
        self.fy = FinancialYear.objects.create(year=today().year)

    def test_finance_lecture_reservee_au_siege(self):
        urls = [f'/api/finance/years/{self.fy.pk}/{a}/' for a in
                ('income_statement', 'cashflow', 'balance_sheet', 'comparative')]
        urls += ['/api/finance/years/', '/api/finance/years/summary/?year=%d' % today().year,
                 '/api/finance/years/doc1_export/?node=%s&month=1&year=%d' % (self.n1.pk, today().year)]
        bad = []
        for u in urls:
            for usr in (self.g1, self.fac, self.liv):
                code = cl(usr).get(u).status_code
                if code != 403:
                    bad.append((usr.role, u, code))
            self.assertEqual(cl().get(u).status_code, 401, u)
            self.assertNotEqual(cl(self.compt).get(u).status_code, 403, u)
        self.assertEqual(bad, [])

    def test_finance_ecriture_interdite_aux_non_siege_et_exercice_inconnu(self):
        for usr in (self.g1, self.fac):
            self.assertEqual(cl(usr).post('/api/finance/years/', {'year': 2031}, format='json').status_code, 403)
            self.assertEqual(cl(usr).delete(f'/api/finance/years/{self.fy.pk}/').status_code, 403)
        r = cl(self.compt).get('/api/finance/years/999999/cashflow/')
        self.assertEqual(r.status_code, 404)

    def test_tresorerie_lecture_livre_et_siege_interdits_aux_roles_boulangerie(self):
        bad = []
        for u in ('/api/treasury/cashbook/', '/api/treasury/cashbook/integrity_check/',
                  '/api/treasury/vouchers/', '/api/treasury/direction-cash-counts/',
                  '/api/treasury/closures/final_report/', '/api/treasury/cashbook/period_summary/'):
            for usr in (self.g1, self.fac, self.liv):
                code = cl(usr).get(u).status_code
                if code not in (403, 404):
                    bad.append((usr.role, u, code))
        self.assertEqual(bad, [])

    def test_blockchain_lecture_reservee(self):
        bad = []
        for u in ('/api/blockchain/alerts/', '/api/blockchain/snapshots/'):
            for usr in (self.g1, self.fac, self.liv):
                if cl(usr).get(u).status_code != 403:
                    bad.append((usr.role, u))
        r = cl(self.g1).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(bad, [])

    def test_gerant_ne_lit_pas_les_clotures_ni_rapports_d_une_autre_boulangerie(self):
        self.report(self.n2, 'A', '5000')
        c = self.close(self.g2, {'bills_5000': 1}).json()
        for u in (f'/api/treasury/closures/?node={self.n2.pk}', f'/api/treasury/reports/?node={self.n2.pk}',
                  f'/api/treasury/expenses/?node={self.n2.pk}'):
            d = cl(self.g1).get(u)
            body = d.json()
            rows = body.get('results', body) if isinstance(body, dict) else body
            self.assertEqual(len(rows), 0, u)
        self.assertEqual(cl(self.g1).get(f"/api/treasury/closures/{c['id']}/").status_code, 404)

    def test_exports_et_rapports_gerant_perimetre(self):
        self.report(self.n2, 'A', '5000')
        for u in ('/api/treasury/reports/monthly_report/', '/api/treasury/reports/suggested_ca/',
                  '/api/treasury/expenses/monthly_total/'):
            for usr in (self.fac, self.liv):
                code = cl(usr).get(u).status_code
                self.assertIn(code, (403, 404), (u, usr.role, code))
