# Rapport dev-backend — BUG-082 (CORS desktop) — 2026-10-24

## Ticket traité

**BUG-082** — CORS backend ne couvre pas l'origine `null` (`file://`, frontend Electron) ni
`http://127.0.0.1:<port-dynamique>` / `http://localhost:<port-dynamique>` (port choisi à chaque
démarrage par `desktop/src/port.ts::findFreePort()`) — passé de `OUVERT` à `CORRIGÉ` dans
`docs/qa/REGISTRE_BUGS.md`. Je ne l'ai pas passé à `VÉRIFIÉ` (règle du projet) : c'est au
coordinateur ou au testeur d'origine de clore.

## Constat de départ

- `backend/kiese/settings.py` (cloud) : `CORS_ALLOWED_ORIGINS` est une liste statique
  (`http://localhost:5173`, `http://127.0.0.1:5173`, domaines `etskiese.com`), sans
  `CORS_ALLOWED_ORIGIN_REGEXES` ni `CORS_ALLOW_ALL_ORIGINS` — correctement restrictif, **non
  modifié** par cette correction.
- `backend/kiese/settings_desktop.py` contenait déjà, avant cette session,
  `CORS_ALLOW_ALL_ORIGINS = True` avec `CORS_ALLOWED_ORIGINS = []` — vérifié dans le code source de
  `django-cors-headers` (`corsheaders/middleware.py::add_response_headers`) que cela aurait
  effectivement laissé passer `null` et `http://127.0.0.1:<port>` (l'en-tête
  `Access-Control-Allow-Origin` reflète alors systématiquement l'origine de la requête quand
  `CORS_ALLOW_CREDENTIALS=True`), mais de façon **beaucoup trop permissive** : n'importe quelle
  origine externe aurait été acceptée, pas seulement `null`/`127.0.0.1`/`localhost` — contraire à la
  consigne de ne jamais élargir le CORS plus que nécessaire, même en mode desktop.

## Correction apportée

Fichier modifié : `backend/kiese/settings_desktop.py` (section CORS uniquement). **Aucune
modification de `backend/kiese/settings.py`** (module cloud).

Remplacement de `CORS_ALLOW_ALL_ORIGINS = True` par une liste blanche scoped :

```python
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = ['null']
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^http://127\.0\.0\.1:\d+$',
    r'^http://localhost:\d+$',
]
CORS_ALLOW_CREDENTIALS = True
```

- `'null'` dans `CORS_ALLOWED_ORIGINS` : `django-cors-headers` compare l'origine `null` par égalité
  stricte de chaîne (pas comme une URL) — c'est la seule façon de l'autoriser explicitement.
- Les deux regex ancrées (`^...$`) couvrent n'importe quel port dynamique sur `127.0.0.1`/`localhost`
  en HTTP, sans élargir à un domaine externe quelconque, un sous-domaine piégé
  (`127.0.0.1.evil.com`) ou un autre schéma (`https://`).
- Un commentaire détaillé dans le fichier explique pourquoi c'est sûr en mode desktop uniquement :
  Waitress n'écoute que sur `127.0.0.1`, jamais exposé au réseau de la boulangerie ni à Internet
  (DESKTOP.md §13) — seul un processus déjà exécuté sur le même poste peut présenter une telle
  origine à ce serveur.

### Credentials/cookies et origine `null`

Vérifié `frontend/src/api/client.ts` : le JWT est envoyé en en-tête `Authorization: Bearer <token>`
depuis `localStorage`, et aucun appel Axios ne positionne `withCredentials`. La limite connue de
certains navigateurs (refus d'envoyer des cookies vers/depuis une origine `null` même avec
`Access-Control-Allow-Credentials: true`) ne s'applique donc pas au flux d'authentification actuel.
`CORS_ALLOW_CREDENTIALS = True` est conservé pour cohérence avec le mode cloud mais n'est pas requis
par ce flux. Documenté en commentaire dans `settings_desktop.py` et dans la fiche BUG-082.

## Tests de non-régression

Nouveau fichier (le test n'existait pas avant ce ticket, pas de `@expectedFailure`) :
`backend/core/tests/test_desktop_cors.py`, 7 tests :

- `DesktopSettingsCorsConfigTests` : importe `kiese.settings_desktop` de façon isolée (variables
  d'environnement requises posées temporairement sans affecter les settings actifs du test runner,
  grâce au cache `sys.modules` sur `kiese.settings`) et vérifie :
  - `CORS_ALLOW_ALL_ORIGINS == False` ;
  - `'null' in CORS_ALLOWED_ORIGINS` ;
  - les regex matchent `http://127.0.0.1:<port>` / `http://localhost:<port>` pour plusieurs ports,
    et rejettent un schéma `https://`, un sous-domaine piégé, ou un domaine externe ;
  - `kiese.settings` (cloud) reste inchangé (pas de `null`, `CORS_ALLOW_ALL_ORIGINS` resté `False`,
    `CORS_ALLOWED_ORIGIN_REGEXES` resté vide).
- `DesktopCorsMiddlewareBehaviorTests` : reproduit les valeurs de `settings_desktop` via
  `@override_settings` sur les settings de test actifs et envoie de vraies requêtes `APIClient` vers
  `/api/schema/` (traverse la pile de middleware réelle, y compris `CorsMiddleware`) avec
  `HTTP_ORIGIN='null'`, puis `HTTP_ORIGIN='http://127.0.0.1:52341'` : confirme
  `Access-Control-Allow-Origin` reflété correctement et `Access-Control-Allow-Credentials: true` ;
  et qu'une origine non liée (`https://attacker.example`) reste rejetée (pas d'en-tête
  `Access-Control-Allow-Origin`).

Résultat : `python manage.py test core.tests.test_desktop_cors` → **7/7 OK**.

### Suite complète

- `python manage.py test core sync` → **75/75 OK**.
- `python manage.py test` (suite complète, 252 tests, ~15 min) → **249/252 OK, 3 échecs** :
  - `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario`
  - `treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`
  - `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests.test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db`

  **Ces 3 échecs sont pré-existants et sans rapport avec BUG-082** : vérifié en les relançant seuls
  (hors suite complète), ils échouent de façon identique et reproductible, avec le même symptôme
  racine `sqlite3.OperationalError: database table is locked` (concurrence multi-thread sur SQLite
  dans cet environnement de test Windows — limitation connue de SQLite sous charge concurrente, pas
  une régression de code). Ces tests sont dans `treasury` et `clients`, modules que je n'ai pas
  touchés (seul fichier modifié : `backend/kiese/settings_desktop.py` ; seul fichier ajouté :
  `backend/core/tests/test_desktop_cors.py`, qui ne lance aucun thread). Je ne les ai pas corrigés
  (hors périmètre BUG-082, et la règle du projet interdit les refactorisations hors ticket) — à
  signaler au coordinateur comme problème d'environnement de test distinct (table SQLite verrouillée
  sous forte concurrence sur cette machine), potentiellement déjà connu de
  `testeur-clients-commissions`/`testeur-tresorerie`.

- `python manage.py makemigrations --check --dry-run` : signale une dérive sur `production`,
  `clients`, `treasury` (champs `id`, contraintes `unique_together`) — **pré-existante, sans rapport
  avec ce ticket** : aucun modèle n'a été touché par cette correction (uniquement
  `settings_desktop.py`, un fichier de settings pur Python sans modèle, et un fichier de test). Non
  corrigée ici (hors périmètre BUG-082) ; signalée au coordinateur.

## Impact API / frontend

Aucun changement de contrat d'API. Impact limité à la configuration CORS du binaire desktop
packagé (`settings_desktop.py`) — invisible du frontend React, aucun ticket `dev-frontend` ouvert.

## Vérification réelle (point 5 de la mission)

Non exécutée avec un vrai `curl`/`requests` contre un serveur Waitress démarré localement : cela
aurait nécessité de lancer `desktop_server.py` avec des secrets desktop simulés
(`KIESE_SECRET_KEY`, etc.) et un dossier de données isolé, ou de modifier temporairement
`backend/.env`/`db.sqlite3` réels — interdit par la consigne (« ne jamais toucher à
`backend/db.sqlite3` réel »). Remplacé par le test d'intégration Django
`DesktopCorsMiddlewareBehaviorTests` (ci-dessus), qui fait traverser à une vraie requête HTTP
(`APIClient`) toute la pile de middleware Django, y compris `CorsMiddleware` — comportement
équivalent à une requête `curl -H "Origin: null"` réelle, sans dépendance à un serveur Waitress
démarré. Vérification manuelle complémentaire sur un vrai poste Windows avec build desktop complet
recommandée à `testeur-installation`/`testeur-matériel`.

## Fichiers modifiés / ajoutés

- `backend/kiese/settings_desktop.py` (modifié — section CORS).
- `backend/core/tests/test_desktop_cors.py` (nouveau).
- `docs/qa/REGISTRE_BUGS.md` (ticket BUG-082 : statut → CORRIGÉ, fiche détaillée complétée).

## Risques / suite à donner

- Les 3 échecs `database table is locked` (hors périmètre de ce ticket) méritent un ticket séparé
  pour le coordinateur ou un testeur — probablement lié à la configuration SQLite des tests sur cette
  machine (pas de `PRAGMA busy_timeout` ni de verrouillage adapté pour les tests de concurrence réels
  sous Windows).
- La dérive `makemigrations --check` sur `production`/`clients`/`treasury` est pré-existante et
  distincte de BUG-082 ; à traiter dans un ticket dédié si elle n'en a pas déjà un.
- Vérification manuelle réelle sur poste Windows avec l'app desktop packagée reste recommandée
  avant clôture définitive (`VÉRIFIÉ`) par testeur-installation/testeur-matériel.
