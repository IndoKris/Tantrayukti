"""Tests for the Device/Reading models, token issue and the digital-twin state."""

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from spaces.models import Building, Floor, Organisation, Room
from telemetry.models import Device, Reading, hash_token


def make_room(name="Lab") -> Room:
    org = Organisation.objects.create(name=f"Org {name}")
    building = Building.objects.create(organisation=org, name=f"B {name}")
    floor = Floor.objects.create(building=building, name="Ground", level=0)
    return Room.objects.create(floor=floor, name=name, area_sqm=Decimal("20.00"), occupancy=4)


class DeviceTokenTests(TestCase):
    def setUp(self):
        self.room = make_room()

    def test_a_device_gets_a_token_on_creation(self):
        device = Device.objects.create(room=self.room, name="Meter")
        self.assertTrue(device.token_hash)
        self.assertEqual(len(device.token_hash), 64)
        self.assertTrue(device.token_prefix)
        self.assertIsNotNone(device.token_issued_at)

    def test_the_raw_token_is_never_stored(self):
        device = Device.objects.create(room=self.room, name="Meter")
        raw = device.rotate_token()

        stored = [str(value) for value in Device.objects.filter(pk=device.pk).values()[0].values()]
        self.assertNotIn(raw, stored)
        self.assertEqual(device.token_hash, hash_token(raw))

    def test_rotating_invalidates_the_previous_token(self):
        device = Device.objects.create(room=self.room, name="Meter")
        first = device.rotate_token()
        second = device.rotate_token()

        self.assertNotEqual(first, second)
        self.assertEqual(device.token_hash, hash_token(second))
        self.assertNotEqual(device.token_hash, hash_token(first))

    def test_token_hashes_are_unique_across_devices(self):
        a = Device.objects.create(room=self.room, name="A")
        b = Device.objects.create(room=self.room, name="B")
        self.assertNotEqual(a.token_hash, b.token_hash)

    def test_device_names_are_unique_within_a_room(self):
        Device.objects.create(room=self.room, name="Meter")
        with self.assertRaises(IntegrityError):
            Device.objects.create(room=self.room, name="Meter")


class DigitalTwinTests(TestCase):
    def setUp(self):
        self.room = make_room()
        self.device = Device.objects.create(
            room=self.room, name="Meter", sample_interval_seconds=30
        )

    def test_a_device_that_has_never_reported_is_not_online(self):
        self.assertEqual(self.device.status, "never-seen")
        self.assertFalse(self.device.is_online)
        self.assertIsNone(self.device.seconds_since_last_seen)

    def test_a_recently_seen_device_is_online(self):
        self.device.last_seen_at = timezone.now()
        self.assertEqual(self.device.status, "online")
        self.assertTrue(self.device.is_online)

    def test_a_silent_device_goes_offline(self):
        self.device.last_seen_at = timezone.now() - timedelta(minutes=30)
        self.assertEqual(self.device.status, "offline")
        self.assertFalse(self.device.is_online)

    def test_an_inactive_device_reports_disabled(self):
        self.device.last_seen_at = timezone.now()
        self.device.is_active = False
        self.assertEqual(self.device.status, "disabled")
        self.assertFalse(self.device.is_online)

    def test_the_offline_threshold_tracks_the_sample_interval(self):
        slow = Device.objects.create(
            room=self.room, name="Slow", sample_interval_seconds=600
        )
        self.assertEqual(slow.offline_after, timedelta(seconds=1800))

    def test_a_very_short_interval_still_gets_a_grace_period(self):
        """A 1 s interval must not mark the device offline after 3 s."""
        fast = Device.objects.create(room=self.room, name="Fast", sample_interval_seconds=1)
        self.assertEqual(fast.offline_after, timedelta(minutes=2))

    def test_buffered_reading_count_counts_only_late_arrivals(self):
        now = timezone.now()
        Reading.objects.create(
            device=self.device,
            timestamp=now,
            active_power_w=Decimal("100"),
            energy_wh=Decimal("0.83"),
            was_buffered=False,
        )
        Reading.objects.create(
            device=self.device,
            timestamp=now - timedelta(minutes=10),
            active_power_w=Decimal("100"),
            energy_wh=Decimal("0.83"),
            was_buffered=True,
        )
        self.assertEqual(self.device.buffered_reading_count(), 1)


class ReadingTests(TestCase):
    def setUp(self):
        self.room = make_room()
        self.device = Device.objects.create(room=self.room, name="Meter")

    def test_one_reading_per_device_and_timestamp(self):
        now = timezone.now()
        Reading.objects.create(
            device=self.device,
            timestamp=now,
            active_power_w=Decimal("100"),
            energy_wh=Decimal("0.83"),
        )
        with self.assertRaises(IntegrityError):
            Reading.objects.create(
                device=self.device,
                timestamp=now,
                active_power_w=Decimal("200"),
                energy_wh=Decimal("1.66"),
            )

    def test_two_devices_may_share_a_timestamp(self):
        now = timezone.now()
        other = Device.objects.create(room=self.room, name="Other")
        for device in (self.device, other):
            Reading.objects.create(
                device=device,
                timestamp=now,
                active_power_w=Decimal("100"),
                energy_wh=Decimal("0.83"),
            )
        self.assertEqual(Reading.objects.count(), 2)

    def test_energy_kwh_converts_from_wh(self):
        reading = Reading.objects.create(
            device=self.device,
            timestamp=timezone.now(),
            active_power_w=Decimal("1500"),
            energy_wh=Decimal("2500.0000"),
        )
        self.assertEqual(reading.energy_kwh, Decimal("2.5"))

    def test_the_organisation_is_reachable_from_a_device(self):
        self.assertEqual(self.device.organisation, self.room.organisation)
