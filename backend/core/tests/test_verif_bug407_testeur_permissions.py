"""
Verification de BUG-407 (gardes de role des routes d'administration du frontend), testeur-permissions, 2026-11-21d-b.

Test statique, sans navigateur : extrait de `frontend/src/App.tsx` la table route -> roles (`isAllowed`) et de
`DashboardLayout.tsx` la table menu -> roles, puis les compare entre elles et avec les permissions backend reelles
(`core/views.py` : ActivityLogViewSet = IsHeadquarters ; Node/User/Config ecritures = IsDirection).
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
APP = (ROOT / 'frontend/src/App.tsx').read_text(encoding='utf-8')
LAYOUT = (ROOT / 'frontend/src/components/layout/DashboardLayout.tsx').read_text(encoding='utf-8')

ROLES = ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR']
HQ = ['ADMIN', 'DIRECTION', 'COMPTABLE']  # User.is_headquarters


def routes_app():
    """path -> liste de roles autorises (None = tout utilisateur authentifie)."""
    out = {}
    for m in re.finditer(r'path="([^"]+)"\s*(?:\{/\*.*?\*/\}|//[^\n]*|\s)*element=\{(.*?)</ProtectedRoute>', APP, re.S):
        path, block = m.group(1), m.group(2)
        a = re.search(r'isAllowed=\{\(u\) => (.*?)\}>', block, re.S)
        if not a:
            out[path] = None
        elif 'is_headquarters' in a.group(1):
            out[path] = HQ
        else:
            out[path] = re.findall(r"'([A-Z]+)'", a.group(1))
    return out


def menu():
    return {
        m.group(1): re.findall(r"'([A-Z]+)'", m.group(2))
        for m in re.finditer(r"\{ to: '([^']+)'.*?roles: \[(.*?)\] \}", LAYOUT)
    }


class Bug407RouteGuardsTests(SimpleTestCase):
    def test_quatre_routes_gardees_comme_le_menu_et_l_api(self):
        app, nav = routes_app(), menu()
        attendu = {
            '/admin/nodes': ['ADMIN', 'DIRECTION'],
            '/admin/users': ['ADMIN', 'DIRECTION'],
            '/settings': ['ADMIN', 'DIRECTION'],
            '/activities': HQ,  # ActivityLogViewSet.permission_classes = [IsHeadquarters]
        }
        for path, roles in attendu.items():
            with self.subTest(path=path):
                self.assertEqual(sorted(app[path] or []), sorted(roles))
                self.assertEqual(sorted(nav[path]), sorted(roles))

    def test_toutes_les_routes_gardees_sont_coherentes_avec_le_menu(self):
        app, nav = routes_app(), menu()
        for path, roles in app.items():
            if roles is None or path not in nav:
                continue
            if path == '/dashboard':
                # BUG-1115 : page d'atterrissage apres connexion (FACTURIER/LIVREUR y arrivent) ;
                # la garde peut etre plus ouverte que le menu, jamais plus restreinte.
                with self.subTest(path=path):
                    self.assertTrue(set(nav[path]) <= set(roles))
                continue
            with self.subTest(path=path):
                self.assertEqual(sorted(roles), sorted(nav[path]))

    def test_table_role_route_admin(self):
        app = routes_app()
        for path in ('/admin/nodes', '/admin/users', '/settings', '/activities', '/admin/backups'):
            for role in ROLES:
                with self.subTest(path=path, role=role):
                    autorise = role in (app[path] or ROLES)
                    if path == '/activities':
                        self.assertEqual(autorise, role in HQ)
                    else:
                        self.assertEqual(autorise, role in ('ADMIN', 'DIRECTION'))

    def test_noms_de_roles_valides(self):
        from core.models import User
        valides = {c for c, _ in User.Role.choices}
        for roles in list(menu().values()) + [r for r in routes_app().values() if r]:
            self.assertTrue(set(roles) <= valides)

    def test_protectedroute_ne_rend_pas_les_enfants_avant_refus(self):
        """Les enfants (donc leurs requetes API) ne sont montes qu'apres `checked` et `isAllowed`."""
        i_wait = APP.index('if (isLoading || !checked)')
        i_deny = APP.index('<AccessDenied />')
        i_ok = APP.index('<DashboardLayout>{children}</DashboardLayout>')
        self.assertTrue(i_wait < i_deny < i_ok)
