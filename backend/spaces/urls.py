"""Spaces routes, mounted under /api/spaces/ by config.urls."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from spaces.views import (
    BuildingViewSet,
    FloorViewSet,
    MembershipViewSet,
    OrganisationViewSet,
    RoomViewSet,
)

app_name = "spaces"

router = DefaultRouter()
router.register("organisations", OrganisationViewSet, basename="organisation")
router.register("buildings", BuildingViewSet, basename="building")
router.register("floors", FloorViewSet, basename="floor")
router.register("rooms", RoomViewSet, basename="room")
router.register("memberships", MembershipViewSet, basename="membership")

urlpatterns = [path("", include(router.urls))]
