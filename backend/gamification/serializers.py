"""Serializers for gamification."""

from rest_framework import serializers

from gamification.models import (
    Badge,
    Challenge,
    ChallengeParticipation,
    Profile,
    SavingClaim,
    UserBadge,
)
from spaces.models import Organisation
from telemetry.models import Device


class ProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    level = serializers.IntegerField(read_only=True)
    xp_into_level = serializers.IntegerField(read_only=True)
    xp_to_next_level = serializers.IntegerField(read_only=True)
    total_xp_including_unverified = serializers.IntegerField(read_only=True)

    class Meta:
        model = Profile
        fields = [
            "username",
            "level",
            "verified_xp",
            "verified_kwh_saved",
            "eco_coins",
            "unverified_xp",
            "total_xp_including_unverified",
            "xp_into_level",
            "xp_to_next_level",
            "streak_days",
            "longest_streak_days",
            "last_active_on",
        ]
        read_only_fields = fields


class BadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Badge
        fields = [
            "id",
            "code",
            "name",
            "description",
            "emoji",
            "threshold_verified_kwh",
            "threshold_streak_days",
            "threshold_verified_claims",
            "requires_verified",
        ]
        read_only_fields = fields


class UserBadgeSerializer(serializers.ModelSerializer):
    badge = BadgeSerializer(read_only=True)

    class Meta:
        model = UserBadge
        fields = ["id", "badge", "awarded_at"]
        read_only_fields = fields


class ChallengeSerializer(serializers.ModelSerializer):
    is_open = serializers.BooleanField(read_only=True)
    participant_count = serializers.IntegerField(
        source="participations.count", read_only=True
    )

    class Meta:
        model = Challenge
        fields = [
            "id",
            "name",
            "description",
            "target_kwh",
            "reward_xp",
            "reward_coins",
            "starts_on",
            "ends_on",
            "is_active",
            "is_open",
            "participant_count",
        ]
        read_only_fields = fields


class ChallengeParticipationSerializer(serializers.ModelSerializer):
    challenge = ChallengeSerializer(read_only=True)
    progress_percent = serializers.DecimalField(
        max_digits=8, decimal_places=2, read_only=True
    )
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = ChallengeParticipation
        fields = [
            "id",
            "challenge",
            "verified_kwh_saved",
            "progress_percent",
            "is_complete",
            "completed_at",
            "joined_at",
        ]
        read_only_fields = fields


class SavingClaimSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    claim_accuracy_percent = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = SavingClaim
        fields = [
            "id",
            "device",
            "device_name",
            "action_taken",
            "baseline_start",
            "baseline_end",
            "claim_start",
            "claim_end",
            "claimed_kwh_saved",
            "baseline_kwh",
            "claim_period_kwh",
            "measured_kwh_saved",
            "claim_accuracy_percent",
            "status",
            "status_display",
            "is_verified",
            "verification_note",
            "verified_at",
            "created_at",
        ]
        read_only_fields = [
            "baseline_kwh",
            "claim_period_kwh",
            "measured_kwh_saved",
            "status",
            "verification_note",
            "verified_at",
            "created_at",
        ]

    def validate_device(self, value: Device) -> Device:
        """
        A claim may only name a device the caller can actually see.

        Checked here rather than trusted from the request body, so a user cannot
        claim savings against someone else's meter.
        """
        request = self.context.get("request")
        if request is None:
            return value

        user = request.user
        organisations = (
            Organisation.objects.all()
            if user.is_superuser
            else Organisation.objects.filter(memberships__user=user)
        )
        if not Device.objects.filter(
            pk=value.pk, room__floor__building__organisation__in=organisations
        ).exists():
            raise serializers.ValidationError("No visible device with that id.")
        return value

    def validate(self, attrs):
        baseline_start = attrs.get("baseline_start")
        baseline_end = attrs.get("baseline_end")
        claim_start = attrs.get("claim_start")
        claim_end = attrs.get("claim_end")

        if baseline_start and baseline_end and baseline_start >= baseline_end:
            raise serializers.ValidationError(
                {"baseline_end": "The baseline window must end after it starts."}
            )
        if claim_start and claim_end and claim_start >= claim_end:
            raise serializers.ValidationError(
                {"claim_end": "The claim window must end after it starts."}
            )
        if baseline_end and claim_start and claim_start < baseline_end:
            raise serializers.ValidationError(
                {
                    "claim_start": (
                        "The claim window must start after the baseline window ends; "
                        "overlapping windows would compare a period against itself."
                    )
                }
            )
        return attrs
