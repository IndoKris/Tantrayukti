"""
XP, levels, streaks, EcoCoins, badges, challenges and proof of saving.

**The distinction the whole app is built around: verified versus unverified.**

A reduction claimed by a person is worth nothing until telemetry agrees with it.
So every profile keeps two parallel tallies:

* `verified_xp` / `verified_kwh_saved` - earned only from a `SavingClaim` that a
  meter confirmed. **This is what the leaderboard ranks on.**
* `unverified_xp` - earned from self-reported activity logging and other
  participation. Visible on your own profile, and deliberately **excluded from
  ranking**, because a logged bus journey is not evidence the way a metered kWh
  is.

The plan requires manual entries to be tagged unverified and kept out of the
ranking; keeping them in separate columns makes that structural rather than a
filter someone can forget to apply.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

#: XP per verified kWh saved. Flat, so the ranking is a direct function of
#: measured energy rather than of an opaque scoring curve.
XP_PER_VERIFIED_KWH = 10

#: XP for logging a self-reported activity. Counts towards `unverified_xp` only.
XP_PER_ACTIVITY_ENTRY = 2

#: EcoCoins per verified kWh saved.
COINS_PER_VERIFIED_KWH = 1

#: XP needed for each level. Level n requires n * this much, cumulatively.
XP_PER_LEVEL = 250

#: A streak survives a gap of at most this many days.
STREAK_GRACE_DAYS = 1


class Profile(models.Model):
    """A user's progress. Created on demand by `Profile.for_user`."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="game_profile"
    )

    # --- Verified: the only tallies the leaderboard uses ---
    verified_xp = models.PositiveIntegerField(
        default=0, help_text="Earned only from telemetry-confirmed savings."
    )
    verified_kwh_saved = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0")
    )
    eco_coins = models.PositiveIntegerField(default=0)

    # --- Unverified: shown to the user, excluded from ranking ---
    unverified_xp = models.PositiveIntegerField(
        default=0,
        help_text=(
            "From self-reported activity. Never counted in the leaderboard, "
            "because it is not evidence."
        ),
    )

    streak_days = models.PositiveIntegerField(default=0)
    longest_streak_days = models.PositiveIntegerField(default=0)
    last_active_on = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-verified_xp"]

    def __str__(self) -> str:
        return f"{self.user}: level {self.level}, {self.verified_xp} verified XP"

    @classmethod
    def for_user(cls, user) -> Profile:
        profile, _ = cls.objects.get_or_create(user=user)
        return profile

    @property
    def level(self) -> int:
        """Level from verified XP only, so levels cannot be self-reported up."""
        return 1 + self.verified_xp // XP_PER_LEVEL

    @property
    def xp_into_level(self) -> int:
        return self.verified_xp % XP_PER_LEVEL

    @property
    def xp_to_next_level(self) -> int:
        return XP_PER_LEVEL - self.xp_into_level

    @property
    def total_xp_including_unverified(self) -> int:
        """Shown on the profile. Never used for ranking."""
        return self.verified_xp + self.unverified_xp

    def touch_streak(self, on_date=None) -> None:
        """
        Record activity for a day and update the streak.

        A gap of one day is forgiven (`STREAK_GRACE_DAYS`); a longer gap resets
        the streak to 1 rather than to 0, because the day being recorded is
        itself active.
        """
        on_date = on_date or timezone.localdate()

        if self.last_active_on is None:
            self.streak_days = 1
        elif on_date == self.last_active_on:
            return  # already counted today
        else:
            gap = (on_date - self.last_active_on).days
            if gap <= 0:
                return  # backdated activity does not extend a streak
            self.streak_days = (
                self.streak_days + 1 if gap <= STREAK_GRACE_DAYS + 1 else 1
            )

        self.last_active_on = on_date
        self.longest_streak_days = max(self.longest_streak_days, self.streak_days)
        self.save(
            update_fields=["streak_days", "longest_streak_days", "last_active_on", "updated_at"]
        )

    def award_verified(self, kwh_saved: Decimal) -> dict:
        """Credit XP and coins for a telemetry-confirmed saving."""
        kwh_saved = Decimal(kwh_saved)
        if kwh_saved <= 0:
            return {"xp": 0, "coins": 0, "kwh": Decimal("0")}

        xp = int(kwh_saved * XP_PER_VERIFIED_KWH)
        coins = int(kwh_saved * COINS_PER_VERIFIED_KWH)

        self.verified_xp += xp
        self.eco_coins += coins
        self.verified_kwh_saved += kwh_saved
        self.save(
            update_fields=["verified_xp", "eco_coins", "verified_kwh_saved", "updated_at"]
        )
        return {"xp": xp, "coins": coins, "kwh": kwh_saved}

    def award_unverified(self, xp: int = XP_PER_ACTIVITY_ENTRY) -> int:
        """Credit participation XP that must never affect the ranking."""
        self.unverified_xp += xp
        self.save(update_fields=["unverified_xp", "updated_at"])
        return xp


class Badge(models.Model):
    """
    An achievement definition.

    `requires_verified` marks badges that only telemetry-confirmed savings can
    unlock, so a badge cannot be earned by logging activity alone.
    """

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200)
    emoji = models.CharField(max_length=8, blank=True)

    threshold_verified_kwh = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    threshold_streak_days = models.PositiveIntegerField(null=True, blank=True)
    threshold_verified_claims = models.PositiveIntegerField(null=True, blank=True)
    requires_verified = models.BooleanField(default=True)

    class Meta:
        ordering = ["threshold_verified_kwh", "name"]

    def __str__(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    def is_earned_by(self, profile: Profile) -> bool:
        """
        Whether a profile currently meets this badge's criteria.

        Thresholds are ANDed: a badge with both a kWh and a streak threshold
        needs both.
        """
        if self.threshold_verified_kwh is not None:
            if profile.verified_kwh_saved < self.threshold_verified_kwh:
                return False
        if self.threshold_streak_days is not None:
            if profile.longest_streak_days < self.threshold_streak_days:
                return False
        if self.threshold_verified_claims is not None:
            confirmed = SavingClaim.objects.filter(
                user=profile.user, status=SavingClaim.Status.VERIFIED
            ).count()
            if confirmed < self.threshold_verified_claims:
                return False
        # A badge with no thresholds is never auto-awarded.
        return any(
            value is not None
            for value in (
                self.threshold_verified_kwh,
                self.threshold_streak_days,
                self.threshold_verified_claims,
            )
        )


class UserBadge(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="badges"
    )
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name="awards")
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-awarded_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "badge"], name="unique_badge_per_user")
        ]

    def __str__(self) -> str:
        return f"{self.user} earned {self.badge}"


class Challenge(models.Model):
    """
    A time-boxed savings target.

    Progress counts **verified** savings inside the window only, so a challenge
    cannot be completed by logging activity.
    """

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    target_kwh = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Verified kWh a participant must save to complete it.",
    )
    reward_xp = models.PositiveIntegerField(default=100)
    reward_coins = models.PositiveIntegerField(default=50)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-starts_on"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_open(self) -> bool:
        today = timezone.localdate()
        return self.is_active and self.starts_on <= today <= self.ends_on


class ChallengeParticipation(models.Model):
    challenge = models.ForeignKey(
        Challenge, on_delete=models.CASCADE, related_name="participations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="challenges"
    )
    verified_kwh_saved = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0")
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-joined_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["challenge", "user"], name="unique_participation_per_challenge"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} in {self.challenge}"

    @property
    def progress_percent(self) -> Decimal | None:
        if self.challenge.target_kwh <= 0:
            return None
        return (
            self.verified_kwh_saved / self.challenge.target_kwh * 100
        ).quantize(Decimal("0.01"))

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None


class SavingClaim(models.Model):
    """
    A claimed reduction, checked against telemetry.

    The user names a device and two windows - a baseline and an "after" period of
    the same length - plus how much they believe they saved. `verify()` reads the
    actual metered energy for both windows and compares.

    **A claim is never trusted on its own.** Status starts `pending` and only
    `verify()` can move it to `verified`; XP is credited from the **measured**
    saving, not from the claimed one, so over-claiming earns nothing extra.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting verification"
        VERIFIED = "verified", "Confirmed by telemetry"
        REJECTED = "rejected", "Not supported by telemetry"
        UNVERIFIABLE = "unverifiable", "Not enough telemetry to check"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saving_claims"
    )
    device = models.ForeignKey(
        "telemetry.Device", on_delete=models.CASCADE, related_name="saving_claims"
    )
    action_taken = models.CharField(
        max_length=200, help_text="What was changed, e.g. 'raised AC setpoint to 26 C'."
    )

    baseline_start = models.DateTimeField()
    baseline_end = models.DateTimeField()
    claim_start = models.DateTimeField()
    claim_end = models.DateTimeField()

    claimed_kwh_saved = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="What the user believes was saved.",
    )

    # --- Filled in by verify() ---
    baseline_kwh = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True, editable=False
    )
    claim_period_kwh = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True, editable=False
    )
    measured_kwh_saved = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        editable=False,
        help_text="baseline_kwh - claim_period_kwh, after length normalisation.",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    verification_note = models.TextField(blank=True, editable=False)
    verified_at = models.DateTimeField(null=True, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} claims {self.claimed_kwh_saved} kWh on {self.device}"

    @property
    def is_verified(self) -> bool:
        return self.status == self.Status.VERIFIED

    @property
    def claim_accuracy_percent(self) -> Decimal | None:
        """How close the claim was to the measurement, for display."""
        if self.measured_kwh_saved is None or self.claimed_kwh_saved <= 0:
            return None
        return (self.measured_kwh_saved / self.claimed_kwh_saved * 100).quantize(
            Decimal("0.01")
        )
