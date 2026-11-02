# Rapport — dev-backend (balayage sécurité/isolation) — 2026-10-22

## Périmètre traité

BUG-022, BUG-023, BUG-024, BUG-025, BUG-026 — tous passés à `CORRIGÉ` dans `docs/qa/REGISTRE_BUGS.md` (fiches complètes : cause, fichiers modifiés, test de non-régression, impact API/frontend). Aucun de ces tickets n'a été passé à `VÉRIFIÉ` — cette vérification revient à `testeur-permissions` (ou au coordinateur), conformément à CLAUDE.md §7 règle 3.

Un nouveau ticket **BUG-044** (Mineur, frontend) a été ouvert pour `dev-frontend`, conséquence directe de la correction de BUG-026 (voir détail plus bas).

## Détail des corrections

### BUG-022 — 5 ViewSets sans filtrage par nœud
- `backend/core/views.py::SystemNotificationViewSet` : ajout de `get_queryset()` filtrant par `node_origin__in=[user.node.code, 'CLOUD']` pour un utilisateur non-HQ (`SystemNotification` n'a pas de FK `node`, seulement `node_origin` — les alertes `CLOUD`/siège restent visibles de tous). `mark_all_read` limité à `self.get_queryset()`.
- `backend/core/views.py::ColisDistributionViewSet.get_queryset` : filtre `node=user.node`.
- `backend/production/views.py::ConsumableMovementViewSet` : ajout de `get_queryset()` (filtre `node=user.node`), absent jusqu'ici contrairement aux autres ViewSets du même fichier.
- `backend/clients/views.py::SocialContributionViewSet.get_queryset`, `SocialDistributionViewSet.get_queryset` : filtre `node=user.node`.
- `backend/clients/views.py::SocialDistributionLineViewSet.get_queryset` : filtre `distribution__node=user.node` (pas de FK `node` directe sur ce modèle).
- Test de non-régression : `backend/core/tests/test_permissions.py` — `NotificationIsolationTests`, `ColisDistributionIsolationTests`, `ConsumableMovementIsolationTests`, `SocialCaisseIsolationTests` (7 tests), décorateurs `@unittest.expectedFailure` retirés, tous passent.

### BUG-023 — `BreadTransferViewSet`
- `get_queryset()` ajouté : pour un utilisateur non-HQ, `Q(from_node=user.node) | Q(to_node=user.node)`.
- Nouvelle méthode `_check_node_involved(request, *allowed_nodes)` : lève `PermissionDenied` (403) si l'utilisateur non-HQ n'appartient à aucun des nœuds autorisés.
- `respond_to_request` : vérifie `transfer.from_node_id` (seule la boulangerie fournisseuse répond).
- `confirm_reception` : vérifie `transfer.to_node_id` (seule la boulangerie destinataire confirme).
- Un tiers totalement étranger au transfert est déjà exclu par `get_queryset()` (404 avant même d'atteindre la vérification de nœud).
- Test de non-régression : `backend/core/tests/test_permissions.py::BreadTransferIsolationTests` (3 tests) + `backend/production/tests/test_transfers.py::ThreeStepTransferWorkflowTests` (2 tests, `@expectedFailure` retiré). Les scénarios existants du flux complet (3 étapes, litige, double validation) continuent de passer.

### BUG-024 — Endpoint de rafraîchissement JWT
- `backend/core/urls.py` : ajout de `path('auth/login/refresh/', TokenRefreshView.as_view(), name='token_refresh')` — exposé exactement à l'URL `/api/core/auth/login/refresh/` déjà appelée par `frontend/src/api/client.ts:39`. Aucune modification frontend (pas nécessaire, le contrat attendu correspond déjà).
- `TokenRefreshView` applique nativement `ROTATE_REFRESH_TOKENS=True`/`BLACKLIST_AFTER_ROTATION=True` (BUG-006) : un refresh token blacklisté après `logout` est rejeté par ce véritable endpoint HTTP (401).
- Test de non-régression : `backend/core/tests/test_permissions.py::RefreshBlacklistTests` — le test documentant l'absence de route (qui attendait 404) est remplacé par deux tests positifs (`test_refresh_endpoint_now_wired_at_the_exact_url_the_frontend_calls`, `test_refresh_endpoint_rejects_a_blacklisted_refresh_token`), tous deux passent.
- Impact : les utilisateurs ne seront plus déconnectés de force toutes les 30 minutes.

### BUG-025 — `ClientViewSet.perform_create`
- Pour `not user.can_access_all_nodes`, le `node` du payload est désormais totalement ignoré : `node = user.node` est imposé sans condition. Le comportement pour un utilisateur HQ (qui peut légitimement choisir le nœud) est inchangé.
- Test de non-régression : `backend/core/tests/test_permissions.py::ClientCrossNodeWriteTests::test_gerant_cannot_create_a_client_forcing_another_node`, `@unittest.expectedFailure` retiré, passe.

### BUG-026 — `CashbookEntryViewSet` (Livre de Caisse Direction)
**Décision prise et documentée** (le ticket demandait explicitement de trancher plutôt que de deviner) : restriction à `IsHeadquarters` (ADMIN/DIRECTION/COMPTABLE), **pas** un filtrage par nœud comme les autres ressources locales. Justification :
1. cahierDesCharges.md §5.1.3 qualifie ce registre de « Livre de Caisse Direction (Siège Central) » — document consolidé de direction, par nature différent de `CashClosure` (Niveau 2, lui bien scopé par nœud/`IsGerant`).
2. `DisbursementVoucherViewSet` (sorties de cette même caisse, même fichier `treasury/views.py`) est déjà `permission_classes = [IsHeadquarters]`. Un filtrage par nœud du `CashbookEntryViewSet` aurait créé une incohérence : un GERANT aurait vu les entrées de sa boulangerie mais jamais les sorties correspondantes (`DisbursementVoucher` n'a pas de FK `node`).
3. Aucune mention dans CLAUDE.md/cahierDesCharges.md/remarque.md d'un usage normal du Livre de Caisse Direction par un GERANT/FACTURIER/LIVREUR — pas d'ambiguïté métier identifiée justifiant un `À CLARIFIER`.

Fichier modifié : `backend/treasury/views.py::CashbookEntryViewSet.permission_classes` → `[IsHeadquarters]` (déjà importé dans ce fichier).

Test de non-régression : l'ancien test (prémisse incompatible — attendait un 200 filtré) est remplacé par `backend/core/tests/test_permissions.py::CashbookEntryIsolationTests::test_gerant_k1_cannot_read_the_direction_cashbook_at_all` (403) et `test_comptable_can_read_the_direction_cashbook` (200). Suite `backend/treasury/tests/test_cashbook_level3.py` relancée sans régression (ces tests n'utilisaient déjà que `comptable` pour lire `/api/treasury/cashbook/`).

**Impact API — changement de contrat signalé** : `GET /api/treasury/cashbook/` (et `integrity_check/`, `period_summary/`) renvoient désormais 403 pour tout rôle non-HQ, au lieu de 200 (avec fuite). `frontend/src/pages/dashboard/Treasury.tsx` appelle ces endpoints sans condition de rôle → **ticket BUG-044 ouvert pour dev-frontend** (masquer la section pour les rôles non-HQ, garde déjà utilisée ailleurs dans ce même fichier via `user?.can_access_all_nodes`).

## Vérifications de fin de session

- `python manage.py check` : 0 problème.
- `python manage.py test` (suite complète, 189 tests) : **OK**, 16 échecs attendus (`expected failures`) — ce sont les faux positifs de concurrence SQLite déjà documentés par `architecte-sync`/`ingenieur-blockchain` dans leurs propres rapports (pré-existants, non introduits par ce travail). Aucun échec réel.
  - Note technique : `manage.py test` doit être lancé avec `DJANGO_DEBUG=True` dans l'environnement (le vrai `.env` de dev n'existe pas encore sur ce poste — `backend/.env` reste le dossier venv historique, BUG-007) et avec l'interpréteur de `backend/.env/Scripts/python.exe` (le `python` par défaut du PATH de cette session pointe vers un venv sans rapport avec ce projet).
- `python manage.py makemigrations --check --dry-run` : signale une dérive sur `production` (`BreadTransfer.transfer_status`, `id` de `BreadTransferLine`/`ConsumableCount`), `clients` (contraintes `unique_together` de `SocialContribution`/`SocialDistribution`/`SocialDistributionLine`) et `treasury` (`DailySavings`/`JournalEntry`). **Cette dérive est pré-existante et sans rapport avec mon périmètre** : aucun de mes changements ne touche `models.py` dans ces trois apps (uniquement `views.py`/`urls.py`/tests). À signaler au coordinateur pour attribution (probablement laissé par un agent précédent ayant modifié ces modèles sans régénérer la migration, ou une migration de données qui modifie indirectement l'état de champs `id`/contraintes).

## Fichiers modifiés (hors tests et registre)

- `backend/core/views.py` (`SystemNotificationViewSet`, `ColisDistributionViewSet`)
- `backend/core/urls.py` (route `TokenRefreshView`)
- `backend/clients/views.py` (`ClientViewSet.perform_create`, `SocialContributionViewSet`, `SocialDistributionViewSet`, `SocialDistributionLineViewSet`)
- `backend/production/views.py` (`ConsumableMovementViewSet`, `BreadTransferViewSet`)
- `backend/treasury/views.py` (`CashbookEntryViewSet.permission_classes`)

## Tests modifiés/ajoutés

- `backend/core/tests/test_permissions.py` : décorateurs `@unittest.expectedFailure` retirés pour BUG-022 (7 tests), BUG-023 (3 tests), BUG-025 (1 test) ; `RefreshBlacklistTests` et `CashbookEntryIsolationTests` réécrits pour refléter le comportement corrigé (voir détail BUG-024/BUG-026 ci-dessus — prémisses des anciens tests incompatibles avec les corrections retenues, pas simplement un retrait de marqueur).
- `backend/production/tests/test_transfers.py` : décorateurs `@expectedFailure` retirés (2 tests, BUG-023).

## Non traité (hors périmètre, rappel)

- BUG-033 à BUG-037 (`treasury/views.py`, hors BUG-026) — laissés pour le prochain agent dev-backend séquencé par le coordinateur.
- BUG-017/018/021 (`clients/views.py`, hors BUG-025) — idem.
- BUG-038 à BUG-043 (`production/`, hors BUG-023) — idem.
- BUG-027 (frontend `Nodes.tsx`) déjà marqué `CORRIGÉ` par un autre agent avant cette session — non touché.

## Risques / points d'attention pour la suite

1. **BUG-044 (nouveau, frontend)** doit être traité avant ou en même temps que la vérification de BUG-026 par `testeur-permissions`, sinon la page Trésorerie affichera des erreurs 403 visibles pour tout GERANT/FACTURIER/LIVREUR qui l'ouvre.
2. La dérive de migrations détectée (`production`/`clients`/`treasury`) n'est pas de moi mais bloque un `makemigrations --check --dry-run` propre pour le prochain agent qui touchera ces modèles — à signaler au coordinateur pour investigation (probablement à régulariser par une migration dédiée, séparée de tout ticket fonctionnel).
3. Pour BUG-022, le choix de traiter `node_origin='CLOUD'` comme « visible de tous » sur `SystemNotification` est un choix raisonnable mais non explicitement demandé par le ticket — à confirmer par `testeur-permissions` lors de la vérification (alertes vraiment globales type « alerte blockchain » doivent rester visibles par tous les gérants, pas seulement HQ).
