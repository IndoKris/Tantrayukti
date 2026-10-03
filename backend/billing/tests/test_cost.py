"""
Unit tests for the slab, time-of-use and projection arithmetic.

Rates are chosen so every expected total can be checked by hand, which is the
point: a tariff engine that is only tested against its own output would happily
bill the wrong amount forever.
"""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from billing import engines
from billing.models import Tariff, TariffSlab, TimeOfUseRate

IST = ZoneInfo("Asia/Kolkata")


def make_tariff(**overrides) -> Tariff:
    defaults = {
        "name": "Test tariff",
        "fixed_charge_inr_month": Decimal("100.00"),
        "tax_percent": Decimal("0.00"),
        "is_sample": True,
        "source": "Test fixture",
    }
    return Tariff.objects.create(**{**defaults, **overrides})


def add_slabs(tariff, blocks):
    """blocks: list of (from_kwh, to_kwh, rate)."""
    for from_kwh, to_kwh, rate in blocks:
        TariffSlab.objects.create(
            tariff=tariff,
            from_kwh=Decimal(str(from_kwh)),
            to_kwh=None if to_kwh is None else Decimal(str(to_kwh)),
            rate_inr_per_kwh=Decimal(str(rate)),
            label=f"{from_kwh}-{to_kwh if to_kwh is not None else 'up'}",
        )


class SlabChargeTests(TestCase):
    """
    Slabs are cumulative: 0-100 @ 5, 100-300 @ 10, 300+ @ 15 INR/kWh.

    So 250 kWh costs 100x5 + 150x10 = 500 + 1500 = 2000 INR.
    """

    def setUp(self):
        self.tariff = make_tariff()
        add_slabs(self.tariff, [(0, 100, 5), (100, 300, 10), (300, None, 15)])
        self.slabs = self.tariff.ordered_slabs

    def charge(self, kwh) -> Decimal:
        _, total = engines.slab_charge(Decimal(str(kwh)), self.slabs)
        return total

    def test_consumption_inside_the_first_slab(self):
        self.assertEqual(self.charge(50), Decimal("250"))

    def test_consumption_exactly_at_a_slab_boundary(self):
        self.assertEqual(self.charge(100), Decimal("500"))

    def test_consumption_spanning_two_slabs(self):
        # 100x5 + 150x10
        self.assertEqual(self.charge(250), Decimal("2000"))

    def test_consumption_spanning_all_three_slabs(self):
        # 100x5 + 200x10 + 100x15 = 500 + 2000 + 1500
        self.assertEqual(self.charge(400), Decimal("4000"))

    def test_zero_consumption_costs_nothing(self):
        self.assertEqual(self.charge(0), Decimal("0"))

    def test_slabs_are_cumulative_not_flat_rate(self):
        """A flat top rate would charge 250x10 = 2500, not 2000."""
        self.assertNotEqual(self.charge(250), Decimal("2500"))

    def test_each_slab_line_reports_its_own_units_and_formula(self):
        lines, _ = engines.slab_charge(Decimal("250"), self.slabs)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].units_kwh, Decimal("100"))
        self.assertEqual(lines[1].units_kwh, Decimal("150"))
        self.assertIn("150.000000 kWh x 10.0000 INR/kWh", lines[1].as_dict()["formula"])

    def test_line_charges_sum_to_the_total(self):
        lines, total = engines.slab_charge(Decimal("437.5"), self.slabs)
        self.assertEqual(sum(line.charge_inr for line in lines), total)

    def test_fractional_consumption_is_not_rounded_away(self):
        # 100x5 + 0.5x10
        self.assertEqual(self.charge("100.5"), Decimal("505.0"))

    def test_no_slabs_means_no_energy_charge(self):
        bare = make_tariff(name="Bare")
        _, total = engines.slab_charge(Decimal("100"), bare.ordered_slabs)
        self.assertEqual(total, Decimal("0"))


class UnboundedSlabTests(TestCase):
    """A tariff whose last slab is bounded must not bill nothing above it."""

    def setUp(self):
        self.tariff = make_tariff(name="Bounded top")
        add_slabs(self.tariff, [(0, 100, 5), (100, 200, 10)])

    def test_consumption_above_the_last_slab_is_charged_at_the_top_rate(self):
        lines, total = engines.slab_charge(Decimal("300"), self.tariff.ordered_slabs)
        # 100x5 + 100x10 + 100x10 (overflow at the top rate)
        self.assertEqual(total, Decimal("2500"))
        self.assertIn("above the last defined block", lines[-1].label)

    def test_the_overflow_units_are_reported_not_hidden(self):
        lines, _ = engines.slab_charge(Decimal("300"), self.tariff.ordered_slabs)
        self.assertEqual(lines[-1].units_kwh, Decimal("100"))

    def test_consumption_within_the_bounds_has_no_overflow_line(self):
        lines, _ = engines.slab_charge(Decimal("150"), self.tariff.ordered_slabs)
        self.assertTrue(all("above the last" not in line.label for line in lines))


class TimeOfUseWindowTests(TestCase):
    """Window membership, including the midnight wrap."""

    def setUp(self):
        self.tariff = make_tariff(name="ToU")
        self.night = TimeOfUseRate.objects.create(
            tariff=self.tariff, name="Night", start_hour=22, end_hour=6, multiplier=Decimal("0.8")
        )
        self.day = TimeOfUseRate.objects.create(
            tariff=self.tariff, name="Day", start_hour=6, end_hour=18, multiplier=Decimal("1.0")
        )
        self.peak = TimeOfUseRate.objects.create(
            tariff=self.tariff, name="Peak", start_hour=18, end_hour=22, multiplier=Decimal("1.25")
        )

    def test_a_normal_window_covers_its_own_hours(self):
        self.assertTrue(self.day.covers_hour(6))
        self.assertTrue(self.day.covers_hour(17))

    def test_a_window_end_is_exclusive(self):
        self.assertFalse(self.day.covers_hour(18))

    def test_a_window_wrapping_midnight_covers_both_sides(self):
        self.assertTrue(self.night.covers_hour(22))
        self.assertTrue(self.night.covers_hour(23))
        self.assertTrue(self.night.covers_hour(0))
        self.assertTrue(self.night.covers_hour(5))

    def test_a_wrapping_window_excludes_the_middle_of_the_day(self):
        self.assertFalse(self.night.covers_hour(6))
        self.assertFalse(self.night.covers_hour(12))

    def test_the_three_windows_tile_the_whole_day_exactly_once(self):
        """No hour may be uncovered or double covered, or the bill shifts."""
        for hour in range(24):
            matches = [
                rate
                for rate in (self.night, self.day, self.peak)
                if rate.covers_hour(hour)
            ]
            self.assertEqual(len(matches), 1, f"hour {hour} matched {len(matches)} windows")


class TimeOfUseAdjustmentTests(TestCase):
    """
    Adjustment = units_in_window x effective_rate x (multiplier - 1).

    With an effective rate of 10 INR/kWh: 100 kWh at x1.25 adds
    100 x 10 x 0.25 = +250 INR; 50 kWh at x0.8 subtracts 50 x 10 x 0.2 = -100 INR.
    """

    def setUp(self):
        self.tariff = make_tariff(name="ToU")
        TimeOfUseRate.objects.create(
            tariff=self.tariff, name="Night", start_hour=22, end_hour=6, multiplier=Decimal("0.8")
        )
        TimeOfUseRate.objects.create(
            tariff=self.tariff, name="Day", start_hour=6, end_hour=18, multiplier=Decimal("1.0")
        )
        TimeOfUseRate.objects.create(
            tariff=self.tariff, name="Peak", start_hour=18, end_hour=22, multiplier=Decimal("1.25")
        )
        self.rates = self.tariff.ordered_tou_rates
        self.rate = Decimal("10")

    def adjust(self, hourly):
        return engines.tou_adjustment(
            {h: Decimal(str(v)) for h, v in hourly.items()}, self.rate, self.rates
        )

    def test_a_peak_surcharge_increases_the_bill(self):
        _, total = self.adjust({19: 100})
        self.assertEqual(total, Decimal("250.0"))

    def test_an_off_peak_rebate_decreases_the_bill(self):
        _, total = self.adjust({2: 50})
        self.assertEqual(total, Decimal("-100.0"))

    def test_a_neutral_window_changes_nothing(self):
        _, total = self.adjust({12: 1000})
        self.assertEqual(total, Decimal("0.0"))

    def test_surcharge_and_rebate_net_off(self):
        _, total = self.adjust({19: 100, 2: 50, 12: 400})
        self.assertEqual(total, Decimal("150.0"))

    def test_consumption_either_side_of_midnight_shares_the_night_window(self):
        lines, total = self.adjust({23: 10, 1: 10})
        night = next(line for line in lines if line.name == "Night")
        self.assertEqual(night.units_kwh, Decimal("20"))
        self.assertEqual(total, Decimal("-40.0"))

    def test_no_hourly_data_means_no_adjustment(self):
        _, total = self.adjust({})
        self.assertEqual(total, Decimal("0"))

    def test_a_tariff_with_no_tou_rates_has_no_adjustment(self):
        flat = make_tariff(name="Flat")
        _, total = engines.tou_adjustment({19: Decimal("100")}, self.rate, flat.ordered_tou_rates)
        self.assertEqual(total, Decimal("0"))

    def test_each_line_names_its_window_and_direction(self):
        lines, _ = self.adjust({19: 100, 2: 50})
        by_name = {line.name: line.as_dict() for line in lines}
        self.assertEqual(by_name["Peak"]["kind"], "surcharge")
        self.assertEqual(by_name["Peak"]["window"], "18:00-22:00")
        self.assertEqual(by_name["Night"]["kind"], "rebate")

    def test_an_hour_in_two_windows_is_counted_once(self):
        """Overlapping configuration must be deterministic, not double charged."""
        overlapping = make_tariff(name="Overlap")
        TimeOfUseRate.objects.create(
            tariff=overlapping, name="A", start_hour=18, end_hour=22, multiplier=Decimal("1.5")
        )
        TimeOfUseRate.objects.create(
            tariff=overlapping, name="B", start_hour=20, end_hour=23, multiplier=Decimal("2.0")
        )
        lines, total = engines.tou_adjustment(
            {21: Decimal("100")}, Decimal("10"), overlapping.ordered_tou_rates
        )
        self.assertEqual(len(lines), 1)
        self.assertEqual(total, Decimal("500.0"))  # the first window only, x1.5


class BillTests(TestCase):
    def setUp(self):
        self.tariff = make_tariff(
            fixed_charge_inr_month=Decimal("100.00"), tax_percent=Decimal("10.00")
        )
        add_slabs(self.tariff, [(0, 100, 5), (100, 300, 10), (300, None, 15)])

    def test_a_bill_adds_energy_fixed_and_tax(self):
        # 250 kWh -> 2000 energy + 100 fixed = 2100, +10% tax = 2310
        bill = engines.estimate_bill(Decimal("250"), self.tariff)
        self.assertEqual(bill.energy_charge_inr, Decimal("2000"))
        self.assertEqual(bill.fixed_charge_inr, Decimal("100.00"))
        self.assertEqual(engines.money(bill.tax_inr), Decimal("210.00"))
        self.assertEqual(engines.money(bill.total_inr), Decimal("2310.00"))

    def test_the_fixed_charge_can_be_excluded_for_a_short_window(self):
        bill = engines.estimate_bill(Decimal("250"), self.tariff, include_fixed_charge=False)
        self.assertEqual(bill.fixed_charge_inr, Decimal("0"))
        self.assertEqual(engines.money(bill.total_inr), Decimal("2200.00"))

    def test_excluding_the_fixed_charge_is_explained_in_the_notes(self):
        bill = engines.estimate_bill(Decimal("250"), self.tariff, include_fixed_charge=False)
        self.assertTrue(any("fixed charge" in note for note in bill.notes))

    def test_the_effective_rate_is_the_total_over_the_units(self):
        bill = engines.estimate_bill(Decimal("250"), self.tariff)
        self.assertEqual(bill.effective_rate_inr_per_kwh, Decimal("9.24"))  # 2310/250

    def test_the_tariff_sample_flag_and_source_travel_with_the_bill(self):
        bill = engines.estimate_bill(Decimal("100"), self.tariff).as_dict()
        self.assertTrue(bill["tariff"]["is_sample"])
        self.assertEqual(bill["tariff"]["source"], "Test fixture")

    def test_no_tariff_produces_zero_cost_and_says_why(self):
        """A missing tariff must not silently invent a rate."""
        bill = engines.estimate_bill(Decimal("250"), None)
        self.assertEqual(bill.total_inr, Decimal("0"))
        self.assertTrue(any("No active tariff" in note for note in bill.notes))

    def test_tou_rates_without_hourly_data_are_flagged_not_ignored_silently(self):
        TimeOfUseRate.objects.create(
            tariff=self.tariff, name="Peak", start_hour=18, end_hour=22, multiplier=Decimal("1.2")
        )
        bill = engines.estimate_bill(Decimal("250"), self.tariff, hourly_kwh=None)
        self.assertEqual(bill.tou_adjustment_inr, Decimal("0"))
        self.assertTrue(any("no hourly breakdown" in note for note in bill.notes))

    def test_a_bill_with_tou_includes_the_adjustment_in_the_total(self):
        TimeOfUseRate.objects.create(
            tariff=self.tariff, name="Peak", start_hour=18, end_hour=22, multiplier=Decimal("1.2")
        )
        bill = engines.estimate_bill(
            Decimal("250"), self.tariff, hourly_kwh={19: Decimal("250")}
        )
        # effective slab rate = 2000/250 = 8; adjustment = 250 x 8 x 0.2 = 400
        self.assertEqual(bill.tou_adjustment_inr, Decimal("400.0"))
        self.assertEqual(engines.money(bill.total_inr), Decimal("2750.00"))  # (2000+400+100)*1.1


class ProjectionTests(TestCase):
    def setUp(self):
        self.tariff = make_tariff(
            fixed_charge_inr_month=Decimal("100.00"), tax_percent=Decimal("0.00")
        )
        add_slabs(self.tariff, [(0, 100, 5), (100, 300, 10), (300, None, 15)])

    def test_a_projection_scales_the_daily_mean_to_the_month(self):
        # 100 kWh over the first 10 days of a 31-day March -> 10 kWh/day -> 310 kWh
        as_of = datetime(2026, 3, 11, 0, 0, tzinfo=IST)
        projection = engines.project_month(Decimal("100"), as_of, self.tariff)

        self.assertEqual(projection.days_in_month, 31)
        self.assertEqual(projection.days_elapsed, Decimal("10.00"))
        self.assertEqual(engines.energy(projection.mean_kwh_per_day), Decimal("10.000000"))
        self.assertEqual(engines.energy(projection.projected_kwh), Decimal("310.000000"))

    def test_the_month_length_is_taken_from_the_calendar(self):
        as_of = datetime(2026, 2, 11, 0, 0, tzinfo=IST)
        self.assertEqual(engines.project_month(Decimal("100"), as_of, self.tariff).days_in_month, 28)

    def test_a_leap_february_has_29_days(self):
        as_of = datetime(2028, 2, 11, 0, 0, tzinfo=IST)
        self.assertEqual(engines.project_month(Decimal("100"), as_of, self.tariff).days_in_month, 29)

    def test_elapsed_days_are_fractional(self):
        """A projection made at midday must not be a whole day behind."""
        as_of = datetime(2026, 3, 11, 12, 0, tzinfo=IST)
        projection = engines.project_month(Decimal("105"), as_of, self.tariff)
        self.assertEqual(projection.days_elapsed, Decimal("10.50"))
        self.assertEqual(engines.energy(projection.mean_kwh_per_day), Decimal("10.000000"))

    def test_the_first_hour_of_a_month_does_not_divide_by_zero(self):
        as_of = datetime(2026, 3, 1, 0, 5, tzinfo=IST)
        projection = engines.project_month(Decimal("1"), as_of, self.tariff)
        self.assertGreater(projection.projected_kwh, 0)

    def test_the_projection_includes_the_fixed_charge_but_month_to_date_does_not(self):
        as_of = datetime(2026, 3, 11, 0, 0, tzinfo=IST)
        projection = engines.project_month(Decimal("100"), as_of, self.tariff)

        self.assertEqual(projection.bill_to_date.fixed_charge_inr, Decimal("0"))
        self.assertEqual(projection.projected_bill.fixed_charge_inr, Decimal("100.00"))

    def test_the_projected_bill_uses_the_projected_total_for_slabs(self):
        """Slabs are cumulative monthly, so a projection must re-slab the total."""
        as_of = datetime(2026, 3, 11, 0, 0, tzinfo=IST)
        projection = engines.project_month(Decimal("100"), as_of, self.tariff)

        # 310 kWh -> 100x5 + 200x10 + 10x15 = 500 + 2000 + 150 = 2650
        self.assertEqual(projection.projected_bill.energy_charge_inr, Decimal("2650"))
        # Month to date, 100 kWh, is only 500.
        self.assertEqual(projection.bill_to_date.energy_charge_inr, Decimal("500"))

    def test_the_assumptions_are_stated_explicitly(self):
        as_of = datetime(2026, 3, 11, 0, 0, tzinfo=IST)
        assumptions = engines.project_month(Decimal("100"), as_of, self.tariff).assumptions

        self.assertTrue(any("same mean daily rate" in a for a in assumptions))
        self.assertTrue(any("No seasonal" in a for a in assumptions))

    def test_zero_consumption_projects_zero(self):
        as_of = datetime(2026, 3, 11, 0, 0, tzinfo=IST)
        projection = engines.project_month(Decimal("0"), as_of, self.tariff)
        self.assertEqual(projection.projected_kwh, Decimal("0"))
