"""
BUG-085 (docs/qa/REGISTRE_BUGS.md) : `is_correction` (ajouté par BUG-083)
n'entrait pas dans la formule de hash du Livre de Caisse Direction — une
falsification directe en base de ce seul champ (ex.
``CashbookEntry.objects.filter(pk=x).update(is_correction=False)``) ne
cassait pas la chaîne et n'était donc pas détectée par
`verify_cashbook_chain`/`integrity_check`/`blockchain.run_check`.

Reproduction exacte de la fiche BUG-085 :
1. Pousser une écriture normale (is_correction=False).
2. Ajouter une écriture de correction (is_correction=True).
3. Falsifier directement en base le champ `is_correction` de la correction
   (le faire passer à False) — sans toucher à aucun autre champ.
4. Avant le correctif : `verify_cashbook_chain` ne signale rien (ce test
   échouait). Après : la rupture est détectée à la bonne écriture.

Couvre aussi le contrôle explicite demandé par la mission : vérifie, avec
des chiffres réels, le comportement de la migration de données
`0014_bug085_recompute_hash_is_correction` sur un jeu d'écritures mêlant
`is_correction=False`/`True`.
"""
import importlib
from decimal import Decimal

from django.apps import apps as global_apps
from django.test import TestCase

from core.models import Node
from treasury.hashing import (
    GENESIS_HASH,
    compute_cashbook_entry_hash,
    compute_v2_hash,
    verify_cashbook_chain,
)
from treasury.models import CashbookEntry
from treasury.views import append_cashbook_entry

# `0014_...` n'est pas un identifiant Python valide : import par nom de
# module complet (comme le fait Django lui-même pour appliquer les
# migrations), plutôt qu'un `from ... import ...` littéral.
_migration_0014 = importlib.import_module(
    'treasury.migrations.0014_bug085_recompute_hash_is_correction'
)
recompute_v3_hash = _migration_0014.recompute_v3_hash


def _make_node(code='K1', name='K1 - TABORA'):
    return Node.objects.create(code=code, name=name)


class IsCorrectionTamperingDetectedTests(TestCase):
    """Scénario de reproduction exact de la fiche BUG-085."""

    def setUp(self):
        self.node = _make_node()

    def _append(self, i, is_correction=False):
        return append_cashbook_entry(
            node=self.node,
            date='2026-10-01',
            piece_number=f'VC-BUG085-{i:03d}',
            imputation='7000',
            label=f"Écriture {'de correction' if is_correction else 'normale'} #{i}",
            entry_amount=Decimal('1000.00'),
            exit_amount=Decimal('0.00'),
            node_origin=self.node.code,
            is_correction=is_correction,
        )

    def test_flipping_is_correction_directly_in_db_is_detected(self):
        normal = self._append(0, is_correction=False)
        correction = self._append(1, is_correction=True)
        self._append(2, is_correction=False)

        # Falsification directe en base du SEUL champ is_correction — aucun
        # autre champ touché.
        CashbookEntry.objects.filter(pk=correction.pk).update(is_correction=False)

        ordered = list(CashbookEntry.objects.order_by('date', 'created_at'))
        results = verify_cashbook_chain(ordered)

        self.assertTrue(results[0][2], "la première écriture ne doit pas être affectée")
        self.assertFalse(
            results[1][2],
            "la falsification de is_correction (True -> False) doit être détectée "
            "par verify_cashbook_chain (c'était le défaut signalé par BUG-085)."
        )
        self.assertFalse(
            results[2][2],
            "l'écriture suivante, chaînée sur le hash désormais incohérent, doit "
            "elle aussi être signalée."
        )

    def test_flipping_false_to_true_is_also_detected(self):
        """Symétrique : faire passer une écriture d'origine pour une
        correction (False -> True) doit être détecté de la même façon."""
        normal = self._append(0, is_correction=False)
        self._append(1, is_correction=False)

        CashbookEntry.objects.filter(pk=normal.pk).update(is_correction=True)

        ordered = list(CashbookEntry.objects.order_by('date', 'created_at'))
        results = verify_cashbook_chain(ordered)
        self.assertFalse(results[0][2])
        self.assertFalse(results[1][2])

    def test_treasury_and_blockchain_agree_on_is_correction_tampering(self):
        """Même vérification croisée que BUG-001 : les deux points d'entrée
        (treasury.integrity_check / blockchain.run_check) doivent donner le
        même verdict, puisqu'ils partagent la même fonction unique."""
        from blockchain.views import _verify_chain_for_node

        self._append(0, is_correction=False)
        correction = self._append(1, is_correction=True)

        CashbookEntry.objects.filter(pk=correction.pk).update(is_correction=False)

        stats = _verify_chain_for_node(self.node)
        self.assertFalse(stats['is_intact'])
        self.assertGreaterEqual(stats['tampered_count'], 1)


class MigrationRecomputeIsCorrectionTests(TestCase):
    """Vérifie, avec des chiffres réels, le comportement de la migration de
    données 0014 sur un jeu d'écritures construites manuellement avec
    l'ANCIENNE formule (v2, sans is_correction) — simulant l'état réel de la
    base avant cette migration."""

    def setUp(self):
        self.node = _make_node()

    def _build_v2_entry(self, i, previous_hash, is_correction=False):
        """Construit une CashbookEntry comme si elle avait été écrite avant
        BUG-085 : block_hash calculé avec la formule v2 (is_correction
        absent du payload), alors que la colonne is_correction, elle, existe
        déjà en base (BUG-083 appliqué avant BUG-085)."""
        entry = CashbookEntry(
            node=self.node,
            date='2026-10-01',
            piece_number=f'VC-MIG-{i:03d}',
            imputation='7000',
            label=f'Écriture {i}',
            entry_amount=Decimal('1000.00'),
            exit_amount=Decimal('0.00'),
            running_balance=Decimal('1000.00') * (i + 1),
            node_origin=self.node.code,
            previous_hash=previous_hash,
            is_correction=is_correction,
        )
        entry.block_hash = compute_v2_hash(entry, previous_hash=previous_hash)
        entry.save()
        return entry

    def test_migration_recomputes_all_hashes_but_keeps_logical_chain_valid(self):
        previous_hash = GENESIS_HASH
        entries = []
        # 3 écritures normales + 1 correction + 1 écriture normale : toutes
        # valides sous la formule v2 (simule une base saine avant BUG-085).
        for i, is_corr in enumerate([False, False, True, False, False]):
            entry = self._build_v2_entry(i, previous_hash, is_correction=is_corr)
            previous_hash = entry.block_hash
            entries.append(entry)

        old_hashes = {e.pk: e.block_hash for e in entries}
        is_correction_count = sum(1 for e in entries if e.is_correction)
        self.assertEqual(is_correction_count, 1)

        # Exécute la migration de données directement (même fonction que
        # celle appelée par `manage.py migrate`).
        recompute_v3_hash(global_apps, None)

        refreshed = list(CashbookEntry.objects.order_by('date', 'created_at'))
        self.assertEqual(len(refreshed), 5)

        changed = [e for e in refreshed if e.block_hash != old_hashes[e.pk]]
        # Constat documenté dans le rapport : ajouter une clé au payload JSON
        # (même valant `False`) change nécessairement le condensé SHA-256
        # pour TOUTE écriture du préfixe recalculé, y compris celles où
        # is_correction=False — il est impossible de "ne rien changer" au
        # sens octet-pour-octet tout en couvrant réellement le champ. La
        # garantie réelle attendue par BUG-085 n'est donc pas "même hash
        # qu'avant", mais : (a) le contenu LOGIQUE représenté par chaque
        # écriture non-correction reste inchangé (is_correction=False avant
        # et après), et (b) la chaîne recalculée est entièrement valide sous
        # la nouvelle formule, sans aucune rupture introduite par la
        # migration elle-même.
        self.assertEqual(
            len(changed), 5,
            "chaque écriture du préfixe recalculé doit recevoir un nouveau "
            "block_hash (payload v3 structurellement différent du payload v2), "
            "y compris les écritures is_correction=False."
        )

        # Chaque écriture non-correction garde sa valeur logique is_correction=False.
        for e in refreshed:
            if e.pk in (entries[0].pk, entries[1].pk, entries[3].pk, entries[4].pk):
                self.assertFalse(e.is_correction)
        self.assertTrue(CashbookEntry.objects.get(pk=entries[2].pk).is_correction)

        # La chaîne recalculée est intégralement valide sous la nouvelle formule.
        results = verify_cashbook_chain(refreshed)
        self.assertTrue(all(is_valid for _e, _h, is_valid in results))

        # Et chaque nouveau hash correspond bien à compute_cashbook_entry_hash
        # (formule v3), pas à un reliquat de la formule v2.
        prev = GENESIS_HASH
        for e in refreshed:
            expected = compute_cashbook_entry_hash(e, previous_hash=prev)
            self.assertEqual(e.block_hash, expected)
            prev = e.block_hash

    def test_migration_stops_at_first_v2_break_and_leaves_the_rest_untouched(self):
        """Si une rupture existait déjà sous l'ancienne formule (v2) avant
        la migration, celle-ci ne doit pas l'écraser silencieusement : seul
        le préfixe valide est recalculé."""
        previous_hash = GENESIS_HASH
        entries = []
        for i in range(4):
            entry = self._build_v2_entry(i, previous_hash, is_correction=(i == 2))
            previous_hash = entry.block_hash
            entries.append(entry)

        # Falsifie directement l'écriture d'index 1 (rupture déjà présente
        # sous la formule v2, avant même que la migration ne tourne).
        CashbookEntry.objects.filter(pk=entries[1].pk).update(entry_amount=Decimal('999999.00'))
        tampered_old_hash = CashbookEntry.objects.get(pk=entries[1].pk).block_hash
        hash_after_index2_before = CashbookEntry.objects.get(pk=entries[2].pk).block_hash
        hash_after_index3_before = CashbookEntry.objects.get(pk=entries[3].pk).block_hash

        recompute_v3_hash(global_apps, None)

        refreshed = {e.pk: e for e in CashbookEntry.objects.all()}
        # Index 0 (avant la rupture) a été recalculé en v3.
        self.assertEqual(
            refreshed[entries[0].pk].block_hash,
            compute_cashbook_entry_hash(refreshed[entries[0].pk], previous_hash=GENESIS_HASH),
        )
        # Index 1 (la rupture elle-même) et tout ce qui suit restent
        # intouchés par la migration (hash "v2 legacy" conservé tel quel).
        self.assertEqual(refreshed[entries[1].pk].block_hash, tampered_old_hash)
        self.assertEqual(refreshed[entries[2].pk].block_hash, hash_after_index2_before)
        self.assertEqual(refreshed[entries[3].pk].block_hash, hash_after_index3_before)
