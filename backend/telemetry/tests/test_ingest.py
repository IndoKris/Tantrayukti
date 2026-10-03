"""
Tests for `POST /api/readings/`: device-token auth, validation, single and batch
uploads, chronological backfill and idempotent replay.
"""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from spaces.models import Building, Floor, Organisation, Room
from telemetry.models import Device, Reading


class IngestTestCase(APITestCase):
    def setUp(self):
        org = Organisation.objects.create(name="Org")
        building = Building.objects.create(organisation=org, name="HQ")
        floor = Floor.objects.create(building=building, name="Ground", level=0)
        self.room = Room.objects.create(floor=floor, name="Lab", area_sqm=Decimal("20"))
        self.device = Device.objects.create(
            room=self.room, name="Meter", sample_interval_seconds=30
        )
        self.token = self.device.rotate_token()
        self.url = reverse("telemetry:reading-ingest")

    def authenticate(self, token=None):
        self.client.credentials(HTTP_AUTHORIZATION=f"Device {token or self.token}")

    def reading(self, **overrides) -> dict:
        payload = {
            "timestamp": timezone.now().isoformat(),
            "active_power_w": "1200.00",
            "energy_wh": "10.0000",
            "voltage_v": "231.40",
            "current_a": "5.400",
            "power_factor": "0.960",
        }
        payload.update(overrides)
        return payload


class DeviceAuthenticationTests(IngestTestCase):
    def test_no_token_is_rejected(self):
        self.assertEqual(self.client.post(self.url, self.reading()).status_code, 401)

    def test_an_unknown_token_is_rejected(self):
        self.authenticate("totally-made-up-token")
        self.assertEqual(self.client.post(self.url, self.reading()).status_code, 401)

    def test_the_x_device_token_header_also_works(self):
        """Some firmware cannot set Authorization conveniently."""
        self.client.credentials(HTTP_X_DEVICE_TOKEN=self.token)
        self.assertEqual(self.client.post(self.url, self.reading()).status_code, 201)

    def test_a_disabled_device_is_refused(self):
        self.device.is_active = False
        self.device.save()
        self.authenticate()
        self.assertEqual(self.client.post(self.url, self.reading()).status_code, 401)

    def test_a_rotated_token_stops_working_immediately(self):
        old = self.token
        self.device.rotate_token()
        self.authenticate(old)
        self.assertEqual(self.client.post(self.url, self.reading()).status_code, 401)

    def test_a_user_jwt_cannot_post_readings(self):
        """Ingestion is device-only, so a stolen user token cannot forge telemetry."""
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_superuser(
            username="root", email="r@example.com", password="pw"
        )
        self.client.force_authenticate(user=user)
        self.assertEqual(self.client.post(self.url, self.reading()).status_code, 403)


class SingleReadingTests(IngestTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate()

    def test_a_single_reading_is_stored(self):
        response = self.client.post(self.url, self.reading())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created"], 1)
        self.assertEqual(Reading.objects.count(), 1)

    def test_all_electrical_fields_are_persisted(self):
        self.client.post(self.url, self.reading())
        reading = Reading.objects.get()
        self.assertEqual(reading.active_power_w, Decimal("1200.00"))
        self.assertEqual(reading.energy_wh, Decimal("10.0000"))
        self.assertEqual(reading.voltage_v, Decimal("231.40"))
        self.assertEqual(reading.current_a, Decimal("5.400"))
        self.assertEqual(reading.power_factor, Decimal("0.960"))

    def test_optional_fields_may_be_omitted(self):
        payload = {"timestamp": timezone.now().isoformat(), "active_power_w": "500.00"}
        self.assertEqual(self.client.post(self.url, payload).status_code, 201)

    def test_energy_is_derived_from_power_when_omitted(self):
        """1200 W over a 30 s interval is 10 Wh."""
        payload = {"timestamp": timezone.now().isoformat(), "active_power_w": "1200.00"}
        self.client.post(self.url, payload)
        self.assertEqual(Reading.objects.get().energy_wh, Decimal("10.0000"))

    def test_a_supplied_energy_value_wins_over_the_derived_one(self):
        self.client.post(self.url, self.reading(energy_wh="9.5000"))
        self.assertEqual(Reading.objects.get().energy_wh, Decimal("9.5000"))


class ValidationTests(IngestTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate()

    def assertRejected(self, **overrides):
        response = self.client.post(self.url, self.reading(**overrides))
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Reading.objects.count(), 0)

    def test_negative_power_is_rejected(self):
        self.assertRejected(active_power_w="-5.00")

    def test_negative_energy_is_rejected(self):
        self.assertRejected(energy_wh="-1.0000")

    def test_an_impossible_voltage_is_rejected(self):
        self.assertRejected(voltage_v="999.00")

    def test_a_power_factor_above_one_is_rejected(self):
        self.assertRejected(power_factor="1.500")

    def test_a_future_timestamp_is_rejected(self):
        self.assertRejected(timestamp=(timezone.now() + timedelta(hours=2)).isoformat())

    def test_a_small_clock_skew_is_tolerated(self):
        """Devices drift; a minute ahead must not break ingestion."""
        response = self.client.post(
            self.url, self.reading(timestamp=(timezone.now() + timedelta(minutes=1)).isoformat())
        )
        self.assertEqual(response.status_code, 201)

    def test_a_timestamp_beyond_the_backfill_window_is_rejected(self):
        self.assertRejected(timestamp=(timezone.now() - timedelta(days=120)).isoformat())

    def test_power_above_apparent_power_is_rejected(self):
        """Real power cannot exceed V x A; this catches a mis-scaled CT clamp."""
        self.assertRejected(voltage_v="230.00", current_a="1.000", active_power_w="5000.00")

    def test_a_missing_timestamp_is_rejected(self):
        response = self.client.post(self.url, {"active_power_w": "100.00"})
        self.assertEqual(response.status_code, 400)

    def test_an_empty_batch_is_rejected(self):
        response = self.client.post(self.url, {"readings": []}, format="json")
        self.assertEqual(response.status_code, 400)


class BatchAndBackfillTests(IngestTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate()
        self.now = timezone.now().replace(microsecond=0)

    def batch_rows(self, count=5, step_seconds=30, oldest_first=True):
        rows = [
            {
                "timestamp": (self.now - timedelta(seconds=step_seconds * i)).isoformat(),
                "active_power_w": f"{100 + i * 10}.00",
                "energy_wh": "0.8333",
            }
            for i in range(count)
        ]
        return list(reversed(rows)) if oldest_first else rows

    def test_a_bare_list_is_accepted(self):
        response = self.client.post(self.url, self.batch_rows(), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created"], 5)

    def test_the_wrapped_form_is_accepted(self):
        response = self.client.post(
            self.url, {"readings": self.batch_rows()}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Reading.objects.count(), 5)

    def test_out_of_order_uploads_are_stored_chronologically(self):
        """A device flushing its buffer may upload newest-first."""
        self.client.post(self.url, self.batch_rows(oldest_first=False), format="json")

        stored = list(Reading.objects.order_by("id").values_list("timestamp", flat=True))
        self.assertEqual(stored, sorted(stored))

    def test_replaying_a_batch_creates_no_duplicates(self):
        rows = self.batch_rows()
        self.client.post(self.url, rows, format="json")
        response = self.client.post(self.url, rows, format="json")

        self.assertEqual(Reading.objects.count(), 5)
        self.assertEqual(response.json()["created"], 0)
        self.assertEqual(response.json()["duplicates"], 5)

    def test_a_partial_replay_stores_only_the_new_rows(self):
        rows = self.batch_rows(count=5)
        self.client.post(self.url, rows[:3], format="json")
        response = self.client.post(self.url, rows, format="json")

        self.assertEqual(response.json()["created"], 2)
        self.assertEqual(response.json()["duplicates"], 3)
        self.assertEqual(Reading.objects.count(), 5)

    def test_duplicate_timestamps_inside_one_batch_are_rejected(self):
        row = self.reading()
        response = self.client.post(self.url, [row, row], format="json")
        self.assertEqual(response.status_code, 400)

    def test_late_arrivals_are_flagged_as_buffered(self):
        old = (self.now - timedelta(hours=3)).isoformat()
        self.client.post(self.url, [self.reading(timestamp=old)], format="json")
        self.assertTrue(Reading.objects.get().was_buffered)

    def test_live_readings_are_not_flagged_as_buffered(self):
        self.client.post(self.url, [self.reading()], format="json")
        self.assertFalse(Reading.objects.get().was_buffered)

    def test_a_backfill_does_not_move_last_reading_at_backwards(self):
        self.client.post(self.url, [self.reading()], format="json")
        self.device.refresh_from_db()
        newest = self.device.last_reading_at

        old = (self.now - timedelta(hours=5)).isoformat()
        self.client.post(self.url, [self.reading(timestamp=old)], format="json")

        self.device.refresh_from_db()
        self.assertEqual(self.device.last_reading_at, newest)


class DigitalTwinUpdateTests(IngestTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate()

    def test_ingestion_marks_the_device_seen_and_online(self):
        self.assertEqual(self.device.status, "never-seen")
        self.client.post(self.url, self.reading())

        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_seen_at)
        self.assertTrue(self.device.is_online)

    def test_the_device_reported_buffer_count_is_recorded(self):
        self.client.post(
            self.url,
            {"readings": [self.reading()], "buffer_count": 42},
            format="json",
        )
        self.device.refresh_from_db()
        self.assertEqual(self.device.reported_buffer_count, 42)

    def test_the_firmware_version_is_recorded(self):
        self.client.post(
            self.url,
            {"readings": [self.reading()], "firmware_version": "1.4.2"},
            format="json",
        )
        self.device.refresh_from_db()
        self.assertEqual(self.device.firmware_version, "1.4.2")

    def test_the_response_carries_the_twin_so_the_device_can_trim_its_buffer(self):
        body = self.client.post(self.url, self.reading()).json()
        self.assertEqual(body["received"], 1)
        self.assertIn("device", body)
        self.assertEqual(body["device"]["status"], "online")
