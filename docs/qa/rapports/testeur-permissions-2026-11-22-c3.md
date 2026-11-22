# testeur-permissions (Dev C) — 2026-11-22-c3 — vérification de BUG-522

## Verdict
**BUG-522 : VÉRIFIÉ** (testeur-permissions, Dev C). Registre mis à jour (ligne de table + fiche). Aucun nouveau défaut ouvert.

## Diff relu
`BreadTransferSerializer.validate()` (backend/production/serializers.py) : à la mise à jour, toute valeur différente pour `from_node`, `to_node`, `initiated_by`, `quantity_sent`, `quantity_received` -> 400 `{"detail": ...}` en français ; valeur identique retirée de `attrs`. Défense en profondeur existante : `perform_update` (BUG-223) refuse déjà toute modification d'un transfert non PENDING (RESPONDED, DISPUTED, CONFIRMED, CANCELLED), même à valeurs identiques ; `perform_destroy` refuse RESPONDED/CONFIRMED/DISPUTED. Les `@expectedFailure` BUG-522 ont bien été retirés de `core/tests/test_verif_isolation_a_c.py` (git diff vérifié) ; il en reste deux, qui référencent BUG-521 (hors périmètre).

## Tests écrits : `backend/production/tests/test_verif_bug522_c.py` (17 tests)
- Matrice : 5 champs x 5 statuts x (demandeur K1, fournisseur K2) x (PATCH, PUT avec un champ falsifié) -> 400, état en base identique (snapshot de tous les champs concrets).
- Siège ADMIN/DIRECTION/COMPTABLE : même refus (400) ; tiers K3 : 404 (PATCH/PUT) ; facturier/livreur K1 et K2 : 403 ; anonyme : 401.
- Tous les champs du modèle `BreadTransfer` (via `_meta`) plus des champs inventés (`request_*`, `transfer_type`, `lines` imbriqué, `id`, `created_at`...) : un par un puis tous ensemble, jamais de 500, aucun champ modifié ; les lignes imbriquées (mass assignment) restent intactes ; `transfer_status` et `confirmed_by` ignorés.
- Aller-retour frontend : GET puis PUT complet à valeurs identiques + `notes` -> 200 pour gérant demandeur, fournisseur et DIRECTION (PENDING) ; PATCH identique ; pk en chaînes (multipart) ; non-PENDING gelé même à valeurs identiques (400) ; valeurs null / invalides / négatives -> 400 et non 500.
- Création : un gérant K3 qui envoie `from_node=K2,to_node=K1` obtient to_node=K3 (aucun transfert sans le nœud de l'appelant) ; `from_node` absent ou égal à soi -> 400 ; facturier/livreur 403, anonyme 401, siège sans nœud 400 ; statut, `confirmed_by`, `initiated_by`, `node_origin`, `quantity_received` forgés ignorés ; `transfer` forgé dans une ligne imbriquée sans effet.
- Actions `respond_to_request`, `confirm_reception`, `resolve_dispute` : cycle complet PENDING -> RESPONDED -> DISPUTED -> CONFIRMED avec `from_node`/`to_node`/`initiated_by`/`transfer_status` forgés dans le corps : nœuds inchangés ; mauvais côté 403, tiers 404, facturier/livreur 403.
Note de nommage : les statuts réels sont PENDING, RESPONDED, CONFIRMED, DISPUTED, CANCELLED (pas ACCEPTED/RECEIVED).

## Résultats
- `production.tests.test_verif_bug522_c` + `production.tests.test_bug522_transfer_nodes_readonly` : 22 tests OK.
- Lot élargi (test_verif_bug522_c, test_bug522_transfer_nodes_readonly, core.test_verif_isolation_a_c, production.test_transfers, core.test_permissions, core.test_permissions_verif_2026_10_22, production.test_verif_rotation_prod_c, production.test_daily_closure_report) : 189 tests, 0 échec, 1 ignoré, 2 échecs attendus (BUG-521). Deux échecs initiaux étaient des hypothèses erronées de mes tests (PUT sur RESPONDED/CANCELLED gelé par la garde BUG-223), corrigées ; pas un défaut applicatif.

## Questions pour le coordinateur (sans trancher)
1. Sens de la création. Le code actuel : to_node = nœud de l'appelant (demandeur), from_node = fournisseur choisi. `remarque.md` ligne 198 ([c], « A demande à B, B répond, A confirme ») et BUG-023/224 (seul from_node répond, seul to_node confirme) sont cohérents avec cette lecture ; la consigne « from_node forcé au nœud de l'appelant » correspondrait plutôt à la ligne 450 de `remarque.md` (non cochée : « envoyer des pains à une autre boulangerie sans avoir reçu la demande »), c'est-à-dire un second flux (envoi spontané) qui n'existe pas encore. Les deux lectures valent chacune pour un flux différent : à arbitrer si le flux « envoi sans demande » est développé (il faudrait alors un champ ou une action distincte plutôt que d'inverser le sens existant).
2. Le siège (ADMIN/DIRECTION/COMPTABLE) peut passer les permissions `IsGerant` sur PATCH/PUT/DELETE d'un transfert PENDING mais ne peut pas changer les nœuds (400, pour tous). Je considère cela correct ; à confirmer si le siège doit pouvoir réaffecter un transfert.

## Tickets
Aucun nouveau ticket (prochain numéro libre au moment de l'écriture : 526+, 524 et 525 déjà pris).
