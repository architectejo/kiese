"""
BUG-149 — Réinitialisation globale des données (bouton Superuser).

remarque.md (après l.404). Voir core/reset.py pour la liste exacte
conservée/supprimée et son argumentaire.

Rappel règle transversale : ces tests passent exclusivement par
`manage.py test` (base de test éphémère) — jamais contre `backend/db.sqlite3`.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import (
    Node, Config, ExpenseCategory, ActivityLog, SystemNotification, ColisDistribution,
)
from core.testing import make_bread_price
from clients.models import Client
from sales.models import Invoice, InvoiceLine
from production.models import ProductionSession, DailyTeamAssignment
from treasury.models import LocalExpense
from commissions.models import CommissionPeriod, ClientCommission
from sync.models import DebtMovement, NodeAuthToken

User = get_user_model()

URL = "/api/core/reset-data/"
PASSWORD = "Super#Pass1234"


def make_user(role, node=None, username=None, is_superuser=False, **extra):
    username = username or f"user_{role.lower()}_{User.objects.count()}"
    user = User.objects.create_user(
        username=username, password=PASSWORD, role=role, node=node, **extra
    )
    if is_superuser:
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=['is_superuser', 'is_staff'])
    return user


def client_as(user):
    c = APIClient()
    token = str(RefreshToken.for_user(user).access_token)
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


class ResetDataPermissionTests(TestCase):
    """Accès réservé strictement à `is_superuser=True`."""

    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code="K1", name="DEMO K1 TABORA")
        # Compte DIRECTION *nommé* mais SANS is_superuser — même motif que
        # le ticket (« même @pierre, DIRECTION, n'y a PAS accès »).
        cls.direction_not_super = make_user("DIRECTION", node=None, username="demo_pierre")
        cls.admin_not_super = make_user("ADMIN", node=None, username="demo_admin")
        cls.real_superuser = make_user(
            "DIRECTION", node=None, username="demo_superuser", is_superuser=True
        )

    def test_direction_role_without_superuser_flag_is_refused_get(self):
        resp = client_as(self.direction_not_super).get(URL)
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_admin_role_without_superuser_flag_is_refused_get(self):
        resp = client_as(self.admin_not_super).get(URL)
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_direction_role_without_superuser_flag_is_refused_post(self):
        resp = client_as(self.direction_not_super).post(
            URL, {"confirm_phrase": "SUPPRIMER TOUT", "password": PASSWORD}, format="json"
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_real_superuser_is_accepted_get(self):
        resp = client_as(self.real_superuser).get(URL)
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_anonymous_is_refused(self):
        resp = APIClient().get(URL)
        self.assertIn(resp.status_code, (401, 403))


class ResetDataScenarioTests(TestCase):
    """
    Scénario complet : crée des données fictives dans chaque catégorie à
    supprimer, exécute le reset, vérifie que tout a disparu sauf
    Config/Node/User/Client (fiche conservée), et que les champs dérivés
    du client sont bien remis à zéro/Normal.
    """

    @classmethod
    def setUpTestData(cls):
        cls.node = Node.objects.create(code="K1", name="DEMO K1 TABORA")
        cls.superuser = make_user(
            "DIRECTION", node=None, username="demo_superuser", is_superuser=True
        )
        cls.gerant = make_user("GERANT", node=cls.node, username="demo_gerant")
        cls.bread_price = make_bread_price(category="DEMO", label="DEMO Pain 500 FC", unit_price=500)
        cls.expense_category = ExpenseCategory.objects.create(code="DEMO", label="DEMO Dépense")
        # Matérialise le singleton Config AVANT les tests (comme en
        # production réelle où il existe déjà) — sinon `core.middleware.
        # OnlineOfflineRoutingMiddleware` le crée lazily à la première
        # requête de ce test et déclenche `on_config_save` (signal
        # pré-existant, hors périmètre BUG-149), qui insère une
        # SystemNotification APRÈS le retour de la vue — artefact de test,
        # pas un effet du reset lui-même.
        Config.get_instance()

    def setUp(self):
        self.client_obj = Client.objects.create(
            node=self.node, node_origin=self.node.code,
            first_name="Jean", last_name="DEMO Client",
            current_debt=Decimal("12345.00"),
            total_breads_received=77,
            category=Client.Category.RISK,
        )

        # sales.Invoice + InvoiceLine
        self.invoice = Invoice.objects.create(
            node=self.node, node_origin=self.node.code, client=self.client_obj,
            order_total=Decimal("5000.00"), payment_amount=Decimal("5000.00"),
        )
        InvoiceLine.objects.create(invoice=self.invoice, bread_price=self.bread_price, quantity=10)

        # production.ProductionSession
        self.session = ProductionSession.objects.create(
            node=self.node, node_origin=self.node.code,
            team=ProductionSession.Team.A, date=date(2026, 11, 1),
            declared_by=self.gerant,
        )

        # BUG-161 (B2) : désignation de l'équipe de service
        DailyTeamAssignment.objects.create(
            node=self.node, work_date=date(2026, 11, 1), team='A', assigned_by=self.gerant,
        )

        # treasury.LocalExpense
        self.expense = LocalExpense.objects.create(
            node=self.node, node_origin=self.node.code, gerant=self.gerant,
            description="DEMO Achat bois", amount=Decimal("3000.00"),
            category=self.expense_category, date=date(2026, 11, 1),
        )

        # commissions.CommissionPeriod + ClientCommission
        self.period = CommissionPeriod.objects.create(
            node=self.node, node_origin=self.node.code, month=11, year=2026,
        )
        self.commission = ClientCommission.objects.create(
            period=self.period, client=self.client_obj, node_origin=self.node.code,
            order_value=Decimal("10000.00"),
        )

        # sync.DebtMovement — doit être supprimé pour que current_debt=0
        # ne soit jamais reconstitué par un recalcul ultérieur.
        self.debt_movement = DebtMovement.objects.create(
            client=self.client_obj, node_origin=self.node.code,
            amount=Decimal("12345.00"), kind=DebtMovement.Kind.ORDER,
        )

        # sync.NodeAuthToken — doit être CONSERVÉ (infrastructure).
        self.auth_token, _raw = NodeAuthToken.issue_for_node(self.node)

        # core.ColisDistribution, ActivityLog, SystemNotification
        self.colis = ColisDistribution.objects.create(
            node=self.node, year=2026, beneficiary_label="DEMO Employé",
        )
        self.old_activity_log = ActivityLog.objects.create(
            action="DEMO_OLD_ACTION", description="Ancienne action",
        )
        self.old_notification = SystemNotification.objects.create(
            title="DEMO alerte", message="message",
        )

    def _post_reset(self):
        return client_as(self.superuser).post(
            URL,
            {"confirm_phrase": "SUPPRIMER TOUT", "password": PASSWORD},
            format="json",
        )

    def test_get_preview_never_deletes_anything(self):
        resp = client_as(self.superuser).get(URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertGreaterEqual(data.get("invoices", 0), 1)
        self.assertGreaterEqual(data.get("production_sessions", 0), 1)
        self.assertGreaterEqual(data.get("clients_to_reset", 0), 1)

        # Rien n'a été supprimé par ce simple GET.
        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())
        self.assertTrue(ProductionSession.objects.filter(pk=self.session.pk).exists())
        self.assertTrue(LocalExpense.objects.filter(pk=self.expense.pk).exists())
        self.assertTrue(ClientCommission.objects.filter(pk=self.commission.pk).exists())
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())
        client_fresh = Client.objects.get(pk=self.client_obj.pk)
        self.assertEqual(client_fresh.current_debt, Decimal("12345.00"))

    def test_post_without_confirm_phrase_is_refused_and_deletes_nothing(self):
        resp = client_as(self.superuser).post(
            URL, {"password": PASSWORD}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())

    def test_post_with_wrong_password_is_refused_and_deletes_nothing(self):
        resp = client_as(self.superuser).post(
            URL,
            {"confirm_phrase": "SUPPRIMER TOUT", "password": "mauvais-mot-de-passe"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())
        self.assertTrue(ProductionSession.objects.filter(pk=self.session.pk).exists())

    def test_post_with_wrong_confirm_phrase_is_refused_and_deletes_nothing(self):
        resp = client_as(self.superuser).post(
            URL,
            {"confirm_phrase": "supprimer tout", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())

    def test_full_reset_deletes_transactional_data_and_resets_client_fields(self):
        resp = self._post_reset()
        self.assertEqual(resp.status_code, 200, resp.content)

        # Transactionnel : tout supprimé.
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(InvoiceLine.objects.exists())
        self.assertFalse(ProductionSession.objects.exists())
        self.assertFalse(DailyTeamAssignment.objects.exists())
        self.assertFalse(LocalExpense.objects.exists())
        self.assertFalse(CommissionPeriod.objects.exists())
        self.assertFalse(ClientCommission.objects.exists())
        self.assertFalse(DebtMovement.objects.exists())
        self.assertFalse(ColisDistribution.objects.exists())
        self.assertFalse(
            SystemNotification.objects.exists(),
            list(SystemNotification.objects.values_list('title', 'message')),
        )
        # L'ancien ActivityLog a disparu...
        self.assertFalse(ActivityLog.objects.filter(pk=self.old_activity_log.pk).exists())

        # ... mais une NOUVELLE entrée journalise l'opération elle-même.
        self.assertTrue(
            ActivityLog.objects.filter(action='GLOBAL_DATA_RESET').exists()
        )

        # Conservé : Node, User, BreadPrice, ExpenseCategory, NodeAuthToken.
        self.assertTrue(Node.objects.filter(pk=self.node.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.gerant.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.superuser.pk).exists())
        self.assertTrue(
            type(self.bread_price).objects.filter(pk=self.bread_price.pk).exists()
        )
        self.assertTrue(ExpenseCategory.objects.filter(pk=self.expense_category.pk).exists())
        self.assertTrue(NodeAuthToken.objects.filter(pk=self.auth_token.pk).exists())

        # Client : fiche conservée, champs dérivés remis à zéro/Normal.
        client_fresh = Client.objects.get(pk=self.client_obj.pk)
        self.assertEqual(client_fresh.current_debt, Decimal("0.00"))
        self.assertEqual(client_fresh.total_breads_received, 0)
        self.assertEqual(client_fresh.category, Client.Category.NORMAL)
        self.assertEqual(client_fresh.first_name, "Jean")
        self.assertEqual(client_fresh.last_name, "DEMO Client")

        # Réponse : décompte de ce qui a été effectivement supprimé.
        data = resp.json()
        self.assertGreaterEqual(data["invoices"], 1)
        self.assertGreaterEqual(data["production_sessions"], 1)
        self.assertGreaterEqual(data["clients_to_reset"], 1)

    def test_reset_is_atomic_on_failure(self):
        """
        Un mot de passe erroné (ou une phrase erronée) ne doit laisser
        AUCUNE trace partielle — déjà couvert par les tests ci-dessus, mais
        on vérifie ici explicitement qu'aucune des catégories n'a bougé
        d'un seul enregistrement après un refus.
        """
        before = {
            "invoices": Invoice.objects.count(),
            "sessions": ProductionSession.objects.count(),
            "expenses": LocalExpense.objects.count(),
            "commissions": ClientCommission.objects.count(),
            "debt_movements": DebtMovement.objects.count(),
        }
        resp = client_as(self.superuser).post(
            URL, {"confirm_phrase": "SUPPRIMER TOUT", "password": "faux"}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        after = {
            "invoices": Invoice.objects.count(),
            "sessions": ProductionSession.objects.count(),
            "expenses": LocalExpense.objects.count(),
            "commissions": ClientCommission.objects.count(),
            "debt_movements": DebtMovement.objects.count(),
        }
        self.assertEqual(before, after)
