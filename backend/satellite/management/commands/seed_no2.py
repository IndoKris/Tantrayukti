"""
Load the static city NO2 fallback and run hotspot detection.

**No Earth Engine attempt is made.** The plan's fallback for absent Earth Engine
credentials is a static city CSV, and that is what this loads. Every row is
stored with `is_measured=False` and a source saying it is a fallback, so nothing
downstream can mistake it for a satellite observation.

Idempotent: re-running updates rows in place.
"""

import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from satellite.hotspots import detect_hotspots
from satellite.models import NO2_UNIT, CityNo2

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "city_no2.csv"

SOURCE = (
    "STATIC FALLBACK, not a measurement. No Earth Engine or Sentinel-5P "
    "credentials are configured, so these order-of-magnitude values stand in for "
    "a real TROPOMI extract. The value is a tropospheric COLUMN density in "
    f"{NO2_UNIT}, not a surface concentration. Replace with a real extract before "
    "quoting any figure."
)


class Command(BaseCommand):
    help = "Load the static city NO2 fallback CSV and detect hotspots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv", type=Path, default=CSV_PATH, help=f"CSV to load (default: {CSV_PATH})."
        )
        parser.add_argument(
            "--no-detect", action="store_true", help="Skip hotspot detection."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        path: Path = options["csv"]
        if not path.exists():
            raise SystemExit(f"No CSV at {path}.")

        with path.open(encoding="utf-8") as handle:
            # Strip the provenance comment block before the header.
            rows = [line for line in handle if not line.startswith("#")]

        loaded = 0
        for row in csv.DictReader(rows):
            CityNo2.objects.update_or_create(
                city=row["city"],
                state=row["state"],
                defaults={
                    "latitude": Decimal(row["latitude"]),
                    "longitude": Decimal(row["longitude"]),
                    "no2_umol_per_m2": Decimal(row["no2_umol_per_m2"]),
                    "population_millions": Decimal(row["population_millions"])
                    if row.get("population_millions")
                    else None,
                    "source": SOURCE,
                    "is_measured": False,
                },
            )
            loaded += 1

        self.stdout.write(f"  loaded {loaded} cities from {path.name}")

        if not options["no_detect"]:
            result = detect_hotspots(persist=True)
            if result["status"] == "evaluated":
                names = [city.city for city in result["hotspots"]]
                self.stdout.write(
                    f"  hotspots: {len(names)} of {result['cities_considered']} "
                    f"({', '.join(names) if names else 'none'})"
                )
                self.stdout.write(
                    f"  threshold: NO2 above {result['threshold']['fence_umol_per_m2']} "
                    f"{NO2_UNIT} (median {result['threshold']['median_umol_per_m2']} + "
                    f"{result['threshold']['fence_sigmas']} robust sigma) AND an "
                    f"Isolation Forest outlier"
                )
            else:
                self.stdout.write(f"  hotspots: {result['reason']}")

        self.stdout.write(
            self.style.WARNING(
                f"All values are a STATIC FALLBACK, flagged is_measured=False.\n"
                f"  Units are {NO2_UNIT} of TROPOSPHERIC COLUMN - not surface ppb."
            )
        )
        self.stdout.write(self.style.SUCCESS(f"Seeded {loaded} city NO2 rows."))
