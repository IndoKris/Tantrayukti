"""Tests for the `seed_spaces` management command."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from accounts.models import Role
from spaces.models import Building, Floor, Membership, Organisation, Room

User = get_user_model()


def seed(**kwargs) -> str:
    out = StringIO()
    call_command("seed_spaces", stdout=out, stderr=StringIO(), **kwargs)
    return out.getvalue()


class SeedSpacesTests(TestCase):
    def test_seeding_creates_an_office_and_a_home(self):
        User.objects.create_superuser(username="root", email="r@example.com", password="pw")
        seed()

        names = set(Organisation.objects.values_list("name", flat=True))
        self.assertEqual(names, {"Tantrayukti Office", "Sample Home"})

    def test_the_office_has_three_floors_and_eight_rooms(self):
        User.objects.create_superuser(username="root", email="r@example.com", password="pw")
        seed()

        office = Organisation.objects.get(name="Tantrayukti Office")
        self.assertEqual(Floor.objects.filter(building__organisation=office).count(), 3)
        self.assertEqual(office.rooms.count(), 8)

    def test_the_home_has_one_floor_and_four_rooms(self):
        User.objects.create_superuser(username="root", email="r@example.com", password="pw")
        seed()

        home = Organisation.objects.get(name="Sample Home")
        self.assertEqual(Floor.objects.filter(building__organisation=home).count(), 1)
        self.assertEqual(home.rooms.count(), 4)

    def test_every_seeded_room_states_an_area_so_comparisons_work(self):
        User.objects.create_superuser(username="root", email="r@example.com", password="pw")
        seed()

        self.assertFalse(Room.objects.filter(area_sqm__isnull=True).exists())
        for org in Organisation.objects.all():
            self.assertIsNotNone(org.total_area_sqm)
            self.assertGreater(org.total_area_sqm, 0)

    def test_the_seed_grants_membership_so_the_data_is_visible_through_the_api(self):
        root = User.objects.create_superuser(
            username="root", email="r@example.com", password="pw"
        )
        seed()
        self.assertEqual(Membership.objects.filter(user=root).count(), 2)

    def test_re_running_is_idempotent(self):
        User.objects.create_superuser(username="root", email="r@example.com", password="pw")
        seed()
        counts = (
            Organisation.objects.count(),
            Building.objects.count(),
            Floor.objects.count(),
            Room.objects.count(),
            Membership.objects.count(),
        )

        seed()

        self.assertEqual(
            counts,
            (
                Organisation.objects.count(),
                Building.objects.count(),
                Floor.objects.count(),
                Room.objects.count(),
                Membership.objects.count(),
            ),
        )

    def test_an_explicit_user_can_be_named(self):
        User.objects.create_superuser(username="root", email="r@example.com", password="pw")
        target = User.objects.create_user(
            username="manager1", email="m@example.com", password="pw", role=Role.MANAGER
        )

        seed(username="manager1")

        self.assertEqual(Membership.objects.filter(user=target).count(), 2)
        self.assertEqual(Membership.objects.filter(user__username="root").count(), 0)

    def test_naming_an_unknown_user_fails_loudly(self):
        with self.assertRaises(SystemExit):
            seed(username="nobody")
        self.assertEqual(Organisation.objects.count(), 0)

    def test_with_no_users_it_creates_a_login_that_cannot_be_used_yet(self):
        """The command must never invent a guessable password."""
        output = seed()

        created = User.objects.get(username="seed-admin")
        self.assertFalse(created.has_usable_password())
        self.assertEqual(created.role, Role.ADMIN)
        self.assertIn("changepassword", output)
        self.assertEqual(Membership.objects.filter(user=created).count(), 2)

    def test_a_superuser_is_preferred_over_an_ordinary_user(self):
        User.objects.create_user(username="plain", email="p@example.com", password="pw")
        root = User.objects.create_superuser(
            username="root", email="r@example.com", password="pw"
        )

        seed()

        self.assertEqual(Membership.objects.filter(user=root).count(), 2)
        self.assertEqual(Membership.objects.filter(user__username="plain").count(), 0)
