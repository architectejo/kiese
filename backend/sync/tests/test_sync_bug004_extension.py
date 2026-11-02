"""
Extension BUG-004 (docs/qa/REGISTRE_BUGS.md, 2026-11-02) : câblage dans
`sync.services.PUSH_HANDLERS` des modèles production/trésorerie restés hors
périmètre de la V1 (docs/architecture/SYNC.md §11) :
`ProductionSession`, `BreadTransfer`, `BreadDisposal`, `ConsumableMovement`
(production), `LocalExpense`, `FacturierReport`, `DisbursementVoucher`
(treasury).

`SocialContribution`/`SocialDistribution`/`SocialDistributionLine`
(clients) étaient initialement restées HORS PÉRIMÈTRE dans cette extension —
ce n'étaient pas des `SyncableModel` (PK entière, pas UUID), voir le rapport
d'extension pour le détail de cette contradiction signalée au coordinateur.
Après arbitrage, elles ont été migrées (PK UUID, `clients/migrations/0008_*`
et `0009_*`) et câblées à leur tour dans `PUSH_HANDLERS` — couvertes par
`backend/clients/tests/test_social.py` et
`backend/clients/tests/test_migration_social_uuid.py`, pas ici (ce fichier
reste dédié au périmètre production/trésorerie de cette extension). Le test
« modèle non supporté » ci-dessous a été réassigné à un modèle qui, lui,
reste réellement hors périmètre (`commissions.ClientCommission`), puisque
`clients.SocialContribution` est désormais accepté.
"""
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Node, BreadPrice, ExpenseCategory
from core.testing import make_node, make_bread_price
from sync.models import NodeAuthToken, SyncBatchLog
from production.models import (
    ProductionSession, ProductionSessionLine, BreadDisposal,
    ConsumableMovement, ConsumableStock, BreadTransfer, BreadTransferLine,
)
from treasury.models import LocalExpense, FacturierReport, DisbursementVoucher, CashbookEntry


def _node_client(node, raw_token):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw_token}')
    return api


def _issue_token(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    return _node_client(node, raw)


class ProductionSessionSyncTests(TestCase):
    """SYNC.md §3.5 point 4 : ProductionSession → ProductionSessionLine."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.api = _issue_token(self.node)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)

    def _session_payload(self, session_id, is_closed=False):
        return {
            'id': session_id, 'node': 'K1', 'team': 'A', 'date': date.today().isoformat(),
            'flour_sacks_used': '2.00', 'total_breads': 100, 'total_fc_produced': 50000,
            'theoretical_yield': 400000, 'yield_gap': -350000, 'sac_value_fc_used': 200000,
            'is_closed': is_closed, 'notes': '', 'node_origin': 'K1',
        }

    def test_session_then_line_are_accepted_in_dependency_order(self):
        # Comme `InvoiceLine` (précédent établi, sales/models.py), `Production
        # SessionLine` est un `models.Model` à PK entière auto-incrémentée
        # LOCALE AU NŒUD (pas un `SyncableModel`, pas d'UUID) — on n'envoie
        # jamais cette PK locale comme identifiant cross-nœud (collision
        # possible entre deux nœuds), on s'appuie sur `unique_together`
        # (session, bread_price) pour l'idempotence (voir rapport
        # d'extension, limitation déjà présente pour `InvoiceLine`).
        session_id = str(uuid.uuid4())
        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.ProductionSession': [self._session_payload(session_id)],
                'production.ProductionSessionLine': [
                    {'session': session_id, 'bread_price': self.bp.pk, 'quantity': 100},
                ],
            },
        }
        resp = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['results']['production.ProductionSession'][0]['status'], 'ACCEPTED')
        self.assertEqual(resp.data['results']['production.ProductionSessionLine'][0]['status'], 'ACCEPTED')
        self.assertTrue(ProductionSession.objects.filter(pk=session_id).exists())
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=session_id, bread_price=self.bp).count(), 1)

    def test_line_referencing_unknown_session_is_rejected_then_accepted_after_retry(self):
        """Coupure au milieu d'un lot (SYNC.md §3.4) : la ligne arrive avant
        sa session dans un lot mal formé → rejet explicite, jamais deviné,
        puis acceptation sans doublon une fois la session connue."""
        session_id = str(uuid.uuid4())
        line_payload = {'session': session_id, 'bread_price': self.bp.pk, 'quantity': 100}
        resp1 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ProductionSessionLine': [line_payload]},
        }, format='json')
        self.assertEqual(resp1.data['results']['production.ProductionSessionLine'][0]['status'], 'REJECTED')
        self.assertEqual(resp1.data['results']['production.ProductionSessionLine'][0]['reason'], 'dépendance manquante : session')

        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ProductionSession': [self._session_payload(session_id)]},
        }, format='json')

        resp2 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ProductionSessionLine': [line_payload]},
        }, format='json')
        self.assertEqual(resp2.data['results']['production.ProductionSessionLine'][0]['status'], 'ACCEPTED')
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=session_id, bread_price=self.bp).count(), 1)

        # Rejeu d'un 3e envoi identique (prudence après coupure) : toujours
        # un seul enregistrement, grâce à `unique_together`.
        resp3 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ProductionSessionLine': [line_payload]},
        }, format='json')
        self.assertEqual(resp3.data['results']['production.ProductionSessionLine'][0]['status'], 'ACCEPTED')
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=session_id, bread_price=self.bp).count(), 1)

    def test_closure_transition_is_idempotent_and_never_regresses(self):
        session_id = str(uuid.uuid4())
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ProductionSession': [self._session_payload(session_id, is_closed=False)]},
        }, format='json')

        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ProductionSession': [self._session_payload(session_id, is_closed=True)]},
        }, format='json')
        session = ProductionSession.objects.get(pk=session_id)
        self.assertTrue(session.is_closed)

        # Rejeu tardif d'un ancien lot "ouvert" : ne doit jamais rouvrir.
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ProductionSession': [self._session_payload(session_id, is_closed=False)]},
        }, format='json')
        session.refresh_from_db()
        self.assertTrue(session.is_closed)

    def test_replaying_the_same_batch_does_not_duplicate_the_session(self):
        session_id = str(uuid.uuid4())
        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ProductionSession': [self._session_payload(session_id)]},
        }
        self.api.post('/api/sync/push/', payload, format='json')
        self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(ProductionSession.objects.filter(pk=session_id).count(), 1)
        self.assertEqual(SyncBatchLog.objects.filter(batch_id=payload['batch_id']).count(), 1)


class BreadDisposalSyncTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.api = _issue_token(self.node)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.session = ProductionSession.objects.create(
            node=self.node, team='A', date=date.today(), node_origin='K1',
        )

    def test_disposal_is_accepted_and_total_value_is_recomputed_server_side(self):
        disposal_id = str(uuid.uuid4())
        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.BreadDisposal': [{
                    'id': disposal_id, 'node': 'K1', 'session': str(self.session.pk),
                    'bread_price': self.bp.pk, 'disposal_type': 'SOLD_DISCOUNT',
                    'quantity': 10, 'unit_price_sold': 300, 'node_origin': 'K1',
                }],
            },
        }
        resp = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp.data['results']['production.BreadDisposal'][0]['status'], 'ACCEPTED')
        disposal = BreadDisposal.objects.get(pk=disposal_id)
        self.assertEqual(disposal.total_value, Decimal('3000.00'))

    def test_replaying_does_not_duplicate(self):
        disposal_id = str(uuid.uuid4())
        record = {
            'id': disposal_id, 'node': 'K1', 'session': str(self.session.pk),
            'bread_price': self.bp.pk, 'disposal_type': 'UNSOLD', 'quantity': 5,
            'node_origin': 'K1',
        }
        self.api.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()), 'records': {'production.BreadDisposal': [record]}}, format='json')
        self.api.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()), 'records': {'production.BreadDisposal': [record]}}, format='json')
        self.assertEqual(BreadDisposal.objects.filter(pk=disposal_id).count(), 1)


class ConsumableMovementSyncTests(TestCase):
    """
    SYNC.md §2.4 : `ConsumableStock` n'est pas lui-même synchronisé — le
    Cloud maintient sa propre ligne consolidée par (nœud, consommable),
    alimentée uniquement par les `ConsumableMovement` reçus.
    """

    def setUp(self):
        self.node = make_node(code='K1')
        self.api = _issue_token(self.node)

    def test_entry_then_exit_are_accepted_and_stock_is_consolidated(self):
        entry_id = str(uuid.uuid4())
        exit_id = str(uuid.uuid4())

        resp1 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.ConsumableMovement': [{
                    'id': entry_id, 'node': 'K1', 'consumable_type': 'FLOUR', 'unit': 'sacs',
                    'movement_type': 'ENTRY', 'quantity': '10.000', 'node_origin': 'K1',
                }],
            },
        }, format='json')
        self.assertEqual(resp1.data['results']['production.ConsumableMovement'][0]['status'], 'ACCEPTED')

        resp2 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.ConsumableMovement': [{
                    'id': exit_id, 'node': 'K1', 'consumable_type': 'FLOUR', 'unit': 'sacs',
                    'movement_type': 'EXIT', 'quantity': '4.000', 'node_origin': 'K1',
                }],
            },
        }, format='json')
        self.assertEqual(resp2.data['results']['production.ConsumableMovement'][0]['status'], 'ACCEPTED')

        stock = ConsumableStock.objects.get(node=self.node, consumable_type='FLOUR')
        self.assertEqual(stock.quantity, Decimal('6.000'))

    def test_exit_without_matching_entry_is_rejected_as_missing_dependency_then_retried(self):
        """BUG-041 côté Cloud : une sortie ne doit jamais faire passer le
        stock consolidé en négatif — rejetée (dépendance manquante), jamais
        acceptée silencieusement, et acceptée sans doublon une fois
        l'entrée correspondante arrivée."""
        exit_id = str(uuid.uuid4())
        exit_record = {
            'id': exit_id, 'node': 'K1', 'consumable_type': 'SEL', 'unit': 'g',
            'movement_type': 'EXIT', 'quantity': '500.000', 'node_origin': 'K1',
        }
        resp1 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ConsumableMovement': [exit_record]},
        }, format='json')
        self.assertEqual(resp1.data['results']['production.ConsumableMovement'][0]['status'], 'REJECTED')
        self.assertFalse(ConsumableMovement.objects.filter(pk=exit_id).exists())

        entry_id = str(uuid.uuid4())
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.ConsumableMovement': [{
                    'id': entry_id, 'node': 'K1', 'consumable_type': 'SEL', 'unit': 'g',
                    'movement_type': 'ENTRY', 'quantity': '1000.000', 'node_origin': 'K1',
                }],
            },
        }, format='json')

        resp2 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'production.ConsumableMovement': [exit_record]},
        }, format='json')
        self.assertEqual(resp2.data['results']['production.ConsumableMovement'][0]['status'], 'ACCEPTED')
        self.assertEqual(ConsumableMovement.objects.filter(pk=exit_id).count(), 1)
        stock = ConsumableStock.objects.get(node=self.node, consumable_type='SEL')
        self.assertEqual(stock.quantity, Decimal('500.000'))


class BreadTransferSyncTests(TestCase):
    """
    SYNC.md §5.3 : chaque étape (PENDING→RESPONDED→CONFIRMED/DISPUTED)
    attend simplement son tour au prochain cycle de sync de chaque nœud —
    le Cloud consolide, il ne rejoue jamais `_adjust_bread_stock` lui-même.
    """

    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k4 = make_node(code='K4')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.api_k1 = _issue_token(self.k1)
        self.api_k4 = _issue_token(self.k4)

    def test_transfer_and_line_sync_then_status_progresses_forward_only(self):
        transfer_id = str(uuid.uuid4())

        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.BreadTransfer': [{
                    'id': transfer_id, 'from_node': 'K1', 'to_node': 'K4',
                    'transfer_status': 'PENDING', 'node_origin': 'K4',
                }],
                # `BreadTransferLine`, comme `ProductionSessionLine`, est une
                # PK entière auto-incrémentée LOCALE (pas de `SyncableModel`
                # — voir rapport d'extension) : on ne la pousse jamais avec
                # son id local, l'idempotence vient de `unique_together`
                # (transfer, bread_price).
                'production.BreadTransferLine': [{
                    'transfer': transfer_id, 'bread_price': self.bp.pk,
                    'quantity_sent': 50,
                }],
            },
        }
        resp = self.api_k4.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp.data['results']['production.BreadTransfer'][0]['status'], 'ACCEPTED')
        self.assertEqual(resp.data['results']['production.BreadTransferLine'][0]['status'], 'ACCEPTED')

        # K1 répond (RESPONDED) puis confirme la réception côté K4 (CONFIRMED) :
        # chaque transition poussée séparément, sans connexion simultanée.
        resp2 = self.api_k1.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.BreadTransfer': [{
                    'id': transfer_id, 'from_node': 'K1', 'to_node': 'K4',
                    'transfer_status': 'RESPONDED', 'node_origin': 'K1',
                }],
            },
        }, format='json')
        self.assertEqual(resp2.data['results']['production.BreadTransfer'][0]['status'], 'ACCEPTED')
        self.assertEqual(BreadTransfer.objects.get(pk=transfer_id).transfer_status, 'RESPONDED')

        resp3 = self.api_k4.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.BreadTransfer': [{
                    'id': transfer_id, 'from_node': 'K1', 'to_node': 'K4',
                    'transfer_status': 'CONFIRMED', 'quantity_received': 50, 'node_origin': 'K4',
                }],
            },
        }, format='json')
        self.assertEqual(resp3.data['results']['production.BreadTransfer'][0]['status'], 'ACCEPTED')
        transfer = BreadTransfer.objects.get(pk=transfer_id)
        self.assertEqual(transfer.transfer_status, 'CONFIRMED')

        # Rejeu tardif d'un statut antérieur : jamais de régression.
        self.api_k1.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.BreadTransfer': [{
                    'id': transfer_id, 'from_node': 'K1', 'to_node': 'K4',
                    'transfer_status': 'RESPONDED', 'node_origin': 'K1',
                }],
            },
        }, format='json')
        transfer.refresh_from_db()
        self.assertEqual(transfer.transfer_status, 'CONFIRMED')

    def test_transfer_line_update_does_not_duplicate_on_replay(self):
        transfer_id = str(uuid.uuid4())
        self.api_k4.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.BreadTransfer': [{
                    'id': transfer_id, 'from_node': 'K1', 'to_node': 'K4',
                    'transfer_status': 'PENDING', 'node_origin': 'K4',
                }],
                'production.BreadTransferLine': [{
                    'transfer': transfer_id, 'bread_price': self.bp.pk, 'quantity_sent': 50,
                }],
            },
        }, format='json')
        line = BreadTransferLine.objects.get(transfer_id=transfer_id, bread_price=self.bp)

        # Mise à jour ultérieure de la MÊME ligne (confirmation de réception,
        # SYNC.md §5.3) : cette fois identifiée par son id réel (déjà connu
        # du Cloud puisque la ligne existe désormais là-bas), rejouée deux
        # fois sans jamais dupliquer ni régresser la valeur reçue.
        update_payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.BreadTransferLine': [{
                    'id': line.pk, 'transfer': transfer_id, 'bread_price': self.bp.pk,
                    'quantity_sent': 50, 'quantity_received': 48,
                }],
            },
        }
        self.api_k4.post('/api/sync/push/', update_payload, format='json')
        self.api_k4.post('/api/sync/push/', dict(update_payload, batch_id=str(uuid.uuid4())), format='json')
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=transfer_id, bread_price=self.bp).count(), 1)
        self.assertEqual(BreadTransferLine.objects.get(pk=line.pk).quantity_received, 48)


class TreasuryExtensionSyncTests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.api = _issue_token(self.node)
        self.category = ExpenseCategory.objects.create(code='TEST-EXP', label='Dépense de test')

    def test_local_expense_push_is_accepted_and_idempotent(self):
        expense_id = str(uuid.uuid4())
        record = {
            'id': expense_id, 'node': 'K1', 'description': 'Essence', 'amount': '5000.00',
            'category': self.category.pk, 'date': date.today().isoformat(), 'node_origin': 'K1',
        }
        payload = {'batch_id': str(uuid.uuid4()), 'records': {'treasury.LocalExpense': [record]}}
        resp1 = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp1.data['results']['treasury.LocalExpense'][0]['status'], 'ACCEPTED')
        resp2 = self.api.post('/api/sync/push/', payload, format='json')
        self.assertTrue(resp2.data['replayed'])
        self.assertEqual(LocalExpense.objects.filter(pk=expense_id).count(), 1)

    def test_local_expense_missing_category_is_rejected_as_missing_dependency(self):
        expense_id = str(uuid.uuid4())
        bogus_category_id = 9999999
        record = {
            'id': expense_id, 'node': 'K1', 'description': 'Essence', 'amount': '5000.00',
            'category': bogus_category_id, 'date': date.today().isoformat(), 'node_origin': 'K1',
        }
        resp = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()), 'records': {'treasury.LocalExpense': [record]},
        }, format='json')
        self.assertEqual(resp.data['results']['treasury.LocalExpense'][0]['status'], 'REJECTED')
        self.assertFalse(LocalExpense.objects.filter(pk=expense_id).exists())

    def test_facturier_report_validation_transition_is_idempotent(self):
        report_id = str(uuid.uuid4())

        def _record(is_validated):
            return {
                'id': report_id, 'node': 'K1', 'team': 'A', 'date': date.today().isoformat(),
                'total_cash_sales': '10000.00', 'total_credit_sales': '0.00',
                'theoretical_cash': '10000.00', 'is_validated': is_validated, 'node_origin': 'K1',
            }

        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()), 'records': {'treasury.FacturierReport': [_record(False)]},
        }, format='json')
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()), 'records': {'treasury.FacturierReport': [_record(True)]},
        }, format='json')
        report = FacturierReport.objects.get(pk=report_id)
        self.assertTrue(report.is_validated)

        # Rejeu tardif d'un ancien lot "non validé" : jamais de régression.
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()), 'records': {'treasury.FacturierReport': [_record(False)]},
        }, format='json')
        report.refresh_from_db()
        self.assertTrue(report.is_validated)
        self.assertEqual(FacturierReport.objects.filter(pk=report_id).count(), 1)

    def test_disbursement_voucher_push_promotes_to_cashbook_once(self):
        """Symétrique de `_push_cash_closure` (SYNC.md §0) : c'est le Cloud,
        pas le nœud, qui écrit l'écriture du Livre de Caisse Direction."""
        from treasury.hashing import verify_cashbook_chain

        # Alimente le solde disponible via une clôture déjà promue, pour
        # que le bordereau (sortie) ne soit pas rejeté pour solde insuffisant.
        # `promote_closure_to_cashbook` réagrège `total_entries` à partir des
        # `FacturierReport` du (nœud, date) — on en pousse un pour que ce
        # réagrégat corresponde au montant attendu (comportement existant,
        # pas introduit par cette extension).
        today = date.today().isoformat()
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'treasury.FacturierReport': [{
                    'id': str(uuid.uuid4()), 'node': 'K1', 'team': 'A', 'date': today,
                    'total_cash_sales': '200000.00', 'node_origin': 'K1',
                }],
            },
        }, format='json')
        closure_id = str(uuid.uuid4())
        self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'treasury.CashClosure': [{
                    'id': closure_id, 'node': 'K1', 'date': today,
                    'total_entries': '200000.00', 'total_expenses': '0.00',
                    'is_validated': True, 'node_origin': 'K1',
                }],
            },
        }, format='json')

        voucher_id = str(uuid.uuid4())
        record = {
            'id': voucher_id, 'date': date.today().isoformat(), 'motif': 'Achat farine',
            'beneficiary': 'MIDEMA', 'bills_10000': 5, 'node_origin': 'CLOUD',
        }
        resp1 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()), 'records': {'treasury.DisbursementVoucher': [record]},
        }, format='json')
        self.assertEqual(resp1.data['results']['treasury.DisbursementVoucher'][0]['status'], 'ACCEPTED', resp1.data)

        voucher = DisbursementVoucher.objects.get(pk=voucher_id)
        self.assertEqual(voucher.cashbook_entries.count(), 1)

        resp2 = self.api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()), 'records': {'treasury.DisbursementVoucher': [record]},
        }, format='json')
        self.assertEqual(resp2.data['results']['treasury.DisbursementVoucher'][0]['status'], 'ACCEPTED')
        voucher.refresh_from_db()
        self.assertEqual(voucher.cashbook_entries.count(), 1)

        entries = list(CashbookEntry.objects.order_by('date', 'created_at'))
        results = verify_cashbook_chain(entries)
        self.assertTrue(all(is_valid for _entry, _expected, is_valid in results))


class UnsupportedModelsAreExplicitlyRejectedTests(TestCase):
    """
    `commissions.ClientCommission` reste hors périmètre de synchronisation
    (aucun handler dans `PUSH_HANDLERS`, bien que ce soit un `SyncableModel`
    comme les autres) : un nœud qui tenterait de le pousser reçoit un rejet
    explicite (SYNC.md §3.4), jamais un silence. (`clients.SocialContribution`
    servait auparavant d'exemple ici tant qu'elle n'était pas une
    `SyncableModel` — désormais acceptée, voir
    `clients/tests/test_social.py`/`test_migration_social_uuid.py`.)
    """

    def test_client_commission_push_is_rejected_as_unsupported(self):
        node = make_node(code='K1')
        api = _issue_token(node)
        resp = api.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {'commissions.ClientCommission': [{'id': str(uuid.uuid4())}]},
        }, format='json')
        self.assertEqual(resp.data['results']['commissions.ClientCommission'][0]['status'], 'REJECTED')
        self.assertEqual(resp.data['results']['commissions.ClientCommission'][0]['reason'], 'modèle non supporté en V1')
