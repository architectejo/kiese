# Rapport testeur-permissions — 2026-10-30 (post-chantier remarque.md + backlog mineur)

## Périmètre

Relecture RBAC / isolation par nœud des endpoints et champs ajoutés depuis la dernière passe
complète de `testeur-permissions` :

1. `POST /api/sales/invoices/{id}/adjust/` (BUG-097).
2. `POST /api/production/sessions/{id}/close/` (BUG-093/108).
3. `GET /api/treasury/journal/suggested_ca/` (BUG-091).
4. Champ `Invoice.commission_exempt` (BUG-052/097).
5. Suite complète `backend/core/tests/test_permissions.py` + `test_permissions_verif_2026_10_22.py`.
6. Impact RBAC du correctif BUG-112 (mode WAL + retry `OperationalError` SQLite).

Règle respectée : aucune modification du code applicatif (`backend/sales`, `backend/production`,
`backend/treasury`, `backend/clients`, `backend/kiese/settings.py`) — uniquement lecture, tests et
registre.

## Résultat détaillé

### 1. `InvoiceViewSet.adjust()` (BUG-097) — Conforme

- Permission : `@action(detail=True, methods=['post'], permission_classes=[IsGerant])`, et
  `InvoiceViewSet.get_permissions()` respecte bien cette déclaration explicite par action (motif
  BUG-031, commenté en détail dans le code). GERANT, COMPTABLE, DIRECTION, ADMIN autorisés ;
  FACTURIER et LIVREUR → 403.
- Isolation par nœud : `self.get_object()` résout via `InvoiceViewSet.get_queryset()`
  (`backend/sales/views.py` l.204-209), déjà filtré sur `node=user.node` pour tout utilisateur
  `not user.can_access_all_nodes`. Un GERANT d'un autre nœud ne trouve donc jamais l'objet et
  reçoit 403/404 — jamais d'ajustement cross-nœud possible.
- Tests ajoutés : `core/tests/test_permissions.py::InvoiceAdjustPermissionTests` (4 tests, tous
  verts) : FACTURIER → 403, LIVREUR → 403, GERANT d'un autre nœud → 403/404, GERANT du même nœud
  → 201.

### 2. `ProductionSessionViewSet.close()` (BUG-093/108) — Conforme

- Permission : aucun `permission_classes` dédié sur l'`@action` → retombe sur
  `ProductionSessionViewSet.get_permissions()` = `IsGerant()` (toute action hors
  `list`/`retrieve`). FACTURIER/LIVREUR → 403.
- Isolation par nœud : même mécanisme (`get_object()` via `get_queryset()` filtré sur
  `user.node`). Vérifié en prime que `_build_reconciliation_querysets` (partagée avec
  `reconciliation()` et appelée par `close()` avec le `node_id` de l'objet déjà résolu) ne retombe
  sur un `node_id` explicite venant des paramètres que pour un utilisateur HQ
  (`can_access_all_nodes`) — comportement correct, contrairement au point 3 ci-dessous.
- Tests ajoutés : `ProductionSessionClosePermissionTests` (4 tests, tous verts) : FACTURIER → 403,
  LIVREUR → 403, GERANT d'un autre nœud → 403/404 (`is_closed` reste `False`), GERANT du même nœud
  → 200.

### 3. `JournalEntryViewSet.suggested_ca` (BUG-091) — **NON CONFORME, ticket BUG-113 ouvert (Bloquant)**

Fuite inter-nœuds en lecture confirmée par test automatisé (reproduction effective, pas seulement
lecture de code) : un GERANT K1 forge `?node=<K2>` sur `GET /api/treasury/journal/suggested_ca/`
et reçoit en clair `total_entries` (recettes cash réelles) de K2
(`{"available": true, "amount": "777000.00", ...}`). Même défaut constaté au passage sur
`monthly_report()` du même fichier (expose `total_entries`/`total_exits`/`final_balance` mensuels
de n'importe quel nœud). Cause : ces deux actions acceptent `node_id` du paramètre de requête sans
jamais vérifier `request.user.can_access_all_nodes` — contrairement au motif déjà appliqué sur de
nombreux autres endpoints après BUG-022/025/030/054/056.

- Ticket détaillé : `docs/qa/REGISTRE_BUGS.md` → **BUG-113** (reproduction, cause, correctif
  attendu, fichiers concernés).
- Tests de preuve : `core/tests/test_permissions.py::JournalSuggestedCaNodeIsolationTests`
  (2 tests, `@unittest.expectedFailure` référençant BUG-113, conformément à la règle « tests
  `@expectedFailure` avec référence tant que non corrigé »).
- **Je n'ai pas corrigé ce code** (hors mandat, CLAUDE.md §7 règle 2) — ticket transmis à
  dev-backend.

### 4. `Invoice.commission_exempt` — Conforme, aucune nouvelle faille

`InvoiceViewSet.get_permissions()` retombe sur `IsGerant()` pour `update`/`partial_update` (toute
action hors `create`/`list`/`retrieve`/`adjust`). Un FACTURIER ne peut donc jamais `PATCH` une
facture existante pour en modifier `commission_exempt` (ou tout autre champ sensible) : testé
explicitement, 403 et valeur inchangée en base. Un GERANT+ peut le faire (200), comportement
attendu et symétrique aux autres champs sensibles déjà protégés (`is_soldee`, `commission_rate`).

- Tests ajoutés : `InvoiceCommissionExemptFieldTests` (2 tests, tous verts).

### 5. Suite complète de tests de permissions — 0 régression

- `manage.py test core.tests.test_permissions core.tests.test_permissions_verif_2026_10_22` :
  **66 tests, `OK (expected failures=2)`** — les 2 `expectedFailure` sont les nouvelles preuves de
  BUG-113 ; les 64 autres scénarios déjà en place (RBAC des 7 profils, isolation inter-nœuds
  transversale sur tous les modules, attaques d'élévation de rôle/`credit_limit`/logs/`Config`/
  prix, authentification JWT/refresh/blacklist/throttle) restent tous verts.
- `manage.py test sales production treasury core` (suite complète des 4 apps touchées par le
  chantier) : **269 tests, `OK (expected failures=2)`** — mêmes 2 `expectedFailure` BUG-113,
  aucune autre régression. (Durée ~41 min dans cet environnement — SQLite en base de test
  mémoire, pas de parallélisation ; sans rapport avec le correctif BUG-112, voir point 6).

### 6. Impact RBAC du correctif BUG-112 (mode WAL + retry SQLite) — Confirmé sans impact

Relecture complète des deux fichiers modifiés par ce correctif :
- `backend/kiese/settings.py` : ajout de `DATABASES['default']['OPTIONS']['timeout']` et de
  PRAGMA (`journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=30000`) via le signal
  `connection_created`, strictement limité au backend sqlite3. Aucune classe de permission, aucun
  middleware d'authentification, aucun réglage CORS/CSRF touché.
- `backend/clients/models.py::Client.save()` : capture supplémentaire d'`OperationalError`
  contenant « locked » (en plus de l'`IntegrityError` déjà gérée), avec un court backoff aléatoire
  avant nouvelle tentative de génération du code client. Ne touche à aucun contrôle de rôle, de
  nœud ou de champ exposé en écriture — uniquement à la robustesse de la boucle de génération de
  code sous contention.

**Confirmation explicite demandée par le coordinateur** : ce correctif est purement technique
(robustesse de connexion DB + retry applicatif), **aucun impact sur le RBAC, aucune nouvelle fuite
ou contournement de permission introduit**. Confirmé par relecture directe du diff décrit dans la
fiche BUG-112 du registre (déjà vérifiée indépendamment par un autre agent) et par la suite de
tests complète relancée au point 5 ci-dessus (0 régression sur les tests de permissions/isolation).

## Ticket ouvert

**BUG-113** (Bloquant, OUVERT, assigné à dev-backend) — `JournalEntryViewSet.suggested_ca` et
`.monthly_report` exposent en lecture les données financières (`CashClosure.total_entries`,
totaux mensuels du Journal de Caisse) d'un nœud quelconque à tout utilisateur authentifié qui
forge `?node=<autre nœud>`, sans jamais vérifier `request.user.can_access_all_nodes`. Détail
complet (reproduction, cause, correctif attendu, point annexe sur `get_queryset()` du même
ViewSet à vérifier dans le même lot) dans `docs/qa/REGISTRE_BUGS.md` sous la fiche BUG-113.

## Fichiers modifiés par ce testeur

- `backend/core/tests/test_permissions.py` — ajout de 4 classes de tests (15 tests) :
  `InvoiceAdjustPermissionTests`, `InvoiceCommissionExemptFieldTests`,
  `ProductionSessionClosePermissionTests`, `JournalSuggestedCaNodeIsolationTests` (2 tests
  `@expectedFailure` référençant BUG-113).
- `docs/qa/REGISTRE_BUGS.md` — nouvelle ligne de synthèse BUG-113 dans le tableau de suivi, fiche
  détaillée BUG-113, et note de synthèse de cette passe (« Note de synthèse — Passe
  testeur-permissions 2026-10-30 (post-chantier remarque.md + backlog mineur) »).

Aucun fichier applicatif (`backend/sales`, `backend/production`, `backend/treasury`,
`backend/clients`, `backend/kiese/settings.py`, `backend/core/permissions.py`, etc.) n'a été
modifié par ce testeur, conformément à CLAUDE.md §7 règle 2.

## Statut de fin de mission

- 5 points sur 6 confirmés conformes (adjust, close, commission_exempt, isolation transversale
  par les tests existants, correctif BUG-112 sans impact RBAC).
- 1 point non conforme, ticket BUG-113 ouvert avec reproduction automatisée et tests
  `@expectedFailure` en place, transmis à dev-backend — pas corrigé par ce testeur.
- `python manage.py test` relancé sur les 4 apps concernées (`sales production treasury core`) :
  269 tests, `OK (expected failures=2)`, 0 régression.
