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
