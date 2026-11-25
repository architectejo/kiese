"""Verification BUG-886/887/888/889 (sync + commissions), BUG-871 (categorie inactive),
BUG-686/687/688 (production) et angles voisins (testeur-permissions, ronde b7, 2026-11-23).
Donnees fictives. Code applicatif non modifie. Les tests `@expectedFailure` referencent leur ticket.
"""
import re
import uuid
from datetime import date as ddate, timedelta
from decimal import Decimal as Dc


from django.contrib.auth import get_user_model
from django.urls import URLPattern, URLResolver, get_resolver

from clients.models import Client, SocialDistribution, SocialDistributionLine
from commissions.models import ClientCommission, CommissionPeriod
from core.models import ExpenseCategory, Node
from core.tests import test_verif_permissions_b5_v5 as b5
from core.tests.test_permissions_regression_2026_11_19 import cl
from production.models import BreadTransfer
from sync.models import NodeAuthToken
from treasury.models import LocalExpense
from treasury.tests import test_cycle1_tresorerie_c as tc
from production.tests.test_verif_a4_testeur_production import TBase, T
from production.tests.test_verif_production_a7_v7 import ARAB, FUT

User = get_user_model()
NIL = '00000000-0000-0000-0000-000000000000'
nocrash = b5.nocrash


# ---------------------------------------------------------------------------
# BUG-886 + balayage de toutes les routes en ecriture avec corps non objet
# ---------------------------------------------------------------------------
def _all_urls():
    def walk(patterns, prefix=''):
        for p in patterns:
            s = prefix + str(p.pattern)
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, s)
            elif isinstance(p, URLPattern):
                yield s
    seen = set()
    for raw in walk(get_resolver().url_patterns):
        if 'format' in raw:
            continue
        u = re.sub(r'\(\?P<[^>]*(?:node|code)[^>]*>[^)]*\)', 'K1', raw)
        u = re.sub(r'\(\?P<\w+>[^)]*\)', NIL, u)
        u = re.sub(r'<uuid:\w+>', NIL, u)
        u = re.sub(r'<int:\w+>', '1', u)
        u = re.sub(r'<(?:str:|slug:|path:)?\w+>', 'K1', u)
        u = u.replace('^', '').replace('$', '').replace('\\Z', '').replace('\\.', '.')
        if '(' in u or '\\' in u or '?' in u:
            continue
        if not u.startswith('/'):
            u = '/' + u
        seen.add(u)
    return sorted(seen)


EXCLUDED = ('reports/generate', 'backup', 'restore', 'reset-data', 'seed', 'import', 'logout', 'docs', 'schema', 'admin', 'media', 'static')


class V886(b5.B5):
    def test_BUG_886_reset_data_et_chat_types_variants(self):
        su = User.objects.create(username='pr7_su', role='ADMIN', is_superuser=True, is_staff=True)
        for body in ({'confirm_phrase': 3.5, 'password': 'x'}, {'confirm_phrase': True, 'password': 'x'},
                     {'confirm_phrase': {'a': 1}, 'password': 'x'}, {'confirm_phrase': 'SUPPRIMER TOUT', 'password': 3.5},
                     {'confirm_phrase': 'SUPPRIMER TOUT', 'password': {'a': 1}}, {'confirm_phrase': None, 'password': None},
                     None, 'null', 0):
            r = nocrash(cl(su)).post('/api/core/reset-data/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))
        for body in ({'user': 5}, {'user': [1]}, {'user': {'a': 1}}, {'user': None}, {'user': True}, {'user': 'x' * 300},
                     {'user': '٣'}, None, 3.5):
            r = nocrash(cl(self.u['GERANT'])).post('/api/chat/conversations/direct/', body, format='json')
            self.assertIn(r.status_code, (400, 404), (body, r.status_code))

    def test_reset_data_reste_reserve_au_superuser(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            r = nocrash(cl(self.u[role])).post('/api/core/reset-data/', {}, format='json')
            self.assertEqual(r.status_code, 403, role)
        self.assertEqual(nocrash(cl()).post('/api/core/reset-data/', {}, format='json').status_code, 401)

    def test_balayage_routes_ecriture_corps_invalides_aucun_500(self):
        admin = User.objects.create(username='pr7_adm', role='ADMIN', is_superuser=True, is_staff=True)
        c = nocrash(cl(admin))
        bad = ([], 5, 'x', {'quantity': [1], 'amount': {'a': 1}, 'node': [1], 'user': {'x': 1}, 'id': 5})
        fails = []
        for url in _all_urls():
            if any(x in url for x in EXCLUDED):
                continue
            for method in ('post', 'patch', 'put'):
                for body in bad:
                    r = getattr(c, method)(url, body, format='json')
                    if r.status_code >= 500:
                        fails.append((method, url, repr(body)[:30], r.status_code))
        self.assertEqual(fails, [])

    def test_BUG_892_treasury_reports_generate_corps_non_objet_est_400(self):
        """BUG-892 : POST /api/treasury/reports/generate/ avec un corps JSON non objet -> 500."""
        admin = User.objects.create(username='pr7_adm2', role='ADMIN', is_superuser=True, is_staff=True)
        for body in ([], 5, 'x'):
            r = nocrash(cl(admin)).post('/api/treasury/reports/generate/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))


# ---------------------------------------------------------------------------
# BUG-887 : lignes de distribution cloturee par le push de synchronisation
# ---------------------------------------------------------------------------
class V887(b5.B5):
    def test_toutes_les_colonnes_figees_sur_distribution_cloturee(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        SocialDistributionLine.objects.filter(pk=self.line1.pk).update(
            indice=2, total_social=Dc('1000'), remise=Dc('10'), merite=Dc('5'), total_payer=Dc('1015'))
        patches = {'indice': 9, 'total_social': '9', 'remise': '9', 'merite': '9', 'total_payer': '9',
                   'position': 'absent', 'form': 'virement'}
        for field, val in patches.items():
            self.push(self.raw1, 'clients.SocialDistributionLine',
                      {'id': str(self.line1.pk), 'distribution': str(self.dist1.pk), field: val})
        self.line1.refresh_from_db()
        self.assertEqual((self.line1.indice, self.line1.total_social, self.line1.remise, self.line1.merite,
                          self.line1.total_payer), (2, Dc('1000'), Dc('10'), Dc('5'), Dc('1015')))
        self.assertNotEqual(self.line1.position, 'absent')
        self.assertNotEqual(self.line1.form, 'virement')

    def test_ligne_de_distribution_ouverte_reste_modifiable(self):
        self.push(self.raw1, 'clients.SocialDistributionLine',
                  {'id': str(self.line1.pk), 'distribution': str(self.dist1.pk), 'total_social': '4321'})
        self.line1.refresh_from_db()
        self.assertEqual(self.line1.total_social, Dc('4321'))

    def test_deplacer_une_ligne_ouverte_vers_une_distribution_cloturee_ou_inversement_refuse(self):
        closed = SocialDistribution.objects.create(node=self.k1, year=2019, tarif=Dc('500'), is_closed=True,
                                                   node_origin='P1')
        self.push(self.raw1, 'clients.SocialDistributionLine',
                  {'id': str(self.line1.pk), 'distribution': str(closed.pk), 'total_social': '77'})
        self.line1.refresh_from_db()
        self.assertEqual(self.line1.distribution_id, self.dist1.pk)
        self.assertNotEqual(self.line1.total_social, Dc('77'))
        cl_line = SocialDistributionLine.objects.create(distribution=closed, client=self.c1, node_origin='P1')
        self.push(self.raw1, 'clients.SocialDistributionLine',
                  {'id': str(cl_line.pk), 'distribution': str(self.dist1.pk), 'total_social': '88'})
        cl_line.refresh_from_db()
        self.assertEqual(cl_line.distribution_id, closed.pk)
        self.assertNotEqual(cl_line.total_social, Dc('88'))

    def test_jeton_de_l_autre_noeud_ne_touche_pas_la_ligne_cloturee(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        self.push(self.raw2, 'clients.SocialDistributionLine',
                  {'id': str(self.line1.pk), 'distribution': str(self.dist1.pk), 'total_social': '5'})
        self.line1.refresh_from_db()
        self.assertNotEqual(self.line1.total_social, Dc('5'))

    def test_rest_distribution_cloturee_actions_et_tarif(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        for act in ('refresh_indices', 'auto_populate_lines'):
            for role in ('GERANT', 'DIRECTION', 'ADMIN'):
                r = nocrash(cl(self.u[role])).post(f'/api/clients/distributions/{self.dist1.pk}/{act}/', {}, format='json')
                self.assertEqual(r.status_code, 400, (act, role, r.status_code))
        tarif = self.dist1.tarif
        r = nocrash(cl(self.u['DIRECTION'])).patch(f'/api/clients/distributions/{self.dist1.pk}/',
                                                   {'tarif': '1'}, format='json')
        self.dist1.refresh_from_db()
        self.assertEqual(self.dist1.tarif, tarif, r.content)

    def test_creation_de_ligne_via_rest_dans_distribution_cloturee_par_tous_les_roles(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        c = Client.objects.create(node=self.k1, node_origin='P1', first_name='Lo', last_name='Neuf')
        for role in ('GERANT', 'DIRECTION', 'ADMIN'):
            r = nocrash(cl(self.u[role])).post('/api/clients/distribution-lines/',
                                               {'distribution': str(self.dist1.pk), 'client': str(c.pk)}, format='json')
            self.assertEqual(r.status_code, 400, (role, r.content))
        self.assertFalse(SocialDistributionLine.objects.filter(distribution=self.dist1, client=c).exists())


# ---------------------------------------------------------------------------
# BUG-888 : machine d'etats BreadTransfer par push, tous les sens
# ---------------------------------------------------------------------------
class V888(b5.B5):
    STATES = ('PENDING', 'RESPONDED', 'CONFIRMED', 'DISPUTED', 'CANCELLED')
    OK = {('em', 'PENDING', 'RESPONDED'), ('em', 'PENDING', 'CANCELLED'),
          ('re', 'RESPONDED', 'CONFIRMED'), ('re', 'RESPONDED', 'DISPUTED')}

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.k3 = Node.objects.create(code='PR3', name='Perm K3', team_rotation_enabled=False)
        _, cls.raw3 = NodeAuthToken.issue_for_node(cls.k3)

    def test_matrice_complete_jeton_x_ancien_statut_x_nouveau_statut(self):
        tokens = {'em': self.raw1, 're': self.raw2, 'tiers': self.raw3}
        bad = []
        for who, raw in tokens.items():
            for old in self.STATES:
                for new in self.STATES:
                    if old == new:
                        continue
                    t = self.transfer(old, qty_recv=None)
                    self.push(raw, 'production.BreadTransfer',
                              {'id': str(t.pk), 'transfer_status': new, 'quantity_received': 7})
                    t.refresh_from_db()
                    expected = new if (who, old, new) in self.OK else old
                    if t.transfer_status != expected:
                        bad.append((who, old, new, t.transfer_status))
                    if who != 're' and t.quantity_received is not None:
                        bad.append((who, old, new, 'qty_received', t.quantity_received))
                    t.delete()
        self.assertEqual(bad, [])

    def test_valeurs_de_statut_invalides_ni_500_ni_effet(self):
        t = self.transfer('RESPONDED')
        for v in (['DISPUTED'], {'a': 1}, 5, True, 'FOO', '', None, 'confirmed', ' CONFIRMED'):
            for raw in (self.raw1, self.raw2):
                r = self.push(raw, 'production.BreadTransfer', {'id': str(t.pk), 'transfer_status': v})
                self.assertLess(r.status_code, 500, (v, r.content))
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'RESPONDED')

    def test_quantite_recue_invalide_par_la_receptrice_pas_de_500_ni_valeur_aberrante(self):
        bad = []
        for q in (-5, 'abc', '٣', [1], 2.5):
            t = self.transfer('RESPONDED')
            r = self.push(self.raw2, 'production.BreadTransfer',
                          {'id': str(t.pk), 'transfer_status': 'CONFIRMED', 'quantity_received': q})
            self.assertLess(r.status_code, 500, (q, r.content))
            t.refresh_from_db()
            if t.quantity_received is not None and not (0 <= t.quantity_received <= 10 ** 9):
                bad.append((q, t.quantity_received))
        self.assertEqual(bad, [])

    def test_BUG_894_quantite_recue_gigantesque_par_push_refusee(self):
        """BUG-894 : le push accepte quantity_received = 10**15 (REST confirm_reception refuse > 2e9 ; PostgreSQL -> 500)."""
        t = self.transfer('RESPONDED')
        self.push(self.raw2, 'production.BreadTransfer',
                  {'id': str(t.pk), 'transfer_status': 'CONFIRMED', 'quantity_received': 10 ** 15})
        t.refresh_from_db()
        self.assertTrue(t.quantity_received is None or t.quantity_received <= 10 ** 9, t.quantity_received)

    def _create(self, raw, src, dst, status, **kw):
        rid = str(uuid.uuid4())
        rec = {'id': rid, 'from_node': src.code, 'to_node': dst.code, 'bread_price': str(self.bp.pk),
               'quantity_sent': 10, 'transfer_status': status, **kw}
        self.push(raw, 'production.BreadTransfer', rec)
        return BreadTransfer.objects.filter(pk=rid).first()

    def test_creation_par_push_pending_par_l_une_ou_l_autre_partie_reste_ok(self):
        self.assertIsNotNone(self._create(self.raw2, self.k1, self.k2, 'PENDING'))
        self.assertIsNotNone(self._create(self.raw1, self.k1, self.k2, 'PENDING'))

    def test_creation_par_un_tiers_refusee(self):
        self.assertIsNone(self._create(self.raw3, self.k1, self.k2, 'PENDING'))

    def test_BUG_891_creation_par_push_directement_en_litige_ou_annule_refusee(self):
        """BUG-891 : la creation par push accepte un statut DISPUTED/CANCELLED/CONFIRMED-equivalent arbitraire."""
        for st in ('DISPUTED', 'CANCELLED'):
            for raw, src, dst in ((self.raw1, self.k1, self.k2), (self.raw2, self.k1, self.k2)):
                t = self._create(raw, src, dst, st)
                self.assertTrue(t is None or t.transfer_status not in ('DISPUTED', 'CANCELLED'), (st, t))

    def test_BUG_891_creation_par_la_receptrice_deja_repondue_refusee(self):
        """BUG-891 : la receptrice cree un transfert RESPONDED (acte reserve a l'emettrice)."""
        t = self._create(self.raw2, self.k1, self.k2, 'RESPONDED')
        self.assertTrue(t is None or t.transfer_status != 'RESPONDED')


# ---------------------------------------------------------------------------
# BUG-889 : commissions en periode cloturee par d'autres routes
# ---------------------------------------------------------------------------
class V889(b5.B5):
    def mk(self, closed=False, month=5):
        per = CommissionPeriod.objects.create(node=self.k1, month=month, year=2025, node_origin='P1', is_closed=closed)
        cm = ClientCommission.objects.create(period=per, client=self.c1, order_value=Dc('1000'), node_origin='P1')
        return per, cm

    def newc(self, n):
        return Client.objects.create(node=self.k1, node_origin='P1', first_name=f'Cm{n}', last_name='Test')

    def test_post_periode_cloturee_refuse_pour_tous_les_roles_siege(self):
        per, _ = self.mk(closed=True)
        for i, role in enumerate(('ADMIN', 'DIRECTION', 'COMPTABLE')):
            c = self.newc(i)
            r = nocrash(cl(self.u[role])).post('/api/commissions/commissions/',
                                               {'period': str(per.pk), 'client': str(c.pk), 'order_value': '1'}, format='json')
            self.assertEqual(r.status_code, 400, (role, r.content))
            self.assertFalse(ClientCommission.objects.filter(period=per, client=c).exists())

    def test_post_periode_ouverte_toujours_ok_et_gerant_refuse(self):
        per, _ = self.mk()
        r = nocrash(cl(self.u['DIRECTION'])).post('/api/commissions/commissions/',
                                                  {'period': str(per.pk), 'client': str(self.newc(1).pk), 'order_value': '1'},
                                                  format='json')
        self.assertEqual(r.status_code, 201, r.content)
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            r = nocrash(cl(self.u[role])).post('/api/commissions/commissions/',
                                               {'period': str(per.pk), 'client': str(self.newc(2).pk)}, format='json')
            self.assertEqual(r.status_code, 403, role)

    def test_deplacement_d_une_commission_ouverte_vers_une_periode_cloturee_refuse(self):
        """Voisin de BUG-889 : PATCH/PUT {'period': <cloturee>} ne deplace pas une commission dans une periode close."""
        closed, _ = self.mk(closed=True, month=4)
        for method in ('patch', 'put'):
            _, cm = self.mk(month=6 if method == 'patch' else 7)
            body = {'period': str(closed.pk)} if method == 'patch' else {
                'period': str(closed.pk), 'client': str(cm.client_id), 'order_value': '1000'}
            r = getattr(nocrash(cl(self.u['DIRECTION'])), method)(f'/api/commissions/commissions/{cm.pk}/', body, format='json')
            cm.refresh_from_db()
            self.assertNotEqual(cm.period_id, closed.pk, (method, r.status_code, r.content))

    def test_BUG_893_periode_cloturee_ne_change_pas_de_mois_ni_d_annee(self):
        """BUG-893 : PATCH month/year d'une periode cloturee (le gel BUG-263 ne couvre que delete)."""
        per, _ = self.mk(closed=True, month=3)
        r = nocrash(cl(self.u['DIRECTION'])).patch(f'/api/commissions/periods/{per.pk}/',
                                                   {'month': 1, 'year': 2020}, format='json')
        per.refresh_from_db()
        self.assertEqual((per.month, per.year), (3, 2025), r.content)

    def test_periode_cloturee_ne_se_rouvre_pas(self):
        per, _ = self.mk(closed=True, month=2)
        r = nocrash(cl(self.u['DIRECTION'])).patch(f'/api/commissions/periods/{per.pk}/',
                                                   {'is_closed': False}, format='json')
        per.refresh_from_db()
        self.assertTrue(per.is_closed, r.content)

    def test_BUG_893_periode_avec_commissions_ne_change_pas_de_boulangerie(self):
        """BUG-893 : PATCH node d'une periode (cloturee ou non) portant des commissions : les commissions changent de boulangerie."""
        per, cm = self.mk(closed=True, month=2)
        nocrash(cl(self.u['DIRECTION'])).patch(f'/api/commissions/periods/{per.pk}/', {'node': self.k2.pk}, format='json')
        per.refresh_from_db()
        self.assertEqual(per.node_id, self.k1.pk)

    def test_generate_sur_periode_cloturee_et_doublon_de_periode_sans_500(self):
        per, _ = self.mk(closed=True, month=8)
        r = nocrash(cl(self.u['DIRECTION'])).post('/api/commissions/periods/generate/',
                                                  {'node': self.k1.pk, 'month': 8, 'year': 2025}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = nocrash(cl(self.u['DIRECTION'])).post('/api/commissions/periods/',
                                                  {'node': self.k1.pk, 'month': 8, 'year': 2025}, format='json')
        self.assertLess(r.status_code, 500, r.content)

    def test_set_manuel_et_suppression_en_periode_cloturee_refuses(self):
        per, cm = self.mk(closed=True, month=9)
        c = nocrash(cl(self.u['DIRECTION']))
        self.assertEqual(c.patch(f'/api/commissions/commissions/{cm.pk}/set_manuel/',
                                 {'manuel_adjustment': '5'}, format='json').status_code, 400)
        self.assertEqual(c.delete(f'/api/commissions/commissions/{cm.pk}/').status_code, 400)
        cm.refresh_from_db()
        self.assertIsNone(cm.manuel_adjustment)


# ---------------------------------------------------------------------------
# BUG-871 : categorie de depense inactive
# ---------------------------------------------------------------------------
class V871(tc.Base):
    def post(self, user, cat, amount='500'):
        return tc.cl(user).post('/api/treasury/expenses/', {
            'description': 'x', 'amount': amount, 'category': cat.id, 'date': str(tc.today())}, format='json')

    def setUp(self):
        self.off = ExpenseCategory.objects.create(code='OFFX', label='Off', scope='BAKERY')
        self.on = ExpenseCategory.objects.create(code='ONX', label='On', scope='BAKERY')

    def test_inactive_refusee_pour_tous_les_roles_ecrivains(self):
        ExpenseCategory.objects.filter(pk=self.off.pk).update(is_active=False)
        for user in (self.g1, self.dirn, self.adm):
            r = self.post(user, self.off)
            self.assertEqual(r.status_code, 400, (user.role, r.content))
        self.assertFalse(LocalExpense.objects.filter(category=self.off).exists())
        for user in (self.fac, self.liv, self.compt):
            self.assertIn(self.post(user, self.off).status_code, (400, 403))

    def test_active_acceptee_et_reactivation_rend_la_categorie_utilisable(self):
        self.assertEqual(self.post(self.g1, self.on).status_code, 201)
        ExpenseCategory.objects.filter(pk=self.off.pk).update(is_active=False)
        self.assertEqual(self.post(self.g1, self.off).status_code, 400)
        ExpenseCategory.objects.filter(pk=self.off.pk).update(is_active=True)
        self.assertEqual(self.post(self.g1, self.off).status_code, 201)

    def test_depense_existante_garde_sa_categorie_desactivee_mais_ne_bascule_pas_vers_une_autre_inactive(self):
        e = self.post(self.g1, self.off).json()
        ExpenseCategory.objects.filter(pk__in=[self.off.pk]).update(is_active=False)
        url = f"/api/treasury/expenses/{e['id']}/"
        self.assertEqual(tc.cl(self.g1).patch(url, {'amount': '700'}, format='json').status_code, 200)
        self.assertEqual(tc.cl(self.g1).patch(url, {'category': self.off.id}, format='json').status_code, 200)
        ExpenseCategory.objects.filter(pk=self.on.pk).update(is_active=False)
        r = tc.cl(self.g1).patch(url, {'category': self.on.id}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(LocalExpense.objects.get(pk=e['id']).category_id, self.off.pk)

    def test_put_vers_categorie_inactive_refuse(self):
        e = self.post(self.g1, self.on).json()
        ExpenseCategory.objects.filter(pk=self.off.pk).update(is_active=False)
        r = tc.cl(self.g1).put(f"/api/treasury/expenses/{e['id']}/", {
            'description': 'x', 'amount': '500', 'category': self.off.id, 'date': str(tc.today())}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_les_categories_inactives_restent_lisibles_et_les_depenses_existantes_listees(self):
        e = self.post(self.g1, self.off).json()
        ExpenseCategory.objects.filter(pk=self.off.pk).update(is_active=False)
        r = tc.cl(self.g1).get(f"/api/treasury/expenses/{e['id']}/")
        self.assertEqual(r.status_code, 200)

    def test_push_sync_depense_hors_ligne_categorie_inactive_observation(self):
        """Observation (sans ticket) : une depense saisie hors ligne avant la desactivation reste synchronisable."""
        from sync.models import NodeAuthToken as NT
        ExpenseCategory.objects.filter(pk=self.off.pk).update(is_active=False)
        _, raw = NT.issue_for_node(self.n1)
        c = nocrash(__import__('rest_framework.test', fromlist=['APIClient']).APIClient())
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
        r = c.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()), 'records': {'treasury.LocalExpense': [
            {'id': str(uuid.uuid4()), 'category': self.off.id, 'amount': '10', 'date': str(tc.today()),
             'description': 'hors ligne'}]}}, format='json')
        self.assertLess(r.status_code, 500)


# ---------------------------------------------------------------------------
# BUG-686/687/688 + voisins production
# ---------------------------------------------------------------------------
class VProd(TBase):
    maxDiff = None

    def test_respond_et_confirm_chiffres_non_ascii_refuses_sans_effet(self):
        t = self.request([self.L(self.b3, 10)])
        for q in (ARAB, '１２', '१'):
            r = self.respond(t, [self.L(self.b3, q)])
            self.assertEqual(r.status_code, 400, (q, r.content))
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')
        self.assertEqual(self.stock(self.k1, self.b3), 100)
        self.assertEqual(self.respond(t, [self.L(self.b3, 10)]).status_code, 200)
        for q in (ARAB, '１２'):
            r = self.confirm(t, [self.L(self.b3, q, 'quantity_received')])
            self.assertEqual(r.status_code, 400, (q, r.content))
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'RESPONDED')

    def test_demande_de_transfert_quantite_non_ascii_refusee(self):
        r = cl(self.g2).post(T, {'from_node': self.k1.pk, 'lines': [self.L(self.b3, ARAB)]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_opening_confirmation_quantites_non_ascii_flottantes_ou_geantes(self):
        from production.models import DailyOpeningConfirmation
        before = DailyOpeningConfirmation.objects.count()
        bad = []
        for q in (1.5, -3, 10 ** 15, True, None, [1]):
            r = cl(self.g1).post('/api/production/opening-confirmation/', {
                'team': 'A', 'lines': [{'bread_price': self.b3.pk, 'qty': q}]}, format='json')
            if r.status_code != 400:
                bad.append((q, r.status_code))
        self.assertEqual(bad, [])
        self.assertEqual(DailyOpeningConfirmation.objects.count(), before)

    def test_BUG_896_opening_confirmation_chiffres_non_ascii_et_notation_exponentielle_refuses(self):
        """BUG-896 : qty « ٣ », « １２ » ou « 1e3 » acceptee (stock de depart ajuste), comme BUG-686 sur les autres champs."""
        bad = []
        for q in (ARAB, '１２', '1e3'):
            r = cl(self.g1).post('/api/production/opening-confirmation/', {
                'team': 'A', 'lines': [{'bread_price': self.b3.pk, 'qty': q}]}, format='json')
            if r.status_code != 400:
                bad.append((q, r.status_code))
        self.assertEqual(bad, [])

    def test_opening_confirmation_dates_futures_proches_et_lointaines(self):
        for n in (1, 2, 400):
            r = cl(self.g1).post('/api/production/opening-confirmation/', {
                'date': FUT(n), 'team': 'A', 'lines': [{'bread_price': self.b3.pk, 'qty': 5}]}, format='json')
            self.assertEqual(r.status_code, 400, (n, r.content))
        for bad in ('2026-13-45', 'x', 5, ['2026-01-01'], '٢٠٢٦-١١-٢٣'):
            r = cl(self.g1).post('/api/production/opening-confirmation/', {
                'date': bad, 'team': 'A', 'lines': [{'bread_price': self.b3.pk, 'qty': 5}]}, format='json')
            self.assertLess(r.status_code, 500, (bad, r.status_code))

    def test_mouvement_quantite_ou_prix_negatif_ou_non_fini(self):
        from production.models import ConsumableStock
        s = ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')[0]
        bad = []
        # BUG-216 (REJETE, decision client) : quantites negatives/nulles autorisees sur un mouvement -> non testees.
        for k, v in (('quantity', 'NaN'), ('unit_price', 'Infinity'), ('quantity', 'Infinity'), ('unit_price', 'NaN'),
                     ('quantity', '٣'), ('unit_price', '１２')):
            body = {'stock': s.pk, 'movement_type': 'ENTRY', 'quantity': '3', 'unit_price': '100', k: v}
            r = cl(self.g1).post('/api/production/movements/', body, format='json')
            if r.status_code != 400:
                bad.append((k, v, r.status_code))
        self.assertEqual(bad, [])

    def test_comptage_ne_force_pas_la_quantite_systeme_et_rejette_les_extremes(self):
        from production.models import ConsumableStock
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='FLOUR')
        r = cl(self.g1).post('/api/production/counts/', {
            'consumable_type': 'FLOUR', 'count_date': str(ddate.today()), 'physical_quantity': '2',
            'system_quantity': '999', 'gap': '5'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertNotEqual(Dc(str(r.data['system_quantity'])), Dc('999'))
        self.assertNotEqual(Dc(str(r.data['gap'])), Dc('5'))
        for q in ('NaN', 'Infinity', '-0.001', '99999999999', '1e400'):
            r = cl(self.g1).post('/api/production/counts/', {
                'consumable_type': 'FLOUR', 'count_date': str(ddate.today()), 'physical_quantity': q}, format='json')
            self.assertEqual(r.status_code, 400, (q, r.status_code, r.content))

    def test_comptage_gerant_autre_noeud_et_date_future_via_node_force(self):
        from production.models import ConsumableStock
        ConsumableStock.objects.get_or_create(node=self.k2, consumable_type='FLOUR')
        r = cl(self.dir).post('/api/production/counts/', {
            'node': self.k2.pk, 'consumable_type': 'FLOUR', 'count_date': FUT(5), 'physical_quantity': '1'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = cl(self.g1).post('/api/production/counts/', {
            'node': self.k2.pk, 'consumable_type': 'FLOUR', 'count_date': str(ddate.today()),
            'physical_quantity': '1'}, format='json')
        self.assertIn(r.status_code, (400, 403, 404, 201), r.content)
        from production.models import ConsumableCount
        self.assertFalse(ConsumableCount.objects.filter(node=self.k2).exists() and r.status_code == 201
                         and ConsumableCount.objects.filter(node=self.k2, counted_by=self.g1).exists())

    def test_disposal_prix_negatif_ou_non_ascii_en_patch_aussi(self):
        from production.models import BreadDisposal, ProductionSession
        ses = ProductionSession.objects.create(node=self.k1, date=ddate.today() - timedelta(days=1), team='B',
                                               flour_sacks_used=Dc('1'))
        r = cl(self.g1).post('/api/production/disposals/', {
            'session': str(ses.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD', 'quantity': 3,
            'unit_price_sold': '100'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        did = r.data['id']
        for v in (ARAB, '-5', 'NaN'):
            rr = cl(self.g1).patch(f'/api/production/disposals/{did}/', {'unit_price_sold': v}, format='json')
            self.assertEqual(rr.status_code, 400, (v, rr.status_code, rr.content))
        for v in ('-5', ARAB):
            rr = cl(self.g1).post('/api/production/disposals/', {
                'session': str(ses.pk), 'bread_price': self.b5.pk, 'disposal_type': 'UNSOLD', 'quantity': v}, format='json')
            self.assertEqual(rr.status_code, 400, (v, rr.status_code, rr.content))
        self.assertEqual(BreadDisposal.objects.get(pk=did).unit_price_sold, Dc('100'))

    def test_BUG_895_prix_valeur_sac_seuil_et_plafond_chiffres_non_ascii_refuses(self):
        """BUG-895 : « ٣ » accepte (=3) sur BreadPrice.unit_price, Node.sac_value_fc, Config.best_client_threshold, Client.credit_limit."""
        from clients.models import Client as C
        c = C.objects.create(node=self.k1, node_origin='Q1', first_name='Zz', last_name='Ar')
        bad = []
        for label, who, url, body in (
                ('bread-price', self.adm, f'/api/core/bread-prices/{self.b3.pk}/', {'unit_price': ARAB}),
                ('node.sac', self.adm, f'/api/core/nodes/{self.k1.pk}/', {'sac_value_fc': ARAB}),
                ('config', self.adm, '/api/core/config/', {'best_client_threshold': ARAB}),
                ('credit_limit', self.g1, f'/api/clients/clients/{c.pk}/', {'credit_limit': ARAB})):
            r = cl(who).patch(url, body, format='json')
            if r.status_code != 400:
                bad.append((label, r.status_code))
        self.assertEqual(bad, [])

    def test_configuration_chiffres_negatifs(self):
        bad = []
        for v in ('-5',):
            r = cl(self.adm).patch(f'/api/core/bread-prices/{self.b3.pk}/', {'unit_price': v}, format='json')
            if r.status_code != 400:
                bad.append(('bread-price', v, r.status_code))
            r = cl(self.adm).patch(f'/api/core/nodes/{self.k1.pk}/', {'sac_value_fc': v}, format='json')
            if r.status_code != 400:
                bad.append(('node.sac', v, r.status_code))
            r = cl(self.adm).patch('/api/core/config/', {'best_client_threshold': v}, format='json')
            if r.status_code != 400:
                bad.append(('config.threshold', v, r.status_code))
        self.assertEqual(bad, [])

    def test_credit_limit_negatif_refuse(self):
        from clients.models import Client as C
        c = C.objects.create(node=self.k1, node_origin='Q1', first_name='Zz', last_name='Plaf')
        bad = []
        for v in ('-5', 'NaN'):
            r = cl(self.g1).patch(f'/api/clients/clients/{c.pk}/', {'credit_limit': v}, format='json')
            if r.status_code != 400:
                bad.append((v, r.status_code))
        self.assertEqual(bad, [])
        c.refresh_from_db()
        self.assertEqual(c.credit_limit, Dc('50000'))


class V686_688(TBase):
    """Re-verification independante de BUG-686/687/688 (production, Dev B d20)."""

    def _stock(self, node=None):
        from production.models import ConsumableStock
        return ConsumableStock.objects.get_or_create(node=node or self.k1, consumable_type='FLOUR')[0]

    def test_686_comptage_inventaire_dispatch_chiffres_non_ascii(self):
        from production.consumables_direction import siege_node
        from production.models import ConsumableCount
        self._stock()
        for v in (ARAB, '１２', '१'):
            r = cl(self.g1).post('/api/production/counts/', {'consumable_type': 'FLOUR', 'count_date': str(ddate.today()),
                                                              'physical_quantity': v}, format='json')
            self.assertEqual(r.status_code, 400, ('count', v, r.content))
            r = cl(self.g1).post('/api/production/inventories/',
                                 {'lines': [{'consumable_type': 'FLOUR', 'physical_quantity': v}]}, format='json')
            self.assertEqual(r.status_code, 400, ('inventory', v, r.content))
        sg = self._stock(siege_node())
        cl(self.dir).post('/api/production/movements/', {'stock': sg.pk, 'movement_type': 'ENTRY', 'quantity': '10',
                                                          'unit_price': '100'}, format='json')
        before = ConsumableCount.objects.count()
        for v in (ARAB, '１２'):
            r = cl(self.dir).post('/api/production/consumables/dispatch/', {
                'consumable_type': 'FLOUR', 'allocations': [{'node': self.k1.pk, 'quantity': v}]}, format='json')
            self.assertEqual(r.status_code, 400, ('dispatch', v, r.content))
        self.assertEqual(ConsumableCount.objects.count(), before)

    def test_686_ascii_valide_inchange(self):
        self._stock()
        r = cl(self.g1).post('/api/production/counts/', {'consumable_type': 'FLOUR', 'count_date': str(ddate.today()),
                                                          'physical_quantity': '2.5'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        m = cl(self.g1).post('/api/production/movements/', {'stock': self._stock().pk, 'movement_type': 'ENTRY',
                                                              'quantity': '3', 'unit_price': '100,5'}, format='json')
        self.assertLess(m.status_code, 500)

    def test_687_count_date_future_post_patch_put_et_passe_ok(self):
        self._stock()
        base = {'consumable_type': 'FLOUR', 'physical_quantity': '2'}
        for n in (1, 2, 30):
            r = cl(self.g1).post('/api/production/counts/', dict(base, count_date=FUT(n)), format='json')
            self.assertEqual(r.status_code, 400, (n, r.content))
        r = cl(self.g1).post('/api/production/counts/', dict(base, count_date=str(ddate.today())), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.data['id']
        self.assertEqual(cl(self.g1).patch(f'/api/production/counts/{cid}/', {'count_date': FUT(3)}, format='json').status_code, 400)
        r = cl(self.g1).put(f'/api/production/counts/{cid}/', dict(base, count_date=FUT(3)), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        past = str(ddate.today() - timedelta(days=3))
        self.assertEqual(cl(self.g1).patch(f'/api/production/counts/{cid}/', {'count_date': past}, format='json').status_code, 200)

    def test_688_physique_negative_post_patch_put_et_zero_ok(self):
        self._stock()
        base = {'consumable_type': 'FLOUR', 'count_date': str(ddate.today())}
        for v in ('-0.001', '-5', -1):
            r = cl(self.g1).post('/api/production/counts/', dict(base, physical_quantity=v), format='json')
            self.assertEqual(r.status_code, 400, (v, r.content))
        r = cl(self.g1).post('/api/production/counts/', dict(base, physical_quantity='0'), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.data['id']
        self.assertEqual(cl(self.g1).patch(f'/api/production/counts/{cid}/', {'physical_quantity': '-1'}, format='json').status_code, 400)
        self.assertEqual(cl(self.g1).put(f'/api/production/counts/{cid}/', dict(base, physical_quantity='-1'), format='json').status_code, 400)

    def test_isolation_comptage_autre_noeud(self):
        self._stock(self.k2)
        r = cl(self.g1).post('/api/production/counts/', {'node': self.k2.pk, 'consumable_type': 'FLOUR',
                                                          'count_date': str(ddate.today()), 'physical_quantity': '1'}, format='json')
        from production.models import ConsumableCount
        self.assertFalse(ConsumableCount.objects.filter(node=self.k2).exists(), r.content)
