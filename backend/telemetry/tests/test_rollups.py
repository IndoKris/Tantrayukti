"""
Tests for the usage rollups and `GET /api/usage/`.

Two layers:

* hand-built readings, where the expected totals are known exactly, so an
  arithmetic or bucketing mistake is unambiguous;
* a run of the real Phase 7 simulator, which proves the rollups survive the data
  the rest of the project actually produces. That class skips with a clear
  reason if the simulator cannot be imported, so the suite stays runnable if the
  repo layout changes.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Role
from spaces.models import Building, Floor, Membership, Organisation, Room
from telemetry import rollups
from telemetry.models import Device, Reading

User = get_user_model()

IST = ZoneInfo("Asia/Kolkata")


def local(year, month, day, hour=0, minute=0) -> datetime:
    """Build an aware datetime in the project's timezone, which buckets follow."""
    return datetime(year, month, day, hour, minute, tzinfo=IST)


class RollupFixture:
    """A room with a mains meter and two appliance meters covering the same load."""

    @classmethod
    def build(cls, test):
        test.org = Organisation.objects.create(name="Org")
        test.building = Building.objects.create(organisation=test.org, name="HQ")
        test.floor = Floor.objects.create(building=test.building, name="Ground", level=0)
        test.room = Room.objects.create(
            floor=test.floor, name="Lab", area_sqm=Decimal("50.00"), occupancy=10
        )
        test.other_room = Room.objects.create(
            floor=test.floor, name="Store", area_sqm=Decimal("10.00"), occupancy=1
        )

        test.mains = Device.objects.create(
            room=test.room, name="Mains", kind=Device.Kind.MAINS
        )
        test.appliance_a = Device.objects.create(
            room=test.room, name="AC", kind=Device.Kind.APPLIANCE
        )
        test.appliance_b = Device.objects.create(
            room=test.room, name="Lights", kind=Device.Kind.APPLIANCE
        )
        test.store_appliance = Device.objects.create(
            room=test.other_room, name="Freezer", kind=Device.Kind.APPLIANCE
        )

        test.user = User.objects.create_user(
            username="member", email="m@example.com", password="pw", role=Role.MANAGER
        )
        Membership.objects.create(user=test.user, organisation=test.org)

    @staticmethod
    def add(device, when, power_w, energy_wh):
        return Reading.objects.create(
            device=device,
            timestamp=when,
            active_power_w=Decimal(str(power_w)),
            energy_wh=Decimal(str(energy_wh)),
        )


class TimeBucketTests(TestCase):
    """Bucketing arithmetic, with totals chosen so mistakes are obvious."""

    def setUp(self):
        RollupFixture.build(self)
        # Four readings on 2 March IST: two in hour 10, two in hour 11.
        for minute, energy in ((0, 100), (30, 200), (60, 400), (90, 800)):
            RollupFixture.add(
                self.mains,
                local(2026, 3, 2, 10) + timedelta(minutes=minute),
                power_w=1000 + minute,
                energy_wh=energy,
            )

    def readings(self):
        return rollups.readings_for(
            Device.objects.filter(pk=self.mains.pk),
            local(2026, 3, 1),
            local(2026, 3, 4),
        )

    def test_hourly_buckets_split_by_local_hour(self):
        series = rollups.time_series(self.readings(), "hour")
        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["energy_wh"], Decimal("300.0000"))
        self.assertEqual(series[1]["energy_wh"], Decimal("1200.0000"))

    def test_daily_bucket_sums_the_whole_local_day(self):
        series = rollups.time_series(self.readings(), "day")
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["energy_wh"], Decimal("1500.0000"))

    def test_monthly_bucket_sums_the_month(self):
        series = rollups.time_series(self.readings(), "month")
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["energy_wh"], Decimal("1500.0000"))

    def test_energy_is_reported_in_both_wh_and_kwh(self):
        series = rollups.time_series(self.readings(), "day")
        self.assertEqual(series[0]["energy_wh"], Decimal("1500.0000"))
        self.assertEqual(series[0]["energy_kwh"], Decimal("1.500000"))

    def test_power_aggregates_are_mean_peak_and_min(self):
        series = rollups.time_series(self.readings(), "day")
        row = series[0]
        self.assertEqual(row["peak_power_w"], Decimal("1090.00"))
        self.assertEqual(row["min_power_w"], Decimal("1000.00"))
        self.assertEqual(row["mean_power_w"], Decimal("1045.00"))
        self.assertEqual(row["sample_count"], 4)

    def test_buckets_are_ordered_oldest_first(self):
        series = rollups.time_series(self.readings(), "hour")
        self.assertEqual([row["bucket"] for row in series], sorted(row["bucket"] for row in series))

    def test_empty_buckets_are_omitted_not_zero_filled(self):
        """Zero energy and "no data" are different facts; the UI must distinguish them."""
        series = rollups.time_series(self.readings(), "hour")
        self.assertEqual(len(series), 2)  # not 72 hours of zeros

    def test_a_window_with_no_readings_yields_an_empty_series(self):
        readings = rollups.readings_for(
            Device.objects.filter(pk=self.mains.pk), local(2026, 1, 1), local(2026, 1, 2)
        )
        self.assertEqual(rollups.time_series(readings, "hour"), [])
        self.assertEqual(rollups.totals(readings)["energy_wh"], Decimal("0.0000"))

    def test_the_window_end_is_exclusive(self):
        """A reading exactly at `to` belongs to the next window, not this one."""
        boundary = local(2026, 3, 2, 12)
        RollupFixture.add(self.mains, boundary, power_w=500, energy_wh=50)

        readings = rollups.readings_for(
            Device.objects.filter(pk=self.mains.pk), local(2026, 3, 1), boundary
        )
        self.assertEqual(rollups.totals(readings)["energy_wh"], Decimal("1500.0000"))

    def test_an_unknown_period_is_rejected(self):
        with self.assertRaises(rollups.ScopeError):
            rollups.time_series(self.readings(), "fortnight")


class LocalDayBoundaryTests(TestCase):
    """
    A local day must not be a UTC day.

    IST is UTC+5:30, so 23:30 local on 2 March is 18:00 UTC on 2 March, while
    00:30 local on 3 March is 19:00 UTC on 2 March. Bucketing in UTC would put
    both in the same day and smear time-of-day tariffs across midnight.
    """

    def setUp(self):
        RollupFixture.build(self)
        RollupFixture.add(self.mains, local(2026, 3, 2, 23, 30), 1000, 500)
        RollupFixture.add(self.mains, local(2026, 3, 3, 0, 30), 1000, 700)

    def test_the_two_readings_fall_on_different_local_days(self):
        self.assertEqual(settings.TIME_ZONE, "Asia/Kolkata")
        readings = rollups.readings_for(
            Device.objects.filter(pk=self.mains.pk), local(2026, 3, 1), local(2026, 3, 5)
        )
        series = rollups.time_series(readings, "day")

        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["energy_wh"], Decimal("500.0000"))
        self.assertEqual(series[1]["energy_wh"], Decimal("700.0000"))


class MeteringSelectionTests(TestCase):
    """
    The double-counting guard.

    The room has a mains meter reading 1000 Wh and two appliance meters reading
    600 + 400 Wh for the same load. Summing everything gives 2000 Wh, which is
    twice the truth.
    """

    def setUp(self):
        RollupFixture.build(self)
        when = local(2026, 3, 2, 10)
        RollupFixture.add(self.mains, when, 1000, 1000)
        RollupFixture.add(self.appliance_a, when, 600, 600)
        RollupFixture.add(self.appliance_b, when, 400, 400)

    def total_for(self, metering: str) -> Decimal:
        devices, applied = rollups.select_devices(
            Device.objects.filter(room=self.room), metering
        )
        readings = rollups.readings_for(devices, local(2026, 3, 1), local(2026, 3, 4))
        self.assertTrue(applied)
        return rollups.totals(readings)["energy_wh"]

    def test_auto_prefers_the_mains_meter(self):
        self.assertEqual(self.total_for("auto"), Decimal("1000.0000"))

    def test_auto_reports_that_it_used_mains(self):
        _, applied = rollups.select_devices(Device.objects.filter(room=self.room), "auto")
        self.assertEqual(applied, "mains")

    def test_summing_everything_double_counts(self):
        """Documents the trap `auto` exists to avoid."""
        self.assertEqual(self.total_for("all"), Decimal("2000.0000"))

    def test_appliance_mode_sums_only_appliances(self):
        self.assertEqual(self.total_for("appliance"), Decimal("1000.0000"))

    def test_auto_falls_back_to_appliances_when_there_is_no_mains(self):
        devices = Device.objects.filter(room=self.other_room)
        RollupFixture.add(self.store_appliance, local(2026, 3, 2, 10), 250, 250)

        selected, applied = rollups.select_devices(devices, "auto")
        self.assertEqual(applied, "appliance")
        readings = rollups.readings_for(selected, local(2026, 3, 1), local(2026, 3, 4))
        self.assertEqual(rollups.totals(readings)["energy_wh"], Decimal("250.0000"))

    def test_an_unknown_metering_mode_is_rejected(self):
        with self.assertRaises(rollups.ScopeError):
            rollups.select_devices(Device.objects.all(), "guesswork")


class GroupingTests(TestCase):
    def setUp(self):
        RollupFixture.build(self)
        when = local(2026, 3, 2, 10)
        RollupFixture.add(self.appliance_a, when, 600, 600)
        RollupFixture.add(self.appliance_b, when, 400, 400)
        RollupFixture.add(self.store_appliance, when, 250, 250)

    def readings(self):
        return rollups.readings_for(
            Device.objects.filter(kind=Device.Kind.APPLIANCE),
            local(2026, 3, 1),
            local(2026, 3, 4),
        )

    def test_by_device_totals_each_device_highest_first(self):
        rows = rollups.by_device(self.readings())
        self.assertEqual([row["device_name"] for row in rows], ["AC", "Lights", "Freezer"])
        self.assertEqual(rows[0]["energy_wh"], Decimal("600.0000"))

    def test_by_device_carries_the_room_and_kind(self):
        rows = rollups.by_device(self.readings())
        self.assertEqual(rows[0]["room_name"], "Lab")
        self.assertEqual(rows[0]["device_kind"], Device.Kind.APPLIANCE)

    def test_by_room_sums_the_devices_in_each_room(self):
        rows = rollups.by_room(self.readings())
        self.assertEqual([row["room_name"] for row in rows], ["Lab", "Store"])
        self.assertEqual(rows[0]["energy_wh"], Decimal("1000.0000"))
        self.assertEqual(rows[1]["energy_wh"], Decimal("250.0000"))


class ScopeResolutionTests(TestCase):
    def setUp(self):
        RollupFixture.build(self)
        self.visible = Organisation.objects.filter(pk=self.org.pk)

    def resolve(self, **params):
        return rollups.resolve_scope(params, self.visible)

    def test_no_scope_means_every_visible_device(self):
        scope = self.resolve()
        self.assertEqual(scope.kind, "all")
        self.assertEqual(scope.devices.count(), 4)

    def test_a_room_scope_selects_that_room(self):
        scope = self.resolve(space=f"room:{self.room.pk}")
        self.assertEqual(scope.kind, "room")
        self.assertEqual(scope.devices.count(), 3)

    def test_a_building_scope_selects_every_room_beneath_it(self):
        scope = self.resolve(space=f"building:{self.building.pk}")
        self.assertEqual(scope.devices.count(), 4)

    def test_an_organisation_scope_selects_everything(self):
        scope = self.resolve(space=f"organisation:{self.org.pk}")
        self.assertEqual(scope.devices.count(), 4)

    def test_explicit_named_parameters_work_too(self):
        scope = self.resolve(room=str(self.room.pk))
        self.assertEqual(scope.kind, "room")
        self.assertEqual(scope.devices.count(), 3)

    def test_a_device_scope_selects_one_device(self):
        scope = self.resolve(device=str(self.mains.pk))
        self.assertEqual(scope.kind, "device")
        self.assertEqual(scope.devices.count(), 1)

    def test_the_scope_carries_area_and_occupancy_for_normalisation(self):
        scope = self.resolve(space=f"room:{self.room.pk}")
        self.assertEqual(scope.area_sqm, Decimal("50.00"))
        self.assertEqual(scope.occupancy, 10)

    def test_a_malformed_space_is_rejected(self):
        with self.assertRaises(rollups.ScopeError):
            self.resolve(space="building")

    def test_an_unknown_space_kind_is_rejected(self):
        with self.assertRaises(rollups.ScopeError):
            self.resolve(space="wing:1")

    def test_a_non_numeric_id_is_rejected(self):
        with self.assertRaises(rollups.ScopeError):
            self.resolve(space="room:abc")

    def test_an_invisible_organisation_is_rejected(self):
        """Scoping must not leak another organisation through an id."""
        other = Organisation.objects.create(name="Other")
        with self.assertRaises(rollups.ScopeError):
            self.resolve(space=f"organisation:{other.pk}")

    def test_an_invisible_room_is_rejected(self):
        other = Organisation.objects.create(name="Other")
        building = Building.objects.create(organisation=other, name="B")
        floor = Floor.objects.create(building=building, name="G", level=0)
        room = Room.objects.create(floor=floor, name="R")
        with self.assertRaises(rollups.ScopeError):
            self.resolve(space=f"room:{room.pk}")


class WindowTests(TestCase):
    def test_defaults_differ_per_period(self):
        now = timezone.now()
        for period, span in (("hour", 1), ("day", 30), ("month", 365)):
            start, end = rollups.resolve_window({}, period)
            self.assertAlmostEqual((end - start).days, span, delta=1)
            self.assertAlmostEqual((end - now).total_seconds(), 0, delta=10)

    def test_explicit_dates_are_honoured(self):
        start, end = rollups.resolve_window(
            {"from": "2026-03-01", "to": "2026-03-05"}, "day"
        )
        self.assertEqual(start, local(2026, 3, 1))
        self.assertEqual(end, local(2026, 3, 5))

    def test_a_bare_date_is_interpreted_in_the_project_timezone(self):
        start, _ = rollups.resolve_window({"from": "2026-03-01"}, "day")
        self.assertEqual(start.utcoffset(), timedelta(hours=5, minutes=30))

    def test_an_offset_aware_datetime_is_preserved(self):
        start, _ = rollups.resolve_window({"from": "2026-03-01T00:00:00+00:00"}, "day")
        self.assertEqual(start.utcoffset(), timedelta(0))

    def test_a_reversed_window_is_rejected(self):
        with self.assertRaises(rollups.ScopeError):
            rollups.resolve_window({"from": "2026-03-05", "to": "2026-03-01"}, "day")

    def test_an_unparseable_date_is_rejected(self):
        with self.assertRaises(rollups.ScopeError):
            rollups.resolve_window({"from": "last tuesday"}, "day")

    def test_an_unknown_period_is_rejected_before_indexing_the_default_table(self):
        """`DEFAULT_WINDOWS[period]` would raise KeyError (a 500) rather than a 400."""
        with self.assertRaises(rollups.ScopeError):
            rollups.resolve_window({}, "fortnight")

    def test_an_unknown_period_is_rejected_even_when_the_window_is_explicit(self):
        with self.assertRaises(rollups.ScopeError):
            rollups.resolve_window({"from": "2026-03-01", "to": "2026-03-05"}, "fortnight")


class UsageEndpointTests(APITestCase):
    def setUp(self):
        RollupFixture.build(self)
        when = local(2026, 3, 2, 10)
        RollupFixture.add(self.mains, when, 1000, 1000)
        RollupFixture.add(self.appliance_a, when, 600, 600)
        RollupFixture.add(self.appliance_b, when, 400, 400)
        self.url = reverse("telemetry:usage")
        self.window = {"from": "2026-03-01", "to": "2026-03-04"}

    def get(self, **params):
        self.client.force_authenticate(self.user)
        return self.client.get(self.url, {**self.window, **params})

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_the_default_response_is_an_hourly_series(self):
        body = self.get().json()
        self.assertEqual(body["period"], "hour")
        self.assertEqual(body["group_by"], "time")
        self.assertEqual(len(body["results"]), 1)

    def test_the_response_states_the_metering_mode_it_applied(self):
        """No figure appears without saying how it was derived."""
        body = self.get(space=f"room:{self.room.pk}").json()
        self.assertEqual(body["metering"]["requested"], "auto")
        self.assertEqual(body["metering"]["applied"], "mains")
        self.assertEqual(body["metering"]["device_count"], 1)

    def test_auto_metering_does_not_double_count(self):
        body = self.get(space=f"room:{self.room.pk}", period="day").json()
        self.assertEqual(Decimal(body["totals"]["energy_wh"]), Decimal("1000.0000"))

    def test_metering_all_shows_the_double_counted_figure(self):
        body = self.get(space=f"room:{self.room.pk}", period="day", metering="all").json()
        self.assertEqual(Decimal(body["totals"]["energy_wh"]), Decimal("2000.0000"))
        self.assertEqual(body["metering"]["applied"], "all")

    def test_the_scope_is_echoed_with_area_and_occupancy(self):
        body = self.get(space=f"room:{self.room.pk}").json()
        self.assertEqual(body["scope"]["kind"], "room")
        self.assertEqual(body["scope"]["label"], "HQ / Ground / Lab")
        self.assertEqual(Decimal(body["scope"]["area_sqm"]), Decimal("50.00"))
        self.assertEqual(body["scope"]["occupancy"], 10)

    def test_the_window_is_echoed(self):
        body = self.get().json()
        self.assertIn("2026-03-01", body["window"]["from"])
        self.assertIn("2026-03-04", body["window"]["to"])

    def test_group_by_device_returns_per_device_rows(self):
        body = self.get(group_by="device", metering="appliance").json()
        self.assertIsNone(body["period"])
        self.assertEqual([row["device_name"] for row in body["results"]], ["AC", "Lights"])

    def test_group_by_room_returns_per_room_rows(self):
        body = self.get(group_by="room", metering="appliance").json()
        self.assertEqual(body["results"][0]["room_name"], "Lab")

    def test_a_daily_period_is_accepted(self):
        body = self.get(period="day").json()
        self.assertEqual(body["period"], "day")

    def test_an_unknown_period_is_a_400(self):
        response = self.get(period="fortnight")
        self.assertEqual(response.status_code, 400)
        self.assertIn("period", response.json()["detail"])

    def test_an_unknown_period_is_a_400_with_no_window_given(self):
        """
        Regression: validation used to run after the default window was looked
        up, so this path raised KeyError and returned 500 instead of 400. The
        other period test passed because it always supplied from/to.
        """
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url, {"period": "fortnight"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("period", response.json()["detail"])

    def test_every_documented_period_is_accepted_with_no_window_given(self):
        self.client.force_authenticate(self.user)
        for period in rollups.PERIODS:
            response = self.client.get(self.url, {"period": period})
            self.assertEqual(response.status_code, 200, f"{period}: {response.content}")

    def test_an_unknown_group_by_is_a_400(self):
        response = self.get(group_by="colour")
        self.assertEqual(response.status_code, 400)

    def test_a_malformed_space_is_a_400_not_a_500(self):
        response = self.get(space="building")
        self.assertEqual(response.status_code, 400)

    def test_another_organisation_cannot_be_queried(self):
        other = Organisation.objects.create(name="Other")
        response = self.get(space=f"organisation:{other.pk}")
        self.assertEqual(response.status_code, 400)
        self.assertIn("No visible", response.json()["detail"])

    def test_a_user_with_no_membership_sees_no_energy(self):
        outsider = User.objects.create_user(
            username="outsider", email="o@example.com", password="pw"
        )
        self.client.force_authenticate(outsider)
        body = self.client.get(self.url, self.window).json()
        self.assertEqual(Decimal(body["totals"]["energy_wh"]), Decimal("0.0000"))
        self.assertEqual(body["results"], [])


def _load_simulator():
    """Import the Phase 7 simulator from the repo root, or return None."""
    simulator_dir = Path(settings.BASE_DIR).parent / "simulator"
    if not (simulator_dir / "generator.py").exists():
        return None
    if str(simulator_dir) not in sys.path:
        sys.path.insert(0, str(simulator_dir))
    try:
        import generator  # noqa: PLC0415

        return generator
    except ImportError:
        return None


SIMULATOR = _load_simulator()


class SimulatorDataTests(TestCase):
    """
    Rollups over data from the real Phase 7 simulator.

    This is the end-to-end arithmetic check the phase asks for: the simulator's
    own per-series energy totals must match what the rollups compute from the
    stored readings.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if SIMULATOR is None:
            raise cls.skipException(
                "simulator/generator.py not importable from backend tests; "
                "skipping the simulator-data rollups."
            )

    def setUp(self):
        RollupFixture.build(self)
        self.start = local(2026, 3, 2, 0)
        self.interval = 900  # 15 minutes

        self.series = SIMULATOR.generate(
            site_keys=["home"],
            start=self.start,
            days=1,
            interval_seconds=self.interval,
            seed=42,
        )
        self.by_key = {s.appliance_key: s for s in self.series}

        # Store the simulator's mains series on the room's mains device, and two
        # appliance series on the appliance devices.
        self.stored = {
            "mains": (self.mains, self.by_key["mains"]),
            "ac": (self.appliance_a, self.by_key["ac"]),
            "fridge": (self.appliance_b, self.by_key["fridge"]),
        }
        for device, series in self.stored.values():
            Reading.objects.bulk_create(
                Reading(
                    device=device,
                    timestamp=sample.timestamp,
                    active_power_w=Decimal(f"{sample.active_power_w:.2f}"),
                    energy_wh=Decimal(f"{sample.energy_wh:.4f}"),
                    voltage_v=Decimal(f"{sample.voltage_v:.2f}"),
                    current_a=Decimal(f"{sample.current_a:.3f}"),
                    power_factor=Decimal(f"{sample.power_factor:.3f}"),
                    source=Reading.Source.SIMULATOR,
                )
                for sample in series.samples
            )

    def window(self):
        return self.start, self.start + timedelta(days=1)

    def test_the_simulator_produced_a_full_day_of_samples(self):
        expected = 24 * 3600 // self.interval
        self.assertEqual(len(self.by_key["mains"].samples), expected)
        self.assertEqual(Reading.objects.count(), expected * 3)

    def test_rollup_energy_matches_the_simulator_total(self):
        start, end = self.window()
        readings = rollups.readings_for(Device.objects.filter(pk=self.mains.pk), start, end)
        rolled_kwh = rollups.totals(readings)["energy_kwh"]

        expected = Decimal(f"{self.by_key['mains'].energy_kwh:.6f}")
        self.assertAlmostEqual(rolled_kwh, expected, places=3)

    def test_hourly_buckets_cover_every_hour_of_the_day(self):
        start, end = self.window()
        readings = rollups.readings_for(Device.objects.filter(pk=self.mains.pk), start, end)
        series = rollups.time_series(readings, "hour")

        self.assertEqual(len(series), 24)
        self.assertTrue(all(row["sample_count"] == 4 for row in series))

    def test_hourly_buckets_sum_back_to_the_daily_total(self):
        start, end = self.window()
        readings = rollups.readings_for(Device.objects.filter(pk=self.mains.pk), start, end)

        hourly = sum(row["energy_wh"] for row in rollups.time_series(readings, "hour"))
        daily = rollups.time_series(readings, "day")[0]["energy_wh"]
        self.assertEqual(hourly, daily)

    def test_peak_power_matches_the_simulator_peak(self):
        start, end = self.window()
        readings = rollups.readings_for(Device.objects.filter(pk=self.mains.pk), start, end)
        peak = rollups.totals(readings)["peak_power_w"]

        self.assertAlmostEqual(
            peak, Decimal(f"{self.by_key['mains'].peak_w:.2f}"), places=1
        )

    def test_auto_metering_picks_mains_over_the_simulated_appliances(self):
        """With both stored, `auto` must not add the AC and fridge to the mains."""
        start, end = self.window()
        devices, applied = rollups.select_devices(Device.objects.filter(room=self.room), "auto")
        self.assertEqual(applied, "mains")

        rolled = rollups.totals(rollups.readings_for(devices, start, end))["energy_kwh"]
        double_counted = rollups.totals(
            rollups.readings_for(Device.objects.filter(room=self.room), start, end)
        )["energy_kwh"]

        self.assertLess(rolled, double_counted)
        self.assertAlmostEqual(
            rolled, Decimal(f"{self.by_key['mains'].energy_kwh:.6f}"), places=3
        )

    def test_by_device_ranks_the_ac_above_the_fridge(self):
        """A 1500 W AC must outrank a 140 W fridge over a full day."""
        start, end = self.window()
        readings = rollups.readings_for(
            Device.objects.filter(kind=Device.Kind.APPLIANCE), start, end
        )
        rows = rollups.by_device(readings)
        self.assertEqual([row["device_name"] for row in rows], ["AC", "Lights"])
