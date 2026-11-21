"""
Verification testeur-installation (2026-11-21, ronde B) : BUG-071, BUG-073,
BUG-082. Tests independants de ceux de packaging-desktop / dev-frontend.

- CORS : le vrai middleware django-cors-headers est interroge avec des
  reglages lus dans `kiese.settings_desktop` (sous-processus isole).
- Settings : un sous-processus importe `kiese.settings_desktop` avec un
  faux `.env` hostile (DB_NAME vide, DJANGO_SECRET_KEY piegee), en
  interceptant `dotenv.load_dotenv` pour viser ce faux fichier, et verifie
  que les variables posees avant `django.setup()` ne sont pas ecrasees.
- BUG-073 : code de sortie 2 sur echec de migration, via desktop_server.
"""
import importlib.util
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

BASE = Path(settings.BASE_DIR)


def _desktop_cors_settings():
    """Lit les reglages CORS de settings_desktop dans un process isole."""
    tmp = tempfile.mkdtemp(prefix='kiese_ti_cors_')
    code = (
        "import os, json;"
        "os.environ['DJANGO_SETTINGS_MODULE']='kiese.settings_desktop';"
        "import kiese.settings_desktop as s;"
        "print(json.dumps({'all':s.CORS_ALLOW_ALL_ORIGINS,'origins':s.CORS_ALLOWED_ORIGINS,"
        "'regex':s.CORS_ALLOWED_ORIGIN_REGEXES,'cred':s.CORS_ALLOW_CREDENTIALS}))"
    )
    env = dict(os.environ, KIESE_DATA_DIR=tmp, KIESE_SECRET_KEY='k' * 50,
               DJANGO_DEBUG='False', DJANGO_SECRET_KEY='k' * 50)
    out = subprocess.run([sys.executable, '-c', code], cwd=BASE, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


_CFG = _desktop_cors_settings()


@override_settings(
    CORS_ALLOW_ALL_ORIGINS=_CFG['all'],
    CORS_ALLOWED_ORIGINS=_CFG['origins'],
    CORS_ALLOWED_ORIGIN_REGEXES=_CFG['regex'],
    CORS_ALLOW_CREDENTIALS=_CFG['cred'],
)
class BUG082CorsTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def _resp(self, origin, preflight=False):
        kw = {'HTTP_ORIGIN': origin}
        if preflight:
            kw['HTTP_ACCESS_CONTROL_REQUEST_METHOD'] = 'POST'
            kw['HTTP_ACCESS_CONTROL_REQUEST_HEADERS'] = 'authorization,content-type'
            return self.c.options('/api/schema/', **kw)
        return self.c.get('/api/schema/', **kw)

    def test_origine_null_file_acceptee(self):
        r = self._resp('null')
        self.assertEqual(r.headers.get('Access-Control-Allow-Origin'), 'null')
        self.assertEqual(r.headers.get('Access-Control-Allow-Credentials'), 'true')

    def test_port_dynamique_127_et_localhost(self):
        for port in (1024, 18234, 49152, 65535):
            for host in ('127.0.0.1', 'localhost'):
                o = f'http://{host}:{port}'
                self.assertEqual(self._resp(o).headers.get('Access-Control-Allow-Origin'), o)

    def test_preflight_autorise_authorization(self):
        r = self._resp('null', preflight=True)
        self.assertEqual(r.headers.get('Access-Control-Allow-Origin'), 'null')
        self.assertIn('authorization', r.headers.get('Access-Control-Allow-Headers', '').lower())

    def test_origines_etrangeres_refusees(self):
        for o in ('https://evil.example', 'http://evil.example:18234',
                  'http://127.0.0.1.evil.com:80', 'http://127.0.0.1:80@evil.com',
                  'https://127.0.0.1:18234', 'http://127.0.0.1', 'http://localhost.evil.com:1',
                  'http://192.168.1.10:18234', 'file://'):
            self.assertIsNone(self._resp(o).headers.get('Access-Control-Allow-Origin'), o)

    def test_pas_de_wildcard(self):
        self.assertFalse(_CFG['all'])
        self.assertNotIn('*', _CFG['origins'])

    def test_cloud_settings_n_acceptent_pas_null(self):
        out = subprocess.run(
            [sys.executable, '-c',
             "import os;os.environ['DJANGO_SETTINGS_MODULE']='kiese.settings';"
             "import kiese.settings as s;print('null' in s.CORS_ALLOWED_ORIGINS)"],
            cwd=BASE, env=dict(os.environ, DJANGO_DEBUG='True'),
            capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip().splitlines()[-1], 'False', out.stderr)


_HOSTILE_ENV_SNIPPET = (
    "import os, json, dotenv\n"
    "env_file = os.environ['FAKE_DOTENV']\n"
    "_orig = dotenv.load_dotenv\n"
    "dotenv.load_dotenv = lambda *a, **k: _orig(env_file, **{kk: vv for kk, vv in k.items() if kk != 'dotenv_path'})\n"
    "os.environ['DJANGO_SETTINGS_MODULE'] = 'kiese.settings_desktop'\n"
    "import kiese.settings_desktop as s\n"
    "print(json.dumps({'name': s.DATABASES['default']['NAME'], 'key': s.SECRET_KEY, 'debug': s.DEBUG}))\n"
)


class BUG071DotenvTests(SimpleTestCase):
    def _run(self, dotenv_text, extra):
        d = tempfile.mkdtemp(prefix='kiese_ti_env_')
        fake = Path(d) / '.env'
        if dotenv_text is not None:
            fake.write_text(dotenv_text, encoding='utf-8')
        data_dir = Path(d) / 'data'
        data_dir.mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('DB_', 'DJANGO_', 'KIESE_'))}
        env.update({'FAKE_DOTENV': str(fake), 'KIESE_DATA_DIR': str(data_dir),
                    'KIESE_SECRET_KEY': 'poste-secret-' + 'x' * 40,
                    'DJANGO_SECRET_KEY': 'poste-secret-' + 'x' * 40,
                    'DJANGO_DEBUG': 'False',
                    'DB_NAME': str(data_dir / 'kiese.sqlite3')})
        env.update(extra)
        out = subprocess.run([sys.executable, '-c', _HOSTILE_ENV_SNIPPET], cwd=BASE, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip().splitlines()[-1]), data_dir

    def test_dotenv_hostile_n_ecrase_ni_db_ni_secret(self):
        res, data_dir = self._run(
            'DB_NAME=\nDJANGO_SECRET_KEY=cle-exposee-du-depot\nDJANGO_DEBUG=True\n', {})
        self.assertEqual(res['name'], str(data_dir / 'kiese.sqlite3'))
        self.assertTrue(res['key'].startswith('poste-secret-'))
        self.assertFalse(res['debug'])

    def test_dotenv_pointant_vers_autre_base(self):
        res, data_dir = self._run('DB_NAME=C:/dev/db.sqlite3\n', {})
        self.assertEqual(res['name'], str(data_dir / 'kiese.sqlite3'))

    def test_sans_dotenv(self):
        res, data_dir = self._run(None, {})
        self.assertEqual(res['name'], str(data_dir / 'kiese.sqlite3'))
        self.assertTrue(res['key'].startswith('poste-secret-'))

    def test_secret_desktop_ne_depend_que_de_kiese_secret_key(self):
        res, _ = self._run('DJANGO_SECRET_KEY=autre\n',
                           {'DJANGO_SECRET_KEY': 'autre-' + 'y' * 40})
        self.assertTrue(res['key'].startswith('poste-secret-'))

    def test_settings_cloud_dotenv_sans_override(self):
        src = (BASE / 'kiese' / 'settings.py').read_text(encoding='utf-8')
        self.assertIn('override=False', src)
        self.assertNotIn('override=True,', src)


def _load_desktop_server(name):
    spec = importlib.util.spec_from_file_location(name, BASE / 'desktop_server.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MIG_SNIPPET = (
    "import sys, os, argparse\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import desktop_server as ds\n"
    "from pathlib import Path\n"
    "data = Path(sys.argv[1])\n"
    "def boom(*a, **k): raise RuntimeError('migration simulee en echec')\n"
    "ds._apply_migrations = boom\n"
    "sys.argv = ['x', '--port', '1', '--data-dir', str(data)]\n"
    "ds.main()\n"
    "print('ATTEINT_NE_DEVRAIT_PAS')\n"
)


class BUG073MigrationExitCodeTests(SimpleTestCase):
    def test_code_sortie_2_sur_echec_de_migration(self):
        d = Path(tempfile.mkdtemp(prefix='kiese_ti_mig_'))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('DB_', 'KIESE_', 'DJANGO_SETTINGS'))}
        env.update({'KIESE_SECRET_KEY': 's' * 50, 'PYTHONIOENCODING': 'utf-8'})
        out = subprocess.run([sys.executable, '-c', _MIG_SNIPPET, str(d)], cwd=BASE, env=env,
                             capture_output=True, text=True, timeout=180)
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertNotIn('ATTEINT_NE_DEVRAIT_PAS', out.stdout)
        log = (d / 'logs' / 'backend.log').read_text(encoding='utf-8')
        self.assertIn('Administration', log)

    def test_code_sortie_aligne_avec_electron(self):
        ts = (BASE.parent / 'desktop' / 'src' / 'backend.ts').read_text(encoding='utf-8')
        self.assertIn('MIGRATION_FAILED_EXIT_CODE = 2', ts)
        self.assertEqual(_load_desktop_server('ds_probe').MIGRATION_FAILED_EXIT_CODE, 2)

    def test_sauvegarde_pre_migration_creee_et_marquee(self):
        mod = _load_desktop_server('ds_probe2')
        d = Path(tempfile.mkdtemp(prefix='kiese_ti_bak_'))
        db = d / 'kiese.sqlite3'
        c = sqlite3.connect(db)
        c.execute('create table t(x)')
        c.execute('insert into t values (42)')
        c.commit()
        c.close()
        bk = d / 'backups'
        lg = logging.getLogger('ti')
        path = mod.backup_database(db, bk, lg)
        self.assertTrue(path and path.exists())
        mod._mark_pre_migration_backup(bk, path, lg)
        self.assertEqual((bk / '.last_pre_migration_backup').read_text(encoding='utf-8'), path.name)
