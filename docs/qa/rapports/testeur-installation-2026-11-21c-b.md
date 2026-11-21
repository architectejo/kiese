# Rapport testeur-installation, 2026-11-21c (dev B) : vérification BUG-403 à BUG-406

Tests : `backend/core/tests/test_verif_bug403_404_testeur_installation.py` (35 tests) + tests du développeur (`test_bug403_404_backup_restore`) : 2 échecs attendus, qui prouvent BUG-408 et BUG-409. Frontend : `npx tsc --noEmit` = 0 erreur, `npm run build` = OK.

| Ticket | Verdict | Reste à faire |
|---|---|---|
| BUG-403 | VÉRIFIÉ (logique Python) | Machine réelle : mode `backup` du `kiese-server.exe` PyInstaller, clic pendant des ventes (checklist §7) |
| BUG-404 | CORRIGÉ maintenu | Corriger BUG-408 ; machine réelle : arrêt/relance Waitress, `-wal` verrouillé, message sur `.gz` corrompu |
| BUG-405 | VÉRIFIÉ (relecture + tsc/build) | Essai manuel facturier / ADMIN sur `#/admin/backups` |
| BUG-406 | VÉRIFIÉ (relecture) | Poste 58 mm réel : réimpression depuis Dashboard |
| BUG-408 | OUVERT (Mineur) | `.gz` de 0 octet ou base non KIESE écrase la base courante (copie de sécurité faite) |
| BUG-409 | OUVERT (Mineur) | `$` accepte un LF final : utiliser `fullmatch` |

## Ce qui a tenu
- Sauvegarde WAL non checkpointé restaurée sur une autre base : 500 lignes identiques, integrity_check ok.
- Sauvegarde pendant qu'un thread écrit : 3 sauvegardes cohérentes, aucun fichier `.tmp`/`.part` résiduel.
- Restauration refusée (gz tronqué, non-gzip, non-SQLite, intégrité négative, introuvable) : SHA-256 de la base courante inchangé, pas de copie de sécurité parasite, pas de temporaire.
- Copie de sécurité `kiese-avant-restauration-*` : listée par la liste blanche, restaurable, contenu d'avant retrouvé ; `-wal` orphelin non rejoué.
- Idempotence (3 restaurations de suite), restauration sans base courante, rotation 30 jours (ne touche pas les fichiers non `kiese-*.gz`, la sauvegarde fraîche survit).
- 27 noms hostiles refusés (`../x`, `..\x`, `C:\x`, UNC, absolu, `/..`, unicode, nul, 5000 caractères, casse, ADS, espaces) ; messages en français sans fuite d'erreur technique.
- CLI `backup` / `restore` : JSON ASCII sur stdout, code 0/1, `--file` absent refusé.

## Relecture TypeScript (desktop/src)
- Aucune injection : `execFile` avec tableau d'arguments (pas de shell), nom validé deux fois (TS + Python), `timeout` 10 min, `maxBuffer` 1 Mo ; promesse toujours résolue ou rejetée (callback unique).
- Le backend est relancé après échec ; mais `await handle.stop()` est hors `try` (si `stop` lève, pas de relance) et si `restartBackend` lève, l'erreur masque l'échec d'origine et `backendHandle` reste périmé. Mineur, non ticketé.
- Pas de verrou contre deux restaurations/sauvegardes simultanées (double clic) : à vérifier que le bouton se désactive (BackupManager). Non ticketé.
- IPC sans authentification de l'appelant : acceptable tant que la fenêtre ne charge que le build local et que l'écran est réservé ADMIN/DIRECTION ; recommandation : contrôler `event.senderFrame.url` dans le handler. Le contrôle de rôle côté renderer n'est pas une barrière contre un XSS.
- Journalisation : le flux stdout du backend (accents cp1252) est mal décodé en UTF-8 côté Node ; le JSON est ASCII donc sans effet sur le résultat.

## Relecture frontend
- `App.tsx` : `isAllowed` ADMIN/DIRECTION ; `ProtectedRoute` laisse passer les superusers (cohérent avec le menu) ; rôle inconnu refusé ; facturier voit « Accès refusé ».
- `Administration.tsx` : double garde ; la page ne monte pas `BackupManager` sans droit.
- `ThermalReceipt.tsx` : prop explicite > `window.kiese?.printerWidthMm` > 80 ; hors Electron (`window.kiese` absent) retombe à 80. Rendu 58 mm à contrôler sur imprimante réelle.

## Observations
- Restaurer une sauvegarde de plus de 30 jours supprime ce fichier source par la rotation (sans conséquence sur les données).
- Sous Windows, un descripteur SQLite peut rester ouvert jusqu'au `gc` après un échec de `backup_database` sur un fichier non SQLite (`_checkpoint_wal` ne ferme pas la connexion dans le chemin d'erreur) ; mineur.
