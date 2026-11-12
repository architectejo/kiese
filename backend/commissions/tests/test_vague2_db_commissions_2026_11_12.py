"""
Vague 2 « base réelle » (testeur-clients-commissions, 2026-11-12) : scénarios de commissions
rejoués sur K4 (comptes zz_clients_*) et reproduits sur une base de test fictive. Valeurs
calculées à la main (en Decimal). Défauts constatés : @expectedFailure + ticket du registre.
"""
from decimal import Decimal as D
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission, CommissionPeriod
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine

GEN = '/api/commissions/periods/generate/'
COMM = '/api/commissions/commissions/'


def _api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='C4')
        self.bp = make_bread_price('GRAND', 'Pain 500 FC', 500)
        self.comptable = make_user('COMPTABLE', node=None, team='')
        self.direction = make_user('DIRECTION', node=None, team='')
        self.gerant = make_user('GERANT', node=self.node, team='')
        self.facturier = make_user('FACTURIER', node=self.node, team='A')

    def invoice(self, client, qty, pay=0, month=2, year=2026, **kw):
        inv = Invoice.objects.create(
            node=self.node, client=client, payment_type='CASH' if pay else 'CREDIT', status='DELIVERED',
            payment_amount=D(pay), invoice_date=f'{year}-{month:02d}-10', node_origin=self.node.code, **kw)
        if qty:
            InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=qty)
        inv.compute_order_total()
        inv.save(update_fields=['order_total'])
        return inv

    def generate(self, month=2, year=2026):
        r = _api(self.comptable).post(GEN, {'node': self.node.pk, 'month': month, 'year': year}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return CommissionPeriod.objects.get(node=self.node, month=month, year=year)

    def row(self, period, client):
        return ClientCommission.objects.get(period=period, client=client)


class FormulesTests(Base):
    def test_cm_25_et_30_retenues_carte_net_et_remise_incorporee_calculs_a_la_main(self):
        c25 = make_client(self.node, current_debt=D('5000'))                       # 10 x 500 = 5000
        c30 = make_client(self.node, current_debt=D('10000'), commission_rate=D('0.30'))   # 20x500 + 12x500 = 16000
        self.invoice(c25, 10)
        self.invoice(c30, 20, pay=6000)
        self.invoice(c30, 12)
        p = self.generate()
        a, b = self.row(p, c25), self.row(p, c30)
        # CM brute = valeur x taux
        self.assertEqual(a.order_value, D('5000.00'))
        self.assertEqual(a.commission_gross, D('1250.00'))     # 5000 x 0,25
        self.assertEqual(b.order_value, D('16000.00'))
        self.assertEqual(b.commission_gross, D('4800.00'))     # 16000 x 0,30
        # retenues : dette 5000 + sociale 3000 + imprimés 0 + autre 0 (+ CARTE 1 % = 12,50, BUG-058)
        self.assertEqual(a.deduction_carte, D('12.50'))
        self.assertEqual(a.total_deductions, D('8012.50'))
        # net = 1250 - 5000 - 12,50 - 3000
        self.assertEqual(a.net_payable, D('-6762.50'))
        self.assertEqual(b.net_payable, D('4800') - D('10000') - D('48.00') - D('3000'))   # -8248,00
        # remise annuelle = 0,025 x pains livrés (10 puis 32), 2 décimales
        self.assertEqual(a.annual_bonus, D('0.25'))
        self.assertEqual(b.annual_bonus, D('0.80'))
        # incorporation : net + remise
        r = _api(self.comptable).patch(f'{COMM}{a.pk}/', {'annual_bonus_incorporated': True}, format='json')
        self.assertEqual(D(str(r.data['net_payable'])), D('-6762.25'))
        # retenue « autre » 500
        r = _api(self.comptable).patch(f'{COMM}{a.pk}/', {'deduction_other': '500'}, format='json')
        self.assertEqual(D(str(r.data['net_payable'])), D('-7262.25'))
        self.assertEqual(D(str(r.data['total_deductions'])), D('8512.50'))

    def test_aucun_float_dans_les_montants_de_l_api(self):
        c = make_client(self.node)
        self.invoice(c, 3)
        p = self.generate()
        r = _api(self.comptable).get(f'{COMM}payroll_listing/', {'period': p.pk})
        for k in ('order_value', 'commission_gross', 'total_deductions', 'net_payable', 'annual_bonus'):
            self.assertIsInstance(r.data[0][k], str, k)

    def test_vente_solde_exoneree_et_occasionnelle_donnent_cm_zero(self):
        c = make_client(self.node)
        self.invoice(c, 10, pay=3750, is_soldee=True)
        self.invoice(c, 4)                                   # 2000, seule base
        ex = make_client(self.node)
        self.invoice(ex, 2, pay=1000, commission_exempt=True)
        occ = Invoice.objects.create(node=self.node, client=None, payment_type='CASH', status='DELIVERED',
                                     payment_amount=D('1000'), invoice_date='2026-02-10', node_origin='C4')
        p = self.generate()
        self.assertEqual(self.row(p, c).order_value, D('2000.00'))
        self.assertEqual(self.row(p, c).commission_gross, D('500.00'))
        self.assertFalse(ClientCommission.objects.filter(period=p, client=ex).exists())
        self.assertEqual(ClientCommission.objects.filter(period=p).count(), 1)

    def test_totaux_verticaux_du_listing_de_paie_et_historique(self):
        cs = [make_client(self.node) for _ in range(3)]
        for c, q in zip(cs, (10, 20, 30)):
            self.invoice(c, q, pay=500)
        p = self.generate()
        rows = _api(self.comptable).get(f'{COMM}payroll_listing/', {'period': p.pk}).data
        self.assertEqual(sum(D(x['order_value']) for x in rows), D('30000.00'))      # 5000+10000+15000
        self.assertEqual(sum(D(x['commission_gross']) for x in rows), D('7500.00'))  # x 0,25
        h = _api(self.comptable).get('/api/commissions/periods/history/', {'node': self.node.pk}).data[0]
        self.assertEqual(D(h['total_orders']), D('30000'))
        self.assertEqual(D(h['total_cm']), D('7500'))
        self.assertEqual(D(h['total_payments']), D('1500'))
        self.assertEqual(h['client_count'], 3)

    def test_droits_generation_et_visibilite_par_noeud(self):
        make_client(self.node)
        self.assertEqual(_api(self.gerant).post(GEN, {'node': self.node.pk, 'month': 2, 'year': 2026}).status_code, 403)
        self.assertEqual(_api(self.facturier).post(GEN, {'node': self.node.pk, 'month': 2, 'year': 2026}).status_code, 403)
        autre = make_node(code='C5')
        ac = make_client(autre)
        Invoice.objects.create(node=autre, client=ac, payment_type='CREDIT', status='DELIVERED', invoice_date='2026-02-10', node_origin='C5')
        _api(self.comptable).post(GEN, {'node': autre.pk, 'month': 2, 'year': 2026})
        self.assertEqual(len(_api(self.gerant).get(COMM).data['results']), 0)

    def test_periode_cloturee_refuse_la_regeneration(self):
        c = make_client(self.node)
        self.invoice(c, 2)
        p = self.generate()
        self.assertEqual(_api(self.comptable).post(f'/api/commissions/periods/{p.pk}/close_period/').status_code, 200)
        self.assertEqual(_api(self.comptable).post(GEN, {'node': self.node.pk, 'month': 2, 'year': 2026}).status_code, 400)

    def test_report_de_dette_net_negatif_repris_le_mois_suivant(self):
        c = make_client(self.node, current_debt=D('10000'))
        self.invoice(c, 20)                                           # CM 2500
        p1 = self.generate(2)
        self.assertEqual(self.row(p1, c).net_payable, D('2500') - D('10000') - D('25.00') - D('3000'))   # -10525
        self.invoice(c, 2, pay=1000, month=3)
        p2 = self.generate(3)
        self.assertEqual(self.row(p2, c).carried_debt_in, D('10525.00'))


class DefautsConstatesTests(Base):
    def test_bug261_regularisation_rg_n_entre_pas_dans_la_base_de_cm(self):
        c = make_client(self.node)
        self.invoice(c, 1, special_code='RG', commission_rate=D('0.00'))
        p = self.generate()
        self.assertFalse(ClientCommission.objects.filter(period=p, client=c, commission_gross__gt=0).exists(),
                         'une RG (CM 0) ne doit pas générer de commission (125 FC constatés)')

    def test_bug262_valeurs_negatives_ou_taux_hors_025_030_refuses_en_patch(self):
        c = make_client(self.node)
        self.invoice(c, 2)
        cc = self.row(self.generate(), c)
        api = _api(self.comptable)
        for payload in ({'deduction_other': '-1000'}, {'order_value': '-100'}, {'commission_rate': '0.90'},
                        {'deduction_debt': '-1'}):
            self.assertEqual(api.patch(f'{COMM}{cc.pk}/', payload, format='json').status_code, 400, payload)

    def test_bug263_commission_payee_ou_periode_cloturee_non_modifiable(self):
        c = make_client(self.node)
        self.invoice(c, 2)
        p = self.generate()
        cc = self.row(p, c)
        _api(self.direction).post(f'{COMM}{cc.pk}/mark_paid/')
        r = _api(self.comptable).patch(f'{COMM}{cc.pk}/', {'deduction_other': '10'}, format='json')
        self.assertEqual(r.status_code, 400, 'commission payée modifiée')
        c2 = make_client(self.node)
        self.invoice(c2, 2)
        p = self.generate()
        _api(self.comptable).post(f'/api/commissions/periods/{p.pk}/close_period/')
        r = _api(self.comptable).patch(f'{COMM}{self.row(p, c2).pk}/', {'deduction_other': '10'}, format='json')
        self.assertEqual(r.status_code, 400, 'ligne d’une période clôturée modifiée')

    def test_bug264_regeneration_conserve_les_retenues_saisies_et_les_commissions_payees(self):
        c = make_client(self.node)
        self.invoice(c, 2)
        cc = self.row(self.generate(), c)
        _api(self.comptable).patch(f'{COMM}{cc.pk}/', {'deduction_social': '1000'}, format='json')
        self.generate()
        cc.refresh_from_db()
        self.assertEqual(cc.deduction_social, D('1000.00'), 'la retenue sociale saisie est écrasée par la régénération')

    def test_bug265_mark_paid_et_set_manuel_reserves_a_la_direction(self):
        c = make_client(self.node)
        self.invoice(c, 2)
        cc = self.row(self.generate(), c)
        self.assertEqual(_api(self.comptable).patch(f'{COMM}{cc.pk}/set_manuel/', {'manuel_adjustment': '100'}, format='json').status_code, 403)
        self.assertEqual(_api(self.comptable).post(f'{COMM}{cc.pk}/mark_paid/').status_code, 403)
        self.assertEqual(_api(self.direction).post(f'{COMM}{cc.pk}/mark_paid/').status_code, 200)

    @expectedFailure  # BUG-266 (À CLARIFIER : que faire d'un net négatif au paiement ?)
    def test_bug266_net_negatif_non_marquable_paye(self):
        c = make_client(self.node, current_debt=D('5000'))
        self.invoice(c, 10)
        cc = self.row(self.generate(), c)
        self.assertLess(cc.net_payable, 0)
        self.assertEqual(_api(self.direction).post(f'{COMM}{cc.pk}/mark_paid/').status_code, 400)

    @expectedFailure  # BUG-267 (À CLARIFIER : épargne client)
    def test_bug267_client_epargne_cm_zero_ne_recoit_pas_son_epargne_en_net_a_payer(self):
        c = make_client(self.node, current_debt=D('-7000'))
        Invoice.objects.create(node=self.node, client=c, payment_type='CASH', status='DELIVERED',
                               payment_amount=D('7000'), is_debt_repayment=True, invoice_date='2026-02-10', node_origin='C4')
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.commission_gross, D('0.00'))
        self.assertLessEqual(cc.net_payable, D('0.00'), 'net de +4000 FC pour une CM de 0 (épargne restituée comme commission)')

    @expectedFailure  # BUG-268 (À CLARIFIER : double comptage dette BP + report)
    def test_bug268_report_de_deficit_ne_recompte_pas_la_dette_bp_deja_retenue(self):
        c = make_client(self.node, current_debt=D('10000'))
        self.invoice(c, 20)                                           # CM 2500, net fév. -10525
        self.generate(2)
        self.invoice(c, 2, pay=1000, month=3)                         # BP inchangée : 10000
        p2 = self.generate(3)
        cc = self.row(p2, c)
        # La dette de 10000 FC figure déjà dans le déficit reporté (10525) : la retenue du mois ne
        # doit pas la compter une seconde fois (dette réellement due = 10000 FC + frais).
        # Net maximal admissible : 250 (CM) - 2,50 (carte) - 10000 (dette, une fois) - 3000 - 3000 (2 cotisations).
        self.assertGreaterEqual(cc.net_payable, D('-16000'), f'net observé {cc.net_payable}')

    @expectedFailure  # BUG-253 (À CLARIFIER)
    def test_bug253_facturier_ne_lit_pas_les_commissions_et_retenues_des_clients(self):
        c = make_client(self.node)
        self.invoice(c, 2)
        self.generate()
        self.assertEqual(_api(self.facturier).get(COMM).status_code, 403)
