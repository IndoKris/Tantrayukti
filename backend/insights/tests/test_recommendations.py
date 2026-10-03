"""Tests for the savings recommendation engine."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from insights import recommendations
from insights.models import Detector
from insights.tests._fixtures import build_world, make_anomaly


class ActionCatalogueTests(TestCase):
    def setUp(self):
        self.world = build_world()
        self.device = self.world["devices"]["big"]

    def recommend(self, detector=Detector.NIGHT_LOAD):
        anomaly = make_anomaly(self.device, detector=detector)
        return recommendations.recommend(
            anomaly, tariff=self.world["tariff"], factor=self.world["factor"]
        )

    def test_recommendations_are_produced_for_a_night_load_anomaly(self):
        actions = self.recommend()["actions"]
        self.assertTrue(actions)

    def test_every_action_reports_kwh_rupees_and_co2(self):
        for action in self.recommend()["actions"]:
            savings = action["savings"]
            self.assertIsNotNone(savings["kwh_per_month"])
            self.assertIsNotNone(savings["inr_per_month"])
            self.assertIsNotNone(savings["kg_co2_per_month"])

    def test_every_action_shows_its_formula(self):
        """A saving with no visible derivation is indistinguishable from an invented one."""
        for action in self.recommend()["actions"]:
            self.assertIn("=", action["formula"])
            self.assertIn("kWh/month", action["formula"])

    def test_every_action_lists_its_assumptions(self):
        for action in self.recommend()["actions"]:
            self.assertTrue(action["assumptions"], action["code"])

    def test_every_action_carries_the_estimate_caveat(self):
        for action in self.recommend()["actions"]:
            self.assertIn("not a measured", action["caveat"])

    def test_co2_is_priced_with_the_factor_and_its_source(self):
        action = self.recommend()["actions"][0]
        co2 = action["pricing"]["co2"]
        self.assertEqual(Decimal(co2["kg_co2_per_kwh"]), Decimal("0.82000"))
        self.assertTrue(co2["factor_source"])

    def test_rupees_use_the_marginal_not_the_average_rate(self):
        """A saving comes off the top slab, so the top rate applies."""
        pricing = self.recommend()["actions"][0]["pricing"]
        self.assertEqual(Decimal(pricing["marginal_rate_inr_per_kwh"]), Decimal("10.0000"))
        self.assertIn("highest-priced", pricing["rate_basis"])

    def test_actions_are_ranked_by_rupee_saving(self):
        actions = self.recommend()["actions"]
        values = [Decimal(a["savings"]["inr_per_month"]) for a in actions]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_a_paid_action_reports_payback_with_its_assumed_cost(self):
        actions = self.recommend(Detector.BASELOAD_JUMP)["actions"]
        paid = [a for a in actions if a["capital_cost_inr"] is not None]
        self.assertTrue(paid)
        for action in paid:
            self.assertIsNotNone(action["payback_months"])
            self.assertIn("payback", action["pricing"])
            self.assertIn("assumption", action["pricing"]["payback"]["note"])

    def test_a_baseload_jump_recommends_cutting_the_standby_draw(self):
        codes = [a["code"] for a in self.recommend(Detector.BASELOAD_JUMP)["actions"]]
        self.assertIn("standby_cutoff", codes)

    def test_the_baseload_saving_uses_the_measured_step(self):
        """1.1 kWh/h extra x 24 h x 30.44 days = about 803 kWh/month."""
        actions = self.recommend(Detector.BASELOAD_JUMP)["actions"]
        standby = next(a for a in actions if a["code"] == "standby_cutoff")
        self.assertAlmostEqual(
            float(standby["savings"]["kwh_per_month"]), 1.1 * 24 * 30.44, delta=1.0
        )

    def test_recommendations_are_linked_to_the_ranked_causes(self):
        payload = self.recommend()
        self.assertTrue(payload["linked_causes"])

    def test_totals_warn_that_actions_may_overlap(self):
        totals = self.recommend()["totals_if_all_applied"]
        self.assertIn("overlap", totals["note"])

    def test_the_recurrence_assumption_is_stated(self):
        context = self.recommend()["context"]
        self.assertIn("recurrence_assumption", context)
        self.assertIn("per month", context["recurrence_assumption"])

    def test_no_tariff_yields_no_rupee_figure_rather_than_a_guess(self):
        """
        With no tariff in the database at all, the engine must decline to price
        rather than invent a rate. Passing tariff=None means "resolve one", so
        the tariffs are removed to exercise the genuinely-unconfigured path.
        """
        from billing.models import Tariff

        Tariff.objects.all().delete()
        anomaly = make_anomaly(self.device)
        payload = recommendations.recommend(
            anomaly, tariff=None, factor=self.world["factor"]
        )
        for action in payload["actions"]:
            self.assertIsNone(action["savings"]["inr_per_month"])
            self.assertIn("No tariff configured", action["pricing"]["note"])


class RecommendationEndpointTests(APITestCase):
    def setUp(self):
        self.world = build_world()
        self.anomaly = make_anomaly(self.world["devices"]["big"])
        self.url = reverse("insights:anomaly-recommendations", args=[self.anomaly.pk])

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_a_member_can_read_recommendations(self):
        self.client.force_authenticate(self.world["member"])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["actions"])

    def test_the_response_carries_formulas_and_savings(self):
        self.client.force_authenticate(self.world["member"])
        action = self.client.get(self.url).json()["actions"][0]
        self.assertIn("formula", action)
        self.assertIn("savings", action)
        self.assertIn("assumptions", action)
