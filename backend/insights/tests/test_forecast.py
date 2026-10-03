"""Tests for the forecast and ML-metrics endpoints."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Role
from spaces.models import Building, Floor, Membership, Organisation, Room
from telemetry.models import Device, Reading

User = get_user_model()


class ForecastEndpointTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organisation.objects.create(name="Org")
        building = Building.objects.create(organisation=cls.org, name="HQ")
        floor = Floor.objects.create(building=building, name="Ground", level=0)
        cls.room = Room.objects.create(floor=floor, name="Lab", area_sqm=Decimal("20"))
        cls.device = Device.objects.create(room=cls.room, name="Mains", kind=Device.Kind.MAINS)

        cls.other_org = Organisation.objects.create(name="Other")
        other_building = Building.objects.create(organisation=cls.other_org, name="B")
        other_floor = Floor.objects.create(building=other_building, name="G", level=0)
        other_room = Room.objects.create(floor=other_floor, name="R")
        cls.other_device = Device.objects.create(room=other_room, name="Theirs")

        cls.user = User.objects.create_user(
            username="member", email="m@example.com", password="pw", role=Role.MEMBER
        )
        Membership.objects.create(user=cls.user, organisation=cls.org)

    def seed_hours(self, hours: int):
        """Readings on whole hours, so each lands in its own rollup bucket."""
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        for index in range(hours):
            Reading.objects.create(
                device=self.device,
                timestamp=now - timedelta(hours=hours - index),
                active_power_w=Decimal("1000.00"),
                energy_wh=Decimal("1000.0000"),
            )

    def url(self, device=None):
        return reverse("insights:device-forecast", args=[(device or self.device).pk])

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_a_foreign_device_is_404(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url(self.other_device)).status_code, 404)

    def test_too_little_history_is_a_409_with_a_reason(self):
        """A dashboard must never be handed an invented curve."""
        self.seed_hours(3)
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["hours_available"], 3)
        self.assertEqual(body["hours_required"], 24)
        self.assertIn("how_to_fix", body)

    def test_a_forecast_is_returned_when_there_is_enough_history(self):
        self.seed_hours(30)
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url())

        # 409 is acceptable only when no model artifact exists in this checkout.
        if response.status_code == 409:
            self.assertIn("No trained forecasting model", response.json()["detail"])
            return

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(len(body["forecast"]["points"]), 24)
        self.assertEqual(body["forecast"]["unit"], "kWh per hour")
        self.assertEqual(len(body["history"]["points"]), 24)

    def test_the_forecast_states_its_model_and_caveats(self):
        self.seed_hours(30)
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url())
        if response.status_code == 409:
            self.skipTest("No trained model artifact in this checkout.")

        forecast = response.json()["forecast"]
        self.assertIn("backend", forecast["model"])
        self.assertIn("is_fallback", forecast["model"])
        self.assertTrue(any("recursively" in c for c in forecast["caveats"]))

    def test_forecast_energy_is_never_negative(self):
        self.seed_hours(30)
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url())
        if response.status_code == 409:
            self.skipTest("No trained model artifact in this checkout.")

        for point in response.json()["forecast"]["points"]:
            self.assertGreaterEqual(float(point["energy_kwh"]), 0.0)


class MlMetricsEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="member2", email="m2@example.com", password="pw"
        )
        self.url = reverse("insights:ml-metrics")

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_metrics_are_served_from_the_artifact_file(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)

        if response.status_code == 409:
            self.assertIn("how_to_fix", response.json())
            return

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("generated_by", body)
        self.assertIn("honesty_note", body)

    def test_the_honesty_note_rules_out_hand_written_numbers(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        if response.status_code == 409:
            self.skipTest("No metrics.json in this checkout.")

        note = response.json()["honesty_note"]
        self.assertIn("never accuracy", note)
