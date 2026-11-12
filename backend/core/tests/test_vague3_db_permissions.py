"""
Non-régression de la matrice de droits sur les routes modifiées par les
correctifs BUG-247 à BUG-256, BUG-259, BUG-263, BUG-265 (testeur-permissions,
vague 3 sur base réelle, 2026-11-12).

Un test paramétré par (route, méthode, rôle). Les routes de détail sont
appelées avec un UUID nul : 403 = refus de rôle, 404 = rôle admis (objet
inexistant). Aucune donnée réelle : base de test éphémère.
"""

from core.tests.test_permissions import BaseNodeTestCase

NIL = "00000000-0000-0000-0000-000000000000"
ROLES = ("anon", "ADMIN", "DIRECTION", "COMPTABLE", "GERANT", "FACTURIER", "LIVREUR")
DIRECTION_UP = {"ADMIN", "DIRECTION"}
HQ = {"ADMIN", "DIRECTION", "COMPTABLE"}
GERANT_UP = HQ | {"GERANT"}
ALL = set(ROLES) - {"anon"}

# (route, méthode, corps, rôles admis, statuts attendus pour un rôle admis, ticket)
MATRIX = [
    # core/users : écriture ADMIN/DIRECTION (BUG-247/248)
    ("/api/core/users/{NIL}/", "PATCH", {}, DIRECTION_UP, (404,), "BUG-247"),
    ("/api/core/users/{NIL}/", "DELETE", None, DIRECTION_UP, (404,), "BUG-247"),
    ("/api/core/users/{NIL}/reset_password/", "POST", {}, DIRECTION_UP, (404,), "BUG-248"),
    ("/api/core/users/", "POST", {}, DIRECTION_UP, (400,), "BUG-247"),
    # clients : écriture gérant+, création facturier (BUG-250/259)
    ("/api/clients/clients/{NIL}/", "PATCH", {}, GERANT_UP, (404,), "BUG-259"),
    ("/api/clients/clients/{NIL}/", "DELETE", None, GERANT_UP, (404,), "BUG-259"),
    ("/api/clients/clients/", "POST", {}, GERANT_UP | {"FACTURIER"}, (400,), "BUG-250"),
    # caisse sociale : écriture gérant+ (BUG-249/254)
    ("/api/clients/contributions/", "POST", {}, GERANT_UP, (400,), "BUG-249"),
    ("/api/clients/contributions/bulk_create_month/", "POST", {}, GERANT_UP, (400, 403), "BUG-249"),
    ("/api/clients/distribution-lines/", "POST", {}, GERANT_UP, (400,), "BUG-254"),
    # commissions (BUG-263/265)
    ("/api/commissions/commissions/{NIL}/mark_paid/", "POST", {}, DIRECTION_UP, (404,), "BUG-265"),
    ("/api/commissions/commissions/{NIL}/set_manuel/", "PATCH", {}, DIRECTION_UP, (404,), "BUG-265"),
    ("/api/commissions/commissions/{NIL}/", "PATCH", {}, HQ, (404,), "BUG-263"),
    ("/api/commissions/commissions/{NIL}/", "DELETE", None, HQ, (404,), "BUG-263"),
    ("/api/commissions/periods/{NIL}/", "DELETE", None, HQ, (404,), "BUG-263"),
    # stocks de consommables : écriture gérant+ (BUG-251)
    ("/api/production/stocks/{NIL}/", "PATCH", {}, GERANT_UP, (404,), "BUG-251"),
    ("/api/production/stocks/{NIL}/", "DELETE", None, GERANT_UP, (404,), "BUG-251"),
    ("/api/production/stocks/", "POST", {}, GERANT_UP, (400,), "BUG-251"),
    # notifications (BUG-252) : tout authentifié atteint la route (404 sur UUID nul)
    ("/api/core/notifications/{NIL}/", "DELETE", None, ALL, (404,), "BUG-252"),
    ("/api/core/notifications/{NIL}/mark_read/", "POST", {}, ALL, (404,), "BUG-252"),
    # config : écriture siège direction (BUG-255)
    ("/api/core/config/", "PATCH", {}, DIRECTION_UP, (200,), "BUG-255"),
]

# (route, rôles autorisés en lecture) ; anonyme : 401 ; autre rôle : 403.
READS = [
    ("/api/core/users/", HQ),
    ("/api/clients/clients/", ALL),
    ("/api/clients/contributions/", GERANT_UP),
    ("/api/commissions/commissions/", ALL),
    ("/api/commissions/periods/", ALL),
    ("/api/production/stocks/", ALL),
    ("/api/core/notifications/", ALL),
]


class Vague3MatrixNonRegressionTests(BaseNodeTestCase):
    def _client(self, role):
        from rest_framework.test import APIClient
        if role == "anon":
            return APIClient()
        user = {
            "ADMIN": self.admin, "DIRECTION": self.direction, "COMPTABLE": self.comptable,
            "GERANT": self.gerant_k1, "FACTURIER": self.facturier_k1, "LIVREUR": self.livreur_k1,
        }[role]
        return self.client_as(user)

    def test_write_matrix(self):
        for route, method, body, allowed, ok_statuses, ticket in MATRIX:
            url = route.replace("{NIL}", NIL)
            for role in ROLES:
                with self.subTest(route=route, method=method, role=role, ticket=ticket):
                    c = self._client(role)
                    kwargs = {"format": "json"} if body is not None else {}
                    r = getattr(c, method.lower())(url, *( [body] if body is not None else [] ), **kwargs)
                    if role == "anon":
                        self.assertEqual(r.status_code, 401, r.content)
                    elif role in allowed:
                        self.assertIn(r.status_code, ok_statuses, (role, r.status_code, r.content))
                    else:
                        self.assertEqual(r.status_code, 403, (role, r.status_code, r.content))

    def test_read_matrix(self):
        for url, allowed in READS:
            for role in ROLES:
                with self.subTest(route=url, role=role):
                    r = self._client(role).get(url)
                    expected = 401 if role == "anon" else (200 if role in allowed else 403)
                    self.assertEqual(r.status_code, expected, (role, r.status_code))

    def test_anonymous_config_is_on_line_only(self):
        r = self._client("anon").get("/api/core/config/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.json()), ["on_line"])

    def test_anonymous_bread_prices_public(self):
        self.assertEqual(self._client("anon").get("/api/core/bread-prices/").status_code, 200)

    def test_direction_self_patch_ignores_superuser_and_staff(self):
        c = self.client_as(self.direction)
        c.patch(f"/api/core/users/{self.direction.pk}/", {"is_superuser": True, "is_staff": True}, format="json")
        self.direction.refresh_from_db()
        self.assertFalse(self.direction.is_superuser)
        self.assertFalse(self.direction.is_staff)
        self.assertEqual(self.direction.role, "DIRECTION")
