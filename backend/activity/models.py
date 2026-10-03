"""
Manual activity logging across five categories.

**Every emission factor here is a published estimate, not a measurement**, and
each one carries its own `source` string that travels with any figure computed
from it - the same rule the Phase 9 CO2 engine follows. Factors live in the
database rather than in code so they can be corrected without a deploy, and are
seeded with `seed_activity_factors`.

**Manual entries are tagged `is_verified=False` and never mix with telemetry.**
Phase 21 excludes unverified entries from the leaderboard; that distinction
starts here, because a self-reported bus journey is not evidence in the way a
metered kWh is.

Units are named in every field: `quantity` is in the factor's own
`quantity_unit` (km, kWh, meals, items, kg), and `kg_co2` is always kilograms.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Category(models.TextChoices):
    TRANSPORT = "transport", "Transport"
    HOME_ENERGY = "home_energy", "Home energy"
    DIET = "diet", "Diet"
    SHOPPING = "shopping", "Shopping"
    WASTE = "waste", "Waste"


class EmissionFactorRow(models.Model):
    """
    One activity type and its emission factor.

    `kg_co2_per_unit` times a quantity gives kilograms of CO2e. The `source` is
    mandatory in practice because the plan requires provenance wherever an
    emissions figure is shown.
    """

    category = models.CharField(max_length=16, choices=Category.choices)
    key = models.SlugField(
        max_length=60, unique=True, help_text="Stable identifier, e.g. 'car-petrol'."
    )
    label = models.CharField(max_length=120)
    quantity_unit = models.CharField(
        max_length=20, help_text="Unit the quantity is measured in: km, kWh, meals, items, kg."
    )
    kg_co2_per_unit = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        validators=[MinValueValidator(Decimal("0"))],
    )
    source = models.TextField(help_text="Where the factor came from. Shown with every figure.")
    is_verified = models.BooleanField(
        default=False,
        help_text="False means the value has not been checked against a primary source.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "label"]

    def __str__(self) -> str:
        return f"{self.label} ({self.kg_co2_per_unit} kg CO2e/{self.quantity_unit})"


class ActivityEntry(models.Model):
    """
    One logged activity.

    `kg_co2` is computed on save from the factor and stored, so a later factor
    correction does not silently rewrite history. `factor_snapshot` records the
    factor actually used, which is what makes the stored figure auditable.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activity_entries"
    )
    factor = models.ForeignKey(
        EmissionFactorRow, on_delete=models.PROTECT, related_name="entries"
    )
    occurred_on = models.DateField(db_index=True)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))]
    )
    note = models.CharField(max_length=200, blank=True)

    kg_co2 = models.DecimalField(
        max_digits=12, decimal_places=4, editable=False, default=Decimal("0")
    )
    factor_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        editable=False,
        default=Decimal("0"),
        help_text="The factor used at entry time, so a later correction cannot rewrite history.",
    )
    is_verified = models.BooleanField(
        default=False,
        editable=False,
        help_text=(
            "Manual entries are self-reported, so always False. Only telemetry-backed "
            "reductions are verified (Phase 21)."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_on", "-created_at"]
        verbose_name_plural = "activity entries"
        indexes = [
            models.Index(fields=["user", "-occurred_on"], name="activity_user_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.occurred_on} {self.factor.label}: {self.quantity} -> {self.kg_co2} kg CO2e"

    @property
    def category(self) -> str:
        return self.factor.category

    @property
    def formula(self) -> str:
        """
        The arithmetic behind `kg_co2`, for display and for the CSV export.

        The quantity is quantized to the field's own precision so the string
        reads identically whether the instance was just constructed or reloaded
        from the database - otherwise `Decimal("100")` and `Decimal("100.000")`
        render two different formulas for the same entry.
        """
        quantity = Decimal(self.quantity).quantize(Decimal("0.001"))
        return (
            f"{quantity} {self.factor.quantity_unit} x {self.factor_snapshot} "
            f"kg CO2e/{self.factor.quantity_unit} = {self.kg_co2} kg CO2e"
        )

    def save(self, *args, **kwargs):
        self.factor_snapshot = Decimal(self.factor.kg_co2_per_unit)
        self.kg_co2 = (Decimal(self.quantity) * self.factor_snapshot).quantize(
            Decimal("0.0001")
        )
        # Self-reported, by definition.
        self.is_verified = False
        super().save(*args, **kwargs)


class MonthlyBudget(models.Model):
    """A user's self-set monthly CO2e budget, used by the reports page."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="co2_budget"
    )
    kg_co2_per_month = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Target kilograms of CO2e per month across all categories.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user}: {self.kg_co2_per_month} kg CO2e/month"
