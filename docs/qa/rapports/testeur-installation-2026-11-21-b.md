# Rapport testeur-installation, 2026-11-21 (ronde B)

Périmètre : tickets desktop CORRIGÉ BUG-071, 073, 074, 075, 076, 077, 081, 082. Contraintes : pas d'installeur, PyInstaller, electron-builder ni Electron (disque 2,2 Go libres, pas d'imprimante, pas de machine vierge).

## Vérifications effectuées
- (a) Relecture critique : `desktop/src/{backend,backup,printing,preload,main}.ts`, `frontend/vite.config.ts`, `kiese/settings.py`, `settings_desktop.py`, `desktop_server.py`, `ThermalReceipt.tsx`, `BackupManager.tsx`, `App.tsx`, `Sales/Clients/Dashboard.tsx`.
- (b) Tests : `backend/core/tests/test_verif_desktop_testeur_installation.py`, 14 tests, OK (CORS réel via middleware, faux `.env` hostile, code de sortie 2 de `desktop_server.main()`, sauvegarde pré-migration + marqueur). Le `manage.py test core` complet a été lancé en arrière-plan (long) ; voir ligne « suite complète » ci-dessous.
- (c) `npx tsc --noEmit` OK, `npm run build` OK. `dist/index.html` : `./favicon.svg`, `./assets/polyfills-legacy-*.js`, `./assets/index-legacy-*.js` ; ni `type="module"`, ni `crossorigin`, ni `/assets` absolu dans tout `dist/`. Le CSS est embarqué dans le bundle JS (aucun .css séparé).
- (d) `desktop/node_modules` absent ; `npm ci` (electron, electron-builder) non léger pour 2,2 Go : non installé, `tsc` desktop non exécuté.

## Verdicts
| Ticket | Verdict | Justification / reste à faire |
|---|---|---|
| BUG-071 | VÉRIFIÉ | Faux `.env` (DB_NAME vide, clé piégée, DEBUG=True) : DB_NAME, SECRET_KEY, DEBUG du poste conservés ; `override=False`. |
| BUG-082 | VÉRIFIÉ | `null`, 127.0.0.1/localhost ports 1024-65535, préflight avec Authorization acceptés ; origines étrangères/piégées refusées ; pas de wildcard ; CORS cloud sans `null`. |
| BUG-073 | CORRIGÉ (partiel) | Backend : code 2 + log + sauvegarde/marqueur vérifiés ; code aligné avec `backend.ts`. Reste : boîte de dialogue Electron (`showMigrationFailureDialog`), absence de boucle de redémarrage, sur machine réelle (checklist : mise à jour avec migration volontairement cassée). |
| BUG-074 | CORRIGÉ (bloqué par nouveaux tickets) | Écran présent, route `/admin/backups`. Défauts : BUG-403 (sauvegarde sans WAL), BUG-404 (restauration destructive), BUG-405 (route sans garde de rôle). À contrôler sur poste : restauration d'une vraie sauvegarde, données identiques. |
| BUG-075 | CORRIGÉ (partiel) | Le code appelle `window.kiese.printReceipt` avec repli `window.print()` ; `printing.ts` cohérent (silent, deviceName, pageSize). Reste : impression réelle sur imprimante thermique. |
| BUG-076 | CORRIGÉ (partiel) | Largeur dynamique (`@media print`, `buildPrintableHtml`, échelle 0,82 en 58 mm). Reste : rendu physique 58 mm (testeur-materiel). |
| BUG-077 | CORRIGÉ (partiel) | `printerWidthMm` exposé via `get-boot-info` -> preload -> `kiese.d.ts` ; branché sur Sales et Clients, mais pas sur Dashboard : BUG-406. Reste : `tsc` desktop et valeur réellement lue sur un poste configuré en 58 mm. |
| BUG-081 | CORRIGÉ (partiel) | Chemins relatifs, bundle classique SystemJS sans module ni crossorigin, HashRouter en `file:`. Aucun contrôle de rendu sans Electron. Reste : ouverture de l'application installée (page non blanche, login, rechargement). |

## Nouveaux tickets
- BUG-403 (Majeur) : sauvegarde manuelle copie le .sqlite3 sans le WAL.
- BUG-404 (Majeur) : restauration supprime la base avant de valider le .gz ; pas de handler `gunzip` ; nom de fichier non assaini.
- BUG-405 (Majeur) : `/admin/backups` ouvert à tout utilisateur connecté.
- BUG-406 (Majeur) : réimpression Dashboard à 80 mm quel que soit le poste.
Mineurs non ticketés : commentaire périmé « override=True » dans `settings_desktop.py` ; commentaire périmé « n'expose PAS la valeur » dans `ThermalReceipt.tsx`.

## À faire sur machine réelle (procédure : `docs/qa/CHECKLIST_INSTALLATION.md`)
Installation sur Windows vierge non-admin ; assistant ; ouverture non blanche ; connexion ; facture ; impression silencieuse 58 et 80 mm (dont réimpression Dashboard) ; mise à jour avec migration cassée (dialogue + restauration guidée) ; sauvegarde manuelle puis restauration en vérifiant que les dernières écritures sont présentes (BUG-403) ; accès direct à `#/admin/backups` avec un compte facturier (BUG-405).
