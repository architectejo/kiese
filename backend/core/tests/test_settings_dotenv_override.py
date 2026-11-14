"""Le .env ne doit jamais ecraser une variable d'environnement deja definie."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from dotenv import dotenv_values

BASE = Path(settings.BASE_DIR)
SNIPPET = (
    "import os, django.conf as c; os.environ['DJANGO_SETTINGS_MODULE']='kiese.settings';"
    "s=c.settings; print(s.DATABASES['default']['NAME']); print(os.environ.get('DJANGO_HSTS_SECONDS',''))"
)


def _run(extra_env, drop=()):
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(extra_env)
    out = subprocess.run([sys.executable, '-c', SNIPPET], cwd=BASE, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout.splitlines()


class DotenvOverrideTests(SimpleTestCase):
    def test_variable_d_environnement_prime_sur_dotenv(self):
        iso = str(Path(tempfile.gettempdir()) / 'kiese_isolated_test.sqlite3')
        name, _ = _run({'DB_NAME': iso, 'DJANGO_HSTS_SECONDS': '123'})
        self.assertEqual(name, iso)

    def test_dotenv_reste_lu_quand_la_variable_n_est_pas_definie(self):
        values = dotenv_values(BASE / '.env') if (BASE / '.env').is_file() else {}
        if not values.get('DJANGO_HSTS_SECONDS'):
            self.skipTest("DJANGO_HSTS_SECONDS absent du .env local")
        _, hsts = _run({}, drop=('DJANGO_HSTS_SECONDS',))
        self.assertEqual(hsts, values['DJANGO_HSTS_SECONDS'])
