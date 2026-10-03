"""Tests for the hierarchy models, slugs, constraints and derived area/occupancy."""

from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from spaces.models import Building, Floor, Organisation, Room


def build_tree(org_name="Acme"):
    org = Organisation.objects.create(name=org_name)
    building = Building.objects.create(organisation=org, name="HQ")
    floor = Floor.objects.create(building=building, name="Ground", level=0)
    return org, building, floor


class OrganisationSlugTests(TestCase):
    def test_slug_is_derived_from_the_name(self):
        org = Organisation.objects.create(name="Tantrayukti Office")
        self.assertEqual(org.slug, "tantrayukti-office")

    def test_duplicate_names_get_distinct_slugs(self):
        first = Organisation.objects.create(name="Sample Home")
        second = Organisation.objects.create(name="Sample Home")
        self.assertEqual(first.slug, "sample-home")
        self.assertEqual(second.slug, "sample-home-2")

    def test_an_explicit_slug_is_kept(self):
        org = Organisation.objects.create(name="Acme", slug="custom")
        self.assertEqual(org.slug, "custom")

    def test_a_name_with_no_slug_characters_still_gets_a_slug(self):
        org = Organisation.objects.create(name="!!!")
        self.assertEqual(org.slug, "organisation")


class ConstraintTests(TestCase):
    def test_building_names_are_unique_within_an_organisation(self):
        org, _, _ = build_tree()
        with self.assertRaises(IntegrityError):
            Building.objects.create(organisation=org, name="HQ")

    def test_the_same_building_name_is_allowed_in_another_organisation(self):
        build_tree("Acme")
        other = Organisation.objects.create(name="Other")
        Building.objects.create(organisation=other, name="HQ")  # must not raise

    def test_floor_levels_are_unique_within_a_building(self):
        _, building, _ = build_tree()
        with self.assertRaises(IntegrityError):
            Floor.objects.create(building=building, name="Mezzanine", level=0)

    def test_room_names_are_unique_within_a_floor(self):
        _, _, floor = build_tree()
        Room.objects.create(floor=floor, name="Lab")
        with self.assertRaises(IntegrityError):
            Room.objects.create(floor=floor, name="Lab")

    def test_basement_levels_are_allowed(self):
        _, building, _ = build_tree()
        basement = Floor.objects.create(building=building, name="Basement", level=-1)
        self.assertEqual(basement.level, -1)


class DerivedAreaTests(TestCase):
    def test_room_area_rolls_up_to_floor_building_and_organisation(self):
        org, building, floor = build_tree()
        Room.objects.create(floor=floor, name="A", area_sqm=Decimal("10.00"), occupancy=2)
        Room.objects.create(floor=floor, name="B", area_sqm=Decimal("15.50"), occupancy=3)

        self.assertEqual(floor.total_area_sqm, Decimal("25.50"))
        self.assertEqual(building.total_area_sqm, Decimal("25.50"))
        self.assertEqual(org.total_area_sqm, Decimal("25.50"))

    def test_occupancy_rolls_up_the_same_way(self):
        org, building, floor = build_tree()
        Room.objects.create(floor=floor, name="A", area_sqm=Decimal("10.00"), occupancy=2)
        Room.objects.create(floor=floor, name="B", area_sqm=Decimal("15.50"), occupancy=3)

        self.assertEqual(floor.total_occupancy, 5)
        self.assertEqual(building.total_occupancy, 5)
        self.assertEqual(org.total_occupancy, 5)

    def test_a_stated_area_overrides_the_children_sum(self):
        """A building that states its own area keeps it, so shared space is not lost."""
        _, building, floor = build_tree()
        Room.objects.create(floor=floor, name="A", area_sqm=Decimal("10.00"))
        building.area_sqm = Decimal("400.00")
        building.save()

        self.assertEqual(building.total_area_sqm, Decimal("400.00"))
        self.assertEqual(floor.total_area_sqm, Decimal("10.00"))

    def test_unknown_area_stays_none_rather_than_becoming_zero(self):
        """Phase 16 must be able to skip a space instead of dividing by zero."""
        org, building, floor = build_tree()
        Room.objects.create(floor=floor, name="A")  # no area stated

        self.assertIsNone(floor.total_area_sqm)
        self.assertIsNone(building.total_area_sqm)
        self.assertIsNone(org.total_area_sqm)

    def test_partially_known_areas_sum_only_the_known_ones(self):
        _, _, floor = build_tree()
        Room.objects.create(floor=floor, name="A", area_sqm=Decimal("12.00"))
        Room.objects.create(floor=floor, name="B")  # unknown

        self.assertEqual(floor.total_area_sqm, Decimal("12.00"))

    def test_a_room_with_no_occupancy_counts_as_zero_people(self):
        _, _, floor = build_tree()
        Room.objects.create(floor=floor, name="Store")
        self.assertEqual(floor.total_occupancy, 0)


class NavigationTests(TestCase):
    def test_every_level_can_name_its_organisation(self):
        org, building, floor = build_tree()
        room = Room.objects.create(floor=floor, name="A")

        self.assertEqual(building.organisation, org)
        self.assertEqual(floor.organisation, org)
        self.assertEqual(room.organisation, org)

    def test_organisation_rooms_spans_every_building_and_floor(self):
        org, building, floor = build_tree()
        Room.objects.create(floor=floor, name="A")
        upper = Floor.objects.create(building=building, name="First", level=1)
        Room.objects.create(floor=upper, name="B")
        second_building = Building.objects.create(organisation=org, name="Annexe")
        annexe_floor = Floor.objects.create(building=second_building, name="Ground", level=0)
        Room.objects.create(floor=annexe_floor, name="C")

        self.assertEqual(org.rooms.count(), 3)

    def test_str_shows_the_path(self):
        _, _, floor = build_tree()
        room = Room.objects.create(floor=floor, name="Lab")
        self.assertEqual(str(room), "HQ / Ground / Lab")
        self.assertEqual(str(floor), "HQ / Ground")
