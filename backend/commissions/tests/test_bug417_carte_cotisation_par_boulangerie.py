"""BUG-417 : cotisation sociale et carte = montants FC (Decimal) PAR boulangerie,
deduits par client dans la situation des ristournes (remarque.md l.452-454).
Valeurs calculees a la main, donnees fictives."""
import importlib
from decimal import Decimal as D

from django.apps import apps as django_apps
from django.test import TestCase
from rest_framework.test import APIClient

from commissions.models import ClientCommission, CommissionPeriod
from core.models import Config, Node
from core.testing import make_bread_price, make_client, make_user
from sales.models import Invoice, InvoiceLine

GEN = '/api/commissions/periods/generate/'
COMM = '/api/commissions/commissions/'


def _api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


class Base(TestCase):
    def setUp(self):
        self.k1, _ = Node.objects.update_or_create(code='K1', defaults=dict(name='K1', monthly_social_contribution=D('0'), card_fee_fc=D('1500')))
        self.b2, _ = Node.objects.update_or_create(code='B2', defaults=dict(name='B2', monthly_social_contribution=D('2000'), card_fee_fc=D('800')))
        self.bp = make_bread_price('GRAND', 'Pain 500 FC', 500)
        self.direction = make_user('DIRECTION', node=None, team='')
        self.comptable = make_user('COMPTABLE', node=None, team='')
        self.g1 = make_user('GERANT', node=self.k1, team='')
        self.g2 = make_user('GERANT', node=self.b2, team='')

    def invoice(self, node, client, qty, month=2, year=2026):
        inv = Invoice.objects.create(
            node=node, client=client, payment_type='CREDIT', status='DELIVERED',
            payment_amount=D('0'), invoice_date=f'{year}-{month:02d}-10', node_origin=node.code)
        InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=qty)
        inv.compute_order_total()
        inv.save(update_fields=['order_total'])

    def generate(self, node, month=2, year=2026):
        r = _api(self.comptable).post(GEN, {'node': node.pk, 'month': month, 'year': year}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return CommissionPeriod.objects.get(node=node, month=month, year=year)


class CarteParBoulangerieTests(Base):
    def test_node_defaults_for_new_bakery(self):
        n = Node.objects.create(code='NEW', name='Nouvelle')
        n.refresh_from_db()
        self.assertEqual(n.monthly_social_contribution, D('2000.00'))
        self.assertEqual(n.card_fee_fc, D('1000.00'))
        self.assertIsInstance(n.card_fee_fc, D)

    def test_values_differ_between_k1_and_b2_and_are_deducted_per_client(self):
        c1 = make_client(self.k1)
        c2 = make_client(self.b2)
        self.invoice(self.k1, c1, 100)    # 50 000 -> CM 12 500
        self.invoice(self.b2, c2, 100)
        p1, p2 = self.generate(self.k1), self.generate(self.b2)
        r1 = ClientCommission.objects.get(period=p1, client=c1)
        r2 = ClientCommission.objects.get(period=p2, client=c2)
        self.assertEqual((r1.deduction_social, r1.deduction_prints), (D('0'), D('1500')))
        self.assertEqual((r2.deduction_social, r2.deduction_prints), (D('2000'), D('800')))
        # net = CM brute - retenues (dette 0)
        self.assertEqual(r1.net_payable, D('12500') - D('1500'))
        self.assertEqual(r2.net_payable, D('12500') - D('2000') - D('800'))
        self.assertEqual(r2.total_deductions, D('2800.00'))

    def test_config_print_fee_no_longer_source(self):
        cfg = Config.get_instance()
        cfg.print_fee = D('9999')
        cfg.save()
        c = make_client(self.k1)
        self.invoice(self.k1, c, 10)
        r = ClientCommission.objects.get(period=self.generate(self.k1), client=c)
        self.assertEqual(r.deduction_prints, D('1500.00'))

    def test_api_exposes_fc_fields_and_vertical_totals(self):
        a, b = make_client(self.b2), make_client(self.b2)
        self.invoice(self.b2, a, 10)
        self.invoice(self.b2, b, 10)
        p = self.generate(self.b2)
        r = _api(self.direction).get(COMM, {'period': p.pk})
        self.assertEqual(r.status_code, 200)
        rows = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(D(row['cotisation_sociale_fc']), D('2000.00'))
            self.assertEqual(D(row['carte_fc']), D('800.00'))
        s = _api(self.direction).get(COMM + 'summary/', {'period': p.pk})
        self.assertEqual(s.status_code, 200, s.data)
        self.assertEqual(D(s.data['total_cotisation']), D('4000.00'))
        self.assertEqual(D(s.data['total_carte']), D('1600.00'))
        self.assertEqual(s.data['count'], 2)
        h = _api(self.direction).get('/api/commissions/periods/history/', {'node': self.b2.pk})
        self.assertEqual(D(h.data[0]['total_cotisation']), D('4000.00'))
        self.assertEqual(D(h.data[0]['total_carte']), D('1600.00'))

    def test_summary_isolated_by_node(self):
        a, b = make_client(self.k1), make_client(self.b2)
        self.invoice(self.k1, a, 10)
        self.invoice(self.b2, b, 10)
        self.generate(self.k1)
        self.generate(self.b2)
        s = _api(self.g1).get(COMM + 'summary/')
        self.assertEqual(s.status_code, 200)
        self.assertEqual(s.data['count'], 1)
        self.assertEqual(D(s.data['total_carte']), D('1500.00'))
        self.assertEqual(D(s.data['total_cotisation']), D('0.00'))

    def test_node_api_card_fee_write_rules(self):
        url = f'/api/core/nodes/{self.k1.pk}/'
        r = _api(self.direction).patch(url, {'card_fee_fc': '1200'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.k1.refresh_from_db()
        self.assertEqual(self.k1.card_fee_fc, D('1200.00'))
        self.assertEqual(_api(self.direction).patch(url, {'card_fee_fc': '-1'}, format='json').status_code, 400)
        self.assertEqual(_api(self.g1).patch(url, {'card_fee_fc': '5'}, format='json').status_code, 403)
        self.k1.refresh_from_db()
        self.assertEqual(self.k1.card_fee_fc, D('1200.00'))
        g = _api(self.g1).get(url)
        self.assertEqual(D(g.data['card_fee_fc']), D('1200.00'))


class MigrationDonneesTests(TestCase):
    def _fill(self):
        mod = importlib.import_module('core.migrations.0021_node_card_fee_fc')
        mod.fill_card_fee(django_apps, None)

    def test_uses_config_print_fee_when_positive_and_keeps_social(self):
        Node.objects.all().delete()
        a = Node.objects.create(code='M1', name='M1', monthly_social_contribution=D('0'))
        b = Node.objects.create(code='M2', name='M2', monthly_social_contribution=D('2000'))
        cfg = Config.get_instance()
        cfg.print_fee = D('700')
        cfg.save()
        self._fill()
        for n, soc in ((a, D('0')), (b, D('2000'))):
            n.refresh_from_db()
            self.assertEqual(n.card_fee_fc, D('700.00'))
            self.assertEqual(n.monthly_social_contribution, soc)

    def test_falls_back_to_1000_when_print_fee_zero(self):
        n = Node.objects.create(code='M3', name='M3', card_fee_fc=D('5'))
        cfg = Config.get_instance()
        cfg.print_fee = D('0')
        cfg.save()
        self._fill()
        n.refresh_from_db()
        self.assertEqual(n.card_fee_fc, D('1000.00'))
