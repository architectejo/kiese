"""
BUG-357 : la commande `recompute_cump` recalcule les CUMP gonflés avant
BUG-402 (simulation par défaut, --apply pour écrire). Données fictives.
"""
import itertools
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.utils import timezone

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import ActivityLog
from core.testing import make_node
from production.models import ConsumableStock, ConsumableMovement


_BASE = timezone.now()
_SEQ = itertools.count(1)


def _stamp(mv):
    ts = _BASE + timedelta(seconds=next(_SEQ))
    ConsumableMovement.objects.filter(pk=mv.pk).update(created_at=ts)
    mv.refresh_from_db()
    return mv


def _run(*args):
    out = StringIO()
    call_command('recompute_cump', *args, stdout=out)
    return out.getvalue()


class RecomputeCumpTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'), unit='sac',
        )

    def _mv(self, kind, qty, price='0.00'):
        mv = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type=kind,
            quantity=Decimal(qty), unit_price=Decimal(price),
        )
        # BUG-416 : horloge grossière sous Windows -> created_at identiques ;
        # on impose un ordre strictement croissant (rejeu déterministe).
        return _stamp(mv)

    def _inflate(self):
        """Scénario pré-BUG-402 : sortie en négatif (-5), entrée de 10 à 100000,
        CUMP gonflé fixé à la main (ancienne formule : 10*100000/5 = 200000),
        puis une sortie valorisée à ce CUMP gonflé."""
        self._mv('EXIT', '5.000')
        self._mv('ENTRY', '10.000', '100000.00')
        out = self._mv('EXIT', '1.000')
        ConsumableStock.objects.filter(pk=self.stock.pk).update(average_unit_cost=Decimal('200000.0000'))
        ConsumableMovement.objects.filter(pk=out.pk).update(unit_price=Decimal('200000.00'))
        return out

    def test_dry_run_default_writes_nothing(self):
        out_mv = self._inflate()
        text = _run()
        self.assertIn('SIMULATION', text)
        self.assertIn('200000.0000 -> 100000.0000', text)
        self.stock.refresh_from_db()
        out_mv.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('200000.0000'))
        self.assertEqual(out_mv.unit_price, Decimal('200000.00'))
        self.assertFalse(ActivityLog.objects.filter(action__contains='CUMP').exists())

    def test_apply_fixes_cump_exits_and_logs(self):
        out_mv = self._inflate()
        text = _run('--apply')
        self.assertIn('APPLICATION', text)
        self.stock.refresh_from_db()
        out_mv.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('100000.0000'))
        self.assertEqual(out_mv.unit_price, Decimal('100000.00'))
        self.assertEqual(self.stock.quantity, Decimal('4.000'))  # quantité jamais touchée
        self.assertEqual(ActivityLog.objects.filter(action__contains='CUMP').count(), 1)

    def test_clean_stock_unchanged(self):
        self._mv('ENTRY', '10.000', '200000.00')
        self._mv('ENTRY', '10.000', '220000.00')
        self.assertIn('inchangé', _run('--apply'))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('210000.0000'))
        self.assertFalse(ActivityLog.objects.filter(action__contains='CUMP').exists())

    def test_apply_twice_second_run_noop(self):
        self._inflate()
        _run('--apply')
        _run('--apply')
        self.assertEqual(ActivityLog.objects.filter(action__contains='CUMP').count(), 1)

    def test_apply_and_dry_run_conflict(self):
        with self.assertRaises(CommandError):
            _run('--apply', '--dry-run')

    def test_node_filter(self):
        other = make_node(code='K2')
        s2 = ConsumableStock.objects.create(node=other, consumable_type='FLOUR', quantity=Decimal('0'), unit='sac')
        ConsumableStock.objects.filter(pk=s2.pk).update(average_unit_cost=Decimal('999.0000'))
        self._inflate()
        _run('--apply', '--node', 'K1')
        s2.refresh_from_db()
        self.assertEqual(s2.average_unit_cost, Decimal('999.0000'))
