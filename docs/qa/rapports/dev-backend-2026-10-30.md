# Rapport dev-backend — 2026-10-30

## Ticket traité

### BUG-067 (lié à BUG-062) — `sync_now` (commande manuelle) ne traitait pas un 503 comme « réessayer plus tard avec le même batch_id »
Statut : OUVERT → **CORRIGÉ**.

- Cause : `backend/sync/management/commands/sync_now.py::Command.handle` construisait un nouveau
  `batch_id` à chaque invocation et traitait tout `response.status_code >= 400` de façon identique
  (`CommandError`), sans distinguer un 503 transitoire (aucun `SyncBatchLog` persisté côté Cloud,
  lot intégralement rejouable, BUG-062) d'un 400/401/403 définitif.
- Correction : nouvelle fonction `_send_with_retry()` dans `sync_now.py`, utilisée pour le push et
  le pull, qui rejoue la MÊME requête (même payload fermé, donc même `batch_id`) uniquement sur un
  code transitoire (`TRANSIENT_STATUS_CODES = {503}`), avec backoff exponentiel plafonné
  (`--retry-backoff`, défaut 2 s, ×2 à chaque essai, plafond 30 s) et nombre borné de tentatives
  (`--max-retries`, défaut 5) avant abandon avec message clair. Les autres codes (400/401/403/500…)
  restent fatals immédiatement, sans aucune retentative — non-régression volontaire.
- `backend/sync/desktop_client.py` (boucle automatique du poste desktop, déjà conforme) importe
  désormais `TRANSIENT_STATUS_CODES` depuis `sync_now.py` au lieu de coder `503` en dur deux fois ;
  docstring mis à jour pour refléter que `sync_now.py` gère maintenant lui aussi BUG-067 (le module
  `desktop_client.py` reste nécessaire pour la persistance `sync_outbox.json` entre cycles de 30 s
  et la boucle de fond infinie, ce qu'un outil en ligne de commande ponctuel ne doit pas faire).
- Fichiers modifiés : `backend/sync/management/commands/sync_now.py`,
  `backend/sync/desktop_client.py`. Aucun autre module touché.
- Test de non-régression : `backend/sync/tests/test_sync_now_command.py` (nouveau, 4 tests —
  tous échouaient avant la correction, faute des options `--max-retries`/`--retry-backoff` et de la
  logique de retry) :
  1. 503 puis 200 → même `batch_id` sur les deux tentatives, succès final.
  2. 503 persistant → abandon après `max_retries` avec `CommandError` explicite, pull jamais tenté.
  3. 400 → fatal immédiatement, aucune retentative (non-régression).
  4. Push accepté puis 503 au pull → retenté puis abandon, message mentionnant le push déjà confirmé.
- Pas de migration (changement de commande de management pur). Pas d'impact sur un contrat d'API
  (aucune route HTTP modifiée) → pas de ticket lié ouvert pour dev-frontend.
- Impact sur BUG-072 : ce ticket (ouvert par `packaging-desktop`) décrivait exactement ce même
  défaut côté commande manuelle et recommandait littéralement cette correction. Une note a été
  ajoutée sur sa fiche indiquant qu'il est vraisemblablement désormais couvert, SANS le passer à
  `VÉRIFIÉ` (réservé au testeur d'origine/coordinateur, CLAUDE.md §7 règle 3).

## Vérifications de clôture
- `python manage.py test sync` → 28/28 OK.
- `python manage.py test` (suite complète) → **372/372 OK**, exit code 0. Aucun faux positif
  connu (BUG-017/057) observé lors de cette exécution ; sans rapport avec cette correction de toute
  façon (hors fichiers modifiés).
- `python manage.py makemigrations --check --dry-run` → « No changes detected ».
- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.
- `python manage.py check` → « System check identified no issues ».

## En attente / risques
- BUG-072 reste formellement `OUVERT` dans le registre (note ajoutée, pas de changement de statut
  par moi-même) — à faire passer à `VÉRIFIÉ` ou `REJETÉ` (doublon) par le testeur d'origine ou le
  coordinateur.
- Aucun autre ticket backend traité dans cette session (mission limitée à BUG-067 par le
  coordinateur, périmètre strict `backend/sync/`).
