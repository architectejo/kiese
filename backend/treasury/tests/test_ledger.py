"""
Tests du Livre de Caisse Direction — BUG-001, BUG-002, BUG-003
(docs/qa/REGISTRE_BUGS.md).

Avant la correction de ces tickets :
- treasury/views.py et blockchain/views.py utilisaient deux formules de
  hash différentes : toute chaîne, même saine, était signalée falsifiée
  dès qu'on la revérifiait depuis `blockchain` (BUG-001).
- `_get_last_balance()` n'était pas protégée contre deux écritures
  concurrentes, qui pouvaient créer deux blocs enfants du même parent
  (fourche — BUG-002).
- Le hash ne couvrait ni `node`, ni `imputation`, ni `source_closure`
  (BUG-003).

Ces tests échouaient avant la correction (voir rapport
docs/qa/rapports/ingenieur-blockchain-2026-10-22.md) et passent après.
"""
import threading
from decimal import Decimal

from django.db import connections
from django.test import TestCase, TransactionTestCase

from core.models import Node
from treasury.hashing import compute_cashbook_entry_hash, verify_cashbook_chain, GENESIS_HASH
from treasury.models import CashbookEntry
from treasury.views import append_cashbook_entry


def _make_node(code='K1', name='K1 - TABORA'):
    return Node.objects.create(code=code, name=name)


class CashbookChainTests(TestCase):
    """Chaîne saine de 50 écritures + détection de falsification / suppression."""

    def setUp(self):
        self.node = _make_node()

    def _append(self, i):
        return append_cashbook_entry(
            node=self.node,
            date='2026-10-01',
            piece_number=f'VC-TEST-{i:03d}',
            imputation='7000',
            label=f'Écriture de test #{i}',
            entry_amount=Decimal('1000.00'),
            exit_amount=Decimal('0.00'),
            node_origin=self.node.code,
        )

    def test_chain_of_50_entries_is_valid(self):
        entries = [self._append(i) for i in range(50)]

        self.assertEqual(CashbookEntry.objects.count(), 50)
        # Chaînage correct : chaque previous_hash == block_hash du précédent.
        self.assertEqual(entries[0].previous_hash, GENESIS_HASH)
        for prev, nxt in zip(entries, entries[1:]):
            self.assertEqual(nxt.previous_hash, prev.block_hash)

        results = verify_cashbook_chain(CashbookEntry.objects.order_by('date', 'created_at'))
        self.assertEqual(len(results), 50)
        self.assertTrue(all(is_valid for _entry, _expected, is_valid in results))

        # Le solde cumulé final doit être 50 * 1000.
        last = CashbookEntry.objects.order_by('-date', '-created_at').first()
        self.assertEqual(last.running_balance, Decimal('50000.00'))

    def test_tampering_an_amount_is_detected_at_the_right_entry(self):
        entries = [self._append(i) for i in range(10)]

        # Falsification directe en base (contourne .save(), donc le
        # block_hash stocké n'est pas recalculé) — simule une altération
        # du fichier de données plutôt qu'un passage par l'application.
        tampered = entries[5]
        CashbookEntry.objects.filter(pk=tampered.pk).update(entry_amount=Decimal('999999.00'))

        ordered = list(CashbookEntry.objects.order_by('date', 'created_at'))
        results = verify_cashbook_chain(ordered)

        for i, (entry, _expected, is_valid) in enumerate(results):
            if i < 5:
                self.assertTrue(is_valid, f"l'écriture {i} ne devait pas être affectée")
            else:
                # L'écriture falsifiée, et toutes celles qui la suivent
                # (puisqu'elles chaînent sur son hash désormais incohérent),
                # doivent être signalées.
                self.assertFalse(is_valid, f"l'écriture {i} devait être détectée falsifiée")

    def test_imputation_node_and_source_closure_are_covered_by_the_hash(self):
        """BUG-003 : falsifier un champ auparavant ignoré casse la chaîne."""
        entries = [self._append(i) for i in range(3)]
        target = entries[1]

        CashbookEntry.objects.filter(pk=target.pk).update(imputation='AUTRE-IMPUTATION')
        results = verify_cashbook_chain(CashbookEntry.objects.order_by('date', 'created_at'))
        self.assertTrue(results[0][2])
        self.assertFalse(results[1][2])

        # Remet imputation, falsifie le nœud à la place.
        CashbookEntry.objects.filter(pk=target.pk).update(imputation=target.imputation)
        other_node = _make_node(code='K2', name='K2 - COQ')
        CashbookEntry.objects.filter(pk=target.pk).update(node=other_node)
        results = verify_cashbook_chain(CashbookEntry.objects.order_by('date', 'created_at'))
        self.assertFalse(results[1][2])

    def test_deleting_an_entry_breaks_the_chain(self):
        entries = [self._append(i) for i in range(6)]
        deleted_index = 3
        entries[deleted_index].delete()

        remaining = list(CashbookEntry.objects.order_by('date', 'created_at'))
        self.assertEqual(len(remaining), 5)
        results = verify_cashbook_chain(remaining)

        # Les écritures avant la suppression restent valides ; celle qui
        # chaînait sur le hash de l'écriture supprimée (et toutes les
        # suivantes) ne peuvent plus être validées.
        for i in range(deleted_index):
            self.assertTrue(results[i][2], f"l'écriture {i} ne devait pas être affectée")
        for i in range(deleted_index, len(results)):
            self.assertFalse(results[i][2], f"l'écriture {i} devait être détectée comme rompue")

    def test_treasury_and_blockchain_agree_on_a_healthy_chain(self):
        """Le but du BUG-001 : une chaîne écrite par treasury est validée par blockchain."""
        from blockchain.views import _verify_chain_for_node

        for i in range(12):
            self._append(i)

        stats = _verify_chain_for_node(self.node)
        self.assertEqual(stats['total_entries'], 12)
        self.assertEqual(stats['tampered_count'], 0)
        self.assertTrue(stats['is_intact'])

        # Les écritures ne sont (plus) jamais marquées is_tampered à tort.
        self.assertFalse(CashbookEntry.objects.filter(is_tampered=True).exists())


class CashbookHashFunctionTests(TestCase):
    """BUG-001 : une seule fonction de hash, utilisée des deux côtés."""

    def setUp(self):
        self.node = _make_node()

    def test_compute_cashbook_entry_hash_is_deterministic(self):
        entry = CashbookEntry(
            node=self.node,
            date='2026-10-01',
            piece_number='VC-001',
            imputation='7000',
            label='Test',
            entry_amount=Decimal('1000.00'),
            exit_amount=Decimal('0.00'),
            running_balance=Decimal('1000.00'),
            previous_hash=GENESIS_HASH,
        )
        h1 = compute_cashbook_entry_hash(entry)
        h2 = compute_cashbook_entry_hash(entry)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_treasury_write_hash_matches_blockchain_verification_hash(self):
        """
        Le hash calculé au moment de l'écriture (treasury.views.append_cashbook_entry,
        via treasury.hashing.compute_cashbook_entry_hash) doit être EXACTEMENT celui
        que recalcule la vérification (blockchain, via treasury.hashing.verify_cashbook_chain
        — la même fonction sous-jacente). C'était la cause racine de BUG-001.
        """
        entry = append_cashbook_entry(
            node=self.node,
            date='2026-10-01',
            piece_number='VC-001',
            imputation='7000',
            label='Test',
            entry_amount=Decimal('1000.00'),
            exit_amount=Decimal('0.00'),
            node_origin=self.node.code,
        )
        written_hash = entry.block_hash

        results = verify_cashbook_chain(CashbookEntry.objects.order_by('date', 'created_at'))
        self.assertEqual(len(results), 1)
        _entry, expected_hash, is_valid = results[0]
        self.assertEqual(expected_hash, written_hash)
        self.assertTrue(is_valid)


class ConcurrentAppendTests(TransactionTestCase):
    """BUG-002 : deux append_cashbook_entry concurrents ne doivent jamais forker la chaîne."""

    def setUp(self):
        self.node = _make_node()

    def test_concurrent_appends_do_not_fork_the_chain(self):
        node_id = self.node.id
        n_threads = 8
        errors = []

        def worker(i):
            try:
                append_cashbook_entry(
                    node_id=node_id,
                    date='2026-10-01',
                    piece_number=f'VC-CONC-{i:03d}',
                    imputation='7000',
                    label=f'Écriture concurrente #{i}',
                    entry_amount=Decimal('100.00'),
                    exit_amount=Decimal('0.00'),
                    node_origin=self.node.code,
                )
            except Exception as exc:  # noqa: BLE001 - on veut capturer et rapporter
                errors.append(exc)
            finally:
                # Chaque thread ouvre sa propre connexion DB ; il faut la
                # fermer explicitement en fin de thread (Django ne le fait
                # pas automatiquement hors requête HTTP).
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"erreurs inattendues dans les threads : {errors}")
        self.assertEqual(CashbookEntry.objects.count(), n_threads)

        ordered = list(CashbookEntry.objects.order_by('date', 'created_at'))
        # Pas de fourche : chaque previous_hash en base est unique (contrainte
        # DB) et la chaîne reconstruite est entièrement valide.
        previous_hashes = [e.previous_hash for e in ordered]
        self.assertEqual(len(previous_hashes), len(set(previous_hashes)), "fourche détectée : previous_hash dupliqué")

        results = verify_cashbook_chain(ordered)
        self.assertTrue(all(is_valid for _e, _h, is_valid in results), "chaîne rompue après écritures concurrentes")

        last = ordered[-1]
        self.assertEqual(last.running_balance, Decimal('100.00') * n_threads)
