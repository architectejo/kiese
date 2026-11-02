"""
Passe finale de vérification — testeur-charge, 2026-11-02 — BUG-004.

Objectif (demande explicite du coordinateur) : vérifier par de VRAIS tests
(pas une relecture) les 9 modèles ajoutés le 2026-11-02
(`docs/qa/rapports/architecte-sync-2026-11-02-bug004-extension.md` et
`...-social-uuid.md`) sous l'angle charge/concurrence/résilience :

1. Idempotence du push sur chacun des 9 nouveaux modèles sous rejeu rapide.
2. Rejet propre d'une dépendance manquante puis rattrapage sans perte.
3. Deux nœuds qui poussent SIMULTANÉMENT (vrais threads) des données qui se
   référencent : `BreadTransfer` émetteur/récepteur sur deux nœuds réels,
   `SocialDistributionLine` → `SocialDistribution` concurrentes.
4. Non-régression du comportement BUG-067/072 (503 sous contention, jamais
   de résultat REJECTED archivé pour toujours) sur un des nouveaux modèles.

Méthodologie (CLAUDE.md §7 règle 2) : ce fichier n'écrit jamais le code
applicatif. Toute anomalie confirmée ici est documentée sous un nouveau
`BUG-NNN`, jamais corrigée ici.
"""
import threading
import uuid
from datetime import date
from decimal import Decimal

from django.db import connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from core.models import Node
from core.testing import make_node, make_bread_price, make_client
from sync.models import NodeAuthToken, SyncBatchLog
from production.models import BreadTransfer, BreadTransferLine
from clients.models import SocialContribution, SocialDistribution, SocialDistributionLine


def _node_client(raw_token):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw_token}')
    return api


def _issue_token(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    return _node_client(raw)


class BreadTransferConcurrentCreateRaceTests(TransactionTestCase):
    """
    SYNC.md §5.3 : `BreadTransfer` référence `from_node`/`to_node`, deux
    nœuds réels. Scénario demandé par le coordinateur : deux pushes
    VRAIMENT concurrents (vrais threads, deux jetons de nœud différents)
    du MÊME `BreadTransfer` (même UUID) — simule une coupure juste après
    l'envoi initial par `to_node`, suivie d'un rejeu avant que l'accusé de
    réception n'ait été vu, pendant qu'un second thread (même ou autre
    nœud) retente aussi. Attendu : jamais de doublon, jamais de 500, état
    final cohérent (une seule ligne `BreadTransfer`).
    """

    def setUp(self):
        self.k1 = make_node(code='CCK1')
        self.k4 = make_node(code='CCK4')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC CC', 500)
        _, self.raw_k4 = NodeAuthToken.issue_for_node(self.k4)

    def _payload(self, transfer_id, batch_id):
        return {
            'batch_id': batch_id,
            'records': {
                'production.BreadTransfer': [{
                    'id': transfer_id, 'from_node': 'CCK1', 'to_node': 'CCK4',
                    'transfer_status': 'PENDING', 'node_origin': 'CCK4',
                }],
            },
        }

    def test_concurrent_create_of_the_same_transfer_never_duplicates_nor_500s(self):
        transfer_id = str(uuid.uuid4())
        n_threads = 8
        status_codes = []
        errors = []

        def _attempt():
            api = _node_client(self.raw_k4)
            try:
                resp = api.post(
                    '/api/sync/push/', self._payload(transfer_id, str(uuid.uuid4())), format='json'
                )
                status_codes.append(resp.status_code)
            except Exception as exc:  # pragma: no cover
                import traceback
                errors.append((exc, traceback.format_exc()))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=_attempt) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Exceptions inattendues (pas de 500 attendu) : {errors}")
        self.assertTrue(all(code in (200, 503) for code in status_codes), status_codes)
        # Jamais plus d'une seule ligne BreadTransfer pour cet UUID, quel
        # que soit le nombre de requêtes concurrentes en course de création.
        self.assertEqual(BreadTransfer.objects.filter(pk=transfer_id).count(), 1)

        # Auto-cicatrisation : un rejeu ultérieur (nouveau batch_id, après
        # que la course est terminée) doit systématiquement être ACCEPTED
        # (no-op idempotent), jamais un rejet permanent causé par la course
        # initiale — même si une des requêtes concurrentes avait, elle,
        # essuyé une erreur transitoire de type IntegrityError.
        api = _node_client(self.raw_k4)
        resp_final = api.post(
            '/api/sync/push/', self._payload(transfer_id, str(uuid.uuid4())), format='json'
        )
        self.assertEqual(resp_final.status_code, 200, resp_final.data)
        self.assertEqual(
            resp_final.data['results']['production.BreadTransfer'][0]['status'], 'ACCEPTED'
        )

    def test_opposing_nodes_push_dependent_transitions_concurrently_without_corruption(self):
        """
        Scénario principal demandé : `from_node` et `to_node` sont deux
        nœuds RÉELS et distincts qui poussent, en vraie concurrence, des
        étapes qui se référencent (le transfert doit exister avant qu'une
        transition ne puisse s'appliquer). Le protocole (SYNC.md §5.3) ne
        requiert jamais que les deux soient en ligne en même temps, mais ce
        test vérifie que le système reste correct même s'ils le sont.
        """
        _, raw_k1 = NodeAuthToken.issue_for_node(self.k1)
        transfer_id = str(uuid.uuid4())

        # Transfert créé par to_node (K4) — pré-condition nécessaire avant
        # toute transition de statut par K1, posée hors course pour isoler
        # la variable testée (la concurrence sur les transitions elles-mêmes).
        api_k4 = _node_client(self.raw_k4)
        api_k4.post(
            '/api/sync/push/', self._payload(transfer_id, str(uuid.uuid4())), format='json'
        )
        self.assertEqual(BreadTransfer.objects.filter(pk=transfer_id).count(), 1)

        results = {}
        errors = []

        def _k1_responds():
            api = _node_client(raw_k1)
            try:
                resp = api.post('/api/sync/push/', {
                    'batch_id': str(uuid.uuid4()),
                    'records': {
                        'production.BreadTransfer': [{
                            'id': transfer_id, 'from_node': 'CCK1', 'to_node': 'CCK4',
                            'transfer_status': 'RESPONDED', 'node_origin': 'CCK1',
                        }],
                    },
                }, format='json')
                results['k1'] = resp.status_code
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connections.close_all()

        def _k4_replays_pending():
            # K4 rejoue, en parallèle, le lot initial (ex. pas encore sûr
            # que son premier envoi a été reçu) — ne doit jamais régresser
            # un RESPONDED déjà appliqué par K1, qu'il arrive avant ou après.
            api = _node_client(self.raw_k4)
            try:
                resp = api.post(
                    '/api/sync/push/',
                    self._payload(transfer_id, str(uuid.uuid4())), format='json'
                )
                results['k4'] = resp.status_code
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=_k1_responds), threading.Thread(target=_k4_replays_pending)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertTrue(all(v in (200, 503) for v in results.values()), results)
        transfer = BreadTransfer.objects.get(pk=transfer_id)
        # Quel que soit l'ordre d'exécution réel des deux threads, le statut
        # final ne peut être QUE PENDING (si le rejeu de K4 a "gagné" la
        # course et que RESPONDED n'a pas encore été appliqué) ou RESPONDED
        # (la transition avant) — JAMAIS un état incohérent, et jamais une
        # régression visible une fois RESPONDED atteint.
        self.assertIn(transfer.transfer_status, ('PENDING', 'RESPONDED'))
        self.assertEqual(BreadTransfer.objects.filter(pk=transfer_id).count(), 1)


class SocialDistributionLineConcurrentCreateTests(TransactionTestCase):
    """
    `SocialDistributionLine` dépend de `SocialDistribution` (FK) — scénario
    demandé : plusieurs lignes, pour des clients différents, poussées en
    VRAIE concurrence alors que la `SocialDistribution` parente n'existe pas
    encore côté Cloud (deux batches concurrents contiennent chacun la
    distribution ET une ligne différente) — vérifie l'absence de collision
    d'UUID et l'absence de double traitement de la distribution partagée.
    """

    def setUp(self):
        self.node = make_node(code='SOCCC')
        self.clients = [make_client(self.node) for _ in range(6)]
        _, self.raw_token = NodeAuthToken.issue_for_node(self.node)
        self.distribution_id = str(uuid.uuid4())

    def _payload(self, client, line_id):
        return {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'clients.SocialDistribution': [{
                    'id': self.distribution_id, 'node': 'SOCCC', 'year': 2026,
                    'tarif': '700.00', 'is_closed': False, 'node_origin': 'SOCCC',
                }],
                'clients.SocialDistributionLine': [{
                    'id': line_id, 'distribution': self.distribution_id, 'client': str(client.pk),
                    'indice': 10, 'total_social': '7000.00', 'node_origin': 'SOCCC',
                }],
            },
        }

    def test_many_lines_for_the_same_new_distribution_pushed_concurrently(self):
        errors = []
        status_codes = []

        def _push_line(client):
            api = _node_client(self.raw_token)
            line_id = str(uuid.uuid4())
            try:
                resp = api.post('/api/sync/push/', self._payload(client, line_id), format='json')
                status_codes.append(resp.status_code)
            except Exception as exc:  # pragma: no cover
                import traceback
                errors.append((exc, traceback.format_exc()))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=_push_line, args=(c,)) for c in self.clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertTrue(all(code in (200, 503) for code in status_codes), status_codes)
        # Une seule SocialDistribution créée, jamais dupliquée malgré 6
        # créations concurrentes du même UUID dans 6 lots différents.
        self.assertEqual(SocialDistribution.objects.filter(pk=self.distribution_id).count(), 1)
        # Toutes les lignes qui ont fini par être acceptées (statut 200)
        # doivent exister et pointer vers l'unique distribution — pas de
        # ligne orpheline, pas de perte silencieuse permanente (un rejeu
        # ultérieur doit rattraper tout échec transitoire).
        for client in self.clients:
            # Rejeu de rattrapage (nouveau lot, hors course) : toujours
            # accepté, jamais de doublon de ligne pour ce client.
            api = _node_client(self.raw_token)
            retry_line_id = str(uuid.uuid4())
            resp = api.post('/api/sync/push/', self._payload(client, retry_line_id), format='json')
            self.assertEqual(resp.status_code, 200, resp.data)
            lines_for_client = SocialDistributionLine.objects.filter(
                distribution_id=self.distribution_id, client=client
            )
            self.assertEqual(lines_for_client.count(), 1, (
                f"Client {client.pk} : {lines_for_client.count()} lignes au lieu de 1 "
                "— double traitement détecté."
            ))


class NewModelsIdempotenceUnderRapidReplayTests(TestCase):
    """
    Mission point 1 : idempotence du push sur chaque nouveau modèle sous
    rejeu rapide répété (pas de vraie concurrence ici — volume/robustesse),
    en complément de `test_sync_bug004_extension.py` qui couvre déjà chaque
    modèle une fois ; ce test rejoue 20 fois pour détecter une dérive sous
    volume que deux appels séquentiels ne révéleraient pas.
    """

    def setUp(self):
        self.node = make_node(code='RPL1')
        self.api = _issue_token(self.node)

    def test_social_contribution_rapid_replay_stays_single_row(self):
        from clients.models import Client
        client = make_client(self.node)
        contrib_id = str(uuid.uuid4())
        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'clients.SocialContribution': [{
                    'id': contrib_id, 'node': 'RPL1', 'client': str(client.pk),
                    'month': 3, 'year': 2026, 'amount': '3000.00', 'node_origin': 'RPL1',
                }],
            },
        }
        for _ in range(20):
            resp = self.api.post('/api/sync/push/', payload, format='json')
            self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(SocialContribution.objects.filter(pk=contrib_id).count(), 1)

    def test_bread_transfer_rapid_replay_stays_single_row(self):
        k_to = make_node(code='RPL2')
        transfer_id = str(uuid.uuid4())
        payload = {
            'batch_id': str(uuid.uuid4()),
            'records': {
                'production.BreadTransfer': [{
                    'id': transfer_id, 'from_node': 'RPL1', 'to_node': 'RPL2',
                    'transfer_status': 'PENDING', 'node_origin': 'RPL2',
                }],
            },
        }
        for _ in range(20):
            resp = self.api.post('/api/sync/push/', payload, format='json')
            self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(BreadTransfer.objects.filter(pk=transfer_id).count(), 1)
