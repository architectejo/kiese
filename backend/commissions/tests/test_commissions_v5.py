"""
Commissions - ronde b18 (testeur clients/commissions, 2026-11-23). Verification independante de BUG-1005
(retenue unique a created_at egal) et balayage final : CM, retenues, remise, net, listing de paie, periode close,
mark_paid, permissions croisees. Valeurs calculees a la main. Donnees FICTIVES. Code applicatif non modifie.
Formules en vigueur = code valide par le client (BUG-058/291/292/295), pas la lettre de CLAUDE.md 5.3.
"""
import itertools
import uuid
from datetime import datetime, timezone as dt_tz
from decimal import Decimal as D
from unittest import expectedFailure
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine

GEN = '/api/commissions/periods/generate/'
COMM = '/api/commissions/commissions/'
PERIODS = '/api/commissions/periods/'


def api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


class Base5(TestCase):
    def setUp(self):
        self.ns = [make_node(code=c, social=D('1500'), card_fee=D('700')) for c in ('Y1', 'Y2', 'Y3')]
        self.p500 = make_bread_price('GRAND', 'Pain 500 FC', 500)
        self.direction = make_user('DIRECTION', node=None, team='')
        self.comptable = make_user('COMPTABLE', node=None, team='')
        self.g1 = make_user('GERANT', node=self.ns[0], team='')
        self.f1 = make_user('FACTURIER', node=self.ns[0], team='A')
        self.l1 = make_user('LIVREUR', node=self.ns[0], team='A')

    def inv(self, node, client, qty, **flags):
        i = Invoice.objects.create(node=node, client=client, payment_type='CREDIT', status='DELIVERED',
                                   payment_amount=D('0'), invoice_date='2026-02-10', node_origin=node.code, **flags)
        InvoiceLine.objects.create(invoice=i, bread_price=self.p500, quantity=qty)
        i.compute_order_total()
        i.save(update_fields=['order_total'])
        return i

    def gen(self, node, user=None, expect=201):
        r = api(user or self.direction).post(GEN, {'node': node.pk, 'month': 2, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, expect, getattr(r, 'data', None))
        return r

    def period(self, node):
        return CommissionPeriod.objects.get(node=node, month=2, year=2026)

    def row(self, node, c):
        return ClientCommission.objects.get(period__node=node, period__month=2, client=c)


# ---------------------------------------------------------------------------
# 1. BUG-1005 : horloge grossiere, tous les ordres
# ---------------------------------------------------------------------------
class RetenueUniqueHorlogeGrossiere(Base5):
    FIXED = datetime(2026, 2, 20, 12, 0, 0, tzinfo=dt_tz.utc)

    def setUp(self):
        super().setUp()
        self.c = make_client(self.ns[2], current_debt=D('10000'))
        for n in self.ns:
            self.inv(n, self.c, 100)

    def assert_une_seule_retenue(self):
        rows = list(ClientCommission.objects.filter(client=self.c))
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(r.deduction_debt for r in rows), D('10000.00'))
        self.assertEqual(sum(r.deduction_social for r in rows), D('1500.00'))
        self.assertEqual(sum(1 for r in rows if r.deduction_debt != 0), 1)
        for r in rows:  # carte propre a chaque boulangerie
            self.assertEqual(r.deduction_prints, D('700.00'))
            self.assertEqual(r.commission_gross, D('12500.00'))  # 100 x 500 x 0,25 par boulangerie
        return rows

    def test_sequentiel_six_ordres_created_at_egal(self):
        for order in itertools.permutations(self.ns):
            ClientCommission.objects.all().delete()
            CommissionPeriod.objects.all().delete()
            with patch('django.utils.timezone.now', return_value=self.FIXED):
                for n in order:
                    self.gen(n)
            rows = self.assert_une_seule_retenue()
            winner = [r for r in rows if r.deduction_debt != 0][0]
            self.assertEqual(winner.period.node_id, order[0].pk, [n.code for n in order])

    def test_imbrique_six_ordres_et_trois_attributions_d_uuid(self):
        mgr_cls = type(ClientCommission.objects)
        real = mgr_cls.get_or_create
        patterns = {
            'asc': [0, 1, 2], 'desc': [2, 1, 0], 'mixte': [1, 2, 0],
        }
        for chain in itertools.permutations(self.ns):
            for name, ranks in patterns.items():
                ClientCommission.objects.all().delete()
                CommissionPeriod.objects.all().delete()
                ids = {n.pk: uuid.UUID(int=(ranks[i] + 1) << 120) for i, n in enumerate(chain)}
                done = set()

                def hook(mgr, *a, **kw):
                    if mgr.model is ClientCommission and kw.get('period') is not None:
                        nid = kw['period'].node_id
                        pos = [n.pk for n in chain].index(nid)
                        if pos + 1 < len(chain) and pos not in done:
                            done.add(pos)
                            self.gen(chain[pos + 1])
                        kw['defaults'] = dict(kw.get('defaults') or {}, id=ids[nid])
                    return real(mgr, *a, **kw)

                with patch.object(mgr_cls, 'get_or_create', hook), \
                        patch('django.utils.timezone.now', return_value=self.FIXED):
                    self.gen(chain[0])
                label = ([n.code for n in chain], name)
                rows = ClientCommission.objects.filter(client=self.c)
                self.assertEqual(len({r.created_at for r in rows}), 1, label)
                self.assert_une_seule_retenue()

    def test_deux_clients_independants_chacun_une_retenue(self):
        c2 = make_client(self.ns[0], current_debt=D('4000'))
        for n in self.ns:
            self.inv(n, c2, 10)
        with patch('django.utils.timezone.now', return_value=self.FIXED):
            for n in self.ns:
                self.gen(n)
        for c, debt in ((self.c, D('10000.00')), (c2, D('4000.00'))):
            rows = ClientCommission.objects.filter(client=c)
            self.assertEqual(sum(r.deduction_debt for r in rows), debt)
            self.assertEqual(sum(r.deduction_social for r in rows), D('1500.00'))

    def test_regeneration_ne_double_ni_ne_deplace_la_retenue(self):
        with patch('django.utils.timezone.now', return_value=self.FIXED):
            for n in self.ns:
                self.gen(n)
        for n in reversed(self.ns):
            self.gen(n)
        self.assert_une_seule_retenue()

    def test_deux_lignes_a_zero_ex_aequo_etat_limite_documente(self):
        """Etat que produirait un double renoncement (generations strictement simultanees) : aucune ligne ne
        retient. Une regeneration ne le repare pas (retenues manuelles conservees) : acceptable seulement parce
        que (a) PostgreSQL verrouille le client (select_for_update, BUG-782) et (b) SQLite serialise les
        ecritures ; l'etat reste visible dans le listing (retenue 0) et modifiable a la main (PATCH)."""
        with patch('django.utils.timezone.now', return_value=self.FIXED):
            self.gen(self.ns[0])
            self.gen(self.ns[1])
        # BUG-1014 : un zero decide par la comptabilite passe par PATCH (pose deduction_manual).
        for x in ClientCommission.objects.filter(client=self.c):
            rz = api(self.comptable).patch(f'{COMM}{x.id}/', {'deduction_debt': '0', 'deduction_social': '0'}, format='json')
            self.assertEqual(rz.status_code, 200, getattr(rz, 'data', None))
        self.gen(self.ns[0])
        r = self.row(self.ns[0], self.c)
        self.assertEqual(r.deduction_debt, D('0.00'))  # conserve tel quel
        # Reparation manuelle possible par la comptabilite.
        resp = api(self.comptable).patch(f'{COMM}{r.id}/', {'deduction_debt': '10000'}, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', None))
        r.refresh_from_db()
        self.assertEqual(r.deduction_debt, D('10000.00'))

    def test_BUG_1009_suppression_de_la_ligne_qui_retient_perd_la_retenue_sans_alerte(self):
        for n in self.ns:
            self.gen(n)
        winner = ClientCommission.objects.get(client=self.c, deduction_debt=D('10000.00'))
        r = api(self.direction).delete(f'{COMM}{winner.id}/')
        self.assertEqual(r.status_code, 204, getattr(r, 'data', None))
        for n in self.ns:
            self.gen(n)  # regeneration de toutes les boulangeries
        rows = ClientCommission.objects.filter(client=self.c)
        # La dette BP du client (10 000) doit rester retenue une fois ; sinon elle est perdue en silence.
        self.assertEqual(sum(x.deduction_debt for x in rows), D('10000.00'),
                         "retenue de dette perdue : aucune ligne restante ne retient, aucune alerte")


# ---------------------------------------------------------------------------
# 2. Balayage final : formules a la main
# ---------------------------------------------------------------------------
class Formules(Base5):
    def test_cm_025_retenues_net_remise(self):
        n = self.ns[0]
        c = make_client(n, current_debt=D('10000'))
        self.inv(n, c, 100)  # 50 000
        self.gen(n)
        r = self.row(n, c)
        self.assertEqual(r.order_value, D('50000.00'))
        self.assertEqual(r.commission_gross, D('12500.00'))
        self.assertEqual((r.deduction_debt, r.deduction_social, r.deduction_prints, r.deduction_other),
                         (D('10000.00'), D('1500.00'), D('700.00'), D('0.00')))
        self.assertEqual(r.total_deductions, D('12200.00'))
        self.assertEqual(r.net_payable, D('300.00'))
        self.assertEqual(r.deduction_remise, D('125.00'))  # 0,25 % de 50 000 : affichee, non deduite
        self.assertEqual(r.annual_bonus, D('0.00'))
        for f in ('order_value', 'commission_gross', 'total_deductions', 'net_payable', 'deduction_remise'):
            self.assertIsInstance(getattr(r, f), D, f)

    def test_cm_030_et_autre_retenue(self):
        n = self.ns[1]
        c = make_client(n, commission_rate=D('0.30'))
        self.inv(n, c, 200)  # 100 000
        self.gen(n)
        r = self.row(n, c)
        resp = api(self.comptable).patch(f'{COMM}{r.id}/', {'deduction_other': '2500'}, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', None))
        r.refresh_from_db()
        self.assertEqual(r.commission_gross, D('30000.00'))
        self.assertEqual(r.total_deductions, D('4700.00'))  # 0 + 1500 + 700 + 2500
        self.assertEqual(r.net_payable, D('25300.00'))

    def test_net_negatif_non_payable_puis_reporte(self):
        n = self.ns[0]
        c = make_client(n, current_debt=D('20000'))
        self.inv(n, c, 100)
        self.gen(n)
        r = self.row(n, c)
        self.assertEqual(r.net_payable, D('-9700.00'))  # 12500 - 20000 - 1500 - 700
        resp = api(self.direction).post(f'{COMM}{r.id}/mark_paid/', {}, format='json')
        self.assertEqual(resp.status_code, 400)
        r.refresh_from_db()
        self.assertFalse(r.is_paid)

    def test_vente_solde_commande_exoneree_et_epargne_aucune_commission(self):
        n = self.ns[0]
        solde, exo, epargne = (make_client(n), make_client(n), make_client(n, current_debt=D('-8000')))
        self.inv(n, solde, 50, is_soldee=True)
        self.inv(n, exo, 50, commission_exempt=True)
        self.inv(n, epargne, 0)
        self.gen(n)
        self.assertFalse(ClientCommission.objects.filter(client__in=[solde, exo, epargne]).exists())

    def test_totaux_verticaux_summary_et_listing_exacts(self):
        n = self.ns[0]
        cs = [make_client(n, current_debt=D(d)) for d in ('1000', '2000', '0')]
        for c, q in zip(cs, (10, 20, 40)):
            self.inv(n, c, q)
        self.gen(n)
        p = self.period(n)
        s = api(self.comptable).get(COMM + 'summary/', {'period': str(p.id)}).data
        # commandes 5000 + 10000 + 20000 ; CM 1250 + 2500 + 5000 ; BP 3000 ; social 3 x 1500 ; cartes 3 x 700
        # (SQLite renvoie les sommes sans zeros de fin : comparaison numerique exacte en Decimal.)
        self.assertEqual((D(s['total_orders']), D(s['total_cm']), D(s['total_debt'])), (D('35000'), D('8750'), D('3000')))
        self.assertEqual((D(s['total_cotisation']), D(s['total_carte']), s['count']), (D('4500'), D('2100'), 3))
        self.assertEqual(D(s['total_deductions']), D('9600'))
        self.assertEqual(D(s['total_net']), D('-850'))  # 8750 - 9600
        lst = api(self.comptable).get(COMM + 'payroll_listing/', {'period': str(p.id)}).data
        self.assertEqual(len(lst), 3)
        self.assertEqual(sum(D(x['net_payable']) for x in lst), D('-850.00'))

    def test_periode_close_gele_generation_edition_suppression_et_mark_paid_reste_dans_les_regles(self):
        n = self.ns[0]
        c = make_client(n)
        self.inv(n, c, 100)
        self.gen(n)
        p, r = self.period(n), self.row(n, c)
        self.assertEqual(api(self.direction).post(f'{PERIODS}{p.id}/close_period/').status_code, 200)
        self.assertEqual(api(self.direction).post(f'{PERIODS}{p.id}/close_period/').status_code, 400)
        self.gen(n, expect=400)
        self.assertEqual(api(self.comptable).patch(f'{COMM}{r.id}/', {'deduction_other': '1'}, format='json').status_code, 400)
        self.assertEqual(api(self.comptable).delete(f'{COMM}{r.id}/').status_code, 400)
        self.assertEqual(api(self.direction).patch(f'{COMM}{r.id}/set_manuel/', {'manuel_adjustment': '1'},
                                                   format='json').status_code, 400)
        self.assertEqual(api(self.direction).delete(f'{PERIODS}{p.id}/').status_code, 400)
        r.refresh_from_db()
        self.assertEqual(r.deduction_other, D('0.00'))

    def test_mark_paid_une_fois_puis_gele_et_regeneration_n_ecrase_pas(self):
        n = self.ns[0]
        c = make_client(n)
        self.inv(n, c, 100)
        self.gen(n)
        r = self.row(n, c)
        self.assertEqual(r.net_payable, D('10300.00'))  # 12500 - 1500 - 700
        self.assertEqual(api(self.direction).post(f'{COMM}{r.id}/mark_paid/', {}, format='json').status_code, 200)
        self.assertEqual(api(self.direction).post(f'{COMM}{r.id}/mark_paid/', {}, format='json').status_code, 400)
        self.inv(n, c, 100)
        self.gen(n)
        r.refresh_from_db()
        self.assertEqual((r.order_value, r.net_payable, r.is_paid), (D('50000.00'), D('10300.00'), True))

    def test_mark_paid_concurrence_simulee_une_seule_ecriture(self):
        n = self.ns[0]
        c = make_client(n)
        self.inv(n, c, 100)
        self.gen(n)
        r = self.row(n, c)
        codes = [api(self.direction).post(f'{COMM}{r.id}/mark_paid/', {}, format='json').status_code for _ in range(3)]
        self.assertEqual(sorted(codes), [200, 400, 400])


# ---------------------------------------------------------------------------
# 3. Permissions croisees
# ---------------------------------------------------------------------------
class PermissionsCroisees(Base5):
    def setUp(self):
        super().setUp()
        n = self.ns[0]
        self.c = make_client(n)
        self.inv(n, self.c, 100)
        self.gen(n)
        self.r = self.row(n, self.c)
        self.p = self.period(n)
        self.g2 = make_user('GERANT', node=self.ns[1], team='')

    def test_facturier_et_livreur_refuses_partout(self):
        for u in (self.f1, self.l1):
            cl = api(u)
            self.assertEqual(cl.get(COMM).status_code, 403)
            self.assertEqual(cl.get(COMM + 'summary/').status_code, 403)
            self.assertEqual(cl.post(GEN, {'node': self.ns[0].pk, 'month': 2, 'year': 2026}, format='json').status_code, 403)
            self.assertEqual(cl.post(f'{COMM}{self.r.id}/mark_paid/', {}, format='json').status_code, 403)
            self.assertEqual(cl.patch(f'{COMM}{self.r.id}/set_manuel/', {'manuel_adjustment': '1'}, format='json').status_code, 403)
            self.assertEqual(cl.get(COMM + 'payroll_listing/', {'period': str(self.p.id)}).status_code, 403)

    def test_gerant_lit_son_noeud_seulement_et_ne_paie_ni_ne_genere_ni_ajuste(self):
        self.assertEqual(api(self.g1).get(f'{COMM}{self.r.id}/').status_code, 200)
        self.assertEqual(api(self.g2).get(f'{COMM}{self.r.id}/').status_code, 404)
        self.assertEqual(api(self.g2).get(COMM + 'summary/').data['count'], 0)
        for g in (self.g1, self.g2):
            cl = api(g)
            self.assertEqual(cl.post(GEN, {'node': self.ns[0].pk, 'month': 2, 'year': 2026}, format='json').status_code, 403)
            self.assertEqual(cl.post(f'{COMM}{self.r.id}/mark_paid/', {}, format='json').status_code, 403)
            self.assertEqual(cl.patch(f'{COMM}{self.r.id}/set_manuel/', {'manuel_adjustment': '1'}, format='json').status_code, 403)
            self.assertEqual(cl.patch(f'{COMM}{self.r.id}/', {'deduction_other': '9'}, format='json').status_code, 403)
            self.assertEqual(cl.post(f'{PERIODS}{self.p.id}/close_period/').status_code, 403)
        self.r.refresh_from_db()
        self.assertEqual((self.r.deduction_other, self.r.is_paid), (D('0.00'), False))

    def test_comptable_edite_mais_ne_paie_pas_ni_ne_fixe_manuel(self):
        cl = api(self.comptable)
        self.assertEqual(cl.patch(f'{COMM}{self.r.id}/', {'deduction_other': '10'}, format='json').status_code, 200)
        self.assertEqual(cl.post(f'{COMM}{self.r.id}/mark_paid/', {}, format='json').status_code, 403)
        self.assertEqual(cl.patch(f'{COMM}{self.r.id}/set_manuel/', {'manuel_adjustment': '1'}, format='json').status_code, 403)

    def test_anonyme_401(self):
        cl = APIClient()
        self.assertEqual(cl.get(COMM).status_code, 401)
        self.assertEqual(cl.post(GEN, {}, format='json').status_code, 401)


# ---------------------------------------------------------------------------
# 4. Throttling du login
# ---------------------------------------------------------------------------
class ThrottlingLogin(TestCase):
    URL = '/api/core/auth/login/'

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.u = make_user('GERANT', node=make_node(code='TH1'), team='', username='thr_user')
        make_user('GERANT', node=None, team='', username='thr_autre')

    def post(self, username, password='mauvais'):
        return APIClient().post(self.URL, {'username': username, 'password': password}, format='json')

    def test_sixieme_tentative_bloquee_meme_avec_le_bon_mot_de_passe(self):
        for _ in range(5):
            self.assertEqual(self.post('thr_user').status_code, 401)
        self.assertEqual(self.post('thr_user', 'test-pass-123').status_code, 429)

    def test_variantes_de_casse_et_d_espaces_partagent_le_compteur(self):
        for name in ('thr_user', 'THR_USER', ' thr_user ', 'Thr_User', 'thr_user'):
            self.assertEqual(self.post(name).status_code, 401)
        self.assertEqual(self.post('THR_user ').status_code, 429)

    def test_un_compte_bloque_n_en_bloque_pas_un_autre(self):
        for _ in range(6):
            self.post('thr_user')
        self.assertEqual(self.post('thr_autre', 'test-pass-123').status_code, 200)

    def test_reponse_429_sans_fuite_de_secret(self):
        for _ in range(5):
            self.post('thr_user')
        r = self.post('thr_user', 'secret-xyz-123')
        self.assertEqual(r.status_code, 429)
        self.assertNotIn('secret-xyz-123', r.content.decode())
