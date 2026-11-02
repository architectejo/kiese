"""
Vérification indépendante (phase 4) — testeur-permissions, 2026-10-22.

Ces tests NE remplacent PAS core/tests/test_permissions.py (écrit en phase 2).
Ils documentent des scénarios d'attaque supplémentaires que je (testeur-permissions,
phase 4) exécute pour contre-vérifier BUG-022/023/024/025/026 de façon critique,
avant de passer ces tickets en VÉRIFIÉ ou de les rouvrir.

Règle transversale (PLAN §0.1) : exclusivement via `manage.py test` (base éphémère).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Node, ColisDistribution
from clients.models import Client, SocialContribution, SocialDistribution
from production.models import ConsumableStock, ConsumableMovement, BreadTransfer, BreadPrice

User = get_user_model()


def make_user(role, node=None, username=None, **extra):
    username = username or f"v_{role.lower()}_{node.code if node else 'hq'}_{User.objects.count()}"
    return User.objects.create_user(
        username=username, password="Test#Pass1234", role=role, node=node, **extra
    )


class VerifBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code="K1", name="DEMO K1 TABORA")
        cls.k2 = Node.objects.create(code="K2", name="DEMO K2 COQ")
        cls.gerant_k1 = make_user("GERANT", node=cls.k1)
        cls.gerant_k2 = make_user("GERANT", node=cls.k2)
        cls.comptable = make_user("COMPTABLE", node=None)

    def client_as(self, user):
        c = APIClient()
        token = str(RefreshToken.for_user(user).access_token)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return c


class ForgedNodeOnWriteTests(VerifBase):
    """BUG-022 (fiche) ne couvrait que la LECTURE (get_queryset) des 5 ViewSets.
    Je vérifie ici si l'ÉCRITURE (perform_create) accepte toujours un `node`
    falsifié dans le payload pour un utilisateur non-HQ — motif identique à
    celui corrigé sur ClientViewSet (BUG-025), mais pas répliqué ici."""

    def test_gerant_k1_cannot_create_colis_distribution_for_k2(self):
        c = self.client_as(self.gerant_k1)
        resp = c.post("/api/core/colis/", {
            "node": str(self.k2.pk), "year": 2026,
            "beneficiary_label": "DEMO Agent forgé K2",
            "rice_value": "0.00", "meat_value": "0.00", "cash_amount": "10000.00",
        }, format="json")
        if resp.status_code not in (200, 201):
            return  # rejeté -> pas de faille sur cet endpoint
        created = ColisDistribution.objects.get(pk=resp.json()["id"])
        self.assertEqual(
            created.node_id, self.gerant_k1.node_id,
            f"FAILLE : GERANT K1 a créé une ColisDistribution rattachée à {created.node.code} "
            f"via un node forgé dans le payload (POST /api/core/colis/)."
        )

    def test_gerant_k1_cannot_create_social_contribution_for_k2(self):
        client_k2 = Client.objects.create(
            code="K2-DEMO02", first_name="Jean", last_name="DEMO", node=self.k2,
        )
        c = self.client_as(self.gerant_k1)
        resp = c.post("/api/clients/contributions/", {
            "node": str(self.k2.pk), "client": str(client_k2.pk),
            "month": 1, "year": 2026, "amount": "3000.00",
        }, format="json")
        if resp.status_code == 404:
            self.skipTest("Route contributions introuvable à cette URL")
        if resp.status_code not in (200, 201):
            return
        created = SocialContribution.objects.get(pk=resp.json()["id"])
        self.assertEqual(
            created.node_id, self.gerant_k1.node_id,
            f"FAILLE : GERANT K1 a créé une SocialContribution rattachée à {created.node.code} "
            f"via un node forgé dans le payload (POST /api/clients/contributions/)."
        )

    def test_gerant_k1_cannot_create_social_distribution_for_k2(self):
        c = self.client_as(self.gerant_k1)
        resp = c.post("/api/clients/distributions/", {
            "node": str(self.k2.pk), "year": 2026,
        }, format="json")
        if resp.status_code == 404:
            self.skipTest("Route distributions introuvable à cette URL")
        if resp.status_code not in (200, 201):
            return
        created = SocialDistribution.objects.get(pk=resp.json()["id"])
        self.assertEqual(
            created.node_id, self.gerant_k1.node_id,
            f"FAILLE : GERANT K1 a créé une SocialDistribution rattachée à {created.node.code} "
            f"via un node forgé dans le payload (POST /api/clients/distributions/)."
        )

    def test_gerant_k1_cannot_create_consumable_movement_for_k2(self):
        stock_k2 = ConsumableStock.objects.create(
            node=self.k2, consumable_type="FARINE", quantity="100.000", unit="sac",
        )
        c = self.client_as(self.gerant_k1)
        resp = c.post("/api/production/movements/", {
            "node": str(self.k2.pk), "stock": str(stock_k2.pk),
            "movement_type": "ENTRY", "quantity": "5.000",
        }, format="json")
        if resp.status_code == 404:
            self.skipTest("Route movements introuvable à cette URL")
        if resp.status_code not in (200, 201):
            return
        created = ConsumableMovement.objects.get(pk=resp.json()["id"])
        self.assertEqual(
            created.node_id, self.gerant_k1.node_id,
            f"FAILLE : GERANT K1 a créé un ConsumableMovement rattaché à {created.node.code} "
            f"via un node forgé dans le payload (POST /api/production/movements/), stock K2 modifié "
            f"depuis K1."
        )


class BreadTransferForgedIdTests(VerifBase):
    """BUG-023 : tentative de contournement par ID forgé d'un transfert entre
    deux AUTRES boulangeries (K2<->K3) que celle de l'attaquant (K1)."""

    def test_unrelated_gerant_gets_404_not_a_leak(self):
        k3 = Node.objects.create(code="K3", name="DEMO K3 ATHENEE")
        bp = BreadPrice.objects.filter(is_active=True).first() or BreadPrice.objects.create(
            category="DEMO", label="DEMO 200", unit_price=200,
        )
        transfer = BreadTransfer.objects.create(
            from_node=self.k2, to_node=k3, bread_price=bp, quantity_sent=10,
        )
        c = self.client_as(self.gerant_k1)
        resp_list = c.get("/api/production/transfers/")
        ids = [row.get("id") for row in resp_list.json().get("results", resp_list.json())]
        self.assertNotIn(str(transfer.pk), [str(i) for i in ids])

        resp_detail = c.get(f"/api/production/transfers/{transfer.pk}/")
        self.assertIn(resp_detail.status_code, (403, 404))

        resp_respond = c.post(f"/api/production/transfers/{transfer.pk}/respond_to_request/", {}, format="json")
        self.assertIn(resp_respond.status_code, (403, 404))


class CashbookHQRoleTests(VerifBase):
    """BUG-026 : vérifie que la restriction IsHeadquarters ne bloque
    aucun rôle légitime HQ (ADMIN/DIRECTION/COMPTABLE)."""

    def test_comptable_role_is_allowed(self):
        c = self.client_as(self.comptable)
        resp = c.get("/api/treasury/cashbook/")
        self.assertEqual(resp.status_code, 200)

    def test_gerant_role_is_forbidden(self):
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/treasury/cashbook/")
        self.assertEqual(resp.status_code, 403)


class ClientNodeMoveViaUpdateTests(VerifBase):
    """BUG-025 ne corrige que ClientViewSet.perform_create. Je vérifie si
    ClientViewSet.perform_update laisse passer le même type de falsification
    (déplacer un client existant vers un autre nœud via PATCH `node`)."""

    def test_gerant_k1_cannot_move_its_own_client_to_k2_via_patch(self):
        client_k1 = Client.objects.create(
            code="K1-DEMO03", first_name="Alice", last_name="DEMO", node=self.k1,
        )
        c = self.client_as(self.gerant_k1)
        resp = c.patch(f"/api/clients/clients/{client_k1.pk}/", {
            "node": str(self.k2.pk),
        }, format="json")
        client_k1.refresh_from_db()
        self.assertEqual(
            client_k1.node_id, self.k1.pk,
            f"FAILLE : GERANT K1 a déplacé son propre client vers {client_k1.node.code} "
            f"via PATCH /api/clients/clients/<id>/ avec node forgé (statut HTTP {resp.status_code})."
        )


class RefreshCycleIndependentTests(VerifBase):
    """BUG-024 : contre-vérification indépendante du cycle complet
    login -> access -> refresh -> nouvel access valide -> logout -> refresh
    blacklisté refusé."""

    def test_full_refresh_and_logout_cycle(self):
        c = APIClient()
        login = c.post("/api/core/auth/login/", {
            "username": self.gerant_k1.username, "password": "Test#Pass1234",
        }, format="json")
        self.assertEqual(login.status_code, 200, login.content)
        access = login.json()["access"]
        refresh = login.json()["refresh"]

        # Nouvel access via refresh
        r1 = c.post("/api/core/auth/login/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(r1.status_code, 200, r1.content)
        new_access = r1.json()["access"]
        self.assertNotEqual(new_access, access)

        # Le nouvel access fonctionne réellement sur une route protégée
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
        me = c.get("/api/core/auth/me/")
        self.assertEqual(me.status_code, 200, me.content)

        # Logout avec le refresh (original) -> doit le blacklister
        logout_refresh = r1.json().get("refresh", refresh)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
        logout = c.post("/api/core/auth/logout/", {"refresh": logout_refresh}, format="json")
        self.assertIn(logout.status_code, (200, 205), logout.content)

        # Le refresh blacklisté ne doit plus permettre d'obtenir un access
        r2 = c.post("/api/core/auth/login/refresh/", {"refresh": logout_refresh}, format="json")
        self.assertEqual(r2.status_code, 401, r2.content)


class NotificationForgedOriginTests(VerifBase):
    """BUG-022 : SystemNotificationViewSet est un ModelViewSet complet (POST
    non désactivé). Je vérifie si un GERANT K1 peut créer une notification
    avec node_origin forgé (K2, ou pire 'CLOUD' pour se faire passer pour
    une alerte siège visible par tout le monde)."""

    def test_gerant_k1_cannot_forge_notification_as_cloud_alert(self):
        from core.models import SystemNotification
        c = self.client_as(self.gerant_k1)
        resp = c.post("/api/core/notifications/", {
            "title": "DEMO Fausse alerte siège",
            "message": "DEMO contenu forgé",
            "severity": "DANGER",
            "node_origin": "CLOUD",
        }, format="json")
        if resp.status_code not in (200, 201):
            return
        notif = SystemNotification.objects.get(pk=resp.json()["id"])
        self.assertNotEqual(
            notif.node_origin, "CLOUD",
            "FAILLE : un GERANT K1 a pu créer une fausse alerte node_origin=CLOUD "
            "(visible par tous les nœuds) via POST /api/core/notifications/."
        )
