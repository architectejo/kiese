# Rapport — testeur-permissions — Vérification BUG-113 (2026-10-30)

## Mission

Vérifier, en tant qu'ouvreur du ticket, le correctif de dev-backend sur **BUG-113**
(fuite inter-nœuds en lecture sur `JournalEntryViewSet.suggested_ca`/`.monthly_report`,
et — affirmation de dev-backend à vérifier — sur `get_queryset()`), sans se fier au
rapport de dev-backend ni au code applicatif modifié.

## 1. Relecture du diff

`backend/treasury/views.py::JournalEntryViewSet`, 3 méthodes modifiées :

- `get_queryset()` (l. 698-725) : pour un non-HQ, tout `node` fourni en paramètre est
  désormais ignoré ; le queryset est forcé sur `user.node` (`qs.none()` si l'utilisateur
  n'a aucun nœud). Pour un HQ, `elif node_id: qs = qs.filter(node_id=node_id)` inchangé.
- `suggested_ca()` (l. 847-899) : même motif — non-HQ sans nœud → `403`; non-HQ avec nœud
  → `node_id = str(request.user.node_id)` imposé, `params.get('node')` ignoré; HQ →
  `params.get('node')` respecté.
- `monthly_report()` (l. 901-940) : motif identique.

`perform_create()` n'a pas été touché (déjà conforme avant le ticket : `node = user.node`
imposé pour un non-HQ, jamais `request.data.get('node')`).

Le motif appliqué est cohérent avec BUG-022/025/030/054/056 déjà présents dans le
registre (jamais de `node` choisi par un non-HQ, que ce soit en lecture ou en écriture).

## 2. Relecture des tests ajoutés

Dans `backend/core/tests/test_permissions.py::JournalSuggestedCaNodeIsolationTests` :

- `test_gerant_k1_cannot_list_journal_entries_of_another_node_via_forged_node_param` :
  couvre le point annexe (`get_queryset()`) — crée un `JournalEntry` pour K2, GERANT K1
  liste `/api/treasury/journal/?node=<K2>`, assertion `assertNotIn` sur l'ID de
  l'écriture K2 dans la réponse.
- `test_hq_can_still_read_suggested_ca_and_monthly_report_and_list_of_other_node` :
  couvre la non-régression HQ sur les **3** endpoints dans un seul test (Direction,
  `?node=<K2>`, vérifie que les données réelles de K2 sont bien renvoyées sur les 3).
- Les 2 tests originaux (`test_gerant_k1_cannot_read_suggested_ca_of_another_node_via_forged_node_param`,
  `..._monthly_report...`) ont perdu leur `@unittest.expectedFailure` et passent.

Couverture jugée suffisante : attaque + non-régression HQ couvertes sur les 3 endpoints
concernés.

## 3. Reproduction indépendante de l'attaque

Script temporaire `backend/core/tests/test_verif_bug113_manual.py` (créé puis **supprimé**
après usage — ne subsiste pas dans le dépôt), réutilisant uniquement les fixtures
`BaseNodeTestCase` (users/nodes), avec des assertions écrites indépendamment des tests de
dev-backend. 4 cas, tous `OK` :

- GERANT K1, `GET /api/treasury/journal/?node=<K2>` → 200, l'écriture K2 n'apparaît pas.
- GERANT K1, `GET /api/treasury/journal/suggested_ca/?node=<K2>&date=...` →
  `available=False` (pas de fuite de `CashClosure.total_entries` de K2 = 777 000 FC).
- GERANT K1, `GET /api/treasury/journal/monthly_report/?node=<K2>&month=...&year=...` →
  `total_entries="0"` (pas de fuite du total K2 = 123 456 FC).
- Direction (HQ), même 3 requêtes avec `?node=<K2>` → 200 avec les données réelles de K2
  sur les 3 endpoints (non-régression confirmée indépendamment).

## 4. Confirmation du périmètre élargi à `get_queryset()`

L'affirmation de dev-backend selon laquelle `get_queryset()` était vulnérable au même
défaut (alors que le périmètre initialement testé par testeur-permissions à l'ouverture
du ticket ne portait que sur `suggested_ca`/`monthly_report`) est **confirmée** par la
reproduction indépendante du point 3 : avant correctif, un `?node=<K2>` forgé par un
GERANT K1 passait silencieusement dans `get_queryset()` (`elif node_id: qs =
qs.filter(node_id=node_id)` sans aucun test de `can_access_all_nodes`), exactement la
même cause racine que les deux actions personnalisées (copier-coller du même motif aux
3 endroits du fichier). **L'élargissement du périmètre de la correction était donc
justifié et nécessaire** : s'en tenir au périmètre initial aurait laissé ouverte une
fuite inter-nœuds bloquante sur le même ViewSet.

## 5. Suite de tests

- `python manage.py test core treasury` → **156 tests, OK**, 0 échec, aucun
  `expectedFailure` restant.
- `python manage.py test` (suite complète) → **391 tests, OK**, 0 échec, aucun
  `expectedFailure` restant.

## 6. Intégrité

- `python manage.py makemigrations --check --dry-run` → `No changes detected`
  (correctif purement applicatif, cohérent — aucun changement de schéma attendu).
- `PRAGMA integrity_check` sur `backend/db.sqlite3` (lecture seule) → `ok`.

## 7. Conclusion

Correctif conforme sur les 3 endpoints de `JournalEntryViewSet`, aucune régression pour
les rôles HQ, périmètre élargi à `get_queryset()` vérifié et justifié. Aucune
modification de code applicatif n'a été apportée par ce testeur (règle CLAUDE.md §7).

**BUG-113 passé à `VÉRIFIÉ`** dans `docs/qa/REGISTRE_BUGS.md` (table récapitulative +
fiche détaillée, section « Vérification » ajoutée), avec mise à jour cohérente de la
référence dans la note de synthèse de la passe du 2026-10-30 (point 3).

## Fichiers concernés

- Lu (non modifié) : `D:\Projects\kiesse\backend\treasury\views.py`
- Lu (non modifié) : `D:\Projects\kiesse\backend\core\tests\test_permissions.py`
- Modifié : `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (statut BUG-113 → VÉRIFIÉ,
  section Vérification, note de synthèse mise à jour)
- Créé puis supprimé (vérification uniquement, ne subsiste pas) :
  `D:\Projects\kiesse\backend\core\tests\test_verif_bug113_manual.py`
