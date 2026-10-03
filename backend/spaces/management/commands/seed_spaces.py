"""
Seed a sample office and a sample home.

Idempotent: re-running updates the sample spaces in place rather than creating
duplicates, so it is safe in a demo loop.

The command never invents a password. It attaches the seeded organisations to an
existing user when it can find one; otherwise it creates `seed-admin` with an
*unusable* password and tells you how to set one. That keeps the data scoped and
visible through the API without leaving a guessable login behind.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role
from spaces.models import Building, Floor, Membership, Organisation, Room

User = get_user_model()

# Area in m2 and typical occupancy. Marked sample data; not measurements.
OFFICE = {
    "organisation": "Tantrayukti Office",
    "building": {
        "name": "YCCE Block A",
        "address": "Hingna Road, Nagpur, Maharashtra",
        # Nagpur, rounded to the city level the Phase 22 map uses.
        "latitude": Decimal("21.146"),
        "longitude": Decimal("79.089"),
    },
    "floors": [
        {
            "name": "Ground floor",
            "level": 0,
            "rooms": [
                ("Reception", Room.Kind.OFFICE, "28.00", 3),
                ("Server room", Room.Kind.SERVER, "18.50", 0),
                ("Canteen", Room.Kind.KITCHEN, "64.00", 24),
            ],
        },
        {
            "name": "First floor",
            "level": 1,
            "rooms": [
                ("Open workspace", Room.Kind.OFFICE, "180.00", 42),
                ("Meeting room 1", Room.Kind.MEETING, "32.00", 10),
                ("Meeting room 2", Room.Kind.MEETING, "24.00", 6),
            ],
        },
        {
            "name": "Second floor",
            "level": 2,
            "rooms": [
                ("Lab", Room.Kind.OFFICE, "120.00", 20),
                ("Store", Room.Kind.OTHER, "16.00", 0),
            ],
        },
    ],
}

HOME = {
    "organisation": "Sample Home",
    "building": {
        "name": "Flat 302, Shivaji Nagar",
        "address": "Shivaji Nagar, Nagpur, Maharashtra",
        "latitude": Decimal("21.131"),
        "longitude": Decimal("79.072"),
    },
    "floors": [
        {
            "name": "Main floor",
            "level": 0,
            "rooms": [
                ("Living room", Room.Kind.LIVING, "26.00", 4),
                ("Kitchen", Room.Kind.KITCHEN, "9.50", 2),
                ("Bedroom 1", Room.Kind.BEDROOM, "14.00", 2),
                ("Bedroom 2", Room.Kind.BEDROOM, "11.00", 1),
            ],
        }
    ],
}


class Command(BaseCommand):
    help = "Create or refresh a sample office and a sample home in the spaces hierarchy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            dest="username",
            help="Username to grant membership to. Defaults to an existing superuser.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        user = self._resolve_user(options.get("username"))

        created_rooms = 0
        for spec in (OFFICE, HOME):
            organisation, rooms = self._seed(spec)
            created_rooms += rooms
            Membership.objects.get_or_create(user=user, organisation=organisation)
            self.stdout.write(
                f"  {organisation.name}: "
                f"{organisation.buildings.count()} building(s), "
                f"{Floor.objects.filter(building__organisation=organisation).count()} floor(s), "
                f"{organisation.rooms.count()} room(s), "
                f"area {organisation.total_area_sqm} m2, "
                f"occupancy {organisation.total_occupancy}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded 2 organisations ({created_rooms} rooms) for user '{user.get_username()}'."
            )
        )

    # --- helpers --------------------------------------------------------------

    def _resolve_user(self, username: str | None):
        """Find the user to attach the seed data to, creating one only as a last resort."""
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist as exc:
                raise SystemExit(f"No user named '{username}'.") from exc

        user = (
            User.objects.filter(is_superuser=True).order_by("id").first()
            or User.objects.order_by("id").first()
        )
        if user:
            return user

        user = User.objects.create(
            username="seed-admin",
            email="seed-admin@example.invalid",
            role=Role.ADMIN,
            is_staff=True,
        )
        user.set_unusable_password()
        user.save()
        self.stdout.write(
            self.style.WARNING(
                "No users existed, so 'seed-admin' was created with no usable password.\n"
                "  Set one with: python manage.py changepassword seed-admin"
            )
        )
        return user

    def _seed(self, spec: dict) -> tuple[Organisation, int]:
        organisation, _ = Organisation.objects.get_or_create(name=spec["organisation"])

        building_spec = dict(spec["building"])
        building, _ = Building.objects.update_or_create(
            organisation=organisation,
            name=building_spec.pop("name"),
            defaults=building_spec,
        )

        room_count = 0
        for floor_spec in spec["floors"]:
            floor, _ = Floor.objects.update_or_create(
                building=building,
                level=floor_spec["level"],
                defaults={"name": floor_spec["name"]},
            )
            for name, kind, area, occupancy in floor_spec["rooms"]:
                Room.objects.update_or_create(
                    floor=floor,
                    name=name,
                    defaults={
                        "kind": kind,
                        "area_sqm": Decimal(area),
                        "occupancy": occupancy,
                    },
                )
                room_count += 1

        return organisation, room_count
