"""BUG-284 : changement de mot de passe obligatoire (dev-backend, 2026-11-14)."""
from rest_framework.test import APIClient

from core.models import ActivityLog, User
from core.testing import make_user
from core.tests.test_permissions import BaseNodeTestCase

STRONG = "Nouveau-mdp-9Zx!"
ME = "/api/core/auth/me/"
CHG = "/api/core/auth/change-password/"


class MustChangePasswordTests(BaseNodeTestCase):
    def test_default_is_false_and_exposed_read_only(self):
        self.assertFalse(self.gerant_k1.must_change_password)
        c = self.client_as(self.gerant_k1)
        self.assertIs(c.get(ME).json()["must_change_password"], False)
        c.patch(ME, {"must_change_password": True}, format="json")
        self.gerant_k1.refresh_from_db()
        self.assertFalse(self.gerant_k1.must_change_password)

    def test_login_exposes_flag(self):
        make_user("GERANT", node=self.k1, username="b284_login", password="test-pass-123")
        r = APIClient().post("/api/core/auth/login/",
                             {"username": "b284_login", "password": "test-pass-123"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.json()["user"]["must_change_password"], False)

    def test_reset_password_sets_flag(self):
        r = self.client_as(self.direction).post(
            f"/api/core/users/{self.gerant_k1.pk}/reset_password/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.gerant_k1.refresh_from_db()
        self.assertTrue(self.gerant_k1.must_change_password)

    def test_admin_created_account_has_flag(self):
        r = self.client_as(self.admin).post("/api/core/users/", {
            "username": "b284_new", "password": "Temp-pass-77x", "role": "FACTURIER",
            "node": str(self.k1.pk), "team": "A"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(User.objects.get(username="b284_new").must_change_password)

    def test_business_api_blocked_while_flag_true(self):
        User.objects.filter(pk=self.gerant_k1.pk).update(must_change_password=True)
        c = self.client_as(self.gerant_k1)
        for url in ("/api/clients/clients/", "/api/sales/invoices/", "/api/core/nodes/"):
            r = c.get(url)
            self.assertEqual(r.status_code, 403, url)
            self.assertEqual(r.json()["code"], "password_change_required")

    def test_exempt_endpoints_still_reachable(self):
        User.objects.filter(pk=self.gerant_k1.pk).update(must_change_password=True)
        c = self.client_as(self.gerant_k1)
        self.assertEqual(c.get(ME).status_code, 200)
        self.assertEqual(c.post("/api/core/auth/logout/", {}, format="json").status_code, 200)

    def test_refresh_still_works_while_flag_true(self):
        u = make_user("GERANT", node=self.k1, username="b284_ref", password="test-pass-123")
        r = APIClient().post("/api/core/auth/login/",
                             {"username": "b284_ref", "password": "test-pass-123"}, format="json")
        refresh = r.json()["refresh"]
        User.objects.filter(pk=u.pk).update(must_change_password=True)
        r2 = APIClient().post("/api/core/auth/login/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(r2.status_code, 200)

    def test_change_password_clears_flag_and_unblocks(self):
        u = make_user("GERANT", node=self.k1, username="b284_chg", password="test-pass-123")
        User.objects.filter(pk=u.pk).update(must_change_password=True)
        c = self.client_as(u)
        r = c.post(CHG, {"old_password": "test-pass-123", "new_password": STRONG}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        u.refresh_from_db()
        self.assertFalse(u.must_change_password)
        self.assertTrue(u.check_password(STRONG))
        self.assertEqual(c.get("/api/clients/clients/").status_code, 200)
        for log in ActivityLog.objects.all():
            self.assertNotIn(STRONG, log.description)

    def test_change_password_wrong_old_weak_or_same(self):
        u = make_user("GERANT", node=self.k1, username="b284_bad", password="test-pass-123")
        User.objects.filter(pk=u.pk).update(must_change_password=True)
        c = self.client_as(u)
        r = c.post(CHG, {"old_password": "faux", "new_password": STRONG}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("detail", r.json())
        r = c.post(CHG, {"old_password": "test-pass-123", "new_password": "12345678"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("detail", r.json())
        r = c.post(CHG, {"old_password": "test-pass-123", "new_password": "test-pass-123"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = c.post(CHG, {"old_password": "test-pass-123"}, format="json")
        self.assertEqual(r.status_code, 400)
        u.refresh_from_db()
        self.assertTrue(u.must_change_password)
        self.assertTrue(u.check_password("test-pass-123"))

    def test_me_patch_password_also_validated_and_clears_flag(self):
        u = make_user("GERANT", node=self.k1, username="b284_patch", password="test-pass-123")
        User.objects.filter(pk=u.pk).update(must_change_password=True)
        c = self.client_as(u)
        r = c.patch(ME, {"old_password": "test-pass-123", "new_password": "123"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = c.patch(ME, {"old_password": "test-pass-123", "new_password": STRONG}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        u.refresh_from_db()
        self.assertFalse(u.must_change_password)

    def test_cleanup_expired_reserved_to_gerant_and_above(self):
        url = "/api/sales/invoices/cleanup_expired/"
        self.assertEqual(self.client_as(self.facturier_k1).post(url).status_code, 403)
        self.assertEqual(self.client_as(self.livreur_k1).post(url).status_code, 403)
        self.assertEqual(self.client_as(self.gerant_k1).post(url).status_code, 200)
