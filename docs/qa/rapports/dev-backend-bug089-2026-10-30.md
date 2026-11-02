# Rapport dev-backend — BUG-089 (2026-10-30)

## Ticket traité

**BUG-089** (Majeur, Clients) — `ClientViewSet` (`IsGerant`) refusait (403) la création de client à
un FACTURIER, cassant silencieusement le flux « Client Occasionnel » / « Vente Directe » de
`Clients.tsx` pour ce rôle.

### Décision client

M. NDUNGA NSAYI PIERRE a tranché explicitement (relayée par le coordinateur) : le FACTURIER **doit**
pouvoir créer un client occasionnel pour une vente directe au comptant. Assouplissement **ciblé**
sur l'action `create` uniquement — pas une ouverture générale des droits Clients à FACTURIER.
Décision consignée dans la fiche BUG-089 de `docs/qa/REGISTRE_BUGS.md`.

### Analyse

- `backend/clients/views.py::ClientViewSet.get_permissions()` ne distinguait pas `create` des autres
  actions d'écriture : tout hors `list`/`retrieve`/`import_excel`/`bulk_move`/`bulk_delete` tombait
  sous `[IsGerant()]`.
- Pattern déjà établi ailleurs dans le projet pour un besoin identique :
  `sales/views.py::InvoiceViewSet.get_permissions()` distingue `create` (→ `IsFacturier()`) du reste
  (→ `IsGerant()`), car un FACTURIER doit pouvoir créer une facture. Repris à l'identique ici.
- `ClientViewSet.perform_create` forçait déjà `node = user.node` pour tout utilisateur non-HQ
  (`can_access_all_nodes` faux, ce qui inclut FACTURIER), motif BUG-025/BUG-030/BUG-056 — aucune
  modification nécessaire : un FACTURIER ne peut pas rattacher le client créé à une autre boulangerie
  même en forgeant `node` dans le payload.

### Correction

- `backend/clients/views.py` : `ClientViewSet.get_permissions()` — ajout `if self.action == 'create':
  return [IsFacturier()]` avant le `return [IsGerant()]` par défaut. Toutes les autres actions
  d'écriture (`update`, `partial_update`, `destroy`, `recalculate_category`, `import_excel`,
  `bulk_move`, `bulk_delete`) restent réservées GERANT+/HQ.
- `backend/clients/tests/test_api.py` : nouvelle classe `FacturierCanCreateClientTests` (6 tests,
  sans `@expectedFailure`, le test n'existait pas avant ce ticket) :
  - FACTURIER peut créer un client (201).
  - Le client créé est forcé au nœud du FACTURIER même si un autre `node` est forgé dans le payload.
  - FACTURIER ne peut toujours pas `update`/`destroy`/`bulk_move` un client (403, reste GERANT+).
  - Non-régression : GERANT toujours autorisé à créer ; LIVREUR (non concerné par la décision
    client) toujours exclu de `create`.

### Tests

- `python manage.py test clients core` → **105 tests, 1 échec** :
  `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests::
  test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db` — flakiness SQLite déjà connue
  et documentée sous BUG-017 (« database table is locked »), sans rapport avec BUG-089. Tous les
  nouveaux tests BUG-089 passent, ainsi que l'ensemble des tests existants (permissions, recherche
  cross-node, photo, plafond crédit, etc.).
- `python manage.py makemigrations --check --dry-run` : signale uniquement la dérive préexistante
  déjà documentée sous **BUG-057** (production/clients/treasury — `AlterField id`,
  `unique_together`). Aucune migration requise pour ce ticket (changement de permissions pur, aucune
  modification de schéma).
- `PRAGMA integrity_check` sur la vraie base `backend/db.sqlite3` → `ok`. Base réelle non touchée par
  ce ticket (aucune migration, aucune commande `shell` exécutée sur les données réelles).

### Impact contrat API

Aucun changement de contrat de requête/réponse. `POST /api/clients/clients/` passe de `403` à `201`
pour un FACTURIER — c'est la correction elle-même, pas une rupture de contrat pour les rôles déjà
autorisés (GERANT+). **Aucun ticket `dev-frontend` ouvert** : le bouton « Vente Directe » de
`Clients.tsx` existait déjà sans garde de rôle côté UI et fonctionnera désormais pour FACTURIER sans
modification frontend nécessaire.

### Statut du ticket

BUG-089 passé à **CORRIGÉ** dans `docs/qa/REGISTRE_BUGS.md` (fiche détaillée avec décision client,
cause, fichiers modifiés, tests). Non passé à VÉRIFIÉ (réservé au testeur d'origine ou au
coordinateur, règle §7 de CLAUDE.md).

## Tickets en attente / non traités dans cette session

Aucun autre ticket backend ne m'a été confié dans cette session — seul BUG-089 était dans le
périmètre demandé.

## Risques / points d'attention signalés au coordinateur et au testeur

- **Risque résiduel UI** (noté dans la fiche BUG-089, à vérifier par le testeur en conditions
  réelles) : `Clients.tsx` pourrait exposer d'autres actions (modifier le plafond crédit, supprimer,
  déplacer un client entre boulangeries) sans garde de rôle visible pour FACTURIER dans l'interface.
  Le backend les bloque bien (403), mais une garde UI manquante resterait un bug frontend distinct
  (échec silencieux côté composant), à documenter séparément si observé — même nature que la
  description initiale de BUG-089 mais sur un périmètre d'action différent.
- BUG-057 (dérive de migrations) reste **OUVERT**, non traité ici (hors périmètre de ce ticket,
  changement de permissions pur sans impact de schéma).
- BUG-017 (flakiness SQLite concurrency) reste **OUVERT**/connu, redécouvert sans surprise lors de la
  suite complète — aucune action requise ici.

## Fichiers modifiés

- `d:\Projects\kiesse\backend\clients\views.py`
- `d:\Projects\kiesse\backend\clients\tests\test_api.py`
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md`
