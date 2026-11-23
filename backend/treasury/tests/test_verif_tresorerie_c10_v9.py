"""Cycle 10 (testeur-tresorerie, 2026-11-23-c10) : verification independante de BUG-910 a 914
(controles stricts du push sync FacturierReport / CashClosure / DisbursementVoucher, d26) et de la
regression BUG-911 corrigee au d27 (deux facturiers distincts / meme facturier). Non-regression des
pushs legitimes, puis exploration des defauts voisins : champ `facturier` desormais stocke
(facturier forge, d'un autre noeud, d'un autre role), rapport pousse sur un jour deja confirme.
Donnees fictives. Code applicatif non modifie.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.testing import make_user
from sync.models import NodeAuthToken
from treasury.models import CashbookEntry, CashClosure, DisbursementVoucher, FacturierReport
from treasury.tests.test_cycle1_tresorerie_c import BILLS, cl, today
from treasury.tests.test_verif_tresorerie_c8_v7 import ARAB, FULL, PUSH, push_client
from treasury.tests.test_verif_tresorerie_c9_v8 import PushBase

RAP = 'treasury.FacturierReport'
CLO = 'treasury.CashClosure'
VOU = 'treasury.DisbursementVoucher'


class Base10(PushBase):
    def results(self, r):
        return r.json()

    def has(self, model, rec):
        return model.objects.filter(pk=rec['id']).exists()

    def batch(self, raw, records):
        r = push_client(raw).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': records}, format='json')
        self.assertLess(r.status_code, 500, r.content)
        return r


# ---------------------------------------------------------------- BUG-910 / 911 / 912
class V910_912_Rapport(Base10):
    def test_910_montants_rejets_cibles(self):
        cases = [('total_cash_sales', '-0.01'), ('total_credit_sales', '-1'), ('theoretical_cash', '-100'),
                 ('sacks_consumed', '-2'), ('total_cash_sales', '10.005'), ('sacks_value_gap', '1.234'),
                 ('total_cash_sales', ARAB), ('sacks_value_gap', FULL), ('total_cash_sales', 'abc'),
                 ('total_cash_sales', '1e400'), ('total_cash_sales', 'NaN'), ('total_cash_sales', '1' * 15)]
        bad = []
        for f, v in cases:
            rec = self.rep(**{f: v})
            self.push(self.raw1, RAP, rec)
            if self.has(FacturierReport, rec):
                bad.append((f, v))
        self.assertEqual(bad, [])

    def test_910_valeurs_legitimes_acceptees(self):
        """Non-regression : zero, 2 decimales, ecart de sacs negatif, entiers, nombres JSON."""
        for i, kw in enumerate((
                {'total_cash_sales': '0', 'total_credit_sales': '0', 'theoretical_cash': '0'},
                {'total_cash_sales': '12500.50'}, {'sacks_value_gap': '-35000.25'},
                {'sacks_consumed': '3.50'}, {'total_cash_sales': 15000, 'theoretical_cash': 15000.5},
                {'total_cash_sales': '99999999999.99'})):
            rec = self.rep(team='A' if i % 2 == 0 else 'B', **kw)
            rec['date'] = str(today() - timedelta(days=i))
            self.push(self.raw1, RAP, rec)
            self.assertTrue(self.has(FacturierReport, rec), kw)
        gap = FacturierReport.objects.filter(sacks_value_gap__lt=0).first()
        self.assertEqual(gap.sacks_value_gap, Dc('-35000.25'))

    def test_911_equipe_obligatoire_et_valide(self):
        bad = []
        for team in ('Z', 'a', 'AB', '', None, 1, ['A'], 'A '):
            rec = self.rep(team=team)
            self.push(self.raw1, RAP, rec)
            if self.has(FacturierReport, rec):
                bad.append(team)
        rec = self.rep()
        del rec['team']
        self.push(self.raw1, RAP, rec)
        if self.has(FacturierReport, rec):
            bad.append('<absent>')
        self.assertEqual(bad, [])

    def test_911_equipes_A_et_B_distinctes_acceptees(self):
        a, b = self.rep(team='A'), self.rep(team='B')
        self.push(self.raw1, RAP, a)
        self.push(self.raw1, RAP, b)
        self.assertEqual(FacturierReport.objects.filter(node=self.n1, date=today()).count(), 2)

    def test_911_rejeu_meme_id_sans_equipe_reste_idempotent(self):
        rec = self.rep()
        self.push(self.raw1, RAP, rec)
        replay = {k: v for k, v in rec.items() if k != 'team'}
        r = self.push(self.raw1, RAP, replay)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(FacturierReport.objects.filter(pk=rec['id']).count(), 1)

    def test_912_dates_rejets_et_hier_accepte(self):
        for d in (str(today() + timedelta(days=1)), '2999-01-01', '2026-02-30', ARAB, 20261122):
            rec = self.rep(date=d)
            self.push(self.raw1, RAP, rec)
            self.assertFalse(self.has(FacturierReport, rec), d)
        ok = self.rep(date=str(today() - timedelta(days=1)))
        self.push(self.raw1, RAP, ok)
        self.assertTrue(self.has(FacturierReport, ok))
        aujourdhui = self.rep(team='B')
        self.push(self.raw1, RAP, aujourdhui)
        self.assertTrue(self.has(FacturierReport, aujourdhui))

    def test_912_non_ascii_date_pas_de_500(self):
        for d in (FULL, '２０２６-１１-２２', None, [], {}):
            rec = self.rep(date=d)
            r = self.push(self.raw1, RAP, rec)
            self.assertEqual(r.status_code, 200)
            self.assertFalse(self.has(FacturierReport, rec))


# ---------------------------------------------------------------- BUG-911 / d27 facturiers
class V911_Facturiers(Base10):
    def n(self, team='A'):
        return FacturierReport.objects.filter(node=self.n1, team=team, date=today()).count()

    def test_deux_facturiers_distincts_acceptes_et_stockes(self):
        f1, f2 = make_user('FACTURIER', self.n1, 'A'), make_user('FACTURIER', self.n1, 'A')
        a, b = self.rep(facturier=str(f1.pk)), self.rep(facturier=str(f2.pk))
        self.push(self.raw1, RAP, a)
        self.push(self.raw1, RAP, b)
        self.assertEqual(self.n(), 2)
        self.assertEqual(FacturierReport.objects.get(pk=a['id']).facturier_id, f1.pk)
        self.assertEqual(FacturierReport.objects.get(pk=b['id']).facturier_id, f2.pk)

    def test_meme_facturier_rejete_message_clair(self):
        f1 = make_user('FACTURIER', self.n1, 'A')
        self.push(self.raw1, RAP, self.rep(facturier=str(f1.pk)))
        r = self.push(self.raw1, RAP, self.rep(facturier=str(f1.pk)))
        self.assertEqual(self.n(), 1)
        self.assertIn('REJECTED', r.content.decode())

    def test_sans_facturier_deux_fois_rejete_et_une_fois_accepte(self):
        a = self.rep()
        self.push(self.raw1, RAP, a)
        self.assertTrue(self.has(FacturierReport, a))
        self.push(self.raw1, RAP, self.rep())
        self.assertEqual(self.n(), 1)

    def test_meme_facturier_autre_equipe_ou_autre_jour_accepte(self):
        f1 = make_user('FACTURIER', self.n1, 'A')
        self.push(self.raw1, RAP, self.rep(facturier=str(f1.pk)))
        self.push(self.raw1, RAP, self.rep(facturier=str(f1.pk), team='B'))
        self.push(self.raw1, RAP, self.rep(facturier=str(f1.pk), date=str(today() - timedelta(days=1))))
        self.assertEqual(FacturierReport.objects.filter(facturier=f1).count(), 3)

    def test_facturier_forme_invalide_pas_de_500(self):
        for v in (12, 1.5, True, ['x'], {'a': 1}, 'pas-un-uuid', ARAB, '0' * 40):
            rec = self.rep(facturier=v, team='B', date=str(today() - timedelta(days=9)))
            r = self.push(self.raw1, RAP, rec)
            self.assertEqual(r.status_code, 200, (v, r.content))
            FacturierReport.objects.all().delete()

    # --- defauts voisins : le champ facturier est desormais stocke sans controle
    def test_facturier_autre_noeud_refuse(self):
        """REST : facturier = utilisateur connecte, donc de la boulangerie. Un noeud C1 ne doit pas
        attribuer un rapport a un utilisateur de C2."""
        etranger = make_user('FACTURIER', self.n2, 'A')
        rec = self.rep(facturier=str(etranger.pk))
        self.push(self.raw1, RAP, rec)
        r = FacturierReport.objects.filter(pk=rec['id']).first()
        self.assertTrue(r is None or r.facturier_id != etranger.pk,
                        "rapport C1 attribue a un facturier de C2")

    def test_facturier_non_facturier_refuse(self):
        """Un gerant, un comptable ou un administrateur n'est pas un facturier."""
        bad = []
        for u in (self.liv,):  # d30 BUG-935 : GERANT/COMPTABLE/DIRECTION/ADMIN du noeud acceptes
            rec = self.rep(facturier=str(u.pk), team='B', date=str(today() - timedelta(days=3)))
            self.push(self.raw1, RAP, rec)
            r = FacturierReport.objects.filter(pk=rec['id']).first()
            if r is not None and r.facturier_id == u.pk:
                bad.append(u.role)
            FacturierReport.objects.all().delete()
        self.assertEqual(bad, [])

    def test_facturier_inexistant_pas_stocke_comme_nul_silencieusement(self):
        """Un uuid de facturier inexistant devient NULL sans rejet : le rapport est accepte avec une
        attribution perdue (et contourne l'unicite d'un facturier reel). On attend un rejet."""
        rec = self.rep(facturier=str(uuid.uuid4()))
        self.push(self.raw1, RAP, rec)
        self.assertFalse(self.has(FacturierReport, rec))

    def test_somme_rapports_multi_facturiers_dans_la_cloture(self):
        """Incidence sur la cloture : la somme des rapports du jour (2 facturiers de la meme equipe)
        alimente total_entries."""
        f1, f2 = make_user('FACTURIER', self.n1, 'A'), make_user('FACTURIER', self.n1, 'A')
        self.push(self.raw1, RAP, self.rep(facturier=str(f1.pk), total_cash_sales='7000'))
        self.push(self.raw1, RAP, self.rep(facturier=str(f2.pk), total_cash_sales='3000.50'))
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(Dc(d['total_entries']), Dc('10000.50'))
        self.assertEqual(Dc(d['cash_gap']), Dc('-0.50'))

    def test_lecture_rapports_cloisonnee_par_noeud(self):
        f1 = make_user('FACTURIER', self.n1, 'A')
        etranger = make_user('FACTURIER', self.n2, 'A')
        self.push(self.raw1, RAP, self.rep(facturier=str(f1.pk)))
        ids_c1 = {x['id'] for x in cl(self.g1).get('/api/treasury/reports/').json().get('results', [])}
        self.assertEqual(len(ids_c1), 1)
        r2 = cl(etranger).get('/api/treasury/reports/').json()
        self.assertEqual(len(r2.get('results', r2)), 0)
        r = cl(self.g2).get(f"/api/treasury/reports/{next(iter(ids_c1))}/")
        self.assertEqual(r.status_code, 404)

    def test_suppression_du_facturier_ne_casse_pas_cloture(self):
        f1 = make_user('FACTURIER', self.n1, 'A')
        self.push(self.raw1, RAP, self.rep(facturier=str(f1.pk), total_cash_sales='5000'))
        f1.delete()
        d = self.close(self.g1, {'bills_5000': 1}).json()
        self.assertEqual(Dc(d['total_entries']), Dc('5000'))

    def test_rapport_pousse_sur_jour_deja_confirme_refuse(self):
        """REST : _refuse_if_closure_confirmed interdit tout rapport un jour de cloture confirmee."""
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{d['id']}/validate/", {}, format='json')
        self.assertTrue(CashClosure.objects.get(pk=d['id']).is_validated)
        rec = self.rep(team='B', total_cash_sales='50000')
        self.push(self.raw1, RAP, rec)
        self.assertFalse(self.has(FacturierReport, rec),
                         "rapport accepte apres confirmation de la cloture : net confirme perime")


# ---------------------------------------------------------------- BUG-913 cloture
class V913_Cloture(Base10):
    def test_rejets_cibles(self):
        bad = []
        for f, v in (('total_entries', '-0.01'), ('total_expenses', '-5'), ('total_entries', '1.005'),
                     ('total_expenses', '1.005'), ('total_entries', ARAB), ('bills_20000', -1),
                     ('bills_50', '1.5'), ('bills_100', 2.0 + 0.5), ('bills_500', FULL), ('bills_200', True),
                     ('bills_200', 'x'), ('bills_1000', [1]), ('bills_10000', 10 ** 30)):
            rec = self.clo(**{f: v})
            self.push(self.raw1, CLO, rec)
            if self.has(CashClosure, rec):
                bad.append((f, v))
            CashClosure.objects.all().delete()
        self.assertEqual(bad, [])

    def test_cloture_legitime_toutes_coupures(self):
        qty = dict(zip(BILLS, (1, 2, 3, 4, 5, 6, 7, 8)))
        rec = self.clo(**qty)
        self.push(self.raw1, CLO, rec)
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual(c.physical_cash_total, Dc(20000 + 20000 + 15000 + 4000 + 2500 + 1200 + 700 + 400))

    def test_cloture_zero_billet_et_chaines_numeriques_acceptees(self):
        rec = self.clo(**{**{b: '0' for b in BILLS}, 'bills_500': '4'})
        r = self.push(self.raw1, CLO, rec)
        self.assertTrue(self.has(CashClosure, rec) or 'erreur serveur' not in r.content.decode(),
                        "chiffre en chaine passe le controle strict puis fait echouer le handler : " + r.content.decode())

    def test_cloture_lot_mixte(self):
        ok = self.clo(date=str(today() - timedelta(days=1)))
        ko = self.clo(total_entries='-1')
        ko2 = self.clo(date=str(today() - timedelta(days=2)), bills_50=ARAB)
        ok2 = self.clo(date=str(today() - timedelta(days=3)), bills_10000=2)
        r = self.batch(self.raw1, {CLO: [ok, ko, ko2, ok2]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.has(CashClosure, ok) and self.has(CashClosure, ok2))
        self.assertFalse(self.has(CashClosure, ko) or self.has(CashClosure, ko2))
        self.assertEqual(r.content.decode().count('REJECTED'), 2, r.content)

    def test_cloture_rejeu_idempotent_et_aucun_doublon_livre(self):
        rec = self.clo(is_validated=True)
        for _ in range(3):
            self.push(self.raw1, CLO, rec)
        self.assertEqual(CashClosure.objects.filter(node=self.n1).count(), 1)
        # BUG-971 : adapte, jamais confirmee ni versee par un jeton de boulangerie
        self.assertFalse(CashClosure.objects.get(node=self.n1).is_validated)
        self.assertEqual(CashbookEntry.objects.count(), 0)
        self.assertTrue(self.chain_ok())

    def test_cloture_valide_rejetee_ne_touche_pas_le_livre(self):
        rec = self.clo(is_validated=True, bills_50=-3)
        self.push(self.raw1, CLO, rec)
        self.assertEqual(CashbookEntry.objects.count(), 0)


# ---------------------------------------------------------------- BUG-914 bordereau
class V914_Bordereau(Base10):
    def last_balance(self):
        e = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        return e.running_balance if e else None

    def test_bordereau_valide_solde_exact_et_chaine(self):
        self.fund_livre('50000')
        rec = self.vou(bills_5000=1, bills_1000=2, bills_500=1, bills_50=3)  # 7650
        self.push(self.raws, VOU, rec)
        self.assertTrue(self.has(DisbursementVoucher, rec))
        self.assertEqual(self.last_balance(), Dc('50000') - Dc('7650'))
        e = CashbookEntry.objects.filter(source_bordereau_id=rec['id']).get()
        self.assertEqual(e.exit_amount, Dc('7650'))
        self.assertTrue(self.chain_ok())

    def test_bordereau_exactement_le_solde_accepte(self):
        self.fund_livre('10000')
        rec = self.vou(bills_1000=10)
        self.push(self.raws, VOU, rec)
        self.assertTrue(self.has(DisbursementVoucher, rec))
        self.assertEqual(self.last_balance(), Dc('0'))

    def test_bordereau_depassant_le_solde_pas_d_orphelin_et_livre_intact(self):
        self.fund_livre('10000')
        for q in (11, 50, 1000):
            rec = self.vou(bills_1000=q)
            self.push(self.raws, VOU, rec)
            self.assertFalse(self.has(DisbursementVoucher, rec), q)
        self.assertEqual(DisbursementVoucher.objects.count(), 0)
        self.assertEqual(CashbookEntry.objects.count(), 1)
        self.assertEqual(self.last_balance(), Dc('10000'))
        self.assertTrue(self.chain_ok())

    def test_bordereau_livre_vide_pas_d_orphelin(self):
        rec = self.vou(bills_1000=1)
        self.push(self.raws, VOU, rec)
        self.assertFalse(self.has(DisbursementVoucher, rec))
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_bordereau_rejeu_apres_rejet_pas_de_debit_fantome(self):
        self.fund_livre('10000')
        rec = self.vou(bills_20000=1)
        self.push(self.raws, VOU, rec)
        self.push(self.raws, VOU, rec)
        self.assertEqual(DisbursementVoucher.objects.count(), 0)
        self.assertEqual(self.last_balance(), Dc('10000'))

    def test_bordereau_zero_et_negatifs_refuses(self):
        self.fund_livre('10000')
        bad = []
        for kw in ({}, {'bills_1000': 0, 'bills_500': 0}, {'bills_1000': -2}, {'bills_1000': 3, 'bills_500': -1},
                   {'bills_1000': ARAB}, {'bills_1000': 1.5}, {'bills_1000': '2.0'}):
            rec = self.vou(**{'bills_1000': 0, **kw})
            self.push(self.raws, VOU, rec)
            if self.has(DisbursementVoucher, rec):
                bad.append(kw)
        self.assertEqual(bad, [])
        self.assertEqual(self.last_balance(), Dc('10000'))

    def test_bordereau_rejeu_idempotent_solde_debite_une_fois(self):
        self.fund_livre('10000')
        rec = self.vou(bills_1000=3)
        for _ in range(4):
            self.push(self.raws, VOU, rec)
        self.assertEqual(CashbookEntry.objects.filter(source_bordereau_id=rec['id']).count(), 1)
        self.assertEqual(self.last_balance(), Dc('7000'))

    def test_bordereau_lot_mixte_solde_exact(self):
        self.fund_livre('10000')
        a, b, c, d = (self.vou(bills_1000=2), self.vou(bills_1000=0), self.vou(bills_1000=50),
                      self.vou(bills_1000=0, bills_500=4))
        r = self.batch(self.raws, {VOU: [a, b, c, d]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.has(DisbursementVoucher, a) and self.has(DisbursementVoucher, d))
        self.assertFalse(self.has(DisbursementVoucher, b) or self.has(DisbursementVoucher, c))
        self.assertEqual(self.last_balance(), Dc('10000') - 2000 - 2000)
        self.assertEqual(DisbursementVoucher.objects.count(), 2)
        self.assertEqual(CashbookEntry.objects.count(), 3)
        self.assertTrue(self.chain_ok())

    def test_bordereau_date_future_refuse_et_boulangerie_refuse(self):
        self.fund_livre('10000')
        f = self.vou(date=str(today() + timedelta(days=2)))
        self.push(self.raws, VOU, f)
        g = self.vou()
        self.push(self.raw1, VOU, g)
        self.assertFalse(self.has(DisbursementVoucher, f) or self.has(DisbursementVoucher, g))
        self.assertEqual(self.last_balance(), Dc('10000'))


# ---------------------------------------------------------------- journee mixte
class JourneeMixtePush(Base10):
    def test_journee_complete_push_puis_rest_chaine_intacte(self):
        fa, fb = make_user('FACTURIER', self.n1, 'A'), make_user('FACTURIER', self.n1, 'B')
        r = self.batch(self.raw1, {RAP: [
            self.rep(team='A', facturier=str(fa.pk), total_cash_sales='30000', theoretical_cash='30000'),
            self.rep(team='B', facturier=str(fb.pk), total_cash_sales='20000', theoretical_cash='20000'),
            self.rep(team='A', facturier=str(fa.pk), total_cash_sales='1'),  # doublon rejete
        ]})
        self.assertEqual(r.content.decode().count('REJECTED'), 1)
        d = self.close(self.g1, {'bills_20000': 2, 'bills_10000': 1}).json()
        self.assertEqual(Dc(d['total_entries']), Dc('50000'))
        self.assertEqual(Dc(d['cash_gap']), Dc('0'))
        self.assertEqual(self.versement(d['id']).status_code, 201)
        self.push(self.raws, VOU, self.vou(bills_1000=0, bills_10000=1))
        e = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(e.running_balance, Dc('40000'))
        self.assertTrue(self.chain_ok())
        a = cl(self.dirn).get('/api/blockchain/verify/')
        if a.status_code == 200:
            self.assertTrue(a.json().get('chain_valid', a.json().get('valid', True)))


class V919_Double_comptage(Base10):
    def test_facturiers_forges_ne_doublent_pas_les_ventes_de_la_vacation(self):
        """Un noeud C1 pousse 3 rapports de la meme vacation (C1, A, aujourd'hui) en attribuant chacun a
        un utilisateur quelconque : tous acceptes, la cloture somme 3 x les ventes."""
        autres = [make_user('GERANT', self.n2), make_user('COMPTABLE'), make_user('LIVREUR', self.n2)]
        for u in autres:
            self.push(self.raw1, RAP, self.rep(facturier=str(u.pk), total_cash_sales='10000'))
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertLessEqual(Dc(d['total_entries']), Dc('10000'))
