"""
Tests for the device API: organisation scoping, role-gated writes, the status
endpoint and token rotation.
"""

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


def room_in(org: Organisation, name="Lab") -> Room:
    building = Building.objects.create(organisation=org, name=f"B {name}")
    floor = Floor.objects.create(building=building, name="Ground", level=0)
    return Room.objects.create(floor=floor, name=name, area_sqm=Decimal("20"), occupancy=4)


class DeviceApiTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organisation.objects.create(name="Org A")
        cls.org_b = Organisation.objects.create(name="Org B")
        cls.room_a = room_in(cls.org_a, "A Lab")
        cls.room_b = room_in(cls.org_b, "B Lab")
        cls.device_a = Device.objects.create(room=cls.room_a, name="A Meter")
        cls.device_b = Device.objects.create(room=cls.room_b, name="B Meter")

        def member(username, role, org):
            user = User.objects.create_user(
                username=username, email=f"{username}@example.com", password="pw", role=role
            )
            Membership.objects.create(user=user, organisation=org)
            return user

        cls.member_a = member("member_a", Role.MEMBER, cls.org_a)
        cls.manager_a = member("manager_a", Role.MANAGER, cls.org_a)
        cls.admin_a = member("admin_a", Role.ADMIN, cls.org_a)


class ScopingTests(DeviceApiTestCase):
    def test_anonymous_access_is_rejected(self):
        self.assertEqual(self.client.get(reverse("telemetry:device-list")).status_code, 401)

    def test_a_member_sees_only_devices_in_their_organisation(self):
        self.client.force_authenticate(self.member_a)
        names = [
            row["name"] for row in self.client.get(reverse("telemetry:device-list")).json()["results"]
        ]
        self.assertEqual(names, ["A Meter"])

    def test_a_foreign_device_is_404(self):
        self.client.force_authenticate(self.member_a)
        response = self.client.get(reverse("telemetry:device-detail", args=[self.device_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_a_foreign_device_status_is_404(self):
        self.client.force_authenticate(self.member_a)
        response = self.client.get(reverse("telemetry:device-status", args=[self.device_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_filtering_by_room_narrows_the_list(self):
        self.client.force_authenticate(self.member_a)
        other = Room.objects.create(floor=self.room_a.floor, name="Other")
        Device.objects.create(room=other, name="Other Meter")

        response = self.client.get(reverse("telemetry:device-list"), {"room": self.room_a.pk})
        self.assertEqual(response.json()["count"], 1)

    def test_the_token_is_never_exposed_by_the_list_or_detail_route(self):
        self.client.force_authenticate(self.member_a)
        body = self.client.get(reverse("telemetry:device-detail", args=[self.device_a.pk])).json()
        self.assertNotIn("token", body)
        self.assertNotIn("token_hash", body)
        self.assertIn("token_prefix", body)


class WritePermissionTests(DeviceApiTestCase):
    def test_a_member_cannot_register_a_device(self):
        self.client.force_authenticate(self.member_a)
        response = self.client.post(
            reverse("telemetry:device-list"), {"room": self.room_a.pk, "name": "New"}
        )
        self.assertEqual(response.status_code, 403)

    def test_a_manager_can_register_a_device_and_sees_the_token_once(self):
        self.client.force_authenticate(self.manager_a)
        response = self.client.post(
            reverse("telemetry:device-list"), {"room": self.room_a.pk, "name": "New Meter"}
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["token"])
        self.assertTrue(body["token"].startswith(body["token_prefix"]))

    def test_a_registered_device_can_immediately_post_a_reading(self):
        """The token handed back at registration must actually work."""
        self.client.force_authenticate(self.manager_a)
        token = self.client.post(
            reverse("telemetry:device-list"), {"room": self.room_a.pk, "name": "Fresh"}
        ).json()["token"]

        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Device {token}")
        response = self.client.post(
            reverse("telemetry:reading-ingest"),
            {"timestamp": timezone.now().isoformat(), "active_power_w": "100.00"},
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_a_manager_cannot_rotate_a_token(self):
        self.client.force_authenticate(self.manager_a)
        response = self.client.post(
            reverse("telemetry:device-rotate-token", args=[self.device_a.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_an_admin_can_rotate_a_token(self):
        self.client.force_authenticate(self.admin_a)
        before = self.device_a.token_hash

        response = self.client.post(
            reverse("telemetry:device-rotate-token", args=[self.device_a.pk])
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["token"])

        self.device_a.refresh_from_db()
        self.assertNotEqual(self.device_a.token_hash, before)


class StatusEndpointTests(DeviceApiTestCase):
    def setUp(self):
        self.client.force_authenticate(self.member_a)
        self.url = reverse("telemetry:device-status", args=[self.device_a.pk])

    def test_a_device_that_never_reported_says_so(self):
        body = self.client.get(self.url).json()
        self.assertEqual(body["status"], "never-seen")
        self.assertFalse(body["is_online"])
        self.assertIsNone(body["seconds_since_last_seen"])

    def test_a_recently_seen_device_is_online(self):
        self.device_a.last_seen_at = timezone.now()
        self.device_a.save()

        body = self.client.get(self.url).json()
        self.assertEqual(body["status"], "online")
        self.assertTrue(body["is_online"])
        self.assertLess(body["seconds_since_last_seen"], 5)

    def test_a_silent_device_is_offline(self):
        self.device_a.last_seen_at = timezone.now() - timedelta(hours=1)
        self.device_a.save()
        self.assertEqual(self.client.get(self.url).json()["status"], "offline")

    def test_the_status_reports_both_buffer_counts(self):
        """What the device claims it holds, and what the server saw arrive late."""
        self.device_a.reported_buffer_count = 7
        self.device_a.save()
        Reading.objects.create(
            device=self.device_a,
            timestamp=timezone.now() - timedelta(minutes=30),
            active_power_w=Decimal("100"),
            energy_wh=Decimal("0.83"),
            was_buffered=True,
        )

        body = self.client.get(self.url).json()
        self.assertEqual(body["reported_buffer_count"], 7)
        self.assertEqual(body["buffered_count_24h"], 1)
        self.assertEqual(body["reading_count"], 1)

    def test_the_status_explains_its_own_offline_threshold(self):
        body = self.client.get(self.url).json()
        self.assertEqual(body["sample_interval_seconds"], 30)
        self.assertEqual(body["offline_after_seconds"], 120)

    def test_timestamps_match_the_detail_route_exactly(self):
        """
        The status route builds its response by hand, so it must render datetimes
        the same way DRF's serializers do - otherwise one API emits two offsets
        for the same instant.
        """
        self.device_a.last_seen_at = timezone.now()
        self.device_a.save()

        status_body = self.client.get(self.url).json()
        detail_body = self.client.get(
            reverse("telemetry:device-detail", args=[self.device_a.pk])
        ).json()

        self.assertEqual(status_body["last_seen_at"], detail_body["last_seen_at"])


class DeviceReadingsRouteTests(DeviceApiTestCase):
    def test_readings_are_returned_newest_first(self):
        now = timezone.now().replace(microsecond=0)
        for index in range(3):
            Reading.objects.create(
                device=self.device_a,
                timestamp=now - timedelta(minutes=index),
                active_power_w=Decimal(100 + index),
                energy_wh=Decimal("0.83"),
            )

        self.client.force_authenticate(self.member_a)
        body = self.client.get(reverse("telemetry:device-readings", args=[self.device_a.pk])).json()

        timestamps = [row["timestamp"] for row in body["results"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        self.assertEqual(body["count"], 3)

    def test_readings_of_a_foreign_device_are_not_reachable(self):
        self.client.force_authenticate(self.member_a)
        response = self.client.get(
            reverse("telemetry:device-readings", args=[self.device_b.pk])
        )
        self.assertEqual(response.status_code, 404)
