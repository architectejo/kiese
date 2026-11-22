"""BUG-417 : migration de donnees core/0022 (2000 / 1000 FC partout)."""
import importlib
from decimal import Decimal as D

from django.apps import apps as django_apps
from django.test import TestCase

from commissions.models import ClientCommission, CommissionPeriod
from core.models import Node
from core.testing import make_client, make_node, make_user


def _forward():
    mod = importlib.import_module('core.migrations.0022_defauts_cotisation_carte_partout')
    return mod.apply_defaults(django_apps, None)


class MigrationDefautsPartoutTests(TestCase):
    def test_existing_zero_nodes_get_defaults(self):
        a = Node.objects.create(code='Z1', name='Z1', monthly_social_contribution=D('0'), card_fee_fc=D('0'))
        b = Node.objects.create(code='Z2', name='Z2', monthly_social_contribution=D('2000'), card_fee_fc=D('0'))
        kept = _forward()
        for n in (a, b):
            n.refresh_from_db()
            self.assertEqual(n.monthly_social_contribution, D('2000.00'))
            self.assertEqual(n.card_fee_fc, D('1000.00'))
        self.assertFalse([k for k in kept if k[0] in ('Z1', 'Z2')])

    def test_own_value_not_overwritten_and_reported(self):
        n = Node.objects.create(code='Z3', name='Z3', monthly_social_contribution=D('3000'), card_fee_fc=D('0'))
        kept = _forward()
        n.refresh_from_db()
        self.assertEqual(n.monthly_social_contribution, D('3000.00'))
        self.assertEqual(n.card_fee_fc, D('1000.00'))
        self.assertIn(('Z3', 'monthly_social_contribution', D('3000.00')), kept)

    def test_idempotent(self):
        n = Node.objects.create(code='Z4', name='Z4', monthly_social_contribution=D('0'), card_fee_fc=D('800'))
        _forward()
        _forward()
        n.refresh_from_db()
        self.assertEqual((n.monthly_social_contribution, n.card_fee_fc), (D('2000.00'), D('800.00')))

    def test_existing_commissions_unchanged(self):
        node = make_node(code='Z5')
        client = make_client(node)
        period = CommissionPeriod.objects.create(node=node, month=2, year=2026)
        cm = ClientCommission.objects.create(
            period=period, client=client, deduction_social=D('0'), deduction_prints=D('0'))
        cm.refresh_from_db()
        before = (cm.deduction_social, cm.deduction_prints, cm.net_payable)
        _forward()
        cm.refresh_from_db()
        self.assertEqual((cm.deduction_social, cm.deduction_prints, cm.net_payable), before)
        node.refresh_from_db()
        self.assertEqual(node.monthly_social_contribution, D('2000.00'))

    def test_new_node_model_defaults(self):
        n = Node.objects.create(code='Z6', name='Z6')
        n.refresh_from_db()
        self.assertEqual((n.monthly_social_contribution, n.card_fee_fc), (D('2000.00'), D('1000.00')))
