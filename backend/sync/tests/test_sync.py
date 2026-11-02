"""
Tests du module de synchronisation Local ↔ Cloud — BUG-004
(docs/qa/REGISTRE_BUGS.md, docs/architecture/SYNC.md).

Couvre les scénarios obligatoires de la mission (SYNC.md §12) :
1. Deux nœuds facturant le même client hors-ligne -> dette correcte et
   commutative au Cloud.
2. Push rejoué deux fois (même batch_id) -> aucun doublon.
3. Coupure au milieu d'un lot (dépendance manquante puis retransmission)
   -> reprise sans perte ni doublon.
4. Changement de prix au Cloud pendant qu'un nœud est hors-ligne -> reçu
   par le nœud au pull suivant.
5. Clôture de caisse hors-ligne synchronisée après coup -> inscrite au
   Livre de Caisse Direction sans casser la chaîne de hash globale (SYNC.md §0).
"""
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Node, BreadPrice
from core.testing import make_node, make_client, make_bread_price
from clients.models import Client
from sync.models import NodeAuthToken, DebtMovement, SyncBatchLog, SyncConflictLog
from treasury.models import CashClosure, CashbookEntry
from treasury.hashing import verify_cashbook_chain


def _node_client(node, raw_token):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw_token}')
    return api


def _issue_token(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    return _node_client(node, raw)


class HandshakeAndAuthTests(TestCase):
    def test_handshake_requires_a_valid_node_token(self):
        api = APIClient()
        resp = api.post('/api/sync/handshake/')
        self.assertIn(resp.status_code, (401, 403))

    def test_handshake_accepts_a_valid_node_token_and_updates_last_sync(self):
        node = make_node(code='K1')
        self.assertIsNone(node.last_sync)
        api = _issue_token(node)
        resp = api.post('/api/sync/handshake/')
        self.assertEqual(resp.status_code, 200, resp.data)
        node.refresh_from_db()
        self.assertIsNotNone(node.last_sync)

    def test_a_revoked_token_is_rejected(self):
        node = make_node(code='K1')
        token, raw = NodeAuthToken.issue_for_node(node)
        token.revoke()
        api = _node_client(node, raw)
        resp = api.post('/api/sync/handshake/')
        # DRF : aucun authenticator n'a réussi (le jeton révoqué n'authentifie
        # personne) -> 401 (NotAuthenticated), pas 403 (PermissionDenied) —
        # sémantique DRF standard, pas une erreur d'implémentation.
        self.assertEqual(resp.status_code, 401)

    def test_a_user_jwt_cannot_call_sync_routes(self):
        """Un JWT utilisateur, même ADMIN, n'est jamais un jeton de nœud valide."""
        from core.testing import make_user
        node = make_node(code='K1')
        admin = make_user('ADMIN')
        api = APIClient()
        api.force_authenticate(user=admin)
        resp = api.post('/api/sync/handshake/')
        self.assertEqual(resp.status_code, 403)


class TwoNodesOfflineDebtScenarioTests(TestCase):
    """
    Scénario central (SYNC.md §2) : le client est facturé hors-ligne par
    deux boulangeries différentes. La dette consolidée au Cloud doit être
    la somme exacte des deux mouvements, quel que soit l'ordre d'arrivée
    des deux lots `push` — c'est la propriété de commutativité recherchée.
    """

    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.client_obj = make_client(self.k1, current_debt=Decimal('0.00'))
        self.api_k1 = _issue_token(self.k1)
        self.api_k2 = _issue_token(self.k2)

    def _push_order(self, api, node_code, amount):
        invoice_id = str(uuid.uuid4())
        movement_id = str(uuid.uuid4())
        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'sales.Invoice': [{
                    'id': invoice_id, 'node': node_code, 'client': str(self.client_obj.pk),
                    'status': 'DELIVERED', 'payment_type': 'CREDIT',
                    'order_total': str(amount), 'payment_amount': '0.00',
                    'debt_before': '0.00', 'debt_after': str(amount),
                    'receipt_number': f'{node_code}-TEST-{amount}',
                    'node_origin': node_code,
                }],
                'sync.DebtMovement': [{
                    'id': movement_id, 'client': str(self.client_obj.pk), 'invoice': invoice_id,
                    'amount': str(amount), 'kind': 'ORDER', 'node_origin': node_code,
                }],
            },
        }
        resp = api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        for model_results in resp.data['results'].values():
            for r in model_results:
                self.assertEqual(r['status'], 'ACCEPTED', r)
        return resp

    def test_debt_is_the_exact_sum_regardless_of_arrival_order_k1_then_k2(self):
        self._push_order(self.api_k1, 'K1', Decimal('5000.00'))
        self._push_order(self.api_k2, 'K2', Decimal('3000.00'))
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('8000.00'))

    def test_debt_is_the_exact_sum_regardless_of_arrival_order_k2_then_k1(self):
        self._push_order(self.api_k2, 'K2', Decimal('3000.00'))
        self._push_order(self.api_k1, 'K1', Decimal('5000.00'))
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('8000.00'))

    def test_category_is_refreshed_after_consolidation(self):
        """Un dépassement de plafond uniquement visible une fois les deux
        nœuds consolidés doit reclasser le client en RISK au Cloud."""
        self.client_obj.credit_limit = Decimal('6000.00')
        self.client_obj.save()
        self._push_order(self.api_k1, 'K1', Decimal('5000.00'))
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.category, Client.Category.NORMAL)

        self._push_order(self.api_k2, 'K2', Decimal('3000.00'))
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('8000.00'))
        self.assertEqual(self.client_obj.category, Client.Category.RISK)


class PushIdempotenceTests(TestCase):
    """Rejouer un lot déjà traité ne doit jamais produire de doublon (SYNC.md §3.3/§3.6)."""

    def setUp(self):
        self.node = make_node(code='K1')
        self.client_obj = make_client(self.node, current_debt=Decimal('0.00'))
        self.api = _issue_token(self.node)

    def _payload(self, batch_id, movement_id):
        return {
            'batch_id': batch_id,
            'records': {
                'sync.DebtMovement': [{
                    'id': movement_id, 'client': str(self.client_obj.pk),
                    'amount': '1000.00', 'kind': 'ORDER', 'node_origin': 'K1',
                }],
            },
        }

    def test_replaying_the_same_batch_id_does_not_duplicate_the_movement(self):
        batch_id = str(uuid.uuid4())
        movement_id = str(uuid.uuid4())
        payload = self._payload(batch_id, movement_id)

        resp1 = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp1.status_code, 200)
        self.assertFalse(resp1.data['replayed'])

        resp2 = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.data['replayed'])
        self.assertEqual(resp2.data['results'], resp1.data['results'])

        self.assertEqual(DebtMovement.objects.filter(pk=movement_id).count(), 1)
        self.assertEqual(SyncBatchLog.objects.filter(batch_id=batch_id).count(), 1)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('1000.00'))

    def test_resending_the_same_record_id_under_a_new_batch_is_still_idempotent(self):
        """Même sans rejouer le même batch_id (ex. le nœud a perdu la trace
        du batch_id envoyé avant la coupure, SYNC.md §3.6), le même UUID
        d'enregistrement ne doit jamais produire un second mouvement."""
        movement_id = str(uuid.uuid4())
        self.api.post('/api/sync/push/', self._payload(str(uuid.uuid4()), movement_id), format='json')
        self.api.post('/api/sync/push/', self._payload(str(uuid.uuid4()), movement_id), format='json')

        self.assertEqual(DebtMovement.objects.filter(pk=movement_id).count(), 1)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('1000.00'))


class InterruptedBatchRecoveryTests(TestCase):
    """
    Coupure au milieu d'un lot (SYNC.md §3.4/§3.6) : un enregistrement dont
    la dépendance n'est pas encore connue est REJETÉ explicitement (jamais
    deviné), puis accepté sans perte ni doublon une fois la dépendance
    arrivée.
    """

    def setUp(self):
        self.node = make_node(code='K1')
        self.api = _issue_token(self.node)

    def test_invoice_referencing_an_unknown_client_is_rejected_then_accepted_after_retry(self):
        client_id = str(uuid.uuid4())
        invoice_id = str(uuid.uuid4())

        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'sales.Invoice': [{
                    'id': invoice_id, 'node': 'K1', 'client': client_id,
                    'status': 'PENDING', 'order_total': '1000.00', 'payment_amount': '0.00',
                    'node_origin': 'K1',
                }],
            },
        }
        resp = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp.data['results']['sales.Invoice'][0]['status'], 'REJECTED')
        self.assertEqual(resp.data['results']['sales.Invoice'][0]['reason'], 'dépendance manquante : client')
        self.assertFalse(Invoice_exists(invoice_id))

        # Le client arrive (poussé par ce même nœud ou déjà connu du Cloud),
        # puis le lot est retransmis avec un nouveau batch_id (le nœud a
        # perdu la trace de l'ancien après la coupure) mais le MÊME id de
        # facture : doit être accepté une seule fois, jamais en double.
        client_payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'clients.Client': [{
                    'id': client_id, 'node': 'K1', 'first_name': 'Jean', 'last_name': 'Mukendi',
                    'node_origin': 'K1',
                }],
            },
        }
        resp_client = self.api.post('/api/sync/push/', client_payload, format='json')
        self.assertEqual(resp_client.data['results']['clients.Client'][0]['status'], 'ACCEPTED')

        retry_payload = dict(payload)
        retry_payload['batch_id'] = str(uuid.uuid4())
        resp_retry = self.api.post('/api/sync/push/', retry_payload, format='json')
        self.assertEqual(resp_retry.data['results']['sales.Invoice'][0]['status'], 'ACCEPTED')
        self.assertTrue(Invoice_exists(invoice_id))

        # Un troisième envoi (le nœud rejoue encore par prudence) ne doit
        # jamais créer une deuxième facture avec cet id.
        resp_third = self.api.post('/api/sync/push/', dict(retry_payload, batch_id=str(uuid.uuid4())), format='json')
        self.assertEqual(resp_third.data['results']['sales.Invoice'][0]['status'], 'ACCEPTED')
        from sales.models import Invoice
        self.assertEqual(Invoice.objects.filter(pk=invoice_id).count(), 1)


def Invoice_exists(invoice_id):
    from sales.models import Invoice
    return Invoice.objects.filter(pk=invoice_id).exists()


class ClientOwnershipConflictTests(TestCase):
    """SYNC.md §1.3/§5.1 : seul le nœud propriétaire (ou le Cloud) peut
    modifier l'identité d'un client ; un nœud tiers qui a seulement facturé
    ce client ne peut jamais la réécrire."""

    def test_a_non_owner_node_cannot_overwrite_client_identity(self):
        k1 = make_node(code='K1')
        k2 = make_node(code='K2')
        client_obj = make_client(k1)
        api_k2 = _issue_token(k2)

        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'clients.Client': [{
                    'id': str(client_obj.pk), 'node': 'K1', 'first_name': 'USURPÉ',
                    'last_name': 'PAR-K2', 'node_origin': 'K2',
                }],
            },
        }
        resp = api_k2.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp.data['results']['clients.Client'][0]['status'], 'REJECTED')
        client_obj.refresh_from_db()
        self.assertNotEqual(client_obj.first_name, 'USURPÉ')
        self.assertEqual(SyncConflictLog.objects.filter(model_label='clients.Client').count(), 1)


class PullCursorTests(TestCase):
    """SYNC.md §4 : un changement de prix fait au Cloud pendant qu'un nœud
    est hors-ligne doit être reçu par ce nœud au premier pull suivant."""

    def test_bread_price_change_is_visible_on_the_next_pull(self):
        node = make_node(code='K1')
        api = _issue_token(node)
        bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)

        resp_before = api.get('/api/sync/pull/')
        self.assertEqual(resp_before.status_code, 200)
        prices_before = {p['id']: p['unit_price'] for p in resp_before.data['bread_prices']}
        self.assertEqual(prices_before[bp.pk], '500')

        bp.unit_price = 600
        bp.save()

        resp_after = api.get('/api/sync/pull/')
        prices_after = {p['id']: p['unit_price'] for p in resp_after.data['bread_prices']}
        self.assertEqual(prices_after[bp.pk], '600')

    def test_client_debt_pull_reflects_cloud_recomputed_value(self):
        node = make_node(code='K1')
        other_node = make_node(code='K2')
        api = _issue_token(node)
        client_obj = make_client(node, current_debt=Decimal('0.00'))

        movement_id = str(uuid.uuid4())
        api_other = _issue_token(other_node)
        api_other.post('/api/sync/push/', {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'sync.DebtMovement': [{
                    'id': movement_id, 'client': str(client_obj.pk),
                    'amount': '7000.00', 'kind': 'ORDER', 'node_origin': 'K2',
                }],
            },
        }, format='json')

        resp = api.get('/api/sync/pull/')
        client_rows = {c['id']: c for c in resp.data['clients']}
        self.assertEqual(client_rows[str(client_obj.pk)]['current_debt'], '7000.00')


class CashClosureOfflineSyncTests(TestCase):
    """
    SYNC.md §0 : une clôture validée hors-ligne, synchronisée après coup,
    est inscrite au Livre de Caisse Direction par le Cloud lui-même (jamais
    directement par le nœud) sans casser la chaîne de hash globale.
    """

    def test_validated_closure_pushed_from_a_node_is_promoted_to_the_cashbook_without_forking(self):
        node = make_node(code='K1')
        api = _issue_token(node)
        closure_id = str(uuid.uuid4())

        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'treasury.CashClosure': [{
                    'id': closure_id, 'node': 'K1', 'date': date.today().isoformat(),
                    'total_entries': '100000.00', 'total_expenses': '20000.00',
                    'is_validated': True, 'node_origin': 'K1',
                }],
            },
        }
        resp = api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp.data['results']['treasury.CashClosure'][0]['status'], 'ACCEPTED')

        closure = CashClosure.objects.get(pk=closure_id)
        self.assertTrue(closure.cashbook_entries.exists())

        entries = list(CashbookEntry.objects.order_by('date', 'created_at'))
        results = verify_cashbook_chain(entries)
        self.assertTrue(all(is_valid for _entry, _expected, is_valid in results))

    def test_replaying_the_same_closure_push_does_not_create_a_second_cashbook_entry(self):
        node = make_node(code='K1')
        api = _issue_token(node)
        closure_id = str(uuid.uuid4())
        record = {
            'id': closure_id, 'node': 'K1', 'date': date.today().isoformat(),
            'total_entries': '50000.00', 'total_expenses': '0.00',
            'is_validated': True, 'node_origin': 'K1',
        }
        api.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()), 'records': {'treasury.CashClosure': [record]}}, format='json')
        api.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()), 'records': {'treasury.CashClosure': [record]}}, format='json')

        closure = CashClosure.objects.get(pk=closure_id)
        self.assertEqual(closure.cashbook_entries.count(), 1)


class DegradedModeCreditLimitTests(TestCase):
    """
    SYNC.md §6 H2 (décision client du 2026-10-22) : un nœud qui n'a JAMAIS
    synchronisé n'est pas considéré dégradé (préserve le comportement actuel
    du monolithe). Un nœud qui a synchronisé puis a cessé de le faire au-delà
    du seuil l'est, et voit le plafond de crédit local réduit à 80 %.
    """

    def test_node_never_synced_is_not_degraded(self):
        node = make_node(code='K1')
        self.assertFalse(node.is_sync_degraded())

    def test_node_stale_beyond_threshold_is_degraded(self):
        from django.utils import timezone
        from datetime import timedelta
        node = make_node(code='K1')
        Node.objects.filter(pk=node.pk).update(last_sync=timezone.now() - timedelta(hours=48))
        node.refresh_from_db()
        self.assertTrue(node.is_sync_degraded(threshold_hours=24))

    def test_degraded_node_blocks_invoice_below_80_percent_of_nominal_limit(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.testing import make_user

        node = make_node(code='K1')
        Node.objects.filter(pk=node.pk).update(last_sync=timezone.now() - timedelta(hours=48))
        bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        facturier = make_user('FACTURIER', node=node)
        client_obj = make_client(node, credit_limit=Decimal('10000.00'), current_debt=Decimal('8500.00'))

        api = APIClient()
        api.force_authenticate(user=facturier)
        resp = api.post('/api/sales/invoices/', {
            'client': str(client_obj.pk), 'payment_type': 'CREDIT', 'payment_amount': '0.00',
            'lines': [{'bread_price': bp.pk, 'quantity': 2}],
        }, format='json')
        # 8500 >= 80% de 10000 (8000) -> bloqué en mode dégradé, alors que
        # 8500 < 10000 l'aurait laissé passer en mode nominal.
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertIn('mode dégradé', resp.data['detail'])
