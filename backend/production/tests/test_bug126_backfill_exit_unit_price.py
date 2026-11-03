"""
BUG-126 (vérification de BUG-123 par auditeur-comptable, 2026-11-02/03) :
la migration de rattrapage `0018_bug123_backfill_average_unit_cost`
recalculait le CUMP final de `ConsumableStock.average_unit_cost` mais ne
restampait jamais `unit_price` sur les `ConsumableMovement` de type EXIT
déjà en base avant le correctif BUG-123 — ces sorties historiques restaient
valorisées à 0.00 dans le Compte de Résultat pour toujours, puisque
`finance.views._income_statement_for_year` lit `ConsumableMovement.unit_price`
ligne par ligne, pas le CUMP courant du stock.

Ce test rejoue le scénario exact de l'auditeur : une sortie historique
forcée à `unit_price=0` (simulant une ligne créée avant le correctif),
encadrée par deux entrées à des prix différents — pour prouver que la
migration corrigée restampe chaque sortie avec le CUMP CHRONOLOGIQUE de
l'instant où elle a eu lieu, pas le CUMP final du stock (qui diffère ici).
Échouait avant la correction de `0018` (EXIT1 restait à 0.00), passe après.
"""
from decimal import Decimal
from importlib import import_module

from django.apps import apps as real_apps
from django.test import TestCase

from core.testing import make_node
from production.models import ConsumableStock, ConsumableMovement

_migration_0018 = import_module(
    'production.migrations.0018_bug123_backfill_average_unit_cost'
)


class Bug126BackfillExitUnitPriceTests(TestCase):
    def setUp(self):
        self.node = make_node()
        self.stock = ConsumableStock.objects.create(
            node=self.node, consumable_type='FLOUR', quantity=Decimal('0.000'), unit='sac',
        )

    def test_historical_exit_is_restamped_with_its_chronological_cump_not_the_final_one(self):
        entry_a = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('100000.00'),
        )
        exit_1 = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='EXIT',
            quantity=Decimal('4.000'),
        )
        # Simule une ligne historique créée avant le correctif BUG-123
        # (ancien défaut : _record_consumable_exits ne renseignait jamais
        # unit_price) — bypass volontaire de save() pour forcer l'état
        # pré-correctif, sans passer par la logique de calcul déjà corrigée.
        ConsumableMovement.objects.filter(pk=exit_1.pk).update(unit_price=Decimal('0.00'))

        entry_b = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('200000.00'),
        )
        exit_2 = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='EXIT',
            quantity=Decimal('5.000'),
        )

        exit_1.refresh_from_db()
        self.assertEqual(exit_1.unit_price, Decimal('0.00'), "précondition : ligne historique dégradée")

        # (6x100000 + 10x200000) / 16 = 162500
        final_cump = Decimal('162500.0000')
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, final_cump)

        _migration_0018.backfill_average_unit_cost(real_apps, None)

        exit_1.refresh_from_db()
        exit_2.refresh_from_db()
        self.stock.refresh_from_db()

        # EXIT1 a eu lieu APRÈS la seule ENTRY A (CUMP = 100000 à cet
        # instant) — jamais le CUMP final (162500) ni 0.
        self.assertEqual(exit_1.unit_price, Decimal('100000.00'))
        self.assertNotEqual(exit_1.unit_price, final_cump)
        # EXIT2 a eu lieu après ENTRY B, son CUMP chronologique est bien le
        # CUMP final du stock dans ce scénario (rien après lui).
        self.assertEqual(exit_2.unit_price, final_cump)
        self.assertEqual(self.stock.average_unit_cost, final_cump)

    def test_reverse_migration_resets_average_cost_and_historical_exit_prices(self):
        ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='ENTRY',
            quantity=Decimal('10.000'), unit_price=Decimal('100000.00'),
        )
        exit_mv = ConsumableMovement.objects.create(
            node=self.node, stock=self.stock, movement_type='EXIT',
            quantity=Decimal('4.000'),
        )
        _migration_0018.reset_average_unit_cost(real_apps, None)

        self.stock.refresh_from_db()
        exit_mv.refresh_from_db()
        self.assertEqual(self.stock.average_unit_cost, Decimal('0.0000'))
        self.assertEqual(exit_mv.unit_price, Decimal('0.00'))
