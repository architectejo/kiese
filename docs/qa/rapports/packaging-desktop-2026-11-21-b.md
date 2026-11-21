# Packaging desktop, 2026-11-21 (lot B) : BUG-403 et BUG-404

## Changements
- `backend/desktop_server.py` : `backup_database` accepte `label`/`with_seconds`, écrit via fichiers temporaires + renommage atomique et nettoie ses résidus. Nouveaux : `validate_backup_file_name`, `restore_database`, `RestoreError`, modes CLI `backup` et `restore` (sortie JSON, sans Django ni secret).
- `desktop/src/backup.ts` : plus aucune lecture/écriture de la base côté Node ; appelle `kiese-server.exe backup|restore` via `execFile`. La liste et l'IPC de restauration n'acceptent que `kiese-*.sqlite3.gz`. Le backend est relancé même après un échec de restauration.
- `desktop/src/backupNames.ts` (nouveau) : `isValidBackupName`, `parseBackendResult` (fonctions pures).
- Tests : `backend/core/tests/test_bug403_404_backup_restore.py` (10 tests).

## Vérifié
- 10 nouveaux tests Python verts. Un run complet `manage.py test core` avait été lancé en arrière-plan (résultat communiqué séparément si disponible).
- CLI exécutée à la main hors Electron : `backup`, `restore` et refus de `../x.sqlite3.gz` (JSON correct).
- TypeScript : `tsc --strict` OK sur `backup.ts` et `backupNames.ts` avec des déclarations minimales (stubs electron/fs/path/child_process) ; logique de `isValidBackupName` exécutée sous Node (refus de `../`, `..\`, sous-dossier, hors préfixe).

## NON vérifié
- Aucun `npm ci`, aucun build Electron, aucun lancement : `desktop/` n'a pas été compilé avec les vrais types Node/Electron.
- Binaire PyInstaller non reconstruit : le fait que `kiese-server.exe backup|restore` fonctionne une fois gelé reste à confirmer (imports stdlib seulement).
- Comportement Windows réel : fichiers `-wal`/`-shm` verrouillés, antivirus, arrêt/redémarrage de Waitress pendant la restauration.
- BUG-405 (restriction de rôle de la route `/admin/backups`) non traité (frontend).

## Notes de conception
- La copie de sécurité s'appelle `kiese-avant-restauration-*.sqlite3.gz` (et non `avant-restauration-*` seul) afin de rester dans la liste blanche, d'être listée dans l'interface et soumise à la rotation de 30 jours.
- Les tickets passent à CORRIGÉ ; la vérification revient à testeur-installation.
