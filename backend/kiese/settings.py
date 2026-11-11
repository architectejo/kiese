"""
Django settings for ETS. KIESE bakery management system.
"""

import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file (dev and production).
# NOTE: dans l'archive d'origine, `backend/.env` était un environnement virtuel
# Windows (dossier), pas un fichier de configuration. Si ce dossier existe encore,
# load_dotenv() échoue silencieusement à le lire comme fichier texte et les
# variables restent simplement absentes : c'est pour cela que `.env` doit être
# renommé `.venv` et qu'un vrai fichier `.env` (texte, voir `.env.example`)
# doit être créé à sa place. Voir BUG-007 dans docs/qa/REGISTRE_BUGS.md.
load_dotenv(BASE_DIR / '.env', override=True)

# Clé de secours utilisée uniquement en développement local (DEBUG=True).
# Ne doit JAMAIS être utilisée en production : voir le garde-fou ci-dessous.
_DEV_ONLY_SECRET_KEY = 'django-insecure-dev-key-change-in-production-kiese-2026'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', _DEV_ONLY_SECRET_KEY)

# SECURITY WARNING: don't run with debug turned on in production!
# Par défaut DEBUG=False : il faut explicitement positionner DJANGO_DEBUG=True
# dans un fichier .env local pour activer le mode développement.
DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('true', '1', 'yes')

# Garde-fou : on refuse de démarrer en dehors de DEBUG si la SECRET_KEY est
# toujours la clé de développement par défaut (clé committée dans ce fichier,
# donc publique). Voir BUG-005.
if not DEBUG and SECRET_KEY == _DEV_ONLY_SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY doit être défini via une variable d'environnement "
        "(.env) lorsque DJANGO_DEBUG=False. La clé de développement par défaut "
        "ne peut pas être utilisée en production."
    )

ALLOWED_HOSTS = os.environ.get(
    'DJANGO_ALLOWED_HOSTS',
    'localhost,127.0.0.1,api.etskiese.com,etskiese.com,www.etskiese.com'
).split(',')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    # Project apps
    'core.apps.CoreConfig',
    'clients.apps.ClientsConfig',
    'sales.apps.SalesConfig',
    'production.apps.ProductionConfig',
    'treasury.apps.TreasuryConfig',
    'commissions.apps.CommissionsConfig',
    'finance.apps.FinanceConfig',
    'blockchain.apps.BlockchainConfig',
    'sync.apps.SyncConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.OnlineOfflineRoutingMiddleware',
]

ROOT_URLCONF = 'kiese.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'kiese.wsgi.application'


# Database — SQLite for dev, PostgreSQL for production
_DB_ENGINE = os.environ.get('DB_ENGINE') or 'django.db.backends.sqlite3'

DATABASES = {
    'default': {
        # `or` (pas `.get(key, default)`) : une variable présente dans .env
        # mais laissée vide (ex. "DB_ENGINE=" en développement local, voir
        # .env.example) doit retomber sur le défaut SQLite, pas sur une
        # chaîne vide qui casse Django ("ENGINE value" manquant).
        'ENGINE': _DB_ENGINE,
        'NAME': os.environ.get('DB_NAME') or (BASE_DIR / 'db.sqlite3'),
        'USER': os.environ.get('DB_USER', ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', ''),
        'PORT': os.environ.get('DB_PORT', ''),
    }
}

# BUG-112 : sous SQLite, le pilote `sqlite3` de Python attend par défaut
# seulement 5 secondes avant de lever `OperationalError: database is
# locked` quand une autre connexion tient déjà le verrou d'écriture — bien
# trop court sous forte concurrence (ex. créations de clients simultanées,
# voir `clients/models.py::_generate_client_code`). On relève ce délai à 30
# secondes via `OPTIONS['timeout']` (clé reconnue par le wrapper sqlite3 de
# Django, transmise telle quelle à `sqlite3.connect(..., timeout=...)`).
# Ne s'applique qu'au moteur sqlite3 : une config PostgreSQL de production
# (DB_ENGINE positionné sur `django.db.backends.postgresql`) n'a pas ce
# problème (verrouillage par ligne, pas par fichier) et ne doit pas recevoir
# cette option (ignorée par le backend postgresql de toute façon, mais on
# évite de la poser pour rester explicite sur le périmètre du correctif).
if _DB_ENGINE == 'django.db.backends.sqlite3':
    DATABASES['default']['OPTIONS'] = {'timeout': 30}

    # BUG-112 (suite) : SQLite est par défaut en mode "rollback journal", qui
    # verrouille TOUTE la base pendant une écriture (même les lecteurs sont
    # bloqués) — c'est la cause principale du taux d'échec observé sous 16
    # créations concurrentes (`clients.tests.test_verification_2026_10_22`).
    # Le mode WAL (Write-Ahead Logging) autorise des lecteurs concurrents
    # pendant qu'une transaction écrit, ce qui réduit fortement les
    # verrous. `OPTIONS['init_command']` n'existe pas pour le backend
    # sqlite3 de Django (contrairement à MySQL) : il n'y a pas de hook
    # Django idiomatique pour exécuter un PRAGMA à l'ouverture de la
    # connexion autre que le signal bas niveau `connection_created`, déjà
    # utilisé pour le même motif dans `kiese/settings_desktop.py` (mode
    # desktop) — on applique ici exactement le même correctif pour le mode
    # cloud/dev afin de garder une seule façon de faire dans le projet.
    from django.db.backends.signals import connection_created

    def _set_sqlite_pragmas(sender, connection, **kwargs):
        if connection.vendor != 'sqlite':
            return
        cursor = connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA synchronous=NORMAL;')
        cursor.execute('PRAGMA busy_timeout=30000;')

    connection_created.connect(_set_sqlite_pragmas)


# Custom User Model
AUTH_USER_MODEL = 'core.User'


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'fr-cd'
TIME_ZONE = 'Africa/Kinshasa'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files (uploaded photos, etc.)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ─── Django REST Framework ──────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'kiese.pagination.DeterministicPageNumberPagination',  # BUG-172
    'PAGE_SIZE': 25,
    'PAGE_SIZE_QUERY_PARAM': 'page_size',
    'MAX_PAGE_SIZE': 500,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # BUG-006 / BUG-087 : limitation des tentatives de connexion sur
    # /api/core/auth/login/. Le throttle est appliqué explicitement sur la
    # vue de login via @throttle_classes([LoginAccountRateThrottle,
    # LoginIPRateThrottle]) (voir core/views.py::login_view et
    # core/throttling.py) — pas de limitation globale ici, pour ne pas
    # pénaliser le reste de l'API.
    #
    # - 'login' (LoginAccountRateThrottle) : clé = compte visé (username du
    #   payload). Protection anti-brute-force réelle, insensible à l'IP :
    #   plusieurs employés d'une même boulangerie connectés depuis la même
    #   IP ne se bloquent plus entre eux (BUG-087).
    # - 'login_ip' (LoginIPRateThrottle) : clé = IP, plafond plus large,
    #   garde-fou complémentaire anti credential-stuffing / énumération de
    #   comptes depuis une même source.
    'DEFAULT_THROTTLE_RATES': {
        'login': os.environ.get('DJANGO_LOGIN_THROTTLE_RATE', '5/min'),
        'login_ip': os.environ.get('DJANGO_LOGIN_IP_THROTTLE_RATE', '30/min'),
    },
}


# ─── Simple JWT ──────────────────────────────────────────────────────
# BUG-006 : durée de vie de l'access token ramenée de 12h à 30 minutes, et
# blacklist du refresh token activée après rotation (nécessite l'app
# 'rest_framework_simplejwt.token_blacklist' ci-dessus + migration).
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(
        minutes=int(os.environ.get('DJANGO_JWT_ACCESS_MINUTES', '30'))
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}


# ─── CORS ────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = os.environ.get(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://127.0.0.1:5173,https://etskiese.com,https://www.etskiese.com'
).split(',')
CORS_ALLOW_CREDENTIALS = True


# ─── DRF Spectacular (API Docs) ──────────────────────────────────────
SPECTACULAR_SETTINGS = {
    'TITLE': 'ETS. KIESE — API',
    'DESCRIPTION': 'API du système de gestion des boulangeries ETS. KIESE',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}


# ─── Sécurité HTTPS / cookies (BUG-005) ──────────────────────────────
# Actifs uniquement hors DEBUG (production). Le site est servi derrière
# Apache/Passenger ou Nginx en TLS : on fait confiance à l'en-tête
# X-Forwarded-Proto posé par ce proxy pour savoir si la requête d'origine
# était bien en HTTPS (sinon Django croit systématiquement être en HTTP et
# boucle sur la redirection).
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 'yes')
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '31536000'))  # 1 an
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True

    X_FRAME_OPTIONS = 'DENY'
else:
    # En développement local, pas de TLS : on ne force rien.
    SECURE_SSL_REDIRECT = False
    X_FRAME_OPTIONS = 'SAMEORIGIN'


# ─── ETS. KIESE Business Constants ───────────────────────────────────
KIESE_COMPANY = {
    'NAME': 'ETS. KIESE',
    'RCCM': '021 – A-650',
    'ID_NAT': '10 – F4300 -N85947U',
    'NUM_IMPOT': 'A1902266K',
    'ADDRESS': '49, Av. Tabora / Mbanza-Ngungu',
    'PHONE': '+243851992947',
    'DIRECTOR': 'NDUNGA NSAYI PIERRE',
    'CURRENCY': 'FC',
    'CURRENCY_FULL': 'Francs Congolais',
}

# Bread price grid (locked by default, editable via admin)
KIESE_BREAD_PRICES = [200, 300, 500, 1000]

# Commission rates
KIESE_COMMISSION_RATES = [0.25, 0.30]

# Annual bonus rate
KIESE_ANNUAL_BONUS_RATE = 0.025

# Bill denominations for cash counting (FC)
KIESE_BILL_DENOMINATIONS = [20000, 10000, 5000, 1000, 500, 200, 100, 50]
