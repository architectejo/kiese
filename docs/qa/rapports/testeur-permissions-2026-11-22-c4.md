# Rapport testeur-permissions (Dev C) - 2026-11-22-c4 : vérification BUG-521

## Verdict
BUG-521 : **VÉRIFIÉ**. Deux défauts voisins ouverts : BUG-531 (bloquant, `bassins`), BUG-532 (mineur).

## Revue du diff (e2f8c98, `clients/views.py::deficit_report`)
- Permission `IsGerant` (gérant et au-dessus). Facturier et livreur : 403, conforme à BUG-253. Anonyme : 401.
- Compte sans boulangerie : `[]`. Non-siège : `period_qs` borné à `user.node_id`, `?node=` ignoré. Siège : `int(node)` sinon 400 `{"detail"}`.
- Les commissions viennent de la période retenue, donc du nœud retenu : pas de fuite par pagination, `count`, `page_size`, `limit`, `format`. La route renvoie une liste simple non paginée. Il n'existe pas d'export.
- Remarque : le `get_permissions()` de `ClientViewSet` (retour par défaut `IsGerant`) prime sur le `permission_classes` des `@action`. Les `@action(permission_classes=[IsAuthenticated])` de `bassins`, `risk_alerts`, `best_clients` et `active_last_month` sont donc en réalité `IsGerant` (facturier : 403 observé).

## Tests écrits : `backend/clients/tests/test_verif_bug521_c.py` (13 tests)
- Isolation : le gérant K1 ne voit jamais K2 avec 12 variantes (`?node=pk`, `?node=code`, `ZZZ`, `P2`, vide, inexistant, doublon, `page_size`, `page`, `limit`, `format`). Symétrie K2. Gérant d'un 3e nœud sans période : vide, y compris avec `?node=K1/K2`. Une période plus récente de K2 n'est pas servie à K1.
- Rôles : 6 rôles et anonyme (200 pour ADMIN, DIRECTION, COMPTABLE, GERANT ; 403 pour FACTURIER et LIVREUR ; 401 anonyme). POST/PUT/PATCH/DELETE : 404 ou 405. Comptes sans nœud : gérant 200 vide, facturier et livreur 403.
- Siège : filtre par nœud pour les 3 rôles HQ ; `ZZZ`, `P2`, `1.5`, `1e3`, `0x1`, `%00`, `1'--`, `-1x` donnent 400 avec `detail` ; `999999` donne 200 vide.
- Contenu légitime : le gérant K1 reçoit exactement ses clients en déficit avec les mêmes chiffres (commande, CM, dette, déficit, période = la plus récente de K1, 7 clés), triés par dette décroissante ; le client sain et la période ancienne sont exclus.
- Boîte noire de `bassins` (l.312-369) : voir BUG-531.
- `@expectedFailure` : 3 BUG-531 et 1 BUG-532.

## `core/tests/test_verif_isolation_a_c.py::DeficitReportLeak`
Les marques `@expectedFailure` BUG-521 sont déjà retirées par le Dev B. Les deux tests passent pour la bonne raison : gérant 200 sans le code de K2, facturier et livreur 403, `?node=P2` sans 500. Aucune marque restante à retirer.

## Résultats
`manage.py test clients.tests.test_verif_bug521_c clients.tests.test_bug521_deficit_report_isolation core.tests.test_verif_isolation_a_c` : 62 tests, OK (expected failures=4).

## Tickets ouverts
- **BUG-531 (bloquant)** : `bassins` ne compare pas `node` à `user.node`. Le gérant K1 lit les clients et CM de K2 ; `?node=ZZZ` donne 500 ; un gérant sans boulangerie lit aussi K2.
- **BUG-532 (mineur)** : `deficit_report?node=<40 chiffres>` donne `OverflowError`, 500 pour le siège. Probablement présent sur les autres `?node=` entiers (BUG-526 à 530).

Le registre n'a pas encore tranché la décision « gérant et au-dessus » pour `deficit_report` : le Dev B signale l'impact frontend (carte « Déficitaires » : un facturier ou livreur reçoit 403, affichage « - »).
