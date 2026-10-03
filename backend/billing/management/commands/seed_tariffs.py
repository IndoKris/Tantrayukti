"""
Seed sample tariffs and the default emission factor.

**Every rate created here is illustrative.** `is_sample=True` and a `source`
string saying so are set on each tariff, and the API returns both with every
estimate. The plan forbids presenting invented numbers as official ones, and a
slab structure that merely looks like a real utility's is exactly the kind of
thing that gets mistaken for one.

Idempotent: re-running updates the sample rows in place.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from billing.models import (
    DEFAULT_FACTOR_SOURCE,
    DEFAULT_KG_CO2_PER_KWH,
    EmissionFactor,
    Tariff,
    TariffSlab,
    TimeOfUseRate,
)

SAMPLE_SOURCE = (
    "ILLUSTRATIVE SAMPLE RATES - not an actual utility tariff. The slab structure "
    "resembles a typical Indian residential/commercial LT tariff in shape only. "
    "Replace with your own tariff schedule before using any figure for a real bill."
)

RESIDENTIAL = {
    "name": "Sample residential slab tariff",
    "fixed_charge_inr_month": Decimal("110.00"),
    "tax_percent": Decimal("9.00"),
    "is_default": True,
    "slabs": [
        # (from_kwh, to_kwh, rate, label)
        (Decimal("0"), Decimal("100"), Decimal("4.7100"), "First 100 units"),
        (Decimal("100"), Decimal("300"), Decimal("10.2900"), "101-300 units"),
        (Decimal("300"), Decimal("500"), Decimal("14.5500"), "301-500 units"),
        (Decimal("500"), None, Decimal("16.6400"), "Above 500 units"),
    ],
    "tou": [],
}

COMMERCIAL = {
    "name": "Sample commercial tariff with time of day",
    "fixed_charge_inr_month": Decimal("480.00"),
    "tax_percent": Decimal("9.00"),
    "is_default": False,
    "slabs": [
        (Decimal("0"), Decimal("500"), Decimal("9.4500"), "First 500 units"),
        (Decimal("500"), None, Decimal("11.2000"), "Above 500 units"),
    ],
    "tou": [
        # (name, start_hour, end_hour, multiplier)
        ("Off-peak night rebate", 22, 6, Decimal("0.850")),
        ("Normal day", 6, 18, Decimal("1.000")),
        ("Evening peak surcharge", 18, 22, Decimal("1.200")),
    ],
}


class Command(BaseCommand):
    help = "Create or refresh the sample tariffs and the default emission factor."

    @transaction.atomic
    def handle(self, *args, **options):
        for spec in (RESIDENTIAL, COMMERCIAL):
            tariff = self._seed_tariff(spec)
            self.stdout.write(
                f"  {tariff.name}: {tariff.slabs.count()} slab(s), "
                f"{tariff.tou_rates.count()} time-of-day window(s), "
                f"fixed {tariff.fixed_charge_inr_month} INR/month, "
                f"tax {tariff.tax_percent}%"
            )

        factor = self._seed_factor()
        self.stdout.write(
            f"  Emission factor: {factor.kg_co2_per_kwh} kg CO2/kWh "
            f"({'verified' if factor.is_verified else 'UNVERIFIED default'})"
        )

        self.stdout.write(
            self.style.WARNING(
                "All seeded rates are ILLUSTRATIVE SAMPLES, flagged is_sample=True.\n"
                "  The emission factor is a static unverified default; check the CEA\n"
                "  CO2 Baseline Database before using it for reporting."
            )
        )
        self.stdout.write(self.style.SUCCESS("Seeded 2 sample tariffs and 1 emission factor."))

    def _seed_tariff(self, spec: dict) -> Tariff:
        tariff, _ = Tariff.objects.update_or_create(
            name=spec["name"],
            organisation=None,
            defaults={
                "currency": "INR",
                "fixed_charge_inr_month": spec["fixed_charge_inr_month"],
                "tax_percent": spec["tax_percent"],
                "is_sample": True,
                "source": SAMPLE_SOURCE,
                "is_active": True,
                "is_default": spec["is_default"],
            },
        )

        for from_kwh, to_kwh, rate, label in spec["slabs"]:
            TariffSlab.objects.update_or_create(
                tariff=tariff,
                from_kwh=from_kwh,
                defaults={"to_kwh": to_kwh, "rate_inr_per_kwh": rate, "label": label},
            )

        for name, start, end, multiplier in spec["tou"]:
            TimeOfUseRate.objects.update_or_create(
                tariff=tariff,
                name=name,
                defaults={"start_hour": start, "end_hour": end, "multiplier": multiplier},
            )

        return tariff

    def _seed_factor(self) -> EmissionFactor:
        factor, _ = EmissionFactor.objects.update_or_create(
            name="India national grid (static default)",
            defaults={
                "region": "India (national grid)",
                "kg_co2_per_kwh": DEFAULT_KG_CO2_PER_KWH,
                "kind": EmissionFactor.Kind.STATIC,
                "source": DEFAULT_FACTOR_SOURCE,
                # Honest: nobody has checked this against a primary source here.
                "is_verified": False,
                "is_default": True,
            },
        )
        return factor
