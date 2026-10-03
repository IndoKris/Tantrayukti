"""Custom user model carrying the EcoTrack role."""

from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """
    Role hierarchy, ordered from most to least privileged.

    ADMIN   - manages the organisation, its spaces, devices and members.
    MANAGER - reads everything in their organisation and acts on anomalies.
    MEMBER  - reads the spaces they belong to and logs their own activity.
    """

    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager"
    MEMBER = "member", "Member"


#: Privilege ranking used by the role-based permission classes. Higher wins.
ROLE_RANK: dict[str, int] = {
    Role.MEMBER: 1,
    Role.MANAGER: 2,
    Role.ADMIN: 3,
}


class User(AbstractUser):
    """
    EcoTrack user.

    Extends Django's `AbstractUser`, so username/password login and the admin
    continue to work unchanged. Two additions:

    * `email` is required and unique - it is how people are identified in reports.
    * `role` drives API authorisation and is embedded in the JWT as a claim.
    """

    email = models.EmailField("email address", unique=True)
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.MEMBER,
        help_text="Determines what this user may read and change.",
    )

    REQUIRED_FIELDS = ["email"]

    class Meta(AbstractUser.Meta):
        swappable = "AUTH_USER_MODEL"

    def __str__(self) -> str:
        return f"{self.get_username()} ({self.get_role_display()})"

    # --- Role helpers ---------------------------------------------------------

    @property
    def role_rank(self) -> int:
        """Numeric privilege level, for comparisons. Unknown roles rank lowest."""
        return ROLE_RANK.get(self.role, 0)

    def has_role_at_least(self, role: str) -> bool:
        """
        True when this user's role is `role` or more privileged.

        A Django superuser always passes, so `createsuperuser` yields a working
        admin without having to set the role separately.
        """
        if self.is_superuser:
            return True
        return self.role_rank >= ROLE_RANK.get(role, 0)

    @property
    def is_admin(self) -> bool:
        return self.has_role_at_least(Role.ADMIN)

    @property
    def is_manager_or_above(self) -> bool:
        return self.has_role_at_least(Role.MANAGER)

    def save(self, *args, **kwargs):
        # Keep the role consistent with Django's own staff/superuser flags so the
        # admin and the API cannot disagree about who is an admin.
        if self.is_superuser and self.role != Role.ADMIN:
            self.role = Role.ADMIN
        super().save(*args, **kwargs)
