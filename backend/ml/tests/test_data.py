"""
Tests for the data pipeline.

Plain `unittest` with no database, so they run under `manage.py test` alongside
everything else without needing fixtures.

The properties worth pinning here are the ones that would silently corrupt every
downstream model: unit handling, dropping rather than imputing the target,
chronological splitting, and the synthetic labelling that keeps metrics honest.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data import clean, prepare, synthetic
from ml.data.sources import Provenance


def minute_frame(hours: int = 3, kw: float = 2.0, start="2024-01-01 00:00") -> pd.DataFrame:
    """A complete 1-minute UCI-shaped frame drawing a constant `kw` kilowatts."""
    index = pd.date_range(start=start, periods=hours * 60, freq="1min")
    return pd.DataFrame(
        {
            "Global_active_power": kw,
            "Global_reactive_power": 0.1,
            "Voltage": 240.0,
            "Global_intensity": kw * 1000 / 240.0,
            "Sub_metering_1": 0.0,
            "Sub_metering_2": 0.0,
            "Sub_metering_3": 0.0,
        },
        index=index,
    )


class UnitConversionTests(unittest.TestCase):
    """
    The kW/kWh boundary.

    A constant 2 kW draw for one hour is 2 kWh. The plan forbids mixing the two
    units, so this is pinned explicitly rather than trusted.
    """

    def test_a_constant_2kw_hour_is_2_kwh(self):
        hourly = clean.to_hourly(minute_frame(hours=3, kw=2.0))
        self.assertEqual(len(hourly), 3)
        for value in hourly["energy_kwh"]:
            self.assertAlmostEqual(value, 2.0, places=6)

    def test_mean_power_is_reported_separately_from_energy(self):
        hourly = clean.to_hourly(minute_frame(kw=2.0))
        self.assertIn("mean_power_kw", hourly.columns)
        self.assertIn("energy_kwh", hourly.columns)

    def test_peak_power_exceeds_the_mean_when_the_load_varies(self):
        frame = minute_frame(hours=1, kw=1.0)
        frame.iloc[30, frame.columns.get_loc("Global_active_power")] = 5.0
        hourly = clean.to_hourly(frame)
        self.assertEqual(hourly["peak_power_kw"].iloc[0], 5.0)
        self.assertLess(hourly["mean_power_kw"].iloc[0], 5.0)

    def test_energy_scales_linearly_with_power(self):
        one = clean.to_hourly(minute_frame(hours=1, kw=1.0))["energy_kwh"].iloc[0]
        four = clean.to_hourly(minute_frame(hours=1, kw=4.0))["energy_kwh"].iloc[0]
        self.assertAlmostEqual(four / one, 4.0, places=6)


class CleaningTests(unittest.TestCase):
    def test_rows_with_no_target_are_dropped_not_imputed(self):
        """Imputing the forecasting target would fabricate the label."""
        frame = minute_frame(hours=1)
        frame.iloc[0:10, frame.columns.get_loc("Global_active_power")] = np.nan

        cleaned, report = clean.clean_uci(frame)
        self.assertEqual(report.missing_power_rows, 10)
        self.assertEqual(len(cleaned), 50)
        self.assertFalse(cleaned["Global_active_power"].isna().any())

    def test_implausible_power_is_dropped(self):
        frame = minute_frame(hours=1)
        frame.iloc[0, frame.columns.get_loc("Global_active_power")] = 90.0

        cleaned, report = clean.clean_uci(frame)
        self.assertEqual(report.implausible_power_rows, 1)
        self.assertEqual(len(cleaned), 59)

    def test_negative_power_is_dropped(self):
        frame = minute_frame(hours=1)
        frame.iloc[0, frame.columns.get_loc("Global_active_power")] = -3.0
        _, report = clean.clean_uci(frame)
        self.assertEqual(report.implausible_power_rows, 1)

    def test_implausible_voltage_is_dropped(self):
        frame = minute_frame(hours=1)
        frame.iloc[0, frame.columns.get_loc("Voltage")] = 9.0
        _, report = clean.clean_uci(frame)
        self.assertEqual(report.implausible_voltage_rows, 1)

    def test_a_clean_frame_loses_nothing(self):
        cleaned, report = clean.clean_uci(minute_frame(hours=2))
        self.assertEqual(len(cleaned), 120)
        self.assertEqual(report.missing_power_rows, 0)
        self.assertEqual(report.implausible_power_rows, 0)

    def test_the_report_explains_why_the_target_is_not_imputed(self):
        _, report = clean.clean_uci(minute_frame(hours=1))
        self.assertTrue(any("not imputed" in note for note in report.notes))


class CoverageTests(unittest.TestCase):
    def test_an_incomplete_hour_is_dropped(self):
        """Keeping a 12-minute hour would understate its energy fivefold."""
        frame = minute_frame(hours=2).iloc[:72]  # 60 + 12 minutes
        report = clean.CleaningReport()
        hourly = clean.to_hourly(frame, report)

        self.assertEqual(len(hourly), 1)
        self.assertEqual(report.hours_dropped_incomplete, 1)

    def test_an_hour_above_the_coverage_threshold_is_kept(self):
        frame = minute_frame(hours=1).iloc[:50]  # 83% coverage
        hourly = clean.to_hourly(frame, min_coverage=0.8)
        self.assertEqual(len(hourly), 1)

    def test_coverage_is_reported_per_hour(self):
        hourly = clean.to_hourly(minute_frame(hours=1).iloc[:48])
        self.assertAlmostEqual(hourly["coverage"].iloc[0], 0.8, places=6)

    def test_the_threshold_is_explained_in_the_report(self):
        report = clean.CleaningReport()
        clean.to_hourly(minute_frame(hours=1), report)
        self.assertTrue(any("Scaling a partial hour" in note for note in report.notes))


class CalendarFeatureTests(unittest.TestCase):
    def setUp(self):
        self.frame = clean.to_hourly(minute_frame(hours=24, start="2024-01-06 00:00"))

    def test_hour_and_month_are_present(self):
        for column in ("hour", "day_of_week", "month", "is_weekend"):
            self.assertIn(column, self.frame.columns)

    def test_cyclical_encodings_make_hour_23_adjacent_to_hour_0(self):
        """A raw hour column would put them 23 units apart."""
        frame = clean.to_hourly(minute_frame(hours=24, start="2024-01-01 00:00"))
        first = frame.loc[frame["hour"] == 0, ["hour_sin", "hour_cos"]].iloc[0]
        last = frame.loc[frame["hour"] == 23, ["hour_sin", "hour_cos"]].iloc[0]

        distance = np.hypot(first["hour_sin"] - last["hour_sin"], first["hour_cos"] - last["hour_cos"])
        self.assertLess(distance, 0.3)

    def test_saturday_is_flagged_as_weekend(self):
        self.assertTrue(bool(self.frame["is_weekend"].iloc[0]))

    def test_a_monday_is_not_flagged_as_weekend(self):
        frame = clean.to_hourly(minute_frame(hours=2, start="2024-01-08 00:00"))
        self.assertFalse(bool(frame["is_weekend"].iloc[0]))


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.frame = synthetic.synthetic_hourly_load(hours=1000)

    def test_the_split_fractions_are_respected(self):
        splits = clean.time_ordered_split(self.frame, train=0.7, validation=0.15)
        self.assertEqual(len(splits["train"]), 700)
        self.assertEqual(len(splits["validation"]), 150)
        self.assertEqual(len(splits["test"]), 150)

    def test_the_split_is_chronological_not_random(self):
        """A random split would leak the future into training."""
        splits = clean.time_ordered_split(self.frame)
        self.assertLess(splits["train"].index.max(), splits["validation"].index.min())
        self.assertLess(splits["validation"].index.max(), splits["test"].index.min())

    def test_no_rows_are_lost_or_duplicated(self):
        splits = clean.time_ordered_split(self.frame)
        total = sum(len(part) for part in splits.values())
        self.assertEqual(total, len(self.frame))

    def test_invalid_fractions_are_rejected(self):
        with self.assertRaises(ValueError):
            clean.time_ordered_split(self.frame, train=0.9, validation=0.2)


class SyntheticLoadTests(unittest.TestCase):
    def test_the_series_is_labelled_synthetic_on_every_row(self):
        frame = synthetic.synthetic_hourly_load(hours=48)
        self.assertTrue((frame["is_synthetic"] == 1).all())

    def test_the_seed_makes_the_series_reproducible(self):
        a = synthetic.synthetic_hourly_load(hours=96, seed=7)
        b = synthetic.synthetic_hourly_load(hours=96, seed=7)
        pd.testing.assert_frame_equal(a, b)

    def test_a_different_seed_changes_the_series(self):
        a = synthetic.synthetic_hourly_load(hours=96, seed=7)
        b = synthetic.synthetic_hourly_load(hours=96, seed=8)
        self.assertFalse(a["energy_kwh"].equals(b["energy_kwh"]))

    def test_power_is_always_positive(self):
        frame = synthetic.synthetic_hourly_load(hours=24 * 30)
        self.assertGreater(frame["energy_kwh"].min(), 0)

    def test_it_has_the_same_columns_as_the_real_pipeline(self):
        """Phase 11 must train on either source without branching."""
        real = clean.to_hourly(minute_frame(hours=3))
        real["is_synthetic"] = 0
        fake = synthetic.synthetic_hourly_load(hours=3)
        self.assertEqual(set(real.columns), set(fake.columns))

    def test_the_evening_peak_is_higher_than_the_overnight_trough(self):
        frame = synthetic.synthetic_hourly_load(hours=24 * 60)
        by_hour = frame.groupby("hour")["energy_kwh"].mean()
        self.assertGreater(by_hour.loc[19], by_hour.loc[3])


class SyntheticEmissionTests(unittest.TestCase):
    def setUp(self):
        self.frame = synthetic.synthetic_emission_factors(hours=24 * 90)

    def test_every_row_is_labelled_synthetic(self):
        self.assertTrue((self.frame["is_synthetic"] == 1).all())

    def test_it_carries_the_features_and_target_phase_12_needs(self):
        for column in ("hour", "month", "load_mw", "kg_co2_per_kwh"):
            self.assertIn(column, self.frame.columns)

    def test_midday_is_cleaner_than_the_evening_peak(self):
        """Solar dilution at midday, peaking plants in the evening."""
        by_hour = self.frame.groupby("hour")["kg_co2_per_kwh"].mean()
        self.assertLess(by_hour.loc[12], by_hour.loc[19])

    def test_midday_is_cleaner_than_the_overnight_coal_baseload(self):
        by_hour = self.frame.groupby("hour")["kg_co2_per_kwh"].mean()
        self.assertLess(by_hour.loc[12], by_hour.loc[3])

    def test_the_factor_stays_in_a_physically_sensible_range(self):
        self.assertGreater(self.frame["kg_co2_per_kwh"].min(), 0.3)
        self.assertLess(self.frame["kg_co2_per_kwh"].max(), 1.2)

    def test_the_mean_sits_near_the_projects_static_default(self):
        """It must straddle 0.82 so the modelled option is comparable to it."""
        self.assertAlmostEqual(self.frame["kg_co2_per_kwh"].mean(), 0.82, delta=0.08)

    def test_intensity_correlates_with_load(self):
        """Peakers are dirtier, so the RF has a real relationship to learn."""
        correlation = self.frame["kg_co2_per_kwh"].corr(self.frame["load_mw"])
        self.assertGreater(correlation, 0.1)

    def test_the_summary_reports_the_cleanest_and_dirtiest_hours(self):
        summary = synthetic.emission_factor_summary(self.frame)
        self.assertEqual(summary["rows"], len(self.frame))
        self.assertIn(summary["cleanest_hour"], range(10, 16))
        self.assertIn(summary["dirtiest_hour"], list(range(18, 24)) + list(range(0, 6)))

    def test_the_seed_makes_it_reproducible(self):
        a = synthetic.synthetic_emission_factors(hours=72, seed=11)
        b = synthetic.synthetic_emission_factors(hours=72, seed=11)
        pd.testing.assert_frame_equal(a, b)


class ProvenanceTests(unittest.TestCase):
    def test_the_sidecar_is_written_beside_the_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data.csv"
            provenance = Provenance(
                dataset="Test", is_synthetic=True, source="unit test"
            )
            sidecar = provenance.write(target)

            self.assertTrue(sidecar.exists())
            self.assertEqual(sidecar.name, "data.csv.provenance.json")

    def test_the_sidecar_records_whether_the_data_is_synthetic(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data.csv"
            sidecar = Provenance(
                dataset="Test", is_synthetic=True, source="unit test"
            ).write(target)

            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertTrue(payload["is_synthetic"])
            self.assertEqual(payload["source"], "unit test")
            self.assertIn("generated_at", payload)


class PrepareCliTests(unittest.TestCase):
    """
    End-to-end runs of the CLI, always with `--synthetic` so no test touches
    the network.
    """

    def run_prepare(self, directory: str, *extra: str) -> int:
        return prepare.main(["--small", "--synthetic", "--out", directory, *extra])

    def test_it_writes_both_datasets_and_both_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.run_prepare(directory), 0)
            out = Path(directory)

            for name in (prepare.HOUSEHOLD_FILE, prepare.EMISSION_FILE):
                self.assertTrue((out / name).exists(), name)
                self.assertTrue((out / f"{name}.provenance.json").exists(), name)

    def test_the_synthetic_run_labels_the_household_series_synthetic(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            self.run_prepare(directory)
            payload = json.loads(
                (Path(directory) / f"{prepare.HOUSEHOLD_FILE}.provenance.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(payload["is_synthetic"])
            self.assertTrue(any("--synthetic" in note for note in payload["notes"]))

    def test_the_emission_series_is_always_synthetic(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            self.run_prepare(directory)
            payload = json.loads(
                (Path(directory) / f"{prepare.EMISSION_FILE}.provenance.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(payload["is_synthetic"])

    def test_the_written_csv_is_readable_and_hourly(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_prepare(directory)
            frame = pd.read_csv(
                Path(directory) / prepare.HOUSEHOLD_FILE,
                index_col="timestamp",
                parse_dates=True,
            )
            self.assertGreater(len(frame), 100)
            gaps = frame.index.to_series().diff().dropna().unique()
            self.assertEqual(list(gaps), [pd.Timedelta(hours=1)])

    def test_small_produces_fewer_rows_than_a_full_run_would(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_prepare(directory)
            frame = pd.read_csv(Path(directory) / prepare.HOUSEHOLD_FILE)
            self.assertEqual(len(frame), prepare.SMALL_LOAD_HOURS)


if __name__ == "__main__":
    unittest.main()
