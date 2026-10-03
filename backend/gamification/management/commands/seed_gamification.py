"""
Seed badge definitions and a sample challenge.

Every badge threshold is expressed in **verified** kWh, streak days or confirmed
claims, so no badge can be earned by self-reported activity alone.

Idempotent: re-running updates the rows in place.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from gamification.models import Badge, Challenge

BADGES = [
    # (code, name, emoji, description, kwh, streak, claims)
    ("first-proof", "First proof", "\U0001f331",
     "Had one reduction confirmed by a meter.", None, None, 1),
    ("saver-10", "10 kWh saved", "\U0001f50b",
     "Saved 10 verified kWh.", "10.00", None, None),
    ("saver-100", "100 kWh saved", "\u26a1",
     "Saved 100 verified kWh.", "100.00", None, None),
    ("saver-500", "500 kWh saved", "\U0001f3c6",
     "Saved 500 verified kWh.", "500.00", None, None),
    ("streak-7", "One week streak", "\U0001f525",
     "Active seven days in a row.", None, 7, None),
    ("streak-30", "One month streak", "\U0001f4c5",
     "Active thirty days in a row.", None, 30, None),
    ("proven-five", "Five confirmed", "\u2705",
     "Had five separate reductions confirmed by a meter.", None, None, 5),
]


class Command(BaseCommand):
    help = "Create or refresh the badge definitions and a sample challenge."

    @transaction.atomic
    def handle(self, *args, **options):
        for code, name, emoji, description, kwh, streak, claims in BADGES:
            Badge.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "emoji": emoji,
                    "description": description,
                    "threshold_verified_kwh": Decimal(kwh) if kwh else None,
                    "threshold_streak_days": streak,
                    "threshold_verified_claims": claims,
                    "requires_verified": True,
                },
            )
        self.stdout.write(f"  {len(BADGES)} badge(s)")

        today = timezone.localdate()
        challenge, _ = Challenge.objects.update_or_create(
            name="Save 25 kWh this month",
            defaults={
                "description": (
                    "Reduce metered consumption by 25 kWh. Only savings confirmed "
                    "against telemetry count towards the target."
                ),
                "target_kwh": Decimal("25.00"),
                "reward_xp": 300,
                "reward_coins": 150,
                "starts_on": today.replace(day=1),
                "ends_on": (today.replace(day=1) + timedelta(days=31)).replace(day=1)
                - timedelta(days=1),
                "is_active": True,
            },
        )
        self.stdout.write(f"  challenge: {challenge.name} (target {challenge.target_kwh} kWh)")

        self.stdout.write(
            self.style.WARNING(
                "Every badge and challenge counts VERIFIED savings only.\n"
                "  Self-reported activity never unlocks a badge or completes a challenge."
            )
        )
        self.stdout.write(self.style.SUCCESS("Seeded gamification definitions."))
