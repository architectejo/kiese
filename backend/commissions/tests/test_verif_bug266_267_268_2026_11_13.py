"""Vérification indépendante BUG-266/267/268 (testeur-clients-commissions, 2026-11-13). Valeurs calculées à la main."""
from decimal import Decimal as D

from commissions.models import ClientCommission
from commissions.tests.test_vague2_db_commissions_2026_11_12 import Base, COMM, _api
from core.testing import make_client
from sales.models import Invoice


class Verif266(Base):
    def test_net_nul_est_payable(self):
        c = self.sans_cotisation()
        self.invoice(c, 2)
        cc = self.row(self.generate(), c)
        r = _api(self.direction).patch(f'{COMM}{cc.pk}/set_manuel/', {'manuel_adjustment': '0'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        cc.refresh_from_db()
        self.assertEqual(cc.net_payable, D('0'))
        self.assertEqual(_api(self.direction).post(f'{COMM}{cc.pk}/mark_paid/').status_code, 200)

    def test_net_negatif_puis_regeneration_reste_non_paye_et_toujours_refuse(self):
        c = make_client(self.node, current_debt=D('5000'))
        self.invoice(c, 10)
        p = self.generate()
        cc = self.row(p, c)
        self.assertEqual(cc.net_payable, D('-6762.50'))
        self.assertEqual(_api(self.direction).post(f'{COMM}{cc.pk}/mark_paid/').status_code, 400)
        self.generate()
        cc.refresh_from_db()
        self.assertEqual(cc.net_payable, D('-6762.50'))
        self.assertFalse(cc.is_paid)
        self.assertEqual(_api(self.direction).post(f'{COMM}{cc.pk}/mark_paid/').status_code, 400)

    def test_net_positif_normal_inchange_et_payable(self):
        c = make_client(self.node, current_debt=D('100'))
        self.invoice(c, 100)                       # 50000 -> CM 12500
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.commission_gross, D('12500.00'))
        self.assertEqual(cc.total_deductions, D('100') + D('3000') + D('125.00'))
        self.assertEqual(cc.net_payable, D('12500') - D('100') - D('125.00') - D('3000'))   # 9275
        self.assertEqual(_api(self.direction).post(f'{COMM}{cc.pk}/mark_paid/').status_code, 200)


class Verif267(Base):
    def test_client_mixte_epargne_et_vente_garde_sa_commission_sans_credit_bp(self):
        c = make_client(self.node, current_debt=D('-7000'))
        Invoice.objects.create(node=self.node, client=c, payment_type='CASH', status='DELIVERED',
                               payment_amount=D('7000'), is_debt_repayment=True, invoice_date='2026-02-10', node_origin='C4')
        self.invoice(c, 2)                          # 1000 -> CM 250
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.order_value, D('1000.00'))
        self.assertEqual(cc.commission_gross, D('250.00'))
        self.assertEqual(cc.deduction_debt, D('0'))
        self.assertEqual(cc.net_payable, D('250') - D('2.50') - D('3000'))

    def test_client_commande_zero_sans_remboursement_exclu_et_autres_clients_non_affectes(self):
        ep = make_client(self.node, current_debt=D('-3000'))
        self.invoice(ep, 0, pay=3000)               # dépôt sans ligne, commande 0
        reg = self.sans_cotisation()
        self.invoice(reg, 2)
        p = self.generate()
        self.assertFalse(ClientCommission.objects.filter(period=p, client=ep).exists())
        self.assertEqual(self.row(p, reg).net_payable, D('250') - D('2.50'))


class Verif268(Base):
    def test_report_exact_sur_trois_periodes(self):
        c = make_client(self.node, current_debt=D('10000'))
        self.invoice(c, 20)
        c1 = self.row(self.generate(2), c)
        self.assertEqual(c1.net_payable, D('-10525.00'))        # 2500 -10000 -25 -3000
        self.invoice(c, 2, month=3)
        c2 = self.row(self.generate(3), c)
        self.assertEqual(c2.carried_debt_in, D('10525.00'))
        self.assertEqual(c2.net_payable, D('-13277.50'))        # 250 -0 -2,5 -3000 -10525
        self.invoice(c, 2, month=4)
        c3 = self.row(self.generate(4), c)
        self.assertEqual(c3.carried_debt_in, D('13277.50'))
        self.assertEqual(c3.net_payable, D('-16030.00'))        # 250 -2,5 -3000 -13277,5
        # idempotence de la régénération
        self.generate(4)
        c3.refresh_from_db()
        self.assertEqual(c3.net_payable, D('-16030.00'))
        self.assertEqual(c2.deduction_debt, D('10000.00'))      # champ stocké non modifié

    def test_dette_superieure_au_report_ne_retient_que_l_exces(self):
        c = make_client(self.node, current_debt=D('10000'))
        self.invoice(c, 20)
        self.generate(2)                                         # report 10525
        c.current_debt = D('20000'); c.save(update_fields=['current_debt'])
        self.invoice(c, 2, month=3)
        cc = self.row(self.generate(3), c)
        # retenue dette = 20000 - 10525 = 9475 ; net = 250 - 9475 - 2,5 - 3000 - 10525
        self.assertEqual(cc.net_payable, D('250') - D('9475') - D('2.50') - D('3000') - D('10525.00'))
