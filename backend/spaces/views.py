"""
CRUD API for the spaces hierarchy, scoped to the caller.

Two rules apply to every viewset here:

* **Visibility.** A queryset only ever contains objects belonging to an
  organisation the user is a member of. Superusers see everything. This is
  enforced in `get_queryset`, so a forgotten filter cannot leak another
  organisation's data through a detail route, a nested write or a filter.
* **Mutability.** Reads need any authenticated member; writes need the manager
  role or above, per `accounts.permissions`.
"""

from django.db.models import Prefetch
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsAdmin, IsManagerOrAbove
from spaces.models import Building, Floor, Membership, Organisation, Room
from spaces.serializers import (
    BuildingSerializer,
    FloorSerializer,
    MembershipSerializer,
    OrganisationSerializer,
    RoomSerializer,
    TreeOrganisationSerializer,
)


class ReadAnyMemberWriteManager(IsAuthenticated):
    """Safe methods: any authenticated user. Writes: manager or above."""

    message = IsManagerOrAbove.message

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        return IsManagerOrAbove().has_permission(request, view)


class ScopedViewSet(viewsets.ModelViewSet):
    """Base viewset that restricts every query to the caller's organisations."""

    permission_classes = [ReadAnyMemberWriteManager]

    #: Query path from this model to `Organisation`, e.g. "floor__building__organisation".
    organisation_path = "organisation"

    def visible_organisations(self):
        user = self.request.user
        if user.is_superuser:
            return Organisation.objects.all()
        return Organisation.objects.filter(memberships__user=user)

    def get_queryset(self):
        return self.queryset.filter(
            **{f"{self.organisation_path}__in": self.visible_organisations()}
        )


class OrganisationViewSet(viewsets.ModelViewSet):
    """
    /api/spaces/organisations/

    Creating an organisation makes the creator a member, otherwise it would be
    invisible to them the moment it was created.
    """

    queryset = Organisation.objects.all()
    serializer_class = OrganisationSerializer
    permission_classes = [ReadAnyMemberWriteManager]
    lookup_field = "pk"

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Organisation.objects.all()
        return Organisation.objects.filter(memberships__user=user).distinct()

    def perform_create(self, serializer):
        organisation = serializer.save()
        Membership.objects.get_or_create(
            user=self.request.user, organisation=organisation
        )

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        """The full hierarchy for every visible organisation, in one response."""
        organisations = (
            self.get_queryset()
            .prefetch_related(
                Prefetch(
                    "buildings",
                    queryset=Building.objects.prefetch_related(
                        Prefetch(
                            "floors",
                            queryset=Floor.objects.prefetch_related("rooms"),
                        )
                    ),
                )
            )
            .distinct()
        )
        return Response(TreeOrganisationSerializer(organisations, many=True).data)


class BuildingViewSet(ScopedViewSet):
    """/api/spaces/buildings/ - filter with ?organisation=<id>"""

    queryset = Building.objects.select_related("organisation")
    serializer_class = BuildingSerializer
    organisation_path = "organisation"

    def get_queryset(self):
        queryset = super().get_queryset()
        organisation = self.request.query_params.get("organisation")
        return queryset.filter(organisation_id=organisation) if organisation else queryset


class FloorViewSet(ScopedViewSet):
    """/api/spaces/floors/ - filter with ?building=<id>"""

    queryset = Floor.objects.select_related("building__organisation")
    serializer_class = FloorSerializer
    organisation_path = "building__organisation"

    def get_queryset(self):
        queryset = super().get_queryset()
        building = self.request.query_params.get("building")
        return queryset.filter(building_id=building) if building else queryset


class RoomViewSet(ScopedViewSet):
    """/api/spaces/rooms/ - filter with ?floor=<id> or ?building=<id>"""

    queryset = Room.objects.select_related("floor__building__organisation")
    serializer_class = RoomSerializer
    organisation_path = "floor__building__organisation"

    def get_queryset(self):
        queryset = super().get_queryset()
        floor = self.request.query_params.get("floor")
        if floor:
            queryset = queryset.filter(floor_id=floor)
        building = self.request.query_params.get("building")
        if building:
            queryset = queryset.filter(floor__building_id=building)
        return queryset


class MembershipViewSet(ScopedViewSet):
    """
    /api/spaces/memberships/

    Granting access is an admin action, so writes here are stricter than
    elsewhere in this app.
    """

    queryset = Membership.objects.select_related("user", "organisation")
    serializer_class = MembershipSerializer
    organisation_path = "organisation"

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [IsAuthenticated()]
        return [IsAdmin()]
