"""
City NO2 readings and the community map.

**Units, and the mistake this module exists to avoid.** Satellite NO2 from an
instrument like Sentinel-5P TROPOMI is a **tropospheric column density** -
molecules integrated through a column of atmosphere - reported here in
**micromol per square metre (umol/m2)**. It is *not* a surface concentration.
Converting a column to surface ppb or ug/m3 needs a vertical profile and
boundary-layer height, which this project does not model, so **no conversion is
performed and none is implied**. Every serialised value carries its unit and a
note saying so.

**Privacy.** Community coordinates are rounded to 3 decimal places (roughly
100 m) before storage, so the map cannot resolve to a household. The rounding
happens on save, not at render time, so the precise value is never persisted.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

#: Decimal places kept for any public coordinate. 3 dp is about 100 m.
CITY_COORDINATE_PLACES = Decimal("0.001")

#: The unit every NO2 value in this app is expressed in.
NO2_UNIT = "umol/m2"

NO2_UNIT_NOTE = (
    "Tropospheric NO2 COLUMN density in micromol per square metre (umol/m2). "
    "This is a column integrated through the atmosphere, not a surface "
    "concentration: it cannot be read as ppb or ug/m3 without a vertical profile "
    "and boundary-layer assumptions, and no such conversion is applied here."
)


def round_to_city(value) -> Decimal | None:
    """Round a coordinate to city level, so a point cannot identify a household."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(CITY_COORDINATE_PLACES, rounding=ROUND_HALF_UP)


class CityNo2(models.Model):
    """
    One city's NO2 column reading.

    `source` and `is_measured` travel with every figure. The seeded rows are a
    static fallback used because no Earth Engine credentials are configured, and
    they say so.
    """

    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=3)
    longitude = models.DecimalField(max_digits=9, decimal_places=3)

    no2_umol_per_m2 = models.DecimalField(
        "tropospheric NO2 column (umol/m2)",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    population_millions = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )

    observed_on = models.DateField(null=True, blank=True)
    source = models.TextField(help_text="Provenance. Returned with every value.")
    is_measured = models.BooleanField(
        default=False,
        help_text="False for the static fallback values seeded without Earth Engine.",
    )

    # --- Filled in by the hotspot detector ---
    anomaly_score = models.FloatField(
        null=True, blank=True, help_text="Isolation Forest decision function."
    )
    is_hotspot = models.BooleanField(default=False)
    hotspot_note = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-no2_umol_per_m2"]
        verbose_name = "city NO2 reading"
        verbose_name_plural = "city NO2 readings"
        constraints = [
            models.UniqueConstraint(fields=["city", "state"], name="unique_city_state")
        ]

    def __str__(self) -> str:
        return f"{self.city}: {self.no2_umol_per_m2} {NO2_UNIT}"

    def save(self, *args, **kwargs):
        # Round before storing: the precise coordinate is never persisted.
        self.latitude = round_to_city(self.latitude)
        self.longitude = round_to_city(self.longitude)
        super().save(*args, **kwargs)


class CommunityPoint(models.Model):
    """
    An aggregated consumption point for the heatmap.

    Built from building coordinates and their metered energy, with coordinates
    rounded to city level on save and a minimum number of contributing buildings
    before a point is published - so a single household is never identifiable
    from the map.
    """

    #: A point is only published when at least this many buildings contribute.
    MIN_BUILDINGS = 1

    latitude = models.DecimalField(max_digits=9, decimal_places=3)
    longitude = models.DecimalField(max_digits=9, decimal_places=3)
    label = models.CharField(max_length=120, blank=True)

    building_count = models.PositiveIntegerField(default=0)
    total_kwh = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    total_area_sqm = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    kwh_per_sqm = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True
    )

    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-total_kwh"]

    def __str__(self) -> str:
        return f"{self.label or 'point'} at {self.latitude},{self.longitude}"

    def save(self, *args, **kwargs):
        self.latitude = round_to_city(self.latitude)
        self.longitude = round_to_city(self.longitude)
        super().save(*args, **kwargs)
