"""
BUG-198 (suppression d'une clôture versée) et BUG-199 (ordre de chaînage
incohérent entre écriture et vérification) — ingenieur-blockchain, 2026-11-12.
Données fictives uniquement.
"""
import importlib
from datetime import date
from decimal import Decimal

from django.apps import apps as django_apps
from django.db.models import ProtectedError
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user
from treasury.hashing import verify_cashbook_chain
from treasury.models import CashClosure, CashbookEntry
from treasury.views import append_cashbook_entry


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _add(node, d, amount, piece, exit_amount='0'):
    return append_cashbook_entry(
        node=node, date=d, piece_number=piece, imputation='7000', label=piece,
        entry_amount=Decimal(amount), exit_amount=Decimal(exit_amount), node_origin=node.code,
    )


class OutOfDateOrderChainTests(TestCase):
    """BUG-199."""

    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.comptable = make_user('COMPTABLE', username='c_199')
        self.api = _api(self.comptable)

    def _verdicts(self):
        a = self.api.get('/api/treasury/cashbook/integrity_check/').json()
        b = self.api.post('/api/blockchain/snapshots/run_check/', {}, format='json').json()
        return a, b

    def test_older_date_appended_after_newer_date_is_intact(self):
        e1 = _add(self.k1, date(2026, 11, 12), '1000', 'P1')       # J+1 de K1 d'abord
        e2 = _add(self.k2, date(2026, 11, 11), '500', 'P2')        # puis J de K2
        e3 = _add(self.k1, date(2026, 11, 10), '200', 'P3', exit_amount='50')
        self.assertEqual([e1.chain_seq, e2.chain_seq, e3.chain_seq], [1, 2, 3])
        # solde progressif suivant l'ordre de chaînage
        self.assertEqual(e2.running_balance, Decimal('1500.00'))
        self.assertEqual(e3.running_balance, Decimal('1650.00'))
        self.assertEqual(e2.previous_hash, e1.block_hash)
        a, b = self._verdicts()
        self.assertTrue(a['chain_valid'], a)
        self.assertEqual(a['tampered_count'], 0)
        self.assertTrue(b['all_intact'], b)

    def test_real_tampering_still_detected_at_right_entry_with_odd_dates(self):
        _add(self.k1, date(2026, 11, 12), '1000', 'P1')
        e2 = _add(self.k2, date(2026, 11, 11), '500', 'P2')
        _add(self.k1, date(2026, 11, 10), '200', 'P3')
        CashbookEntry.objects.filter(pk=e2.pk).update(entry_amount=Decimal('9999'))
        a, b = self._verdicts()
        self.assertFalse(a['chain_valid'])
        self.assertEqual(a['tampered_ids'][0], str(e2.id))
        self.assertFalse(b['all_intact'])

    def test_verify_function_on_chain_order_is_valid(self):
        for i in range(10):
            _add(self.k1 if i % 2 else self.k2, date(2026, 11, 20 - i), '10', f'T{i}')
        res = verify_cashbook_chain(CashbookEntry.chain_queryset())
        self.assertTrue(all(ok for _e, _x, ok in res))

    def test_backfill_migration_numbers_existing_entries_without_rewriting_hashes(self):
        entries = [_add(self.k1, date(2026, 11, 12 - i), '10', f'M{i}') for i in range(5)]
        hashes = {e.pk: (e.block_hash, e.previous_hash) for e in entries}
        CashbookEntry.objects.update(chain_seq=None)
        mod = importlib.import_module('treasury.migrations.0016_bug198_199_chain_seq_protect_closure')
        mod.backfill_chain_seq(django_apps, None)
        for i, e in enumerate(entries, start=1):
            e.refresh_from_db()
            self.assertEqual(e.chain_seq, i)
            self.assertEqual((e.block_hash, e.previous_hash), hashes[e.pk])
        self.assertTrue(self.api.get('/api/treasury/cashbook/integrity_check/').json()['chain_valid'])
        mod.clear_chain_seq(django_apps, None)
        self.assertEqual(CashbookEntry.objects.filter(chain_seq__isnull=False).count(), 0)


class ClosureDeletionTests(TestCase):
    """BUG-198."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.other = make_node(code='K2')
        self.gerant = make_user('GERANT', node=self.node, username='g_198')
        self.gerant2 = make_user('GERANT', node=self.other, username='g2_198')
        self.comptable = make_user('COMPTABLE', username='c_198')
        self.api = _api(self.gerant)
        self.api_c = _api(self.comptable)

    def _closure(self, validated=False, pushed=False):
        c = CashClosure.objects.create(node=self.node, date=date(2026, 11, 11), gerant=self.gerant,
                                       node_origin='K1', total_entries=Decimal('1500'), total_expenses=Decimal('0'), bills_1000=1, bills_500=1)
        c.compute_physical_cash()
        c.is_validated = validated or pushed
        c.save()
        if pushed:
            r = self.api_c.post(f'/api/treasury/closures/{c.pk}/push_to_cashbook/', {}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
        return c

    def test_validated_and_pushed_closure_cannot_be_deleted(self):
        c = self._closure(pushed=True)
        r = self.api.delete(f'/api/treasury/closures/{c.pk}/')
        self.assertEqual(r.status_code, 403, r.content)
        self.assertIn('interdite', r.json()['detail'])
        self.assertTrue(CashClosure.objects.filter(pk=c.pk).exists())
        self.assertEqual(CashbookEntry.objects.get().source_closure_id, c.pk)
        self.assertTrue(self.api_c.get('/api/treasury/cashbook/integrity_check/').json()['chain_valid'])

    def test_validated_not_pushed_closure_cannot_be_deleted(self):
        c = self._closure(validated=True)
        self.assertEqual(self.api.delete(f'/api/treasury/closures/{c.pk}/').status_code, 403)
        self.assertTrue(CashClosure.objects.filter(pk=c.pk).exists())

    def test_unvalidated_unpushed_closure_deletable_by_own_gerant_only(self):
        c = self._closure()
        self.assertEqual(_api(self.gerant2).delete(f'/api/treasury/closures/{c.pk}/').status_code, 404)
        self.assertTrue(CashClosure.objects.filter(pk=c.pk).exists())
        self.assertEqual(self.api.delete(f'/api/treasury/closures/{c.pk}/').status_code, 204)
        self.assertFalse(CashClosure.objects.filter(pk=c.pk).exists())

    def test_model_level_protect_blocks_cascade_but_ordered_reset_works(self):
        c = self._closure(pushed=True)
        with self.assertRaises(ProtectedError):
            c.delete()
        with self.assertRaises(ProtectedError):
            CashClosure.objects.filter(pk=c.pk).delete()
        # remise à zéro : livre d'abord, puis clôtures
        CashbookEntry.objects.all().delete()
        CashClosure.objects.all().delete()
        self.assertEqual(CashClosure.objects.count(), 0)
