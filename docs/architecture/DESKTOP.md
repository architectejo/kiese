# Application Desktop KIESE — Architecture et mise en œuvre

> Document de référence de la phase Desktop. Utilisé par les agents `packaging-desktop`, `testeur-installation`, `testeur-materiel`, `architecte-sync` et `redacteur-documentation`.

---

## 1. Pourquoi une application de bureau ?

| Besoin du client | Ce que le desktop apporte |
|---|---|
| Facturer même sans Internet (objectif n°4 du cahier des charges) | Chaque boulangerie a son propre serveur local sur le PC : la facturation ne dépend plus du réseau |
| Installation simple chez le client | Un seul fichier `.exe` à double-cliquer, pas de Python, Node ou serveur web à installer à la main |
| Impression rapide des reçus | Impression silencieuse directe sur l'imprimante thermique, sans fenêtre de dialogue |
| Centralisation au siège | Le poste local se synchronise avec le serveur cloud dès que la connexion revient |

Le poste desktop **est le « nœud local »** prévu par la section 6.3 du cahier des charges.

---

## 2. Vue d'ensemble

```
┌──────────────────────── PC de la boulangerie (Windows) ────────────────────────┐
│                                                                                │
│  ┌─────────────── Application Electron « KIESE » ──────────────┐               │
│  │                                                             │               │
│  │  Processus principal (main.ts)                              │               │
│  │   • démarre et surveille le backend                         │               │
│  │   • gère la fenêtre, l'impression, les mises à jour         │               │
│  │                                                             │               │
│  │  Fenêtre (renderer) ── frontend React compilé (fichiers)    │               │
│  │          │  appels HTTP                                     │               │
│  └──────────┼──────────────────────────────────────────────────┘               │
│             ▼                                                                  │
│   http://127.0.0.1:<port dynamique>                                            │
│  ┌─────────────────────────────────────────┐   ┌───────────────────────────┐   │
│  │ Backend Django empaqueté (PyInstaller)  │──▶│ %APPDATA%\KIESE\          │   │
│  │ servi par Waitress                      │   │  kiese.sqlite3 (WAL)      │   │
│  │ + service de synchronisation            │   │  media\  logs\  backups\  │   │
│  └───────────────────┬─────────────────────┘   │  config.json              │   │
│                      │                         └───────────────────────────┘   │
└──────────────────────┼─────────────────────────────────────────────────────────┘
                       │ HTTPS (quand Internet est disponible)
                       ▼
        ┌────────────────────────────────────────┐
        │ Serveur cloud (Linux)                  │
        │ Nginx → Gunicorn → Django → PostgreSQL │
        │ Siège, consolidation, états financiers │
        └────────────────────────────────────────┘
```

---

## 3. Choix techniques et justification

### 3.1 Waitress au lieu de Gunicorn sur le poste
**Gunicorn ne fonctionne pas sous Windows** (il dépend de `fork`, absent de Windows). Les postes des boulangeries sont sous Windows (l'environnement virtuel du projet est déjà un venv Windows). On utilise donc **Waitress**, serveur WSGI pur Python, stable et multiplateforme.
Gunicorn reste utilisé **sur le serveur cloud Linux**.

### 3.2 Pas de Nginx sur le poste
Sur un PC avec un seul utilisateur local, Nginx n'apporte rien et ajoute un service Windows à installer et maintenir :
- les fichiers du frontend sont chargés directement par Electron ;
- les fichiers statiques Django (admin, DRF) sont servis par **WhiteNoise**, déjà présent ;
- les photos clients (`media/`) sont servies par Django en local.

Nginx reste utilisé **sur le serveur cloud** (HTTPS, compression, fichiers statiques, reverse proxy vers Gunicorn).

### 3.3 SQLite sur le poste, PostgreSQL au cloud
- Poste : **SQLite en mode WAL** (`PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`). Un seul fichier, aucun service, suffisant pour une boulangerie (2 facturiers + 1 gérant).
- Cloud : **PostgreSQL**, nécessaire pour 8 boulangeries qui écrivent en même temps.
- Le code ne doit utiliser que des fonctions de l'ORM compatibles avec les deux moteurs.

### 3.4 Electron
- Une seule base de code React pour le web, le desktop et les écrans tactiles.
- Accès natif à l'impression silencieuse, au système de fichiers (sauvegardes) et aux mises à jour automatiques.
- Sécurité : `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, pont minimal dans `preload.ts`, navigation limitée à `127.0.0.1`.

---

## 4. Arborescence prévue

```
desktop/
  package.json                 electron, electron-builder, electron-updater
  electron-builder.yml         configuration de l'installeur NSIS
  src/
    main.ts                    processus principal
    backend.ts                 lancement / surveillance / arrêt du backend
    preload.ts                 pont sécurisé exposé au frontend (window.kiese)
    printing.ts                impression silencieuse des reçus
    updater.ts                 mises à jour automatiques
    backup.ts                  sauvegardes et restauration
    firstRun.ts                assistant de première installation
  resources/
    icon.ico
    splash.html                écran de chargement
  scripts/
    build-backend.ps1          PyInstaller → resources/backend/kiese-server.exe
    build-frontend.ps1         npm run build → resources/frontend/
    build-all.ps1
backend/
  desktop_server.py            point d'entrée du backend en mode desktop
  kiese/settings_desktop.py    réglages spécifiques au poste
```

---

## 5. Séquence de démarrage

1. L'utilisateur lance **KIESE** ; Electron affiche `splash.html` (« Démarrage… »).
2. `main.ts` lit `%APPDATA%\KIESE\config.json`. S'il n'existe pas → **assistant de première installation** (§7).
3. Choix d'un port libre sur `127.0.0.1` (ex. entre 18000 et 18999).
4. Lancement de `kiese-server.exe --port <port> --data-dir "%APPDATA%\KIESE"` ; sa sortie est écrite dans `logs\backend.log`.
5. `desktop_server.py` :
   - charge `settings_desktop.py` (base, `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS=['127.0.0.1']`) ;
   - **sauvegarde la base** si des migrations sont en attente, puis lance `migrate` ;
   - active le mode WAL ;
   - démarre Waitress (`threads=8`) et le service de synchronisation en tâche de fond.
6. Electron interroge `GET /api/core/config/` toutes les 500 ms (max 60 s).
7. Dès la réponse : la fenêtre charge le frontend avec l'adresse de l'API transmise par `preload.ts` (`window.kiese.apiUrl`), et non par une variable Vite figée au build.
8. Si le backend ne répond pas : message clair + bouton « Ouvrir le journal » + « Réessayer ».

**Arrêt** : à la fermeture, Electron demande l'arrêt propre du backend (signal ou endpoint local protégé), attend 5 s, puis force l'arrêt. **Plantage** : redémarrage automatique (3 tentatives), puis message d'erreur.

---

## 6. Réglages Django en mode desktop (`settings_desktop.py`)

```python
from .settings import *  # noqa

DATA_DIR = Path(os.environ['KIESE_DATA_DIR'])
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
SECRET_KEY = lire_depuis(DATA_DIR / 'config.json')       # générée à l'installation
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': DATA_DIR / 'kiese.sqlite3',
    'OPTIONS': {'timeout': 20, 'init_command': 'PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;'},
}}
MEDIA_ROOT = DATA_DIR / 'media'
STATIC_ROOT = BUNDLE_DIR / 'staticfiles'                  # collectstatic fait au build
CORS_ALLOWED_ORIGINS = ['app://kiese', 'file://']         # selon le protocole de chargement retenu
KIESE_NODE_CODE = config['node_code']                     # ex. 'K1'
KIESE_CLOUD_URL = config['cloud_url']
```

> Le paramètre `init_command` n'existe pas pour SQLite selon la version de Django : appliquer les PRAGMA via le signal `connection_created` si nécessaire.

---

## 7. Assistant de première installation

Écrans successifs :
1. **Langue** (Français / English).
2. **Boulangerie** : code (K1…B2 ou nouveau) et nom.
3. **Connexion au cloud** : URL du serveur + **jeton de nœud** fourni par le siège (menu Nœuds). Test de connexion. Possibilité de « Continuer hors-ligne » et de lier plus tard.
4. **Première synchronisation descendante** : prix des pains, configuration, utilisateurs de cette boulangerie, clients (avec barre de progression).
5. **Compte administrateur local** de secours (si pas de cloud).
6. **Imprimante** : liste des imprimantes Windows, choix de la thermique, largeur 58 / 80 mm, impression d'un ticket de test.
7. Récapitulatif → génération de `config.json` et d'une `SECRET_KEY` aléatoire unique au poste.

---

## 8. Données et sauvegardes

```
%APPDATA%\KIESE\
  kiese.sqlite3, kiese.sqlite3-wal, kiese.sqlite3-shm
  config.json            code nœud, URL cloud, jeton de nœud (chiffré via safeStorage d'Electron), imprimante
  media\                 photos clients
  logs\                  backend.log, electron.log, sync.log (rotation 10 × 5 Mo)
  backups\               kiese-AAAAMMJJ-HHMM.sqlite3.gz
```
- Sauvegarde **quotidienne** (à la première ouverture du jour et après chaque clôture journalière) via l'API de sauvegarde SQLite (cohérente même pendant l'utilisation), compressée, conservée **30 jours**.
- Sauvegarde **avant chaque migration** et avant chaque mise à jour.
- Copie optionnelle sur clé USB ou dossier réseau choisi par le gérant.
- **Restauration** depuis le menu Administration : arrêt du backend, remplacement de la base, redémarrage, puis synchronisation.
- La désinstallation **ne supprime pas** `%APPDATA%\KIESE\`.

---

## 9. Synchronisation (résumé)

Conçue par `architecte-sync` dans `docs/architecture/SYNC.md`. Principes côté poste :
- Toute écriture locale marque l'enregistrement `is_synced=False`.
- Un service vérifie la connexion toutes les 30 s ; quand le cloud répond, il **envoie** les lots non synchronisés (idempotents par UUID), puis **récupère** les changements de configuration.
- Bandeau dans l'interface : 🟢 En ligne · 🟠 Hors-ligne — 12 opérations en attente · 🔴 Erreur de synchronisation.
- La dette d'un client qui achète dans plusieurs boulangeries est recalculée au cloud à partir des mouvements, jamais écrasée.

---

## 10. Impression des reçus

- Le frontend appelle `window.kiese.printReceipt(html, { width: 80 })`.
- `printing.ts` crée une fenêtre cachée, charge le reçu, puis `webContents.print({ silent: true, deviceName, margins: { marginType: 'none' }, pageSize: { width: 80000, height: … } })`.
- Hors desktop (navigateur, POS Android), repli sur `window.print()` existant.
- Polices embarquées (pas de Google Fonts) ; vérification des accents et du symbole « FC ».
- Imprimantes ESC/POS sans pilote Windows : option ultérieure via un module natif (`node-thermal-printer`), à valider par `testeur-materiel`.

---

## 11. Mises à jour

- `electron-updater` interroge un serveur de mises à jour (dossier HTTPS sur le serveur cloud ou GitHub Releases privé).
- Téléchargement en arrière-plan ; installation **proposée** (jamais forcée pendant une vacation) à la fermeture.
- Au redémarrage : sauvegarde → migrations → démarrage. En cas d'échec de migration : restauration automatique de la sauvegarde et retour à la version précédente avec message.
- Numéro de version affiché dans l'application et envoyé au cloud au handshake (le siège voit quelle boulangerie est à jour).

---

## 12. Construction de l'installeur

```powershell
# Sur une machine de build Windows
cd desktop
.\scripts\build-all.ps1
#   1. frontend : npm ci && npm run build  → resources\frontend\
#   2. backend  : python -m venv .venv-build ; pip install -r ..\backend\requirements.txt waitress pyinstaller
#                 python ..\backend\manage.py collectstatic --noinput
#                 pyinstaller --onedir --name kiese-server ..\backend\desktop_server.py (+ données : migrations, templates, staticfiles)
#   3. electron : npm ci && npx electron-builder --win nsis
# → dist\KIESE-Setup-<version>.exe
```
- **Signature de code** recommandée (certificat Authenticode) pour éviter les alertes SmartScreen et les faux positifs antivirus fréquents avec PyInstaller.
- Le build se fait sur Windows (PyInstaller ne fait pas de compilation croisée).
- Objectifs : installeur < 250 Mo, démarrage < 15 s sur un PC modeste (Core i3, 4 Go de RAM, disque HDD).

---

## 13. Sécurité du poste

- Backend lié **uniquement à 127.0.0.1** : inaccessible depuis le réseau de la boulangerie.
- `SECRET_KEY` et jeton de nœud propres à chaque poste, stockés via `safeStorage` (chiffrement lié au compte Windows).
- Comptes utilisateurs et mots de passe hachés synchronisés depuis le cloud ; verrouillage de session après inactivité.
- Base locale : la chaîne de hash du livre de caisse et la comparaison au cloud détectent les modifications manuelles ; chiffrement complet de la base (SQLCipher) à évaluer selon le risque.
- Journal des activités conservé localement et envoyé au cloud.

---

## 14. Plusieurs postes dans une même boulangerie (option)

Si une boulangerie a plusieurs postes (facturier A, facturier B, gérant) :
- **Option simple (recommandée au départ)** : un poste « serveur » héberge le backend ; les autres postes (ou tablettes, POS Android) ouvrent l'application dans le navigateur sur `http://<ip-du-poste>:<port>` via le réseau local. Le backend écoute alors sur l'IP locale (avec pare-feu limité au réseau local).
- Option avancée : chaque poste est un nœud et se synchronise ; plus complexe (conflits locaux), à éviter en V1.

---

## 15. Plan de réalisation

| Étape | Contenu | Agent | Vérification |
|---|---|---|---|
| D1 | `desktop_server.py` + `settings_desktop.py`, lancement Waitress, WAL | packaging-desktop | testeur-installation |
| D2 | Squelette Electron : splash, lancement/arrêt backend, chargement frontend, `apiUrl` dynamique | packaging-desktop | testeur-e2e |
| D3 | Assistant de première installation + `config.json` | packaging-desktop | testeur-installation |
| D4 | Impression silencieuse 58/80 mm | packaging-desktop + dev-frontend | testeur-materiel |
| D5 | Sauvegardes, restauration, journaux | packaging-desktop | testeur-installation |
| D6 | Intégration du service de synchronisation | architecte-sync | testeur-charge |
| D7 | Mises à jour automatiques + installeur signé | packaging-desktop | testeur-installation |
| D8 | Pilote d'un mois dans une boulangerie | coordinateur | client |

**Prérequis** : la synchronisation (`docs/architecture/SYNC.md`) doit être validée avant D6 ; les étapes D1 à D5 peuvent avancer en parallèle.

---

## 16. Points à valider avec le client

1. Système d'exploitation et caractéristiques des PC des boulangeries (Windows 10/11 ? 32 ou 64 bits ? RAM ?).
2. Nombre de postes par boulangerie et présence d'un réseau local.
3. Modèles d'imprimantes thermiques et de terminaux POS Android.
4. Hébergement du serveur cloud (l'hébergement mutualisé actuel avec Passenger ne permet ni PostgreSQL dédié ni processus de fond fiables : un VPS Linux est recommandé).
5. Achat d'un certificat de signature de code.
6. Procédure en cas de vol ou de panne d'un PC (réinstallation + resynchronisation depuis le cloud).
