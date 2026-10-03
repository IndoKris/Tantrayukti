"""Tests for ranked cause explanation, one per injected fault type."""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from insights import causes
from insights.models import Detector
from insights.tests._fixtures import build_world, make_anomaly


class CauseRankingTests(TestCase):
    def setUp(self):
        self.world = build_world()
        self.device = self.world["devices"]["big"]

    def ranked(self, detector):
        return causes.rank_causes(make_anomaly(self.device, detector=detector))

    def test_night_load_is_attributed_to_an_occupancy_mismatch(self):
        ranked = self.ranked(Detector.NIGHT_LOAD)
        self.assertEqual(ranked[0].code, "night_occupancy_mismatch")

    def test_a_baseload_jump_is_attributed_to_a_new_always_on_load(self):
        ranked = self.ranked(Detector.BASELOAD_JUMP)
        self.assertEqual(ranked[0].code, "baseload_increase")

    def test_a_left_on_device_is_attributed_to_equipment_left_running(self):
        ranked = self.ranked(Detector.DEVICE_LEFT_ON)
        self.assertEqual(ranked[0].code, "device_left_on")

    def test_a_seasonal_night_spike_is_attributed_to_occupancy(self):
        ranked = self.ranked(Detector.SEASONAL_ZSCORE)
        self.assertEqual(ranked[0].code, "night_occupancy_mismatch")

    def test_an_isolation_forest_finding_is_labelled_an_unusual_pattern(self):
        ranked = self.ranked(Detector.ISOLATION_FOREST)
        self.assertEqual(ranked[0].code, "unusual_pattern")

    def test_causes_are_ordered_by_confidence(self):
        ranked = self.ranked(Detector.SEASONAL_ZSCORE)
        confidences = [cause.confidence for cause in ranked]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_every_cause_carries_evidence(self):
        for detector in Detector:
            for cause in self.ranked(detector):
                self.assertTrue(cause.evidence, f"{detector}/{cause.code} has no evidence")

    def test_duplicate_codes_are_collapsed_keeping_the_strongest(self):
        ranked = self.ranked(Detector.NIGHT_LOAD)
        codes = [cause.code for cause in ranked]
        self.assertEqual(len(codes), len(set(codes)))

    def test_an_anomaly_with_no_evidence_says_so_rather_than_guessing(self):
        anomaly = make_anomaly(self.device, detector="unknown_detector", evidence={})
        ranked = causes.rank_causes(anomaly)
        self.assertEqual(ranked[0].code, "insufficient_evidence")


class CauseTextTests(TestCase):
    def setUp(self):
        self.world = build_world()
        self.device = self.world["devices"]["big"]

    def test_every_detector_renders_a_readable_sentence_offline(self):
        for detector in Detector:
            anomaly = make_anomaly(self.device, detector=detector)
            for cause in causes.rank_causes(anomaly):
                text = causes.describe(cause)
                self.assertGreater(len(text), 20, f"{detector}/{cause.code}: {text!r}")
                self.assertNotIn("{", text, f"{detector}/{cause.code} left a placeholder")

    def test_the_baseload_sentence_quotes_the_real_numbers(self):
        anomaly = make_anomaly(self.device, detector=Detector.BASELOAD_JUMP)
        text = causes.describe(causes.rank_causes(anomaly)[0])
        self.assertIn("0.4", text)
        self.assertIn("1.5", text)
        self.assertIn("26.4", text)

    def test_a_missing_template_field_degrades_to_the_label(self):
        cause = causes.Cause(code="device_left_on", label="Fallback label", confidence=0.5)
        self.assertEqual(causes.describe(cause), "Fallback label")


class ExplainPayloadTests(TestCase):
    def setUp(self):
        self.world = build_world()
        self.anomaly = make_anomaly(self.world["devices"]["big"])

    def test_the_payload_states_that_ranking_is_rule_based(self):
        payload = causes.explain(self.anomaly)
        self.assertFalse(payload["wording"]["llm_used"])
        self.assertIn("never by a language model", payload["wording"]["note"])

    def test_requesting_an_llm_without_a_provider_falls_back_and_says_so(self):
        payload = causes.explain(self.anomaly, use_llm=True)
        self.assertTrue(payload["wording"]["llm_requested"])
        self.assertFalse(payload["wording"]["llm_used"])
        self.assertIn("no provider is configured", payload["wording"]["note"])

    def test_the_payload_names_a_top_cause(self):
        payload = causes.explain(self.anomaly)
        self.assertEqual(payload["top_cause"], payload["causes"][0]["code"])


class CauseEndpointTests(APITestCase):
    def setUp(self):
        self.world = build_world()
        self.anomaly = make_anomaly(self.world["devices"]["big"])
        self.url = reverse("insights:anomaly-causes", args=[self.anomaly.pk])

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_a_member_can_read_causes(self):
        self.client.force_authenticate(self.world["member"])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["causes"])

    def test_each_cause_includes_its_explanation_and_evidence(self):
        self.client.force_authenticate(self.world["member"])
        cause = self.client.get(self.url).json()["causes"][0]
        self.assertIn("explanation", cause)
        self.assertIn("evidence", cause)
        self.assertIn("confidence", cause)

    def test_a_foreign_anomaly_is_404(self):
        """Scoping lives in get_queryset, so another organisation simply does not exist."""
        from decimal import Decimal

        from spaces.models import Building, Floor, Organisation, Room
        from telemetry.models import Device

        other_org = Organisation.objects.create(name="Other org")
        other_building = Building.objects.create(organisation=other_org, name="Their HQ")
        other_floor = Floor.objects.create(building=other_building, name="G", level=0)
        other_room = Room.objects.create(
            floor=other_floor, name="Their room", area_sqm=Decimal("20")
        )
        other_device = Device.objects.create(room=other_room, name="Their mains")
        foreign = make_anomaly(other_device)

        self.client.force_authenticate(self.world["member"])
        response = self.client.get(reverse("insights:anomaly-causes", args=[foreign.pk]))
        self.assertEqual(response.status_code, 404)
