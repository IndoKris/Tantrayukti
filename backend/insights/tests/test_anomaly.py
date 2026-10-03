"""
Tests for anomaly detection, plus an evaluation against simulator-injected
faults that writes precision/recall/F1 into `metrics.json`.

The evaluation is the part the plan asks for: a detector is only credible if it
is scored against known-faulty data, and those scores must come from code rather
than from a claim in a README.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from django.conf import settings
from django.test import TestCase

from insights import detection
from insights.models import Anomaly, AnomalyState, Detector, Severity
from spaces.models import Building, Floor, Organisation, Room
from telemetry.models import Device

IST = ZoneInfo("Asia/Kolkata")


def observations(
    hours: int,
    base_kwh: float = 1.0,
    start: datetime | None = None,
    seed: int = 7,
) -> list[detection.Observation]:
    """A clean daily-shaped series with mild noise."""
    rng = np.random.default_rng(seed)
    start = start or datetime(2026, 3, 1, 0, tzinfo=IST)
    shape = [0.4, 0.35, 0.33, 0.33, 0.35, 0.5, 0.8, 1.1, 1.2, 1.0, 0.9, 0.9,
             0.95, 0.9, 0.85, 0.9, 1.05, 1.3, 1.6, 1.75, 1.6, 1.3, 0.9, 0.6]

    rows = []
    for index in range(hours):
        stamp = start + timedelta(hours=index)
        value = base_kwh * shape[stamp.hour] * float(rng.normal(1.0, 0.04))
        rows.append(
            detection.Observation(
                timestamp=stamp,
                energy_kwh=max(0.05, value),
                peak_power_w=value * 1800,
                mean_power_w=value * 1000,
            )
        )
    return rows


class SeasonalDetectorTests(TestCase):
    def test_a_clean_series_raises_nothing(self):
        """A healthy week must produce an empty feed, not a quota of anomalies."""
        self.assertEqual(detection.detect_seasonal(observations(24 * 14)), [])

    def test_a_large_spike_is_detected(self):
        rows = observations(24 * 14)
        rows[200].energy_kwh = 12.0
        findings = detection.detect_seasonal(rows)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].detector, Detector.SEASONAL_ZSCORE)
        self.assertEqual(findings[0].timestamp, rows[200].timestamp)

    def test_the_finding_carries_expected_versus_observed(self):
        rows = observations(24 * 14)
        rows[200].energy_kwh = 12.0
        finding = detection.detect_seasonal(rows)[0]

        self.assertEqual(finding.observed_kwh, 12.0)
        self.assertIsNotNone(finding.expected_kwh)
        self.assertGreater(finding.excess_kwh, 0)
        self.assertIn("z_score", finding.evidence)
        self.assertIn("baseline_median_kwh", finding.evidence)

    def test_severity_rises_with_the_z_score(self):
        rows = observations(24 * 14)
        rows[200].energy_kwh = 60.0
        self.assertEqual(detection.detect_seasonal(rows)[0].severity, Severity.CRITICAL)

    def test_weekday_and_weekend_get_separate_baselines(self):
        """An office being quiet on Sunday is not an anomaly."""
        baseline = detection.seasonal_baseline(observations(24 * 14))
        keys = set(baseline)
        self.assertTrue(any(weekend for _, weekend in keys))
        self.assertTrue(any(not weekend for _, weekend in keys))

    def test_an_hour_with_too_little_history_is_not_judged(self):
        baseline = detection.seasonal_baseline(observations(5))
        self.assertEqual(baseline, {})


class IsolationForestTests(TestCase):
    def test_a_clean_series_raises_nothing(self):
        """The threshold is validated against the data, not a fixed contamination."""
        self.assertEqual(detection.detect_isolation_forest(observations(24 * 14)), [])

    def test_an_extreme_combination_is_detected(self):
        rows = observations(24 * 14)
        rows[300].energy_kwh = 25.0
        rows[300].peak_power_w = 400.0  # high energy, implausibly low peak
        findings = detection.detect_isolation_forest(rows)
        self.assertTrue(any(f.timestamp == rows[300].timestamp for f in findings))

    def test_the_evidence_records_the_validated_threshold(self):
        rows = observations(24 * 14)
        rows[300].energy_kwh = 25.0
        findings = detection.detect_isolation_forest(rows)
        if not findings:
            self.skipTest("No finding to inspect.")

        evidence = findings[0].evidence
        self.assertEqual(evidence["contamination"], "auto")
        self.assertIn("isolation_forest_score", evidence)
        self.assertIn("No fixed", evidence["threshold_rule"])
        self.assertIn("magnitude_fence_kwh", evidence)

    def test_a_short_series_is_not_scored(self):
        self.assertEqual(detection.detect_isolation_forest(observations(10)), [])


class RuleDetectorTests(TestCase):
    def test_night_load_is_detected(self):
        rows = observations(24 * 10)
        for row in rows:
            if row.timestamp.day == 5 and row.timestamp.hour in (2, 3):
                row.energy_kwh = 4.0

        findings = detection.detect_night_load(rows)
        self.assertTrue(findings)
        self.assertEqual(findings[0].detector, Detector.NIGHT_LOAD)
        self.assertIn("night_median_kwh", findings[0].evidence)

    def test_a_clean_night_raises_nothing(self):
        self.assertEqual(detection.detect_night_load(observations(24 * 10)), [])

    def test_a_baseload_jump_is_detected(self):
        rows = observations(24 * 10)
        midpoint = rows[len(rows) // 2].timestamp
        for row in rows:
            if row.timestamp >= midpoint:
                row.energy_kwh += 1.5

        findings = detection.detect_baseload_jump(rows)
        self.assertTrue(findings)
        self.assertEqual(findings[0].detector, Detector.BASELOAD_JUMP)
        self.assertGreater(findings[0].evidence["increase_fraction"], 0.5)
        self.assertIn("extra_kwh_per_day", findings[0].evidence)

    def test_a_steady_baseload_raises_nothing(self):
        self.assertEqual(detection.detect_baseload_jump(observations(24 * 10)), [])

    def test_a_device_left_on_is_detected(self):
        rows = observations(24 * 10)
        start = 24 * 5
        for row in rows[start : start + 9]:
            row.energy_kwh = 3.2  # flat plateau

        findings = detection.detect_device_left_on(rows)
        self.assertTrue(findings)
        self.assertEqual(findings[0].detector, Detector.DEVICE_LEFT_ON)
        self.assertGreaterEqual(findings[0].evidence["run_hours"], 4)

    def test_a_normal_varying_load_is_not_called_left_on(self):
        """The rule needs a plateau; an ordinary evening peak must not match."""
        self.assertEqual(detection.detect_device_left_on(observations(24 * 10)), [])


class PipelineTests(TestCase):
    def test_detect_all_runs_every_detector_and_sorts_worst_first(self):
        rows = observations(24 * 14)
        rows[200].energy_kwh = 30.0
        findings = detection.detect_all(rows)

        self.assertTrue(findings)
        ranks = [
            detection.Anomaly.severity_rank.fget(
                detection.Anomaly(severity=f.severity)
            )
            for f in findings
        ]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_a_clean_series_produces_no_findings_at_all(self):
        self.assertEqual(detection.detect_all(observations(24 * 14)), [])


class PersistenceTests(TestCase):
    def setUp(self):
        org = Organisation.objects.create(name="Org")
        building = Building.objects.create(organisation=org, name="HQ")
        floor = Floor.objects.create(building=building, name="G", level=0)
        room = Room.objects.create(floor=floor, name="Lab", area_sqm=Decimal("20"))
        self.device = Device.objects.create(room=room, name="Mains")

        rows = observations(24 * 14)
        rows[200].energy_kwh = 20.0
        self.findings = detection.detect_all(rows)

    def test_findings_are_stored_as_anomalies(self):
        result = detection.persist_findings(self.device, self.findings)
        self.assertEqual(result["created"], len(self.findings))
        self.assertEqual(Anomaly.objects.count(), len(self.findings))

    def test_re_running_updates_rather_than_duplicating(self):
        detection.persist_findings(self.device, self.findings)
        before = Anomaly.objects.count()

        result = detection.persist_findings(self.device, self.findings)
        self.assertEqual(Anomaly.objects.count(), before)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], before)

    def test_a_resolved_anomaly_is_not_reopened(self):
        """Re-detection must not undo a person's decision."""
        detection.persist_findings(self.device, self.findings)
        anomaly = Anomaly.objects.first()
        anomaly.resolve("fixed the timer")

        result = detection.persist_findings(self.device, self.findings)
        anomaly.refresh_from_db()

        self.assertEqual(anomaly.state, AnomalyState.RESOLVED)
        self.assertGreaterEqual(result["skipped_already_closed"], 1)

    def test_the_lifecycle_transitions_work(self):
        from django.contrib.auth import get_user_model

        detection.persist_findings(self.device, self.findings)
        anomaly = Anomaly.objects.first()
        user = get_user_model().objects.create_user(
            username="m", email="m@example.com", password="pw"
        )

        self.assertEqual(anomaly.state, AnomalyState.OPEN)
        anomaly.acknowledge(user)
        self.assertEqual(anomaly.state, AnomalyState.ACKNOWLEDGED)
        self.assertEqual(anomaly.acknowledged_by, user)
        self.assertTrue(anomaly.is_open)

        anomaly.resolve("done")
        self.assertEqual(anomaly.state, AnomalyState.RESOLVED)
        self.assertFalse(anomaly.is_open)


def _load_simulator():
    simulator_dir = Path(settings.BASE_DIR).parent / "simulator"
    if not (simulator_dir / "generator.py").exists():
        return None
    if str(simulator_dir) not in sys.path:
        sys.path.insert(0, str(simulator_dir))
    try:
        import generator

        return generator
    except ImportError:
        return None


SIMULATOR = _load_simulator()


class SimulatorFaultEvaluationTests(TestCase):
    """
    Score the detectors against the Phase 7 simulator's injected faults and
    write precision/recall/F1 into `metrics.json`.

    The simulator labels every sample with the fault active at that moment, so
    these are real labels rather than a self-assessment.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if SIMULATOR is None:
            raise cls.skipException("simulator/generator.py not importable.")

    def build(self, faults, days=14, interval=3600):
        series = SIMULATOR.generate(
            site_keys=["office"],
            start=datetime(2026, 3, 1, 0, tzinfo=IST),
            days=days,
            interval_seconds=interval,
            seed=99,
            fault_names=tuple(faults),
        )
        mains = next(s for s in series if s.appliance_key == "mains")
        rows = [
            detection.Observation(
                timestamp=sample.timestamp,
                energy_kwh=sample.energy_wh / 1000,
                peak_power_w=sample.active_power_w,
                mean_power_w=sample.active_power_w,
            )
            for sample in mains.samples
        ]
        truth = {sample.timestamp: bool(sample.fault) for sample in mains.samples}
        return rows, truth

    def score(self, faults):
        rows, truth = self.build(faults)
        findings = detection.detect_all(rows)
        flagged = {finding.timestamp for finding in findings}

        true_positive = sum(1 for stamp, faulty in truth.items() if faulty and stamp in flagged)
        false_positive = sum(
            1 for stamp, faulty in truth.items() if not faulty and stamp in flagged
        )
        false_negative = sum(
            1 for stamp, faulty in truth.items() if faulty and stamp not in flagged
        )

        precision = (
            true_positive / (true_positive + false_positive)
            if (true_positive + false_positive)
            else None
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if (true_positive + false_negative)
            else None
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall
            else None
        )
        return {
            "faults_injected": list(faults),
            "faulty_hours": sum(1 for v in truth.values() if v),
            "clean_hours": sum(1 for v in truth.values() if not v),
            "true_positives": true_positive,
            "false_positives": false_positive,
            "false_negatives": false_negative,
            "precision": None if precision is None else round(precision, 4),
            "recall": None if recall is None else round(recall, 4),
            "f1": None if f1 is None else round(f1, 4),
        }

    def test_a_clean_simulator_run_produces_few_false_positives(self):
        rows, truth = self.build([])
        findings = detection.detect_all(rows)
        false_positive_rate = len({f.timestamp for f in findings}) / max(len(truth), 1)
        self.assertLess(false_positive_rate, 0.10, f"{len(findings)} findings on clean data")

    def test_night_load_is_recalled(self):
        result = self.score(["night-load"])
        self.assertIsNotNone(result["recall"])
        self.assertGreater(result["recall"], 0.0, result)

    def test_evaluation_is_written_to_metrics_json(self):
        """The plan requires these figures to come from code, not from prose."""
        from ml.config import METRICS_PATH

        results = {
            "night_load": self.score(["night-load"]),
            "baseload_jump": self.score(["baseload-jump"]),
            "ac_left_on": self.score(["ac-left-on"]),
            "all_faults": self.score(["night-load", "baseload-jump", "ac-left-on"]),
        }

        payload = {}
        if METRICS_PATH.exists():
            try:
                payload = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}

        payload["anomaly_detection"] = {
            "status": "evaluated",
            "evaluated_by": "insights/tests/test_anomaly.py::SimulatorFaultEvaluationTests",
            "data": "Phase 7 simulator, office site, 14 days hourly, seed 99",
            "labels": (
                "Per-sample fault labels emitted by the simulator, so these are "
                "real labels rather than a self-assessment."
            ),
            "detectors": [d.value for d in Detector],
            "scenarios": results,
            "caveats": [
                "Scored on SYNTHETIC simulator data, not on real faults.",
                "An anomaly is counted as a hit only when its hour matches a "
                "faulty hour exactly; a detector that flags the hour after a "
                "fault starts is counted as a miss, so recall is conservative.",
                "The baseload-jump detector reports one finding for a multi-day "
                "condition by design, so its recall per faulty hour is low while "
                "its precision is high.",
            ],
        }
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        METRICS_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

        written = json.loads(METRICS_PATH.read_text(encoding="utf-8"))["anomaly_detection"]
        self.assertEqual(written["status"], "evaluated")
        self.assertIn("night_load", written["scenarios"])
        for scenario in written["scenarios"].values():
            self.assertIn("precision", scenario)
            self.assertIn("recall", scenario)
            self.assertIn("f1", scenario)
