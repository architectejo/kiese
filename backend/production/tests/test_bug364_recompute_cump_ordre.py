"""BUG-364 : `recompute_cump` à instants égaux (ordre à UUID aléatoire) : ordre
déterministe (ENTRY avant EXIT), avertissement et refus d'application sans --force."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.testing import make_node
from production.management.commands.recompute_cump import count_ambiguous_movements
from production.models import ConsumableMovement, ConsumableStock


def _run(*args):
    out = StringIO()
    call_command('recompute_cump', *args, stdout=out)
    return out.getvalue()


class RecomputeCumpTieTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'), unit='sac')
        self.t0 = timezone.now()

    def _mv(self, kind, qty, price, ts):
        mv = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type=kind,
            quantity=Decimal(qty), unit_price=Decimal(price))
        ConsumableMovement.objects.filter(pk=mv.pk).update(created_at=ts)
        return mv

    def _tied_scenario(self):
        # Entrée et sortie au MÊME instant ; CUMP en base volontairement faux.
        self._mv('ENTRY', '10.000', '100.00', self.t0)
        self.exit = self._mv('EXIT', '2.000', '0.00', self.t0)
        ConsumableStock.objects.filter(pk=self.stock.pk).update(average_unit_cost=Decimal('999'))

    def test_tie_is_warned_in_simulation(self):
        self._tied_scenario()
        out = _run()
        self.assertIn('même instant', out)
        self.assertIn('2 mouvement(s)', out)

    def test_apply_skips_ambiguous_stock_without_force(self):
        self._tied_scenario()
        out = _run('--apply')
        self.assertIn('IGNORÉ', out)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('999'))

    def test_force_applies_with_entries_first(self):
        self._tied_scenario()
        _run('--apply', '--force')
        self.stock.refresh_from_db()
        self.exit.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('100'))
        self.assertEqual(self.exit.unit_price, Decimal('100.00'))  # entrée rejouée avant la sortie

    def test_distinct_instants_unaffected(self):
        self._mv('ENTRY', '10.000', '100.00', self.t0)
        self._mv('EXIT', '2.000', '0.00', self.t0 + timedelta(seconds=1))
        ConsumableStock.objects.filter(pk=self.stock.pk).update(average_unit_cost=Decimal('999'))
        out = _run('--apply')
        self.assertNotIn('même instant', out)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('100'))

    def test_count_helper_same_type_tie_is_not_ambiguous(self):
        a = self._mv('ENTRY', '1.000', '1.00', self.t0)
        b = self._mv('ENTRY', '1.000', '1.00', self.t0)
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(count_ambiguous_movements([a, b]), 0)
