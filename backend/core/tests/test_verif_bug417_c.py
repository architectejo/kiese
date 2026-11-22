"""Verification independante BUG-417 (testeur-clients-commissions, Dev C, 2026-11-22).
Donnees fictives. Migration jouee pour de vrai via MigrationExecutor (modeles historiques)."""
import contextlib
import io
from decimal import Decimal as D

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from commissions.models import ClientCommission, CommissionPeriod
from core.models import Config, Node
from core.testing import make_bread_price, make_client, make_user
from sales.models import Invoice, InvoiceLine

M21 = [('core', '0021_node_card_fee_fc')]
M22 = [('core', '0022_defauts_cotisation_carte_partout')]


class MigrationReelleTests(TransactionTestCase):
    """0021 -> 0022 avec les modeles HISTORIQUES (pas les modeles courants)."""

    def _migrate(self, target):
        ex = MigrationExecutor(connection)
        ex.migrate(target)
        return ex.loader.project_state(target).apps

    def tearDown(self):
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())

    def test_forward_real(self):
        apps = self._migrate(M21)
        N = apps.get_model('core', 'Node')
        N.objects.all().delete()
        spec = {
            'V0': (D('0'), D('0')), 'V1': (D('3000'), D('0')),
            'V2': (D('0'), D('1500')), 'V3': (D('2000'), D('1000')),
            'V4': (D('2500.50'), D('999.99')),
        }
        for code, (s, c) in spec.items():
            N.objects.create(code=code, name=code, monthly_social_contribution=s, card_fee_fc=c)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            apps = self._migrate(M22)
        N = apps.get_model('core', 'Node')
        got = {n.code: (n.monthly_social_contribution, n.card_fee_fc) for n in N.objects.all()}
        self.assertEqual(got['V0'], (D('2000.00'), D('1000.00')))
        self.assertEqual(got['V1'], (D('3000.00'), D('1000.00')))
        self.assertEqual(got['V2'], (D('2000.00'), D('1500.00')))
        self.assertEqual(got['V3'], (D('2000.00'), D('1000.00')))
        self.assertEqual(got['V4'], (D('2500.50'), D('999.99')))
        txt = out.getvalue()
        self.assertIn('V1.monthly_social_contribution', txt)
        self.assertIn('V2.card_fee_fc', txt)
        self.assertNotIn('V0.', txt)
        self.assertNotIn('V3.', txt)

    def test_reverse_noop_et_rejeu(self):
        apps = self._migrate(M22)
        N = apps.get_model('core', 'Node')
        N.objects.all().delete()
        N.objects.create(code='R1', name='R1', monthly_social_contribution=D('0'), card_fee_fc=D('0'))
        self._migrate(M21)
        apps = self._migrate(M22)
        n = apps.get_model('core', 'Node').objects.get(code='R1')
        self.assertEqual((n.monthly_social_contribution, n.card_fee_fc), (D('2000.00'), D('1000.00')))

    def test_commissions_deja_generees_inchangees(self):
        apps = self._migrate(M21)
        apps.get_model('core', 'Node').objects.all().delete()
        apps.get_model('core', 'Node').objects.create(
            code='G1', name='G1', monthly_social_contribution=D('0'), card_fee_fc=D('0'))
        self._migrate(M22)
        node = Node.objects.get(code='G1')
        self.assertEqual(node.monthly_social_contribution, D('2000.00'))
        client = make_client(node)
        period = CommissionPeriod.objects.create(node=node, month=1, year=2026)
        cm = ClientCommission.objects.create(
            period=period, client=client, order_value=D('100000'), commission_rate=D('0.25'),
            deduction_social=D('0'), deduction_prints=D('0'))
        cols = ('deduction_social', 'deduction_prints', 'net_payable')
        before = ClientCommission.objects.values_list(*cols).get(pk=cm.pk)
        self._migrate(M21)
        self._migrate(M22)
        after = ClientCommission.objects.values_list(*cols).get(pk=cm.pk)
        self.assertEqual(before, after)
        self.assertEqual(after[:2], (D('0.00'), D('0.00')))


def _api(u):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(u)
    return c


class DefautsEtFormulesTests(TestCase):
    def setUp(self):
        self.direction = make_user('DIRECTION', node=None, team='')
        self.comptable = make_user('COMPTABLE', node=None, team='')
        self.bp = make_bread_price('GRAND', 'Pain 500 FC', 500)

    def _gen(self, node, month=3):
        r = _api(self.comptable).post('/api/commissions/periods/generate/',
                                      {'node': node.pk, 'month': month, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return CommissionPeriod.objects.get(node=node, month=month, year=2026)

    def _inv(self, node, client, qty, day=10, month=3, **kw):
        inv = Invoice.objects.create(
            node=node, client=client, payment_type='CREDIT', status='DELIVERED',
            payment_amount=D('0'), invoice_date=f'2026-{month:02d}-{day:02d}',
            node_origin=node.code, **kw)
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=qty)
        inv.compute_order_total()
        inv.save(update_fields=['order_total'])

    def test_api_creation_noeud_defauts_en_fc(self):
        r = _api(self.direction).post('/api/core/nodes/', {'code': 'N9', 'name': 'Neuf'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(D(r.data['monthly_social_contribution']), D('2000'))
        self.assertEqual(D(r.data['card_fee_fc']), D('1000'))

    def test_api_refuse_negatifs(self):
        n = Node.objects.create(code='N8', name='N8')
        for f in ('card_fee_fc', 'monthly_social_contribution'):
            r = _api(self.direction).patch(f'/api/core/nodes/{n.pk}/', {f: '-1'}, format='json')
            self.assertEqual(r.status_code, 400, (f, r.data))

    def test_formules_a_la_main_defauts(self):
        # 100 x 500 = 50 000 ; CM 25 % = 12 500 ; retenues 0 + 2000 + 1000 = 3000 ; net 9 500
        node = Node.objects.create(code='N7', name='N7')
        c = make_client(node)
        self._inv(node, c, 100)
        cm = ClientCommission.objects.get(period=self._gen(node), client=c)
        self.assertEqual(cm.order_value, D('50000'))
        self.assertEqual(cm.commission_gross, D('12500.00'))
        self.assertEqual(cm.total_deductions, D('3000.00'))
        self.assertEqual(cm.net_payable, D('9500.00'))
        self.assertIsInstance(cm.net_payable, D)

    def test_taux_030(self):
        node = Node.objects.create(code='N6', name='N6')
        c = make_client(node, commission_rate=D('0.30'))
        self._inv(node, c, 100)
        cm = ClientCommission.objects.get(period=self._gen(node), client=c)
        self.assertEqual(cm.commission_gross, D('15000.00'))
        self.assertEqual(cm.net_payable, D('12000.00'))

    def test_cotisation_propre_au_client_prime(self):
        node = Node.objects.create(code='N5', name='N5')
        c = make_client(node)
        c.cotisation_sociale = D('500')
        c.save()
        self._inv(node, c, 100)
        cm = ClientCommission.objects.get(period=self._gen(node), client=c)
        self.assertEqual(cm.deduction_social, D('500.00'))
        self.assertEqual(cm.deduction_prints, D('1000.00'))

    def test_changement_tarif_noeud_ne_modifie_pas_commission_existante(self):
        node = Node.objects.create(code='N4', name='N4')
        c = make_client(node)
        self._inv(node, c, 100)
        cm = ClientCommission.objects.get(period=self._gen(node), client=c)
        node.card_fee_fc = D('5000')
        node.monthly_social_contribution = D('7000')
        node.save()
        cm.refresh_from_db()
        self.assertEqual((cm.deduction_social, cm.deduction_prints), (D('2000.00'), D('1000.00')))
        self._gen(node)
        cm.refresh_from_db()
        self.assertEqual((cm.deduction_social, cm.deduction_prints), (D('2000.00'), D('1000.00')))

    def test_vente_solde_pas_de_commission(self):
        node = Node.objects.create(code='N3', name='N3')
        c = make_client(node)
        self._inv(node, c, 10, is_soldee=True)
        self._gen(node)
        self.assertFalse(ClientCommission.objects.filter(client=c).exists())

    def test_totaux_verticaux_et_filtre_mois_annee(self):
        node = Node.objects.create(code='N2', name='N2')
        a, b = make_client(node), make_client(node)
        self._inv(node, a, 100, month=3)   # 50 000 -> CM 12 500
        self._inv(node, b, 40, month=3)    # 20 000 -> CM 5 000
        self._inv(node, a, 10, month=4)
        self._gen(node, 3)
        self._gen(node, 4)
        s = _api(self.direction).get('/api/commissions/commissions/summary/',
                                     {'period__month': 3, 'period__year': 2026, 'period__node': node.pk})
        self.assertEqual(s.status_code, 200, s.data)
        self.assertEqual(s.data['count'], 2)
        self.assertEqual(D(s.data['total_orders']), D('70000.00'))
        self.assertEqual(D(s.data['total_cm']), D('17500.00'))
        self.assertEqual(D(s.data['total_cotisation']), D('4000.00'))
        self.assertEqual(D(s.data['total_carte']), D('2000.00'))
        self.assertEqual(D(s.data['total_net']), D('17500.00') - D('6000.00'))
        s4 = _api(self.direction).get('/api/commissions/commissions/summary/',
                                      {'period__month': 4, 'period__year': 2026})
        self.assertEqual(s4.data['count'], 1)
        self.assertEqual(D(s4.data['total_carte']), D('1000.00'))

    def test_config_print_fee_sans_effet(self):
        """Constat (BUG-555) : Config.print_fee (champ Settings) n'alimente plus rien."""
        cfg = Config.get_instance()
        cfg.print_fee = D('7777')
        cfg.save()
        node = Node.objects.create(code='N1', name='N1')
        c = make_client(node)
        self._inv(node, c, 10)
        cm = ClientCommission.objects.get(period=self._gen(node), client=c)
        self.assertEqual(cm.deduction_prints, D('1000.00'))
