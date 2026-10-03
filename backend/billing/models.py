"""
Tariffs and emission factors.

**Every rate in here is sample data unless someone replaces it.** `Tariff.is_sample`
and `Tariff.source` exist so the UI can say so, and the API returns both with
every estimate. The plan forbids presenting invented numbers as measured or
official ones.

Units, named explicitly throughout:

* `rate_inr_per_kwh`         - rupees per kilowatt-hour
* `fixed_charge_inr_month`   - rupees per month, independent of consumption
* `kg_co2_per_kwh`           - kilograms of CO2 per kilowatt-hour
* slab bounds are in **kWh per month**, which is how Indian slab tariffs work

**How slabs and time-of-use combine.** Indian slab tariffs are cumulative over a
billing month: which slab a unit falls into depends on the month's running
total, not on the hour it was used. Time-of-day charges are then applied as a
surcharge or rebate on top. The engine follows that order - slabs first on the
monthly total, then a time-of-use adjustment - and returns each step separately
so the arithmetic is auditable rather than a single opaque number.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

#: Fallback grid emission factor, kg CO2 per kWh, used when no EmissionFactor row
#: is marked default. Deliberately the plan's documented value so the number in
#: the code and the number in the docs cannot drift apart.
DEFAULT_KG_CO2_PER_KWH = Decimal("0.82")

#: Why that number is what it is. Returned with every CO2 figure the API produces.
DEFAULT_FACTOR_SOURCE = (
    "Project-plan default (0.82 kg CO2/kWh). A commonly cited approximate value "
    "for the Indian grid; it is static and unverified here. Check the current CEA "
    "CO2 Baseline Database for your year and region before using this for "
    "reporting. Phase 12 adds an optional model-derived hourly factor."
)


class Tariff(models.Model):
    """
    A named tariff plan.

    `organisation` is nullable so a sample tariff can be shared by every
    organisation; a real one would be scoped to the organisation that signed it.
    """

    name = models.CharField(max_length=120)
    organisation = models.ForeignKey(
        "spaces.Organisation",
        on_delete=models.CASCADE,
        related_name="tariffs",
        null=True,
        blank=True,
        help_text="Leave empty for a shared sample tariff available to everyone.",
    )
    currency = models.CharField(max_length=3, default="INR")
    fixed_charge_inr_month = models.DecimalField(
        "fixed charge (INR/month)",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Charged regardless of consumption.",
    )
    tax_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Applied to the energy charge plus fixed charge.",
    )

    is_sample = models.BooleanField(
        default=True,
        help_text="True for illustrative rates. The UI must label these as samples.",
    )
    source = models.TextField(
        blank=True,
        help_text="Where these rates came from. Shown alongside every estimate.",
    )
    effective_from = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False, help_text="Used when a request does not name a tariff."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self) -> str:
        return f"{self.name}{' (sample)' if self.is_sample else ''}"

    @classmethod
    def resolve(cls, organisation=None, tariff_id=None):
        """
        Pick the tariff to use: an explicit id, then the organisation's default,
        then a shared default, then any active tariff. Returns None if there are
        none at all, which the engine reports rather than guessing a rate.
        """
        if tariff_id is not None:
            return cls.objects.filter(pk=tariff_id, is_active=True).first()

        candidates = cls.objects.filter(is_active=True)
        if organisation is not None:
            owned = candidates.filter(organisation=organisation)
            if found := owned.filter(is_default=True).first() or owned.first():
                return found
        shared = candidates.filter(organisation__isnull=True)
        return shared.filter(is_default=True).first() or shared.first() or candidates.first()

    @property
    def ordered_slabs(self):
        return list(self.slabs.order_by("from_kwh"))

    @property
    def ordered_tou_rates(self):
        return list(self.tou_rates.order_by("start_hour"))


class TariffSlab(models.Model):
    """
    One cumulative consumption block, in kWh per billing month.

    `to_kwh` null means "and above". Blocks are expected to be contiguous and
    non-overlapping; `Tariff.clean_slabs()` reports gaps rather than silently
    mis-billing.
    """

    tariff = models.ForeignKey(Tariff, on_delete=models.CASCADE, related_name="slabs")
    from_kwh = models.DecimalField(
        "from (kWh/month)",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    to_kwh = models.DecimalField(
        "to (kWh/month)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Leave empty for the final, unbounded block.",
    )
    rate_inr_per_kwh = models.DecimalField(
        "rate (INR/kWh)",
        max_digits=8,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
    )
    label = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["tariff", "from_kwh"]
        constraints = [
            models.UniqueConstraint(
                fields=["tariff", "from_kwh"], name="unique_slab_start_per_tariff"
            )
        ]

    def __str__(self) -> str:
        upper = f"{self.to_kwh:g}" if self.to_kwh is not None else "and above"
        return f"{self.from_kwh:g}-{upper} kWh @ {self.rate_inr_per_kwh} INR/kWh"


class TimeOfUseRate(models.Model):
    """
    A time-of-day surcharge or rebate, as a multiplier on the slab rate.

    Indian time-of-day tariffs are normally expressed as a percentage surcharge
    on peak hours and a rebate off-peak, which is why this is a multiplier rather
    than an absolute rate: it composes with whichever slab the unit landed in.

    Windows use **local** hours (`TIME_ZONE`), matching the local-time buckets
    the Phase 8 rollups produce. `start_hour` > `end_hour` wraps past midnight,
    so an off-peak window of 22:00-06:00 is a single row.
    """

    tariff = models.ForeignKey(Tariff, on_delete=models.CASCADE, related_name="tou_rates")
    name = models.CharField(max_length=60)
    start_hour = models.PositiveSmallIntegerField(help_text="Local hour, 0-23, inclusive.")
    end_hour = models.PositiveSmallIntegerField(help_text="Local hour, 1-24, exclusive.")
    multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=3,
        default=Decimal("1.000"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="1.0 is no change; 1.2 is a 20% peak surcharge; 0.9 a 10% rebate.",
    )

    class Meta:
        ordering = ["tariff", "start_hour"]

    def __str__(self) -> str:
        return f"{self.name} {self.start_hour:02d}:00-{self.end_hour:02d}:00 x{self.multiplier}"

    def covers_hour(self, hour: int) -> bool:
        """True when a local hour falls in this window, handling midnight wrap."""
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        # Wraps past midnight, e.g. 22 -> 6.
        return hour >= self.start_hour or hour < self.end_hour


class EmissionFactor(models.Model):
    """
    Grid CO2 intensity, kg CO2 per kWh.

    `source` is mandatory in practice: the plan requires the provenance of the
    factor to be shown wherever a CO2 number appears, because the default is a
    static approximation rather than a measurement.
    """

    class Kind(models.TextChoices):
        STATIC = "static", "Static published factor"
        MODELLED = "modelled", "Model-derived (Phase 12 random forest)"

    name = models.CharField(max_length=120)
    region = models.CharField(max_length=80, default="India (national grid)")
    kg_co2_per_kwh = models.DecimalField(
        "factor (kg CO2/kWh)",
        max_digits=8,
        decimal_places=5,
        validators=[MinValueValidator(Decimal("0"))],
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.STATIC)
    source = models.TextField(help_text="Provenance. Returned with every CO2 figure.")
    is_verified = models.BooleanField(
        default=False,
        help_text="False means the value has not been checked against a primary source.",
    )
    is_default = models.BooleanField(default=False)
    valid_from = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.kg_co2_per_kwh} kg CO2/kWh)"

    @classmethod
    def resolve(cls, factor_id=None):
        """
        The factor to use, or None when the database has none.

        None is handled by the engine, which then falls back to
        `DEFAULT_KG_CO2_PER_KWH` and says so in the response - it never silently
        substitutes a number without naming its source.
        """
        if factor_id is not None:
            return cls.objects.filter(pk=factor_id).first()
        return cls.objects.filter(is_default=True).first() or cls.objects.first()


class BillingSettings(models.Model):
    """
    Per-organisation billing preferences.

    Kept separate from `Tariff` so switching tariff does not lose the
    organisation's choice of emission factor.
    """

    organisation = models.OneToOneField(
        "spaces.Organisation", on_delete=models.CASCADE, related_name="billing_settings"
    )
    tariff = models.ForeignKey(
        Tariff, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    emission_factor = models.ForeignKey(
        EmissionFactor, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "billing settings"

    def __str__(self) -> str:
        return f"Billing settings for {self.organisation}"
