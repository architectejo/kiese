"""Vérification indépendante (testeur-clients-commissions, 2026-11-15) de
BUG-289, 291, 292, 293, 295 et de la migration clients/0010. Valeurs à la main."""
from decimal import Decimal as D

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from clients.models import (Client, SocialContribution, SocialDistribution,
                            SocialDistributionLine)
from commissions.models import ClientCommission, CommissionPeriod
from core.testing import make_node, make_user, make_client, make_bread_price
from sales.models import Invoice, InvoiceLine

GEN = '/api/commissions/periods/generate/'
CONTRIB = '/api/clients/contributions/bulk_create_month/'
DIST = '/api/clients/distributions/'


def api(u):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(u)
    return c


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='V9')
        self.bp = make_bread_price('GRAND', 'Pain 500 FC', 500)
        self.compta = make_user('COMPTABLE', node=None, team='')
        self.direction = make_user('DIRECTION', node=None, team='')

    def invoice(self, client, qty):
        inv = Invoice.objects.create(
            node=self.node, client=client, payment_type='CREDIT', status='DELIVERED',
            payment_amount=D(0), invoice_date='2026-02-10', node_origin=self.node.code)
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=qty)
        inv.compute_order_total()
        inv.save(update_fields=['order_total'])

    def gen(self):
        r = api(self.compta).post(GEN, {'node': self.node.pk, 'month': 2, 'year': 2026}, format='json')
        self.assertIn(r.status_code, (200, 201), getattr(r, 'data', None))

    def row(self, client):
        p = CommissionPeriod.objects.get(node=self.node, month=2, year=2026)
        return ClientCommission.objects.get(period=p, client=client)


class CommissionFormules(Base):
    def test_net_complet_social_remise_credit_sans_carte(self):
        self.node.monthly_social_contribution = D('2000')
        self.node.save()
        c = make_client(self.node, current_debt=D('-1500'))      # BP créditrice
        self.invoice(c, 40)                                       # 40 x 500 = 20 000
        self.gen()
        cc = self.row(c)
        self.assertEqual(cc.commission_gross, D('5000.00'))       # 20000 x 0,25
        self.assertEqual(cc.deduction_remise, D('50.00'))         # 20000 x 0,0025
        self.assertEqual(cc.deduction_carte, D('0.00'))
        self.assertEqual(cc.annual_bonus, D('0.00'))
        self.assertEqual(cc.deduction_debt, D('-1500.00'))
        self.assertEqual(cc.deduction_social, D('2000.00'))
        self.assertEqual(cc.net_ordi, D('6500.00'))               # 5000 + 1500
        self.assertEqual(cc.net_carte, D('6500.00'))
        self.assertEqual(cc.net_payable, D('4500.00'))            # 6500 - 2000, remise non déduite

    def test_taux_030_et_dette_positive(self):
        c = make_client(self.node, current_debt=D('1000'), commission_rate=D('0.30'))
        self.invoice(c, 20)                                       # 10 000
        self.gen()
        cc = self.row(c)
        self.assertEqual(cc.commission_gross, D('3000.00'))
        self.assertEqual(cc.deduction_remise, D('25.00'))
        self.assertEqual(cc.net_payable, D('2000.00'))            # 3000 - 1000

    def test_flag_remise_incorporee_sans_effet(self):
        c = make_client(self.node)
        self.invoice(c, 20)
        self.gen()
        cc = self.row(c)
        cc.annual_bonus_incorporated = True
        cc.compute()
        self.assertEqual(cc.annual_bonus, D('0.00'))
        self.assertEqual(cc.net_payable, D('2500.00'))            # 10000 x 0,25

    def test_cotisation_null_suit_boulangerie_zero_explicite_prevaut(self):
        self.node.monthly_social_contribution = D('2000')
        self.node.save()
        a = make_client(self.node)
        b = make_client(self.node)
        Client.objects.filter(pk=b.pk).update(cotisation_sociale=D('0'))
        for c in (a, b):
            self.invoice(c, 20)
        self.gen()
        self.assertEqual(self.row(a).deduction_social, D('2000.00'))
        self.assertEqual(self.row(b).deduction_social, D('0.00'))

    def test_commission_payee_ou_existante_non_corrompue_par_regeneration(self):
        c = make_client(self.node, current_debt=D('1000'))
        self.invoice(c, 20)
        self.gen()
        cc = self.row(c)
        avant = (cc.commission_gross, cc.net_payable, cc.deduction_social, cc.deduction_debt)
        self.node.monthly_social_contribution = D('2000')
        self.node.save()
        self.gen()
        cc = self.row(c)
        self.assertEqual((cc.commission_gross, cc.net_payable, cc.deduction_social, cc.deduction_debt), avant)


class CaisseSociale(Base):
    def test_cotisations_par_boulangerie(self):
        self.node.monthly_social_contribution = D('2000')
        self.node.save()
        a = make_client(self.node)
        b = make_client(self.node)
        Client.objects.filter(pk=b.pk).update(cotisation_sociale=D('0'))
        n2 = make_node(code='V8')                                 # cotisation 0
        z = make_client(n2)
        r = api(self.direction).post(CONTRIB, {'node': self.node.pk, 'month': 3, 'year': 2026}, format='json')
        self.assertIn(r.status_code, (200, 201), getattr(r, 'data', None))
        self.assertEqual(r.data['created'], 1)
        self.assertEqual(SocialContribution.objects.get(client=a).amount, D('2000.00'))
        r = api(self.direction).post(CONTRIB, {'node': n2.pk, 'month': 3, 'year': 2026}, format='json')
        self.assertEqual(r.data['created'], 0)
        self.assertFalse(SocialContribution.objects.filter(client=z).exists())

    def _setup_dist(self):
        c = make_client(self.node)
        for m in range(1, 11):                                    # 10 mois payés
            SocialContribution.objects.create(client=c, node=self.node, month=m, year=2026,
                                              amount=D('3000'), is_paid=True)
        SocialContribution.objects.create(client=c, node=self.node, month=11, year=2026,
                                          amount=D('3000'), is_paid=False)
        d = SocialDistribution.objects.create(node=self.node, year=2026, tarif=D('700'))
        return c, d

    def test_refresh_indices_tarif_merite_cloture(self):
        c, d = self._setup_dist()
        line = SocialDistributionLine.objects.create(distribution=d, client=c, merite=D('1500'))
        r = api(self.direction).post(f'{DIST}{d.pk}/refresh_indices/')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        line.refresh_from_db()
        self.assertEqual(line.indice, 10)                         # le mois non payé est exclu
        self.assertEqual(line.total_social, D('30000.00'))
        self.assertEqual(line.remise, D('7000.00'))               # 10 x 700
        self.assertEqual(line.total_payer, D('38500.00'))         # 30000 + 7000 + 1500
        r = api(self.direction).patch(f'{DIST}{d.pk}/', {'tarif': '600'}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        line.refresh_from_db()
        self.assertEqual(line.remise, D('6000.00'))
        self.assertEqual(line.total_payer, D('37500.00'))
        SocialContribution.objects.filter(client=c, month=11).update(is_paid=True)
        api(self.direction).post(f'{DIST}{d.pk}/refresh_indices/')
        line.refresh_from_db()
        self.assertEqual((line.indice, line.remise, line.total_payer),
                         (11, D('6600.00'), D('41100.00')))       # 33000 + 6600 + 1500
        r = api(self.direction).patch(f'{DIST}{d.pk}/', {'is_closed': True}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertEqual(api(self.direction).patch(f'{DIST}{d.pk}/', {'tarif': '900'}, format='json').status_code, 400)
        self.assertEqual(api(self.direction).post(f'{DIST}{d.pk}/refresh_indices/').status_code, 400)
        d.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(d.tarif, D('600.00'))
        self.assertEqual(line.total_payer, D('41100.00'))

    def test_refresh_interdit_facturier_et_autre_boulangerie(self):
        c, d = self._setup_dist()
        fact = make_user('FACTURIER', node=self.node, team='A')
        self.assertIn(api(fact).post(f'{DIST}{d.pk}/refresh_indices/').status_code, (403, 404))
        g2 = make_user('GERANT', node=make_node(code='V7'), team='')
        self.assertIn(api(g2).post(f'{DIST}{d.pk}/refresh_indices/').status_code, (403, 404))


class Migration0010(TransactionTestCase):
    def test_aller_retour_et_commissions_intactes(self):
        ex = MigrationExecutor(connection)
        T9 = [('clients', '0009_social_syncable_step2'), ('commissions', '0005_bug292_remise_label')]
        ex.migrate(T9)
        old = ex.loader.project_state(T9).apps
        Node = old.get_model('core', 'Node')
        OClient = old.get_model('clients', 'Client')
        n = Node.objects.create(code='MG1', name='Mig')
        mk = lambda code, v: OClient.objects.create(
            node=n, node_origin='MG1', first_name=code, last_name='X', code=code, cotisation_sociale=D(v))
        a, b, z = mk('MGA', '3000.00'), mk('MGB', '1500.00'), mk('MGZ', '0.00')
        OCom = old.get_model('commissions', 'ClientCommission')
        OPer = old.get_model('commissions', 'CommissionPeriod')
        per = OPer.objects.create(node=n, month=1, year=2026)
        com = OCom.objects.create(period=per, client=a, deduction_social=D('3000.00'),
                                  net_payable=D('777.00'), annual_bonus=D('611.00'),
                                  deduction_carte=D('37.00'))
        ex = MigrationExecutor(connection)
        T10 = [('clients', '0010_bug289'), ('commissions', '0005_bug292_remise_label')]
        ex.migrate(T10)
        new = ex.loader.project_state(T10).apps
        NC = new.get_model('clients', 'Client')
        self.assertIsNone(NC.objects.get(code='MGA').cotisation_sociale)
        self.assertEqual(NC.objects.get(code='MGB').cotisation_sociale, D('1500.00'))
        self.assertEqual(NC.objects.get(code='MGZ').cotisation_sociale, D('0.00'))
        c = new.get_model('commissions', 'ClientCommission').objects.get(pk=com.pk)
        self.assertEqual((c.deduction_social, c.net_payable, c.annual_bonus, c.deduction_carte),
                         (D('3000.00'), D('777.00'), D('611.00'), D('37.00')))
        ex = MigrationExecutor(connection)
        ex.migrate(T9)
        back = ex.loader.project_state(T9).apps
        self.assertEqual(back.get_model('clients', 'Client').objects.get(code='MGA').cotisation_sociale, D('3000.00'))
        self.assertEqual(back.get_model('commissions', 'ClientCommission').objects.get(pk=com.pk).net_payable, D('777.00'))
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())
