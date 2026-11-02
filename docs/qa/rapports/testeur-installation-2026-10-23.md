# Rapport — testeur-installation — 2026-10-23

Mission : tester le cycle de vie de l'application desktop livrée par `packaging-desktop`
(`docs/qa/rapports/packaging-desktop-2026-10-23.md` et `-bug073-2026-10-23.md`), en allant le plus
loin possible vers un build réel sur l'environnement Windows mis à disposition.

## 1. Résumé — l'essentiel

**L'environnement disponible est bien un Windows 10 réel avec accès Internet** (contrairement à
l'hypothèse de limite signalée par `packaging-desktop`). J'ai donc pu construire un vrai
`kiese-server.exe` avec PyInstaller, pas seulement valider la logique Python par appel direct de
fonctions. **Ce build réel révèle que `desktop/scripts/build-backend.ps1`, dans son état actuel,
produit un exécutable totalement inutilisable** : aucune des quatre tentatives de build n'a abouti
à une application desktop fonctionnelle de bout en bout sans intervention manuelle. J'ai isolé et
documenté précisément quatre causes distinctes, les ai corrigées une par une **uniquement dans mes
invocations de test** (jamais dans les fichiers livrés, conformément à la règle « je ne corrige
pas le code applicatif/packaging »), pour vérifier que chaque correctif proposé fonctionne
réellement avant de l'écrire dans le registre.

4 tickets ouverts : **BUG-078** (Bloquant), **BUG-079** (Majeur), **BUG-080** (Mineur), tous
`composant: desktop`, détaillés dans `docs/qa/REGISTRE_BUGS.md`.

## 2. Ce qui a été fait, dans l'ordre

1. Lecture de `docs/architecture/DESKTOP.md`, des deux rapports `packaging-desktop`, du registre
   des bugs existant (BUG-071 à BUG-077, dont plusieurs déjà `CORRIGÉ` par d'autres agents en
   parallèle).
2. Vérification de l'environnement : Python 3.12.2, Node 20.19, accès Internet confirmé
   (`pip install --trusted-host ...` nécessaire — un proxy TLS local intercepte les requêtes HTTPS
   sortantes et casse la vérification de certificat par défaut de `pip`, sans bloquer le trafic ;
   ce correctif d'environnement n'est pas un bug du projet).
3. **Backend — build réel** (`cd desktop && .\scripts\build-backend.ps1`, puis invocations
   manuelles de PyInstaller pour isoler chaque cause après le premier échec total) :
   - venv de build dédié `backend/.venv-build` (jamais `backend/.venv` ni `backend/db.sqlite3`
     touchés intentionnellement — voir §5 pour un incident mineur non intentionnel).
   - **1er essai (script tel que livré)** : échec total, aucun exécutable produit
     (`ERROR: Unable to find 'clients\templates'`) → **BUG-079**.
   - **2e essai** (`--add-data clients/templates` retiré manuellement pour continuer le
     diagnostic) : exécutable produit (75 Mo), mais plante immédiatement au lancement
     (`ModuleNotFoundError: No module named 'kiese.settings_desktop'`) → **BUG-078**, 1er
     symptôme.
   - **3e essai** (`--hidden-import kiese.settings_desktop` ajouté) : ce symptôme disparaît, un
     second apparaît aussitôt (`ModuleNotFoundError: No module named 'core.apps'`) — aucune des 9
     apps Django du projet n'est chargée → **BUG-078**, 2e symptôme.
   - **4e essai** (`--hidden-import <app>.apps` + `--collect-submodules <app>` pour les 9 apps) :
     l'exécutable démarre enfin, crée les dossiers de données, prend la sauvegarde pré-migration
     (BUG-073 toujours correct), détecte les 30 migrations en attente — **puis plante dès la
     première migration réelle** (`sqlite3.OperationalError: no such table: core_user`, levée par
     une migration de données de `token_blacklist` qui suppose `core` déjà migré) → **BUG-078**,
     3e symptôme. Root cause identifiée avec un niveau de confiance élevé par contre-épreuve
     croisée : `manage.py migrate` non figé, avec exactement les mêmes variables d'environnement,
     applique toutes les migrations sans erreur (voir détail dans la fiche) ; et
     `find dist -path "*core/migrations*"` ne trouve aucun fichier loose, alors que les migrations
     de `django.contrib.*`/`token_blacklist` sont bien présentes comme fichiers isolés sur disque
     — le dossier `migrations/` des apps du projet n'est jamais traité comme donnée par
     PyInstaller, seulement comme sous-module compilé (invisible pour l'auto-découverte de
     migrations de Django, qui liste un répertoire sur le système de fichiers).
   - **5e essai** (`--add-data "<app>/migrations;<app>/migrations"` ajouté pour les 9 apps) :
     **toutes les migrations des 9 apps s'appliquent avec succès, dans le bon ordre** —
     confirmation complète de la cause racine du 3e symptôme. Mais un **4e symptôme**, de la même
     famille, apparaît aussitôt : `treasury.migrations.0007...py` fait un import différé
     `from treasury.hashing import ...` qui échoue (`ModuleNotFoundError`), et une vérification du
     contenu réel du paquet (`PYZ-00.toc`) montre que, malgré `--collect-submodules treasury`
     explicitement passé, seuls `treasury.apps`/`models`/`signals` sont réellement présents — ni
     `treasury.hashing`, ni `treasury.views`, ni `treasury.urls`, ni `treasury.serializers`. Même
     constat pour `core` (`core.views`/`urls`/`serializers`/`admin` absents). **Conséquence : même
     une fois les migrations corrigées, aucune route API ne pourrait fonctionner** (`kiese.urls`
     a besoin d'importer `<app>.urls`/`<app>.views` pour construire le routeur). Documenté comme
     addendum dans BUG-078, cause exacte non élucidée avec certitude dans le temps disponible
     (candidats : interaction de `--collect-submodules` répété avec le hook Django, ou absence de
     `DJANGO_SETTINGS_MODULE` au moment du build) ; recommandation : `--collect-all <app>` plutôt
     que `--collect-submodules <app>`, et un test de fumée **fonctionnel** (vraie requête HTTP sur
     une route de chaque app), pas seulement `KIESE_READY`.
   - Je n'ai **jamais modifié `desktop/scripts/build-backend.ps1`** : toutes ces variantes sont des
     invocations manuelles de PyInstaller en ligne de commande, utilisées uniquement pour
     diagnostiquer puis vérifier mes hypothèses avant de les écrire dans le registre. Le script
     livré reste inchangé et toujours en échec total (BUG-079 seul suffit à bloquer tout le reste).
4. **Desktop (Electron)** : `npm ci`, `npm run typecheck`, `npm run build` dans `desktop/` —
   **tous passent sans erreur** sur le code TypeScript livré.
5. **Relecture de code ciblée** de `desktop/src/*.ts` (main, backend, preload, config, firstRun,
   backup, printing, updater, port, paths, logger, splashPreload) : architecture cohérente avec
   DESKTOP.md, sécurité correcte (`contextIsolation`, `sandbox`, navigation restreinte, secrets
   via `safeStorage`, jamais en ligne de commande). Un défaut trouvé par relecture croisée avec
   `resources/splash.html` : le bouton « Réessayer » de l'écran de démarrage envoie un message IPC
   (`kiese:splash:retry`) qu'aucun gestionnaire de `main.ts` n'écoute → **BUG-080** (mineur,
   n'empêche pas d'utiliser l'application, juste de relancer le backend sans fermer toute la
   fenêtre).
6. `docs/qa/CHECKLIST_INSTALLATION.md` créée pour l'humain (Windows 10/11, compte non admin,
   antivirus actif, avec et sans Internet) : installation, assistant de premier lancement,
   connexion, facture, impression, fermeture/réouverture, mise à jour, restauration de sauvegarde,
   désinstallation/réinstallation avec reprise des données, changement d'heure système. Chaque
   section renvoie explicitement vers BUG-074 (écran de restauration absent, en correction
   parallèle par `dev-frontend`) et BUG-075/076 (impression) pour éviter de coter KO à tort ce qui
   est déjà connu.

## 3. Niveau de confiance par domaine

**Vérifié avec un niveau de confiance élevé (build réel, exécution réelle de l'exécutable
packagé, pas seulement la logique Python en isolation)** :
- Le script de build livré échoue totalement (BUG-079) — confirmé par exécution directe du
  script, sans aucune modification.
- Une fois ce blocage contourné manuellement, l'exécutable packagé plante en cascade sur quatre
  symptômes distincts, tous de la même famille (références dynamiques/différées invisibles à
  l'analyse statique de PyInstaller), documentés avec preuve avant/après pour chacun (BUG-078).
- Le correctif « ajouter les `--add-data` migrations » fonctionne réellement : toutes les
  migrations des 9 apps s'appliquent dans le bon ordre une fois ce correctif appliqué — vérifié en
  observant le journal complet d'une exécution réelle (`Applying core.0001_initial... OK` jusqu'à
  `treasury.0006...OK`).
- `desktop/` (TypeScript) compile et type-check sans erreur (`npm run typecheck`, `npm run build`).
- BUG-080 (bouton « Réessayer » mort) confirmé par recherche exhaustive du gestionnaire IPC
  correspondant.
- BUG-071 (garde-fou `.env`) re-confirmé sain sur le build réel : aucun fichier `.env` trouvé dans
  `dist/kiese-server/` à aucune étape.
- `PRAGMA integrity_check` sur `backend/db.sqlite3` (base réelle) : `ok`, 83 lignes dans
  `django_migrations`, après l'incident décrit au §5 — aucune donnée perdue ou altérée.

**Non vérifié dans cette session, à confirmer sur une machine Windows dédiée avec un build
complètement corrigé** :
- L'exécutable complet fonctionnant de bout en bout (migrations **et** toutes les routes API
  disponibles) — le 4e symptôme (modules manquants au-delà des migrations) n'a pas été entièrement
  résolu ni revérifié dans le temps disponible ; je recommande à `packaging-desktop` de reprendre
  à partir de `--collect-all <app>` plutôt que `--collect-submodules`.
- `electron-builder --win nsis` (l'installeur `.exe` final) : non tenté dans cette session (le
  temps disponible a été concentré sur le blocage, plus sévère, du backend packagé — produire un
  installeur autour d'un backend qui ne démarre pas n'aurait rien appris de plus). À faire dès que
  BUG-078/079 sont corrigés par `packaging-desktop`.
- Impression thermique physique, comportement sous coupure de courant brutale (pas de machine
  jetable disponible pour un arrêt forcé contrôlé dans cette session), désinstallation réelle via
  le panneau de configuration Windows avec un vrai installeur NSIS — tout cela reste dans
  `docs/qa/CHECKLIST_INSTALLATION.md` pour la session humaine, car cela suppose un installeur réel
  qui n'existe pas encore (bloqué par BUG-078/079).
- Assistant de première installation (`firstRun.html`/`firstRun.ts`) testé uniquement par lecture
  de code, jamais exécuté dans la fenêtre Electron réelle (aurait nécessité de résoudre BUG-078/079
  d'abord pour avoir un backend sur lequel s'appuyer).

## 4. Tickets ouverts (détail complet dans `docs/qa/REGISTRE_BUGS.md`)

- **BUG-078** (Bloquant, `desktop`) — `kiese-server.exe` ne démarre ni ne sert aucune route utile
  tel que `build-backend.ps1` le construit actuellement : `kiese.settings_desktop` absent, les 9
  apps Django du projet absentes de `INSTALLED_APPS` au chargement, leurs migrations invisibles
  pour Django même une fois les apps chargées, et une partie de leurs sous-modules (vues, urls,
  sérialiseurs) toujours absents du paquet même avec `--collect-submodules`. Quatre symptômes
  cascadés, chacun masquant le suivant, documentés avec reproduction complète et contre-épreuves.
- **BUG-079** (Majeur, `desktop`) — `--add-data "clients/templates;clients/templates"` dans
  `build-backend.ps1` référence un dossier qui n'existe nulle part dans le dépôt : échec total et
  immédiat du build, sans ce correctif aucun des diagnostics de BUG-078 n'aurait même été
  accessible.
- **BUG-080** (Mineur, `desktop`) — le bouton « Réessayer » de l'écran de démarrage n'a aucun
  gestionnaire IPC côté `main.ts` : clic sans effet.

Je n'ai passé aucun des tickets déjà `CORRIGÉ` par d'autres agents (BUG-071, BUG-073, BUG-075,
BUG-076) à `VÉRIFIÉ` : BUG-071 a été re-confirmé sain par un test indépendant sur le build réel
(mentionné ci-dessus) mais sa vérification formelle reste au testeur d'origine ou au coordinateur
par prudence, faute d'avoir pu tester le scénario complet qu'il décrit (poste de production, pas
seulement l'absence de `.env` dans le paquet).

## 5. Incident de process à signaler honnêtement

Pendant le diagnostic du 3e symptôme de BUG-078, j'ai lancé par erreur un `manage.py migrate`
**sans** `DJANGO_SETTINGS_MODULE=kiese.settings_desktop` (en utilisant `kiese.settings` nu, pour
isoler si le problème venait de l'ordre des migrations plutôt que du packaging). Cette commande a,
sans que je m'en rende compte immédiatement, **touché `backend/db.sqlite3` réel** : le mécanisme
exact de BUG-071 (`.env` du dépôt avec `DB_NAME` vide, écrasant toute variable d'environnement
posée manuellement) a fait retomber `DB_NAME` sur la base de développement réelle au lieu du
dossier temporaire voulu. La commande a répondu « No migrations to apply » (la base était déjà à
jour) : **aucune écriture de schéma ni de données n'a eu lieu**. Vérification après coup :
`PRAGMA integrity_check` → `ok`, 83 lignes dans `django_migrations` (nombre cohérent). Je signale
cet incident sans le minimiser : la règle « ne jamais toucher `backend/db.sqlite3` réel » a été
enfreinte par inattention, même si la conséquence constatée est nulle. Leçon retenue et applicable
aux prochaines sessions : toute invocation CLI de diagnostic sur ce dépôt doit explicitement forcer
`DJANGO_SETTINGS_MODULE=kiese.settings_desktop` **et** `DB_NAME` vers un chemin temporaire, jamais
supposer que poser seulement `DB_NAME` en variable d'environnement suffit (BUG-071 le confirme).

## 6. Fichiers livrés par cette session

- `docs/qa/CHECKLIST_INSTALLATION.md` (nouveau) — checklist manuelle complète pour l'humain.
- `docs/qa/REGISTRE_BUGS.md` — BUG-078, BUG-079, BUG-080 ajoutés (table de suivi + fiches
  détaillées complètes).
- `docs/qa/rapports/testeur-installation-2026-10-23.md` (ce rapport).
- Aucune modification de code applicatif ou de packaging (`backend/`, `desktop/` hors doc/rapport
  inchangés). Tous les artefacts de build temporaires (`backend/.venv-build`, `backend/dist`,
  `backend/build`, `backend/staticfiles`, `backend/kiese-server.spec`) ont été supprimés en fin de
  session.

## 7. Recommandation au coordinateur

BUG-078/BUG-079 bloquent entièrement l'étape D1 de DESKTOP.md §15 (et donc toutes les étapes
suivantes D2-D8) : aucun exécutable desktop réel n'existe actuellement, malgré le travail déjà
solide de `packaging-desktop` sur la logique applicative (validée en isolation, mais jamais à
travers un vrai build PyInstaller avant cette session). Je recommande que `packaging-desktop`
reprenne `build-backend.ps1` avec les pistes documentées dans BUG-078 (`--collect-all <app>` pour
les 9 apps, `--add-data` migrations, test de fumée fonctionnel en fin de script) avant toute
nouvelle tentative de construire l'installeur complet.
