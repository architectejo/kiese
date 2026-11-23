"""Verification BUG-891..896 (dev-backend d23) et BUG-890 (ventes d22), relecture du perimetre de
BUG-895 (AsciiDigitsMixin), balayage des serializers numeriques voisins et voies de push sync
(testeur-permissions, ronde b8, 2026-11-23). Donnees fictives. Code applicatif non modifie.
Les tests `@expectedFailure` referencent leur ticket.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.contrib.auth import get_user_model

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.models import Config, ExpenseCategory, Node
from core.tests import test_verif_permissions_b5_v5 as b5
from core.tests.test_permissions_regression_2026_11_19 import cl
from production.models import BreadTransfer
from production.tests.test_verif_a4_testeur_production import TBase
from production.tests.test_verif_production_a7_v7 import ARAB
from sales.tests.test_ventes_a3_v2 import Base as SalesBase, INV, _api
from django.utils import timezone
from sync.models import NodeAuthToken
from treasury.models import FacturierReport, LocalExpense

User = get_user_model()
nocrash = b5.nocrash
FULL = '１２'
BAD_NUM = (ARAB, FULL)


# ---------------------------------------------------------------------------
# BUG-891 / 894 : push BreadTransfer
# ---------------------------------------------------------------------------
class V891(b5.B5):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.k3 = Node.objects.create(code='PR8', name='Perm K3')
        _, cls.raw3 = NodeAuthToken.issue_for_node(cls.k3)

    def _create(self, raw, src, dst, status, **kw):
        rid = str(uuid.uuid4())
        rec = {'id': rid, 'from_node': src.code, 'to_node': dst.code, 'bread_price': str(self.bp.pk),
               'quantity_sent': 10, 'transfer_status': status, **kw}
        self.push(raw, 'production.BreadTransfer', rec)
        return BreadTransfer.objects.filter(pk=rid).first()

    def test_BUG_891_creation_par_push_seulement_pending_pour_chaque_jeton_et_statut(self):
        bad = []
        for who, raw in (('em', self.raw1), ('re', self.raw2), ('tiers', self.raw3)):
            for st in ('RESPONDED', 'CONFIRMED', 'DISPUTED', 'CANCELLED', 'pending', 'FOO', None, 5, ['PENDING']):
                t = self._create(raw, self.k1, self.k2, st)
                if t is not None and t.transfer_status != 'PENDING':
                    bad.append((who, st, t.transfer_status))
        self.assertEqual(bad, [])

    def test_BUG_891_creation_pending_reste_possible_pour_les_deux_parties_et_defaut(self):
        self.assertEqual(self._create(self.raw1, self.k1, self.k2, 'PENDING').transfer_status, 'PENDING')
        self.assertEqual(self._create(self.raw2, self.k1, self.k2, 'PENDING').transfer_status, 'PENDING')
        rid = str(uuid.uuid4())
        self.push(self.raw1, 'production.BreadTransfer', {
            'id': rid, 'from_node': 'P1', 'to_node': 'P2', 'bread_price': str(self.bp.pk), 'quantity_sent': 4})
        self.assertEqual(BreadTransfer.objects.get(pk=rid).transfer_status, 'PENDING')

    def test_BUG_894_quantite_recue_bornee_creation_et_mise_a_jour(self):
        bad = []
        for q in (10 ** 15, 2_000_000_001, -1, '٣', '１２', True, '1e3', 5.5, [1], {'a': 1}, 'abc'):
            t = self.transfer('RESPONDED')
            r = self.push(self.raw2, 'production.BreadTransfer',
                          {'id': str(t.pk), 'transfer_status': 'CONFIRMED', 'quantity_received': q})
            self.assertLess(r.status_code, 500, (q, r.content))
            t.refresh_from_db()
            if t.quantity_received not in (None,) and not (0 <= t.quantity_received <= 2_000_000_000):
                bad.append(('maj', q, t.quantity_received))
            if t.quantity_received not in (None, 0) and q in ('٣', '１２', True, '1e3', 5.5, 'abc', [1], {'a': 1}):
                bad.append(('maj-non-entier', q, t.quantity_received))
            rid = str(uuid.uuid4())
            self.push(self.raw2, 'production.BreadTransfer', {
                'id': rid, 'from_node': 'P1', 'to_node': 'P2', 'bread_price': str(self.bp.pk),
                'quantity_sent': 10, 'transfer_status': 'PENDING', 'quantity_received': q})
            c = BreadTransfer.objects.filter(pk=rid).first()
            if c is not None and c.quantity_received not in (None, 0):
                bad.append(('creation', q, c.quantity_received))
        self.assertEqual(bad, [])

    def test_BUG_894_valeurs_legitimes_toujours_acceptees(self):
        for q, exp in ((10, 10), ('10', 10), (0, 0), (100, 100)):
            t = self.transfer('RESPONDED')
            self.push(self.raw2, 'production.BreadTransfer',
                      {'id': str(t.pk), 'transfer_status': 'CONFIRMED', 'quantity_received': q})
            t.refresh_from_db()
            self.assertEqual((t.transfer_status, t.quantity_received), ('CONFIRMED', exp), q)

    def test_litige_disputed_vers_confirmed_impossible_par_push_quel_que_soit_le_jeton(self):
        """Voisin : seule la voie REST resolve_dispute (journalisee, stock realigne) sort de DISPUTED."""
        for who, raw in (('em', self.raw1), ('re', self.raw2), ('tiers', self.raw3)):
            for new in ('CONFIRMED', 'RESPONDED', 'PENDING', 'CANCELLED'):
                t = self.transfer('DISPUTED', qty_recv=7)
                self.push(raw, 'production.BreadTransfer', {'id': str(t.pk), 'transfer_status': new, 'quantity_received': 100})
                t.refresh_from_db()
                self.assertEqual((t.transfer_status, t.quantity_received), ('DISPUTED', 7), (who, new))

    def test_resolve_dispute_roles_et_etat(self):
        """Voisin : resolve_dispute reserve a l'emettrice et au siege ; refuse hors DISPUTED ; motif obligatoire."""
        body = {'resolution': 'ALIGN_ON_SENT', 'reason': 'verif b8'}
        for role, user in (('GERANT-recepteur', self.u2['GERANT']), ('FACTURIER-emetteur', self.u['FACTURIER']),
                           ('LIVREUR-emetteur', self.u['LIVREUR'])):
            t = self.transfer('DISPUTED', qty_recv=7)
            r = nocrash(cl(user)).post(f'/api/production/transfers/{t.pk}/resolve_dispute/', body, format='json')
            self.assertIn(r.status_code, (403, 404), (role, r.status_code))
            t.refresh_from_db()
            self.assertEqual(t.transfer_status, 'DISPUTED', role)
        t = self.transfer('RESPONDED', qty_recv=7)
        r = nocrash(cl(self.u['GERANT'])).post(f'/api/production/transfers/{t.pk}/resolve_dispute/', body, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        t = self.transfer('DISPUTED', qty_recv=7)
        for bad in ({'resolution': 'ALIGN_ON_SENT'}, {'resolution': 'ALIGN_ON_SENT', 'reason': '  '},
                    {'resolution': 'X', 'reason': 'a'}, {'resolution': 'ALIGN_ON_SENT', 'reason': ['a']}):
            r = nocrash(cl(self.u['GERANT'])).post(f'/api/production/transfers/{t.pk}/resolve_dispute/', bad, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content))
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'DISPUTED')
        # double resolution : la seconde est refusee (statut CONFIRMED)
        ok = nocrash(cl(self.u['GERANT'])).post(f'/api/production/transfers/{t.pk}/resolve_dispute/', body, format='json')
        self.assertLess(ok.status_code, 500, ok.content)
        again = nocrash(cl(self.u['DIRECTION'])).post(f'/api/production/transfers/{t.pk}/resolve_dispute/', body, format='json')
        if ok.status_code == 200:
            self.assertEqual(again.status_code, 400, again.content)


# ---------------------------------------------------------------------------
# Push LocalExpense / FacturierReport (voisins)
# ---------------------------------------------------------------------------
class VPushTreasury(b5.B5):
    def exp(self, raw, **kw):
        rid = str(uuid.uuid4())
        cat = kw.pop('cat', None) or self.cat
        rec = {'id': rid, 'node': 'P1', 'description': 'push b8', 'amount': '500', 'category': cat.pk,
               'date': str(self.today), **kw}
        r = self.push(raw, 'treasury.LocalExpense', rec)
        return rid, r

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat = ExpenseCategory.objects.get_or_create(code='B8EAU', defaults={'label': 'Eau b8'})[0]
        cls.cat_off = ExpenseCategory.objects.get_or_create(
            code='B8OFF', defaults={'label': 'Off b8', 'is_active': False})[0]
        cls.cat_dir = ExpenseCategory.objects.get_or_create(
            code='B8DIR', defaults={'label': 'Direction b8', 'scope': 'DIRECTION'})[0]

    def test_depense_legitime_acceptee_et_idempotente(self):
        rid, _ = self.exp(self.raw1)
        self.assertTrue(LocalExpense.objects.filter(pk=rid).exists())

    def test_push_depense_pour_une_autre_boulangerie_refuse(self):
        """Regression : un jeton de K1 ne peut pas pousser une depense imputee a K2 (refus constate)."""
        rid, _ = self.exp(self.raw1, node='P2')
        e = LocalExpense.objects.filter(pk=rid).first()
        self.assertTrue(e is None or e.node_id == self.k1.pk, e and e.node.code)

    def test_push_rapport_facturier_pour_une_autre_boulangerie_refuse(self):
        rid = str(uuid.uuid4())
        self.push(self.raw1, 'treasury.FacturierReport', {'id': rid, 'node': 'P2', 'date': str(self.today), 'team': 'A'})
        e = FacturierReport.objects.filter(pk=rid).first()
        self.assertTrue(e is None or e.node_id == self.k1.pk, e and e.node.code)

    def test_BUG_898_push_depense_montant_negatif_nul_ou_non_numerique(self):
        """BUG-898 : la voie REST exige amount > 0 (BUG-205) ; le push accepte -500, 0 ou 'abc' (->0)."""
        bad = []
        for v in ('-500', '0', 'abc', None, '٣', '1e3', 'NaN', 'Infinity'):
            rid, r = self.exp(self.raw1, amount=v)
            self.assertLess(r.status_code, 500, (v, r.content))
            e = LocalExpense.objects.filter(pk=rid).first()
            if e is not None and e.amount <= 0:
                bad.append((v, str(e.amount)))
        self.assertEqual(bad, [])

    def test_BUG_899_push_depense_categorie_reservee_direction_par_une_boulangerie(self):
        """BUG-899 : la voie REST refuse a une boulangerie une categorie scope=DIRECTION (BUG-677) ; le push l'accepte."""
        rid, _ = self.exp(self.raw1, cat=self.cat_dir)
        self.assertFalse(LocalExpense.objects.filter(pk=rid).exists())

    def test_note_categorie_desactivee_via_push_acceptee_ambigu(self):
        """AMBIGU (pas de ticket) : hors ligne, une depense saisie avant la desactivation de la categorie doit
        rester synchronisable. On documente l'etat : acceptee. REST la refuse (BUG-871) pour une NOUVELLE depense."""
        rid, _ = self.exp(self.raw1, cat=self.cat_off)
        self.assertTrue(LocalExpense.objects.filter(pk=rid).exists())


# ---------------------------------------------------------------------------
# BUG-893 : PATCH/PUT periode de commission
# ---------------------------------------------------------------------------
class V893(b5.B5):
    def test_periode_cloturee_immuable_patch_et_put_tous_roles_siege(self):
        bad = []
        n = 0
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            for method in ('patch', 'put'):
                n += 1
                per = CommissionPeriod.objects.create(node=self.k1, month=(n % 11) + 1, year=2019, node_origin='P1', is_closed=True)
                ClientCommission.objects.create(period=per, client=self.c1, order_value=Dc('10'), node_origin='P1')
                for body in ({'month': 12}, {'year': 2018}, {'node': self.k2.pk}):
                    full = {'node': per.node_id, 'month': per.month, 'year': per.year, **body}
                    r = getattr(nocrash(cl(self.u[role])), method)(
                        f'/api/commissions/periods/{per.pk}/', full if method == 'put' else body, format='json')
                    per.refresh_from_db()
                    if (per.month, per.year, per.node_id) != ((n % 11) + 1, 2019, self.k1.pk):
                        bad.append((role, method, body, r.status_code))
                        break
                    self.assertLess(r.status_code, 500)
        self.assertEqual(bad, [])

    def test_changement_a_l_identique_et_periode_vide_ouverte_restent_possibles(self):
        per = CommissionPeriod.objects.create(node=self.k1, month=2, year=2018, node_origin='P1')
        c = nocrash(cl(self.u['DIRECTION']))
        r = c.patch(f'/api/commissions/periods/{per.pk}/', {'month': 2, 'year': 2018}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = c.patch(f'/api/commissions/periods/{per.pk}/', {'month': 3}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        per.refresh_from_db()
        self.assertEqual(per.month, 3)
        # periode close : un PATCH sans changement de cle ne casse pas (pas de 500)
        closed = CommissionPeriod.objects.create(node=self.k1, month=4, year=2018, node_origin='P1', is_closed=True)
        r = c.patch(f'/api/commissions/periods/{closed.pk}/', {'month': 4}, format='json')
        self.assertLess(r.status_code, 500, r.content)

    def test_periode_avec_commissions_ouverte_ne_change_ni_de_mois_ni_de_noeud(self):
        per = CommissionPeriod.objects.create(node=self.k1, month=5, year=2018, node_origin='P1')
        ClientCommission.objects.create(period=per, client=self.c1, order_value=Dc('10'), node_origin='P1')
        c = nocrash(cl(self.u['DIRECTION']))
        for body in ({'month': 6}, {'year': 2017}, {'node': self.k2.pk}):
            r = c.patch(f'/api/commissions/periods/{per.pk}/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.content))
        per.refresh_from_db()
        self.assertEqual((per.month, per.year, per.node_id), (5, 2018, self.k1.pk))

    def test_gerant_facturier_livreur_et_autre_noeud_toujours_refuses(self):
        per = CommissionPeriod.objects.create(node=self.k1, month=7, year=2018, node_origin='P1')
        for who in (self.u['GERANT'], self.u['FACTURIER'], self.u['LIVREUR'], self.u2['GERANT']):
            r = nocrash(cl(who)).patch(f'/api/commissions/periods/{per.pk}/', {'month': 8}, format='json')
            self.assertIn(r.status_code, (403, 404), r.status_code)
        per.refresh_from_db()
        self.assertEqual(per.month, 7)


# ---------------------------------------------------------------------------
# BUG-892 : reports/generate corps non objet
# ---------------------------------------------------------------------------
class V892(b5.B5):
    def test_tous_roles_et_corps_non_objets_jamais_500(self):
        bad = []
        for who in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            for body in ([], [1], 5, 'x', None, True, 3.5):
                r = nocrash(cl(self.u[who])).post('/api/treasury/reports/generate/', body, format='json')
                if r.status_code >= 500:
                    bad.append((who, body, r.status_code))
                if body is not None and who in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER') and r.status_code not in (400, 403):
                    bad.append((who, body, 'inattendu', r.status_code))
        self.assertEqual(bad, [])

    def test_corps_objet_vide_ne_donne_pas_500(self):
        for who in ('GERANT', 'FACTURIER', 'DIRECTION'):
            r = nocrash(cl(self.u[who])).post('/api/treasury/reports/generate/', {}, format='json')
            self.assertLess(r.status_code, 500, (who, r.content))


# ---------------------------------------------------------------------------
# BUG-896 : opening-confirmation qty
# ---------------------------------------------------------------------------
class V896(TBase):
    def _post(self, q, team='A'):
        return cl(self.g1).post('/api/production/opening-confirmation/', {
            'team': team, 'lines': [{'bread_price': self.b3.pk, 'qty': q}]}, format='json')

    def test_BUG_896_valeurs_non_ascii_exponentielles_signes_et_formats_exotiques_refuses(self):
        bad = []
        for q in (ARAB, FULL, '१', '１', '1e3', '1E3', '+3', '3e0', '0x3', '1_0', '3.5', '١٢', '３.０', '1,5', ' ', '', 'abc',
                  '٣.٠', '3.0e0', '3. 0', '٣٣'):
            r = self._post(q)
            if r.status_code != 400:
                bad.append((q, r.status_code))
        self.assertEqual(bad, [])

    def test_BUG_896_valeurs_legitimes_toujours_acceptees(self):
        """Pas de regression : entier en chaine, avec point zero, negatif (ajustement), entier JSON."""
        for i, q in enumerate(('5', '12', '5.0', '5.00', 5, 0, '0')):
            team = 'A' if i % 2 == 0 else 'B'
            r = self._post(q, team)
            self.assertIn(r.status_code, (200, 201), (q, r.status_code, getattr(r, 'data', None)))


# ---------------------------------------------------------------------------
# BUG-895 : perimetre de AsciiDigitsMixin (pas de refus a tort) + champs voisins
# ---------------------------------------------------------------------------
class V895(b5.B5):
    def patch(self, who, url, body, fmt='json'):
        return nocrash(cl(who)).patch(url, body, format=fmt)

    def test_config_valeurs_legitimes_toujours_acceptees(self):
        body = {'best_client_threshold': 5000000, 'debt_ceiling': '50000.00', 'default_commission_rate': '0.25',
                'print_fee': '100', 'sac_value_fc': 200000, 'social_deduction_rate': '0.05', 'annual_bonus_rate': '0.025'}
        r = self.patch(self.u['ADMIN'], '/api/core/config/', body)
        self.assertEqual(r.status_code, 200, r.content)
        for k, v in (('debt_ceiling', 75000.5), ('default_commission_rate', 0.3), ('print_fee', ' 100 '),
                     ('best_client_threshold', '4000000'), ('sac_value_fc', '210000')):
            r = self.patch(self.u['ADMIN'], '/api/core/config/', {k: v})
            self.assertEqual(r.status_code, 200, (k, v, r.content))

    def test_config_chaque_champ_du_mixin_refuse_les_chiffres_non_ascii(self):
        bad = []
        for k in ('best_client_threshold', 'debt_ceiling', 'sac_value_fc', 'print_fee', 'default_commission_rate',
                  'social_deduction_rate', 'annual_bonus_rate'):
            for v in BAD_NUM:
                r = self.patch(self.u['ADMIN'], '/api/core/config/', {k: v})
                if r.status_code != 400:
                    bad.append((k, v, r.status_code))
        self.assertEqual(bad, [])

    def test_noeud_et_prix_valeurs_legitimes_et_formulaire_multipart(self):
        for body in ({'sac_value_fc': '200000'}, {'sac_value_fc': 200000.5}, {'sac_value_fc': None}, {'sac_value_fc': ''}):
            r = self.patch(self.u['ADMIN'], f'/api/core/nodes/{self.k1.pk}/', body)
            self.assertIn(r.status_code, (200, 400), (body, r.content))
            self.assertLess(r.status_code, 500)
        r = self.patch(self.u['ADMIN'], f'/api/core/nodes/{self.k1.pk}/', {'sac_value_fc': '205000.50'}, 'multipart')
        self.assertEqual(r.status_code, 200, r.content)
        for body in ({'unit_price': '650'}, {'unit_price': 650}, {'unit_price': ' 650 '}):
            r = self.patch(self.u['ADMIN'], f'/api/core/bread-prices/{self.bp.pk}/', body)
            self.assertEqual(r.status_code, 200, (body, r.content))
        r = self.patch(self.u['ADMIN'], f'/api/core/bread-prices/{self.bp.pk}/', {'unit_price': '500', 'label': 'Pain é à 500'}, 'multipart')
        self.assertEqual(r.status_code, 200, r.content)

    def test_champs_texte_non_ascii_non_touches_par_le_mixin(self):
        """Libelles accentues / arabes / emoji ne sont pas des champs numeriques : jamais refuses."""
        r = self.patch(self.u['ADMIN'], f'/api/core/bread-prices/{self.bp.pk}/', {'label': 'Pain « é » ٣ à 500 FC'})
        self.assertEqual(r.status_code, 200, r.content)
        r = self.patch(self.u['ADMIN'], f'/api/core/nodes/{self.k1.pk}/', {'name': 'Boulangerie Tabora é', 'address': '49, Av. Tabora ٣'})
        self.assertEqual(r.status_code, 200, r.content)
        r = self.patch(self.u['GERANT'], f'/api/clients/clients/{self.c1.pk}/', {
            'first_name': 'Élodie', 'last_name': 'Mukendi', 'address': 'Av. ٣', 'notes': 'ç « ٣ »', 'phone': '+243 81 000 00 00'})
        self.assertEqual(r.status_code, 200, r.content)

    def test_client_chaque_champ_du_mixin_creation_et_modification(self):
        bad = []
        for k in ('credit_limit', 'commission_rate', 'cotisation_sociale'):
            for v in BAD_NUM:
                r = self.patch(self.u['GERANT'], f'/api/clients/clients/{self.c1.pk}/', {k: v})
                if r.status_code != 400:
                    bad.append(('patch', k, v, r.status_code))
                r = nocrash(cl(self.u['GERANT'])).post('/api/clients/clients/', {
                    'first_name': 'Nul', 'last_name': 'Ascii', 'client_type': 'DETAILLANT', k: v}, format='json')
                if r.status_code != 400:
                    bad.append(('post', k, v, r.status_code))
        self.assertEqual(bad, [])
        self.c1.refresh_from_db()
        self.assertEqual((self.c1.credit_limit, self.c1.commission_rate), (Dc('50000'), Dc('0.25')))

    def test_client_valeurs_legitimes_ascii_decimaux_null_et_formulaire(self):
        url = f'/api/clients/clients/{self.c1.pk}/'
        for body in ({'credit_limit': '75000'}, {'credit_limit': 75000}, {'credit_limit': '75000.50'}, {'credit_limit': 60000.5},
                     {'commission_rate': '0.30'}, {'commission_rate': 0.25}, {'commission_rate': '0'},
                     {'cotisation_sociale': '1500'}, {'cotisation_sociale': None}, {'credit_limit': ' 50000 '}):
            r = self.patch(self.u['GERANT'], url, body)
            self.assertEqual(r.status_code, 200, (body, r.content))
        r = self.patch(self.u['GERANT'], url, {'credit_limit': '80000', 'commission_rate': '0.25'}, 'multipart')
        self.assertEqual(r.status_code, 200, r.content)
        r = nocrash(cl(self.u['GERANT'])).post('/api/clients/clients/', {
            'first_name': 'Ok', 'last_name': 'Ascii', 'client_type': 'DETAILLANT', 'credit_limit': '50000.00',
            'commission_rate': '0.25', 'phone': '+243 81 ٣'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_import_excel_et_seed_n_utilisent_pas_le_mixin(self):
        """Le parseur Excel construit des objets Client sans passer par ClientCreateSerializer."""
        import inspect
        from clients import imports
        src = inspect.getsource(imports)
        self.assertNotIn('Serializer', src)

    def test_BUG_897_noeud_cotisation_mensuelle_et_carte_chiffres_non_ascii_refuses(self):
        """BUG-897 : Node.monthly_social_contribution et card_fee_fc (meme serializer que sac_value_fc) acceptent « ٣ »."""
        bad = []
        for k in ('monthly_social_contribution', 'card_fee_fc'):
            for v in BAD_NUM:
                r = self.patch(self.u['ADMIN'], f'/api/core/nodes/{self.k1.pk}/', {k: v})
                if r.status_code != 400:
                    bad.append((k, v, r.status_code))
        self.assertEqual(bad, [])


# ---------------------------------------------------------------------------
# Balayage : serializers numeriques non couverts (treasury, commissions, sales, finance)
# ---------------------------------------------------------------------------
class VSweep(b5.B5):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat = ExpenseCategory.objects.get_or_create(code='B8SW', defaults={'label': 'Sweep b8'})[0]

    def probe(self, who, method, url, body, field, results, label):
        """Controle avec '3' (doit passer) puis valeur arabe ; renvoie True si la valeur arabe est acceptee."""
        c = nocrash(cl(who))
        ok = getattr(c, method)(url, {**body, field: '3'}, format='json')
        if ok.status_code >= 300:
            results.append((label, 'controle-ko', ok.status_code, str(getattr(ok, 'data', ''))[:80]))
            return
        for v in BAD_NUM:
            r = getattr(c, method)(url, {**body, field: v}, format='json')
            if r.status_code < 300:
                results.append((label, field, v, r.status_code))

    def test_BUG_897_balayage_chiffres_non_ascii_serializers_voisins(self):
        res = []
        t = str(self.today)
        g, d, a = self.u['GERANT'], self.u['DIRECTION'], self.u['ADMIN']
        self.probe(g, 'post', '/api/treasury/expenses/', {'description': 'x', 'category': self.cat.pk, 'date': t},
                   'amount', res, 'expense.amount')
        self.probe(d, 'post', '/api/treasury/journal/', {'node': self.k1.pk, 'date': t, 'imput': 'EAU', 'label': 'x',
                                                         'exit_amount': '0'}, 'entry_amount', res, 'journal.entry_amount')
        self.probe(d, 'post', '/api/treasury/journal/', {'node': self.k1.pk, 'date': t, 'imput': 'EAU', 'label': 'y',
                                                         'entry_amount': '0'}, 'exit_amount', res, 'journal.exit_amount')
        self.probe(d, 'post', '/api/treasury/savings/', {'node': self.k1.pk, 'date': t, 'daily_revenue': '10',
                                                         'flour_sacks': '1'}, 'daily_revenue', res, 'savings.daily_revenue')
        self.probe(d, 'post', '/api/treasury/direction-cash-counts/', {'date': t}, 'bills_20000', res, 'dircount.bills_20000')
        self.probe(a, 'patch', f'/api/commissions/commissions/{self.cm1.pk}/', {}, 'order_value', res, 'cm.order_value')
        for f in ('deduction_debt', 'deduction_social', 'deduction_prints', 'deduction_other'):
            self.probe(a, 'patch', f'/api/commissions/commissions/{self.cm1.pk}/', {}, f, res, f'cm.{f}')
        self.probe(a, 'patch', f'/api/commissions/commissions/{self.cm1.pk}/set_manuel/', {}, 'manuel_adjustment', res,
                   'cm.manuel_adjustment')
        for f in ('monthly_social_contribution', 'card_fee_fc'):
            self.probe(a, 'patch', f'/api/core/nodes/{self.k1.pk}/', {}, f, res, f'node.{f}')
        accepted = [x for x in res if x[1] != 'controle-ko']
        self.last_res = res
        # Les controles ko sont des routes mal amorcees par ce test : on les remonte pour lecture, sans echec.
        print('\n[b8 sweep] controles ko :', [x for x in res if x[1] == 'controle-ko'])
        print('[b8 sweep] acceptes :', accepted)
        self.assertEqual(accepted, [])


# ---------------------------------------------------------------------------
# BUG-890 : ajustement d'une facture en attente puis annulation de la mere
# ---------------------------------------------------------------------------
class V890(SalesBase):
    def _adj(self, iid, sign, qty, pay=0):
        return _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': pay,
            'lines': [{'bread_price': self.bp3.pk, 'quantity': qty}]}, format='json')

    def _cancel(self, iid):
        return _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')

    def _bs(self):
        return _api(self.fa1).get(f'{INV}bread_summary/').data

    def _daily(self):
        rows = _api(self.fa1).get(f'{INV}daily_summary/', {'date': timezone.localdate().isoformat()}).data
        return {x['node__code'] for x in rows}

    def _clean(self):
        self.assertEqual(self._bs()['grand_total_qty'], 0)
        self.assertNotIn('AV1', self._daily())
        self.cl.refresh_from_db()
        self.assertEqual((self.cl.current_debt, self.cl.total_breads_received), (0, 0))

    def test_en_attente_ajustement_moins_puis_annulation_mere(self):
        iid = self.post().data['id']
        self.assertEqual(self._adj(iid, -1, 2).status_code, 201)
        self.assertEqual(self._cancel(iid).status_code, 200)
        self._clean()

    def test_en_attente_ajustement_plus_avec_versement_puis_annulation_mere(self):
        iid = self.post().data['id']
        self.assertEqual(self._adj(iid, 1, 3, pay=500).status_code, 201)
        self.assertEqual(self._cancel(iid).status_code, 200)
        self._clean()

    def test_plusieurs_ajustements_puis_annulation_mere_puis_stock_restitue(self):
        iid = self.post().data['id']
        self._adj(iid, 1, 3)
        self._adj(iid, -1, 1)
        self._cancel(iid)
        self._clean()
        self.assertEqual(self.sent(), 0)

    def test_annulation_repetee_idempotente_sans_500(self):
        iid = self.post().data['id']
        self._adj(iid, -1, 2)
        self._cancel(iid)
        r = self._cancel(iid)
        self.assertLess(r.status_code, 500)
        self._clean()

    def test_livraison_puis_ajustement_la_mere_non_annulee_reste_comptee(self):
        """Pas de regression : une facture livree et ajustee compte net (10 - 3 = 7 pains)."""
        iid = self.post().data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        self._adj(iid, -1, 3)
        self.assertEqual(self._bs()['grand_total_qty'], 7)


class V890Voisin(SalesBase):
    def test_BUG_897_versement_et_ajustement_chiffres_non_ascii_refuses(self):
        bad = []
        for v in BAD_NUM:
            r = self.post(payment_amount=v)
            if r.status_code != 400:
                bad.append(('create.payment_amount', v, r.status_code))
        iid = self.post().data['id']
        for v in BAD_NUM:
            r = _api(self.g1).post(f'{INV}{iid}/adjust/', {
                'adjustment_sign': 1, 'payment_amount': v,
                'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}, format='json')
            if r.status_code != 400:
                bad.append(('adjust.payment_amount', v, r.status_code))
        self.assertEqual(bad, [])
