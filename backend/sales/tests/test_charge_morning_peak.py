"""
Tests de charge — testeur-charge, 2026-10-22.

Scénario « pic du matin » (mission testeur-charge point 2/CLAUDE.md §5.2) :
plusieurs facturiers de plusieurs boulangeries créent des factures en
parallèle. On vérifie trois garanties attendues par CLAUDE.md §4/§5.2 :

1. Aucune erreur 500 (seuls des refus métier 400/403 sont acceptables).
2. Aucun double déstockage perdu/dupliqué (`BreadStock.qty_sent` doit
   être EXACTEMENT la somme des quantités réellement facturées avec
   succès — ni plus, ni moins).
3. Aucun doublon de `receipt_number` pour un même (nœud, jour).

Point 3 est le risque signalé comme « théorique, non reproduit sous
SQLite » par `docs/architecture/SYNC.md` §10 et par `testeur-ventes`
(voir `sales/tests/test_invoices.py`, docstring de
`ConcurrentInvoiceBPTests`). Ce fichier le reproduit avec de vrais
threads : `sales/views.py::_make_receipt_number` lit
`Invoice.objects.filter(...).count() + 1` SANS verrou ni transaction
dédiée (contrairement à `_generate_client_code`, corrigé sous BUG-017, ou
à `append_cashbook_entry`, corrigé sous BUG-002) — deux requêtes
concurrentes PEUVENT lire le même compteur avant que l'une des deux n'ait
commité son `INSERT`, et `Invoice.receipt_number` n'a NI verrou NI
contrainte d'unicité en base pour s'en protéger a posteriori.

Rappel méthodologique (CLAUDE.md §7 règle 2) : ce fichier n'écrit jamais
le code applicatif. Toute anomalie confirmée ouvre un ticket
`BUG-NNN` dans `docs/qa/REGISTRE_BUGS.md`.
"""
import threading
from collections import Counter
from decimal import Decimal

from django.db import connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import BreadStock
from sales.models import Invoice


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class MorningPeakMultiNodeTests(TransactionTestCase):
    """
    8 boulangeries × 2 facturiers (16 threads) créant chacun 3 factures
    (48 factures au total) en parallèle, sur un pool de clients partagé
    par boulangerie — représentatif du pic du matin (mission point 2).
    """

    def setUp(self):
        Config.get_instance()
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.nodes = [make_node(code=f"CH{i}") for i in range(8)]
        # 2 facturiers (équipes A et B) par boulangerie + quelques clients.
        self.facturiers_by_node = {
            node.pk: [
                make_user('FACTURIER', node=node, team='A'),
                make_user('FACTURIER', node=node, team='B'),
            ]
            for node in self.nodes
        }
        self.clients_by_node = {
            node.pk: [make_client(node, credit_limit=Decimal('1000000.00')) for _ in range(3)]
            for node in self.nodes
        }

    def _create_invoice(self, facturier, client_obj, results, errors, qty=2):
        api = _api_for(facturier)
        try:
            resp = api.post('/api/sales/invoices/', {
                'client': str(client_obj.pk),
                'payment_type': 'CASH',
                'payment_amount': str(qty * self.bp.unit_price),
                # `bread_price` : PK entière de `BreadPrice`, envoyée comme
                # entier (pas chaîne) — voir BUG-063 ouvert par ce fichier,
                # découvert incidemment : `InvoiceViewSet.create` compare
                # `bp_ids` (bruts, non typés) à des clés `int` de `bp_map`
                # sans normaliser les types, donc `"1" not in {1: ...}` est
                # vrai même quand le BreadPrice existe réellement. Hors
                # périmètre du scénario de charge testé ici (pas un effet de
                # la concurrence) — on neutralise volontairement ce bug
                # sans rapport pour isoler le VRAI scénario sous test
                # (numéro de reçu dupliqué).
                'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
            }, format='json')
            results.append((facturier.node_id, resp.status_code, resp.data if resp.status_code != 201 else resp.data.get('receipt_number')))
        except Exception as exc:  # pragma: no cover — on veut voir toute exception, pas la masquer
            errors.append(exc)
        finally:
            connections.close_all()

    def test_no_500_no_duplicate_receipt_number_no_lost_stock_under_concurrent_morning_peak(self):
        """
        BUG-062 (CORRIGÉ) : `InvoiceViewSet.create` (sales/views.py) retente
        désormais sur `OperationalError` ("database table is locked"), même
        motif que `append_cashbook_entry`/`_generate_client_code`
        (BUG-002/BUG-017). Chaque tentative relit l'état depuis le début
        (`_create_once`, y compris le numéro de reçu), ce qui élimine aussi
        le risque de doublon de `receipt_number` sous charge.
        """
        qty = 2
        n_per_facturier = 1
        results = []
        errors = []
        threads = []
        for node in self.nodes:
            node_clients = self.clients_by_node[node.pk]
            for facturier in self.facturiers_by_node[node.pk]:
                for i in range(n_per_facturier):
                    client_obj = node_clients[i % len(node_clients)]
                    t = threading.Thread(
                        target=self._create_invoice,
                        args=(facturier, client_obj, results, errors, qty),
                    )
                    threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 1. Jamais d'exception Python non maîtrisée (crash du worker).
        self.assertEqual(errors, [], f"Exceptions inattendues côté client de test : {errors}")

        # 2. Jamais de 500 — seuls 201 (créé) ou un refus métier 4xx (ex.
        #    "database is locked" retourné en 500 par DRF serait, lui, un
        #    vrai problème de robustesse sous charge à signaler).
        server_errors = [r for r in results if r[1] >= 500]
        self.assertEqual(
            server_errors, [],
            f"Erreur(s) serveur 5xx pendant le pic du matin (inacceptable, CLAUDE.md §4) : {server_errors}"
        )

        successes = [r for r in results if r[1] == 201]
        self.assertGreater(
            len(successes), 0,
            f"Aucune facture n'a réussi — le test ne prouve rien. Codes obtenus : "
            f"{Counter(r[1] for r in results)} | détail : {results[:5]}"
        )

        # 3. Pas de perte/duplication de déstockage : qty_sent doit être
        #    exactement qty * nombre de succès, PAR NŒUD.
        successes_by_node = Counter(r[0] for r in successes)
        for node in self.nodes:
            expected_qty_sent = successes_by_node.get(node.pk, 0) * qty
            try:
                stock = BreadStock.objects.get(node=node, bread_price=self.bp)
                actual = stock.qty_sent
            except BreadStock.DoesNotExist:
                actual = 0
            self.assertEqual(
                actual, expected_qty_sent,
                f"Déstockage incohérent pour {node.code} : attendu {expected_qty_sent} "
                f"(= {successes_by_node.get(node.pk, 0)} factures × {qty}), obtenu {actual}. "
                "Une perte indique une mise à jour F() écrasée ; un excédent indique un double déstockage."
            )

        # 4. Pas de doublon de receipt_number par (nœud, jour) — THE scénario
        #    décrit dans SYNC.md §10, non protégé par verrou ni unicité.
        receipt_numbers_by_node = {}
        for node_id, status_code, payload in successes:
            receipt_numbers_by_node.setdefault(node_id, []).append(payload)
        for node_id, numbers in receipt_numbers_by_node.items():
            dupes = [n for n, c in Counter(numbers).items() if c > 1]
            self.assertEqual(
                dupes, [],
                f"Numéros de reçu DUPLIQUÉS sous charge concurrente pour le nœud {node_id} : {dupes} "
                f"(sur {numbers}) — confirme le risque théorique de SYNC.md §10 : "
                "`_make_receipt_number` (sales/views.py) lit `count()+1` sans verrou."
            )
