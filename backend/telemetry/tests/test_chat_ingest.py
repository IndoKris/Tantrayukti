"""
Tests for chat ingestion, the mock extractors and the NILM step-change detector.

The behaviour worth pinning hardest: **a modality with no provider must decline,
not fabricate.** Several tests exist only to ensure no path can invent a reading.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from spaces.models import Building, Floor, Membership, Organisation, Room
from telemetry import extractors
from telemetry.models import Device, Reading

User = get_user_model()


class ExtractorTests(APITestCase):
    def test_a_direct_kwh_figure_is_read(self):
        result = extractors.extract("text", {"text": "the AC used 6 kWh today"})
        self.assertTrue(result.succeeded)
        self.assertEqual(result.energy_kwh, Decimal("6"))
        self.assertEqual(result.appliance, "ac")

    def test_units_spelled_out_are_read(self):
        result = extractors.extract("text", {"text": "fridge used 2.5 kilowatt-hours"})
        self.assertTrue(result.succeeded)
        self.assertEqual(result.energy_kwh, Decimal("2.5"))

    def test_watts_and_hours_are_combined_into_energy(self):
        """1500 W for 4 h is 6 kWh."""
        result = extractors.extract("text", {"text": "1500 W AC ran for 4 hours"})
        self.assertTrue(result.succeeded)
        self.assertEqual(result.energy_kwh, Decimal("6.0000"))
        self.assertTrue(any("derived" in warning for warning in result.warnings))

    def test_a_derived_figure_has_lower_confidence_than_a_stated_one(self):
        stated = extractors.extract("text", {"text": "AC used 6 kWh"})
        derived = extractors.extract("text", {"text": "1500 W AC ran 4 hours"})
        self.assertGreater(stated.confidence, derived.confidence)

    def test_an_unparseable_message_fails_with_guidance(self):
        result = extractors.extract("text", {"text": "the AC felt expensive today"})
        self.assertFalse(result.succeeded)
        self.assertIsNone(result.energy_kwh)
        self.assertIn("kWh", result.reason)

    def test_an_empty_message_fails(self):
        self.assertFalse(extractors.extract("text", {"text": "  "}).succeeded)

    def test_every_extraction_declares_whether_it_is_a_mock(self):
        result = extractors.extract("text", {"text": "AC used 6 kWh"})
        self.assertTrue(result.is_mock)
        self.assertIn("mock", result.provider)

    def test_image_input_declines_rather_than_inventing_a_value(self):
        """The central guarantee: a mock must never emit a plausible number."""
        result = extractors.extract("image", {"image_url": "http://example.com/meter.jpg"})

        self.assertFalse(result.succeeded)
        self.assertIsNone(result.energy_kwh)
        self.assertEqual(result.confidence, 0.0)
        self.assertIn("credentials", result.reason)
        self.assertIn("invented reading is worse than none", result.reason)

    def test_audio_input_declines_rather_than_inventing_a_value(self):
        result = extractors.extract("audio", {"audio_url": "http://example.com/note.m4a"})
        self.assertFalse(result.succeeded)
        self.assertIsNone(result.energy_kwh)
        self.assertIn("Whisper", result.reason)

    def test_an_unknown_modality_is_reported(self):
        result = extractors.extract("telepathy", {})
        self.assertFalse(result.succeeded)
        self.assertIn("No extractor", result.reason)


class RangeValidationTests(APITestCase):
    def test_a_plausible_figure_passes(self):
        result = extractors.extract("text", {"text": "AC used 6 kWh"})
        self.assertEqual(extractors.validate_ranges(result), [])

    def test_an_absurd_energy_figure_is_rejected(self):
        """A typo turning 6 into 6000 would distort a month of rollups."""
        result = extractors.extract("text", {"text": "AC used 6000 kWh"})
        problems = extractors.validate_ranges(result)
        self.assertTrue(problems)
        self.assertIn("plausibility limit", problems[0])

    def test_more_than_24_hours_in_a_day_is_rejected(self):
        result = extractors.extract("text", {"text": "1000 W heater ran 40 hours"})
        self.assertTrue(extractors.validate_ranges(result))

    def test_an_absurd_wattage_is_rejected(self):
        result = extractors.extract("text", {"text": "90000 W device ran 1 hour"})
        self.assertTrue(extractors.validate_ranges(result))


class IntervalSpreadingTests(APITestCase):
    def test_energy_is_spread_across_the_stated_runtime(self):
        spread = extractors.spread_over_interval(Decimal("6"), Decimal("4"), 3600)
        self.assertEqual(len(spread), 4)
        self.assertEqual(sum(value for _, value in spread), Decimal("6.000000"))

    def test_with_no_runtime_it_falls_back_to_one_hour(self):
        spread = extractors.spread_over_interval(Decimal("6"), None, 3600)
        self.assertEqual(len(spread), 1)

    def test_a_shorter_interval_produces_more_steps(self):
        spread = extractors.spread_over_interval(Decimal("6"), Decimal("1"), 900)
        self.assertEqual(len(spread), 4)

    def test_the_total_is_preserved(self):
        spread = extractors.spread_over_interval(Decimal("10"), Decimal("3"), 1800)
        self.assertAlmostEqual(
            float(sum(value for _, value in spread)), 10.0, places=4
        )


class ChatIngestEndpointTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organisation.objects.create(name="Org")
        building = Building.objects.create(organisation=cls.org, name="HQ")
        floor = Floor.objects.create(building=building, name="G", level=0)
        room = Room.objects.create(floor=floor, name="Lab", area_sqm=Decimal("20"))
        cls.device = Device.objects.create(
            room=room, name="AC meter", sample_interval_seconds=3600
        )

        other_org = Organisation.objects.create(name="Other")
        other_building = Building.objects.create(organisation=other_org, name="B")
        other_floor = Floor.objects.create(building=other_building, name="G", level=0)
        other_room = Room.objects.create(floor=other_floor, name="R")
        cls.other_device = Device.objects.create(room=other_room, name="Theirs")

        cls.user = User.objects.create_user(
            username="reporter", email="r@example.com", password="pw"
        )
        Membership.objects.create(user=cls.user, organisation=cls.org)

    def setUp(self):
        self.url = reverse("telemetry:chat-ingest")

    def post(self, **body):
        self.client.force_authenticate(self.user)
        payload = {"device": self.device.pk, "modality": "text"}
        payload.update(body)
        return self.client.post(self.url, payload)

    def test_authentication_is_required(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 401)

    def test_a_parseable_message_creates_readings(self):
        response = self.post(text="AC ran 4 hours at 1500 W")

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["stored"], 4)
        self.assertEqual(Reading.objects.filter(device=self.device).count(), 4)

    def test_readings_are_tagged_as_imported_not_metered(self):
        """Chat data must stay distinguishable from telemetry in every rollup."""
        self.post(text="AC used 6 kWh")
        for reading in Reading.objects.filter(device=self.device):
            self.assertEqual(reading.source, Reading.Source.IMPORT)

    def test_the_stored_energy_matches_the_reported_figure(self):
        self.post(text="AC ran 4 hours at 1500 W")
        total_wh = sum(
            reading.energy_wh for reading in Reading.objects.filter(device=self.device)
        )
        self.assertAlmostEqual(float(total_wh), 6000.0, places=1)

    def test_the_response_states_the_spreading_assumption(self):
        body = self.post(text="AC ran 4 hours at 1500 W").json()
        self.assertTrue(any("spread evenly" in note for note in body["assumptions"]))
        self.assertTrue(any("source=import" in note for note in body["assumptions"]))

    def test_the_response_names_the_extractor_and_that_it_is_a_mock(self):
        body = self.post(text="AC used 6 kWh").json()
        self.assertTrue(body["extraction"]["is_mock"])
        self.assertIn("mock", body["extraction"]["provider"])

    def test_an_image_is_refused_with_422_and_nothing_is_stored(self):
        response = self.post(modality="image", image_url="http://example.com/m.jpg")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["stored"], 0)
        self.assertEqual(Reading.objects.count(), 0)
        self.assertIn("credentials", response.json()["extraction"]["reason"])

    def test_audio_is_refused_with_422_and_nothing_is_stored(self):
        response = self.post(modality="audio", audio_url="http://example.com/a.m4a")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(Reading.objects.count(), 0)

    def test_an_unparseable_message_is_422_with_guidance(self):
        response = self.post(text="it felt expensive")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Reading.objects.count(), 0)
        self.assertIn("kWh", response.json()["extraction"]["reason"])

    def test_an_implausible_figure_is_422_and_lists_the_failed_check(self):
        response = self.post(text="AC used 9000 kWh")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Reading.objects.count(), 0)
        self.assertTrue(response.json()["problems"])

    def test_a_foreign_device_is_404(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            {"device": self.other_device.pk, "modality": "text", "text": "6 kWh"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Reading.objects.count(), 0)

    def test_an_explicit_date_anchors_the_readings(self):
        body = self.post(text="AC used 2 kWh", occurred_on="2026-03-02").json()
        self.assertIn("2026-03-02", body["window"]["from"])

    def test_a_malformed_date_is_a_400(self):
        response = self.post(text="AC used 2 kWh", occurred_on="last tuesday")
        self.assertEqual(response.status_code, 400)

    def test_re_posting_the_same_message_does_not_duplicate_readings(self):
        """The (device, timestamp) constraint makes a retry harmless."""
        self.post(text="AC used 2 kWh", occurred_on="2026-03-02")
        before = Reading.objects.count()
        self.post(text="AC used 2 kWh", occurred_on="2026-03-02")
        self.assertEqual(Reading.objects.count(), before)


class NilmDetectorTests(APITestCase):
    def test_a_clean_square_pulse_is_detected_as_one_event(self):
        power = np.array([100.0] * 6 + [1600.0] * 6 + [100.0] * 6)
        stamps = [f"h{index}" for index in range(len(power))]

        from ml.training.train_nilm import detect_step_changes

        found = detect_step_changes(power, stamps)
        matched = [event for event in found if event.matched]

        self.assertEqual(len(matched), 1)
        self.assertAlmostEqual(matched[0].magnitude_w, 1500.0, places=1)
        self.assertAlmostEqual(matched[0].duration_hours, 6.0, places=1)
        self.assertAlmostEqual(matched[0].energy_kwh, 9.0, places=2)

    def test_a_flat_series_yields_no_events(self):
        from ml.training.train_nilm import detect_step_changes

        power = np.array([250.0] * 40)
        self.assertEqual(detect_step_changes(power, [f"h{i}" for i in range(40)]), [])

    def test_noise_below_the_threshold_is_ignored(self):
        from ml.training.train_nilm import detect_step_changes

        rng = np.random.default_rng(3)
        power = 300 + rng.normal(0, 20, size=48)
        found = detect_step_changes(power, [f"h{i}" for i in range(48)])
        self.assertEqual([event for event in found if event.matched], [])

    def test_two_separate_cycles_are_detected_separately(self):
        from ml.training.train_nilm import detect_step_changes

        power = np.array(
            [100.0] * 5 + [1600.0] * 5 + [100.0] * 5 + [1600.0] * 5 + [100.0] * 5
        )
        found = detect_step_changes(power, [f"h{i}" for i in range(len(power))])
        self.assertEqual(len([event for event in found if event.matched]), 2)

    def test_an_unclosed_rise_is_reported_as_unmatched(self):
        """The detector shows its uncertainty rather than only its conclusions."""
        from ml.training.train_nilm import detect_step_changes

        power = np.array([100.0] * 6 + [1600.0] * 10)
        found = detect_step_changes(power, [f"h{i}" for i in range(len(power))])

        self.assertTrue(any(not event.matched for event in found))

    def test_a_fall_of_a_very_different_size_is_not_matched_to_the_rise(self):
        from ml.training.train_nilm import detect_step_changes

        # A 1500 W rise, then only a 200 W fall: not the same appliance.
        power = np.array([100.0] * 5 + [1600.0] * 5 + [1400.0] * 8)
        found = detect_step_changes(power, [f"h{i}" for i in range(len(power))])
        self.assertEqual([event for event in found if event.matched], [])

    def test_the_manifest_marks_metrics_as_not_evaluated(self):
        """
        No UK-DALE labels exist, so no accuracy figure may be produced.

        Runs the CLI only when the processed dataset is present.
        """
        from ml.config import PROCESSED_DIR
        from ml.training.train_nilm import run

        data = Path(PROCESSED_DIR) / "household_hourly.csv"
        if not data.exists():
            self.skipTest("No processed dataset; run python -m ml.data.prepare --small")

        manifest = run(["--small"])

        self.assertEqual(manifest["metrics"]["status"], "not evaluated")
        self.assertIn("ground truth", manifest["metrics"]["reason"])
        self.assertTrue(any("step-change fallback" in c for c in manifest["caveats"]))
