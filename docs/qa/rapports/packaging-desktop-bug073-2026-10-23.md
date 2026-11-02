# Rapport — BUG-073 : message clair après échec de migration (desktop)

Agent : packaging-desktop · Date : 2026-10-23

## Décision client consignée

M. NDUNGA NSAYI PIERRE (ADG) a tranché : **restauration manuelle guidée**, pas de rollback
automatique. `electron-updater` n'installe que la version la plus récente par construction ; un
retour arrière automatique vers l'exécutable précédent dépasse le périmètre standard de l'outil et
n'a pas été demandé.

## Ce qui a été implémenté

### 1. `backend/desktop_server.py`

- Nouvelle constante `MIGRATION_FAILED_EXIT_CODE = 2`. `main()` sort désormais avec ce code
  **uniquement** quand `_apply_migrations()` échoue (les autres abandons au démarrage, ex.
  `KIESE_SECRET_KEY` absent, gardent le code 1 générique — pas de confusion possible côté
  Electron).
- `backup_database()` renvoie maintenant le chemin (`Path`) du fichier `.sqlite3.gz` créé (ou
  `None` si aucune base n'existait).
- Nouvelle fonction `_mark_pre_migration_backup()` : écrit le nom de la sauvegarde pré-migration
  dans `backups/.last_pre_migration_backup` (texte brut, un nom de fichier). Appelée uniquement
  dans la branche « migrations en attente » de `_apply_migrations` (pas pour la sauvegarde
  quotidienne ordinaire) — le marqueur ne désigne donc toujours que la sauvegarde prise juste
  avant un `migrate` qui a pu échouer.

### 2. `desktop/src/backend.ts`

- Export de `MIGRATION_FAILED_EXIT_CODE` (= 2, dupliqué côté TypeScript pour éviter une
  dépendance d'exécution au process Python pour cette seule constante) et d'une classe
  `MigrationFailedError`.
- `startBackend()` : le health-check (`waitForHealthCheck`, jusqu'à 60 s) est maintenant mis en
  compétition (`Promise.race`) avec la détection d'une sortie précoce du process (`child.once('exit', ...)`
  avant que le health-check ait réussi). Si le process sort avec le code 2 avant d'être prêt, la
  promesse est rejetée immédiatement avec `MigrationFailedError` — l'utilisateur n'attend plus 60 s
  pour un message d'erreur générique.

### 3. `desktop/src/main.ts`

- `readLastPreMigrationBackupName()` : lit le marqueur ci-dessus (best-effort, aucune exception
  propagée si absent — anciennes versions du backend ou premier démarrage sans base).
- `showMigrationFailureDialog()` : `dialog.showMessageBoxSync` (bloquant, type `error`) en
  français. Contenu : la mise à jour a échoué à cause d'une migration ; les données sont intactes ;
  nom exact de la sauvegarde pré-migration si identifiable ; marche à suivre en 4 étapes (menu
  Administration → Restaurer une sauvegarde → sélectionner la plus récente → confirmer puis
  contacter le support avant de retenter la mise à jour). Le dossier des sauvegardes s'ouvre
  ensuite automatiquement (`shell.openPath`).
- `quitAfterMigrationFailure()` : arrête le backend si besoin, affiche le dialogue, puis
  `app.quit()`. **Appelée depuis les 4 points où une tentative de démarrage du backend peut
  rencontrer ce cas** : `launchBackendAndMainWindow`, `launchBackendAfterFirstRun`,
  `handleBackendCrash` (y compris en interceptant directement `code === MIGRATION_FAILED_EXIT_CODE`,
  avant même la logique des 3 tentatives `MAX_RESTARTS`), et `restartBackendForRestore` (après une
  restauration manuelle qui redémarrerait quand même sur une migration en échec, cas limite).
- Aucune boucle de redémarrage automatique n'est déclenchée pour ce cas précis : `handleBackendCrash`
  court-circuite la logique de retry existante dès que le code 2 est détecté.

## Limite documentée (point 3 de la mission)

Le message invite à utiliser « menu Administration → Restaurer une sauvegarde ». Côté code,
`desktop/src/backup.ts` (gestionnaires IPC `kiese:backup:list` / `kiese:backup:restore`,
opérations fichier Node pures, indépendantes du backend Python) et `desktop/src/preload.ts`
(pont `window.kiese.backup.*`) sont fonctionnels et déjà enregistrés au démarrage de l'app
(`registerBackupHandlers`, appelé dans `bootstrap()` avant tout démarrage du backend). **Aucune
page frontend React ne les consomme encore** (`frontend/src/pages/` ne contient pas d'écran
Administration/Restauration — vérifié par recherche de `window.kiese`/`backup` dans
`frontend/src`). Cette page reste donc à construire par `dev-frontend` pour que la marche à suivre
du dialogue soit exécutable de bout en bout dans l'application ; en attendant, le dialogue ouvre
directement le dossier des sauvegardes dans l'explorateur de fichiers comme filet de sécurité.

Cette limite ne bloque pas la correction de BUG-073 au sens strict (détection du code de sortie,
message clair, pas de boucle de redémarrage, identification de la sauvegarde) mais elle est
nécessaire pour que l'utilisateur final puisse réellement « cliquer » sur Administration →
Restaurer comme décrit. Signalé ici plutôt que traité, car hors du périmètre confié
(« reste concentré sur ce point précis »).

## Vérifications effectuées

- `cd desktop && npm run typecheck` → OK, aucune erreur.
- `cd desktop && npm run build` → OK, aucune erreur.
- `python -I -m py_compile backend/desktop_server.py` → OK.
- Test fonctionnel isolé (sans toucher `backend/db.sqlite3` ni les migrations réelles) : script
  temporaire dans un dossier de données `tempfile.mkdtemp()`, avec une base SQLite jetable
  pré-créée et `django.core.management.call_command` monkeypatché pour lever une exception
  (simulant une migration cassée). Résultat : `sys.exit(2)` confirmé, et
  `backups/.last_pre_migration_backup` contient bien le nom d'un fichier `.sqlite3.gz` existant
  dans le même dossier. Script et dossier temporaire supprimés après exécution — aucune trace dans
  le dépôt.

## Fichiers modifiés

- `backend/desktop_server.py`
- `desktop/src/backend.ts`
- `desktop/src/main.ts`
- `docs/qa/REGISTRE_BUGS.md` (BUG-073 → CORRIGÉ)
