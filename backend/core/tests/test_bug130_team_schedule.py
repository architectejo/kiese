"""
Tests du chantier BUG-130 (demande client, remarque.md l.396) :
chaque boulangerie (`Node`) peut déclarer les créneaux horaires des
équipes A et B (`team_a_start_time`/`team_a_end_time`/`team_b_start_time`/
`team_b_end_time`), modifiables uniquement par le Siège, et une méthode
utilitaire `Node.active_team_at()` destinée à être réutilisée par le futur
chantier de détermination automatique de l'équipe active.

Numérotation : le ticket demandé par le coordinateur sous le nom "BUG-129"
existait déjà dans docs/qa/REGISTRE_BUGS.md pour une anomalie distincte
(`getErrorDetail` / tableau JSON nu, `ProductionSessionViewSet`) — voir la
note dans le ticket BUG-130 de REGISTRE_BUGS.md. Cette fonctionnalité a donc
été enregistrée sous BUG-130, et le futur chantier de détection automatique
d'équipe (mentionné par le coordinateur comme "BUG-130, pas encore lancé")
devra être renuméroté BUG-131 par le coordinateur.
"""
from datetime import date, datetime, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Node

User = get_user_model()


def make_user(role, node=None, username=None, **extra):
    username = username or f"user_{role.lower()}_{node.code if node else 'hq'}_{User.objects.count()}"
    return User.objects.create_user(
        username=username, password="Test#Pass1234", role=role, node=node, **extra
    )


class NodeTeamScheduleApiTests(TestCase):
    """Édition des 4 champs horaires via l'API `/api/core/nodes/`."""

    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code="K1", name="DEMO K1 TABORA")
        cls.direction = make_user("DIRECTION", node=None)
        cls.comptable = make_user("COMPTABLE", node=None)
        cls.gerant_k1 = make_user("GERANT", node=cls.k1)

    def client_as(self, user):
        c = APIClient()
        token = str(RefreshToken.for_user(user).access_token)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return c

    def test_direction_can_set_team_schedules_on_update(self):
        c = self.client_as(self.direction)
        resp = c.patch(
            f"/api/core/nodes/{self.k1.id}/",
            {
                "team_a_start_time": "06:00:00",
                "team_a_end_time": "13:00:00",
                "team_b_start_time": "13:00:00",
                "team_b_end_time": "20:00:00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.k1.refresh_from_db()
        self.assertEqual(self.k1.team_a_start_time, time(6, 0))
        self.assertEqual(self.k1.team_a_end_time, time(13, 0))
        self.assertEqual(self.k1.team_b_start_time, time(13, 0))
        self.assertEqual(self.k1.team_b_end_time, time(20, 0))

    def test_team_schedule_fields_returned_on_read_by_any_authenticated_user(self):
        self.k1.team_a_start_time = time(6, 0)
        self.k1.team_a_end_time = time(13, 0)
        self.k1.save()
        c = self.client_as(self.gerant_k1)
        resp = c.get(f"/api/core/nodes/{self.k1.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["team_a_start_time"], "06:00:00")
        self.assertEqual(resp.json()["team_a_end_time"], "13:00:00")

    def test_non_hq_gerant_cannot_edit_team_schedules(self):
        """Même garde que les autres champs de configuration de Node
        (`NodeViewSet.get_permissions` → `IsDirection` pour toute écriture,
        pas seulement `IsHeadquarters` — vérifié côté code : il n'existe pas
        de garde par champ, uniquement par action au niveau du viewset)."""
        c = self.client_as(self.gerant_k1)
        resp = c.patch(
            f"/api/core/nodes/{self.k1.id}/",
            {"team_a_start_time": "06:00:00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.k1.refresh_from_db()
        self.assertIsNone(self.k1.team_a_start_time)

    def test_comptable_cannot_edit_team_schedules_either(self):
        """IsHeadquarters inclut COMPTABLE, mais NodeViewSet restreint
        l'écriture à IsDirection (ADMIN/DIRECTION) pour tous ses champs :
        le COMPTABLE (HQ mais pas DIRECTION) ne peut donc pas non plus les
        modifier — cohérent avec le reste des champs de configuration de
        Node (ex. `sac_value_fc`, `is_active`)."""
        c = self.client_as(self.comptable)
        resp = c.patch(
            f"/api/core/nodes/{self.k1.id}/",
            {"team_a_start_time": "06:00:00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_creating_a_node_without_schedules_does_not_force_any_value(self):
        c = self.client_as(self.direction)
        resp = c.post(
            "/api/core/nodes/",
            {"code": "K9", "name": "DEMO Nouvelle Boulangerie", "address": "", "sac_value_fc": None, "is_active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        node = Node.objects.get(code="K9")
        self.assertIsNone(node.team_a_start_time)
        self.assertIsNone(node.team_a_end_time)
        self.assertIsNone(node.team_b_start_time)
        self.assertIsNone(node.team_b_end_time)


class NodeActiveTeamAtTests(TestCase):
    """`Node.active_team_at()` — utilitaire réutilisé par le futur chantier
    de détermination automatique de l'équipe active."""

    @classmethod
    def setUpTestData(cls):
        cls.node = Node.objects.create(
            code="K1", name="DEMO K1 TABORA",
            team_a_start_time=time(6, 0), team_a_end_time=time(13, 0),
            team_b_start_time=time(13, 0), team_b_end_time=time(20, 0),
        )
        cls.node_no_schedule = Node.objects.create(code="K2", name="DEMO K2 COQ")

    def test_time_inside_team_a_slot(self):
        self.assertEqual(self.node.active_team_at(time(9, 0)), 'A')

    def test_time_at_exact_start_of_team_a_slot_is_included(self):
        self.assertEqual(self.node.active_team_at(time(6, 0)), 'A')

    def test_time_at_exact_end_of_team_a_slot_belongs_to_team_b(self):
        # [start, end) : la borne de fin n'appartient pas au créneau — elle
        # est le début exact du créneau suivant dans ce scénario (13:00).
        self.assertEqual(self.node.active_team_at(time(13, 0)), 'B')

    def test_time_inside_team_b_slot(self):
        self.assertEqual(self.node.active_team_at(time(18, 0)), 'B')

    def test_time_outside_both_slots_returns_none(self):
        self.assertIsNone(self.node.active_team_at(time(22, 0)))
        self.assertIsNone(self.node.active_team_at(time(2, 0)))

    def test_undeclared_schedule_returns_none(self):
        self.assertIsNone(self.node_no_schedule.active_team_at(time(9, 0)))

    def test_accepts_aware_datetime(self):
        dt = timezone.make_aware(datetime(2026, 11, 9, 9, 0))
        self.assertEqual(self.node.active_team_at(dt), 'A')

    def test_default_uses_current_local_time(self):
        # Ne doit pas lever d'exception quand aucun argument n'est fourni.
        result = self.node.active_team_at()
        self.assertIn(result, ('A', 'B', None))

    def test_invalid_type_raises(self):
        with self.assertRaises(TypeError):
            self.node.active_team_at(date(2026, 11, 9))
