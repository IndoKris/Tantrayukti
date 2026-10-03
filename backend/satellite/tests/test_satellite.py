"""
Tests for the satellite NO2 module and the community map.

Two properties get the most attention, both called out in the plan:

* **NO2 is a column density**, never presented as a surface concentration.
* **Hotspots use a validated threshold**, so a set of similar cities produces
  no hotspots rather than a fixed fraction of them.
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from satellite import hotspots
from satellite.models import NO2_UNIT, CityNo2, CommunityPoint, round_to_city
from spaces.models import Building, Floor, Membership, Organisation, Room
from telemetry.models import Device, Reading

User = get_user_model()


def make_city(name, no2, population=5.0, latitude="21.146", longitude="79.089"):
    return CityNo2.objects.create(
        city=name,
        state="Test",
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
        no2_umol_per_m2=Decimal(str(no2)),
        population_millions=Decimal(str(population)),
        source="test fixture",
        is_measured=False,
    )


class SeedTests(APITestCase):
    def seed(self) -> str:
        out = StringIO()
        call_command("seed_no2", stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_twenty_cities_are_loaded(self):
        self.seed()
        self.assertEqual(CityNo2.objects.count(), 20)

    def test_every_row_is_flagged_as_a_fallback_not_a_measurement(self):
        self.seed()
        for city in CityNo2.objects.all():
            self.assertFalse(city.is_measured, city.city)
            self.assertIn("STATIC FALLBACK", city.source)

    def test_the_source_states_the_column_units(self):
        self.seed()
        source = CityNo2.objects.first().source
        self.assertIn("COLUMN", source)
        self.assertIn(NO2_UNIT, source)
        self.assertIn("not a surface concentration", source)

    def test_the_command_warns_about_units_and_provenance(self):
        output = self.seed()
        self.assertIn("STATIC FALLBACK", output)
        self.assertIn("not surface ppb", output)

    def test_coordinates_are_rounded_to_city_level(self):
        """3 decimal places is about 100 m, so no point identifies a household."""
        self.seed()
        for city in CityNo2.objects.all():
            self.assertEqual(city.latitude, round_to_city(city.latitude))
            self.assertLessEqual(abs(city.latitude.as_tuple().exponent), 3)

    def test_re_running_is_idempotent(self):
        self.seed()
        before = CityNo2.objects.count()
        self.seed()
        self.assertEqual(CityNo2.objects.count(), before)


class CoordinateRoundingTests(APITestCase):
    def test_a_precise_coordinate_is_rounded_on_save(self):
        """The precise value must never be persisted."""
        city = make_city("Precise", 100, latitude="21.1461234", longitude="79.0891234")
        city.refresh_from_db()

        self.assertEqual(city.latitude, Decimal("21.146"))
        self.assertEqual(city.longitude, Decimal("79.089"))

    def test_a_community_point_is_also_rounded(self):
        point = CommunityPoint.objects.create(
            latitude=Decimal("12.9716543"), longitude=Decimal("77.5946543")
        )
        point.refresh_from_db()
        self.assertEqual(point.latitude, Decimal("12.972"))
        self.assertEqual(point.longitude, Decimal("77.595"))


class HotspotThresholdTests(APITestCase):
    def test_similar_cities_produce_no_hotspots(self):
        """
        The central guarantee. A fixed contamination or a fixed percentile would
        always label one of these a hotspot; a validated threshold does not.
        """
        for index in range(12):
            make_city(f"City {index}", 100 + index * 0.5)

        result = hotspots.detect_hotspots(persist=False)

        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["hotspots"], [])

    def test_a_genuine_outlier_is_flagged(self):
        for index in range(12):
            make_city(f"City {index}", 100 + index * 0.5)
        make_city("Smog City", 400)

        result = hotspots.detect_hotspots(persist=False)
        names = [city.city for city in result["hotspots"]]

        self.assertIn("Smog City", names)

    def test_an_unusually_clean_city_is_not_a_hotspot(self):
        for index in range(12):
            make_city(f"City {index}", 100 + index * 0.5)
        make_city("Clean City", 5)

        result = hotspots.detect_hotspots(persist=False)
        names = [city.city for city in result["hotspots"]]

        self.assertNotIn("Clean City", names)

    def test_the_threshold_is_reported_so_a_flag_can_be_explained(self):
        for index in range(12):
            make_city(f"City {index}", 100 + index * 2)

        threshold = hotspots.detect_hotspots(persist=False)["threshold"]

        self.assertIn("median_umol_per_m2", threshold)
        self.assertIn("fence_umol_per_m2", threshold)
        self.assertIn("contamination='auto'", threshold["rule"])
        # The rule must disclaim both failure modes by name.
        self.assertIn("fixed contamination", threshold["rule"])
        self.assertIn("fixed percentile", threshold["rule"])

    def test_too_few_cities_is_not_evaluated_rather_than_guessed(self):
        make_city("Only one", 100)
        result = hotspots.detect_hotspots(persist=False)

        self.assertEqual(result["status"], "not evaluated")
        self.assertIn("at least", result["reason"])

    def test_detection_can_be_persisted(self):
        for index in range(12):
            make_city(f"City {index}", 100 + index * 0.5)
        make_city("Smog City", 400)

        hotspots.detect_hotspots(persist=True)
        smog = CityNo2.objects.get(city="Smog City")

        self.assertTrue(smog.is_hotspot)
        self.assertIsNotNone(smog.anomaly_score)
        self.assertIn("above the robust fence", smog.hotspot_note)

    def test_a_non_hotspot_records_why_it_was_not_flagged(self):
        for index in range(12):
            make_city(f"City {index}", 100 + index * 0.5)
        make_city("Smog City", 400)

        hotspots.detect_hotspots(persist=True)
        ordinary = CityNo2.objects.get(city="City 0")

        self.assertFalse(ordinary.is_hotspot)
        self.assertIn("Not a hotspot", ordinary.hotspot_note)


class ApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_no2", stdout=StringIO(), stderr=StringIO())
        cls.user = User.objects.create_user(
            username="viewer", email="v@example.com", password="pw"
        )

    def test_the_hotspots_endpoint_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("satellite:hotspots")).status_code, 401)

    def test_the_hotspots_endpoint_reports_its_unit_and_threshold(self):
        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("satellite:hotspots")).json()

        self.assertEqual(body["unit"], NO2_UNIT)
        self.assertIn("not a surface concentration", body["unit_note"])
        self.assertIn("threshold", body)
        self.assertIn("hotspot_count", body)

    def test_the_hotspots_endpoint_explains_an_empty_result(self):
        self.client.force_authenticate(self.user)
        note = self.client.get(reverse("satellite:hotspots")).json()["note"]
        self.assertIn("no fixed fraction", note)

    def test_posting_persists_the_detection(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("satellite:hotspots"))

        self.assertEqual(response.status_code, 201)
        self.assertTrue(CityNo2.objects.filter(is_hotspot=True).exists())

    def test_the_city_list_states_the_units_on_every_row(self):
        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("satellite:cities")).json()

        self.assertEqual(body["unit"], NO2_UNIT)
        for row in body["results"]:
            self.assertEqual(row["unit"], NO2_UNIT)
            self.assertIn("not a surface", row["unit_note"])

    def test_the_city_list_says_nothing_is_measured(self):
        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("satellite:cities")).json()

        self.assertEqual(body["measured_count"], 0)
        self.assertIn("no Earth Engine", body["provenance_note"])

    def test_no_row_exposes_a_ppb_or_surface_field(self):
        """A conversion is not performed, so no such field may exist."""
        self.client.force_authenticate(self.user)
        row = self.client.get(reverse("satellite:cities")).json()["results"][0]

        for key in row:
            self.assertNotIn("ppb", key.lower())
            self.assertNotIn("ug_per_m3", key.lower())
            self.assertNotIn("surface", key.lower())


class CommunityMapTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_no2", stdout=StringIO(), stderr=StringIO())

        cls.org = Organisation.objects.create(name="Org")
        cls.building = Building.objects.create(
            organisation=cls.org,
            name="HQ",
            latitude=Decimal("21.1461234"),
            longitude=Decimal("79.0891234"),
            area_sqm=Decimal("200.00"),
        )
        floor = Floor.objects.create(building=cls.building, name="G", level=0)
        room = Room.objects.create(floor=floor, name="Lab", area_sqm=Decimal("50"))
        cls.device = Device.objects.create(room=room, name="Mains", kind=Device.Kind.MAINS)

        # A building with no coordinates: must be skipped, not guessed.
        cls.unplaced = Building.objects.create(organisation=cls.org, name="Unplaced")

        cls.user = User.objects.create_user(
            username="mapper", email="m@example.com", password="pw"
        )
        Membership.objects.create(user=cls.user, organisation=cls.org)

        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        for index in range(24):
            Reading.objects.create(
                device=cls.device,
                timestamp=now - timedelta(hours=index + 1),
                active_power_w=Decimal("1000.00"),
                energy_wh=Decimal("1000.0000"),
            )

    def test_the_map_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("satellite:community-map")).status_code, 401)

    def test_energy_points_are_aggregated_onto_rounded_coordinates(self):
        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("satellite:community-map")).json()

        self.assertEqual(len(body["energy_points"]), 1)
        point = body["energy_points"][0]
        self.assertEqual(Decimal(point["latitude"]), Decimal("21.146"))
        self.assertEqual(Decimal(point["longitude"]), Decimal("79.089"))
        self.assertAlmostEqual(float(point["total_kwh"]), 24.0, places=2)

    def test_a_building_without_coordinates_is_skipped_not_placed(self):
        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("satellite:community-map")).json()
        self.assertEqual(body["energy_points"][0]["building_count"], 1)

    def test_the_map_states_its_privacy_rounding(self):
        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("satellite:community-map")).json()
        self.assertIn("rounded to 3 decimal places", body["privacy"])

    def test_the_no2_layer_travels_with_its_units(self):
        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("satellite:community-map")).json()

        self.assertEqual(body["no2"]["unit"], NO2_UNIT)
        self.assertEqual(len(body["no2"]["results"]), 20)

    def test_another_organisation_contributes_no_points(self):
        other = User.objects.create_user(
            username="outsider", email="o@example.com", password="pw"
        )
        self.client.force_authenticate(other)
        body = self.client.get(reverse("satellite:community-map")).json()
        self.assertEqual(body["energy_points"], [])

    def test_intensity_per_square_metre_is_computed_where_area_is_known(self):
        self.client.force_authenticate(self.user)
        point = self.client.get(reverse("satellite:community-map")).json()["energy_points"][0]
        # 24 kWh over a 200 m2 building.
        self.assertAlmostEqual(float(point["kwh_per_sqm"]), 0.12, places=3)


class Co2TrendEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="trend", email="t@example.com", password="pw"
        )
        self.url = reverse("satellite:co2-trend")

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_the_trend_is_served_from_the_training_manifest(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)

        if response.status_code == 409:
            self.assertIn("how_to_fix", response.json())
            return

        body = response.json()
        self.assertIn("fit", body)
        self.assertIn("projection", body)
        self.assertIn("caveats", body)

    def test_the_trend_states_whether_the_slope_is_significant(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        if response.status_code == 409:
            self.skipTest("No co2_trend manifest in this checkout.")

        self.assertIn("is_significant", response.json()["fit"])
        self.assertIn("p_value", response.json()["fit"])
