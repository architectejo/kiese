"""
Tests de charge — synchronisation multi-nœuds (testeur-charge, 2026-10-22).

Va plus loin que `sync/tests/test_sync.py::TwoNodesOfflineDebtScenarioTests`
(mission testeur-charge point 2) :
- plus de deux nœuds (4 boulangeries),
- plus de mouvements par nœud (volumétrie),
- des séquences d'arrivée VRAIMENT désordonnées (pas seulement « A puis B »
  et « B puis A », mais un ordre aléatoire parmi N nœuds),
- rejeu RAPIDE et RÉPÉTÉ du même lot sous charge concurrente réelle (vrais
  threads, pas seulement deux appels séquentiels) — mission point 3,
  « idempotence sous charge répétée ».

Rappel méthodologique (CLAUDE.md §7 règle 2) : ce fichier n'écrit jamais le
code applicatif. BUG-004 est déjà `CORRIGÉ (V1)` ; toute anomalie confirmée
ici rouvre une anomalie sous un nouveau ticket `BUG-NNN` (pas une
réouverture de BUG-004 lui-même, dont le périmètre V1 est documenté comme
partiel — voir `docs/qa/REGISTRE_BUGS.md`).
"""
import random
import threading
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.db import OperationalError, connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_client
from clients.models import Client
from sync.models import NodeAuthToken, DebtMovement, SyncBatchLog


def _node_client(raw_token):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw_token}')
    return api


def _issue_token(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    return _node_client(raw)


class ManyNodesOutOfOrderVolumeTests(TestCase):
    """
    4 boulangeries facturent le même client hors-ligne, chacune avec
    PLUSIEURS mouvements (pas un seul), remontés dans un ordre
    complètement mélangé. La dette finale doit être la somme exacte de
    TOUS les mouvements, quel que soit l'ordre d'arrivée des lots.
    """

    N_NODES = 4
    MOVEMENTS_PER_NODE = 5

    def setUp(self):
        self.nodes = [make_node(code=f"VOL{i}") for i in range(self.N_NODES)]
        self.client_obj = make_client(self.nodes[0], current_debt=Decimal('0.00'))
        self.apis = {node.code: _issue_token(node) for node in self.nodes}

    def _push_one_movement(self, node_code, amount):
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
                    'receipt_number': f'{node_code}-VOL-{movement_id[:8]}',
                    'node_origin': node_code,
                }],
                'sync.DebtMovement': [{
                    'id': movement_id, 'client': str(self.client_obj.pk), 'invoice': invoice_id,
                    'amount': str(amount), 'kind': 'ORDER', 'node_origin': node_code,
                }],
            },
        }
        resp = self.apis[node_code].post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        for model_results in resp.data['results'].values():
            for r in model_results:
                self.assertEqual(r['status'], 'ACCEPTED', r)

    def test_debt_is_the_exact_sum_under_random_arrival_order_many_nodes_many_movements(self):
        # Chaque nœud facture plusieurs fois, montant différent à chaque fois.
        amounts_by_node = {}
        all_pushes = []  # liste de (node_code, amount), à mélanger
        for node in self.nodes:
            amounts = [Decimal(random.randint(500, 5000)) for _ in range(self.MOVEMENTS_PER_NODE)]
            amounts_by_node[node.code] = amounts
            all_pushes.extend((node.code, a) for a in amounts)

        random.shuffle(all_pushes)  # ordre d'arrivée totalement désordonné
        for node_code, amount in all_pushes:
            self._push_one_movement(node_code, amount)

        expected_total = sum(
            amount for amounts in amounts_by_node.values() for amount in amounts
        )
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, expected_total)

        # Vérification complémentaire : autant de DebtMovement que de
        # pushes, aucun perdu ni dupliqué.
        self.assertEqual(
            DebtMovement.objects.filter(client=self.client_obj).count(),
            self.N_NODES * self.MOVEMENTS_PER_NODE,
        )

    def test_debt_is_the_exact_sum_under_a_second_independent_random_order(self):
        """Rejoue le même scénario avec un ordre différent (graine différente) —
        prouve que ce n'est pas un hasard favorable à un seul tirage."""
        self.test_debt_is_the_exact_sum_under_random_arrival_order_many_nodes_many_movements()


class ConcurrentRapidReplayTests(TransactionTestCase):
    """
    Mission point 3 : rejouer le MÊME lot plusieurs fois RAPIDEMENT,
    y compris de façon concurrente (vrais threads) — simule une coupure
    réseau juste après l'envoi (le nœud ne sait pas si le Cloud a reçu la
    réponse, et retente immédiatement, éventuellement en recouvrement
    avec une requête encore en cours de traitement).

    `TransactionTestCase` (pas `TestCase`) : CORRECTION appliquée pendant
    BUG-062 — avec `TestCase`, le test entier tourne dans une seule
    transaction englobante ouverte sur la connexion du thread principal ;
    les connexions des threads concurrents (`connections.close_all()` +
    nouvelle connexion par thread) se heurtent alors systématiquement à
    « database is locked » tenu par CETTE transaction englobante elle-même
    — un artefact du harnais de test, pas de la robustesse réelle de
    l'application sous charge (déjà constaté par testeur-charge sur le
    scénario `sales` équivalent, qui utilisait déjà `TransactionTestCase`).
    """

    def setUp(self):
        self.node = make_node(code='REPLAY1')
        self.client_obj = make_client(self.node, current_debt=Decimal('0.00'))
        _, self.raw_token = NodeAuthToken.issue_for_node(self.node)

    def _payload(self, batch_id):
        movement_id = str(uuid.uuid4())
        return {
            'batch_id': batch_id,
            'records': {
                'sync.DebtMovement': [{
                    'id': movement_id, 'client': str(self.client_obj.pk),
                    'amount': '1000.00', 'kind': 'ORDER', 'node_origin': self.node.code,
                }],
            },
        }

    def test_replaying_the_same_batch_id_concurrently_many_times_never_duplicates(self):
        """
        BUG-062 (CORRIGÉ, même cause racine que sa version `sales` — voir
        `sales/tests/test_charge_morning_peak.py`) : sous 10 rejeux
        VRAIMENT concurrents, l'authentification du nœud elle-même
        (`sync.models.NodeAuthToken.authenticate()`) retente désormais sa
        mise à jour de `last_used_at` sur `OperationalError`, même motif que
        `sync.services._WRITE_MAX_RETRIES`.
        """
        batch_id = str(uuid.uuid4())
        payload = self._payload(batch_id)  # même payload, même movement_id, à chaque rejeu
        n_concurrent_replays = 10
        results = []
        errors = []

        def _replay():
            api = _node_client(self.raw_token)
            try:
                resp = api.post('/api/sync/push/', payload, format='json')
                results.append(resp.status_code)
            except Exception as exc:  # pragma: no cover
                import traceback
                errors.append((exc, traceback.format_exc()))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=_replay) for _ in range(n_concurrent_replays)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Exceptions inattendues pendant le rejeu concurrent : {errors}")
        # BUG-062 (réouverture, voir `TransientFailureNeverArchivedPermanentlyTests`
        # ci-dessous) : sous contention EXTRÊME, un budget de tentatives
        # épuisé renvoie désormais 503 (« réessayez ce lot »), jamais un 200
        # archivant un résultat REJECTED permanent — les deux codes sont
        # donc acceptables ici. Ce qui ne l'est JAMAIS : un 500 brut, ou un
        # état final incohérent (vérifié ci-dessous).
        self.assertTrue(all(code in (200, 503) for code in results), results)

        # Jamais plus d'un DebtMovement, quel que soit le nombre de rejeux —
        # ni perte silencieuse ni duplication.
        movement_count = DebtMovement.objects.filter(client=self.client_obj).count()
        self.assertIn(movement_count, (0, 1), (
            "Le rejeu concurrent du même batch_id a créé plus d'un DebtMovement — "
            "l'idempotence par UUID d'enregistrement ne suffit pas sous vraie concurrence."
        ))
        self.client_obj.refresh_from_db()
        if movement_count == 1:
            # Au moins un rejeu a réellement traité le lot : l'état doit
            # être exactement celui attendu, et jamais archivé en PARTIAL
            # (le lot ne contient qu'un DebtMovement, aucun rejet métier
            # possible ici).
            self.assertEqual(self.client_obj.current_debt, Decimal('1000.00'))
            batch_log = SyncBatchLog.objects.filter(batch_id=batch_id).first()
            self.assertIsNotNone(batch_log)
            self.assertEqual(batch_log.status, SyncBatchLog.Status.OK)
        else:
            # Cas résiduel extrême (tous les rejeux ont essuyé un échec
            # transitoire) : AUCUN SyncBatchLog ne doit avoir été archivé —
            # le lot reste intégralement rejouable plus tard, pas perdu.
            self.assertEqual(SyncBatchLog.objects.filter(batch_id=batch_id).count(), 0)

        # Dans tous les cas : au plus un seul SyncBatchLog pour ce batch_id
        # (§3.3 promet UN journal par batch_id, `unique=True` sur le champ).
        self.assertLessEqual(SyncBatchLog.objects.filter(batch_id=batch_id).count(), 1)

    def test_rapid_sequential_replay_hundred_times_stays_idempotent(self):
        """Rejeu séquentiel très rapide (pas de délai) — pas de concurrence
        réelle ici, mais un volume de rejeu représentatif d'un nœud qui
        retenterait en boucle serrée après une coupure répétée."""
        batch_id = str(uuid.uuid4())
        payload = self._payload(batch_id)
        api = _node_client(self.raw_token)
        for _ in range(100):
            resp = api.post('/api/sync/push/', payload, format='json')
            self.assertEqual(resp.status_code, 200, resp.data)

        self.assertEqual(DebtMovement.objects.filter(client=self.client_obj).count(), 1)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('1000.00'))


class TransientFailureNeverArchivedPermanentlyTests(TestCase):
    """
    BUG-062 (RÉOUVERT par testeur-charge le 2026-10-23, puis CORRIGÉ) :
    reproduit déterministiquement — sans dépendre d'une vraie course de
    threads — le scénario exact décrit par le testeur : un item du lot
    épuise son budget de retentatives sur un verrou SQLite
    (`sync_debtmovement`), et le rejeu ultérieur du MÊME `batch_id` (cas
    d'usage réel : un nœud qui retente après coupure réseau) doit RECRÉER
    le `DebtMovement` manquant, pas renvoyer indéfiniment un résultat figé.

    AVANT la correction : la première requête renvoyait 200 avec un
    résultat `{'status': 'REJECTED', 'reason': 'erreur serveur : ...'}`
    archivé pour toujours dans `SyncBatchLog` (`status='PARTIAL'`) ; la
    seconde requête (même `batch_id`) retrouvait ce log déjà présent et
    renvoyait `replayed: True` avec EXACTEMENT le même résultat archivé —
    sans jamais recréer le `DebtMovement` : perte silencieuse et
    définitive d'une dette client facturée hors-ligne.
    """

    def setUp(self):
        self.node = make_node(code='TRANSIENT1')
        self.client_obj = make_client(self.node, current_debt=Decimal('0.00'))
        _, self.raw_token = NodeAuthToken.issue_for_node(self.node)
        self.api = _node_client(self.raw_token)

    def _payload(self, batch_id, movement_id):
        return {
            'batch_id': batch_id,
            'records': {
                'sync.DebtMovement': [{
                    'id': movement_id, 'client': str(self.client_obj.pk),
                    'amount': '1500.00', 'kind': 'ORDER', 'node_origin': self.node.code,
                }],
            },
        }

    def test_exhausted_retry_budget_is_not_archived_and_replay_recreates_the_movement(self):
        batch_id = str(uuid.uuid4())
        movement_id = str(uuid.uuid4())
        payload = self._payload(batch_id, movement_id)

        # Simule un verrou SQLite jamais libéré pendant toute la fenêtre de
        # retentatives de `record_debt_movement` — budgets réduits
        # uniquement pour que le test reste rapide (le mécanisme testé, pas
        # sa durée, est ce qui importe ici).
        with patch('sync.services._WRITE_MAX_RETRIES', 1), \
             patch('sync.views._PUSH_MAX_RETRIES', 2), \
             patch(
                 'sync.services.DebtMovement.objects.create',
                 side_effect=OperationalError('database table is locked: sync_debtmovement'),
             ):
            resp1 = self.api.post('/api/sync/push/', payload, format='json')

        # APRÈS la correction : échec transitoire signalé explicitement
        # (503, jamais 200 avec un rejet archivé), AUCUN SyncBatchLog
        # persisté pour ce batch_id, AUCUN DebtMovement créé (cohérent avec
        # l'échec signalé — rien de perdu puisque rien n'a été promis).
        self.assertEqual(resp1.status_code, 503, resp1.data)
        self.assertEqual(SyncBatchLog.objects.filter(batch_id=batch_id).count(), 0)
        self.assertEqual(DebtMovement.objects.filter(pk=movement_id).count(), 0)

        # Rejeu du MÊME batch_id, verrou désormais relâché (mock retiré) :
        # doit RÉELLEMENT traiter l'enregistrement — pas renvoyer un
        # résultat figé — exactement le cas d'usage visé (nœud qui retente
        # après coupure réseau).
        resp2 = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp2.status_code, 200, resp2.data)
        self.assertFalse(resp2.data['replayed'])
        for model_results in resp2.data['results'].values():
            for r in model_results:
                self.assertEqual(r['status'], 'ACCEPTED', r)

        self.assertEqual(DebtMovement.objects.filter(pk=movement_id).count(), 1)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('1500.00'))

        batch_log = SyncBatchLog.objects.get(batch_id=batch_id)
        self.assertEqual(batch_log.status, SyncBatchLog.Status.OK)

    def test_replaying_the_same_batch_id_after_a_transient_failure_never_returns_a_frozen_rejection(self):
        """Variante : rejoue deux fois après l'échec transitoire — la
        deuxième requête (celle qui a réellement réussi) doit désormais
        être servie en mode `replayed: True` avec le résultat RÉEL
        (ACCEPTED), jamais le résultat REJECTED de la tentative échouée."""
        batch_id = str(uuid.uuid4())
        movement_id = str(uuid.uuid4())
        payload = self._payload(batch_id, movement_id)

        with patch('sync.services._WRITE_MAX_RETRIES', 1), \
             patch('sync.views._PUSH_MAX_RETRIES', 2), \
             patch(
                 'sync.services.DebtMovement.objects.create',
                 side_effect=OperationalError('database table is locked: sync_debtmovement'),
             ):
            resp1 = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp1.status_code, 503, resp1.data)

        resp2 = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp2.status_code, 200, resp2.data)
        self.assertFalse(resp2.data['replayed'])

        resp3 = self.api.post('/api/sync/push/', payload, format='json')
        self.assertEqual(resp3.status_code, 200, resp3.data)
        self.assertTrue(resp3.data['replayed'])
        for model_results in resp3.data['results'].values():
            for r in model_results:
                self.assertEqual(r['status'], 'ACCEPTED', r)

        self.assertEqual(DebtMovement.objects.filter(pk=movement_id).count(), 1)
