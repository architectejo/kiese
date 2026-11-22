# Rapport dev-backend (Dev C, rôle A) — 2026-11-22-a

## Tickets
- BUG-522 [Bloquant] : CORRIGÉ. `BreadTransferSerializer.validate()` refuse (400 `{"detail"}`) toute modification de from_node/to_node/initiated_by/quantity_sent/quantity_received à la mise à jour (valeur identique tolérée). Tests : `production/tests/test_bug522_transfer_nodes_readonly.py` ; `@expectedFailure` BUG-522 retirés de `core/tests/test_verif_isolation_a_c.py`.
- BUG-364 [Mineur] : CORRIGÉ (sans migration). `recompute_cump` : ordre `created_at, movement_type, pk`, avertissement sur instants partagés entrée/sortie, `--apply` ignore le stock sauf `--force`. Test : `test_bug364_recompute_cump_ordre.py`. Limite : ordre réel invérifiable ; vraie solution = séquence persistée (migration, à décider).
- BUG-365 [Mineur] : CORRIGÉ. `reconciliation` renvoie le nœud réellement utilisé. Test : `test_bug365_reconciliation_node_echo.py`.

## Résultats
- Avant correctif : bug522 3 échecs/5 ; bug364 3 échecs/5 ; bug365 2 échecs/4.
- Après : `manage.py test production core.tests.test_verif_isolation_a_c` : 937 tests OK (skipped=1, expected failures=4). `check` OK, `makemigrations --check` : aucun changement.

## Risques
- Contrat API : PATCH/PUT de transfert avec un nœud différent -> 400 (le frontend n'est pas censé le faire).
- Sur la création, `from_node` reste le fournisseur choisi et `to_node` = nœud de l'appelant (modèle existant), pas l'inverse de la consigne.
