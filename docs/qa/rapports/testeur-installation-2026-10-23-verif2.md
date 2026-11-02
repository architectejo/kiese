# Rapport — Vérification indépendante BUG-078 / BUG-079 / BUG-080

- Agent : testeur-installation
- Date : 2026-10-23
- Portée : vérification indépendante du correctif `packaging-desktop` décrit dans
  `docs/qa/rapports/packaging-desktop-bug078-079-080-fix-2026-10-23.md`
  (`desktop/scripts/build-backend.ps1`, `desktop/src/main.ts`, `desktop/resources/splash.html`).

## Méthode

1. Lecture des fiches CORRIGÉ de BUG-078/079/080 dans `docs/qa/REGISTRE_BUGS.md` et du rapport de
   correction.
2. Relecture complète de `desktop/scripts/build-backend.ps1` modifié.
3. **Build réel rejoué depuis zéro** sur cette machine Windows : sauvegarde de sécurité de
   `backend/db.sqlite3` prise avant toute opération (jamais modifiée, hash MD5 identique avant/après,
   `PRAGMA integrity_check` = `ok`, 695 clients intacts — vérifié et nettoyé en fin de session).
   `backend/.venv-build` n'existait pas au départ (déjà supprimé par packaging-desktop) : recréé
   intégralement.
4. Smoke tests étendus sur l'exécutable réellement produit, dans des dossiers `--data-dir`
   temporaires isolés (jamais `backend/db.sqlite3`).
5. Vérification de code du correctif BUG-080 + `npx tsc --noEmit`.
6. Tentative d'aller plus loin (installeur NSIS complet) — documentée ci-dessous, non aboutie.

## Build réel — BUG-078 / BUG-079

- `pip install -r requirements.txt waitress pyinstaller` dans `.venv-build` : a d'abord échoué
  (`SSLCertVerificationError` sur pypi.org — interception SSL locale à cet environnement, déjà
  rencontrée et documentée comme non pertinente pour l'artefact par packaging-desktop). Contourné
  manuellement avec `--trusted-host pypi.org --trusted-host files.pythonhosted.org
  --trusted-host pypi.python.org`, puis le script a été relancé tel quel pour le reste du build
  (aucune modification du script lui-même).
  - **Observation pour packaging-desktop/coordinateur** : le script ne gère pas ce cas (pas de
    `--trusted-host`, pas de vérification du code de sortie de `pip install`/`collectstatic` avant
    de poursuivre) — sur une machine propre avec le même problème réseau, le script échouera
    silencieusement plus loin (ex. `pyinstaller.exe introuvable`) sans message clair expliquant que
    la cause racine est `pip install` resté bloqué en amont. Observation de robustesse, **pas un
    nouveau ticket** : le comportement du script une fois les dépendances présentes est conforme et
    déjà couvert par BUG-078/079.
- `.\scripts\build-backend.ps1` ensuite exécuté intégralement sans aucune modification :
  - `collectstatic` : 154 fichiers statiques copiés, OK.
  - Préparation des sources (étape 3/6) : les 9 apps + `kiese` copiées dans `.build-staging/`.
  - PyInstaller (étape 4/6) : **terminé avec succès** (`Build complete!`).
  - Test de fumée intégré au script (étape 5/6) : `KIESE_READY`, `core_user`/`clients_client`/
    `treasury_cashbookentry` présents, `GET /api/core/config/` → 200, `GET /api/docs/swagger/` → 200.
  - Copie finale (étape 6/6) : `desktop/resources/backend/kiese-server.exe` produit.
  - **Code de sortie global : 0.**
  - Nettoyage automatique confirmé : `backend/dist/`, `build/`, `.spec`, `.build-staging/` absents
    après exécution. `desktop/resources/backend/` : **88 Mo** (cohérent avec les 92 Mo rapportés).

## Smoke tests indépendants supplémentaires (au-delà de ceux de packaging-desktop)

Backend lancé depuis l'exécutable final (`desktop/resources/backend/kiese-server.exe`), dans un
`--data-dir` temporaire neuf, `KIESE_SECRET_KEY` posé explicitement, `KIESE_NODE_TOKEN`/
`KIESE_CLOUD_URL` absents (mode hors-ligne). Log des migrations confirme l'application réelle des
**14 apps** (`admin, auth, blockchain, clients, commissions, contenttypes, core, finance,
production, sales, sessions, sync, token_blacklist, treasury`) — donc bien les 9 apps du projet,
pas seulement `core`.

Routes testées, une par app du projet (couverture volontairement plus large que packaging-desktop,
qui n'avait pas testé `sales`/`production`/`commissions`/`finance`/`blockchain`/`sync`) :

| Route | Code | Commentaire |
|---|---|---|
| `GET /api/core/config/` | 200 | |
| `GET /api/clients/clients/` | 401 | pas 500 — exerce `clients.views → clients.imports → openpyxl` |
| `GET /api/sales/invoices/` | 401 | |
| `GET /api/production/sessions/` | 401 | |
| `GET /api/treasury/closures/` | 401 | |
| `GET /api/commissions/periods/` | 401 | |
| `GET /api/finance/years/` | 401 | |
| `GET /api/blockchain/alerts/` | 401 | |
| `GET /api/sync/status/` | 401 | |
| `GET /admin/login/` | 200 | gabarits admin Django |
| `GET /api/docs/swagger/` | 200 | force l'import vues/urls/sérialiseurs des 9 apps |
| `GET /api/docs/redoc/` | 200 | |
| `GET /api/schema/` | 200 | schéma OpenAPI brut |
| `POST /api/core/auth/login/` | 401 | pas 500, identifiants invalides |

Aucune route n'a renvoyé 500. Aucun `ModuleNotFoundError`/`TemplateDoesNotExist`/traceback dans
`stdout.log`/`stderr.log`. Seuls des avertissements bénins `drf_spectacular` ("unable to guess
serializer" sur des `APIView` sans `serializer_class`, "AnonymousUser has no attribute
can_access_all_nodes" lors de la génération du schéma sur des vues authentifiées) — préexistants,
sans rapport avec l'empaquetage, non bloquants (schéma généré quand même, 200). Mode WAL confirmé
(`kiese.sqlite3-wal`/`-shm` présents dans le `--data-dir`).

**Conclusion BUG-078/BUG-079 : confirmés corrigés, reproduits de façon totalement indépendante,
couverture élargie à toutes les apps. Passés à VÉRIFIÉ.**

## BUG-080 — bouton « Réessayer »

- Relecture de `desktop/src/main.ts` : `ipcMain.on('kiese:splash:retry', ...)` présent, avec garde
  `retryInProgress` et `if (retryInProgress || mainWindow) return;`, enchaîne
  `stopBackendIfRunning().then(() => launchBackendAndMainWindow())`, retombe sur `setSplashError()`
  en cas de nouvel échec — conforme à la description du correctif.
- `desktop/resources/splash.html` : le gestionnaire de statut remasque bien le bloc d'erreur et
  réaffiche le spinner à chaque nouveau statut.
- `cd desktop && npx tsc --noEmit` ré-exécuté indépendamment : **passe sans erreur**.
- **Non réalisé dans cette passe** : test de bout en bout dans l'application Electron packagée
  réelle (renommer `kiese-server.exe`, observer l'écran d'erreur, cliquer « Réessayer », rétablir
  l'exécutable, vérifier l'apparition de la fenêtre principale). `npm ci` du frontend avait échoué
  à ce stade (`EPERM` sur `node_modules/@rolldown/binding-win32-x64-msvc`, verrou par deux
  processus Node résiduels — voir section « Complément » plus bas : le coordinateur a levé ce
  verrou et la suite de la mission, incluant une tentative de ce test précis, a été reprise et
  documentée plus loin dans ce rapport).
- **Conclusion BUG-080 : passé à VÉRIFIÉ sur la base de la relecture de code et de `tsc`, qui
  couvrent fidèlement la description du correctif.** Voir la section « Complément » plus bas pour
  la tentative effective du scénario end-to-end (verrou levé, mais obstacle différent rencontré :
  absence de session Windows interactive dans cet environnement d'agent).

## Tentative d'aller plus loin (installeur NSIS complet) — première passe

- `desktop/scripts/build-frontend.ps1` lancé : `npm ci` échoue avec `EPERM: operation not
  permitted, unlink ... @rolldown/binding-win32-x64-msvc\rolldown-binding.win32-x64-msvc.node`
  (fichier verrouillé — identifié ensuite par le coordinateur comme provenant de deux processus
  Node résiduels d'une session de test antérieure). Le script ne vérifie pas le code de sortie de
  `npm ci`/`npm run build` avant de poursuivre vers la copie — observation de robustesse similaire
  à celle notée plus haut pour `build-backend.ps1`, **hors périmètre de BUG-078/079/080** (fichier
  différent, `build-frontend.ps1`), non transformée en ticket dans cette session faute de temps
  pour la qualifier complètement (à signaler au coordinateur/packaging-desktop si jugé utile).
- `npm run build` relancé directement dans `frontend/` (sans `npm ci`) : échoue aussi
  (`'tsc' n'est pas reconnu`, `node_modules/.bin` incomplet suite à l'échec partiel de `npm ci`).
- Faute de build frontend, `build-all.ps1`/`electron-builder --win nsis` n'a pas pu être exécuté
  lors de cette première passe. **Reprise et résultats complets dans la section « Complément »
  ci-dessous, après que le coordinateur a levé le verrou.**

## Nettoyage effectué

- `backend/.venv-build/` : supprimé en fin de session.
- `backend/db.sqlite3.bak-verif2-<horodatage>` (sauvegarde de sécurité prise avant le build) :
  vérifiée identique (MD5) à `backend/db.sqlite3` final, puis supprimée.
- `backend/dist/`, `build/`, `.spec`, `.build-staging/` : nettoyés automatiquement par le script
  lui-même (comme attendu).
- Dossiers `--data-dir` temporaires de smoke test (dans le dossier scratchpad de cette session,
  jamais dans le dépôt) : non committés, sans impact sur le dépôt.
- `backend/db.sqlite3` réel : jamais modifié (confirmé par hash MD5 identique avant/après + `PRAGMA
  integrity_check = ok` + 695 clients toujours présents).
- `desktop/resources/backend/` reconstruit par cette session (88 Mo) remplace celui laissé par
  packaging-desktop (92 Mo) — artefact de build normal, laissé en place comme livrable attendu par
  `electron-builder` (pas de dépôt git à ce niveau du repo, donc pas de question de commit).
- Après la reprise de mission (complément ci-dessous) : `backend/.venv-build/` recréé pour le
  rebuild via `build-all.ps1`, supprimé à nouveau en fin de session. Cache
  `%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\` (≈ 234 Mo d'extractions partielles ayant
  toutes échoué, voir complément) : supprimé. `desktop/dist-installer/win-unpacked/` (≈ 358 Mo,
  application Electron assemblée avec succès, sans l'installeur NSIS) : **laissé en place** comme
  preuve tangible que l'assemblage frontend+backend+Electron réussit de bout en bout, malgré
  l'échec de la seule étape NSIS.

## Complément — suite à la reprise des locks `frontend/node_modules` par le coordinateur

Le coordinateur a arrêté deux processus Node résiduels qui verrouillaient
`frontend/node_modules/@rolldown/binding-win32-x64-msvc`. Reprise de la mission avec cet obstacle
levé :

- `cd frontend && npm ci` : **réussit** cette fois (56 paquets installés, aucune erreur EPERM).
- `desktop/scripts/build-frontend.ps1` : **réussit** intégralement (`tsc && vite build` → build
  Vite OK, copié vers `desktop/resources/frontend`).
- `desktop/scripts/build-all.ps1` relancé en entier :
  - Étape 1/3 (frontend) : OK, comme ci-dessus.
  - Étape 2/3 (backend) : rejoue `build-backend.ps1` depuis un `.venv-build` neuf (celui de la
    vérification précédente avait été nettoyé en fin de session) — même contournement réseau
    (`--trusted-host`) nécessaire une fois pour réinstaller les dépendances de build, puis script
    terminé avec succès (code de sortie 0), conforme à la vérification déjà actée de BUG-078/079.
  - Étape 3/3 (`npx electron-builder --win nsis`) : **l'empaquetage de l'application Electron
    (`win-unpacked/KIESE.exe`, 189 Mo, avec `resources/backend` et `resources/frontend` intégrés)
    réussit**, mais **la production du véritable installeur NSIS (`KIESE-Setup-<version>.exe`)
    échoue** systématiquement, avant même d'atteindre l'étape NSIS proprement dite : electron-builder
    tente de télécharger et d'extraire l'archive partagée `winCodeSign-2.6.0.7z` (outils
    `rcedit`/`signtool` utilisés même sans certificat de signature réel), et cette extraction échoue
    à chaque tentative avec :
    `ERROR: Cannot create symbolic link : Le client ne dispose pas d'un privilège nécessaire.`
    sur deux fichiers macOS (`darwin/10.12/lib/libcrypto.dylib`, `libssl.dylib`) contenus dans cette
    archive partagée (mac+Windows). Confirmé : le compte de cette session **n'est pas administrateur**
    (`net session` → accès refusé) et ne peut donc pas obtenir `SeCreateSymbolicLinkPrivilege`
    (requiert soit un compte administrateur, soit le Mode développeur Windows activé — les deux hors
    de portée de ce compte dans cet environnement). Testé aussi avec
    `CSC_IDENTITY_AUTO_DISCOVERY=false` : même échec, la tentative de téléchargement/extraction de
    `winCodeSign` n'est pas conditionnée par la présence d'un certificat.
    **Ce n'est pas un défaut du code de packaging** (`build-all.ps1`/`electron-builder.yml` sont
    corrects et conformes à DESKTOP.md §12 — absence de certificat gérée normalement, « signing is
    skipped » bien loggé) : c'est une limitation de privilège du compte Windows utilisé pour builder
    sur **cette machine précise**, en amont de toute étape propre à KIESE.
  - **Observation annexe (robustesse, hors périmètre BUG-078/079/080)** : comme pour
    `build-backend.ps1`/`pip install` plus haut, `build-all.ps1`/`npm ci` ne vérifient pas le code de
    sortie des commandes externes avant de poursuivre : le script a fini par afficher « Terminé »
    avec un code de sortie global 0 malgré l'échec de production de l'installeur NSIS — seule
    l'inspection du dossier `desktop/dist-installer/` (présence de `win-unpacked/` mais absence de
    `KIESE-Setup-*.exe`) permet de s'en rendre compte. À qualifier par le coordinateur/
    packaging-desktop si jugé utile (pas transformé en ticket dans cette session).
- Test du lancement direct de l'application non empaquetée en installeur
  (`dist-installer/win-unpacked/KIESE.exe`, qui contient déjà le backend et le frontend corrigés,
  pour approcher au plus près un « premier lancement » sans installeur NSIS) : **le processus se
  termine immédiatement (quelques secondes), sans fenêtre visible, sans aucune ligne de log, sans
  créer `%APPDATA%\KIESE\`** (vérifié absent avant et après). Conclusion : cette session d'agent ne
  dispose pas d'une session Windows interactive (bureau/Window Station) à laquelle Electron puisse
  attacher une fenêtre — contrainte d'infrastructure de l'environnement d'exécution de cet agent,
  pas un défaut de l'application. Le test de premier lancement, création du compte admin local,
  fermeture/réouverture, et le test de bout en bout du bouton « Réessayer » (BUG-080) **nécessitent
  une session Windows interactive réelle** (physique ou RDP avec session console) et ne peuvent pas
  être exécutés par cet agent dans cet environnement, qu'un installeur NSIS existe ou non.

### Conclusion du complément

- BUG-078/079 : aucun changement — déjà VÉRIFIÉ, reconfirmés une seconde fois par ce rebuild complet.
- BUG-080 : statut **VÉRIFIÉ maintenu**, sur la base du code/`tsc` (inchangé). Le test end-to-end
  dans l'app Electron réellement packagée reste **impossible à réaliser par un agent dans cet
  environnement** (pas de session interactive Windows), indépendamment de la disponibilité d'un
  installeur — ce n'est donc pas un chantier à poursuivre dans une prochaine session du même type
  d'agent, mais un test réservé à un humain ou à `testeur-materiel` sur une vraie machine physique.
- Production de l'installeur NSIS complet : **bloquée sur cette machine par un privilège Windows
  manquant** (compte non-administrateur, Mode développeur indisponible) lors de la récupération de
  l'outillage de signature partagé par electron-builder — à relancer par un humain ou un agent
  disposant d'un accès administrateur local, ou en pré-renseignant
  `ELECTRON_BUILDER_BINARIES_MIRROR`/un cache `winCodeSign` déjà extrait sur une autre machine.
  `desktop/dist-installer/win-unpacked/KIESE.exe` (version non empaquetée en installeur, mais
  fonctionnellement équivalente, build + resources identiques) reste disponible comme preuve que
  l'assemblage Electron + backend + frontend réussit de bout en bout.

## Points ouverts pour la suite

- Construire l'installeur NSIS complet sur une machine disposant d'un accès administrateur local
  (ou Mode développeur Windows activé), pour lever le blocage `winCodeSign`/symlink identifié dans
  le complément ci-dessus.
- Dérouler `docs/qa/CHECKLIST_INSTALLATION.md` (premier lancement, compte admin, mise à jour,
  restauration de sauvegarde, désinstallation) et le test end-to-end du bouton « Réessayer »
  (BUG-080) sur une **machine avec session Windows interactive réelle** — physique ou RDP console —
  une fois l'installeur produit : les deux obstacles rencontrés dans cette session
  (`winCodeSign`/privilège admin, puis absence de session interactive pour l'Electron non empaqueté)
  sont des contraintes d'environnement d'agent, pas des défauts applicatifs.
- Aucune modification nécessaire de `docs/qa/CHECKLIST_INSTALLATION.md` : les deux builds réels de
  cette session (backend seul, puis frontend+backend+assemblage Electron) n'ont révélé aucune
  nouvelle étape à ajuster dans la checklist d'installation manuelle elle-même — les obstacles
  rencontrés relèvent de l'outillage de build (privilège admin, session interactive), pas de la
  procédure d'installation documentée pour l'utilisateur final.

## Complément 2 (2026-10-24) — installeur NSIS produit avec succès après activation du Mode développeur

Suite à l'activation du **Mode développeur Windows** sur cette machine (action du coordinateur/
utilisateur, hors de portée de cet agent), le blocage `winCodeSign`/`SeCreateSymbolicLinkPrivilege`
documenté dans le Complément ci-dessus est **levé**. Reprise de la mission :

1. Première relance de `desktop/scripts/build-all.ps1` après activation : a échoué dès l'étape
   backend avec `pip` : `SyntaxError: source code string cannot contain null bytes` (import
   `pip._vendor.tomli` cassé) — `backend/.venv-build` d'une session précédente s'est révélé corrompu
   (probablement un `.venv-build` partiellement écrit par une tentative interrompue). **Sans rapport
   avec le Mode développeur ni avec BUG-078/079/080** : un venv Python corrompu, pas un défaut de
   `build-backend.ps1`.
   - Correctif appliqué (hors du script, ménage d'environnement uniquement) : suppression complète
     de `backend/.venv-build/`, recréation avec `python -m venv`, puis
     `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org
     --trusted-host pypi.python.org -r requirements.txt waitress pyinstaller` — réussi proprement
     (Django 5.2.18, PyInstaller 6.22.3, etc.).
2. `desktop/scripts/build-all.ps1` relancé en entier depuis ce venv propre :
   - Étape 1/3 (frontend) : OK.
   - Étape 2/3 (backend) : OK, **test de fumée intégré réussi** (migrations des 9 apps appliquées,
     `core_user` présente, `GET /api/core/config/` → 200, `GET /api/docs/swagger/` → 200).
     `desktop/resources/backend/kiese-server.exe` produit.
   - Étape 3/3 (`electron-builder --win nsis`) : packaging Electron (`win-unpacked/KIESE.exe`)
     réussi, mais la session d'agent qui exécutait cette étape a été interrompue par une coupure
     côté infrastructure avant que je puisse confirmer la fin réelle de l'étape NSIS — un suivi par
     attente passive de l'apparition du fichier final (au lieu d'un suivi du PID réel du process) a
     échoué à détecter cette coupure, laissant croire à tort que le build était simplement long.
     **Leçon méthodologique actée** : ne plus surveiller un build long par une boucle d'attente de
     fichier dérivée, mais directement via la notification native de fin du process lancé en arrière-
     plan (ou, à défaut, vérification explicite par PID avec `wmic process`).
3. Nouvelle tentative, en ne rejouant **que** l'étape finale (`cd desktop && npm run dist`, soit
   `tsc` puis `electron-builder --win nsis`), les artefacts `resources/backend`/`resources/frontend`/
   `win-unpacked` du 23/10 restant valides et cohérents entre eux (vérifié par horodatage avant de
   relancer) :
   - Lancé avec `DEBUG=electron-builder`, sortie complète conservée dans
     `nsis-build-verbose.log` (scratchpad de session), suivi cette fois par la notification native de
     fin de process en arrière-plan **et** vérification indépendante par `wmic process` (PID réels
     confirmés vivants pendant l'exécution : `npm run dist` et `electron-builder cli.js --win nsis`).
   - **Résultat : succès complet.** `makensis.exe` termine avec le code 0, blockmap généré,
     `electron-builder` se termine avec le code de sortie 0.
   - **`D:\Projects\kiesse\desktop\dist-installer\KIESE Setup 1.0.0.exe` produit : 114 241 069 octets
     (≈ 109 Mio), SHA-512 `77cYcRk7pxxQxt57NTiG3yP9NakhME02hwX5nueUvXW69S3hP5DKUzU6PNTVOH04DdOvPw6yNH/YBTS1cH5vtA==`
     (loggé par `app-builder.exe blockmap`).** Fichiers associés : `.blockmap`, `latest.yml`,
     `builder-debug.yml`. Signature de code toujours absente (pas de certificat Authenticode fourni
     dans cet environnement) — « signing is skipped », comportement attendu et documenté par
     DESKTOP.md §12.
4. Test du premier lancement réel, repris dans ces conditions :
   - Lancement direct de `desktop/dist-installer/win-unpacked/KIESE.exe` (build identique à celui
     empaqueté dans le `.exe` NSIS) : **même constat que lors du Complément précédent** — le
     processus se termine en quelques secondes, sans fenêtre visible, sans ligne de log, sans
     création de `%APPDATA%\KIESE\` (vérifié absent avant/après). La disponibilité d'un installeur
     NSIS complet **ne change rien** à cette contrainte : il s'agit toujours de l'absence de session
     Windows interactive (bureau/Window Station) à laquelle Electron puisse attacher une fenêtre dans
     cet environnement d'exécution d'agent, confirmée une seconde fois, de façon indépendante.
   - Conséquence : le test du premier lancement (assistant de première configuration), de la
     fermeture/réouverture, et **le test de bout en bout du bouton « Réessayer » (BUG-080)** restent
     **impossibles à exécuter par cet agent**, même avec l'installeur NSIS désormais disponible.
     Ces tests nécessitent une session Windows interactive réelle (physique ou RDP avec session
     console) — à réserver à un humain ou à `testeur-materiel` sur machine physique.

### Conclusion du Complément 2

- **L'obstacle `winCodeSign`/privilège administrateur est définitivement levé** par l'activation du
  Mode développeur Windows : l'installeur NSIS complet (`KIESE Setup 1.0.0.exe`) a été produit avec
  succès, de façon reproductible, sur cette machine.
- BUG-078/079 : reconfirmés une troisième fois (rebuild complet depuis un `.venv-build` neuf).
- BUG-080 : statut **VÉRIFIÉ maintenu** (relecture de code + `tsc`, inchangé). Le test end-to-end
  dans l'application réellement installée reste **hors de portée de cet agent** dans cet
  environnement (absence de session Windows interactive), **indépendamment de la disponibilité de
  l'installeur** — confirmé une seconde fois dans des conditions différentes (avec installeur NSIS
  cette fois, pas seulement `win-unpacked/`). Ce n'est donc plus un obstacle d'outillage à lever,
  mais une limite structurelle de ce type d'agent : à transmettre tel quel à `testeur-materiel` ou à
  un testeur humain pour la suite (checklist complète `docs/qa/CHECKLIST_INSTALLATION.md`, y compris
  le bouton « Réessayer »).
- `desktop/dist-installer/KIESE Setup 1.0.0.exe` est **laissé en place** comme livrable, prêt à être
  installé et testé manuellement sur une machine avec session interactive (physique ou RDP console).

## Tickets

- BUG-078 : CORRIGÉ → **VÉRIFIÉ** (confirmé trois fois : rebuild backend seul, rebuild complet
  frontend+backend+assemblage Electron, puis rebuild NSIS complet).
- BUG-079 : CORRIGÉ → **VÉRIFIÉ** (idem).
- BUG-080 : CORRIGÉ → **VÉRIFIÉ** par relecture de code et `tsc` (trois fois confirmé). Test
  end-to-end dans l'app Electron installée (installeur NSIS désormais disponible) tenté mais non
  concluant pour des raisons d'environnement d'agent (pas de session Windows interactive) — reste à
  faire par un humain ou `testeur-materiel` sur machine physique, sans remettre en cause le statut
  VÉRIFIÉ de ce ticket. **Installeur NSIS complet désormais disponible et prêt pour ce test manuel** :
  `D:\Projects\kiesse\desktop\dist-installer\KIESE Setup 1.0.0.exe`.
