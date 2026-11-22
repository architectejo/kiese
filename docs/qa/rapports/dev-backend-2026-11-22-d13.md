# Rapport dev-backend (Dev B) - 2026-11-22 d13

## Tickets passés à CORRIGÉ
- BUG-652 : `respond_to_request` (production/views.py) : 400 français sans écriture pour catégorie absente de la demande, réponse entièrement à 0, quantité > stock de l'émettrice (même message que `send/`, stock verrouillé `select_for_update`).
- BUG-653 : fournée datée du futur refusée en 400 (`work_date_for(node)`), saisie rétroactive inchangée.
- BUG-654 : `_strict_int` exige `isascii()` ; `ProductionSessionSerializer.to_internal_value` refuse les chiffres Unicode pour `flour_sacks_used`.
- BUG-626 : champ `ConsumableCount.is_synced` (migration additive `production/0030_bug626_consumablecount_is_synced`, données : lignes sans inventaire passées à False, reverse noop) ; `sync_now.build_outbound_payload` les envoie (id = pk local), `apply_push_response` les marque synchronisées ; Cloud déjà idempotent. `ConsumableCountViewSet.perform_create` pose `is_synced=False`.
- BUG-651b : `InvoiceSerializer.node_code` (lecture seule).
- BUG-625 : déjà `À CLARIFIER`, non codé.

## Tests
- Nouveau : `production/tests/test_dev_d13_bugs_652_654_626.py`.
- Marques `@expectedFailure` retirées : 652 x2, 653, 654 x2 (test_verif_a4...), et les 2 BUG-626 de `test_sync_inventaire_v2_a3.py` (qui passaient déjà : « unexpected success »).
- Fixtures de 7 fichiers existants complétées (stock de l'émettrice semé avant `respond_to_request`), car la nouvelle règle (alignée sur `send/`) refuse la réponse sans stock alors que ces tests s'appuyaient sur un stock négatif : test_bug190_196, test_daily_closure_report, test_verif_bug161_b3_b5, test_verif_bug177_rapport, test_verif_bug319_322, test_verif_bug522_c, test_verif_rotation_prod_c. Aucune assertion modifiée ni supprimée.
- Exécution : suite `production sync sales` complète (1937 tests) : 15 échecs, tous traités ci-dessus (14 fixtures + flour_sacks Unicode) ; rejeu ciblé des 10 modules touchés : OK ; test_verif_bug319_322 : OK (36). `makemigrations --check` : aucun changement. Les rejeux ciblés n'ont pas relancé tout `sales`/`sync` (68 min) après les correctifs de fixtures.

## Reste / risques
- Observation : `test_BUG_625_comptable_cannot_supply_direction_stock` (test_production_v2_a3) est en « unexpected success » (le comportement attendu est déjà obtenu) : à traiter par le testeur / lors de la clarification de BUG-625 ; le suite complète reste donc en échec tant que cette marque n'est pas levée.
- Impact API : nouveaux 400 sur `respond_to_request` ; le frontend doit afficher `detail` (déjà le cas pour les 400 de ce flux).
- Rotation/minuit : des tests dépendant de l'horloge ont tourné à cheval sur minuit (22 -> 23/11) ; aucun échec attribuable.
