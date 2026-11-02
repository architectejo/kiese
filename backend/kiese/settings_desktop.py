"""
Réglages Django spécifiques au poste desktop (Electron + PyInstaller),
docs/architecture/DESKTOP.md §6.

IMPORTANT : les variables sensibles (SECRET_KEY réelle, jeton de nœud) ne
sont PAS lues ici depuis `config.json` — elles sont injectées par
`desktop_server.py` dans l'environnement du processus (`DJANGO_SECRET_KEY`,
`KIESE_NODE_TOKEN`, ...) **avant** l'import de `kiese.settings`, de sorte que
`from .settings import *` ci-dessous voit déjà les bonnes valeurs sans
qu'aucun secret ne transite par ce module ni par un fichier en clair lu par
Django lui-même (Electron se charge seul du déchiffrement `safeStorage`,
voir `desktop/src/backend.ts`).
"""

import logging.handlers
import os
from pathlib import Path

from django.db.backends.signals import connection_created

from .settings import *  # noqa: F401,F403

# ─── Dossiers du poste ────────────────────────────────────────────────
# Renseignés par desktop_server.py avant `django.setup()`.
DATA_DIR = Path(os.environ['KIESE_DATA_DIR'])
BUNDLE_DIR = Path(os.environ.get('KIESE_BUNDLE_DIR', BASE_DIR))  # noqa: F405

DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

# ─── Réaffirmation explicite de SECRET_KEY / DATABASES ────────────────
# CRITIQUE : `kiese.settings` appelle `load_dotenv(BASE_DIR / '.env',
# override=True)` — si un fichier `.env` est présent à côté de l'exécutable
# PyInstaller (il ne devrait jamais l'être, voir `desktop/scripts/
# build-backend.ps1` qui l'exclut explicitement), ses valeurs écraseraient
# silencieusement les variables posées par `desktop_server.py` avant
# `django.setup()` — confirmé empiriquement : `DB_NAME=""` dans le `.env` de
# développement de ce dépôt fait retomber `kiese.settings` sur
# `BASE_DIR / 'db.sqlite3'` (la base de DÉVELOPPEMENT, pas celle du poste)
# malgré un `DB_NAME` valide déjà présent dans l'environnement du process.
# Le même risque existe pour `SECRET_KEY` (voir BUG connu #7, CLAUDE.md §6 :
# `.env.production` contient une clé à traiter comme exposée). On réaffirme
# donc ici, après l'import de `kiese.settings`, les deux valeurs qui ne
# doivent jamais dépendre d'un `.env` en mode desktop.
SECRET_KEY = os.environ['KIESE_SECRET_KEY']
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(DATA_DIR / 'kiese.sqlite3'),
        'USER': '',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
        'OPTIONS': {'timeout': 20},
    }
}

MEDIA_ROOT = DATA_DIR / 'media'
# `collectstatic` est fait au moment du build (DESKTOP.md §12), pas à chaque
# démarrage : STATIC_ROOT pointe donc vers le dossier déjà construit et
# empaqueté par PyInstaller, à côté de l'exécutable, pas vers DATA_DIR.
STATIC_ROOT = BUNDLE_DIR / 'staticfiles'

# ─── Sécurité réseau : aucune exposition hors 127.0.0.1 ───────────────
# `kiese.settings` active HSTS/redirection HTTPS/cookies sécurisés dès que
# DEBUG=False (BUG-005) : pertinent pour le Cloud derrière TLS, inutile et
# contre-productif ici (Waitress en clair sur boucle locale uniquement,
# DESKTOP.md §13 — jamais exposé au réseau de la boulangerie).
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = 'SAMEORIGIN'

# ─── CORS (BUG-082) ────────────────────────────────────────────────────
# Le frontend desktop est chargé par Electron via `file://` : le navigateur
# envoie alors l'en-tête `Origin: null` (origine opaque). Le backend local
# packagé écoute sur `127.0.0.1:<port>` où `<port>` est choisi dynamiquement
# à chaque démarrage par `desktop/src/port.ts::findFreePort()` : il ne peut
# donc pas figurer dans une liste statique comme `CORS_ALLOWED_ORIGINS`
# (c'est le cas en mode cloud, voir `kiese.settings`).
#
# On n'utilise PAS `CORS_ALLOW_ALL_ORIGINS = True` (trop permissif, même ici :
# cela reflèterait aveuglément N'IMPORTE QUELLE origine, y compris celle
# d'une page web distante ouverte par erreur dans le même navigateur/poste) :
# on autorise explicitement seulement les deux formes attendues en mode
# desktop :
#   1. L'origine littérale `null` (`file://`), via `CORS_ALLOWED_ORIGINS`
#      — `django-cors-headers` compare `null` par égalité stricte de chaîne,
#      pas comme une URL (`corsheaders/middleware.py::origin_found_in_white_lists`).
#   2. `http://127.0.0.1:<port>` et `http://localhost:<port>`, port
#      quelconque, via `CORS_ALLOWED_ORIGIN_REGEXES` (regex ancrée, un seul
#      hôte autorisé, pas un domaine générique).
#
# Pourquoi c'est sûr en mode desktop uniquement (jamais repris par
# `kiese.settings`, le module cloud) : Waitress n'écoute que sur
# `127.0.0.1` (DESKTOP.md §13), jamais exposé au réseau de la boulangerie ni
# à Internet — seul un processus tournant SUR CE MÊME POSTE peut présenter
# une origine `null` ou `127.0.0.1:<port>` à ce serveur. Le risque résiduel
# (un logiciel malveillant déjà exécuté sur le poste) existe indépendamment
# de ce réglage CORS et n'est pas aggravé par lui.
#
# Limite connue sur les identifiants/cookies : certains navigateurs (dont
# Chromium/Electron) refusent d'envoyer des cookies vers/depuis une origine
# `null` même quand `Access-Control-Allow-Credentials: true` est renvoyé.
# Sans impact ici : l'app n'utilise pas de cookies de session pour l'auth —
# le JWT est envoyé en en-tête `Authorization: Bearer <token>` depuis
# `localStorage` (`frontend/src/api/client.ts`), et aucun appel Axios ne
# positionne `withCredentials`. `CORS_ALLOW_CREDENTIALS = True` reste réglé
# ci-dessous uniquement pour cohérence avec le mode cloud ; il n'est pas
# requis par le flux d'authentification actuel.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = ['null']
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^http://127\.0\.0\.1:\d+$',
    r'^http://localhost:\d+$',
]
CORS_ALLOW_CREDENTIALS = True

# ─── Identité du nœud / synchronisation ───────────────────────────────
KIESE_DATA_DIR = str(DATA_DIR)
KIESE_NODE_CODE = os.environ.get('KIESE_NODE_CODE', '')
KIESE_CLOUD_URL = os.environ.get('KIESE_CLOUD_URL', '')
KIESE_NODE_TOKEN = os.environ.get('KIESE_NODE_TOKEN', '')
KIESE_APP_VERSION = os.environ.get('KIESE_APP_VERSION', '0.0.0')

# ─── Journalisation (DESKTOP.md §8 : logs/backend.log, rotation 10×5 Mo) ──
LOG_DIR = DATA_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'},
    },
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'backend.log'),
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 10,
            'encoding': 'utf-8',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {'handlers': ['file'], 'level': 'INFO', 'propagate': False},
    },
}


# ─── Mode WAL SQLite (DESKTOP.md §3.3/§6) ──────────────────────────────
# `OPTIONS['init_command']` n'existe pas pour le moteur sqlite3 de Django :
# on applique les PRAGMA à chaque connexion via ce signal, comme prévu par
# la note du document d'architecture.
def _set_sqlite_pragmas(sender, connection, **kwargs):
    if connection.vendor != 'sqlite':
        return
    cursor = connection.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    cursor.execute('PRAGMA busy_timeout=5000;')


connection_created.connect(_set_sqlite_pragmas)
