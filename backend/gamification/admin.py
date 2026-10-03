"""Admin registration for gamification."""

from django.contrib import admin

from gamification.models import (
    Badge,
    Challenge,
    ChallengeParticipation,
    Profile,
    SavingClaim,
    UserBadge,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "level", "verified_xp", "unverified_xp", "verified_kwh_saved", "eco_coins", "streak_days"]
    search_fields = ["user__username"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "threshold_verified_kwh", "threshold_streak_days", "requires_verified"]


@admin.register(UserBadge)
class UserBadgeAdmin(admin.ModelAdmin):
    list_display = ["user", "badge", "awarded_at"]
    list_filter = ["badge"]


class ParticipationInline(admin.TabularInline):
    model = ChallengeParticipation
    extra = 0
    readonly_fields = ["verified_kwh_saved", "completed_at", "joined_at"]


@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ["name", "target_kwh", "starts_on", "ends_on", "is_active"]
    inlines = [ParticipationInline]


@admin.register(SavingClaim)
class SavingClaimAdmin(admin.ModelAdmin):
    list_display = ["user", "device", "claimed_kwh_saved", "measured_kwh_saved", "status", "created_at"]
    list_filter = ["status"]
    readonly_fields = [
        "baseline_kwh",
        "claim_period_kwh",
        "measured_kwh_saved",
        "verification_note",
        "verified_at",
        "created_at",
    ]
