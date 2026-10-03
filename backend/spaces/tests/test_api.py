"""
Tests for the spaces CRUD API.

The important property here is isolation: a member of one organisation must not
be able to see or touch another organisation's spaces, through a list, a detail
route, a filter or a write.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import Role
from spaces.models import Building, Floor, Membership, Organisation, Room

User = get_user_model()


class SpacesApiTestCase(APITestCase):
    """Two organisations, each with its own member, plus a manager and an admin."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organisation.objects.create(name="Org A")
        cls.org_b = Organisation.objects.create(name="Org B")

        cls.building_a = Building.objects.create(organisation=cls.org_a, name="A HQ")
        cls.floor_a = Floor.objects.create(building=cls.building_a, name="Ground", level=0)
        cls.room_a = Room.objects.create(
            floor=cls.floor_a, name="A Lab", area_sqm=Decimal("20.00"), occupancy=4
        )

        cls.building_b = Building.objects.create(organisation=cls.org_b, name="B HQ")
        cls.floor_b = Floor.objects.create(building=cls.building_b, name="Ground", level=0)
        cls.room_b = Room.objects.create(
            floor=cls.floor_b, name="B Lab", area_sqm=Decimal("30.00"), occupancy=6
        )

        def member(username, role, org):
            user = User.objects.create_user(
                username=username, email=f"{username}@example.com", password="pw", role=role
            )
            Membership.objects.create(user=user, organisation=org)
            return user

        cls.member_a = member("member_a", Role.MEMBER, cls.org_a)
        cls.manager_a = member("manager_a", Role.MANAGER, cls.org_a)
        cls.admin_a = member("admin_a", Role.ADMIN, cls.org_a)
        cls.member_b = member("member_b", Role.MEMBER, cls.org_b)
        cls.outsider = User.objects.create_user(
            username="outsider", email="outsider@example.com", password="pw"
        )
        cls.superuser = User.objects.create_superuser(
            username="root", email="root@example.com", password="pw"
        )


class ScopingTests(SpacesApiTestCase):
    def test_anonymous_access_is_rejected(self):
        self.assertEqual(self.client.get(reverse("spaces:room-list")).status_code, 401)

    def test_a_member_sees_only_their_own_organisation(self):
        self.client.force_authenticate(self.member_a)
        names = [row["name"] for row in self.client.get(reverse("spaces:organisation-list")).json()["results"]]
        self.assertEqual(names, ["Org A"])

    def test_a_member_sees_only_their_own_rooms(self):
        self.client.force_authenticate(self.member_a)
        names = [row["name"] for row in self.client.get(reverse("spaces:room-list")).json()["results"]]
        self.assertEqual(names, ["A Lab"])

    def test_a_user_with_no_membership_sees_nothing(self):
        self.client.force_authenticate(self.outsider)
        for route in ("organisation-list", "building-list", "floor-list", "room-list"):
            self.assertEqual(self.client.get(reverse(f"spaces:{route}")).json()["count"], 0)

    def test_a_superuser_sees_every_organisation(self):
        self.client.force_authenticate(self.superuser)
        self.assertEqual(self.client.get(reverse("spaces:organisation-list")).json()["count"], 2)

    def test_another_organisation_detail_route_is_404_not_403(self):
        """Scoping happens in the queryset, so foreign objects simply do not exist."""
        self.client.force_authenticate(self.member_a)
        response = self.client.get(reverse("spaces:room-detail", args=[self.room_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_filtering_by_a_foreign_building_leaks_nothing(self):
        self.client.force_authenticate(self.member_a)
        response = self.client.get(
            reverse("spaces:room-list"), {"building": self.building_b.pk}
        )
        self.assertEqual(response.json()["count"], 0)

    def test_a_member_cannot_modify_a_foreign_room(self):
        self.client.force_authenticate(self.manager_a)
        response = self.client.patch(
            reverse("spaces:room-detail", args=[self.room_b.pk]), {"name": "hijacked"}
        )
        self.assertEqual(response.status_code, 404)
        self.room_b.refresh_from_db()
        self.assertEqual(self.room_b.name, "B Lab")


class RolePermissionTests(SpacesApiTestCase):
    def test_a_member_may_read_but_not_write(self):
        self.client.force_authenticate(self.member_a)
        self.assertEqual(self.client.get(reverse("spaces:room-list")).status_code, 200)

        response = self.client.post(
            reverse("spaces:room-list"), {"floor": self.floor_a.pk, "name": "New"}
        )
        self.assertEqual(response.status_code, 403)

    def test_a_manager_may_create_a_room(self):
        self.client.force_authenticate(self.manager_a)
        response = self.client.post(
            reverse("spaces:room-list"),
            {"floor": self.floor_a.pk, "name": "New room", "area_sqm": "12.50", "occupancy": 3},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["total_area_sqm"], "12.50")

    def test_a_manager_may_delete_a_room_in_their_organisation(self):
        self.client.force_authenticate(self.manager_a)
        room = Room.objects.create(floor=self.floor_a, name="Temp")
        response = self.client.delete(reverse("spaces:room-detail", args=[room.pk]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())

    def test_a_member_may_not_grant_membership(self):
        self.client.force_authenticate(self.member_a)
        response = self.client.post(
            reverse("spaces:membership-list"),
            {"user": self.outsider.pk, "organisation": self.org_a.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_an_admin_may_grant_membership(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.post(
            reverse("spaces:membership-list"),
            {"user": self.outsider.pk, "organisation": self.org_a.pk},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(
            Membership.objects.filter(user=self.outsider, organisation=self.org_a).exists()
        )


class CreateOrganisationTests(SpacesApiTestCase):
    def test_creating_an_organisation_makes_the_creator_a_member(self):
        """Otherwise the new organisation would be invisible to its creator."""
        self.client.force_authenticate(self.manager_a)
        response = self.client.post(reverse("spaces:organisation-list"), {"name": "Fresh Org"})
        self.assertEqual(response.status_code, 201, response.content)

        created = Organisation.objects.get(name="Fresh Org")
        self.assertTrue(
            Membership.objects.filter(user=self.manager_a, organisation=created).exists()
        )

        visible = [row["name"] for row in self.client.get(reverse("spaces:organisation-list")).json()["results"]]
        self.assertIn("Fresh Org", visible)

    def test_slug_is_assigned_by_the_api(self):
        self.client.force_authenticate(self.manager_a)
        body = self.client.post(reverse("spaces:organisation-list"), {"name": "Slug Test"}).json()
        self.assertEqual(body["slug"], "slug-test")


class TreeEndpointTests(SpacesApiTestCase):
    def test_tree_returns_the_nested_hierarchy_for_visible_organisations_only(self):
        self.client.force_authenticate(self.member_a)
        body = self.client.get(reverse("spaces:organisation-tree")).json()

        self.assertEqual(len(body), 1)
        org = body[0]
        self.assertEqual(org["name"], "Org A")
        self.assertEqual(org["buildings"][0]["name"], "A HQ")
        self.assertEqual(org["buildings"][0]["floors"][0]["name"], "Ground")
        self.assertEqual(org["buildings"][0]["floors"][0]["rooms"][0]["name"], "A Lab")

    def test_tree_reports_derived_area_and_occupancy(self):
        self.client.force_authenticate(self.member_a)
        org = self.client.get(reverse("spaces:organisation-tree")).json()[0]
        self.assertEqual(org["total_area_sqm"], "20.00")
        self.assertEqual(org["total_occupancy"], 4)

    def test_tree_is_empty_for_a_user_with_no_membership(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(reverse("spaces:organisation-tree")).json(), [])
