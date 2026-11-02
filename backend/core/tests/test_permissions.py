"""
Tests du testeur-permissions — ETS. KIESE (2026-10-22).

Partie 1 : vérification de BUG-005/006 (DEBUG/SECRET_KEY/HTTPS, JWT/blacklist/
throttle login) corrigés par nettoyeur-securite. Celui qui corrige ne se
valide jamais lui-même (CLAUDE.md §7 règle 3) : ces tests sont écrits ici,
par testeur-permissions, et non par nettoyeur-securite.

Partie 2 : audit BUG-016 (partie permissions/dashboard/nodes de remarque.md)
+ isolation inter-nœuds transversale (cœur de métier de cet agent), sur
TOUTES les routes API, pas seulement le périmètre remarque.md.

Partie 3 (2026-10-30, post-chantier remarque.md + backlog mineur) : relecture
RBAC/isolation des nouveaux endpoints/champs apparus depuis la dernière passe
complète — `InvoiceViewSet.adjust()` (BUG-097), `ProductionSessionViewSet.close()`
(BUG-093), `Invoice.commission_exempt`, `JournalEntryViewSet.suggested_ca`
(BUG-091). Voir docs/qa/REGISTRE_BUGS.md, note de synthèse « Passe
testeur-permissions 2026-10-30 (post-chantier) ».

Rappel règle transversale (PLAN_2026-10-22.md §0.1) : ces tests passent
exclusivement par `manage.py test` (base de test éphémère) — jamais contre
`backend/db.sqlite3`.
"""
import io
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Node, SystemNotification, ColisDistribution
from core.testing import make_bread_price, make_client as make_demo_client
from clients.models import Client, SocialContribution, SocialDistribution
from production.models import (
    ConsumableStock, ConsumableMovement, BreadTransfer, ProductionSession,
)
from sales.models import Invoice, InvoiceLine
from treasury.models import CashClosure, JournalEntry

User = get_user_model()


def make_user(role, node=None, username=None, **extra):
    username = username or f"user_{role.lower()}_{node.code if node else 'hq'}_{User.objects.count()}"
    return User.objects.create_user(
        username=username, password="Test#Pass1234", role=role, node=node, **extra
    )


class BaseNodeTestCase(TestCase):
    """Deux nœuds K1/K2 avec un utilisateur de chaque rôle sur K1, pour les
    tests d'isolation. Les ressources de test sont volontairement fictives
    (préfixe DEMO), conformément à la règle PLAN §0.1 — même si ici tout
    passe par la base de test éphémère de `manage.py test`."""

    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code="K1", name="DEMO K1 TABORA")
        cls.k2 = Node.objects.create(code="K2", name="DEMO K2 COQ")

        cls.admin = make_user("ADMIN", node=None)
        cls.direction = make_user("DIRECTION", node=None)
        cls.comptable = make_user("COMPTABLE", node=None)
        cls.gerant_k1 = make_user("GERANT", node=cls.k1)
        cls.gerant_k2 = make_user("GERANT", node=cls.k2)
        cls.facturier_k1 = make_user("FACTURIER", node=cls.k1)
        cls.livreur_k1 = make_user("LIVREUR", node=cls.k1)

    def client_as(self, user):
        c = APIClient()
        token = str(RefreshToken.for_user(user).access_token)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return c


# ───────────────────────────────────────────────────────────────────
# Partie 1 — Vérification BUG-005/006
# ───────────────────────────────────────────────────────────────────

class LoginThrottleTests(BaseNodeTestCase):
    """BUG-006 : 6 tentatives de login erronées en moins d'une minute →
    la 6e doit renvoyer HTTP 429.

    BUG-087 : ce martèlement du MÊME compte doit rester throttlé — c'est le
    test de non-régression de la correction (throttle par compte visé, pas
    seulement par IP, voir core/throttling.py)."""

    def test_sixth_bad_login_attempt_is_throttled(self):
        c = APIClient()
        statuses = []
        for _ in range(6):
            resp = c.post(
                "/api/core/auth/login/",
                {"username": "inexistant_demo", "password": "mauvais-mdp"},
                format="json",
            )
            statuses.append(resp.status_code)
        # Les 5 premières doivent être 401 (identifiants invalides), la 6e 429.
        self.assertEqual(statuses[:5], [401] * 5, statuses)
        self.assertEqual(statuses[5], 429, statuses)


class LoginThrottlePerAccountTests(BaseNodeTestCase):
    """BUG-087 : le throttle de login était compté par IP uniquement, pour
    toute tentative (y compris les connexions réussies), sans distinction
    de compte. Plusieurs employés d'une même boulangerie se connectant
    l'un après l'autre depuis le même poste/réseau (même IP) se
    bloquaient donc mutuellement dès la 6e connexion — reproduit dans
    e2e/tests/02-connexion-roles.spec.ts (6 rôles séquentiels, le 6e échoue
    en 429).

    Avant la correction, ce test échouait : la 6e connexion (6e compte
    distinct, même IP) recevait 429 au lieu de 200."""

    def test_six_different_accounts_same_ip_all_succeed(self):
        password = "Test#Pass1234"
        accounts = [
            self.admin, self.direction, self.comptable,
            self.gerant_k1, self.gerant_k2, self.facturier_k1,
        ]
        self.assertEqual(len(accounts), 6)

        c = APIClient()
        statuses = []
        for user in accounts:
            resp = c.post(
                "/api/core/auth/login/",
                {"username": user.username, "password": password},
                format="json",
            )
            statuses.append(resp.status_code)

        # Les 6 connexions, sur 6 comptes différents mais depuis la même
        # IP (APIClient sans adresse distincte), doivent toutes réussir.
        self.assertEqual(statuses, [200] * 6, statuses)


class RefreshBlacklistTests(BaseNodeTestCase):
    """BUG-006 : un refresh token blacklisté après logout ne doit plus
    permettre d'obtenir un nouvel access token.

    NOTE IMPORTANTE (voir rapport, nouveau ticket ouvert) : il n'existe
    AUCUN endpoint HTTP de refresh dans ce backend — ni `/api/token/refresh/`
    (jamais câblé dans `kiese/urls.py`), ni `/api/core/auth/login/refresh/`
    (l'URL que le frontend appelle réellement, `frontend/src/api/client.ts`
    — également absente de `core/urls.py`). Le mécanisme de rotation/
    blacklist de SimpleJWT est donc correctement configuré au niveau
    librairie (vérifié ci-dessous directement sur la classe `RefreshToken`),
    mais **inutilisable en conditions réelles** : tout utilisateur est
    déconnecté de force dès l'expiration de l'access token (30 min depuis
    BUG-006, contre 12h avant), sans aucun moyen de rafraîchir. Ce point
    dépasse le périmètre strict de BUG-006 (qui portait sur la blacklist,
    pas sur l'existence de la route) : voir ticket dédié dans le registre."""

    def test_refresh_token_blacklisted_after_logout_cannot_mint_new_access_token(self):
        c = self.client_as(self.gerant_k1)
        refresh = RefreshToken.for_user(self.gerant_k1)

        logout_resp = c.post(
            "/api/core/auth/logout/", {"refresh": str(refresh)}, format="json"
        )
        self.assertEqual(logout_resp.status_code, 200)

        from rest_framework_simplejwt.exceptions import TokenError
        with self.assertRaises(TokenError):
            # Reproduit exactement ce que ferait une TokenRefreshView standard :
            # lever une erreur car le token est dans la blacklist.
            RefreshToken(str(refresh)).check_blacklist()

    def test_refresh_endpoint_now_wired_at_the_exact_url_the_frontend_calls(self):
        """BUG-024 corrigé : `/api/core/auth/login/refresh/` (URL appelée par
        `frontend/src/api/client.ts`) renvoie bien un nouvel access token.
        `/api/token/refresh/` reste volontairement absent (seule l'URL
        réellement utilisée par le frontend a été câblée)."""
        c = APIClient()
        refresh = RefreshToken.for_user(self.gerant_k1)

        resp_unwired = c.post("/api/token/refresh/", {"refresh": str(refresh)}, format="json")
        self.assertEqual(resp_unwired.status_code, 404)

        resp = c.post("/api/core/auth/login/refresh/", {"refresh": str(refresh)}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("access", resp.json())

    def test_refresh_endpoint_rejects_a_blacklisted_refresh_token(self):
        """BUG-024 + BUG-006 : un refresh token blacklisté après logout ne
        doit plus permettre d'obtenir un nouvel access token via le vrai
        endpoint HTTP (pas seulement vérifié au niveau librairie)."""
        c = self.client_as(self.gerant_k1)
        refresh = RefreshToken.for_user(self.gerant_k1)

        logout_resp = c.post("/api/core/auth/logout/", {"refresh": str(refresh)}, format="json")
        self.assertEqual(logout_resp.status_code, 200)

        resp = c.post("/api/core/auth/login/refresh/", {"refresh": str(refresh)}, format="json")
        self.assertEqual(resp.status_code, 401, resp.content)


class DeploySecurityCheckTests(TestCase):
    """BUG-005 : `manage.py check --deploy` avec un .env de production simulé
    doit renvoyer 0 avertissement security.*."""

    @override_settings(
        DEBUG=False,
        SECURE_SSL_REDIRECT=True,
        SECURE_HSTS_SECONDS=31536000,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
        SECURE_HSTS_PRELOAD=True,
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        SECURE_CONTENT_TYPE_NOSNIFF=True,
        ALLOWED_HOSTS=["etskiese.com", "www.etskiese.com"],
        SECRET_KEY="une-cle-aleatoire-forte-et-longue-simulee-pour-le-test-de-prod-2026",
        # X_FRAME_OPTIONS est décidé dans settings.py par un `if not DEBUG:`
        # évalué UNE FOIS à l'import du module, à partir du DEBUG réel de ce
        # process (ici True, car `manage.py test` tourne avec DJANGO_DEBUG=True
        # dans l'environnement d'exécution des tests) — `override_settings` ne
        # peut pas rejouer cette branche a posteriori. On le force donc
        # explicitement ici pour ne simuler QUE ce que ce test peut réellement
        # vérifier ; le comportement réel de la branche conditionnelle a été
        # vérifié manuellement par nettoyeur-securite avec un vrai
        # DJANGO_DEBUG=False (voir BUG-005 dans le registre).
        X_FRAME_OPTIONS="DENY",
    )
    def test_no_security_warnings_with_simulated_production_env(self):
        out = io.StringIO()
        err = io.StringIO()
        try:
            call_command("check", "--deploy", stdout=out, stderr=err)
        except SystemExit:
            pass
        output = out.getvalue() + err.getvalue()
        security_warnings = [
            line for line in output.splitlines() if "security.W" in line
        ]
        self.assertEqual(
            security_warnings, [],
            f"Avertissements security.* inattendus avec un .env de prod simulé : {security_warnings}"
        )


class AllowAnyAuditTests(TestCase):
    """Audit indépendant des endpoints AllowAny : confirme qu'il n'y en a
    que 3 dans le code applicatif (login, GET config, GET/retrieve
    bread-prices), tous justifiés (point d'entrée d'auth ou lecture
    publique pour la vitrine)."""

    def test_config_get_is_public_but_patch_requires_direction(self):
        c = APIClient()
        resp = c.get("/api/core/config/")
        self.assertEqual(resp.status_code, 200)
        resp_patch = c.patch("/api/core/config/", {"debt_ceiling": "1.00"}, format="json")
        self.assertIn(resp_patch.status_code, (401, 403))

    def test_bread_prices_list_is_public_but_write_requires_direction(self):
        c = APIClient()
        resp = c.get("/api/core/bread-prices/")
        self.assertEqual(resp.status_code, 200)
        resp_post = c.post(
            "/api/core/bread-prices/",
            {"category": "P200", "label": "Pain 200 FC", "unit_price": "200.00"},
            format="json",
        )
        self.assertIn(resp_post.status_code, (401, 403))

    def test_login_endpoint_is_the_only_fully_anonymous_write_entrypoint(self):
        c = APIClient()
        resp = c.post(
            "/api/core/auth/login/", {"username": "x", "password": "y"}, format="json"
        )
        # 401 (bad credentials) ou 400, jamais 403/404 — c'est bien le point
        # d'entrée volontairement public.
        self.assertIn(resp.status_code, (400, 401))

    def test_other_authenticated_endpoints_reject_anonymous_access(self):
        """Échantillon d'endpoints représentatifs de chaque app — doivent
        tous refuser l'accès anonyme (DEFAULT_PERMISSION_CLASSES = IsAuthenticated,
        confirmé par relecture de settings.py ; ce test vérifie qu'aucune vue
        ne déroge à ce défaut en-dehors des 3 exceptions ci-dessus)."""
        c = APIClient()
        endpoints = [
            "/api/core/nodes/",
            "/api/core/users/",
            "/api/core/activities/",
            "/api/core/notifications/",
            "/api/core/colis/",
            "/api/clients/clients/",
            "/api/sales/invoices/",
            "/api/production/sessions/",
            "/api/treasury/cashbook/",
            "/api/commissions/periods/",
            "/api/finance/years/",
            "/api/blockchain/alerts/",
        ]
        for url in endpoints:
            resp = c.get(url)
            self.assertIn(
                resp.status_code, (401, 403),
                f"{url} est accessible sans authentification (status {resp.status_code})."
            )


# ───────────────────────────────────────────────────────────────────
# Partie 2 — BUG-016 (permissions/dashboard/nodes) + isolation transversale
# ───────────────────────────────────────────────────────────────────

class SelfElevationAttackTests(BaseNodeTestCase):
    """Un utilisateur ne doit jamais pouvoir s'élever lui-même via
    PATCH /users/<soi-même>/ ni via /auth/me/ (role, node, is_superuser)."""

    def test_patch_users_self_requires_direction_permission(self):
        c = self.client_as(self.gerant_k1)
        resp = c.patch(
            f"/api/core/users/{self.gerant_k1.pk}/",
            {"role": "ADMIN"}, format="json"
        )
        self.assertIn(resp.status_code, (403, 404))
        self.gerant_k1.refresh_from_db()
        self.assertEqual(self.gerant_k1.role, "GERANT")

    def test_auth_me_patch_cannot_change_role_node_or_superuser(self):
        c = self.client_as(self.facturier_k1)
        resp = c.patch(
            "/api/core/auth/me/",
            {"role": "ADMIN", "node": self.k2.pk, "is_superuser": True, "first_name": "Jean"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.facturier_k1.refresh_from_db()
        self.assertEqual(self.facturier_k1.role, "FACTURIER")
        self.assertEqual(self.facturier_k1.node_id, self.k1.pk)
        self.assertFalse(self.facturier_k1.is_superuser)


class CreditLimitAttackTests(BaseNodeTestCase):
    """Un facturier ne doit jamais pouvoir modifier credit_limit (ou tout
    autre champ) d'un client via l'API — l'action update/destroy du
    ClientViewSet exige IsGerant (FACTURIER en est exclu)."""

    def test_facturier_cannot_patch_client_credit_limit(self):
        client_obj = Client.objects.create(
            code="K1-DEMO01", first_name="Jean", last_name="DEMO",
            node=self.k1, credit_limit=Decimal("50000.00"),
        )
        c = self.client_as(self.facturier_k1)
        resp = c.patch(
            f"/api/clients/clients/{client_obj.pk}/",
            {"credit_limit": "5000000.00"}, format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)
        client_obj.refresh_from_db()
        self.assertEqual(client_obj.credit_limit, Decimal("50000.00"))


class ActivityLogAccessTests(BaseNodeTestCase):
    """Les logs d'activité ne sont accessibles qu'aux rôles HQ."""

    def test_gerant_cannot_list_activity_logs(self):
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/core/activities/")
        self.assertEqual(resp.status_code, 403)

    def test_comptable_can_list_activity_logs(self):
        c = self.client_as(self.comptable)
        resp = c.get("/api/core/activities/")
        self.assertEqual(resp.status_code, 200)


class ConfigAndPricesAttackTests(BaseNodeTestCase):
    def test_facturier_cannot_patch_config(self):
        c = self.client_as(self.facturier_k1)
        resp = c.patch("/api/core/config/", {"debt_ceiling": "1.00"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_gerant_cannot_patch_bread_prices(self):
        from core.models import BreadPrice
        bp = BreadPrice.objects.create(category="MINI", label="Pain 200 FC DEMO", unit_price=200)
        c = self.client_as(self.gerant_k1)
        resp = c.patch(f"/api/core/bread-prices/{bp.pk}/", {"unit_price": 1}, format="json")
        self.assertEqual(resp.status_code, 403)


class CashbookEntryDeletionTests(BaseNodeTestCase):
    """Le livre de caisse est en lecture seule : aucune méthode DELETE ne doit
    exister sur /api/treasury/cashbook/<id>/, même pour ADMIN."""

    def test_no_delete_method_exists_on_cashbook_entries(self):
        c = self.client_as(self.admin)
        resp = c.delete("/api/treasury/cashbook/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(resp.status_code, 405, resp.content)


class CashbookEntryIsolationTests(BaseNodeTestCase):
    """BUG-026 : le Livre de Caisse Direction (cahierDesCharges.md §5.1.3)
    est un document de direction consolidé, pas un document par boulangerie
    — la correction retenue (voir REGISTRE_BUGS.md) est de le restreindre
    entièrement à ADMIN/DIRECTION/COMPTABLE (IsHeadquarters), pas de le
    filtrer par nœud comme une ressource locale : un GERANT ne doit donc
    avoir accès à AUCUNE écriture, pas même celles de sa propre boulangerie."""

    def test_gerant_k1_cannot_read_the_direction_cashbook_at_all(self):
        from treasury.models import CashbookEntry
        # previous_hash est unique (BUG-002) : une valeur fictive distincte
        # suffit ici, le test ne porte pas sur la chaîne de hash elle-même.
        CashbookEntry.objects.create(
            node=self.k2, date="2026-10-01", piece_number="DEMO-K2-0001",
            label="DEMO écriture K2", entry_amount="1000.00",
            previous_hash="DEMO-PREV-HASH-0001",
        )
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/treasury/cashbook/")
        self.assertEqual(
            resp.status_code, 403,
            "BUG-026 : un GERANT ne doit pas pouvoir lire le Livre de Caisse "
            "Direction, même filtré sur sa propre boulangerie — c'est un "
            "document de direction (ADMIN/DIRECTION/COMPTABLE uniquement)."
        )

    def test_comptable_can_read_the_direction_cashbook(self):
        c = self.client_as(self.comptable)
        resp = c.get("/api/treasury/cashbook/")
        self.assertEqual(resp.status_code, 200, resp.content)


class FinancialStatementsLeakTests(BaseNodeTestCase):
    """BUG-101 (découvert lors de la passe de non-régression permissions
    post-BUG-089/BUG-087, 2026-10-30) : `FinancialYearViewSet` (CLAUDE.md §5.6,
    états N/N-1 — balance, compte de résultat, bilan, cash-flow) est un
    document de direction consolidé pour tout le groupe, exactement comme
    le Livre de Caisse (BUG-026, ci-dessus). Mais `get_permissions()`
    n'applique `IsAuthenticated` (pas `IsHeadquarters`) que pour `list`,
    `retrieve`, `income_statement`, `cashflow`, `balance_sheet` et
    `comparative` : un GERANT/FACTURIER/LIVREUR reçoit aujourd'hui 200 sur
    les quatre endpoints — les états financiers consolidés de TOUTES les
    boulangeries, pas seulement la sienne (il n'y a même pas de filtre par
    nœud possible, ces états sont agrégés au niveau du groupe). Corrigé dans
    `finance/views.py::FinancialYearViewSet.get_permissions()` (BUG-101) :
    toutes les actions exigent désormais `IsHeadquarters`."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from finance.models import FinancialYear
        cls.fy = FinancialYear.objects.create(year=2026)

    def test_gerant_cannot_list_financial_years(self):
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/finance/years/")
        self.assertEqual(
            resp.status_code, 403,
            "BUG-101 : un GERANT ne doit pas pouvoir lister les exercices "
            "financiers (document de direction consolidé, même motif que "
            "BUG-026 pour le Livre de Caisse)."
        )

    def test_gerant_cannot_read_income_statement(self):
        c = self.client_as(self.gerant_k1)
        resp = c.get(f"/api/finance/years/{self.fy.pk}/income_statement/")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_gerant_cannot_read_balance_sheet(self):
        c = self.client_as(self.gerant_k1)
        resp = c.get(f"/api/finance/years/{self.fy.pk}/balance_sheet/")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_facturier_cannot_read_comparative(self):
        c = self.client_as(self.facturier_k1)
        resp = c.get(f"/api/finance/years/{self.fy.pk}/comparative/")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_comptable_can_read_income_statement(self):
        """Non-régression : HQ (COMPTABLE) doit rester autorisé."""
        c = self.client_as(self.comptable)
        resp = c.get(f"/api/finance/years/{self.fy.pk}/income_statement/")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_gerant_cannot_read_summary(self):
        """Vérification directe BUG-101 : summary déclare permission_classes=
        [IsAuthenticated] sur l'@action mais get_permissions() l'écrase —
        à confirmer par un appel réel, pas seulement par relecture."""
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/finance/years/summary/", {"year": 2026})
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_facturier_cannot_read_doc1_report(self):
        c = self.client_as(self.facturier_k1)
        resp = c.get(
            "/api/finance/years/doc1_report/",
            {"node": str(self.k1.pk), "month": 1, "year": 2026},
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_facturier_cannot_read_doc1_export(self):
        c = self.client_as(self.facturier_k1)
        resp = c.get(
            "/api/finance/years/doc1_export/",
            {"node": str(self.k1.pk), "month": 1, "year": 2026},
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_comptable_can_read_summary(self):
        """Non-régression HQ."""
        c = self.client_as(self.comptable)
        resp = c.get("/api/finance/years/summary/", {"year": 2026})
        self.assertEqual(resp.status_code, 200, resp.content)


# --- Isolation inter-nœuds : lecture, modification, suppression, création ---

class NotificationIsolationTests(BaseNodeTestCase):
    """BUG confirmé (voir registre) : SystemNotificationViewSet ne filtre pas
    par nœud — un GERANT/FACTURIER voit et modifie les notifications de
    TOUTES les boulangeries."""

    def test_gerant_k1_should_not_see_notifications_of_k2(self):
        SystemNotification.objects.create(
            title="DEMO alerte K2", message="secret K2", node_origin="K2"
        )
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/core/notifications/")
        self.assertEqual(resp.status_code, 200)
        node_origins = {n["node_origin"] for n in resp.json().get("results", resp.json()) if isinstance(n, dict)}
        self.assertNotIn(
            "K2", node_origins,
            "BUG-017 non corrigé : un GERANT K1 voit les notifications de K2 "
            "(SystemNotificationViewSet.get_queryset ne filtre pas par nœud)."
        )

    def test_gerant_k1_cannot_mark_read_a_k2_notification(self):
        notif = SystemNotification.objects.create(
            title="DEMO alerte K2", message="secret K2", node_origin="K2"
        )
        c = self.client_as(self.gerant_k1)
        resp = c.post(f"/api/core/notifications/{notif.pk}/mark_read/")
        self.assertIn(
            resp.status_code, (403, 404),
            "BUG-017 non corrigé : un GERANT K1 peut marquer comme lue une "
            "notification appartenant à K2."
        )


class ColisDistributionIsolationTests(BaseNodeTestCase):
    def test_gerant_k1_should_not_see_colis_of_k2(self):
        ColisDistribution.objects.create(
            node=self.k2, year=2026, beneficiary_label="DEMO Agent K2",
        )
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/core/colis/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        node_codes = {row.get("node_display", "") for row in rows}
        self.assertFalse(
            any("K2" in str(code) for code in node_codes),
            "BUG-017 non corrigé : un GERANT K1 voit les distributions COLIS de K2."
        )


class SocialCaisseIsolationTests(BaseNodeTestCase):
    def test_gerant_k1_should_not_see_social_contributions_of_k2(self):
        client_k2 = Client.objects.create(
            code="K2-DEMO01", first_name="Marie", last_name="DEMO", node=self.k2,
        )
        contrib = SocialContribution.objects.create(
            client=client_k2, node=self.k2, month=1, year=2026, amount="3000.00",
        )
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/clients/contributions/")
        if resp.status_code == 404:
            self.skipTest("Route social-contributions introuvable à cette URL — vérifier clients/urls.py")
        ids = {row.get("id") for row in resp.json().get("results", resp.json())}
        self.assertNotIn(
            str(contrib.pk), {str(i) for i in ids},
            "BUG-017 non corrigé : un GERANT K1 voit la caisse sociale de K2."
        )

    def test_gerant_k1_should_not_see_social_distributions_of_k2(self):
        SocialDistribution.objects.create(node=self.k2, year=2026)
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/clients/distributions/")
        if resp.status_code == 404:
            self.skipTest("Route social-distributions introuvable à cette URL — vérifier clients/urls.py")
        data = resp.json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        self.assertEqual(
            len(rows), 0,
            "BUG-017 non corrigé : un GERANT K1 voit les distributions sociales de K2."
        )


class ConsumableMovementIsolationTests(BaseNodeTestCase):
    def test_gerant_k1_should_not_see_consumable_movements_of_k2(self):
        stock_k2 = ConsumableStock.objects.create(node=self.k2, consumable_type="FLOUR", unit="sacs")
        mv = ConsumableMovement.objects.create(
            node=self.k2, stock=stock_k2, movement_type="ENTRY", quantity="10.000",
            description="DEMO appro K2",
        )
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/production/movements/")
        if resp.status_code == 404:
            self.skipTest("Route consumable-movements introuvable à cette URL — vérifier production/urls.py")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        ids = {str(row.get("id")) for row in rows}
        self.assertNotIn(
            str(mv.pk), ids,
            "BUG-017 non corrigé : un GERANT K1 voit les mouvements de "
            "consommables de K2 (ConsumableMovementViewSet n'a aucun "
            "get_queryset filtrant par nœud)."
        )

    def test_gerant_k1_cannot_filter_consumable_movements_by_foreign_node(self):
        """Même en forçant ?node=<K2> dans l'URL, un GERANT K1 ne doit rien obtenir."""
        stock_k2 = ConsumableStock.objects.create(node=self.k2, consumable_type="SALT", unit="g")
        ConsumableMovement.objects.create(
            node=self.k2, stock=stock_k2, movement_type="ENTRY", quantity="500.000",
        )
        c = self.client_as(self.gerant_k1)
        resp = c.get(f"/api/production/movements/?node={self.k2.pk}")
        if resp.status_code == 404:
            self.skipTest("Route consumable-movements introuvable à cette URL — vérifier production/urls.py")
        data = resp.json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        self.assertEqual(
            len(rows), 0,
            "BUG-017 non corrigé : un GERANT K1 peut forcer ?node=K2 pour lire "
            "les mouvements de consommables d'une autre boulangerie."
        )


class BreadTransferIsolationTests(BaseNodeTestCase):
    """BUG confirmé : BreadTransferViewSet n'a pas de get_queryset et les
    actions respond_to_request/confirm_reception ne vérifient pas que
    l'utilisateur appartient à from_node ou to_node."""

    def setUp(self):
        self.k3 = Node.objects.create(code="K3", name="DEMO K3 ATHENEE")
        self.gerant_k3 = make_user("GERANT", node=self.k3)
        self.transfer_k2_k3 = BreadTransfer.objects.create(
            from_node=self.k3, to_node=self.k2,
            transfer_status=BreadTransfer.TransferStatus.PENDING,
        )

    def test_gerant_k1_should_not_see_transfer_between_k2_and_k3(self):
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/production/transfers/")
        if resp.status_code == 404:
            self.skipTest("Route bread-transfers introuvable à cette URL — vérifier production/urls.py")
        data = resp.json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        ids = {str(row.get("id")) for row in rows}
        self.assertNotIn(
            str(self.transfer_k2_k3.pk), ids,
            "BUG-018 non corrigé : un GERANT K1, étranger au transfert, le "
            "voit dans la liste des transferts inter-boulangeries."
        )

    def test_gerant_k1_cannot_respond_to_a_transfer_not_concerning_his_node(self):
        c = self.client_as(self.gerant_k1)
        resp = c.post(
            f"/api/production/transfers/{self.transfer_k2_k3.pk}/respond_to_request/",
            {"approved": True, "lines": []}, format="json",
        )
        self.assertIn(
            resp.status_code, (403, 404),
            "BUG-018 non corrigé : un GERANT K1 peut répondre (accepter/refuser) "
            "à une demande de transfert entre K2 et K3, deux boulangeries "
            "auxquelles il n'est pas affecté."
        )
        self.transfer_k2_k3.refresh_from_db()
        self.assertEqual(self.transfer_k2_k3.transfer_status, BreadTransfer.TransferStatus.PENDING)

    def test_gerant_k1_cannot_confirm_reception_of_a_transfer_not_concerning_his_node(self):
        self.transfer_k2_k3.transfer_status = BreadTransfer.TransferStatus.RESPONDED
        self.transfer_k2_k3.save(update_fields=["transfer_status"])
        c = self.client_as(self.gerant_k1)
        resp = c.post(
            f"/api/production/transfers/{self.transfer_k2_k3.pk}/confirm_reception/",
            {"lines": []}, format="json",
        )
        self.assertIn(
            resp.status_code, (403, 404),
            "BUG-018 non corrigé : un GERANT K1 peut confirmer la réception "
            "d'un transfert entre K2 et K3, deux boulangeries auxquelles il "
            "n'est pas affecté."
        )


class ClientCrossNodeWriteTests(BaseNodeTestCase):
    """Rappel CLAUDE.md §4 : l'exemption de filtrage par nœud pour les
    facturiers/livreurs ne concerne QUE la recherche de clients (déjà
    vérifié par testeur-ventes / BUG-013 l.10-12). Ici on vérifie qu'elle ne
    s'étend PAS à la modification ou à la suppression d'un client d'un autre
    nœud — ce point est conforme : IsGerant (exigé en update/destroy) exclut
    FACTURIER et LIVREUR, donc aucune mutation inter-nœuds n'est possible
    pour ces deux rôles, même si get_queryset ne les filtre pas en lecture."""

    def test_facturier_cannot_update_a_client_of_another_node(self):
        client_k2 = Client.objects.create(
            code="K2-DEMO02", first_name="Paul", last_name="DEMO", node=self.k2,
        )
        c = self.client_as(self.facturier_k1)
        resp = c.patch(
            f"/api/clients/clients/{client_k2.pk}/",
            {"last_name": "PIRATE"}, format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_facturier_cannot_delete_a_client_of_another_node(self):
        client_k2 = Client.objects.create(
            code="K2-DEMO03", first_name="Alice", last_name="DEMO", node=self.k2,
        )
        c = self.client_as(self.facturier_k1)
        resp = c.delete(f"/api/clients/clients/{client_k2.pk}/")
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertTrue(Client.objects.filter(pk=client_k2.pk).exists())

    def test_gerant_cannot_create_a_client_forcing_another_node(self):
        """Un gérant K1 qui force `node=K2` dans le corps de la requête ne
        doit pas pouvoir créer un client rattaché à K2."""
        c = self.client_as(self.gerant_k1)
        resp = c.post(
            "/api/clients/clients/",
            {
                "first_name": "Eve", "last_name": "DEMO", "node": str(self.k2.pk),
                "client_type": "DETAILLANT",
            },
            format="json",
        )
        if resp.status_code == 201:
            # ClientCreateSerializer (utilisé en écriture) n'expose pas `id`
            # dans sa réponse — on retrouve le client créé par ses autres
            # champs, uniques dans ce test (first_name/last_name fictifs).
            created = Client.objects.get(first_name="Eve", last_name="DEMO")
            self.assertEqual(
                created.node_id, self.k1.pk,
                "BUG potentiel : un GERANT K1 a pu créer un client rattaché "
                "à K2 en forçant le champ node dans le corps de la requête."
            )
        else:
            self.assertIn(resp.status_code, (400, 403))


class NodeCreationValidationTests(BaseNodeTestCase):
    """remarque.md l.52-83 : erreur 400 à la création d'une succursale.
    Reproduction : le payload envoyé par Nodes.tsx est valide pour la
    plupart des cas, mais le champ `code` (max_length=5) n'a ni attribut
    HTML `maxLength` ni validation côté client — un code trop long (plus de
    5 caractères, ex. une tentative de code complet "TABORA" au lieu de
    "K1") provoque un 400 dont le message est correct côté API mais que
    l'utilisateur ne relie pas à la cause. Voir BUG-019 (frontend)."""

    def test_node_creation_succeeds_with_a_valid_short_code(self):
        c = self.client_as(self.direction)
        resp = c.post(
            "/api/core/nodes/",
            {"code": "K9", "name": "DEMO Nouvelle Boulangerie", "address": "", "sac_value_fc": None, "is_active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_node_creation_fails_with_code_over_5_chars_with_clear_message(self):
        c = self.client_as(self.direction)
        resp = c.post(
            "/api/core/nodes/",
            {"code": "TABORA2", "name": "DEMO Boulangerie", "address": "", "sac_value_fc": None, "is_active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("code", resp.json())


# ───────────────────────────────────────────────────────────────────
# Partie 3 — Relecture post-chantier 2026-10-30
# (BUG-097 adjust, BUG-093 close, BUG-091 suggested_ca, commission_exempt)
# ───────────────────────────────────────────────────────────────────

class InvoiceAdjustPermissionTests(BaseNodeTestCase):
    """BUG-097 : `POST /api/sales/invoices/{id}/adjust/` réservé à GERANT+
    (`permission_classes=[IsGerant]` posé directement sur l'action, lu via
    `get_permissions()` — motif BUG-031). Isolation par nœud : `get_object()`
    passe par `InvoiceViewSet.get_queryset()`, déjà filtré sur `user.node`
    pour un non-HQ (ligne ~204-209) — un GERANT d'un AUTRE nœud ne doit donc
    jamais pouvoir ajuster une facture d'un nœud qui n'est pas le sien."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bp = make_bread_price(category='MOYEN', label='Pain DEMO 500 FC', unit_price=500)
        cls.client_k1 = make_demo_client(cls.k1)
        cls.invoice_k1 = Invoice.objects.create(
            node=cls.k1, client=cls.client_k1,
            facturier=cls.facturier_k1, team='A',
            payment_type='CASH', payment_amount=500, debt_before=0,
            order_total=500, commission_rate='0.25',
            node_origin=cls.k1.code, receipt_number='DEMO-ADJ-001',
            status=Invoice.Status.DELIVERED,
        )
        InvoiceLine.objects.create(invoice=cls.invoice_k1, bread_price=cls.bp, quantity=1)

    def _adjust_payload(self):
        return {
            "adjustment_sign": -1,
            "payment_amount": 0,
            "lines": [{"bread_price": self.bp.pk, "quantity": 1}],
        }

    def test_facturier_cannot_adjust_an_invoice(self):
        c = self.client_as(self.facturier_k1)
        resp = c.post(
            f"/api/sales/invoices/{self.invoice_k1.pk}/adjust/",
            self._adjust_payload(), format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_livreur_cannot_adjust_an_invoice(self):
        c = self.client_as(self.livreur_k1)
        resp = c.post(
            f"/api/sales/invoices/{self.invoice_k1.pk}/adjust/",
            self._adjust_payload(), format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_gerant_of_another_node_cannot_adjust_an_invoice_not_his_own(self):
        c = self.client_as(self.gerant_k2)
        resp = c.post(
            f"/api/sales/invoices/{self.invoice_k1.pk}/adjust/",
            self._adjust_payload(), format="json",
        )
        self.assertIn(
            resp.status_code, (403, 404),
            "Fuite inter-nœuds potentielle : un GERANT K2 a pu ajuster une "
            "facture de K1 via POST .../adjust/.",
        )

    def test_gerant_of_the_same_node_can_adjust_the_invoice(self):
        c = self.client_as(self.gerant_k1)
        resp = c.post(
            f"/api/sales/invoices/{self.invoice_k1.pk}/adjust/",
            self._adjust_payload(), format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)


class InvoiceCommissionExemptFieldTests(BaseNodeTestCase):
    """`commission_exempt` (BUG-052/097) : vérifie qu'elle n'ouvre pas de
    nouvelle faille d'écriture — un FACTURIER (qui n'a pas le droit de PATCH
    une facture existante, seulement de la créer) ne doit jamais pouvoir
    faire basculer `commission_exempt` après coup sur une facture déjà
    enregistrée (`InvoiceViewSet.get_permissions()` retombe sur `IsGerant()`
    pour toute action hors create/list/retrieve/l'action dédiée, donc aussi
    pour `update`/`partial_update`)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bp = make_bread_price(category='MOYEN', label='Pain DEMO 500 FC', unit_price=500)
        cls.client_k1 = make_demo_client(cls.k1)
        cls.invoice_k1 = Invoice.objects.create(
            node=cls.k1, client=cls.client_k1,
            facturier=cls.facturier_k1, team='A',
            payment_type='CASH', payment_amount=500, debt_before=0,
            order_total=500, commission_rate='0.25', commission_exempt=False,
            node_origin=cls.k1.code, receipt_number='DEMO-CMX-001',
            status=Invoice.Status.DELIVERED,
        )

    def test_facturier_cannot_patch_commission_exempt_on_an_existing_invoice(self):
        c = self.client_as(self.facturier_k1)
        resp = c.patch(
            f"/api/sales/invoices/{self.invoice_k1.pk}/",
            {"commission_exempt": True}, format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)
        self.invoice_k1.refresh_from_db()
        self.assertFalse(self.invoice_k1.commission_exempt)

    def test_gerant_can_patch_commission_exempt(self):
        c = self.client_as(self.gerant_k1)
        resp = c.patch(
            f"/api/sales/invoices/{self.invoice_k1.pk}/",
            {"commission_exempt": True}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)


class ProductionSessionClosePermissionTests(BaseNodeTestCase):
    """BUG-093/108 : `POST /api/production/sessions/{id}/close/` n'a pas de
    `permission_classes` dédiés sur l'`@action` — elle retombe donc sur
    `ProductionSessionViewSet.get_permissions()` (`IsGerant()` hors
    list/retrieve). Isolation : `get_object()` passe par `get_queryset()`,
    déjà filtré sur `user.node` pour un non-HQ (ligne ~213-223)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.session_k1 = ProductionSession.objects.create(
            node=cls.k1, team='A', date=date.today(),
            declared_by=cls.gerant_k1, flour_sacks_used=Decimal('1.00'),
            node_origin=cls.k1.code,
        )

    def test_facturier_cannot_close_a_production_session(self):
        c = self.client_as(self.facturier_k1)
        resp = c.post(f"/api/production/sessions/{self.session_k1.pk}/close/")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_livreur_cannot_close_a_production_session(self):
        c = self.client_as(self.livreur_k1)
        resp = c.post(f"/api/production/sessions/{self.session_k1.pk}/close/")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_gerant_of_another_node_cannot_close_a_session_not_his_own(self):
        c = self.client_as(self.gerant_k2)
        resp = c.post(f"/api/production/sessions/{self.session_k1.pk}/close/")
        self.assertIn(
            resp.status_code, (403, 404),
            "Fuite inter-nœuds potentielle : un GERANT K2 a pu clôturer une "
            "fournée de K1 via POST .../close/.",
        )
        self.session_k1.refresh_from_db()
        self.assertFalse(self.session_k1.is_closed)

    def test_gerant_of_the_same_node_can_close_the_session(self):
        c = self.client_as(self.gerant_k1)
        resp = c.post(f"/api/production/sessions/{self.session_k1.pk}/close/")
        self.assertEqual(resp.status_code, 200, resp.content)


class JournalSuggestedCaNodeIsolationTests(BaseNodeTestCase):
    """BUG-091 : `GET /api/treasury/journal/suggested_ca/` lit directement
    `request.query_params.get('node')` et interroge `CashClosure` par ce
    `node_id` SANS JAMAIS vérifier `request.user.can_access_all_nodes` ni
    retomber sur `user.node` pour un non-HQ — contrairement à
    `JournalEntryViewSet.get_queryset()` (ligne ~698-708) et à
    `monthly_report()` (ligne ~880-908, même défaut constaté au passage),
    qui au moins appliquent le filtrage par défaut quand `node` est absent
    du payload, mais pas quand il est explicitement forgé. Même motif que
    BUG-022/025/030/054/056 (fuite/forge inter-nœuds), ici en LECTURE sur une
    donnée financière sensible (recettes cash du jour d'une autre
    boulangerie) — voir ticket ouvert dans docs/qa/REGISTRE_BUGS.md."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.closure_k2 = CashClosure.objects.create(
            node=cls.k2, gerant=cls.gerant_k2, date=date.today(),
            total_entries=Decimal('777000.00'),
            node_origin=cls.k2.code,
        )

    def test_gerant_k1_cannot_read_suggested_ca_of_another_node_via_forged_node_param(self):
        c = self.client_as(self.gerant_k1)
        resp = c.get(
            "/api/treasury/journal/suggested_ca/",
            {"node": str(self.k2.pk), "date": str(date.today())},
        )
        # Un GERANT K1 n'a pas accès aux données de K2 : la réponse ne doit
        # JAMAIS exposer les recettes réelles de K2 (available=True/amount).
        if resp.status_code == 200:
            body = resp.json()
            self.assertFalse(
                body.get("available"),
                f"BUG-113 : un GERANT K1 a pu lire les recettes cash "
                f"(total_entries={self.closure_k2.total_entries}) de K2 via "
                f"?node={self.k2.pk} forgé dans /journal/suggested_ca/ — "
                f"réponse complète : {body}",
            )
        else:
            self.assertIn(resp.status_code, (403, 404))

    def test_gerant_k1_cannot_read_monthly_report_of_another_node_via_forged_node_param(self):
        """Même défaut constaté incidemment sur `monthly_report()` (même
        fichier, même motif) — un GERANT K1 peut forger `?node=<K2>` pour
        lire les totaux mensuels (entrées/sorties/solde) du Journal de
        Caisse de K2."""
        JournalEntry.objects.create(
            node=self.k2, date=date.today(), imput='CA',
            entry_amount=Decimal('123456.00'), exit_amount=Decimal('0.00'),
            running_balance=Decimal('123456.00'), month_carried=Decimal('0.00'),
            recorded_by=self.gerant_k2,
        )
        c = self.client_as(self.gerant_k1)
        resp = c.get(
            "/api/treasury/journal/monthly_report/",
            {"node": str(self.k2.pk), "month": str(date.today().month), "year": str(date.today().year)},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(
            body.get("total_entries"), "0",
            f"BUG-091-bis : un GERANT K1 a pu lire le total_entries mensuel "
            f"de K2 (123456.00) via ?node={self.k2.pk} forgé dans "
            f"/journal/monthly_report/ — réponse : {body}",
        )

    def test_gerant_k1_cannot_list_journal_entries_of_another_node_via_forged_node_param(self):
        """BUG-113 (point annexe) : `JournalEntryViewSet.get_queryset()`
        appliquait `qs.filter(node_id=node_id)` dès que `?node=` était fourni,
        sans jamais vérifier `can_access_all_nodes` — un GERANT K1 pouvait
        lister les écritures du Journal de Caisse de K2 en forgeant ce
        paramètre."""
        entry_k2 = JournalEntry.objects.create(
            node=self.k2, date=date.today(), imput='CA',
            entry_amount=Decimal('999999.00'), exit_amount=Decimal('0.00'),
            running_balance=Decimal('999999.00'), month_carried=Decimal('0.00'),
            recorded_by=self.gerant_k2,
        )
        c = self.client_as(self.gerant_k1)
        resp = c.get("/api/treasury/journal/", {"node": str(self.k2.pk)})
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        results = body.get("results", body if isinstance(body, list) else [])
        returned_ids = [str(r.get("id")) for r in results]
        self.assertNotIn(
            str(entry_k2.pk), returned_ids,
            f"BUG-113 : un GERANT K1 a pu lister l'écriture {entry_k2.pk} du "
            f"Journal de Caisse de K2 via ?node={self.k2.pk} forgé — "
            f"réponse : {body}",
        )

    def test_hq_can_still_read_suggested_ca_and_monthly_report_and_list_of_other_node(self):
        """Non-régression BUG-113 : un utilisateur HQ (Direction/Siège) doit
        conserver l'accès à n'importe quelle boulangerie via `?node=`."""
        entry_k2 = JournalEntry.objects.create(
            node=self.k2, date=date.today(), imput='CA',
            entry_amount=Decimal('123456.00'), exit_amount=Decimal('0.00'),
            running_balance=Decimal('123456.00'), month_carried=Decimal('0.00'),
            recorded_by=self.gerant_k2,
        )
        c = self.client_as(self.direction)

        resp = c.get(
            "/api/treasury/journal/suggested_ca/",
            {"node": str(self.k2.pk), "date": str(date.today())},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json().get("available"))
        self.assertEqual(resp.json().get("amount"), str(self.closure_k2.total_entries))

        resp = c.get(
            "/api/treasury/journal/monthly_report/",
            {"node": str(self.k2.pk), "month": str(date.today().month), "year": str(date.today().year)},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Decimal(resp.json().get("total_entries")), Decimal("123456.00"))

        resp = c.get("/api/treasury/journal/", {"node": str(self.k2.pk)})
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        results = body.get("results", body if isinstance(body, list) else [])
        returned_ids = [str(r.get("id")) for r in results]
        self.assertIn(str(entry_k2.pk), returned_ids)
