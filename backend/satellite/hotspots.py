"""
NO2 hotspot detection.

**No fixed contamination, and no fixed percentile either.** The same trap the
Phase 13 detector fell into applies with more force here: there are only 20
cities, so `contamination=0.05` would label exactly one of them a hotspot
whatever the data said, and a percentile cutoff would do the same. Either way the
"finding" would be an artefact of the parameter rather than of the air quality.

What is used instead, and both conditions must hold:

1. The Isolation Forest flags the city as an outlier using its own
   `contamination="auto"` offset, and
2. the city's NO2 column exceeds a **robust upper fence** computed from the data
   (`median + k x MAD-sigma`).

So a set of cities with similar readings yields **no** hotspots, which is the
correct answer rather than an empty-looking result. A test pins exactly that.

Features are the NO2 column and population, because a high column over a small
population is a different story from one over a dense city - the multivariate
detector can separate them where a threshold on NO2 alone cannot.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from satellite.models import NO2_UNIT, CityNo2

#: Scale factor from median absolute deviation to a normal-equivalent sigma.
MAD_TO_SIGMA = 1.4826

#: A city must exceed median + this many robust sigmas to be a hotspot.
FENCE_SIGMAS = 1.5

#: Fewer cities than this and the Isolation Forest is not meaningful.
MIN_CITIES = 8


def robust_fence(values) -> tuple[float, float, float]:
    """Median, robust sigma and the upper fence for a set of values."""
    array = np.asarray(list(values), dtype=float)
    median = float(np.median(array))
    mad = float(np.median(np.abs(array - median)))
    sigma = max(mad * MAD_TO_SIGMA, 1e-9)
    return median, sigma, median + FENCE_SIGMAS * sigma


def detect_hotspots(queryset=None, persist: bool = True) -> dict:
    """
    Flag hotspot cities and optionally store the result.

    Returns a summary including the validated threshold, so a caller can show
    *why* a city was flagged rather than only that it was.
    """
    cities = list(queryset if queryset is not None else CityNo2.objects.all())

    if len(cities) < MIN_CITIES:
        return {
            "status": "not evaluated",
            "reason": (
                f"Only {len(cities)} cities available; at least {MIN_CITIES} are "
                f"needed for the detector to mean anything."
            ),
            "hotspots": [],
        }

    no2 = [float(city.no2_umol_per_m2) for city in cities]
    population = [float(city.population_millions or 0) for city in cities]

    median, sigma, fence = robust_fence(no2)

    from sklearn.ensemble import IsolationForest

    from ml.config import RANDOM_SEED

    features = np.column_stack([no2, population])
    model = IsolationForest(
        n_estimators=200,
        contamination="auto",  # the forest sets its own offset
        random_state=RANDOM_SEED,
    )
    model.fit(features)
    scores = model.decision_function(features)
    flagged_by_forest = model.predict(features) == -1

    hotspots = []
    for city, score, is_outlier in zip(cities, scores, flagged_by_forest):
        value = float(city.no2_umol_per_m2)
        # Both conditions, and only the high side: a city with unusually clean
        # air is not a hotspot.
        is_hotspot = bool(is_outlier and value > fence)

        city.anomaly_score = round(float(score), 6)
        city.is_hotspot = is_hotspot
        city.hotspot_note = (
            (
                f"Isolation Forest outlier (contamination=auto) AND NO2 column "
                f"{value:.1f} {NO2_UNIT} above the robust fence "
                f"{fence:.1f} {NO2_UNIT} (median {median:.1f} + "
                f"{FENCE_SIGMAS} x {sigma:.1f})."
            )
            if is_hotspot
            else (
                f"Not a hotspot: forest outlier={bool(is_outlier)}, "
                f"NO2 {value:.1f} vs fence {fence:.1f} {NO2_UNIT}."
            )
        )

        if persist:
            city.save(update_fields=["anomaly_score", "is_hotspot", "hotspot_note", "updated_at"])

        if is_hotspot:
            hotspots.append(city)

    return {
        "status": "evaluated",
        "unit": NO2_UNIT,
        "unit_note": (
            "Tropospheric column density, not a surface concentration. "
            "No ppb conversion is applied."
        ),
        "cities_considered": len(cities),
        "threshold": {
            "rule": (
                "Isolation Forest outlier using the model's own "
                "contamination='auto' offset AND NO2 above median + "
                f"{FENCE_SIGMAS} robust sigma. Neither a fixed contamination nor "
                "a fixed percentile is used, so a set of similar cities yields no "
                "hotspots."
            ),
            "median_umol_per_m2": round(median, 2),
            "robust_sigma_umol_per_m2": round(sigma, 2),
            "fence_umol_per_m2": round(fence, 2),
            "fence_sigmas": FENCE_SIGMAS,
        },
        "features": ["no2_umol_per_m2", "population_millions"],
        "hotspots": hotspots,
    }


def community_points(organisations, start, end, metering: str = "auto") -> list:
    """
    Aggregate metered energy onto city-level coordinates for the heatmap.

    Buildings without coordinates are skipped - a point cannot be placed on a
    map without them, and guessing a location would be worse than omitting it.
    Coordinates are rounded to 3 dp by `CommunityPoint.save`, so the published
    map never resolves to a household.
    """
    from collections import defaultdict

    from spaces.models import Building
    from telemetry import rollups
    from telemetry.models import Device

    from satellite.models import CommunityPoint, round_to_city

    buckets: dict[tuple, dict] = defaultdict(
        lambda: {
            "building_count": 0,
            "total_kwh": Decimal("0"),
            "total_area_sqm": Decimal("0"),
            "labels": [],
        }
    )

    buildings = Building.objects.filter(
        organisation__in=organisations, latitude__isnull=False, longitude__isnull=False
    ).select_related("organisation")

    for building in buildings:
        devices, _ = rollups.select_devices(
            Device.objects.filter(room__floor__building=building), metering
        )
        totals = rollups.totals(rollups.readings_for(devices, start, end))

        key = (round_to_city(building.latitude), round_to_city(building.longitude))
        bucket = buckets[key]
        bucket["building_count"] += 1
        bucket["total_kwh"] += Decimal(totals["energy_kwh"])
        if building.total_area_sqm:
            bucket["total_area_sqm"] += Decimal(building.total_area_sqm)
        bucket["labels"].append(building.organisation.name)

    points = []
    for (latitude, longitude), bucket in buckets.items():
        if bucket["building_count"] < CommunityPoint.MIN_BUILDINGS:
            continue

        area = bucket["total_area_sqm"] or None
        point, _ = CommunityPoint.objects.update_or_create(
            latitude=latitude,
            longitude=longitude,
            defaults={
                # Named by area, never by a single building, so the label does
                # not identify a specific site.
                "label": sorted(set(bucket["labels"]))[0]
                if len(set(bucket["labels"])) == 1
                else f"{len(set(bucket['labels']))} organisations",
                "building_count": bucket["building_count"],
                "total_kwh": bucket["total_kwh"].quantize(Decimal("0.0001")),
                "total_area_sqm": area,
                "kwh_per_sqm": (
                    (bucket["total_kwh"] / area).quantize(Decimal("0.000001"))
                    if area and area > 0
                    else None
                ),
                "window_start": start,
                "window_end": end,
            },
        )
        points.append(point)

    return points
