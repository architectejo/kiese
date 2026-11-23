"""Cycle 11 (testeur-tresorerie, 2026-11-23-c11) : verification independante de BUG-929 a 932
(controles du push FacturierReport / billetage en chaines, d29), arbitrage des deux points laisses
ouverts (equipe du facturier, role GERANT) et defauts voisins (facturier desactive apres coup,
rejeu, rapports hors ligne du jour J pendant la cloture de J). Donnees fictives. Code applicatif
non modifie.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.testing import make_user
from treasury.models import CashClosure, FacturierReport
from treasury.tests.test_cycle1_tresorerie_c import BILLS, cl, today
from treasury.tests.test_verif_tresorerie_c10_v9 import CLO, RAP, Base10


class V929_930_Facturier(Base10):
    def test_929_forge_inactif_autre_role_autre_noeud_refuses(self):
        inactif = make_user('FACTURIER', self.n1, 'A')
        inactif.is_active = False
        inactif.save()
        etranger = make_user('FACTURIER', self.n2, 'A')
        bad = []
        for label, val in (('inactif', inactif.pk), ('autre_noeud', etranger.pk), ('livreur', self.liv.pk),
                           ('compta', self.compt.pk), ('uuid_inconnu', uuid.uuid4()), ('texte', 'x'),
                           ('nombre', 12), ('liste', ['a'])):
            rec = self.rep(facturier=str(val) if not isinstance(val, (int, list)) else val,
                           team='B', date=str(today() - timedelta(days=2)))
            r = self.push(self.raw1, RAP, rec)
            self.assertEqual(r.status_code, 200)
            if self.has(FacturierReport, rec):
                bad.append(label)
            FacturierReport.objects.all().delete()
        self.assertEqual(bad, [])

    def test_930_pas_de_null_silencieux_pour_uuid_inconnu(self):
        rec = self.rep(facturier=str(uuid.uuid4()))
        r = self.push(self.raw1, RAP, rec)
        self.assertFalse(self.has(FacturierReport, rec))
        self.assertIn('facturier', r.content.decode().lower())

    def test_non_regression_flux_legitimes(self):
        f1, f2 = make_user('FACTURIER', self.n1, 'A'), make_user('FACTURIER', self.n1, 'A')
        for f in (f1, f2):
            self.push(self.raw1, RAP, self.rep(facturier=str(f.pk)))
        sans = self.rep()
        self.push(self.raw1, RAP, sans)
        self.assertEqual(FacturierReport.objects.filter(node=self.n1, team='A', date=today()).count(), 3)
        self.assertIsNone(FacturierReport.objects.get(pk=sans['id']).facturier_id)
        doublon = self.rep()
        self.push(self.raw1, RAP, doublon)
        self.assertFalse(self.has(FacturierReport, doublon))

    def test_facturier_du_siege_pour_rapport_noeud_refuse(self):
        sf = make_user('FACTURIER', self.siege, 'A')
        rec = self.rep(facturier=str(sf.pk))
        self.push(self.raw1, RAP, rec)
        self.assertFalse(self.has(FacturierReport, rec))

    # ---- point 1 : equipe du facturier
    def test_equipe_du_facturier_non_controlee_coherent_avec_REST(self):
        """REST : equipe du rapport = user.team au moment de la creation ; user.team est modifiable
        (rotation A/B, remarque.md : le gerant peut changer d'equipe). Un meme facturier peut donc
        produire des rapports A puis B. Le push ne doit pas refuser (verrouille le comportement actuel)."""
        fb = make_user('FACTURIER', self.n1, 'B')
        rec = self.rep(team='A', facturier=str(fb.pk))
        self.push(self.raw1, RAP, rec)
        self.assertTrue(self.has(FacturierReport, rec))

    def test_REST_meme_utilisateur_deux_equipes_apres_changement(self):
        g = make_user('GERANT', self.n1, 'A')
        r1 = cl(g).post('/api/treasury/reports/', {
            'date': str(today()), 'total_cash_sales': '1000', 'total_credit_sales': '0'}, format='json')
        self.assertEqual(r1.status_code, 201, r1.content)
        g.team = 'B'
        g.save()
        r2 = cl(g).post('/api/treasury/reports/', {
            'date': str(today()), 'total_cash_sales': '2000', 'total_credit_sales': '0'}, format='json')
        self.assertEqual(r2.status_code, 201, r2.content)
        self.assertEqual({r1.json()['team'], r2.json()['team']}, {'A', 'B'})

    # ---- point 2 : role GERANT
    def test_REST_qui_peut_creer_un_rapport(self):
        res = {}
        for u in (self.fac, self.liv, self.g1, self.compt, self.dirn):
            res[u.role] = cl(u).post('/api/treasury/reports/', {
                'node': str(self.n1.pk), 'date': str(today() - timedelta(days=5)),
                'total_cash_sales': '1', 'total_credit_sales': '0'}, format='json').status_code
            FacturierReport.objects.all().delete()
        self.assertEqual(res['FACTURIER'], 403)
        self.assertEqual(res['LIVREUR'], 403)
        self.assertEqual(res['GERANT'], 201)
        self.assertEqual(res['COMPTABLE'], 201)
        self.assertEqual(res['DIRECTION'], 201)

    def test_REST_gerant_est_son_propre_facturier(self):
        r = cl(self.g1).post('/api/treasury/reports/', {
            'date': str(today()), 'total_cash_sales': '1000', 'total_credit_sales': '0'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(str(FacturierReport.objects.get(pk=r.json()['id']).facturier_id), str(self.g1.pk))

    @expectedFailure  # BUG-935
    def test_935_push_rapport_dont_le_facturier_est_un_gerant_accepte(self):
        """Un rapport cree localement par/pour un gerant (REST : facturier = utilisateur connecte,
        IsGerant) est refuse au push : « doit etre un utilisateur actif de role facturier »."""
        rec = self.rep(facturier=str(self.g1.pk))
        self.push(self.raw1, RAP, rec)
        self.assertTrue(self.has(FacturierReport, rec))

    @expectedFailure  # BUG-935
    def test_935_push_rapport_facturier_comptable_ou_direction_du_noeud(self):
        c1 = make_user('COMPTABLE', self.n1, 'A')
        rec = self.rep(facturier=str(c1.pk))
        self.push(self.raw1, RAP, rec)
        self.assertTrue(self.has(FacturierReport, rec))

    # ---- defauts voisins : facturier desactive apres coup
    def test_rejeu_apres_desactivation_reste_idempotent(self):
        f = make_user('FACTURIER', self.n1, 'A')
        rec = self.rep(facturier=str(f.pk))
        self.push(self.raw1, RAP, rec)
        f.is_active = False
        f.save()
        r = self.push(self.raw1, RAP, rec)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(FacturierReport.objects.filter(pk=rec['id']).count(), 1)
        self.assertNotIn('REJECTED', r.content.decode())

    @expectedFailure  # BUG-936
    def test_936_rapport_hors_ligne_d_un_facturier_desactive_depuis_accepte(self):
        """Le rapport a ete cree legitimement hors ligne ; le facturier a quitte l'entreprise
        (compte desactive) avant la synchronisation : le rapport (cash) ne doit pas etre perdu."""
        f = make_user('FACTURIER', self.n1, 'A')
        rec = self.rep(facturier=str(f.pk), total_cash_sales='25000', theoretical_cash='25000')
        f.is_active = False
        f.save()
        self.push(self.raw1, RAP, rec)
        self.assertTrue(self.has(FacturierReport, rec),
                        "ventes cash de 25 000 FC perdues pour la cloture du jour")

    def test_936_consequence_sur_la_cloture(self):
        """Verrouille le constat : rapport refuse -> cloture sans ces ventes (ecart physique)."""
        f = make_user('FACTURIER', self.n1, 'A')
        rec = self.rep(facturier=str(f.pk), total_cash_sales='25000', theoretical_cash='25000')
        f.is_active = False
        f.save()
        self.push(self.raw1, RAP, rec)
        d = self.close(self.g1, {'bills_20000': 1, 'bills_5000': 1}).json()
        attendu = Dc('25000') if self.has(FacturierReport, rec) else Dc('0')
        self.assertEqual(Dc(d['total_entries']), attendu)

    # ---- BUG-931 : jour confirme / jour en cours de cloture
    def test_931_rapport_avant_et_pendant_la_cloture_non_confirmee_accepte(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        rec = self.rep(team='B', total_cash_sales='4000', theoretical_cash='4000')
        self.push(self.raw1, RAP, rec)
        self.assertTrue(self.has(FacturierReport, rec))
        r = cl(self.compt).post(f"/api/treasury/closures/{d['id']}/validate/", {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        c = CashClosure.objects.get(pk=d['id'])
        self.assertEqual(c.total_entries, Dc('14000'),
                         "le rapport hors ligne arrive avant confirmation doit etre compte")

    def test_931_apres_confirmation_refuse_y_compris_autre_equipe_et_facturier(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{d['id']}/validate/", {}, format='json')
        f = make_user('FACTURIER', self.n1, 'B')
        for kw in ({}, {'team': 'B'}, {'facturier': str(f.pk), 'team': 'B'}):
            rec = self.rep(**kw)
            self.push(self.raw1, RAP, rec)
            self.assertFalse(self.has(FacturierReport, rec), kw)

    def test_931_autres_jours_et_autres_noeuds_non_bloques(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{d['id']}/validate/", {}, format='json')
        veille = self.rep(date=str(today() - timedelta(days=1)))
        self.push(self.raw1, RAP, veille)
        self.assertTrue(self.has(FacturierReport, veille))
        autre = self.rep(node='C2')
        self.push(self.raw1, RAP, autre)  # jeton C1, rapport C2 : hors perimetre, pas de 500
        self.assertFalse(FacturierReport.objects.filter(pk=autre['id'], node=self.n1).exists())

    def test_931_rejeu_rapport_deja_accepte_apres_confirmation_idempotent(self):
        rec = self.rep()
        self.push(self.raw1, RAP, rec)
        d = self.close(self.g1, {'bills_10000': 1}).json()
        cl(self.compt).post(f"/api/treasury/closures/{d['id']}/validate/", {}, format='json')
        r = self.push(self.raw1, RAP, rec)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('REJECTED', r.content.decode())
        self.assertEqual(FacturierReport.objects.filter(pk=rec['id']).count(), 1)

    def test_931_cloture_non_confirmee_du_jour_J_pas_de_double_compte_au_rejeu(self):
        rec = self.rep(total_cash_sales='3000', theoretical_cash='3000')
        self.push(self.raw1, RAP, rec)
        self.push(self.raw1, RAP, rec)
        d = self.close(self.g1, {'bills_1000': 3}).json()
        self.assertEqual(Dc(d['total_entries']), Dc('3000'))


class V932_Billetage(Base10):
    def test_932_chaine_4_acceptee_et_total(self):
        rec = self.clo(**{**{b: '0' for b in BILLS}, 'bills_500': '4', 'bills_10000': 0})
        self.push(self.raw1, CLO, rec)
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.bills_500, c.physical_cash_total), (4, Dc('2000')))

    def test_932_toutes_coupures_en_chaines_et_types_mixtes(self):
        qty = dict(zip(BILLS, ('1', 2, '3', 4, '5', 6, '7', 8)))
        rec = self.clo(**qty)
        self.push(self.raw1, CLO, rec)
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual(c.physical_cash_total, Dc(20000 + 20000 + 15000 + 4000 + 2500 + 1200 + 700 + 400))
        self.assertIsInstance(c.bills_20000, int)

    def test_932_absent_ou_vide_vaut_zero_et_rejets(self):
        rec = self.clo(bills_500='', bills_100=None)
        del rec['bills_50']
        self.push(self.raw1, CLO, rec)
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.bills_500, c.bills_100, c.bills_50), (0, 0, 0))
        bad = []
        for v in ('4.5', '-1', '１', '٣', '1e2', 'x', True, 4.5, [4], 10 ** 30, '0x4'):
            r = self.clo(bills_500=v)
            self.push(self.raw1, CLO, r)
            if self.has(CashClosure, r):
                bad.append(v)
            CashClosure.objects.all().delete()
        self.assertEqual(bad, [])

    def test_932_rejeu_cloture_idempotent_billetage_inchange(self):
        rec = self.clo(bills_500='4', bills_10000=0)
        self.push(self.raw1, CLO, rec)
        self.push(self.raw1, CLO, {**rec, 'bills_500': '9'})
        self.assertEqual(CashClosure.objects.get(pk=rec['id']).bills_500, 4)
