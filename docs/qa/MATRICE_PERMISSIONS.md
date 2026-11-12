# Matrice des permissions — ETS. KIESE

Testeur : `testeur-permissions` — 2026-10-22.

Légende attendu/observé : `✅` = accès autorisé, `❌` = refusé (403/404), `🌐` = public (AllowAny),
`🧪` = testé par un test automatisé dans `backend/core/tests/test_permissions.py` (ou test cité).
Rôles : AN = anonyme, ADM = ADMIN, DIR = DIRECTION, CPT = COMPTABLE, GER = GERANT (nœud),
FAC = FACTURIER (nœud), LIV = LIVREUR (nœud). ADM/DIR/CPT ont toujours `can_access_all_nodes=True`.

Seules les routes où un écart a été trouvé, ou qui sont au cœur du périmètre BUG-016/transversal,
sont détaillées ligne à ligne ci-dessous. L'inventaire complet des routes (tous les `router.register`
de chaque `urls.py`) est en annexe §3.

## 1. Écarts confirmés (voir tickets dans REGISTRE_BUGS.md)

| Route | Méthode | Attendu | Observé | Preuve |
|---|---|---|---|---|
| `/api/core/notifications/` | GET (list) | GER/FAC/LIV ne voient que les notifications de leur nœud | **Aucun filtrage par nœud** — tous les rôles voient toutes les notifications de tous les nœuds | 🧪 `NotificationIsolationTests.test_gerant_k1_should_not_see_notifications_of_k2` |
| `/api/core/notifications/<id>/mark_read/` | POST | GER/FAC/LIV ne peuvent agir que sur les notifications de leur nœud | Action possible sur n'importe quelle notification, de n'importe quel nœud | 🧪 `NotificationIsolationTests.test_gerant_k1_cannot_mark_read_a_k2_notification` |
| `/api/core/colis/` | GET/PATCH/DELETE | GER ne voit/modifie que les COLIS de son nœud | `ColisDistributionViewSet.get_queryset()` renvoie `.all()` sans filtre nœud | 🧪 `ColisDistributionIsolationTests.test_gerant_k1_should_not_see_colis_of_k2` |
| `/api/clients/contributions/` | GET/PATCH/DELETE | GER ne voit/modifie que la caisse sociale de son nœud | `SocialContributionViewSet.get_queryset()` renvoie `.all()` sans filtre nœud | 🧪 `SocialCaisseIsolationTests.test_gerant_k1_should_not_see_social_contributions_of_k2` |
| `/api/clients/distributions/` et `/distribution-lines/` | GET/PATCH/DELETE | idem | idem (aucun filtre nœud) | 🧪 `SocialCaisseIsolationTests.test_gerant_k1_should_not_see_social_distributions_of_k2` |
| `/api/production/movements/` | GET (list, y compris `?node=<autre>`) | GER ne voit que les mouvements de consommables de son nœud | `ConsumableMovementViewSet` n'a **aucun** `get_queryset` : tous les mouvements de toutes les boulangeries sont visibles, y compris en forçant `?node=` | 🧪 `ConsumableMovementIsolationTests` (2 tests) |
| `/api/production/transfers/` | GET (list) | GER ne voit que les transferts où son nœud est `from_node` ou `to_node` | Aucun filtre : un GER voit les transferts entre deux AUTRES boulangeries | 🧪 `BreadTransferIsolationTests.test_gerant_k1_should_not_see_transfer_between_k2_and_k3` |
| `/api/production/transfers/<id>/respond_to_request/` | POST | Seul le GER de `from_node` peut répondre | **Aucune vérification d'appartenance au nœud** — n'importe quel GER peut répondre à la place de la boulangerie concernée | 🧪 `BreadTransferIsolationTests.test_gerant_k1_cannot_respond_to_a_transfer_not_concerning_his_node` |
| `/api/production/transfers/<id>/confirm_reception/` | POST | Seul le GER de `to_node` peut confirmer | Idem — aucune vérification | 🧪 `BreadTransferIsolationTests.test_gerant_k1_cannot_confirm_reception_of_a_transfer_not_concerning_his_node` |
| `/api/clients/clients/` | POST (création, `node` forcé dans le corps) | Un GER ne peut créer un client que pour son propre nœud | `ClientViewSet.perform_create` utilise `serializer.validated_data.get('node')` **tel que fourni par le client de l'API**, sans vérifier qu'il correspond à `user.node` pour un GER | 🧪 `ClientCrossNodeWriteTests.test_gerant_cannot_create_a_client_forcing_another_node` |
| `/api/treasury/cashbook/` | GET (list) | Lecture réservée au niveau Direction (Livre de Caisse Direction, §5.5) | `permission_classes = [IsAuthenticated]`, aucun filtre nœud : un GER/FAC/LIV voit tout le Livre de Caisse Direction de toutes les boulangeries | Lecture de code (`treasury/views.py` `CashbookEntryViewSet`), pas encore testé par un cas d'échec dédié — signalé en l'état |
| `POST /api/token/refresh/` et `/api/core/auth/login/refresh/` | POST | Un endpoint de refresh JWT doit exister et fonctionner | **Aucune route de refresh n'existe** dans `kiese/urls.py` ni `core/urls.py` ; le frontend appelle une URL (`/api/core/auth/login/refresh/`) qui n'a jamais existé. Tout utilisateur est déconnecté de force après l'expiration de l'access token (30 min) | 🧪 `RefreshBlacklistTests.test_no_http_refresh_endpoint_is_reachable_at_either_candidate_url` |
| `POST /api/core/nodes/` (Nodes.tsx) | POST | Message d'erreur clair si `code` dépasse 5 caractères | Le backend renvoie bien `{"code": ["Assurez-vous que ce champ comporte au plus 5 caractères."]}` (conforme) — mais le formulaire frontend n'a ni `maxLength={5}` ni placeholder réellement contraignant, ce qui rend l'erreur 400 incomprise par l'utilisateur | 🧪 `NodeCreationValidationTests` (2 tests, confirment le comportement API ; cause frontend documentée) |

## 2. Points audités et confirmés CONFORMES (remarque.md, périmètre BUG-016 permissions/dashboard/nodes)

| Point remarque.md | Attendu | Observé | Conclusion |
|---|---|---|---|
| l.110 « Registre Blockchain » | Doit être réellement connecté au backend (`TamperAlert`/`BlockchainSnapshot`), pas statique | `frontend/src/pages/dashboard/Blockchain.tsx` appelle bien `blockchainApi.snapshots.globalStatus()`, `alerts.list()`, `runCheck()` — données réelles, pas mockées. Fonctionne d'autant mieux depuis la correction BUG-001/002/003 | **Conforme** — marqué `[c]` dans `remarque.md` l.110 |
| l.160 « Clients Actifs du Groupe » | Client actif = au moins une commande dans les 30 derniers jours | `clients/views.py::ClientViewSet.active_last_month` filtre bien `invoices__invoice_date__gte=date.today()-30j`, `Count(...) > 0` | **Conforme** — marqué `[c]` dans `remarque.md` l.160 |
| Élévation de rôle via `/users/<soi-même>/` | GER/FAC ne doivent jamais pouvoir changer `role`/`node`/`is_superuser` | `UserViewSet.get_permissions()` exige `IsDirection()` pour tout sauf list/retrieve → GER/FAC reçoivent 403 avant même d'atteindre le champ. `/auth/me/` (PATCH) filtre explicitement les champs autorisés (`first_name`, `last_name`, `phone`, `email`, `username`) — `role`/`node`/`is_superuser` ignorés silencieusement | **Conforme** — 🧪 `SelfElevationAttackTests` (2 tests, passent) |
| `credit_limit` modifiable par un facturier | Doit être refusé | `ClientViewSet.get_permissions()` exige `IsGerant()` pour update/destroy, qui exclut FACTURIER/LIVREUR du rôle | **Conforme** — 🧪 `CreditLimitAttackTests` (passe) |
| Accès aux logs d'activité | Réservé HQ (ADMIN/DIRECTION/COMPTABLE) | `ActivityLogViewSet.permission_classes = [IsHeadquarters]` | **Conforme** — 🧪 `ActivityLogAccessTests` (2 tests, passent) |
| Modification de `Config` / prix (`BreadPrice`) | ADMIN/DIRECTION uniquement | `get_permissions()` exige `IsDirection()` pour toute écriture sur les deux | **Conforme** — 🧪 `ConfigAndPricesAttackTests` (2 tests, passent) |
| Suppression d'écritures comptables (`CashbookEntry`) | Impossible (lecture seule) | `CashbookEntryViewSet` est un `ReadOnlyModelViewSet` — aucune route DELETE n'est générée | **Conforme** — 🧪 `CashbookEntryDeletionTests` (passe) |
| Modification/suppression d'un client d'un autre nœud par un facturier | Doit être refusé (l'exemption « facturier voit tous les clients » ne concerne QUE la lecture/recherche, cf. CLAUDE.md §4) | `get_permissions()` exige `IsGerant()` pour update/destroy → FACTURIER/LIVREUR exclus de ce rôle, donc 403 quel que soit le nœud. L'exemption de `get_queryset` (lignes 44-50 de `clients/views.py`) ne s'applique donc en pratique qu'en lecture | **Conforme** — 🧪 `ClientCrossNodeWriteTests` (2 tests sur 3, passent) |
| Jeton expiré / blacklist après logout (mécanisme) | Refus de rafraîchir | La classe `RefreshToken` lève bien `TokenError` après blacklist (`check_blacklist()`) | **Conforme au niveau librairie** — 🧪 `RefreshBlacklistTests.test_refresh_token_blacklisted_after_logout_cannot_mint_new_access_token` — **mais inexploitable en HTTP**, voir écart ci-dessus (absence de route) |
| Limitation des tentatives de login | 5/min puis 429 | `ScopedRateThrottle` + `throttle_scope='login'` + `DEFAULT_THROTTLE_RATES['login']='5/min'` | **Conforme** — 🧪 `LoginThrottleTests` (passe) |
| `AllowAny` limités à login / GET config / GET bread-prices | Exactement ces 3 | Grep exhaustif du code applicatif (`backend/**/*.py`, hors `.env`/site-packages) : 3 occurrences, exactement ces 3 vues. `DEFAULT_PERMISSION_CLASSES = ['IsAuthenticated']` en défaut global | **Conforme** — 🧪 `AllowAnyAuditTests` (4 tests, passent) |
| `manage.py check --deploy` avec `.env` prod simulé | 0 avertissement `security.*` | Reproduit avec `override_settings` (DEBUG=False, SECRET_KEY forte, HSTS, cookies sécurisés, ALLOWED_HOSTS renseigné) | Résultat mitigé — voir §4 (test `DeploySecurityCheckTests` actuellement en échec, cause à vérifier avant `VÉRIFIÉ` définitif, voir rapport) |

## 3. Inventaire des routes (par app, `router.register`)

- **core** (`/api/core/`) : `nodes`, `users`, `bread-prices`, `expense-categories`, `activities` (lecture seule),
  `notifications`, `colis` + `auth/login/`, `auth/logout/`, `auth/me/`, `config/`.
- **clients** (`/api/clients/`) : `clients`, `contributions`, `distributions`, `distribution-lines`
  + actions : `active_last_month`, `risk_alerts`, `best_clients`, `bassins`, `recalculate_category`,
  `import_excel`, `bulk_move`, `bulk_delete`, `deficit_report`, `toggle_paid`, `auto_populate_lines`.
- **sales** (`/api/sales/`) : `invoices` (périmètre `testeur-ventes`, BUG-013).
- **production** (`/api/production/`) : `sessions`, `bread-stocks`, `consumable-types`, `stocks`,
  `movements`, `counts`, `transfers`, `disposals` (périmètre partagé `testeur-production`, BUG-014,
  mais isolation inter-nœuds testée ici de bout en bout, cœur de métier `testeur-permissions`).
- **treasury** (`/api/treasury/`) : `expenses`, `reports`, `closures`, `cashbook` (lecture seule),
  `journal`, `savings`, `vouchers` (périmètre `testeur-tresorerie`, BUG-015, sauf le point `cashbook`
  signalé ci-dessus qui relève de l'isolation transversale).
- **commissions** (`/api/commissions/`) : `periods`, `commissions` (périmètre `testeur-clients-commissions`, BUG-012).
- **finance** (`/api/finance/`) : `years` + actions calculées (`income_statement`, `cashflow`,
  `balance_sheet`, `comparative`, `doc1_export`) — périmètre partagé avec `auditeur-comptable`, non
  détaillé ici.
- **blockchain** (`/api/blockchain/`) : `alerts`, `snapshots` — `permission_classes = [IsHeadquarters]`
  partout, `get_queryset` filtré par `?node=` en option mais accès global réservé HQ — **conforme**.

## 5. Passe du 2026-11-12 sur la base réelle (vague 2) — valeurs observées, 252 routes x 7 profils

Profils : AN anonyme, ADM/DIR/CPT (siège), GER/FAC/LIV (K5). Corps de requête vide et identifiants inexistants (UUID nul / 999999) : `401` non authentifié, `403` refusé par le rôle, `400`/`404`/`200`/`201` = le rôle a passé le contrôle de permission (la validation ou la recherche d'objet répond ensuite). `skip` = non rejoué (effet réel : `mark_all_read`, `cleanup_expired` ; `reset-data`, `login`, `logout`, `login/refresh` testés à part).

Écarts attendu/observé : voir BUG-247 à BUG-256 (`ConsumableStock` écriture FAC/LIV : lignes `production/stocks` ci-dessous ; notifications DELETE/mark_read ouverts à tous ; lecture trésorerie/commissions FAC/LIV ; schéma public).

| Route | AN | ADM | DIR | CPT | GER | FAC | LIV |
|---|---|---|---|---|---|---|---|
| `GET blockchain/alerts/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `POST blockchain/alerts/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET blockchain/alerts/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PUT blockchain/alerts/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH blockchain/alerts/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `DELETE blockchain/alerts/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `POST blockchain/alerts/{id}/resolve/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET blockchain/snapshots/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `GET blockchain/snapshots/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET blockchain/snapshots/global_status/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `POST blockchain/snapshots/run_check/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `GET clients/clients/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST clients/clients/` | 401 | 400 | 400 | 400 | 400 | 400 | 403 |
| `GET clients/clients/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT clients/clients/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH clients/clients/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE clients/clients/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST clients/clients/{id}/recalculate_category/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET clients/clients/active_last_month/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `GET clients/clients/bassins/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET clients/clients/best_clients/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST clients/clients/bulk_delete/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `POST clients/clients/bulk_move/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET clients/clients/deficit_report/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST clients/clients/import_excel/` | 401 | 415 | 415 | 415 | 403 | 403 | 403 |
| `GET clients/clients/risk_alerts/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `GET clients/contributions/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST clients/contributions/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET clients/contributions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PUT clients/contributions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH clients/contributions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE clients/contributions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST clients/contributions/{id}/toggle_paid/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST clients/contributions/bulk_create_month/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET clients/distribution-lines/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST clients/distribution-lines/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET clients/distribution-lines/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PUT clients/distribution-lines/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH clients/distribution-lines/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE clients/distribution-lines/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET clients/distributions/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST clients/distributions/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET clients/distributions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PUT clients/distributions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH clients/distributions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE clients/distributions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST clients/distributions/{id}/auto_populate_lines/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET commissions/commissions/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST commissions/commissions/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET commissions/commissions/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT commissions/commissions/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH commissions/commissions/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `DELETE commissions/commissions/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `POST commissions/commissions/{id}/mark_paid/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH commissions/commissions/{id}/set_manuel/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET commissions/commissions/payroll_listing/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET commissions/periods/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST commissions/periods/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET commissions/periods/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT commissions/periods/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH commissions/periods/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `DELETE commissions/periods/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `POST commissions/periods/{id}/close_period/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `POST commissions/periods/generate/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET commissions/periods/history/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `GET core/activities/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `GET core/activities/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET core/auth/me/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `PATCH core/auth/me/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET core/bread-prices/` | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST core/bread-prices/` | 401 | 400 | 400 | 403 | 403 | 403 | 403 |
| `GET core/bread-prices/{id}/` | 404 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT core/bread-prices/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `PATCH core/bread-prices/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `DELETE core/bread-prices/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `GET core/colis/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST core/colis/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET core/colis/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PUT core/colis/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH core/colis/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE core/colis/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET core/config/` | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| `PUT core/config/` | 401 | 200 | 200 | 403 | 403 | 403 | 403 |
| `PATCH core/config/` | 401 | 200 | 200 | 403 | 403 | 403 | 403 |
| `GET core/expense-categories/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST core/expense-categories/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET core/expense-categories/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT core/expense-categories/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH core/expense-categories/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `DELETE core/expense-categories/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET core/nodes/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST core/nodes/` | 401 | 400 | 400 | 403 | 403 | 403 | 403 |
| `GET core/nodes/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT core/nodes/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `PATCH core/nodes/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `DELETE core/nodes/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `GET core/notifications/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST core/notifications/` | 401 | 201 | 201 | 201 | 403 | 403 | 403 |
| `GET core/notifications/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT core/notifications/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH core/notifications/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `DELETE core/notifications/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `POST core/notifications/{id}/mark_read/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `POST core/notifications/mark_all_read/` | 401 | skip | skip | skip | skip | skip | skip |
| `GET core/users/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `POST core/users/` | 401 | 400 | 400 | 403 | 403 | 403 | 403 |
| `GET core/users/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PUT core/users/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `PATCH core/users/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `DELETE core/users/{id}/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `POST core/users/{id}/reset_password/` | 401 | 404 | 404 | 403 | 403 | 403 | 403 |
| `GET finance/years/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `POST finance/years/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET finance/years/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PUT finance/years/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH finance/years/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `DELETE finance/years/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET finance/years/{id}/balance_sheet/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET finance/years/{id}/cashflow/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET finance/years/{id}/comparative/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET finance/years/{id}/income_statement/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET finance/years/doc1_export/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET finance/years/doc1_report/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET finance/years/summary/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `GET production/bread-stocks/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET production/bread-stocks/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `GET production/bread-stocks/by-date/` | 401 | 400 | 400 | 400 | 200 | 200 | 200 |
| `GET production/consumable-types/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST production/consumable-types/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET production/consumable-types/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT production/consumable-types/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH production/consumable-types/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `DELETE production/consumable-types/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET production/counts/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST production/counts/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET production/counts/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PUT production/counts/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH production/counts/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE production/counts/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET production/daily-closure/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET production/disposals/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST production/disposals/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET production/disposals/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PUT production/disposals/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH production/disposals/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE production/disposals/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET production/movements/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST production/movements/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET production/movements/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PUT production/movements/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH production/movements/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE production/movements/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET production/movements/flour_history/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET production/opening-confirmation/` | 401 | 400 | 400 | 400 | 200 | 200 | 403 |
| `POST production/opening-confirmation/` | 401 | 400 | 400 | 400 | 400 | 400 | 403 |
| `GET production/sessions/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST production/sessions/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET production/sessions/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT production/sessions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH production/sessions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE production/sessions/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST production/sessions/{id}/close/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET production/sessions/reconciliation/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `GET production/sessions/shift-end-status/` | 401 | 400 | 400 | 400 | 200 | 200 | 200 |
| `GET production/stocks/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST production/stocks/` | 401 | 400 | 400 | 400 | 400 | 400 | 400 |
| `GET production/stocks/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT production/stocks/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PATCH production/stocks/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `DELETE production/stocks/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `GET production/team-assignment/` | 401 | 400 | 400 | 400 | 200 | 200 | 403 |
| `POST production/team-assignment/` | 401 | 400 | 400 | 400 | 400 | 400 | 403 |
| `GET production/transfers/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST production/transfers/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET production/transfers/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT production/transfers/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH production/transfers/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE production/transfers/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST production/transfers/{id}/confirm_reception/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST production/transfers/{id}/resolve_dispute/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST production/transfers/{id}/respond_to_request/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET sales/invoices/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST sales/invoices/` | 401 | 400 | 400 | 400 | 400 | 400 | 403 |
| `GET sales/invoices/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PATCH sales/invoices/{id}/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `POST sales/invoices/{id}/adjust/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST sales/invoices/{id}/cancel/` | 401 | 404 | 404 | 404 | 404 | 404 | 403 |
| `POST sales/invoices/{id}/deliver/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `GET sales/invoices/bread_summary/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST sales/invoices/cleanup_expired/` | 401 | skip | skip | skip | skip | skip | skip |
| `GET sales/invoices/daily_summary/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET sales/invoices/pending_deliveries/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET sync/conflicts/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `POST sync/handshake/` | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| `GET sync/local-status/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET sync/pull/` | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| `POST sync/push/` | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| `GET sync/status/` | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| `GET treasury/cashbook/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `GET treasury/cashbook/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET treasury/cashbook/integrity_check/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `GET treasury/cashbook/period_summary/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `GET treasury/closures/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST treasury/closures/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET treasury/closures/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT treasury/closures/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH treasury/closures/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE treasury/closures/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST treasury/closures/{id}/push_to_cashbook/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `POST treasury/closures/{id}/reject/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `POST treasury/closures/{id}/validate/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET treasury/direction-cash-counts/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `POST treasury/direction-cash-counts/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET treasury/direction-cash-counts/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET treasury/expenses/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `POST treasury/expenses/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET treasury/expenses/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PUT treasury/expenses/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH treasury/expenses/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE treasury/expenses/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET treasury/journal/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST treasury/journal/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET treasury/journal/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `GET treasury/journal/monthly_report/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET treasury/journal/suggested_ca/` | 401 | 400 | 400 | 400 | 400 | 400 | 400 |
| `GET treasury/reports/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST treasury/reports/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET treasury/reports/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT treasury/reports/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH treasury/reports/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE treasury/reports/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST treasury/reports/{id}/validate/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `POST treasury/reports/generate/` | 401 | 200 | 200 | 200 | 200 | 403 | 403 |
| `GET treasury/savings/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `POST treasury/savings/` | 401 | 400 | 400 | 400 | 400 | 403 | 403 |
| `GET treasury/savings/{id}/` | 401 | 404 | 404 | 404 | 404 | 404 | 404 |
| `PUT treasury/savings/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `PATCH treasury/savings/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `DELETE treasury/savings/{id}/` | 401 | 404 | 404 | 404 | 404 | 403 | 403 |
| `GET treasury/savings/monthly_total/` | 401 | 200 | 200 | 200 | 200 | 200 | 200 |
| `GET treasury/vouchers/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |
| `POST treasury/vouchers/` | 401 | 400 | 400 | 400 | 403 | 403 | 403 |
| `GET treasury/vouchers/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PUT treasury/vouchers/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `PATCH treasury/vouchers/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `DELETE treasury/vouchers/{id}/` | 401 | 404 | 404 | 404 | 403 | 403 | 403 |
| `GET treasury/vouchers/final_report/` | 401 | 200 | 200 | 200 | 403 | 403 | 403 |

