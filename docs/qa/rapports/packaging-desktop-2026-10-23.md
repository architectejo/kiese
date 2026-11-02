# Rapport — packaging-desktop — 2026-10-23

Phase 5 (Desktop), étapes D1 à D5 et D7 de `docs/architecture/DESKTOP.md` §15. Conçu en tenant
compte de BUG-067 (traitement du 503 transitoire par le futur client de synchronisation desktop,
`docs/qa/REGISTRE_BUGS.md`).

## 1. Ce qui a été livré

### 1.1 Backend Django en mode desktop

- `backend/desktop_server.py` — point d'entrée appelé par Electron
  (`kiese-server.exe --port <port> --data-dir "%APPDATA%\KIESE"`) :
  - pose les variables d'environnement attendues par `kiese.settings`/`kiese.settings_desktop`
    **avant** `django.setup()` (`KIESE_SECRET_KEY`, `DB_NAME`, `DJANGO_ALLOWED_HOSTS`, etc.) ;
  - sauvegarde la base (API `sqlite3.Connection.backup()`, compressée, rotation 30 jours) avant
    toute migration en attente, ou une fois par jour sinon ;
  - applique les migrations, active le mode WAL (`journal_mode=WAL`, `synchronous=NORMAL`,
    `busy_timeout=5000`) ;
  - démarre le service de synchronisation en tâche de fond (best-effort, ne bloque jamais le
    démarrage de Waitress) ;
  - démarre Waitress (`threads=8`) ;
  - supporte aussi un mode `kiese-server.exe manage --data-dir <dir> <commande>` pour exécuter une
    commande `manage.py` ponctuelle (utilisé pour créer le compte administrateur local pendant
    l'assistant de première installation) sans démarrer le serveur.
- `backend/kiese/settings_desktop.py` — réglages spécifiques au poste : `DEBUG=False`,
  `ALLOWED_HOSTS=['127.0.0.1','localhost']`, `MEDIA_ROOT`/`STATIC_ROOT` sous le dossier de
  données/bundle, désactivation des réglages HTTPS forcés (inutiles en boucle locale),
  `CORS_ALLOW_ALL_ORIGINS=True` (justifié : le backend n'écoute que sur 127.0.0.1, jamais exposé
  au réseau de la boulangerie), journalisation vers `logs/backend.log` (rotation 10×5 Mo), mode
  WAL appliqué aussi via le signal `connection_created`.
  **Point important découvert et corrigé en cours de route (BUG-071, voir §3)** : `SECRET_KEY` et
  `DATABASES` sont **réaffirmés explicitement** après l'import de `kiese.settings`, parce que
  `load_dotenv(..., override=True)` dans `kiese/settings.py` écraserait sinon silencieusement les
  valeurs posées par `desktop_server.py` si un fichier `.env` se retrouvait dans le paquet.
- `backend/core/management/commands/ensure_local_admin.py` — crée/mets à jour de façon idempotente
  le compte administrateur local de secours (DESKTOP.md §7 étape 5), mot de passe transmis
  uniquement par variable d'environnement (`KIESE_LOCAL_ADMIN_PASSWORD`), jamais en argument CLI.

### 1.2 Client de synchronisation embarqué (tient compte de BUG-067)

- `backend/sync/desktop_client.py` (nouveau module, **n'édite aucun fichier déjà livré par
  `architecte-sync`**, les appelle) : boucle de fond (toutes les 30 s ± aléa) exécutée dans un
  thread démon par `desktop_server.py`. Réutilise
  `sync.management.commands.sync_now.{build_outbound_payload, apply_push_response,
  apply_pull_response}` et ajoute deux garanties absentes de la commande manuelle :
  1. **503 = « réessayer plus tard avec le même `batch_id` »**, jamais une erreur définitive —
     conforme à BUG-067. 401/403 laissent aussi le lot en attente (jeton éventuellement révoqué,
     pas le contenu du lot qui serait en cause). Seul un code ≥ 400 non-503/401/403 abandonne le
     `batch_id` (payload rejeté métier), sans jamais marquer quoi que ce soit `is_synced=True`.
  2. **Persistance locale du lot en attente** (`<data_dir>/sync_outbox.json`) : survit à un
     redémarrage du processus pendant qu'un lot attend sa confirmation.
  - État exposé en mémoire (`ONLINE`/`OFFLINE`/`SYNC_ERROR`, dernier push/pull, nb en attente,
    dernière erreur) pour le bandeau frontend (SYNC.md §9).
- `backend/sync/desktop_status.py` + route ajoutée dans `backend/sync/urls.py`
  (`GET /api/sync/local-status/`) : expose cet état via une authentification **JWT utilisateur
  classique**, distincte de `/api/sync/status/` (jeton de nœud, côté Cloud). Voir §4 point 1 pour
  la contradiction identifiée avec SYNC.md §9 sur ce point précis.
- **Non corrigé volontairement** : `sync_now.py` (usage manuel en ligne de commande) ne bénéficie
  pas de ces deux garanties — ticket **BUG-072** ouvert pour `architecte-sync`/`dev-backend`.

### 1.3 Application Electron (`desktop/`)

Arborescence conforme à DESKTOP.md §4 :
```
desktop/
  package.json, tsconfig.json, electron-builder.yml
  src/
    main.ts         orchestrateur : config → (assistant 1er lancement) → backend → fenêtre
    backend.ts       spawn/health-check (`/api/core/config/`)/arrêt propre (SIGTERM puis SIGKILL)/
                      3 tentatives de redémarrage automatique en cas de plantage
    preload.ts        pont `window.kiese` (contextIsolation, apiUrl dynamique injecté par sendSync)
    splashPreload.ts   pont minimal pour l'écran de démarrage
    printing.ts        impression silencieuse 58/80 mm (`webContents.print`, `silent:true`)
    backup.ts          sauvegarde manuelle, liste, restauration (arrête le backend avant remplacement)
    updater.ts         electron-updater, canal stable, installation proposée à la fermeture
    firstRun.ts        IPC de l'assistant (test de connexion cloud, soumission finale)
    config.ts          config.json + chiffrement safeStorage des secrets (jeton de nœud, SECRET_KEY)
    port.ts             port libre 18000-18999 (sans dépendance externe)
    paths.ts, logger.ts
  resources/
    splash.html, firstRun.html (assistant HTML/JS autonome, pas de données métier)
    icon.ico (PLACEHOLDER généré programmatiquement — à remplacer par la charte graphique réelle)
  scripts/
    build-backend.ps1   venv de build + PyInstaller --onedir, exclut explicitement tout `.env`
    build-frontend.ps1   npm ci && npm run build → resources/frontend
    build-all.ps1        orchestre les deux + electron-builder --win nsis
```

Points de sécurité respectés (DESKTOP.md §3.4/§13) : `contextIsolation:true`, `nodeIntegration:
false`, `sandbox:true` sur toutes les fenêtres (principale, splash, impression) ; navigation
limitée à `file://`/`127.0.0.1` (`will-navigate`, `setWindowOpenHandler`) ; secrets transmis au
process backend uniquement par variable d'environnement, jamais en ligne de commande ni réécrits
en clair sur disque (`safeStorage`, lié au compte Windows).

### 1.4 Frontend — `apiUrl` dynamique

`frontend/src/api/client.ts` modifié (minimal, ciblé) : `API_BASE_URL` lit désormais
`window.kiese?.apiUrl` en priorité (injecté par `preload.ts` avant l'évaluation du module), avec
repli sur `VITE_API_URL` figé au build pour tout usage hors desktop (navigateur, POS Android,
inchangé). `npm run build` du frontend repasse sans erreur après cette modification (confirmé).

## 2. Vérifications effectuées dans cette session

Aucune modification de `backend/db.sqlite3` à aucun moment (toutes les validations utilisent des
répertoires de données temporaires isolés, supprimés ensuite) :

- `python -m py_compile` sur tous les nouveaux fichiers Python — OK.
- `manage.py check` / `manage.py migrate --noinput` avec `DJANGO_SETTINGS_MODULE=kiese.
  settings_desktop` et un `--data-dir` temporaire — migrations appliquées avec succès, fichier
  `kiese.sqlite3` créé au bon endroit (pas `backend/db.sqlite3`).
- Exécution complète de `desktop_server.py` (bootstrap, migrations, sauvegarde, rotation,
  `ensure_local_admin`) par appel direct des fonctions internes — toutes les étapes passent,
  sauvegarde `.gz` créée et marqueur quotidien posé.
- `python manage.py test sync` → **24/24 OK**. `python manage.py test core` → OK (exit 0).
- `python manage.py makemigrations --check --dry-run` → dérive déjà connue et documentée
  (BUG-057, `clients`/`production`/`treasury`), **non liée** à cette session.
- `npm run typecheck` et `npm run build` dans `desktop/` (après `npm install`) → aucune erreur
  TypeScript, `dist/*.js` généré.
- `npm run build` dans `frontend/` → OK (warning préexistant sur la taille du bundle, sans
  rapport avec cette session).

### Ce qui n'a PAS été construit/exécuté dans cette session (limites de l'environnement)

- **Aucun exécutable `kiese-server.exe` réel** : PyInstaller n'est pas installé dans cet
  environnement de développement (seulement vérifié absent, pas installé pour ne pas polluer
  l'environnement partagé) ; `build-backend.ps1` est écrit et relit mais pas exécuté de bout en
  bout. Logique métier équivalente validée indirectement en appelant les mêmes fonctions Python
  directement (voir §2).
- **Aucun `electron-builder --win nsis` réel** : nécessiterait de télécharger Electron complet,
  de disposer des deux dossiers `resources/backend`/`resources/frontend` déjà construits, et
  éventuellement d'un certificat de signature — non fait ici. Seul `tsc` (compilation du
  processus principal) a été exécuté.
- **Icône** : `desktop/resources/icon.ico` est un espace réservé généré par script, pas un
  élément de charte graphique validé.
- Aucune impression réelle testée sur une imprimante thermique physique (pas de matériel
  disponible ici) — relève de `testeur-materiel` (DESKTOP.md §15, D4).

## 3. Bug trouvé et corrigé pendant la construction (BUG-071)

`kiese/settings.py::load_dotenv(BASE_DIR / '.env', override=True)` écraserait silencieusement
`DB_NAME`/`SECRET_KEY` posés par `desktop_server.py` avant `django.setup()` si un `.env` se
retrouvait dans le paquet PyInstaller — reproduit : avec le `.env` de développement de ce dépôt
(`DB_NAME=` vide), `settings.DATABASES['default']['NAME']` retombait sur `backend/db.sqlite3` (la
base de DÉVELOPPEMENT) malgré un `DB_NAME` valide déjà présent dans l'environnement du process.
Corrigé par réaffirmation explicite de `SECRET_KEY`/`DATABASES` dans `settings_desktop.py` après
l'import, **et** par un garde-fou dans `build-backend.ps1` qui supprime/avertit si un `.env` est
trouvé dans le paquet final. Détail complet et preuve reproduite avant/après :
`docs/qa/REGISTRE_BUGS.md` fiche BUG-071 (statut CORRIGÉ, à vérifier par `testeur-installation`
sur un build réel).

## 4. Points à signaler au coordinateur (ne pas trancher seul)

1. **Contradiction SYNC.md §9 / implémentation réelle de `/api/sync/status/`.** SYNC.md §9 décrit
   le bandeau frontend comme alimenté par « un nouvel endpoint local `GET /api/sync/status/`
   exposé par le backend desktop lui-même » — mais la route `/api/sync/status/` existante est
   authentifiée par `NodeTokenAuthentication` (jeton de nœud, une « machine »), incompatible avec
   un appel direct depuis le navigateur humain du poste. J'ai levé cette contradiction en ajoutant
   une route séparée `GET /api/sync/local-status/` (JWT utilisateur classique), sans toucher à la
   route Cloud existante. **À confirmer/aligner avec `architecte-sync`** si une convention de
   nommage unique est préférée pour la V2.
2. **BUG-072** (mineur, ouvert) : `manage.py sync_now` en usage manuel ne respecte pas encore
   BUG-067 (régénère un `batch_id` à chaque appel, traite 503 comme toute autre erreur). Seule la
   boucle automatique du poste desktop (`sync/desktop_client.py`, dans mon périmètre) est
   conforme. Je n'ai pas modifié `sync_now.py` lui-même pour ne pas interférer avec le travail
   livré par `architecte-sync` — à vous de décider si cet alignement doit être fait.
3. **BUG-073** (majeur, ouvert) : DESKTOP.md §11 demande qu'un échec de migration après mise à
   jour déclenche une « restauration automatique de la sauvegarde et un retour à la version
   précédente ». La sauvegarde automatique avant migration est bien faite
   (`desktop_server.py`), mais ni la restauration automatique en cas d'échec, ni le retour à
   l'exécutable précédent (hors du périmètre standard d'`electron-updater`, qui n'installe que la
   version la plus récente) ne sont implémentés. Décision produit nécessaire avant D7 : accepter
   un blocage avec restauration **manuelle** guidée (déjà possible via le menu Administration,
   `backup.ts::restoreBackup`, fonctionnel), ou commander un vrai rollback automatique (plus
   complexe, à chiffrer).
4. **`backup.ts::createBackupFile` (sauvegarde « à la demande » depuis l'interface)** utilise une
   copie/compression fichier simple (`fs.createReadStream` + gzip), pas l'API `sqlite3.backup()`
   utilisée côté Python pour les sauvegardes automatiques (démarrage, quotidienne, pré-migration).
   Documenté en commentaire dans le code : acceptable parce que cette action est pensée pour être
   déclenchée pendant une période d'inactivité, mais pas rigoureusement cohérent si elle est
   utilisée pendant une écriture concurrente réelle. Signalé ici pour que `testeur-installation`
   le teste explicitement sous charge avant de le considérer suffisant pour la V1.

## 5. Fichiers livrés/modifiés (chemins absolus)

Backend :
- `D:\Projects\kiesse\backend\desktop_server.py` (nouveau)
- `D:\Projects\kiesse\backend\kiese\settings_desktop.py` (nouveau)
- `D:\Projects\kiesse\backend\sync\desktop_client.py` (nouveau)
- `D:\Projects\kiesse\backend\sync\desktop_status.py` (nouveau)
- `D:\Projects\kiesse\backend\sync\urls.py` (modifié : route `local-status/` ajoutée)
- `D:\Projects\kiesse\backend\core\management\commands\ensure_local_admin.py` (nouveau)

Frontend :
- `D:\Projects\kiesse\frontend\src\api\client.ts` (modifié : `apiUrl` dynamique)

Desktop (nouveau dossier complet) :
- `D:\Projects\kiesse\desktop\package.json`, `tsconfig.json`, `electron-builder.yml`
- `D:\Projects\kiesse\desktop\src\{main,backend,preload,splashPreload,printing,backup,updater,firstRun,config,port,paths,logger}.ts`
- `D:\Projects\kiesse\desktop\resources\{splash.html,firstRun.html,icon.ico}`
- `D:\Projects\kiesse\desktop\scripts\{build-backend.ps1,build-frontend.ps1,build-all.ps1}`

Registre/documentation :
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-071 CORRIGÉ, BUG-072 et BUG-073 OUVERT)
- `D:\Projects\kiesse\docs\qa\rapports\packaging-desktop-2026-10-23.md` (ce rapport)

## 6. Suite recommandée

- `testeur-installation` : exécuter réellement `build-all.ps1` sur une machine Windows avec accès
  internet complet, vérifier l'installeur NSIS produit (taille, raccourci, désinstallation qui
  conserve `%APPDATA%\KIESE\`), confirmer BUG-071 sur le build réel, dérouler l'assistant de
  première installation de bout en bout avec un vrai jeton de nœud.
- `testeur-materiel` : valider l'impression silencieuse 58/80 mm sur une imprimante thermique
  physique, et les accents/symbole « FC » (DESKTOP.md §10).
- `testeur-charge` : scénario de coupure prolongée avec le nouveau `desktop_client.py` (503 répété
  plusieurs cycles de suite, vérifier qu'aucun doublon n'apparaît côté Cloud et que
  `sync_outbox.json` survit à un redémarrage du processus).
- Coordinateur : trancher BUG-072 et BUG-073 (voir §4).
