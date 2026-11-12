"""
Non-régression BUG-248, 250 (bornes), 254, 255, 256 (dev-backend, 2026-11-12).
Les sondes BUG-247/249/250/251/252 sont dans test_vague2_db_permissions.py.
"""
from decimal import Decimal

from rest_framework.test import APIClient

from clients.models import Client, SocialContribution, SocialDistribution
from core.testing import make_client
from core.tests.test_permissions import BaseNodeTestCase


class Bug248TemporaryPasswordTests(BaseNodeTestCase):
    def test_temporary_password_is_returned_once_and_works(self):
        c = self.client_as(self.direction)
        r = c.post(f"/api/core/users/{self.gerant_k1.pk}/reset_password/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        temp = r.json()["temporary_password"]
        self.assertGreaterEqual(len(temp), 10)
        self.assertNotEqual(temp, self.gerant_k1.username)
        self.assertNotIn(temp, r.json()["detail"])
        self.gerant_k1.refresh_from_db()
        self.assertTrue(self.gerant_k1.check_password(temp))

    def test_temporary_password_not_in_activity_log(self):
        from core.models import ActivityLog
        c = self.client_as(self.direction)
        r = c.post(f"/api/core/users/{self.gerant_k1.pk}/reset_password/", {}, format="json")
        temp = r.json()["temporary_password"]
        for log in ActivityLog.objects.all():
            self.assertNotIn(temp, log.description)


class Bug254DistributionLineTests(BaseNodeTestCase):
    def test_post_line_without_distribution_is_400_not_500(self):
        cl = make_client(self.k1)
        c = self.client_as(self.gerant_k1)
        r = c.post("/api/clients/distribution-lines/", {"client": str(cl.pk)}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_post_line_with_distribution_ok_and_foreign_refused(self):
        cl = make_client(self.k1)
        dist = SocialDistribution.objects.create(node=self.k1, year=2026)
        c = self.client_as(self.gerant_k1)
        r = c.post("/api/clients/distribution-lines/",
                   {"distribution": str(dist.pk), "client": str(cl.pk)}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        dist2 = SocialDistribution.objects.create(node=self.k2, year=2026)
        r = c.post("/api/clients/distribution-lines/",
                   {"distribution": str(dist2.pk), "client": str(cl.pk)}, format="json")
        self.assertEqual(r.status_code, 400, r.content)


class Bug255PublicConfigTests(BaseNodeTestCase):
    def test_anonymous_config_exposes_only_on_line(self):
        r = APIClient().get("/api/core/config/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json().keys()), {"on_line"})

    def test_authenticated_config_is_full(self):
        r = self.client_as(self.facturier_k1).get("/api/core/config/")
        self.assertIn("debt_ceiling", r.json())

    def test_schema_requires_authentication(self):
        # Le test runner force settings.DEBUG à False, mais SERVE_PERMISSIONS est
        # figé à l'import des réglages : on lit donc la même variable d'environnement.
        import os
        if os.environ.get('DJANGO_DEBUG', 'False').lower() in ('true', '1', 'yes'):
            self.skipTest("DEBUG actif au chargement des réglages")
        self.assertEqual(APIClient().get("/api/schema/").status_code, 401)


class Bug256BulkCreateMonthTests(BaseNodeTestCase):
    def test_bulk_create_uses_positive_amount_filter(self):
        cl = make_client(self.k1)
        Client.objects.filter(pk=cl.pk).update(cotisation_sociale=Decimal("3000"))
        c = self.client_as(self.gerant_k1)
        r = c.post("/api/clients/contributions/bulk_create_month/",
                   {"month": 10, "year": 2026}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["created"], 1)
        contrib = SocialContribution.objects.get(client=cl)
        self.assertEqual(contrib.amount, Decimal("3000"))


class Bug250BoundsTests(BaseNodeTestCase):
    def test_gerant_credit_limit_out_of_bounds_refused(self):
        c = self.client_as(self.gerant_k1)
        r = c.post("/api/clients/clients/", {
            "first_name": "ZZ", "last_name": "Bound", "phone": "1", "credit_limit": "99999999",
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_gerant_can_set_credit_limit_in_bounds(self):
        c = self.client_as(self.gerant_k1)
        r = c.post("/api/clients/clients/", {
            "first_name": "ZZ", "last_name": "Bound", "phone": "1", "credit_limit": "80000",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Decimal(str(r.json()["credit_limit"])), Decimal("80000"))
