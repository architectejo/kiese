"""
Verification independante BUG-199 (ordre de chainage Livre de caisse) -
testeur-tresorerie, 2026-11-21 (Dev C). Donnees fictives uniquement.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user
from treasury import hashing as treasury_hashing
from treasury import views as treasury_views
from treasury.models import CashbookEntry
from treasury.views import append_cashbook_entry, _get_last_balance
from blockchain import views as blockchain_views


def _add(node, d, amount, piece, exit_amount='0'):
    return append_cashbook_entry(
        node=node, date=d, piece_number=piece, imputation='7000', label=piece,
        entry_amount=Decimal(amount), exit_amount=Decimal(exit_amount), node_origin=node.code,
    )


class Bug199IndependentTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.k3 = make_node(code='K3')
        self.api = APIClient()
        self.api.force_authenticate(make_user('COMPTABLE', username='c_v199'))

    def _verdicts(self):
        a = self.api.get('/api/treasury/cashbook/integrity_check/').json()
        b = self.api.post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        return a, b

    def test_single_hash_function_shared(self):
        self.assertIs(treasury_views.verify_cashbook_chain, treasury_hashing.verify_cashbook_chain)
        self.assertIs(blockchain_views.verify_cashbook_chain, treasury_hashing.verify_cashbook_chain)
        self.assertIs(treasury_views.compute_cashbook_entry_hash, treasury_hashing.compute_cashbook_entry_hash)

    def test_same_date_many_entries_chain_valid(self):
        d = date(2026, 11, 10)
        for i in range(12):
            _add([self.k1, self.k2, self.k3][i % 3], d, '100', f'S{i}', exit_amount='10' if i % 4 == 0 else '0')
        a, b = self._verdicts()
        self.assertTrue(a['chain_valid'], a)
        self.assertTrue(b['all_intact'], b)
        last = CashbookEntry.chain_queryset().last()
        self.assertEqual(last.running_balance, Decimal('1200') - Decimal('30'))

    def test_get_last_balance_follows_chain_not_date(self):
        _add(self.k1, date(2026, 11, 20), '1000', 'A')
        e2 = _add(self.k2, date(2026, 11, 1), '500', 'B')   # retroactive, appended last
        with transaction.atomic():
            bal, h = _get_last_balance()
        self.assertEqual(bal, Decimal('1500.00'))
        self.assertEqual(h, e2.block_hash)

    def test_retroactive_interleaving_30_entries_all_endpoints_agree(self):
        days = [25, 3, 18, 3, 30, 1, 12, 12, 7, 28]
        for i in range(30):
            node = [self.k1, self.k2, self.k3][i % 3]
            _add(node, date(2026, 10, days[i % 10]), '50', f'R{i}', exit_amount='5' if i % 5 == 0 else '0')
        a, b = self._verdicts()
        self.assertTrue(a['chain_valid'], a)
        self.assertTrue(b['all_intact'], b)
        self.assertEqual(a['total_entries'], 30)

    def test_tamper_amount_detected_by_both_endpoints(self):
        es = [_add(self.k1, date(2026, 11, 12 - i), '10', f'T{i}') for i in range(6)]
        CashbookEntry.objects.filter(pk=es[3].pk).update(entry_amount=Decimal('999'))
        a, b = self._verdicts()
        self.assertFalse(a['chain_valid'])
        self.assertFalse(b['all_intact'])
        self.assertEqual(a['tampered_ids'][0], str(es[3].id))

    def test_tamper_date_only_detected(self):
        es = [_add(self.k1, date(2026, 11, 12), '10', f'D{i}') for i in range(4)]
        CashbookEntry.objects.filter(pk=es[1].pk).update(date=date(2026, 11, 13))
        a, _b = self._verdicts()
        self.assertFalse(a['chain_valid'])

    def test_swapping_chain_seq_detected(self):
        e1 = _add(self.k1, date(2026, 11, 12), '10', 'W1')
        e2 = _add(self.k1, date(2026, 11, 12), '20', 'W2')
        CashbookEntry.objects.filter(pk=e1.pk).update(chain_seq=99)
        CashbookEntry.objects.filter(pk=e2.pk).update(chain_seq=1)
        CashbookEntry.objects.filter(pk=e1.pk).update(chain_seq=2)
        a, _b = self._verdicts()
        self.assertFalse(a['chain_valid'])

    def test_middle_deletion_detected(self):
        es = [_add(self.k1, date(2026, 11, 12), '10', f'X{i}') for i in range(5)]
        CashbookEntry.objects.filter(pk=es[2].pk).delete()
        a, b = self._verdicts()
        self.assertFalse(a['chain_valid'])
        self.assertFalse(b['all_intact'])

    def test_tail_deletion_detected_by_head_anchor(self):
        es = [_add(self.k1, date(2026, 11, 12), '10', f'Y{i}') for i in range(3)]
        CashbookEntry.objects.filter(pk=es[2].pk).delete()
        a, _b = self._verdicts()
        self.assertFalse(a['chain_valid'])
        self.assertTrue(a['head_problem'])

    def test_bulk_inserted_entry_without_chain_seq_detected(self):
        _add(self.k1, date(2026, 11, 12), '10', 'Z1')
        last = _add(self.k1, date(2026, 11, 12), '10', 'Z2')
        rogue = CashbookEntry(
            node=self.k1, date=date(2026, 11, 13), piece_number='ROGUE', imputation='7000',
            label='rogue', entry_amount=Decimal('5'), exit_amount=Decimal('0'),
            running_balance=Decimal('25'), previous_hash=last.block_hash, block_hash='f' * 64,
            node_origin='K1',
        )
        CashbookEntry.objects.bulk_create([rogue])
        a, _b = self._verdicts()
        self.assertFalse(a['chain_valid'])

    def test_collision_retry_keeps_chain_linear(self):
        """Simule une ecriture concurrente : la 1re lecture du dernier bloc est perimee."""
        _add(self.k1, date(2026, 11, 12), '100', 'C1')
        state = {'done': False}
        real = treasury_views._get_last_balance

        def flaky():
            if not state['done']:
                state['done'] = True
                return Decimal('0'), treasury_hashing.GENESIS_HASH   # lecture perimee
            return real()

        with mock.patch.object(treasury_views, '_get_last_balance', flaky):
            e2 = _add(self.k2, date(2026, 11, 11), '50', 'C2')
        self.assertEqual(e2.running_balance, Decimal('150.00'))
        self.assertEqual(CashbookEntry.objects.filter(previous_hash=treasury_hashing.GENESIS_HASH).count(), 1)
        a, b = self._verdicts()
        self.assertTrue(a['chain_valid'], a)
        self.assertTrue(b['all_intact'], b)

    def test_chain_seq_unique_constraint(self):
        e = _add(self.k1, date(2026, 11, 12), '10', 'U1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            CashbookEntry.objects.create(
                node=self.k1, date=date(2026, 11, 12), piece_number='U2', imputation='7000',
                label='u2', entry_amount=Decimal('1'), exit_amount=Decimal('0'),
                running_balance=Decimal('11'), previous_hash='a', block_hash='b', chain_seq=e.chain_seq,
                node_origin='K1',
            )
