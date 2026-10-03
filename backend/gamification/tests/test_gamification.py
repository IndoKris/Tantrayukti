"""
Tests for gamification and proof of saving.

The property that matters most: **self-reported activity must never affect the
ranking, a badge, or a challenge.** Several tests exist purely to pin that.
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from gamification import verification
from gamification.models import (
    XP_PER_LEVEL,
    XP_PER_VERIFIED_KWH,
    Badge,
    Challenge,
    ChallengeParticipation,
    Profile,
    SavingClaim,
    UserBadge,
)
from spaces.models import Building, Floor, Membership, Organisation, Room
from telemetry.models import Device, Reading

User = get_user_model()


class GamificationTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_gamification", stdout=StringIO(), stderr=StringIO())

        cls.org = Organisation.objects.create(name="Org")
        building = Building.objects.create(organisation=cls.org, name="HQ")
        floor = Floor.objects.create(building=building, name="G", level=0)
        cls.room = Room.objects.create(floor=floor, name="Lab", area_sqm=Decimal("20"))
        cls.device = Device.objects.create(room=cls.room, name="Mains", kind=Device.Kind.MAINS)

        cls.other_org = Organisation.objects.create(name="Other")
        other_building = Building.objects.create(organisation=cls.other_org, name="B")
        other_floor = Floor.objects.create(building=other_building, name="G", level=0)
        other_room = Room.objects.create(floor=other_floor, name="R")
        cls.other_device = Device.objects.create(room=other_room, name="Theirs")

        cls.user = User.objects.create_user(
            username="saver", email="s@example.com", password="pw"
        )
        cls.rival = User.objects.create_user(
            username="rival", email="r@example.com", password="pw"
        )
        for user in (cls.user, cls.rival):
            Membership.objects.create(user=user, organisation=cls.org)

    def readings(self, start, hours: int, kwh_per_hour: float):
        """Hourly readings, one per hour, starting at `start`."""
        for index in range(hours):
            Reading.objects.update_or_create(
                device=self.device,
                timestamp=start + timedelta(hours=index),
                defaults={
                    "active_power_w": Decimal(str(round(kwh_per_hour * 1000, 2))),
                    "energy_wh": Decimal(str(round(kwh_per_hour * 1000, 4))),
                },
            )

    def make_claim(self, claimed="24", baseline_kwh=2.0, after_kwh=1.0, hours=24, user=None):
        """
        A claim with telemetry behind it.

        Baseline and claim windows are the same length, so no length scaling is
        needed to reason about the expected figures.
        """
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        baseline_start = now - timedelta(hours=hours * 2)
        claim_start = now - timedelta(hours=hours)

        self.readings(baseline_start, hours, baseline_kwh)
        self.readings(claim_start, hours, after_kwh)

        return SavingClaim.objects.create(
            user=user or self.user,
            device=self.device,
            action_taken="raised the AC setpoint",
            baseline_start=baseline_start,
            baseline_end=claim_start,
            claim_start=claim_start,
            claim_end=now,
            claimed_kwh_saved=Decimal(claimed),
        )


class ProfileTests(GamificationTestCase):
    def test_a_profile_is_created_on_demand(self):
        profile = Profile.for_user(self.user)
        self.assertEqual(profile.verified_xp, 0)
        self.assertEqual(profile.level, 1)

    def test_levels_come_from_verified_xp_only(self):
        """Levels must not be reachable by self-reporting."""
        profile = Profile.for_user(self.user)
        profile.award_unverified(XP_PER_LEVEL * 5)
        self.assertEqual(profile.level, 1)

        profile.award_verified(Decimal(XP_PER_LEVEL / XP_PER_VERIFIED_KWH))
        self.assertEqual(profile.level, 2)

    def test_verified_savings_award_xp_and_coins(self):
        profile = Profile.for_user(self.user)
        result = profile.award_verified(Decimal("10"))

        self.assertEqual(result["xp"], 10 * XP_PER_VERIFIED_KWH)
        self.assertEqual(profile.verified_kwh_saved, Decimal("10"))
        self.assertGreater(profile.eco_coins, 0)

    def test_a_zero_or_negative_saving_awards_nothing(self):
        profile = Profile.for_user(self.user)
        self.assertEqual(profile.award_verified(Decimal("0"))["xp"], 0)
        self.assertEqual(profile.award_verified(Decimal("-5"))["xp"], 0)
        self.assertEqual(profile.verified_xp, 0)

    def test_unverified_xp_is_tracked_separately(self):
        profile = Profile.for_user(self.user)
        profile.award_unverified(50)

        self.assertEqual(profile.unverified_xp, 50)
        self.assertEqual(profile.verified_xp, 0)
        self.assertEqual(profile.total_xp_including_unverified, 50)


class StreakTests(GamificationTestCase):
    def test_a_first_day_starts_a_streak_of_one(self):
        profile = Profile.for_user(self.user)
        profile.touch_streak(timezone.localdate())
        self.assertEqual(profile.streak_days, 1)

    def test_consecutive_days_extend_the_streak(self):
        profile = Profile.for_user(self.user)
        today = timezone.localdate()
        for offset in range(3):
            profile.touch_streak(today - timedelta(days=2 - offset))
        self.assertEqual(profile.streak_days, 3)

    def test_the_same_day_twice_does_not_double_count(self):
        profile = Profile.for_user(self.user)
        today = timezone.localdate()
        profile.touch_streak(today)
        profile.touch_streak(today)
        self.assertEqual(profile.streak_days, 1)

    def test_a_one_day_gap_is_forgiven(self):
        profile = Profile.for_user(self.user)
        today = timezone.localdate()
        profile.touch_streak(today - timedelta(days=3))
        profile.touch_streak(today - timedelta(days=1))
        self.assertEqual(profile.streak_days, 2)

    def test_a_long_gap_resets_to_one(self):
        profile = Profile.for_user(self.user)
        today = timezone.localdate()
        profile.touch_streak(today - timedelta(days=10))
        profile.touch_streak(today)
        self.assertEqual(profile.streak_days, 1)

    def test_the_longest_streak_is_remembered(self):
        profile = Profile.for_user(self.user)
        today = timezone.localdate()
        for offset in range(4):
            profile.touch_streak(today - timedelta(days=20 - offset))
        profile.touch_streak(today)

        self.assertEqual(profile.streak_days, 1)
        self.assertEqual(profile.longest_streak_days, 4)


class ProofOfSavingTests(GamificationTestCase):
    def test_a_supported_claim_is_verified(self):
        """Baseline 48 kWh vs 24 kWh after, over equal windows: 24 kWh saved."""
        claim = self.make_claim(claimed="24", baseline_kwh=2.0, after_kwh=1.0)
        verification.verify(claim)

        self.assertEqual(claim.status, SavingClaim.Status.VERIFIED)
        self.assertAlmostEqual(float(claim.measured_kwh_saved), 24.0, places=2)

    def test_xp_comes_from_the_measured_saving_not_the_claim(self):
        """Over-claiming must not earn more."""
        claim = self.make_claim(claimed="24", baseline_kwh=2.0, after_kwh=1.0)
        verification.verify(claim)

        profile = Profile.for_user(self.user)
        self.assertAlmostEqual(
            float(profile.verified_kwh_saved), float(claim.measured_kwh_saved), places=2
        )

    def test_a_claim_with_no_real_reduction_is_rejected(self):
        claim = self.make_claim(claimed="20", baseline_kwh=1.0, after_kwh=1.0)
        verification.verify(claim)

        self.assertEqual(claim.status, SavingClaim.Status.REJECTED)
        self.assertEqual(Profile.for_user(self.user).verified_xp, 0)
        self.assertIn("no reduction", claim.verification_note)

    def test_a_wildly_over_stated_claim_is_rejected_with_a_suggestion(self):
        # 2 kWh really saved against a 100 kWh claim.
        claim = self.make_claim(claimed="100", baseline_kwh=1.1, after_kwh=1.0)
        verification.verify(claim)

        self.assertEqual(claim.status, SavingClaim.Status.REJECTED)
        self.assertIn("would verify", claim.verification_note)

    def test_an_understated_claim_still_verifies_and_pays_the_measurement(self):
        claim = self.make_claim(claimed="5", baseline_kwh=2.0, after_kwh=1.0)
        verification.verify(claim)

        self.assertEqual(claim.status, SavingClaim.Status.VERIFIED)
        self.assertGreater(claim.measured_kwh_saved, Decimal("5"))

    def test_too_little_telemetry_is_unverifiable_not_rejected(self):
        """"We cannot tell" and "it did not happen" are different answers."""
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        claim = SavingClaim.objects.create(
            user=self.user,
            device=self.device,
            action_taken="did a thing",
            baseline_start=now - timedelta(hours=48),
            baseline_end=now - timedelta(hours=24),
            claim_start=now - timedelta(hours=24),
            claim_end=now,
            claimed_kwh_saved=Decimal("10"),
        )
        verification.verify(claim)

        self.assertEqual(claim.status, SavingClaim.Status.UNVERIFIABLE)
        self.assertIn("not a rejection", claim.verification_note)

    def test_unequal_window_lengths_are_normalised(self):
        """
        A 48 h baseline against a 24 h claim window would otherwise show a 50%
        saving from arithmetic alone.
        """
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        baseline_start = now - timedelta(hours=72)
        claim_start = now - timedelta(hours=24)

        self.readings(baseline_start, 48, 1.0)  # 48 kWh over 48 h
        self.readings(claim_start, 24, 1.0)  # 24 kWh over 24 h, same rate

        claim = SavingClaim.objects.create(
            user=self.user,
            device=self.device,
            action_taken="changed nothing",
            baseline_start=baseline_start,
            baseline_end=baseline_start + timedelta(hours=48),
            claim_start=claim_start,
            claim_end=now,
            claimed_kwh_saved=Decimal("20"),
        )
        verification.verify(claim)

        # Same consumption rate, so no saving once lengths are normalised.
        self.assertEqual(claim.status, SavingClaim.Status.REJECTED)
        self.assertAlmostEqual(float(claim.measured_kwh_saved), 0.0, places=1)
        self.assertIn("scaled by", claim.verification_note)

    def test_the_note_shows_the_arithmetic(self):
        claim = self.make_claim()
        verification.verify(claim)
        self.assertIn("Measured saving", claim.verification_note)
        self.assertIn("kWh", claim.verification_note)


class BadgeTests(GamificationTestCase):
    def test_a_verified_claim_awards_the_first_proof_badge(self):
        claim = self.make_claim()
        verification.verify(claim)

        codes = set(
            UserBadge.objects.filter(user=self.user).values_list("badge__code", flat=True)
        )
        self.assertIn("first-proof", codes)

    def test_a_kwh_threshold_badge_is_awarded(self):
        claim = self.make_claim(claimed="24", baseline_kwh=2.0, after_kwh=1.0)
        verification.verify(claim)

        codes = set(
            UserBadge.objects.filter(user=self.user).values_list("badge__code", flat=True)
        )
        self.assertIn("saver-10", codes)
        self.assertNotIn("saver-100", codes)

    def test_badges_are_not_awarded_twice(self):
        claim = self.make_claim()
        verification.verify(claim)
        before = UserBadge.objects.filter(user=self.user).count()

        verification.award_badges(Profile.for_user(self.user))
        self.assertEqual(UserBadge.objects.filter(user=self.user).count(), before)

    def test_unverified_xp_alone_unlocks_nothing(self):
        """A badge must not be reachable by logging activity."""
        profile = Profile.for_user(self.user)
        profile.award_unverified(100_000)
        verification.award_badges(profile)

        self.assertEqual(UserBadge.objects.filter(user=self.user).count(), 0)

    def test_a_badge_with_no_thresholds_is_never_auto_awarded(self):
        decorative = Badge.objects.create(
            code="decorative", name="Decorative", description="No criteria."
        )
        profile = Profile.for_user(self.user)
        profile.award_verified(Decimal("1000"))

        self.assertFalse(decorative.is_earned_by(profile))


class ChallengeTests(GamificationTestCase):
    def setUp(self):
        self.challenge = Challenge.objects.get(name="Save 25 kWh this month")

    def test_a_user_can_join_an_open_challenge(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            reverse("gamification:challenge-join", args=[self.challenge.pk])
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_joining_twice_is_idempotent(self):
        self.client.force_authenticate(self.user)
        url = reverse("gamification:challenge-join", args=[self.challenge.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(ChallengeParticipation.objects.filter(user=self.user).count(), 1)

    def test_a_closed_challenge_cannot_be_joined(self):
        closed = Challenge.objects.create(
            name="Finished",
            target_kwh=Decimal("10"),
            starts_on=timezone.localdate() - timedelta(days=60),
            ends_on=timezone.localdate() - timedelta(days=30),
        )
        self.client.force_authenticate(self.user)
        response = self.client.post(
            reverse("gamification:challenge-join", args=[closed.pk])
        )
        self.assertEqual(response.status_code, 400)

    def test_a_verified_claim_advances_challenge_progress(self):
        ChallengeParticipation.objects.create(challenge=self.challenge, user=self.user)
        claim = self.make_claim(claimed="24", baseline_kwh=2.0, after_kwh=1.0)
        verification.verify(claim)

        participation = ChallengeParticipation.objects.get(
            challenge=self.challenge, user=self.user
        )
        self.assertGreater(participation.verified_kwh_saved, Decimal("0"))

    def test_meeting_the_target_completes_the_challenge_and_pays_the_reward(self):
        ChallengeParticipation.objects.create(challenge=self.challenge, user=self.user)
        # 48 kWh baseline vs 24 kWh after -> 24 kWh; target is 25, so claim twice.
        verification.verify(self.make_claim(claimed="24", baseline_kwh=2.0, after_kwh=1.0))

        participation = ChallengeParticipation.objects.get(
            challenge=self.challenge, user=self.user
        )
        if not participation.is_complete:
            # Second claim on a different window pushes it over the target.
            now = timezone.now().replace(minute=0, second=0, microsecond=0)
            baseline_start = now - timedelta(hours=96)
            claim_start = now - timedelta(hours=72)
            self.readings(baseline_start, 24, 2.0)
            self.readings(claim_start, 24, 1.0)
            verification.verify(
                SavingClaim.objects.create(
                    user=self.user,
                    device=self.device,
                    action_taken="again",
                    baseline_start=baseline_start,
                    baseline_end=claim_start,
                    claim_start=claim_start,
                    claim_end=claim_start + timedelta(hours=24),
                    claimed_kwh_saved=Decimal("24"),
                )
            )
            participation.refresh_from_db()

        self.assertTrue(participation.is_complete)
        self.assertGreaterEqual(
            Profile.for_user(self.user).eco_coins, self.challenge.reward_coins
        )

    def test_unverified_xp_does_not_advance_a_challenge(self):
        ChallengeParticipation.objects.create(challenge=self.challenge, user=self.user)
        Profile.for_user(self.user).award_unverified(100_000)

        participation = ChallengeParticipation.objects.get(user=self.user)
        self.assertEqual(participation.verified_kwh_saved, Decimal("0"))
        self.assertFalse(participation.is_complete)


class LeaderboardTests(GamificationTestCase):
    def test_the_leaderboard_ranks_on_verified_xp(self):
        Profile.for_user(self.user).award_verified(Decimal("50"))
        Profile.for_user(self.rival).award_verified(Decimal("10"))

        rows = verification.leaderboard()
        self.assertEqual(rows[0]["username"], "saver")
        self.assertEqual(rows[1]["username"], "rival")

    def test_unverified_xp_cannot_change_the_ranking(self):
        """The central guarantee of the whole app."""
        Profile.for_user(self.user).award_verified(Decimal("10"))

        rival = Profile.for_user(self.rival)
        rival.award_verified(Decimal("5"))
        rival.award_unverified(1_000_000)

        rows = verification.leaderboard()
        self.assertEqual(rows[0]["username"], "saver")
        self.assertEqual(rows[1]["username"], "rival")

    def test_a_user_with_no_verified_savings_is_absent(self):
        Profile.for_user(self.rival).award_unverified(5000)
        usernames = [row["username"] for row in verification.leaderboard()]
        self.assertNotIn("rival", usernames)

    def test_each_row_reports_the_excluded_unverified_xp(self):
        profile = Profile.for_user(self.user)
        profile.award_verified(Decimal("10"))
        profile.award_unverified(77)

        row = verification.leaderboard()[0]
        self.assertEqual(row["unverified_xp_excluded"], 77)

    def test_the_endpoint_states_its_basis(self):
        Profile.for_user(self.user).award_verified(Decimal("10"))
        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("gamification:leaderboard")).json()

        self.assertIn("verified", body["basis"])
        self.assertIn("excluded", body["basis"])
        self.assertEqual(body["me"]["rank"], 1)


class ApiTests(GamificationTestCase):
    def test_the_profile_endpoint_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("gamification:profile")).status_code, 401)

    def test_the_profile_endpoint_separates_verified_from_unverified(self):
        profile = Profile.for_user(self.user)
        profile.award_verified(Decimal("10"))
        profile.award_unverified(30)

        self.client.force_authenticate(self.user)
        body = self.client.get(reverse("gamification:profile")).json()

        self.assertEqual(body["profile"]["verified_xp"], 100)
        self.assertEqual(body["profile"]["unverified_xp"], 30)
        self.assertIn("never affects your rank", body["ranking_note"])

    def test_a_claim_can_be_submitted_and_verified_through_the_api(self):
        claim = self.make_claim()
        self.client.force_authenticate(self.user)

        response = self.client.post(
            reverse("gamification:claim-verify", args=[claim.pk])
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["claim"]["status"], "verified")

    def test_verifying_twice_is_a_409(self):
        claim = self.make_claim()
        self.client.force_authenticate(self.user)
        url = reverse("gamification:claim-verify", args=[claim.pk])
        self.client.post(url)
        self.assertEqual(self.client.post(url).status_code, 409)

    def test_preview_awards_nothing(self):
        claim = self.make_claim()
        self.client.force_authenticate(self.user)

        response = self.client.post(reverse("gamification:claim-preview", args=[claim.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Profile.for_user(self.user).verified_xp, 0)
        self.assertIn("Dry run", response.json()["note"])

    def test_claims_are_private_to_their_owner(self):
        mine = self.make_claim()
        theirs = self.make_claim(user=self.rival)

        self.client.force_authenticate(self.user)
        ids = [row["id"] for row in self.client.get(reverse("gamification:claim-list")).json()["results"]]

        self.assertIn(mine.pk, ids)
        self.assertNotIn(theirs.pk, ids)

    def test_a_claim_cannot_name_a_device_in_another_organisation(self):
        self.client.force_authenticate(self.user)
        now = timezone.now()
        response = self.client.post(
            reverse("gamification:claim-list"),
            {
                "device": self.other_device.pk,
                "action_taken": "nothing",
                "baseline_start": (now - timedelta(hours=48)).isoformat(),
                "baseline_end": (now - timedelta(hours=24)).isoformat(),
                "claim_start": (now - timedelta(hours=24)).isoformat(),
                "claim_end": now.isoformat(),
                "claimed_kwh_saved": "5",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("device", response.json())

    def test_overlapping_windows_are_rejected(self):
        self.client.force_authenticate(self.user)
        now = timezone.now()
        response = self.client.post(
            reverse("gamification:claim-list"),
            {
                "device": self.device.pk,
                "action_taken": "nothing",
                "baseline_start": (now - timedelta(hours=48)).isoformat(),
                "baseline_end": now.isoformat(),
                "claim_start": (now - timedelta(hours=24)).isoformat(),
                "claim_end": now.isoformat(),
                "claimed_kwh_saved": "5",
            },
        )
        self.assertEqual(response.status_code, 400)


class SeedTests(APITestCase):
    def test_seeding_is_idempotent(self):
        call_command("seed_gamification", stdout=StringIO(), stderr=StringIO())
        counts = (Badge.objects.count(), Challenge.objects.count())
        call_command("seed_gamification", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(counts, (Badge.objects.count(), Challenge.objects.count()))

    def test_every_seeded_badge_requires_verified_savings(self):
        call_command("seed_gamification", stdout=StringIO(), stderr=StringIO())
        for badge in Badge.objects.all():
            self.assertTrue(badge.requires_verified, badge.code)
