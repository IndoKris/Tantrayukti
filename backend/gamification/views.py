"""
Gamification API: profile, badges, challenges, leaderboard and saving claims.

The leaderboard is public to signed-in users; everything else is scoped to the
caller. Claims may only be made against a device in an organisation the caller
belongs to, which is checked in the serializer rather than trusted from the body.
"""

from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gamification import verification
from gamification.models import (
    Badge,
    Challenge,
    ChallengeParticipation,
    Profile,
    SavingClaim,
    UserBadge,
)
from gamification.serializers import (
    BadgeSerializer,
    ChallengeParticipationSerializer,
    ChallengeSerializer,
    ProfileSerializer,
    SavingClaimSerializer,
    UserBadgeSerializer,
)


class MyProfileView(APIView):
    """
    GET /api/game/profile/

    The caller's progress, badges and open challenges. Verified and unverified
    tallies are reported separately, with a note saying which one ranks.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = Profile.for_user(request.user)

        return Response(
            {
                "profile": ProfileSerializer(profile).data,
                "badges": UserBadgeSerializer(
                    UserBadge.objects.filter(user=request.user).select_related("badge"),
                    many=True,
                ).data,
                "challenges": ChallengeParticipationSerializer(
                    ChallengeParticipation.objects.filter(
                        user=request.user
                    ).select_related("challenge"),
                    many=True,
                ).data,
                "ranking_note": (
                    "The leaderboard ranks on verified XP only. Self-reported "
                    "activity contributes unverified XP, which is shown here but "
                    "never affects your rank - a logged journey is not evidence "
                    "the way a metered kWh is."
                ),
            }
        )


class BadgeViewSet(viewsets.ReadOnlyModelViewSet):
    """/api/game/badges/ - every badge definition and its criteria."""

    queryset = Badge.objects.all()
    serializer_class = BadgeSerializer
    permission_classes = [IsAuthenticated]


class ChallengeViewSet(viewsets.ReadOnlyModelViewSet):
    """/api/game/challenges/ - challenge definitions, with a join action."""

    queryset = Challenge.objects.filter(is_active=True)
    serializer_class = ChallengeSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"])
    def join(self, request, pk=None):
        challenge = self.get_object()
        if not challenge.is_open:
            return Response(
                {
                    "detail": "That challenge is not open.",
                    "starts_on": challenge.starts_on,
                    "ends_on": challenge.ends_on,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        participation, created = ChallengeParticipation.objects.get_or_create(
            challenge=challenge, user=request.user
        )
        return Response(
            ChallengeParticipationSerializer(participation).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class LeaderboardView(APIView):
    """
    GET /api/game/leaderboard/

    Ranked by verified savings. Each row carries the excluded unverified XP, so
    the exclusion is visible rather than mysterious.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 20)), 100)
        rows = verification.leaderboard(limit=limit)

        mine = Profile.for_user(request.user)
        my_rank = next(
            (row["rank"] for row in rows if row["username"] == request.user.get_username()),
            None,
        )

        return Response(
            {
                "results": rows,
                "me": {
                    "username": request.user.get_username(),
                    "rank": my_rank,
                    "verified_xp": mine.verified_xp,
                    "verified_kwh_saved": mine.verified_kwh_saved,
                    "unverified_xp_excluded": mine.unverified_xp,
                    "in_top": my_rank is not None,
                },
                "basis": (
                    "Ranked on verified XP, earned only from reductions a meter "
                    "confirmed. Self-reported activity is excluded entirely."
                ),
            }
        )


class SavingClaimViewSet(viewsets.ModelViewSet):
    """
    /api/game/claims/

    Submit a claimed reduction and have it checked against telemetry. Claims are
    private to the person who made them.

    Creating a claim leaves it `pending`; `POST .../verify/` runs the check.
    `POST .../preview/` runs the same check without recording or awarding, so a
    user can see what would happen first.
    """

    serializer_class = SavingClaimSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SavingClaim.objects.filter(user=self.request.user).select_related(
            "device__room__floor__building__organisation"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        """Run the telemetry check and credit XP from the measured saving."""
        claim = self.get_object()
        if claim.status == SavingClaim.Status.VERIFIED:
            return Response(
                {
                    "detail": "This claim has already been verified.",
                    "claim": SavingClaimSerializer(claim).data,
                },
                status=status.HTTP_409_CONFLICT,
            )

        verification.verify(claim, award=True)
        profile = Profile.for_user(request.user)

        return Response(
            {
                "claim": SavingClaimSerializer(claim).data,
                "profile": ProfileSerializer(profile).data,
            }
        )

    @action(detail=True, methods=["post"])
    def preview(self, request, pk=None):
        """Same check, nothing recorded and nothing awarded."""
        claim = self.get_object()
        verification.verify(claim, award=False)
        return Response(
            {
                "claim": SavingClaimSerializer(claim).data,
                "note": "Dry run: no XP, coins or badges were awarded.",
            }
        )
