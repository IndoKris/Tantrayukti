"""
Proof of saving: check a claimed reduction against telemetry.

The procedure, and why each step is there:

1. Read metered energy for the baseline window and the claim window from the
   Phase 8 rollups, which means the `metering=auto` guard applies and a room
   with both a mains and appliance meters is not counted twice.
2. **Normalise for window length.** Comparing a 14-day baseline against a 7-day
   claim period would show a 50% "saving" from arithmetic alone, so the baseline
   is scaled to the claim window's duration before subtracting.
3. Require enough readings in both windows. Too little telemetry makes the claim
   `unverifiable` rather than `rejected` - "we cannot tell" and "it did not
   happen" are different answers and the user deserves the right one.
4. Credit the **measured** saving, never the claimed one. Over-claiming earns
   nothing extra; under-claiming is not punished.

A claim within tolerance of the measurement is `verified`. A measurement showing
no saving is `rejected`, with the numbers attached so the user can see why.
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from gamification.models import Profile, SavingClaim
from telemetry import rollups
from telemetry.models import Device

#: Minimum readings in each window before a claim can be judged.
MIN_READINGS_PER_WINDOW = 12

#: A claim is verified when the measurement is at least this fraction of it.
#: Below this the measurement does not support the claim.
CLAIM_TOLERANCE = Decimal("0.5")

#: Measured savings below this are treated as noise, not a saving.
MIN_MEANINGFUL_KWH = Decimal("0.01")


def energy_for(device: Device, start, end, metering: str = "auto") -> dict:
    """Metered energy for one device over a window, via the Phase 8 rollups."""
    devices, applied = rollups.select_devices(
        Device.objects.filter(pk=device.pk), metering
    )
    totals = rollups.totals(rollups.readings_for(devices, start, end))
    return {
        "energy_kwh": Decimal(totals["energy_kwh"]),
        "sample_count": int(totals["sample_count"]),
        "metering_applied": applied,
    }


def verify(claim: SavingClaim, award: bool = True) -> SavingClaim:
    """
    Check a claim against telemetry and record the outcome.

    `award` is False for a dry run, used by the preview endpoint so a user can
    see what a claim would resolve to without it counting.
    """
    baseline_seconds = (claim.baseline_end - claim.baseline_start).total_seconds()
    claim_seconds = (claim.claim_end - claim.claim_start).total_seconds()

    if baseline_seconds <= 0 or claim_seconds <= 0:
        return _settle(
            claim,
            status=SavingClaim.Status.UNVERIFIABLE,
            note="Both windows must have a positive duration.",
            award=False,
        )

    baseline = energy_for(claim.device, claim.baseline_start, claim.baseline_end)
    after = energy_for(claim.device, claim.claim_start, claim.claim_end)

    claim.baseline_kwh = baseline["energy_kwh"].quantize(Decimal("0.0001"))
    claim.claim_period_kwh = after["energy_kwh"].quantize(Decimal("0.0001"))

    if (
        baseline["sample_count"] < MIN_READINGS_PER_WINDOW
        or after["sample_count"] < MIN_READINGS_PER_WINDOW
    ):
        return _settle(
            claim,
            status=SavingClaim.Status.UNVERIFIABLE,
            note=(
                f"Not enough telemetry to judge this claim: "
                f"{baseline['sample_count']} reading(s) in the baseline window and "
                f"{after['sample_count']} in the claim window, against a minimum of "
                f"{MIN_READINGS_PER_WINDOW} each. This is not a rejection - the meter "
                f"simply did not record enough to tell."
            ),
            award=False,
        )

    # Scale the baseline to the claim window's length before subtracting.
    scale = Decimal(str(claim_seconds)) / Decimal(str(baseline_seconds))
    scaled_baseline = (baseline["energy_kwh"] * scale).quantize(Decimal("0.0001"))
    measured = (scaled_baseline - after["energy_kwh"]).quantize(Decimal("0.0001"))
    claim.measured_kwh_saved = measured

    length_note = (
        f"Baseline {baseline['energy_kwh']} kWh over "
        f"{baseline_seconds / 3600:.1f} h scaled by {scale:.4f} to "
        f"{scaled_baseline} kWh for the {claim_seconds / 3600:.1f} h claim window, "
        f"which used {after['energy_kwh']} kWh. "
        f"Measured saving {measured} kWh."
    )

    if measured < MIN_MEANINGFUL_KWH:
        return _settle(
            claim,
            status=SavingClaim.Status.REJECTED,
            note=(
                f"{length_note} The meter shows no reduction, so the claimed "
                f"{claim.claimed_kwh_saved} kWh is not supported."
            ),
            award=False,
        )

    if claim.claimed_kwh_saved > 0 and measured < claim.claimed_kwh_saved * CLAIM_TOLERANCE:
        return _settle(
            claim,
            status=SavingClaim.Status.REJECTED,
            note=(
                f"{length_note} That is under {CLAIM_TOLERANCE:.0%} of the claimed "
                f"{claim.claimed_kwh_saved} kWh, so the claim is not supported. "
                f"A smaller claim of about {measured} kWh would verify."
            ),
            award=False,
        )

    return _settle(
        claim,
        status=SavingClaim.Status.VERIFIED,
        note=(
            f"{length_note} XP and coins are credited from the measured saving, "
            f"not the claimed figure."
        ),
        award=award,
    )


def _settle(claim: SavingClaim, status: str, note: str, award: bool) -> SavingClaim:
    claim.status = status
    claim.verification_note = note
    claim.verified_at = timezone.now()
    claim.save(
        update_fields=[
            "baseline_kwh",
            "claim_period_kwh",
            "measured_kwh_saved",
            "status",
            "verification_note",
            "verified_at",
        ]
    )

    if award and status == SavingClaim.Status.VERIFIED and claim.measured_kwh_saved:
        profile = Profile.for_user(claim.user)
        profile.award_verified(claim.measured_kwh_saved)
        profile.touch_streak()
        award_badges(profile)
        update_challenge_progress(claim)

    return claim


def award_badges(profile: Profile) -> list:
    """Award every badge whose criteria the profile now meets. Idempotent."""
    from gamification.models import Badge, UserBadge

    newly_awarded = []
    held = set(
        UserBadge.objects.filter(user=profile.user).values_list("badge_id", flat=True)
    )

    for badge in Badge.objects.all():
        if badge.pk in held or not badge.is_earned_by(profile):
            continue
        UserBadge.objects.create(user=profile.user, badge=badge)
        newly_awarded.append(badge)

    return newly_awarded


def update_challenge_progress(claim: SavingClaim) -> list:
    """
    Add a verified saving to any open challenge the user has joined.

    Only counts when the claim window falls inside the challenge window, so a
    saving cannot be credited to a challenge that had not started.
    """
    from gamification.models import ChallengeParticipation

    completed = []
    claim_date = timezone.localtime(claim.claim_end).date()

    participations = ChallengeParticipation.objects.filter(
        user=claim.user,
        challenge__is_active=True,
        challenge__starts_on__lte=claim_date,
        challenge__ends_on__gte=claim_date,
        completed_at__isnull=True,
    ).select_related("challenge")

    for participation in participations:
        participation.verified_kwh_saved += claim.measured_kwh_saved or Decimal("0")

        if participation.verified_kwh_saved >= participation.challenge.target_kwh:
            participation.completed_at = timezone.now()
            profile = Profile.for_user(claim.user)
            profile.verified_xp += participation.challenge.reward_xp
            profile.eco_coins += participation.challenge.reward_coins
            profile.save(update_fields=["verified_xp", "eco_coins", "updated_at"])
            completed.append(participation)

        participation.save(update_fields=["verified_kwh_saved", "completed_at"])

    return completed


def leaderboard(limit: int = 20) -> list[dict]:
    """
    Ranked by **verified** savings only.

    Self-reported activity XP is deliberately absent from the ordering. It is
    returned per row as `unverified_xp_excluded` so the UI can say so rather than
    leaving a user wondering why their logged journeys did not move them up.
    """
    rows = (
        Profile.objects.select_related("user")
        .filter(verified_xp__gt=0)
        .order_by("-verified_xp", "-verified_kwh_saved")[:limit]
    )

    return [
        {
            "rank": index,
            "username": profile.user.get_username(),
            "level": profile.level,
            "verified_xp": profile.verified_xp,
            "verified_kwh_saved": profile.verified_kwh_saved,
            "eco_coins": profile.eco_coins,
            "streak_days": profile.streak_days,
            "unverified_xp_excluded": profile.unverified_xp,
        }
        for index, profile in enumerate(rows, start=1)
    ]
