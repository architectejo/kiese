"""
BUG-082 : `kiese.settings_desktop` doit autoriser l'origine `null`
(frontend Electron chargé via `file://`) et `http://127.0.0.1:<port
dynamique>` / `http://localhost:<port dynamique>` (port choisi à chaque
démarrage par `desktop/src/port.ts::findFreePort()`), SANS utiliser
`CORS_ALLOW_ALL_ORIGINS = True` (trop permissif) et SANS jamais toucher au
réglage CORS du module cloud `kiese.settings`.

Deux volets :
  1. Inspection directe de la configuration du module `kiese.settings_desktop`
     (import isolé, sans affecter les settings Django actifs du test runner).
  2. Test d'intégration via `APIClient` + `override_settings` reproduisant
     exactement les valeurs de `settings_desktop` sur les settings actifs,
     pour vérifier le comportement réel du middleware `django-cors-headers`
     (pas seulement la configuration statique).
"""
import importlib
import os
import re
import tempfile

from django.test import TestCase, override_settings
from rest_framework.test import APIClient


class DesktopSettingsCorsConfigTests(TestCase):
    """Vérifie la configuration CORS déclarée dans `kiese.settings_desktop`."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp_data_dir = tempfile.mkdtemp(prefix="kiese_desktop_cors_test_")
        # `settings_desktop` lit ces variables au niveau module : on les pose
        # juste pour cet import isolé (le module importé n'est PAS le
        # settings actif de ce test runner : `kiese.settings` reste
        # inchangé et chargé depuis le cache `sys.modules`).
        cls._env_backup = {
            k: os.environ.get(k)
            for k in ('KIESE_DATA_DIR', 'KIESE_SECRET_KEY', 'KIESE_BUNDLE_DIR')
        }
        os.environ['KIESE_DATA_DIR'] = cls._tmp_data_dir
        os.environ['KIESE_SECRET_KEY'] = 'test-secret-key-desktop-cors'
        try:
            cls.settings_desktop = importlib.import_module('kiese.settings_desktop')
        finally:
            for k, v in cls._env_backup.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_desktop_settings_do_not_use_allow_all_origins(self):
        """CORS_ALLOW_ALL_ORIGINS=True serait trop permissif même en mode
        desktop (reflèterait n'importe quelle origine, pas seulement
        null/127.0.0.1)."""
        self.assertFalse(self.settings_desktop.CORS_ALLOW_ALL_ORIGINS)

    def test_null_origin_is_explicitly_whitelisted(self):
        """`django-cors-headers` compare l'origine `null` par égalité
        stricte de chaîne dans CORS_ALLOWED_ORIGINS (pas par URL)."""
        self.assertIn('null', self.settings_desktop.CORS_ALLOWED_ORIGINS)

    def test_dynamic_localhost_port_regexes_match_expected_origins(self):
        regexes = self.settings_desktop.CORS_ALLOWED_ORIGIN_REGEXES
        self.assertTrue(regexes, "CORS_ALLOWED_ORIGIN_REGEXES ne doit pas être vide")

        def matches(origin):
            return any(re.match(p, origin) for p in regexes)

        for allowed in (
            'http://127.0.0.1:18234',
            'http://127.0.0.1:5173',
            'http://localhost:4321',
        ):
            self.assertTrue(matches(allowed), f"{allowed} devrait être autorisé")

        for forbidden in (
            'https://127.0.0.1:18234',  # schéma https refusé
            'http://127.0.0.1.evil.com:80',  # sous-domaine piégé
            'http://evil.com',
            'http://127.0.0.1:18234.evil.com',
        ):
            self.assertFalse(matches(forbidden), f"{forbidden} ne doit pas être autorisé")

    def test_cloud_settings_module_untouched(self):
        """Le réglage cloud (`kiese.settings`) ne doit jamais devenir
        permissif à cause de cette correction desktop."""
        from kiese import settings as cloud_settings

        self.assertFalse(getattr(cloud_settings, 'CORS_ALLOW_ALL_ORIGINS', False))
        self.assertNotIn('null', cloud_settings.CORS_ALLOWED_ORIGINS)
        self.assertEqual(getattr(cloud_settings, 'CORS_ALLOWED_ORIGIN_REGEXES', []), [])


@override_settings(
    CORS_ALLOW_ALL_ORIGINS=False,
    CORS_ALLOWED_ORIGINS=['null'],
    CORS_ALLOWED_ORIGIN_REGEXES=[
        r'^http://127\.0\.0\.1:\d+$',
        r'^http://localhost:\d+$',
    ],
    CORS_ALLOW_CREDENTIALS=True,
)
class DesktopCorsMiddlewareBehaviorTests(TestCase):
    """Reproduit exactement les valeurs de `settings_desktop` sur les
    settings Django actifs pour vérifier le comportement réel du
    middleware `django-cors-headers` (et pas seulement la configuration
    statique) sur un vrai endpoint de l'API."""

    def setUp(self):
        self.client = APIClient()

    def test_null_origin_is_accepted_with_cors_headers(self):
        response = self.client.get('/api/schema/', HTTP_ORIGIN='null')
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), 'null')
        self.assertEqual(response.headers.get('Access-Control-Allow-Credentials'), 'true')

    def test_dynamic_port_localhost_origin_is_accepted(self):
        response = self.client.get('/api/schema/', HTTP_ORIGIN='http://127.0.0.1:52341')
        self.assertEqual(
            response.headers.get('Access-Control-Allow-Origin'),
            'http://127.0.0.1:52341',
        )

    def test_unrelated_origin_is_still_rejected(self):
        """La correction ne doit pas ouvrir le CORS à n'importe quelle
        origine : seules null/127.0.0.1/localhost sont concernées."""
        response = self.client.get('/api/schema/', HTTP_ORIGIN='https://attacker.example')
        self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
