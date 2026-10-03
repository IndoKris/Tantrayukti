"""Role-based DRF permission classes.

Used by later phases, for example so only a manager or admin may acknowledge an
anomaly while any member may read their own spaces.
"""

from rest_framework.permissions import BasePermission

from accounts.models import Role


class HasRoleAtLeast(BasePermission):
    """Base class: grant access when the user's role meets `required_role`."""

    required_role: str = Role.MEMBER

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return user.has_role_at_least(self.required_role)


class IsMember(HasRoleAtLeast):
    """Any authenticated user with a valid role."""

    required_role = Role.MEMBER


class IsManagerOrAbove(HasRoleAtLeast):
    """Managers and admins."""

    required_role = Role.MANAGER

    message = "This action requires the manager or admin role."


class IsAdmin(HasRoleAtLeast):
    """Admins (and Django superusers) only."""

    required_role = Role.ADMIN

    message = "This action requires the admin role."
