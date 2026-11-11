"""
BUG-161 / B1 : `core.workday` (journée de travail de relève à relève) et
`Node.handover_time` (défaut 12:00, exposé par le sérialiseur).
"""
from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Node
from core.workday import business_date, next_handover, workday_bounds

User = get_user_model()


def at(y, m, d, hh, mm=0, ss=0):
    """Datetime aware en heure locale du projet."""
    return timezone.make_aware(datetime(y, m, d, hh, mm, ss))


class BusinessDateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.node = Node.objects.create(code="K1", name="DEMO K1")

    def test_default_handover_is_noon(self):
        self.assertEqual(self.node.handover_time, time(12, 0))
        self.node.refresh_from_db()
        self.assertEqual(self.node.handover_time, time(12, 0))

    def test_just_before_and_after_handover(self):
        self.assertEqual(business_date(self.node, at(2026, 11, 11, 11, 59, 59)), date(2026, 11, 10))
        self.assertEqual(business_date(self.node, at(2026, 11, 11, 12, 0, 0)), date(2026, 11, 11))

    def test_midnight_belongs_to_previous_workday(self):
        self.assertEqual(business_date(self.node, at(2026, 11, 12, 0, 0, 0)), date(2026, 11, 11))
        self.assertEqual(business_date(self.node, at(2026, 11, 11, 23, 59, 59)), date(2026, 11, 11))

    def test_month_and_year_boundary(self):
        self.assertEqual(business_date(self.node, at(2027, 1, 1, 3)), date(2026, 12, 31))

    def test_handover_at_midnight_equals_localdate(self):
        """Test d'équivalence exigé : relève 00:00 => business_date == date locale."""
        self.node.handover_time = time(0, 0)
        for hh, mm, ss in [(0, 0, 0), (0, 0, 1), (5, 30, 0), (12, 0, 0), (23, 59, 59)]:
            instant = at(2026, 11, 11, hh, mm, ss)
            self.assertEqual(
                business_date(self.node, instant), timezone.localtime(instant).date(),
                f"{hh}:{mm}:{ss}",
            )

    def test_handover_late_evening(self):
        self.node.handover_time = time(23, 30)
        self.assertEqual(business_date(self.node, at(2026, 11, 11, 23, 29, 59)), date(2026, 11, 10))
        self.assertEqual(business_date(self.node, at(2026, 11, 11, 23, 30, 0)), date(2026, 11, 11))
        self.assertEqual(business_date(self.node, at(2026, 11, 11, 8, 0)), date(2026, 11, 10))

    def test_utc_instant_is_converted_to_local_time(self):
        """Africa/Kinshasa = UTC+1 : 10:59:59 UTC = 11:59:59 local (avant relève)."""
        utc = timezone.get_fixed_timezone(0)
        self.assertEqual(
            business_date(self.node, datetime(2026, 11, 11, 10, 59, 59, tzinfo=utc)),
            date(2026, 11, 10),
        )
        self.assertEqual(
            business_date(self.node, datetime(2026, 11, 11, 11, 0, 0, tzinfo=utc)),
            date(2026, 11, 11),
        )

    def test_default_instant_is_now(self):
        self.assertEqual(
            business_date(self.node), business_date(self.node, timezone.now())
        )

    def test_isolation_between_nodes(self):
        k2 = Node.objects.create(code="K2", name="DEMO K2", handover_time=time(6, 0))
        instant = at(2026, 11, 11, 9, 0)
        self.assertEqual(business_date(self.node, instant), date(2026, 11, 10))  # relève 12:00
        self.assertEqual(business_date(k2, instant), date(2026, 11, 11))         # relève 06:00


class WorkdayBoundsTests(TestCase):
    def test_bounds_consistent_with_business_date(self):
        for handover in (time(0, 0), time(12, 0), time(23, 30), time(6, 15)):
            node = Node(code="X", name="x", handover_time=handover)
            work_date = date(2026, 11, 11)
            start, end = workday_bounds(node, work_date)
            self.assertTrue(timezone.is_aware(start) and timezone.is_aware(end))
            self.assertEqual(end - start, timedelta(hours=24))
            self.assertEqual(timezone.localtime(start).time(), handover)
            self.assertEqual(business_date(node, start), work_date)
            self.assertEqual(business_date(node, end - timedelta(seconds=1)), work_date)
            self.assertEqual(business_date(node, end), work_date + timedelta(days=1))
            self.assertEqual(
                business_date(node, start - timedelta(seconds=1)), work_date - timedelta(days=1)
            )

    def test_bounds_noon(self):
        node = Node(code="X", name="x")
        start, end = workday_bounds(node, date(2026, 11, 11))
        self.assertEqual(start, at(2026, 11, 11, 12))
        self.assertEqual(end, at(2026, 11, 12, 12))

    def test_midnight_handover_bounds_are_calendar_day(self):
        node = Node(code="X", name="x", handover_time=time(0, 0))
        start, end = workday_bounds(node, date(2026, 11, 11))
        self.assertEqual(start, at(2026, 11, 11, 0))
        self.assertEqual(end, at(2026, 11, 12, 0))


class NextHandoverTests(TestCase):
    def setUp(self):
        self.node = Node(code="X", name="x")  # 12:00

    def test_before_handover_is_today(self):
        self.assertEqual(next_handover(self.node, at(2026, 11, 11, 11, 59, 59)), at(2026, 11, 11, 12))

    def test_at_or_after_handover_is_tomorrow(self):
        self.assertEqual(next_handover(self.node, at(2026, 11, 11, 12, 0, 0)), at(2026, 11, 12, 12))
        self.assertEqual(next_handover(self.node, at(2026, 11, 11, 18)), at(2026, 11, 12, 12))

    def test_after_midnight_before_handover(self):
        self.assertEqual(next_handover(self.node, at(2026, 11, 12, 0, 30)), at(2026, 11, 12, 12))

    def test_next_handover_ends_current_workday(self):
        instant = at(2026, 11, 11, 15)
        _, end = workday_bounds(self.node, business_date(self.node, instant))
        self.assertEqual(next_handover(self.node, instant), end)

    def test_isolation_between_nodes(self):
        other = Node(code="Y", name="y", handover_time=time(6, 0))
        instant = at(2026, 11, 11, 9)
        self.assertEqual(next_handover(self.node, instant), at(2026, 11, 11, 12))
        self.assertEqual(next_handover(other, instant), at(2026, 11, 12, 6))


class NodeHandoverSerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code="K1", name="DEMO K1")
        cls.direction = User.objects.create_user(
            username="dir_b161", password="Test#Pass1234", role="DIRECTION", node=None)
        cls.gerant = User.objects.create_user(
            username="ger_b161", password="Test#Pass1234", role="GERANT", node=cls.k1)

    def client_as(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return c

    def test_read_returns_default(self):
        resp = self.client_as(self.gerant).get(f"/api/core/nodes/{self.k1.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["handover_time"], "12:00:00")

    def test_direction_can_write(self):
        resp = self.client_as(self.direction).patch(
            f"/api/core/nodes/{self.k1.id}/", {"handover_time": "06:30:00"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.k1.refresh_from_db()
        self.assertEqual(self.k1.handover_time, time(6, 30))

    def test_gerant_cannot_write(self):
        resp = self.client_as(self.gerant).patch(
            f"/api/core/nodes/{self.k1.id}/", {"handover_time": "06:30:00"}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.k1.refresh_from_db()
        self.assertEqual(self.k1.handover_time, time(12, 0))

    def test_invalid_and_null_values_rejected(self):
        c = self.client_as(self.direction)
        for bad in ("25:00:00", "abc", None):
            resp = c.patch(f"/api/core/nodes/{self.k1.id}/", {"handover_time": bad}, format="json")
            self.assertEqual(resp.status_code, 400, (bad, resp.content))
        self.k1.refresh_from_db()
        self.assertEqual(self.k1.handover_time, time(12, 0))

    def test_create_without_handover_uses_default(self):
        resp = self.client_as(self.direction).post(
            "/api/core/nodes/", {"code": "K9", "name": "DEMO K9"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(Node.objects.get(code="K9").handover_time, time(12, 0))

    def test_legacy_team_fields_untouched(self):
        resp = self.client_as(self.gerant).get(f"/api/core/nodes/{self.k1.id}/")
        for f in ("team_a_start_time", "team_a_end_time", "team_b_start_time", "team_b_end_time"):
            self.assertIn(f, resp.json())
