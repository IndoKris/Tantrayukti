"""Tests for the space and period comparison APIs."""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from insights.tests._fixtures import add_readings, build_world
from spaces.models import Organisation


class SpaceComparisonTests(APITestCase):
    def setUp(self):
        self.world = build_world()
        # Big room: 200 m2, 40 people, 100 kWh -> 0.5 kWh/m2, 2.5 kWh/person
        # Small room: 10 m2, 1 person, 20 kWh  -> 2.0 kWh/m2, 20 kWh/person
        add_readings(self.world["devices"]["big"], hours=10, kwh_per_hour=10)
        add_readings(self.world["devices"]["small"], hours=10, kwh_per_hour=2)
        add_readings(self.world["devices"]["unmeasured"], hours=10, kwh_per_hour=5)

        self.url = reverse("insights:compare-spaces")
        now = timezone.now()
        self.window = {
            "from": (now - timedelta(days=2)).isoformat(),
            "to": (now + timedelta(hours=1)).isoformat(),
        }

    def get(self, **params):
        self.client.force_authenticate(self.world["member"])
        return self.client.get(
            self.url,
            {"space": f"floor:{self.world['floor'].pk}", **self.window, **params},
        )

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_a_malformed_space_is_a_400(self):
        self.client.force_authenticate(self.world["member"])
        self.assertEqual(self.client.get(self.url, {"space": "floor"}).status_code, 400)

    def test_rooms_are_compared_and_ranked(self):
        body = self.get().json()
        self.assertEqual(body["compared_level"], "room")
        self.assertTrue(body["results"])
        self.assertEqual(body["results"][0]["rank"], 1)

    def test_the_small_room_ranks_worst_per_square_metre(self):
        """Raw energy would rank the big room first; normalisation is the point."""
        body = self.get(normalise_by="area").json()
        names = [row["name"] for row in body["results"]]
        self.assertEqual(names[0], "Store")

    def test_raw_energy_would_have_ranked_the_big_room_first(self):
        body = self.get(normalise_by="none").json()
        self.assertEqual(body["results"][0]["name"], "Open workspace")
        self.assertTrue(any("NOT NORMALISED" in note for note in body["notes"]))

    def test_per_square_metre_is_computed_correctly(self):
        body = self.get(normalise_by="area").json()
        by_name = {row["name"]: row for row in body["results"]}
        self.assertAlmostEqual(float(by_name["Store"]["kwh_per_sqm"]), 2.0, places=3)
        self.assertAlmostEqual(
            float(by_name["Open workspace"]["kwh_per_sqm"]), 0.5, places=3
        )

    def test_per_person_normalisation_also_works(self):
        body = self.get(normalise_by="occupancy").json()
        by_name = {row["name"]: row for row in body["results"]}
        self.assertAlmostEqual(float(by_name["Store"]["kwh_per_person"]), 20.0, places=3)
        self.assertAlmostEqual(
            float(by_name["Open workspace"]["kwh_per_person"]), 2.5, places=3
        )

    def test_a_space_with_no_area_is_excluded_and_explained(self):
        """Ranking it on raw energy would be a meaningless comparison."""
        body = self.get(normalise_by="area").json()
        excluded = {row["name"] for row in body["excluded"]}

        self.assertIn("Corridor", excluded)
        self.assertNotIn("Corridor", {row["name"] for row in body["results"]})
        self.assertIn("No area recorded", body["excluded"][0]["excluded_reason"])

    def test_the_exclusion_is_mentioned_in_the_notes(self):
        body = self.get(normalise_by="area").json()
        self.assertTrue(any("excluded" in note for note in body["notes"]))

    def test_an_unknown_normalisation_is_a_400(self):
        self.assertEqual(self.get(normalise_by="vibes").status_code, 400)

    def test_a_room_cannot_be_compared_inside(self):
        self.client.force_authenticate(self.world["member"])
        response = self.client.get(
            self.url,
            {"space": f"room:{self.world['rooms']['big'].pk}", **self.window},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot compare inside", response.json()["detail"])

    def test_another_organisation_yields_no_rows(self):
        other = Organisation.objects.create(name="Other")
        self.client.force_authenticate(self.world["member"])
        response = self.client.get(
            self.url, {"space": f"organisation:{other.pk}", **self.window}
        )
        self.assertEqual(response.json()["results"], [])


class PeriodComparisonTests(APITestCase):
    def setUp(self):
        self.world = build_world()
        self.url = reverse("insights:compare-periods")

    def get(self, **params):
        self.client.force_authenticate(self.world["member"])
        return self.client.get(
            self.url, {"space": f"floor:{self.world['floor'].pk}", **params}
        )

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_the_four_documented_periods_are_accepted(self):
        for period in ("day", "week", "month", "same_weekday_last_week"):
            response = self.get(period=period)
            self.assertEqual(response.status_code, 200, f"{period}: {response.content}")
            self.assertEqual(response.json()["period"], period)

    def test_an_unknown_period_is_a_400(self):
        self.assertEqual(self.get(period="fortnight").status_code, 400)

    def test_both_windows_are_reported(self):
        body = self.get(period="day").json()
        self.assertIn("current", body)
        self.assertIn("previous", body)
        self.assertIn("change_kwh", body)
        self.assertIn("direction", body)

    def test_same_weekday_comparison_looks_back_seven_days(self):
        body = self.get(period="same_weekday_last_week").json()
        self.assertIn("same weekday", body["label"])

    def test_an_incomplete_period_is_pro_rated_and_says_so(self):
        """A part-way-through month against a whole month would be a false saving."""
        body = self.get(period="month").json()
        if not body["is_partial_period"]:
            self.skipTest("Ran on the last instant of a month.")

        self.assertLess(float(body["elapsed_fraction"]), 1.0)
        self.assertTrue(any("pro-rated" in note for note in body["notes"]))

    def test_an_increase_is_reported_as_up(self):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        today_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        # Yesterday small, today large.
        add_readings(
            self.world["devices"]["big"], hours=4, kwh_per_hour=1,
            end=today_start - timedelta(hours=1),
        )
        add_readings(self.world["devices"]["big"], hours=3, kwh_per_hour=20, end=now)

        body = self.get(period="day").json()
        self.assertEqual(body["direction"], "up")
        self.assertGreater(float(body["change_kwh"]), 0)

    def test_empty_periods_are_flagged_as_not_meaningful(self):
        body = self.get(period="day").json()
        self.assertTrue(any("not meaningful" in note for note in body["notes"]))
