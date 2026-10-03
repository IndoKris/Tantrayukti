"""
Tests for the billing endpoints and the seed command.

The estimate endpoint draws its energy from the Phase 8 rollups, so the critical
property is that it inherits the double-counting guard: a room metered twice
must not be billed twice.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import Role
from billing.models import EmissionFactor, Tariff, TariffSlab, TimeOfUseRate
from spaces.models import Building, Floor, Membership, Organisation, Room
from telemetry.models import Device, Reading

User = get_user_model()
IST = ZoneInfo("Asia/Kolkata")


def local(year, month, day, hour=0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=IST)


class BillingApiTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organisation.objects.create(name="Org")
        building = Building.objects.create(organisation=cls.org, name="HQ")
        floor = Floor.objects.create(building=building, name="Ground", level=0)
        cls.room = Room.objects.create(
            floor=floor, name="Lab", area_sqm=Decimal("50.00"), occupancy=10
        )

        cls.mains = Device.objects.create(room=cls.room, name="Mains", kind=Device.Kind.MAINS)
        cls.appliance = Device.objects.create(
            room=cls.room, name="AC", kind=Device.Kind.APPLIANCE
        )

        cls.manager = User.objects.create_user(
            username="manager", email="m@example.com", password="pw", role=Role.MANAGER
        )
        cls.member = User.objects.create_user(
            username="member", email="me@example.com", password="pw", role=Role.MEMBER
        )
        for user in (cls.manager, cls.member):
            Membership.objects.create(user=user, organisation=cls.org)

        cls.tariff = Tariff.objects.create(
            name="Sample",
            fixed_charge_inr_month=Decimal("100.00"),
            tax_percent=Decimal("0.00"),
            is_sample=True,
            source="Test fixture sample rates",
            is_default=True,
        )
        for from_kwh, to_kwh, rate in ((0, 100, 5), (100, 300, 10), (300, None, 15)):
            TariffSlab.objects.create(
                tariff=cls.tariff,
                from_kwh=Decimal(from_kwh),
                to_kwh=None if to_kwh is None else Decimal(to_kwh),
                rate_inr_per_kwh=Decimal(rate),
            )

        cls.factor = EmissionFactor.objects.create(
            name="Static default",
            kg_co2_per_kwh=Decimal("0.82000"),
            source="Static unverified default",
            is_verified=False,
            is_default=True,
        )

    @staticmethod
    def add_reading(device, when, kwh):
        """One reading carrying `kwh` of interval energy."""
        Reading.objects.create(
            device=device,
            timestamp=when,
            active_power_w=Decimal("1000.00"),
            energy_wh=Decimal(str(kwh)) * Decimal("1000"),
        )


class EstimateEndpointTests(BillingApiTestCase):
    def setUp(self):
        # 250 kWh on the mains, and 250 kWh of appliance readings for the same load.
        self.add_reading(self.mains, local(2026, 3, 2, 10), 250)
        self.add_reading(self.appliance, local(2026, 3, 2, 10), 250)
        self.url = reverse("billing:estimate")
        self.window = {"from": "2026-03-01", "to": "2026-03-04"}

    def get(self, **params):
        self.client.force_authenticate(self.member)
        return self.client.get(self.url, {**self.window, **params})

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_the_energy_total_comes_from_the_rollups(self):
        body = self.get(space=f"room:{self.room.pk}").json()
        self.assertEqual(Decimal(body["energy"]["total_kwh"]), Decimal("250.000000"))

    def test_auto_metering_prevents_billing_the_same_load_twice(self):
        """Both meters total 500 kWh; `auto` must bill the mains figure of 250."""
        body = self.get(space=f"room:{self.room.pk}").json()
        self.assertEqual(body["metering"]["applied"], "mains")
        self.assertEqual(Decimal(body["energy"]["total_kwh"]), Decimal("250.000000"))
        # 100x5 + 150x10 = 2000
        self.assertEqual(Decimal(body["cost"]["energy_charge_inr"]), Decimal("2000.00"))

    def test_metering_all_shows_the_doubled_figure_for_comparison(self):
        body = self.get(space=f"room:{self.room.pk}", metering="all").json()
        self.assertEqual(Decimal(body["energy"]["total_kwh"]), Decimal("500.000000"))
        # 100x5 + 200x10 + 200x15 = 5500, which is why `auto` exists.
        self.assertEqual(Decimal(body["cost"]["energy_charge_inr"]), Decimal("5500.00"))

    def test_the_slab_breakdown_is_returned_with_formulas(self):
        body = self.get(space=f"room:{self.room.pk}").json()
        lines = body["cost"]["slab_lines"]
        self.assertEqual(len(lines), 2)
        self.assertIn("kWh x", lines[0]["formula"])

    def test_the_tariff_sample_flag_and_source_are_returned(self):
        body = self.get().json()
        self.assertTrue(body["cost"]["tariff"]["is_sample"])
        self.assertIn("sample", body["cost"]["tariff"]["source"].lower())

    def test_co2_is_returned_with_its_factor_and_formula(self):
        body = self.get(space=f"room:{self.room.pk}").json()
        co2 = body["co2"]
        self.assertEqual(Decimal(co2["kg_co2"]), Decimal("205.000000"))  # 250 x 0.82
        self.assertEqual(Decimal(co2["factor"]["kg_co2_per_kwh"]), Decimal("0.82000"))
        self.assertIn("kg CO2/kWh", co2["formula"])

    def test_the_co2_factor_source_is_always_present(self):
        """The plan requires the factor's provenance wherever CO2 appears."""
        body = self.get().json()
        self.assertTrue(body["co2"]["factor"]["source"])
        self.assertIn("is_verified", body["co2"]["factor"])

    def test_a_short_window_excludes_the_monthly_fixed_charge(self):
        body = self.get(space=f"room:{self.room.pk}").json()
        self.assertEqual(Decimal(body["cost"]["fixed_charge_inr"]), Decimal("0.00"))
        self.assertTrue(any("fixed charge" in note for note in body["cost"]["notes"]))

    def test_the_fixed_charge_can_be_forced_on(self):
        body = self.get(space=f"room:{self.room.pk}", fixed_charge="true").json()
        self.assertEqual(Decimal(body["cost"]["fixed_charge_inr"]), Decimal("100.00"))

    def test_a_full_month_window_includes_the_fixed_charge_by_default(self):
        self.client.force_authenticate(self.member)
        body = self.client.get(
            self.url, {"from": "2026-03-01", "to": "2026-04-01", "space": f"room:{self.room.pk}"}
        ).json()
        self.assertEqual(Decimal(body["cost"]["fixed_charge_inr"]), Decimal("100.00"))

    def test_an_explicit_tariff_can_be_chosen(self):
        cheap = Tariff.objects.create(
            name="Cheap", is_sample=True, source="x", tax_percent=Decimal("0")
        )
        TariffSlab.objects.create(
            tariff=cheap, from_kwh=Decimal("0"), to_kwh=None, rate_inr_per_kwh=Decimal("1")
        )
        body = self.get(space=f"room:{self.room.pk}", tariff=cheap.pk).json()
        self.assertEqual(body["cost"]["tariff"]["name"], "Cheap")
        self.assertEqual(Decimal(body["cost"]["energy_charge_inr"]), Decimal("250.00"))

    def test_a_malformed_scope_is_a_400(self):
        self.assertEqual(self.get(space="building").status_code, 400)

    def test_another_organisation_cannot_be_priced(self):
        other = Organisation.objects.create(name="Other")
        response = self.get(space=f"organisation:{other.pk}")
        self.assertEqual(response.status_code, 400)

    def test_a_user_with_no_membership_is_billed_nothing(self):
        outsider = User.objects.create_user(
            username="outsider", email="o@example.com", password="pw"
        )
        self.client.force_authenticate(outsider)
        body = self.client.get(self.url, self.window).json()
        self.assertEqual(Decimal(body["energy"]["total_kwh"]), Decimal("0.000000"))
        self.assertEqual(Decimal(body["cost"]["energy_charge_inr"]), Decimal("0.00"))


class TimeOfUseThroughTheApiTests(BillingApiTestCase):
    """The hourly rollup must feed time-of-use in **local** hours."""

    def setUp(self):
        self.tariff.tou_rates.all().delete()
        TimeOfUseRate.objects.create(
            tariff=self.tariff,
            name="Evening peak",
            start_hour=18,
            end_hour=22,
            multiplier=Decimal("1.200"),
        )
        TimeOfUseRate.objects.create(
            tariff=self.tariff,
            name="Rest of day",
            start_hour=22,
            end_hour=18,
            multiplier=Decimal("1.000"),
        )
        self.url = reverse("billing:estimate")

    def estimate(self):
        self.client.force_authenticate(self.member)
        return self.client.get(
            self.url,
            {
                "from": "2026-03-01",
                "to": "2026-03-04",
                "space": f"room:{self.room.pk}",
                "metering": "mains",
            },
        ).json()

    def test_consumption_in_the_local_evening_peak_attracts_the_surcharge(self):
        self.add_reading(self.mains, local(2026, 3, 2, 19), 250)
        body = self.estimate()

        peak = next(
            line for line in body["cost"]["tou_lines"] if line["name"] == "Evening peak"
        )
        self.assertEqual(Decimal(peak["units_kwh"]), Decimal("250.000000"))
        # effective slab rate = 2000/250 = 8; 250 x 8 x 0.2 = 400
        self.assertEqual(Decimal(body["cost"]["tou_adjustment_inr"]), Decimal("400.00"))

    def test_consumption_outside_the_peak_attracts_no_surcharge(self):
        self.add_reading(self.mains, local(2026, 3, 2, 11), 250)
        body = self.estimate()
        self.assertEqual(Decimal(body["cost"]["tou_adjustment_inr"]), Decimal("0.00"))

    def test_a_reading_at_1930_ist_is_peak_not_afternoon(self):
        """
        Regression guard for the timezone trap.

        19:30 IST is 14:00 UTC. Reading the UTC hour would place this in the
        afternoon window and lose the surcharge entirely.
        """
        self.add_reading(self.mains, datetime(2026, 3, 2, 19, 30, tzinfo=IST), 250)
        body = self.estimate()
        self.assertGreater(Decimal(body["cost"]["tou_adjustment_inr"]), Decimal("0.00"))


class ProjectionEndpointTests(BillingApiTestCase):
    def setUp(self):
        from django.utils import timezone

        now = timezone.localtime()
        # Two readings earlier today, so the month-to-date window always covers them.
        self.add_reading(self.mains, now - timedelta(hours=2), 30)
        self.add_reading(self.mains, now - timedelta(hours=1), 30)
        self.url = reverse("billing:projection")

    def get(self):
        self.client.force_authenticate(self.member)
        return self.client.get(self.url, {"space": f"room:{self.room.pk}"})

    def test_the_projection_returns_month_to_date_and_a_projected_total(self):
        body = self.get().json()
        projection = body["projection"]
        self.assertEqual(Decimal(projection["consumed_kwh"]), Decimal("60.000000"))
        self.assertGreaterEqual(Decimal(projection["projected_kwh"]), Decimal("60"))

    def test_the_projection_reports_the_month_and_its_length(self):
        from django.utils import timezone

        body = self.get().json()
        now = timezone.localtime()
        self.assertEqual(body["projection"]["month"], f"{now.year:04d}-{now.month:02d}")
        self.assertIn(body["projection"]["days_in_month"], (28, 29, 30, 31))

    def test_the_projection_states_its_assumptions(self):
        """A naive projection must not look like a forecast."""
        assumptions = self.get().json()["projection"]["assumptions"]
        self.assertTrue(any("mean daily rate" in a for a in assumptions))
        self.assertTrue(any("No seasonal" in a for a in assumptions))

    def test_both_bills_are_returned(self):
        projection = self.get().json()["projection"]
        self.assertIn("bill_to_date", projection)
        self.assertIn("projected_bill", projection)
        self.assertEqual(
            Decimal(projection["bill_to_date"]["fixed_charge_inr"]), Decimal("0.00")
        )

    def test_co2_is_returned_for_both_to_date_and_projected(self):
        body = self.get().json()
        self.assertEqual(Decimal(body["co2_to_date"]["kg_co2"]), Decimal("49.200000"))
        self.assertGreaterEqual(
            Decimal(body["co2_projected"]["kg_co2"]), Decimal(body["co2_to_date"]["kg_co2"])
        )

    def test_a_caller_supplied_window_is_ignored(self):
        """A projection is month-to-date by definition."""
        self.client.force_authenticate(self.member)
        body = self.client.get(self.url, {"from": "2020-01-01", "to": "2020-01-02"}).json()
        self.assertNotIn("2020", body["window"]["from"])


class TariffApiTests(BillingApiTestCase):
    def test_a_member_can_read_tariffs(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(reverse("billing:tariff-list"))
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["count"], 1)

    def test_a_member_cannot_create_a_tariff(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse("billing:tariff-list"), {"name": "Mine"})
        self.assertEqual(response.status_code, 403)

    def test_a_manager_can_create_a_tariff(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(
            reverse("billing:tariff-list"), {"name": "Mine", "source": "typed in"}
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_tariffs_include_their_slabs_and_tou_rates(self):
        self.client.force_authenticate(self.member)
        rows = self.client.get(reverse("billing:tariff-list")).json()["results"]
        sample = next(row for row in rows if row["name"] == "Sample")
        self.assertEqual(len(sample["slabs"]), 3)

    def test_a_zero_length_tou_window_is_rejected(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(
            reverse("billing:tou-rate-list"),
            {"tariff": self.tariff.pk, "name": "Bad", "start_hour": 10, "end_hour": 10},
        )
        self.assertEqual(response.status_code, 400)

    def test_an_out_of_range_hour_is_rejected(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(
            reverse("billing:tou-rate-list"),
            {"tariff": self.tariff.pk, "name": "Bad", "start_hour": 25, "end_hour": 26},
        )
        self.assertEqual(response.status_code, 400)

    def test_emission_factors_are_readable_with_their_sources(self):
        self.client.force_authenticate(self.member)
        rows = self.client.get(reverse("billing:emission-factor-list")).json()["results"]
        self.assertTrue(all(row["source"] for row in rows))


class SeedTariffsTests(APITestCase):
    def seed(self) -> str:
        out = StringIO()
        call_command("seed_tariffs", stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_seeding_creates_two_tariffs_and_one_factor(self):
        self.seed()
        self.assertEqual(Tariff.objects.count(), 2)
        self.assertEqual(EmissionFactor.objects.count(), 1)

    def test_every_seeded_tariff_is_flagged_as_a_sample(self):
        """The plan forbids presenting invented rates as official ones."""
        self.seed()
        for tariff in Tariff.objects.all():
            self.assertTrue(tariff.is_sample)
            self.assertIn("ILLUSTRATIVE SAMPLE", tariff.source)

    def test_the_seeded_factor_is_the_documented_default_and_unverified(self):
        self.seed()
        factor = EmissionFactor.objects.get()
        self.assertEqual(factor.kg_co2_per_kwh, Decimal("0.82000"))
        self.assertFalse(factor.is_verified)
        self.assertIn("CEA", factor.source)

    def test_the_command_warns_that_the_rates_are_samples(self):
        output = self.seed()
        self.assertIn("ILLUSTRATIVE SAMPLES", output)

    def test_the_residential_tariff_has_four_cumulative_slabs(self):
        self.seed()
        tariff = Tariff.objects.get(name="Sample residential slab tariff")
        slabs = tariff.ordered_slabs
        self.assertEqual(len(slabs), 4)
        # Contiguous: each slab starts where the previous one ended.
        for lower, upper in zip(slabs, slabs[1:]):
            self.assertEqual(lower.to_kwh, upper.from_kwh)
        self.assertIsNone(slabs[-1].to_kwh)

    def test_the_commercial_tou_windows_tile_the_day_exactly_once(self):
        self.seed()
        rates = Tariff.objects.get(
            name="Sample commercial tariff with time of day"
        ).ordered_tou_rates
        for hour in range(24):
            matches = [rate for rate in rates if rate.covers_hour(hour)]
            self.assertEqual(len(matches), 1, f"hour {hour} matched {len(matches)}")

    def test_re_running_is_idempotent(self):
        self.seed()
        counts = (Tariff.objects.count(), TariffSlab.objects.count(), EmissionFactor.objects.count())
        self.seed()
        self.assertEqual(
            counts,
            (Tariff.objects.count(), TariffSlab.objects.count(), EmissionFactor.objects.count()),
        )
