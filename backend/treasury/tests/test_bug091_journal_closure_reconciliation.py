"""
BUG-091 (remarque.md l.384-385) : le Journal de Caisse par Boulangerie
(§5.1.4, imputation « Recettes du jour (CA) ») doit se rapprocher
automatiquement de la CashClosure (Niveau 2, §5.5) du même (nœud, date),
au lieu d'exiger une ressaisie manuelle non confrontée.

Décision du coordinateur (implémentée telle quelle) :
- Pré-remplissage/rapprochement automatique via CashClosure.total_entries
  si une clôture existe pour ce (nœud, date).
- Jamais de blocage : l'utilisateur reste libre du montant saisi.
- Écart avec la clôture -> SystemNotification WARNING, sauvegarde réussie.
- Pas de clôture -> écriture acceptée, marquée `is_reconciled=False`
  (« non rapprochée »).
- Seule l'imputation 'CA' est concernée ; les autres restent manuelles.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user
from treasury.models import CashClosure, JournalEntry


class JournalCaReconciliationTests(TestCase):

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant1')
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)

    def _make_closure(self, date_str, total_entries, total_expenses=Decimal('0.00')):
        closure = CashClosure.objects.create(
            node=self.node, gerant=self.gerant, date=date_str,
            node_origin=self.node.code,
            total_entries=total_entries, total_expenses=total_expenses,
        )
        closure.compute_physical_cash()
        closure.save(update_fields=['net_cash', 'physical_cash_total', 'cash_gap'])
        return closure

    def test_ca_entry_reconciled_with_existing_closure_matching_amount(self):
        """Avant ce correctif : aucune confrontation n'existait du tout."""
        closure = self._make_closure('2026-10-20', Decimal('150000.00'))

        resp = self.api.post('/api/treasury/journal/', {
            'date': '2026-10-20', 'imput': 'CA', 'label': 'Recettes du jour',
            'entry_amount': '150000.00', 'exit_amount': '0.00',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        entry = JournalEntry.objects.get(pk=resp.data['id'])
        self.assertTrue(entry.is_reconciled)
        self.assertEqual(entry.reconciled_closure_id, closure.id)
        self.assertEqual(entry.reconciliation_gap, Decimal('0.00'))
        self.assertTrue(resp.data['is_reconciled'])
        self.assertEqual(resp.data['reconciliation_gap'], '0.00')

        # Pas d'avertissement si le montant correspond exactement.
        self.assertFalse(
            SystemNotification.objects.filter(title__icontains='Écart Journal de Caisse').exists()
        )

    def test_ca_entry_amount_can_be_edited_and_mismatch_warns_without_blocking(self):
        """
        Règle 2/3 de BUG-091 : l'utilisateur reste libre de modifier le
        montant ; un écart avec la Clôture avertit mais n'empêche jamais
        la sauvegarde (cohérent avec BUG-083 « Autoriser et avertir »).
        """
        self._make_closure('2026-10-21', Decimal('200000.00'))

        resp = self.api.post('/api/treasury/journal/', {
            'date': '2026-10-21', 'imput': 'CA', 'label': 'Recettes du jour',
            'entry_amount': '180000.00', 'exit_amount': '0.00',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        entry = JournalEntry.objects.get(pk=resp.data['id'])
        self.assertTrue(entry.is_reconciled)
        self.assertEqual(entry.entry_amount, Decimal('180000.00'))
        self.assertEqual(entry.reconciliation_gap, Decimal('-20000.00'))

        notif = SystemNotification.objects.filter(title__icontains='Écart Journal de Caisse').first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.severity, 'WARNING')
        self.assertIn('20', notif.message)

    def test_ca_entry_without_existing_closure_is_not_blocked_and_marked_unreconciled(self):
        """Règle 4 de BUG-091 : pas de clôture -> pas de blocage, juste l'information."""
        self.assertFalse(CashClosure.objects.filter(node=self.node, date='2026-10-22').exists())

        resp = self.api.post('/api/treasury/journal/', {
            'date': '2026-10-22', 'imput': 'CA', 'label': 'Recettes du jour',
            'entry_amount': '90000.00', 'exit_amount': '0.00',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        entry = JournalEntry.objects.get(pk=resp.data['id'])
        self.assertFalse(entry.is_reconciled)
        self.assertIsNone(entry.reconciled_closure_id)
        self.assertEqual(entry.reconciliation_gap, Decimal('0.00'))
        self.assertFalse(resp.data['is_reconciled'])

        # Aucun avertissement d'écart tant qu'il n'y a rien à confronter.
        self.assertFalse(
            SystemNotification.objects.filter(title__icontains='Écart Journal de Caisse').exists()
        )

    def test_non_ca_imputation_untouched_by_reconciliation(self):
        """Seule l'imputation CA est concernée — les autres restent manuelles."""
        self._make_closure('2026-10-23', Decimal('100000.00'))

        resp = self.api.post('/api/treasury/journal/', {
            'date': '2026-10-23', 'imput': 'RATION', 'label': 'Ration boulangers',
            'entry_amount': '0.00', 'exit_amount': '15000.00',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        entry = JournalEntry.objects.get(pk=resp.data['id'])
        self.assertFalse(entry.is_reconciled)
        self.assertIsNone(entry.reconciled_closure_id)
        self.assertEqual(entry.reconciliation_gap, Decimal('0.00'))

    def test_suggested_ca_endpoint_exposes_closure_amount_for_prefill(self):
        """Point 5 de la proposition d'architecture : GET pour pré-remplissage frontend."""
        closure = self._make_closure('2026-10-24', Decimal('123456.00'))

        resp = self.api.get('/api/treasury/journal/suggested_ca/', {
            'node': str(self.node.id), 'date': '2026-10-24',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data['available'])
        self.assertEqual(resp.data['amount'], '123456.00')
        self.assertEqual(resp.data['closure_id'], str(closure.id))

    def test_suggested_ca_endpoint_reports_unavailable_without_closure(self):
        resp = self.api.get('/api/treasury/journal/suggested_ca/', {
            'node': str(self.node.id), 'date': '2026-10-25',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data['available'])
        self.assertIsNone(resp.data['amount'])
