# Dev backend d44 (2026-11-23) : BUG-993, 994, 995

Tickets passés à CORRIGÉ (décorateurs @expectedFailure retirés dans clients/tests/test_clients_v11.py).

- BUG-993 : `build_outbound_payload` exporte `invoice_date` ; `_push_invoice` (sync/services.py) la lit (ISO ASCII AAAA-MM-JJ strict, pas de futur via `_sync_not_future_date`, >= 2020-01-01, sinon REJECTED) ; avertissement BUG-083 reproduit via `_warn_if_commission_period_locked`. Poste ancien sans la clé : comportement inchangé.
- BUG-994 : `apply_pull_response` crée les clients inconnus (`_create_unknown_pulled_clients`, bulk_create par lots de 500, UUID/code/node_origin du cloud, is_synced=True, aucun DebtMovement ni notification, idempotent, nœud inconnu ou code déjà pris = ignoré avec journal). `PullView` exporte en plus node, node_origin, commission_rate, cotisation_sociale, client_type, notes, total_breads_received (additif). Périmètre du pull NON changé (propres + déjà facturés) : le test existant `test_pull_ne_descend_pas_les_clients_des_autres_noeuds_sans_facture` le fige ; écart avec CLAUDE.md §5.1 (facturier cherche les clients des autres boulangeries hors ligne) à trancher (ticket proposé).
- BUG-995 : `_apply_client_identity_push` ajoute les valeurs écrasées du 2e écrasement au détail du conflit existant.

Tests (log $TEMP/d44.log, 234 tests) : makemigrations --check : aucune migration. Perf apply_pull 5 000 clients : 7,3 s.
- 1 ÉCHEC : `test_BUG_994_...` : l'assertion attend credit_limit 50 000 pour K1-P00007, mais le seed donne 80 000 (i % 7 == 0). Le client est bien recréé avec la valeur du cloud (80 000). Assertion à corriger par le testeur (non modifiée par moi).
- 1 ERREUR : `clients.tests.test_clients_v10.Migration0011` (NOT NULL core_expensecategory.scope pendant migrate arrière) : fichiers non touchés, apparemment préexistant, hors périmètre.

Risques : le pull ne descend toujours pas les clients des autres boulangeries jamais facturées ; un poste neuf n'a donc que les siens.
