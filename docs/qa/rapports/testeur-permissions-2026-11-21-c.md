# Rapport testeur-permissions — vérification croisée Dev C — 2026-11-21 (c)

Branche `dev-c`. Aucun code applicatif modifié ; aucun commit. Tests : `backend/core/tests/test_verif_matrice_c.py` (45 tests). Données fictives.

## 1. Verdicts par ticket

| Ticket | Verdict | Preuve |
|---|---|---|
| BUG-247 (élévation de rôle, reset ADMIN) | VÉRIFIÉ (testeur-permissions, Dev C) | `V247` : tous rôles : PATCH/PUT de soi-même sur `role`/`node`/`is_active` = 403, `is_superuser`/`is_staff` ignorés ; création/reset/suppression d'un ADMIN ou superuser par DIRECTION = 403 ; ADMIN ne se rétrograde ni ne se supprime ; `change-password` et `/auth/me/` ignorent `role`/`node`/flags |
| BUG-248 (mot de passe de reset) | VÉRIFIÉ | `V248` : aléatoire (≥ 10 car.), jamais l'identifiant, différent à chaque reset, absent du `detail` et du journal, `must_change_password` posé ; reset refusé sous DIRECTION (403), anonyme 401 |
| BUG-249 (caisse sociale inter-nœuds) | VÉRIFIÉ | `V249` : POST avec client K2 (node K1 ou K2), `bulk_create_month` node=K2, PATCH/DELETE d'une cotisation K2, déplacement d'une cotisation K1 vers un client K2 : tout refusé, rien créé ni modifié |
| BUG-250 (plafond/taux à la création) | VÉRIFIÉ | `V250` : facturier : plafond 9 999 999 et taux 0,30 ramenés à 50 000 / 0,25, `node` forcé K1, PATCH 403 ; gérant : bornes 400, client K2 403/404 |
| BUG-251 (écriture des stocks) | VÉRIFIÉ pour `/stocks/` (voir BUG-504 pour `/movements/`) | `V251` : FAC/LIV lecture seule (POST/PUT/PATCH/DELETE 403) ; gérant : `quantity`, `average_unit_cost`, `node` ignorés ; détail/PATCH/DELETE d'un stock K2 = 404 |
| BUG-252 (notifications globales) | VÉRIFIÉ | `V252` : DELETE/mark_read/PATCH/POST d'une alerte CLOUD = 403 pour GER/FAC/LIV ; `mark_all_read` épargne CLOUD ; notification K2 invisible (404) ; DIRECTION `mark_read` 200 |
| BUG-255 (AllowAny / schéma / config) | VÉRIFIÉ | Config anonyme = `{"on_line"}` seul ; seuls login, refresh, GET config, GET bread-prices (liste + détail) sont `AllowAny` (contrôle sur toutes les classes de vue) ; avec `DJANGO_DEBUG=False` : `/api/schema/`, `/api/docs/swagger/`, `/api/docs/redoc/` = 401 anonyme, 200 authentifié |
| BUG-253 | non tranché | Question client : un facturier ou un livreur doit-il pouvoir CONSULTER clôtures, épargne, journal et commissions de sa boulangerie ? Décision du 2026-11-13 = non, appliquée et rejouée (FAC/LIV = 403, y compris `cleanup_expired`). Reste à confirmer que le livreur ne doit pas lancer `cleanup_expired`. |
| BUG-266/267/268 | non tranchés | Question client : confirmer, sur un exemple chiffré de client à BP créditrice, que (266) un net négatif n'est pas payable, (267) les clients épargne n'ont pas de commission, (268) seul le report est retenu (pas la dette en double). |

### BUG-255 et BUG-401 (consigné, non corrigé)
- `DJANGO_DEBUG=True` : `core.tests.test_verif_bug247_248_252_255_testeur_permissions.Bug255.test_schema_requires_auth_outside_debug` ÉCHOUE (`['AllowAny'] != ['IsAuthenticated']`). Cause : le runner force `settings.DEBUG=False` après l'import de `kiese/settings.py`, mais `SPECTACULAR_SETTINGS['SERVE_PERMISSIONS']` a été figé d'après la variable d'environnement. C'est BUG-401 (ticket de B).
- `DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY` temporaire, `DJANGO_SECURE_SSL_REDIRECT=False` (sinon 301 sur toutes les requêtes de test) : ce test passe. Mon `V255.test_schema_policy_matches_debug` lit `DJANGO_DEBUG` dans l'environnement (pas `settings.DEBUG`) et passe dans les deux modes.

## 2. Tickets ouverts (registre : BUG-503 à 507)

| Ticket | Gravité | Résumé |
|---|---|---|
| BUG-503 | Bloquant | `POST /treasury/reports/` : un gérant K1 crée un rapport facturier pour K2 en forgeant `node` (201) |
| BUG-504 | Bloquant | `POST /production/movements/` : un gérant K1 modifie quantité et CUMP du stock de K2 en forgeant `stock` (stock K2 0 -> 5, CUMP 0 -> 1 000) |
| BUG-505 | Majeur | `GET /production/movements/flour_history/?node=K2` lisible par un non-siège (`IsAuthenticated`) |
| BUG-506 | Majeur | Compte non-siège sans boulangerie : création acceptée, vue de tous les nœuds, auto-création (BUG-147) de stocks de tout nœud via `?node=` |
| BUG-507 | Mineur, À CLARIFIER | Le livreur a aussi la recherche de clients inter-boulangeries (la spec ne vise que le facturier) |

Les tests correspondants sont `@expectedFailure` avec le numéro du ticket (7 marqueurs ; BUG-506 en porte 3).

## 3. Points demandés

- **`recompute_cump` (BUG-357)** : aucune route ni action ne contient `cump` ou `recompute` (toutes les URL `/api/` énumérées) ; les URL plausibles répondent 401/404/405 en anonyme et en ADMIN ; `production.views` n'importe pas la commande. Non exposée. `average_unit_cost` n'est modifiable par aucun rôle via `/stocks/` (PATCH/PUT des 6 rôles : inchangé). Tests : `IsolationProduction::test_recompute_cump_not_exposed`, `test_no_cump_manipulation_via_api`.
- **Auto-création de `ConsumableStock` (BUG-147)** : gérant/facturier/livreur K1 avec `?node=K2`, `?node=999999` (400) ou deux `node` : aucun stock créé pour K2, liste limitée à K1 ; `?node=<invalide>` pour DIRECTION : pas de 500. Réserves : BUG-506 (compte sans boulangerie) et BUG-504 (l'écriture inter-nœuds passe par les mouvements, pas par la création de comptes de stock).
- **Rapports rétroactifs (BUG-175)** : le tableau n'utilise que `GET/POST /treasury/reports/`, `reports/generate/` et `reports/{id}/validate/` (lecture de `Treasury.tsx` et `services.ts`). `generate` et `validate` : FAC/LIV 403, anonyme 401, rapport K2 = 404 pour un gérant K1, `node` du corps ignoré par `generate` pour un non-siège, liste filtrée même avec `?node=K2`. Seule la création directe `POST /reports/` fuit (BUG-503) ; le tableau ne l'utilise pas.
- **Exception 5.1** : facturier K1 recherche les clients de K2 (OK), PATCH/DELETE = 403 ; gérant K1 sur client K2 = 403/404 (BUG-507 pour le livreur).
- **JWT** (`JwtAuth`) : refresh après logout 401 ; rotation (ancien refresh refusé) ; access expiré, signature altérée, `alg=none`, access utilisé comme refresh : 401 ; compte désactivé : 401 ; 6e tentative de login sur un compte = 429 (même le bon mot de passe), un autre compte n'est pas bloqué ; `must_change_password` : toutes les routes 403 sauf `/auth/me/` ; routes `/api/sync/*` refusées aux JWT humains (sauf `conflicts/`, siège par conception) et à l'anonyme.

## 4. Matrice rejouée (262 couples route x méthode, 7 profils)

Énumération automatique (`EndpointEnumerator`), corps `{}`, identifiant nul. 401 = non authentifié, 403 = refusé par le rôle, 404/400/200 = a passé le contrôle de rôle. GER/FAC/LIV = K1 ; AN = anonyme. Routes `sync/*` (jeton de nœud) hors boucle, testées à part. Contrôles automatiques : aucun 5xx ; anonyme 401 hors liste publique ; GERANT refusé implique FAC et LIV refusés ; ADMIN jamais plus restreint (exception documentée : `GET chat/conversations/node/`, ADMIN/DIR/CPT 403 car sans nœud, GER/FAC/LIV 200).

| AN | ADM | DIR | CPT | GER | FAC | LIV | Nb | Routes (méthode chemin) |
|---|---|---|---|---|---|---|---|---|
| 401 | 404 | 404 | 404 | 404 | 403 | 403 | 69 | écriture/détail clients (`clients/clients/{pk}/` PUT/PATCH/DELETE), contributions, distributions, lignes, colis, counts, disposals, movements, sessions (PATCH/DELETE/close), stocks (PUT/PATCH/DELETE), transfers (PATCH/DELETE, confirm_reception, resolve_dispute, respond_to_request), closures/expenses/savings (PATCH/DELETE), reports (PATCH/DELETE, `validate`), `sales/invoices/{pk}/adjust/`, `clients/{pk}/history/`, `recalculate_category`, `toggle_paid`, `auto_populate_lines`, `refresh_indices` |
| 401 | 404 | 404 | 404 | 403 | 403 | 403 | 40 | détail/écriture sur `blockchain/alerts`, `blockchain/snapshots/{pk}`, `commissions/commissions` et `periods` (DELETE/PATCH/PUT, `close_period`), `core/expense-categories`, `core/activities/{pk}`, `core/users/{pk}` (GET), `core/notifications/{pk}` PATCH/PUT, `finance/years/{pk}` et états, `production/consumable-types`, `treasury/cashbook/{pk}`, `direction-cash-counts/{pk}`, `vouchers`, `closures/{pk}/validate|reject|push_to_cashbook` |
| 401 | 200 | 200 | 200 | 200 | 200 | 200 | 23 | `chat/conversations/`, `chat/unread-count/`, `chat/users/`, `clients/clients/` (GET), `core/auth/me/` (GET/PATCH), `core/auth/logout/`, `core/expense-categories/`, `core/nodes/`, `core/notifications/` (GET, `mark_all_read`), `production/bread-stocks/`, `consumable-types/`, `movements/flour_history/` (voir BUG-505), `sessions/`, `stocks/`, `transfers/`, `sales/invoices/` (liste, `bread_summary`, `daily_summary`, `pending_deliveries`), `sync/local-status/`, `treasury/reports/` (GET) |
| 401 | 200 | 200 | 200 | 200 | 403 | 403 | 21 | `clients/clients/active_last_month|best_clients|deficit_report|risk_alerts`, `clients/contributions/`, `distribution-lines/`, `distributions/`, `commissions/commissions/`, `periods/`, `core/colis/`, `production/counts/`, `disposals/`, `movements/`, `sessions/reconciliation/`, `treasury/closures/`, `expenses/`, `journal/` (+ `monthly_report`), `savings/` (+ `monthly_total`), `POST sales/invoices/cleanup_expired/` |
| 401 | 400 | 400 | 400 | 400 | 403 | 403 | 21 | `POST` de création gérant+ : contributions (+ `bulk_create_month`), distribution-lines, distributions, colis, counts, disposals, movements, sessions, stocks, transfers, closures, expenses, journal, reports, savings ; `GET clients/clients/bassins/`, `production/daily-closure/` (+ `clients/`), `treasury/journal/suggested_ca/`, `PATCH sales/invoices/{pk}/` |
| 401 | 404 | 404 | 404 | 404 | 404 | 404 | 19 | objets forgés accessibles à tout authentifié mais absents : `core/notifications/{pk}` (GET/DELETE, `mark_read`), `clients/clients/{pk}/`, `core/nodes/{pk}/`, `core/expense-categories/{pk}/`, `production/bread-stocks|consumable-types|sessions|stocks|transfers/{pk}/` (GET), `sales/invoices/{pk}/` (GET, `deliver`, `mark-not-served`), `treasury/reports/{pk}/` (GET), `chat/conversations/{pk}/messages|read`, `chat/conversations/direct/` |
| 401 | 200 | 200 | 200 | 403 | 403 | 403 | 16 | siège seul : `blockchain/alerts/`, `snapshots/` (+ `global_status`, `POST run_check`), `chat/conversations/direction/`, `commissions/periods/history/`, `core/activities/`, `core/users/` (GET), `finance/years/` (+ `summary`), `treasury/cashbook/` (+ `integrity_check`, `period_summary`), `direction-cash-counts/`, `vouchers/` (+ `final_report`) |
| 401 | 400 | 400 | 400 | 403 | 403 | 403 | 14 | siège seul, création : `blockchain/alerts/`, `clients/clients/bulk_delete|bulk_move`, `commissions/commissions/`, `periods/` (+ `generate`), `commissions/commissions/payroll_listing/`, `core/expense-categories/`, `finance/years/` (+ `doc1_export`, `doc1_report`), `production/consumable-types/`, `treasury/direction-cash-counts/`, `vouchers/` |
| 401 | 404 | 404 | 403 | 403 | 403 | 403 | 12 | direction seule (COMPTABLE refusé) : `core/bread-prices/{pk}` PUT/PATCH/DELETE, `core/nodes/{pk}` PUT/PATCH/DELETE, `core/users/{pk}` PUT/PATCH/DELETE, `core/users/{pk}/reset_password/`, `commissions/{pk}/mark_paid`, `set_manuel` |
| 200 | 200 | 200 | 200 | 200 | 200 | 200 | 5 | publics : `core/bread-prices/`, `core/config/` (GET, réduit à `on_line` en anonyme), et en DEBUG seulement `schema/`, `docs/swagger/`, `docs/redoc/` (401 hors DEBUG) |
| 401 | 400 | 400 | 400 | 400 | 400 | 403 | 4 | `POST clients/clients/`, `POST sales/invoices/`, `POST production/opening-confirmation/`, `team-assignment/` |
| 401 | 400 | 400 | 403 | 403 | 403 | 403 | 3 | `POST core/bread-prices/`, `POST core/nodes/`, `POST core/users/` |
| 401 | 403 | 403 | 403 | 403 | 403 | 403 | 2 | `GET`/`POST core/reset-data/` (superuser strict : même ADMIN refusé) |
| 401 | 400 | 400 | 400 | 200 | 200 | 200 | 2 | `production/bread-stocks/by-date/`, `sessions/shift-end-status/` |
| 401 | 400 | 400 | 400 | 200 | 200 | 403 | 2 | `GET production/opening-confirmation/`, `team-assignment/` |
| 401 | 200 | 200 | 403 | 403 | 403 | 403 | 2 | `PUT`/`PATCH core/config/` (direction seule) |
| 401 | 403 | 403 | 403 | 200 | 200 | 200 | 1 | `GET chat/conversations/node/` |
| 404 | 404 | 404 | 404 | 404 | 404 | 404 | 1 | `GET core/bread-prices/{pk}/` (public, objet absent) |
| 401 | 415 | 415 | 415 | 403 | 403 | 403 | 1 | `POST clients/clients/import_excel/` |
| 401 | 400 | 400 | 400 | 400 | 400 | 400 | 1 | `POST core/auth/change-password/` |
| 401 | 201 | 201 | 201 | 403 | 403 | 403 | 1 | `POST core/notifications/` (siège seul ; un corps vide crée une notification, sans gravité) |
| 401 | 404 | 404 | 404 | 404 | 404 | 403 | 1 | `POST sales/invoices/{pk}/cancel/` |
| 401 | 400 | 400 | 400 | 200 | 403 | 403 | 1 | `POST treasury/reports/generate/` |

(Le groupement par profil de statuts résume la matrice complète ; l'export brut route par route s'obtient avec `MATRICE_C_OUT=<fichier.json>`.)

### Écarts par rapport à la passe du 2026-11-12 (MATRICE_PERMISSIONS.md §5)
- Durcissements attendus : `production/stocks` écriture FAC/LIV 404 -> 403 (BUG-251) ; `treasury/closures|savings|journal` et `commissions/commissions|periods` lecture FAC/LIV 200 -> 403 (BUG-253) ; `commissions/{id}/mark_paid` et `set_manuel` COMPTABLE 404 -> 403 (restriction postérieure, sans ticket) ; `sales/invoices/cleanup_expired` FAC/LIV 200 -> 403 (point laissé ouvert dans BUG-253, désormais fermé).
- Nouvelles routes : `chat/*`, `clients/{id}/history/`, `clients/distributions/{id}/refresh_indices/`, `core/auth/change-password/`, `core/auth/logout/`, `core/notifications/mark_all_read/`, `core/reset-data/`, `production/daily-closure/clients/`, `sales/invoices/{id}/mark-not-served/`.
- Aucune ouverture involontaire détectée par le balayage ; les écarts BUG-503 à 506 viennent des tests ciblés (corps forgé, identifiant d'un autre nœud, compte sans nœud), que le balayage à corps vide ne peut pas voir.

## 5. Exécution
- `DJANGO_DEBUG=True` : `core.tests.test_verif_matrice_c` -> Ran 45, OK (expected failures=7).
- `DJANGO_DEBUG=False` + clé temporaire + `DJANGO_SECURE_SSL_REDIRECT=False` : `test_verif_matrice_c` + `test_verif_bug247_248_252_255_testeur_permissions` -> Ran 61, OK (expected failures=7).
- `DJANGO_DEBUG=True`, test BUG-255 de B seul : 1 échec (BUG-401, connu).
- Non couvert : routes `sync/*` à jeton de nœud (autre campagne, `architecte-sync`), corps valides pour toutes les routes d'écriture (le balayage envoie `{}`), isolation des factures/stocks de pain par UUID réels (couvert par `test_permissions_regression_2026_11_19.py`).
