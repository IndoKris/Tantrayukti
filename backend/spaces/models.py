"""
Spaces hierarchy: Organisation > Building > Floor > Room.

Area and occupancy exist at every level below the organisation because Phase 16
compares spaces normalised per m2 and per person. They are optional on the
container levels: when a building does not state its own area, the area is the
sum of its floors, and the area of a floor is the sum of its rooms.
`total_area_sqm` and `total_occupancy` expose that resolution so callers never
have to decide.

Units are explicit in the field names (`area_sqm`) because the plan forbids
ambiguous units anywhere in the project.
"""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify


class TimestampedModel(models.Model):
    """Creation and update stamps, shared by everything in this app."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SpaceNode(TimestampedModel):
    """
    Fields shared by Building, Floor and Room.

    `area_sqm` and `occupancy` are nullable so a space can inherit them from its
    children rather than forcing a guessed number into the database.
    """

    name = models.CharField(max_length=120)
    area_sqm = models.DecimalField(
        "area (m2)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Floor area in square metres. Leave empty to derive it from children.",
    )
    occupancy = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Typical number of people. Leave empty to derive it from children.",
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.name


def _sum_area(children):
    """
    Sum `total_area_sqm` over children, returning None when none of them state one.

    None is deliberate: it keeps "area unknown" distinct from "area is zero", so
    Phase 16 can skip a space rather than divide by zero.
    """
    known = [
        child.total_area_sqm for child in children if child.total_area_sqm is not None
    ]
    if not known:
        return None
    return sum(known)


class Organisation(TimestampedModel):
    """
    Top of the hierarchy and the unit of access control.

    A user sees exactly the organisations they are a member of; everything below
    is reached through those.
    """

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="Membership",
        related_name="organisations",
        blank=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = slugify(self.name) or "organisation"
        slug = base
        suffix = 2
        while Organisation.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    @property
    def rooms(self) -> models.QuerySet["Room"]:
        """Every room in the organisation, however deeply nested."""
        return Room.objects.filter(floor__building__organisation=self)

    @property
    def total_area_sqm(self):
        return _sum_area(self.buildings.all())

    @property
    def total_occupancy(self) -> int:
        return sum(building.total_occupancy for building in self.buildings.all())


class Membership(TimestampedModel):
    """Links a user to an organisation. Organisation-level roles are in BACKLOG."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="memberships"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organisation"], name="unique_membership_per_org"
            )
        ]
        ordering = ["organisation__name", "user__username"]

    def __str__(self) -> str:
        return f"{self.user} in {self.organisation}"


class Building(SpaceNode):
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="buildings"
    )
    address = models.CharField(max_length=255, blank=True)
    # Used by the Phase 22 community map, which rounds coordinates to city level.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["organisation__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "name"], name="unique_building_name_per_org"
            )
        ]

    @property
    def total_area_sqm(self):
        return self.area_sqm if self.area_sqm is not None else _sum_area(self.floors.all())

    @property
    def total_occupancy(self) -> int:
        if self.occupancy is not None:
            return self.occupancy
        return sum(floor.total_occupancy for floor in self.floors.all())


class Floor(SpaceNode):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="floors")
    level = models.IntegerField(
        default=0, help_text="0 is ground level; negatives are basements."
    )

    class Meta:
        ordering = ["building__name", "level"]
        constraints = [
            models.UniqueConstraint(
                fields=["building", "level"], name="unique_floor_level_per_building"
            )
        ]

    def __str__(self) -> str:
        return f"{self.building.name} / {self.name}"

    @property
    def organisation(self) -> Organisation:
        return self.building.organisation

    @property
    def total_area_sqm(self):
        return self.area_sqm if self.area_sqm is not None else _sum_area(self.rooms.all())

    @property
    def total_occupancy(self) -> int:
        if self.occupancy is not None:
            return self.occupancy
        return sum(room.occupancy or 0 for room in self.rooms.all())


class Room(SpaceNode):
    """
    A leaf space. Devices attach here in Phase 6.

    Area and occupancy are expected to be set on rooms, since the levels above
    derive theirs from them.
    """

    class Kind(models.TextChoices):
        OFFICE = "office", "Office"
        MEETING = "meeting", "Meeting room"
        KITCHEN = "kitchen", "Kitchen"
        SERVER = "server", "Server room"
        BEDROOM = "bedroom", "Bedroom"
        LIVING = "living", "Living room"
        OTHER = "other", "Other"

    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name="rooms")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.OTHER)

    class Meta:
        ordering = ["floor__building__name", "floor__level", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["floor", "name"], name="unique_room_name_per_floor"
            )
        ]

    def __str__(self) -> str:
        return f"{self.floor.building.name} / {self.floor.name} / {self.name}"

    @property
    def organisation(self) -> Organisation:
        return self.floor.building.organisation

    @property
    def total_area_sqm(self):
        return self.area_sqm

    @property
    def total_occupancy(self) -> int:
        return self.occupancy or 0
