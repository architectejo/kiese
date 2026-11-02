# Rapport de session — dev-backend, 2026-10-30 (BUG-112)

## Ticket traité

**BUG-112** — `database table is locked` sous forte concurrence réelle de création de clients
(SQLite). Gravité Majeur, module Clients, composant backend.

Statut final : **CORRIGÉ** (laissé ainsi conformément à CLAUDE.md §7 règle 3 : seul le testeur
d'origine, `testeur-clients-commissions`, ou le coordinateur peut passer ce ticket à `VÉRIFIÉ`).

Fiche détaillée complète ajoutée en fin de `docs/qa/REGISTRE_BUGS.md` (section
`### BUG-112 — ...`), ligne de synthèse du tableau de suivi (ligne ~123) mise à jour
(`OUVERT` → `CORRIGÉ`, `Assigné à` → `dev-backend`).

## Démarche

1. **Reproduction en isolation** (avant toute correction) : lancement isolé, 3 fois de suite, de
   `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests::test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db`
   avec `backend/.venv/Scripts/python.exe manage.py test ...` :
   - Run 1 : 0/16 créations réussies (16 `OperationalError: database table is locked`).
   - Run 2 : 2/16 réussies.
   - Run 3 : 2/16 réussies.
   - Confirmé : défaut sévère et reproductible, pas un artefact de contention multi-agents (aucun
     autre process actif pendant la reproduction).

2. **Confirmation des deux causes probables** mentionnées dans la mission :
   - `backend/clients/models.py::Client.save()` ne retentait que sur `IntegrityError`, jamais sur
     `OperationalError` — confirmé par lecture du code (avant correction, l.138-156).
   - `backend/kiese/settings.py::DATABASES['default']` n'avait aucun `OPTIONS` (ni `timeout`, ni
     mode WAL) — confirmé par lecture (avant correction, ~l.112-126). Par contraste,
     `backend/kiese/settings_desktop.py` avait déjà exactement ce correctif (mode WAL via
     `connection_created`, `OPTIONS['timeout']: 20`), ce qui a servi de modèle pour aligner le mode
     cloud/dev.

3. **Correction** (2 fichiers, aucune migration nécessaire) :
   - `backend/kiese/settings.py` : ajout de `OPTIONS = {'timeout': 30}` et activation du mode WAL
     SQLite (`PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=30000`) via le signal
     `django.db.backends.signals.connection_created`, **uniquement si** le moteur est
     `django.db.backends.sqlite3` (aucun effet sur une configuration PostgreSQL de production via
     `DB_ENGINE`).
   - `backend/clients/models.py` : la boucle de retry de `Client.save()` (toujours
     `_CODE_GENERATION_MAX_RETRIES = 10`) capture désormais aussi `OperationalError` dont le
     message contient `"locked"` (insensible à la casse), avec un court backoff aléatoire
     (`random.uniform(0.01, 0.05)` s), même style que `treasury/views.py::append_cashbook_entry`
     (BUG-002). Toute autre `OperationalError` (ex. erreur de schéma réelle) continue d'être
     relevée immédiatement — pas de `except Exception` large qui masquerait un vrai problème.
   - Aucun affaiblissement du contrôle d'unicité : `select_for_update()` +
     `transaction.atomic()` sur `ClientCodeSequence`, et la boucle de vérification
     `Client.objects.filter(code=code).exists()` restent strictement identiques.

4. **Vérification du correctif** :
   - Test ciblé relancé isolément 5 fois après correction : **5/5 OK** (0/5 avant aurait réussi au
     seuil exigé par l'assertion). Taux de réussite des créations concurrentes individuelles :
     passé d'environ 15 % (2,4/16 en moyenne) à 100 % (16/16 à chaque run observé).
   - `backend/.venv/Scripts/python.exe manage.py test` (suite complète) : **377 tests, OK** (exit
     code 0, aucun échec, aucune erreur).
   - `backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → `No changes
     detected` (attendu : correctif purement Python/config, aucun changement de schéma).
   - `PRAGMA integrity_check` sur `backend/db.sqlite3` → `[('ok',)]`.
   - `backend/kiese/settings_desktop.py` relu et **non modifié** : le mode WAL y était déjà actif
     indépendamment ; aucune incohérence introduite (double connexion du même type de signal au
     pire, PRAGMA idempotents, sans effet nuisible).

5. **Impact API** : aucun. Pas de changement de champ, de format ou de code HTTP. Aucun ticket
   `dev-frontend` à ouvrir pour ce correctif.

## Fichiers modifiés

- `D:\Projects\kiesse\backend\kiese\settings.py`
- `D:\Projects\kiesse\backend\clients\models.py`
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (mise à jour ligne de synthèse + fiche détaillée
  BUG-112 ajoutée)

## Tickets en attente

Aucun autre ticket backend n'a été traité dans cette session (mission limitée à BUG-112 par le
coordinateur).

## Risques / observations pour le coordinateur

- Pendant la suite complète (`manage.py test`), un log (pas un échec de test) est apparu :
  `NodeAuthToken.authenticate() : échec de la lecture du jeton après 150 tentatives : database
  table is locked` — émis par `sync/authentication.py::NodeTokenAuthentication` (module
  **sync**, hors périmètre de ce ticket et non modifié par cette session). La suite reste `OK`
  (377/377, exit 0), donc ce n'est pas un échec actuel, mais le message suggère que ce module a
  son propre mécanisme de retry sous verrouillage SQLite, déjà partiellement éprouvé (150
  tentatives) mais visiblement parfois encore insuffisant sous forte charge de tests concurrents.
  Signalé ici à titre préventif ; je n'ai pas ouvert de ticket séparé sans consigne explicite du
  coordinateur, mais cela pourrait valoir une vérification ciblée de `sync/authentication.py` si
  un flakiness apparaît un jour sur ce module (le correctif WAL global de `kiese/settings.py`
  devrait d'ailleurs déjà réduire sensiblement ce risque, puisqu'il s'applique à toute la base
  pour toute connexion, pas seulement à `clients`).
- Le ticket reste à `CORRIGÉ`, pas `VÉRIFIÉ` — c'est à `testeur-clients-commissions` ou au
  coordinateur de faire la vérification indépendante (CLAUDE.md §7 règle 3).
