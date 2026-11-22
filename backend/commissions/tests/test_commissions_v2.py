"""Commissions - ronde v2 (testeur Clients/Commissions, 2026-11-22-b2).

Valeurs calculées à la main dans chaque test. Angles : BUG-417 (cotisation et
carte par boulangerie, totaux verticaux `summary`, `periods/history`,
commissions déjà générées inchangées), paramètres invalides, isolation par
nœud, clients épargne / VENTE SOLDE, double retenue d'un client facturé dans
deux boulangeries, Decimal exact, idempotence. Données FICTIVES.
"""
from decimal import Decimal as D
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.models import Config, Node
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine

GEN = '/api/commissions/periods/generate/'
PERIODS = '/api/commissions/periods/'
COMM = '/api/commissions/commissions/'


def api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


def rows(resp):
    d = resp.data
    return d['results'] if isinstance(d, dict) and 'results' in d else d


class Base(TestCase):
    def setUp(self):
        self.n1 = make_node(code='QA1', social=D('2000'), card_fee=D('1000'))
        self.n3 = make_node(code='QA3', social=D('1500'), card_fee=D('700'))
        self.p500 = make_bread_price('GRAND', 'Pain 500 FC', 500)
        self.direction = make_user('DIRECTION', node=None, team='')
        self.comptable = make_user('COMPTABLE', node=None, team='')
        self.g1 = make_user('GERANT', node=self.n1, team='')
        self.g3 = make_user('GERANT', node=self.n3, team='')
        self.f1 = make_user('FACTURIER', node=self.n1, team='A')
        self.l1 = make_user('LIVREUR', node=self.n1, team='A')

    def invoice(self, node, client, qty=0, month=2, year=2026, day=10, price=None, status='DELIVERED',
                payment=D('0'), **flags):
        inv = Invoice.objects.create(
            node=node, client=client, payment_type='CREDIT', status=status,
            payment_amount=payment, invoice_date=f'{year}-{month:02d}-{day:02d}', node_origin=node.code, **flags)
        if qty:
            InvoiceLine.objects.create(invoice=inv, bread_price=price or self.p500, quantity=qty)
            inv.compute_order_total()
            inv.save(update_fields=['order_total'])
        return inv

    def generate(self, node, month=2, year=2026, user=None):
        r = api(user or self.comptable).post(GEN, {'node': node.pk, 'month': month, 'year': year}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return CommissionPeriod.objects.get(node=node, month=month, year=year)

    def row(self, period, client):
        return ClientCommission.objects.get(period=period, client=client)


# --------------------------------------------------------------------------
# Formules (calculs à la main)
# --------------------------------------------------------------------------
class FormulesTests(Base):
    def test_cm_030_toutes_retenues_net_a_la_main(self):
        c = make_client(self.n1, commission_rate=D('0.30'), current_debt=D('5000'))
        self.invoice(self.n1, c, 320)        # 320 x 500 = 160 000
        r = self.row(self.generate(self.n1), c)
        self.assertEqual(r.order_value, D('160000.00'))
        self.assertEqual(r.commission_gross, D('48000.00'))      # 160 000 x 0,30
        self.assertEqual((r.deduction_debt, r.deduction_social, r.deduction_prints), (D('5000.00'), D('2000.00'), D('1000.00')))
        resp = api(self.comptable).patch(f'{COMM}{r.id}/', {'deduction_other': '500'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        r.refresh_from_db()
        # retenues = 5 000 + 2 000 + 1 000 + 500 = 8 500 ; net = 48 000 - 8 500
        self.assertEqual(r.total_deductions, D('8500.00'))
        self.assertEqual(r.net_payable, D('39500.00'))
        self.assertEqual(r.deduction_remise, D('400.00'))         # 0,25 % de la commande, affichée seulement
        self.assertEqual(r.annual_bonus, D('0.00'))
        self.assertEqual(r.deduction_carte, D('0.00'))            # pas de double retenue de la carte
        self.assertEqual(resp.data['net_payable'], '39500.00')

    def test_cm_025_avec_defauts_2000_1000_sans_dette(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 200)        # 100 000
        r = self.row(self.generate(self.n1), c)
        self.assertEqual(r.commission_gross, D('25000.00'))
        self.assertEqual(r.net_payable, D('22000.00'))            # 25 000 - 2 000 - 1 000

    def test_decimal_exact_sans_derive_flottante(self):
        p333 = make_bread_price('MOYEN', 'Pain 333 FC', 333)
        c = make_client(self.n1, commission_rate=D('0.25'))
        self.invoice(self.n1, c, 7, price=p333)                    # 2 331 FC
        r = self.row(self.generate(self.n1), c)
        self.assertEqual(r.commission_gross, D('582.75'))          # 2 331 x 0,25
        self.assertEqual(r.net_payable, D('582.75') - D('3000.00'))
        self.assertIsInstance(r.commission_gross, D)
        d = api(self.g1).get(f'{COMM}{r.id}/').data
        for k in ('order_value', 'commission_gross', 'net_payable', 'total_deductions', 'deduction_remise'):
            self.assertIsInstance(d[k], str, k)
        self.assertEqual(d['net_payable'], '-2417.25')

    def test_agregation_de_plusieurs_factures_du_mois_et_bornes_de_mois(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 10, day=1)        # 5 000
        self.invoice(self.n1, c, 20, day=28)       # 10 000
        self.invoice(self.n1, c, 99, month=3, day=1)   # hors période
        self.invoice(self.n1, c, 99, month=1, day=31)  # hors période
        self.invoice(self.n1, c, 99, year=2025)        # autre année
        r = self.row(self.generate(self.n1), c)
        self.assertEqual((r.order_value, r.total_breads), (D('15000.00'), 30))
        self.assertEqual(r.commission_gross, D('3750.00'))

    def test_factures_non_eligibles_exclues_de_la_base(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 10)                                   # 5 000 : seule éligible
        self.invoice(self.n1, c, 50, status='PENDING_DELIVERY' if hasattr(Invoice.Status, 'PENDING_DELIVERY') else 'PENDING')
        self.invoice(self.n1, c, 50, is_soldee=True)                   # VENTE SOLDE / CASH
        self.invoice(self.n1, c, 50, commission_exempt=True)
        self.invoice(self.n1, c, 50, special_code='RG')
        self.invoice(self.n1, c, 50, commission_rate=D('0'))
        r = self.row(self.generate(self.n1), c)
        self.assertEqual(r.order_value, D('5000.00'))
        self.assertEqual(r.commission_gross, D('1250.00'))

    def test_vente_solde_cash_seule_ne_cree_aucune_ligne_et_cm_zero(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 80, is_soldee=True)
        p = self.generate(self.n1)
        self.assertFalse(ClientCommission.objects.filter(period=p, client=c).exists())

    def test_client_epargne_depot_sans_commande_aucune_cm_ni_net(self):
        c = make_client(self.n1, current_debt=D('-30000'))
        self.invoice(self.n1, c, 0, payment=D('30000'))          # dépôt : commande = 0
        p = self.generate(self.n1)
        self.assertEqual(ClientCommission.objects.filter(period=p).count(), 0)
        c.refresh_from_db()
        self.assertEqual(c.current_debt, D('-30000.00'))

    def test_remboursement_de_bp_n_est_pas_une_vente(self):
        c = make_client(self.n1, current_debt=D('10000'))
        self.invoice(self.n1, c, 0, payment=D('10000'), is_debt_repayment=True)
        self.assertEqual(ClientCommission.objects.filter(period=self.generate(self.n1)).count(), 0)

    def test_vente_occasionnelle_sans_client_ignoree(self):
        self.invoice(self.n1, None, 10)
        self.assertEqual(ClientCommission.objects.filter(period=self.generate(self.n1)).count(), 0)

    @expectedFailure   # BUG-738
    def test_taux_de_la_facture_pris_en_compte_quand_le_taux_client_change_en_cours_de_mois(self):
        """Une facture à 0,25 (50 000) et une à 0,30 (50 000) : CM attendue 12 500 + 15 000 = 27 500.
        Le code applique le taux courant du client à toute la base (BUG-738)."""
        c = make_client(self.n1, commission_rate=D('0.30'))
        self.invoice(self.n1, c, 100, commission_rate=D('0.25'))
        self.invoice(self.n1, c, 100, commission_rate=D('0.30'))
        r = self.row(self.generate(self.n1), c)
        self.assertEqual(r.commission_gross, D('27500.00'))


# --------------------------------------------------------------------------
# BUG-417 : cotisation / carte par boulangerie, commissions déjà générées
# --------------------------------------------------------------------------
class Bug417Tests(Base):
    def test_valeurs_propres_a_chaque_boulangerie_et_client_personnalise(self):
        a = make_client(self.n1)
        b = make_client(self.n3)
        perso = make_client(self.n3)
        Client.objects.filter(pk=perso.pk).update(cotisation_sociale=D('0'))     # exempté de cotisation
        for cl, n in ((a, self.n1), (b, self.n3), (perso, self.n3)):
            self.invoice(n, cl, 100)                                              # 50 000 -> CM 12 500
        p1, p3 = self.generate(self.n1), self.generate(self.n3)
        ra, rb, rp = self.row(p1, a), self.row(p3, b), self.row(p3, perso)
        self.assertEqual((ra.deduction_social, ra.deduction_prints, ra.net_payable), (D('2000'), D('1000'), D('9500.00')))
        self.assertEqual((rb.deduction_social, rb.deduction_prints, rb.net_payable), (D('1500'), D('700'), D('10300.00')))
        self.assertEqual((rp.deduction_social, rp.deduction_prints, rp.net_payable), (D('0'), D('700'), D('11800.00')))

    def test_changer_cotisation_ou_carte_ne_modifie_pas_les_commissions_deja_generees(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        p = self.generate(self.n1)
        before = self.row(p, c)
        self.n1.monthly_social_contribution = D('9999')
        self.n1.card_fee_fc = D('8888')
        self.n1.save()
        p = self.generate(self.n1)                                                # re-génération (rafraîchit les factures)
        after = self.row(p, c)
        self.assertEqual((after.deduction_social, after.deduction_prints), (D('2000.00'), D('1000.00')))
        self.assertEqual(after.net_payable, before.net_payable)
        self.assertEqual(after.total_deductions, before.total_deductions)
        # un nouveau client de la même période prend les nouveaux montants
        d = make_client(self.n1)
        self.invoice(self.n1, d, 100)
        p = self.generate(self.n1)
        new = self.row(p, d)
        self.assertEqual((new.deduction_social, new.deduction_prints), (D('9999.00'), D('8888.00')))
        self.assertEqual(self.row(p, c).deduction_social, D('2000.00'))

    def test_changer_la_carte_via_api_node_ne_touche_pas_l_historique(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        p = self.generate(self.n1)
        r = api(self.direction).patch(f'/api/core/nodes/{self.n1.pk}/', {'card_fee_fc': '4321'}, format='json')
        self.assertIn(r.status_code, (200, 404), r.data)
        self.assertEqual(self.row(p, c).deduction_prints, D('1000.00'))

    def test_summary_totaux_verticaux_exacts(self):
        cs = [make_client(self.n1, commission_rate=D('0.25'), current_debt=D('4000')),
              make_client(self.n1, commission_rate=D('0.30')),
              make_client(self.n1)]
        for cl, q in zip(cs, (100, 200, 40)):
            self.invoice(self.n1, cl, q)                    # 50 000 ; 100 000 ; 20 000
        p = self.generate(self.n1)
        r = api(self.comptable).get(COMM + 'summary/', {'period': str(p.id)})
        self.assertEqual(r.status_code, 200, r.data)
        # CM : 12 500 + 30 000 + 5 000 = 47 500
        # retenues : dette 4 000 ; cotisation 3 x 2 000 ; carte 3 x 1 000 ; total = 4 000 + 6 000 + 3 000
        # net : 47 500 - 13 000 = 34 500
        self.assertEqual(r.data['count'], 3)
        expected = {'total_orders': '170000', 'total_cm': '47500', 'total_debt': '4000',
                    'total_cotisation': '6000', 'total_carte': '3000', 'total_other': '0',
                    'total_deductions': '13000', 'total_net': '34500'}
        for k, v in expected.items():
            self.assertIsInstance(r.data[k], str, k)          # jamais un float
            self.assertEqual(D(r.data[k]), D(v), k)
        # cohérence avec la somme des lignes de la liste
        lines = rows(api(self.comptable).get(COMM, {'period': str(p.id)}))
        self.assertEqual(sum(D(x['net_payable']) for x in lines), D('34500.00'))
        self.assertEqual(sum(D(x['cotisation_sociale_fc']) for x in lines), D('6000.00'))
        self.assertEqual(sum(D(x['carte_fc']) for x in lines), D('3000.00'))

    def test_summary_suit_une_modification_de_retenue(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        p = self.generate(self.n1)
        r0 = self.row(p, c)
        api(self.comptable).patch(f'{COMM}{r0.id}/', {'deduction_prints': '2500', 'deduction_other': '300'}, format='json')
        s = api(self.comptable).get(COMM + 'summary/', {'period': str(p.id)}).data
        self.assertEqual((D(s['total_carte']), D(s['total_other'])), (D('2500'), D('300')))
        self.assertEqual(D(s['total_net']), D('7700'))          # 12 500 - 2 000 - 2 500 - 300

    def test_summary_vide_donne_des_zeros_decimaux(self):
        s = api(self.comptable).get(COMM + 'summary/').data
        self.assertEqual(s['count'], 0)
        for k in ('total_orders', 'total_cm', 'total_debt', 'total_cotisation', 'total_carte',
                  'total_other', 'total_deductions', 'total_net'):
            self.assertEqual(D(s[k]), D('0'), k)

    def test_summary_isolation_permissions_et_filtres_invalides(self):
        c1, c3 = make_client(self.n1), make_client(self.n3)
        self.invoice(self.n1, c1, 100)
        self.invoice(self.n3, c3, 100)
        self.generate(self.n1)
        self.generate(self.n3)
        self.assertEqual(api(self.g1).get(COMM + 'summary/').data['count'], 1)
        self.assertEqual(api(self.g1).get(COMM + 'summary/', {'period__node': self.n3.pk}).data['count'], 0)
        self.assertEqual(api(self.direction).get(COMM + 'summary/').data['count'], 2)
        self.assertEqual(D(api(self.direction).get(COMM + 'summary/', {'period__node': self.n3.pk}).data['total_carte']), D('700'))
        for u in (self.f1, self.l1):
            self.assertEqual(api(u).get(COMM + 'summary/').status_code, 403)
        self.assertIn(APIClient().get(COMM + 'summary/').status_code, (401, 403))
        for params in ({'period': 'pas-uuid'}, {'period__node': 'abc'}, {'period__month': 'abc'},
                       {'period__year': 'abc'}):
            with self.subTest(params=params):
                self.assertEqual(api(self.direction).get(COMM + 'summary/', params).status_code, 400, params)

    def test_summary_gerant_sans_noeud_zero(self):
        orphan = make_user('GERANT', node=None, team='')
        make_client(self.n1)
        self.assertEqual(api(orphan).get(COMM + 'summary/').data['count'], 0)

    def test_history_totaux_cotisation_carte_et_encaissements(self):
        a, b = make_client(self.n1), make_client(self.n1)
        self.invoice(self.n1, a, 100, payment=D('20000'))
        self.invoice(self.n1, b, 100, payment=D('5000.50'))
        self.invoice(self.n1, b, 0, payment=D('999'), status='NOT_SERVED')       # versement conservé (BUG-320)
        self.invoice(self.n3, a, 100, payment=D('77777'))                         # autre boulangerie : exclu
        self.generate(self.n1)
        r = api(self.direction).get(PERIODS + 'history/', {'node': self.n1.pk})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data), 1)
        h = r.data[0]
        self.assertEqual((h['client_count'], D(h['total_cotisation']), D(h['total_carte'])), (2, D('4000'), D('2000')))
        self.assertEqual(D(h['total_cm']), D('25000'))
        self.assertEqual(D(h['total_net']), D('19000'))   # 25 000 - 4 000 - 2 000
        self.assertEqual(D(h['total_payments']), D('25999.50'))
        self.assertEqual(D(h['total_paid']), D('0'))

    def test_history_parametres_invalides_et_isolation(self):
        c = make_client(self.n3)
        self.invoice(self.n3, c, 10)
        self.generate(self.n3)
        for params in ({'node': 'abc'}, {'node': '9' * 30}, {'months': 'abc'}, {'months': '0'}, {'months': '-3'},
                       {'months': '1e3'}, {'months': ''}):
            with self.subTest(params=params):
                r = api(self.direction).get(PERIODS + 'history/', params)
                self.assertEqual(r.status_code, 400, (params, r.status_code))
        self.assertEqual(api(self.direction).get(PERIODS + 'history/', {'months': '99999'}).status_code, 200)
        self.assertEqual(api(self.direction).get(PERIODS + 'history/', {'node': self.n1.pk}).data, [])
        self.assertEqual(len(api(self.direction).get(PERIODS + 'history/', {'node': self.n3.pk}).data), 1)
        # action reservee au siege (get_permissions l'emporte sur le decorateur IsGerant)
        for u in (self.g1, self.g3, self.f1, self.l1):
            self.assertEqual(api(u).get(PERIODS + 'history/').status_code, 403)


# --------------------------------------------------------------------------
# Paramètres invalides
# --------------------------------------------------------------------------
class ParametresInvalidesTests(Base):
    def test_generate_corps_invalide_400_pas_500(self):
        # BUG-736 (corrige dans l'arbre de travail par un autre agent) : test de non-regression.
        for payload in ({'node': self.n1.pk, 'month': 13, 'year': 2026},
                        {'node': self.n1.pk, 'month': 0, 'year': 2026},
                        {'node': self.n1.pk, 'month': 'abc', 'year': 2026},
                        {'node': self.n1.pk, 'month': 2, 'year': 'abc'},
                        {'node': self.n1.pk, 'month': 2, 'year': -1},
                        {'node': self.n1.pk, 'month': 2, 'year': 99999999999999999999},
                        {'node': 'abc', 'month': 2, 'year': 2026},
                        {'node': '9' * 30, 'month': 2, 'year': 2026},
                        {'node': self.n1.pk, 'month': 2.5, 'year': 2026},
                        {'node': [1], 'month': 2, 'year': 2026}):
            with self.subTest(payload=payload):
                r = api(self.comptable).post(GEN, payload, format='json')
                self.assertEqual(r.status_code, 400, (payload, r.status_code))
                CommissionPeriod.objects.all().delete()

    def test_generate_reserve_au_siege_et_non_authentifie(self):
        for u in (self.g1, self.f1, self.l1):
            self.assertEqual(api(u).post(GEN, {'node': self.n1.pk, 'month': 2, 'year': 2026}, format='json').status_code, 403)
        self.assertIn(APIClient().post(GEN, {}, format='json').status_code, (401, 403))

    def test_payroll_listing_period_non_uuid_400(self):
        url = COMM + 'payroll_listing/'
        for bad in ('pas-uuid', '123', "x' OR 1=1", '9' * 50):
            with self.subTest(bad=bad):
                self.assertEqual(api(self.direction).get(url, {'period': bad}).status_code, 400)

    def test_payroll_listing_parametres_et_isolation(self):
        c = make_client(self.n3)
        self.invoice(self.n3, c, 10)
        p = self.generate(self.n3)
        url = COMM + 'payroll_listing/'
        self.assertEqual(api(self.direction).get(url).status_code, 400)
        self.assertEqual(len(api(self.direction).get(url, {'period': str(p.id)}).data), 1)
        self.assertEqual(len(api(self.comptable).get(url, {'period': str(p.id)}).data), 1)
        for u in (self.f1, self.l1):
            self.assertEqual(api(u).get(url, {'period': str(p.id)}).status_code, 403)

    @expectedFailure   # BUG-705 : le decorateur IsGerant est sans effet, le gerant recoit 403
    def test_gerant_lit_le_listing_de_paie_et_l_historique_de_son_noeud(self):
        c = make_client(self.n3)
        self.invoice(self.n3, c, 10)
        p = self.generate(self.n3)
        self.assertEqual(api(self.g3).get(COMM + 'payroll_listing/', {'period': str(p.id)}).status_code, 200)
        self.assertEqual(api(self.g3).get(PERIODS + 'history/').status_code, 200)
        # isolation : le gerant de QA1 ne voit pas la paie de QA3
        r = api(self.g1).get(COMM + 'payroll_listing/', {'period': str(p.id)})
        self.assertEqual((r.status_code, r.data), (200, []))

    def test_liste_commissions_filtres_et_pagination(self):
        for q in ('abc', '0', '-1', ''):
            self.assertEqual(api(self.direction).get(COMM, {'page_size': q}).status_code, 200, q)
        self.assertEqual(api(self.direction).get(COMM, {'page': 'abc'}).status_code, 404)
        for params in ({'period': 'x'}, {'client': 'x'}, {'period__year': 'x'}):
            with self.subTest(params=params):
                self.assertEqual(api(self.direction).get(COMM, params).status_code, 400, params)

    def test_periods_liste_filtres_invalides(self):
        for params in ({'node': 'x'}, {'month': 'x'}, {'year': 'x'}):
            with self.subTest(params=params):
                self.assertEqual(api(self.direction).get(PERIODS, params).status_code, 400, params)

    def test_set_manuel_valeurs_non_finies_refusees(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        r = self.row(self.generate(self.n1), c)
        for bad in ('NaN', 'Infinity', '-Infinity', 'abc', '1e400', '12345678901234567890'):
            with self.subTest(bad=bad):
                resp = api(self.direction).patch(f'{COMM}{r.id}/set_manuel/', {'manuel_adjustment': bad}, format='json')
                self.assertEqual(resp.status_code, 400, (bad, resp.status_code))
                ClientCommission.objects.filter(pk=r.pk).update(manuel_adjustment=None)
        r.refresh_from_db()
        self.assertEqual(r.net_payable, D('9500.00'))
        self.assertIsNone(r.manuel_adjustment)

    def test_set_manuel_direction_seule_et_net_remplace(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        r = self.row(self.generate(self.n1), c)
        for u in (self.g1, self.comptable, self.f1):
            self.assertEqual(api(u).patch(f'{COMM}{r.id}/set_manuel/', {'manuel_adjustment': '1'}, format='json').status_code, 403)
        resp = api(self.direction).patch(f'{COMM}{r.id}/set_manuel/', {'manuel_adjustment': '8000.25', 'manuel_notes': 'x'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['net_payable'], '8000.25')
        resp = api(self.direction).patch(f'{COMM}{r.id}/set_manuel/', {'manuel_adjustment': None}, format='json')
        self.assertEqual(resp.data['net_payable'], '9500.00')

    def test_edition_valeurs_hors_borne_refusees(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        r = self.row(self.generate(self.n1), c)
        for bad in ({'order_value': '-1'}, {'deduction_other': '-5'},
                    {'commission_rate': '0.31'}, {'commission_rate': '-0.01'},
                    {'order_value': '1' + '0' * 14}, {'total_breads': -1}):
            resp = api(self.comptable).patch(f'{COMM}{r.id}/', bad, format='json')
            self.assertEqual(resp.status_code, 400, (bad, resp.status_code))
        r.refresh_from_db()
        self.assertEqual(r.net_payable, D('9500.00'))

    def test_edition_recalcule_cm_avec_taux_030_a_la_main(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        r = self.row(self.generate(self.n1), c)
        resp = api(self.comptable).patch(f'{COMM}{r.id}/', {'commission_rate': '0.30'}, format='json')
        self.assertEqual(resp.status_code, 200)
        r.refresh_from_db()
        self.assertEqual(r.commission_gross, D('15000.00'))
        self.assertEqual(r.net_payable, D('12000.00'))

    def test_creation_manuelle_doublon_periode_client_refusee(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        p = self.generate(self.n1)
        resp = api(self.comptable).post(COMM, {'period': str(p.id), 'client': str(c.id), 'order_value': '10000'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ClientCommission.objects.filter(period=p).count(), 1)

    def test_modification_interdite_gerant_et_facturier(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        r = self.row(self.generate(self.n1), c)
        for u in (self.g1, self.f1, self.l1):
            self.assertEqual(api(u).patch(f'{COMM}{r.id}/', {'deduction_other': '1'}, format='json').status_code, 403)
            self.assertEqual(api(u).delete(f'{COMM}{r.id}/').status_code, 403)


# --------------------------------------------------------------------------
# Net négatif, report, paiement
# --------------------------------------------------------------------------
class NetNegatifEtReportTests(Base):
    def test_petit_client_net_negatif_non_payable_puis_report_mois_suivant(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 4)                             # 2 000 -> CM 500
        r2 = self.row(self.generate(self.n1, month=2), c)
        self.assertEqual(r2.commission_gross, D('500.00'))
        self.assertEqual(r2.net_payable, D('-2500.00'))          # 500 - 2 000 - 1 000
        resp = api(self.direction).post(f'{COMM}{r2.id}/mark_paid/')
        self.assertEqual(resp.status_code, 400)
        self.invoice(self.n1, c, 100, month=3)                  # 50 000 -> CM 12 500
        r3 = self.row(self.generate(self.n1, month=3), c)
        self.assertEqual(r3.carried_debt_in, D('2500.00'))
        # 12 500 - 2 000 - 1 000 - 2 500 (report) = 7 000
        self.assertEqual(r3.net_payable, D('7000.00'))
        self.assertEqual(r3.total_deductions, D('5500.00'))

    def test_bp_credit_client_ajoute_au_net_sans_double_retenue_dans_summary(self):
        c = make_client(self.n1, current_debt=D('-1000'))
        self.invoice(self.n1, c, 100)
        p = self.generate(self.n1)
        r = self.row(p, c)
        # net/ordi = 12 500 - (-1 000) = 13 500 ; - 2 000 - 1 000 = 10 500
        self.assertEqual(r.net_payable, D('10500.00'))
        s = api(self.comptable).get(COMM + 'summary/', {'period': str(p.id)}).data
        self.assertEqual(D(s['total_net']), r.net_payable)

    def test_mark_paid_direction_seule_et_une_seule_fois(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        r = self.row(self.generate(self.n1), c)
        for u in (self.g1, self.comptable, self.f1):
            self.assertEqual(api(u).post(f'{COMM}{r.id}/mark_paid/').status_code, 403)
        self.assertEqual(api(self.direction).post(f'{COMM}{r.id}/mark_paid/').status_code, 200)
        self.assertEqual(api(self.direction).post(f'{COMM}{r.id}/mark_paid/').status_code, 400)
        # paid : plus de recalcul par generate ni par PATCH
        self.invoice(self.n1, c, 100)
        self.generate(self.n1)
        r.refresh_from_db()
        self.assertEqual(r.order_value, D('50000.00'))
        self.assertEqual(api(self.comptable).patch(f'{COMM}{r.id}/', {'deduction_other': '1'}, format='json').status_code, 400)

    def test_periode_cloturee_refuse_generate_et_edition(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        p = self.generate(self.n1)
        r = self.row(p, c)
        self.assertEqual(api(self.direction).post(f'{PERIODS}{p.id}/close_period/').status_code, 200)
        self.assertEqual(api(self.direction).post(f'{PERIODS}{p.id}/close_period/').status_code, 400)
        self.assertEqual(api(self.comptable).post(GEN, {'node': self.n1.pk, 'month': 2, 'year': 2026}, format='json').status_code, 400)
        self.assertEqual(api(self.comptable).patch(f'{COMM}{r.id}/', {'deduction_other': '1'}, format='json').status_code, 400)
        self.assertEqual(api(self.direction).delete(f'{PERIODS}{p.id}/').status_code, 400)

    def test_generate_idempotent_pas_de_double_retenue(self):
        c = make_client(self.n1, current_debt=D('3000'))
        self.invoice(self.n1, c, 100)
        for _ in range(3):
            p = self.generate(self.n1)
        self.assertEqual(ClientCommission.objects.filter(period=p).count(), 1)
        self.assertEqual(CommissionPeriod.objects.filter(node=self.n1).count(), 1)
        r = self.row(p, c)
        self.assertEqual((r.deduction_debt, r.net_payable), (D('3000.00'), D('6500.00')))   # 12 500 - 3 000 - 2 000 - 1 000

    def test_retenues_saisies_a_la_main_conservees_apres_regeneration(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        p = self.generate(self.n1)
        r = self.row(p, c)
        api(self.comptable).patch(f'{COMM}{r.id}/', {'deduction_other': '750', 'deduction_prints': '1200'}, format='json')
        self.invoice(self.n1, c, 100, day=20)                   # nouvelle livraison : 100 000 -> CM 25 000
        self.generate(self.n1)
        r.refresh_from_db()
        self.assertEqual((r.order_value, r.deduction_other, r.deduction_prints), (D('100000.00'), D('750.00'), D('1200.00')))
        self.assertEqual(r.net_payable, D('21050.00'))          # 25 000 - 2 000 - 1 200 - 750


# --------------------------------------------------------------------------
# Client facturé dans deux boulangeries (règle 5.1) : double retenue
# --------------------------------------------------------------------------
class ClientMultiBoulangerieTests(Base):
    def setUp(self):
        super().setUp()
        self.c = make_client(self.n3, current_debt=D('10000'))     # client de QA3
        self.invoice(self.n3, self.c, 100)                          # 50 000 à QA3
        self.invoice(self.n1, self.c, 100)                          # 50 000 à QA1 (autre boulangerie)
        self.p3 = self.generate(self.n3)
        self.p1 = self.generate(self.n1)

    def test_chaque_boulangerie_a_sa_ligne_avec_sa_carte(self):
        self.assertEqual(self.row(self.p3, self.c).deduction_prints, D('700.00'))
        self.assertEqual(self.row(self.p1, self.c).deduction_prints, D('1000.00'))
        self.assertEqual(self.row(self.p1, self.c).commission_gross, D('12500.00'))

    def test_dette_du_client_retenue_une_seule_fois_sur_l_ensemble_des_boulangeries(self):
        """BP 10 000 FC : la somme des retenues dette sur les deux listings doit valoir 10 000, pas 20 000 (BUG-737)."""
        total = sum(r.deduction_debt for r in ClientCommission.objects.filter(client=self.c))
        self.assertEqual(total, D('10000.00'))

    def test_cotisation_sociale_retenue_une_seule_fois_par_mois(self):
        """La cotisation mensuelle (1 500 FC de la boulangerie de rattachement) ne doit être retenue qu'une fois (BUG-737)."""
        total = sum(r.deduction_social for r in ClientCommission.objects.filter(client=self.c))
        self.assertEqual(total, D('1500.00'))
