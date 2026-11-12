"""
Sondes du testeur-permissions — vague 2 sur base réelle (2026-11-12).

Chaque test reproduit, sur la base de test éphémère (jamais db.sqlite3), un
écart constaté sur le backend réel. Les écarts non corrigés sont marqués
`@expectedFailure` avec leur ticket ; dev-backend retire le marqueur à la
correction (le testeur confirme ensuite).

Tickets : BUG-247 à BUG-253 (docs/qa/REGISTRE_BUGS.md).

Mise à jour 2026-11-12 (vague 3) : tous les `@expectedFailure` ont été retirés par
dev-backend ; les tests passent et les tickets 247 à 252 sont VÉRIFIÉS par le
testeur. Non-régression de la matrice : test_vague3_db_permissions.py.
"""

from clients.models import Client, SocialContribution
from core.models import SystemNotification
from core.tests.test_permissions import BaseNodeTestCase, make_user
from core.testing import make_client
from production.models import ConsumableStock


class Bug247DirectionSelfElevationTests(BaseNodeTestCase):
    """BUG-247 : un compte DIRECTION ne doit pas pouvoir se promouvoir ADMIN,
    créer un ADMIN ni réinitialiser le mot de passe d'un ADMIN."""

    def test_direction_cannot_promote_self_to_admin(self):
        c = self.client_as(self.direction)
        r = c.patch(f"/api/core/users/{self.direction.pk}/", {"role": "ADMIN"}, format="json")
        self.direction.refresh_from_db()
        self.assertEqual(self.direction.role, "DIRECTION", (r.status_code, r.content))

    def test_direction_cannot_create_admin(self):
        c = self.client_as(self.direction)
        r = c.post("/api/core/users/", {
            "username": "zz_made_admin", "password": "Test#Pass1234", "role": "ADMIN",
            "first_name": "Z", "last_name": "Z",
        }, format="json")
        self.assertGreaterEqual(r.status_code, 400, r.content)

    def test_direction_cannot_reset_admin_password(self):
        c = self.client_as(self.direction)
        r = c.post(f"/api/core/users/{self.admin.pk}/reset_password/", {}, format="json")
        self.assertEqual(r.status_code, 403, r.content)


class Bug248ResetPasswordTests(BaseNodeTestCase):
    """BUG-248 : le mot de passe réinitialisé ne doit être ni l'identifiant
    ni renvoyé en clair dans la réponse."""

    def test_reset_password_is_not_username_and_not_echoed(self):
        c = self.client_as(self.direction)
        r = c.post(f"/api/core/users/{self.gerant_k1.pk}/reset_password/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.gerant_k1.refresh_from_db()
        self.assertFalse(self.gerant_k1.check_password(self.gerant_k1.username))
        self.assertNotIn(self.gerant_k1.username, r.json().get("detail", "").split("mot de passe :")[-1])


class Bug249SocialContributionCrossNodeTests(BaseNodeTestCase):
    """BUG-249 : écritures caisse sociale inter-nœuds par un gérant."""

    def test_gerant_cannot_bulk_create_for_other_node(self):
        foreign = make_client(self.k2)
        Client.objects.filter(pk=foreign.pk).update(cotisation_sociale=1)
        c = self.client_as(self.gerant_k1)
        c.post("/api/clients/contributions/bulk_create_month/",
               {"node": self.k2.pk, "month": 10, "year": 2026, "amount": "1"}, format="json")
        self.assertFalse(SocialContribution.objects.filter(client=foreign).exists())

    def test_gerant_cannot_create_contribution_for_foreign_client(self):
        foreign = make_client(self.k2)
        c = self.client_as(self.gerant_k1)
        r = c.post("/api/clients/contributions/", {
            "client": str(foreign.pk), "node": self.k1.pk, "month": 11, "year": 2026, "amount": "1",
        }, format="json")
        self.assertGreaterEqual(r.status_code, 400, r.content)
        self.assertFalse(SocialContribution.objects.filter(client=foreign).exists())


class Bug250FacturierClientCreationTests(BaseNodeTestCase):
    """BUG-250 : un facturier ne fixe ni plafond de crédit ni taux de commission."""

    def test_facturier_cannot_set_credit_limit_or_commission_rate_on_create(self):
        c = self.client_as(self.facturier_k1)
        r = c.post("/api/clients/clients/", {
            "first_name": "ZZ", "last_name": "Perm", "phone": "1",
            "credit_limit": "9999999", "commission_rate": "0.30",
        }, format="json")
        if r.status_code < 300:
            body = r.json()
            self.assertEqual(str(body["credit_limit"]), "50000.00", body)
            self.assertEqual(str(body["commission_rate"]), "0.25", body)


class Bug251ConsumableStockWriteTests(BaseNodeTestCase):
    """BUG-251 : le stock de consommables ne se modifie que par mouvements (gérant+)."""

    def test_livreur_and_facturier_cannot_patch_stock_quantity(self):
        stock = ConsumableStock.objects.create(node=self.k1, consumable_type="FLOUR", quantity="10.000")
        for user in (self.livreur_k1, self.facturier_k1):
            c = self.client_as(user)
            r = c.patch(f"/api/production/stocks/{stock.pk}/", {"quantity": "999"}, format="json")
            stock.refresh_from_db()
            self.assertEqual(str(stock.quantity), "10.000", (user.role, r.status_code))


class Bug252GlobalNotificationTests(BaseNodeTestCase):
    """BUG-252 : un utilisateur de boulangerie ne supprime pas une alerte siège (CLOUD)."""

    def test_livreur_cannot_delete_cloud_notification(self):
        n = SystemNotification.objects.create(title="ZZ", message="alerte siège", severity="DANGER", node_origin="CLOUD")
        c = self.client_as(self.livreur_k1)
        r = c.delete(f"/api/core/notifications/{n.pk}/")
        self.assertIn(r.status_code, (403, 404), r.status_code)
        self.assertTrue(SystemNotification.objects.filter(pk=n.pk).exists())
