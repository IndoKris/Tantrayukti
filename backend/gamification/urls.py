"""Gamification routes, mounted under /api/game/ by config.urls."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from gamification.views import (
    BadgeViewSet,
    ChallengeViewSet,
    LeaderboardView,
    MyProfileView,
    SavingClaimViewSet,
)

app_name = "gamification"

router = DefaultRouter()
router.register("badges", BadgeViewSet, basename="badge")
router.register("challenges", ChallengeViewSet, basename="challenge")
router.register("claims", SavingClaimViewSet, basename="claim")

urlpatterns = [
    path("profile/", MyProfileView.as_view(), name="profile"),
    path("leaderboard/", LeaderboardView.as_view(), name="leaderboard"),
    path("", include(router.urls)),
]
