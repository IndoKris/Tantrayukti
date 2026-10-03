"""
Seed the five activity categories with emission factors.

**Every factor is an unverified published estimate**, flagged `is_verified=False`
with a `source` saying so. They are order-of-magnitude figures typical of public
datasets (DEFRA/IPCC-style per-km and per-meal factors), chosen so the categories
rank plausibly against each other - not values checked against a primary source
by this project. The plan forbids presenting invented or unchecked numbers as
authoritative, so the UI shows the source beside every total.

Idempotent: re-running updates the rows in place.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from activity.models import Category, EmissionFactorRow

UNVERIFIED = (
    "UNVERIFIED published estimate, order-of-magnitude only. Typical of public "
    "per-unit emission factor datasets; not checked against a primary source by "
    "this project. Replace with a cited factor before using any figure for "
    "reporting."
)

FACTORS = [
    # (category, key, label, unit, kg CO2e per unit)
    (Category.TRANSPORT, "car-petrol", "Car, petrol", "km", "0.17000"),
    (Category.TRANSPORT, "car-diesel", "Car, diesel", "km", "0.16000"),
    (Category.TRANSPORT, "motorcycle", "Motorcycle", "km", "0.10300"),
    (Category.TRANSPORT, "bus", "Bus", "km", "0.10200"),
    (Category.TRANSPORT, "train", "Train", "km", "0.04100"),
    (Category.TRANSPORT, "flight-short", "Flight, short haul", "km", "0.25500"),
    (Category.TRANSPORT, "walk-cycle", "Walking or cycling", "km", "0.00000"),
    (Category.HOME_ENERGY, "grid-electricity", "Grid electricity", "kWh", "0.82000"),
    (Category.HOME_ENERGY, "lpg-cylinder", "LPG cooking gas", "kg", "2.98300"),
    (Category.HOME_ENERGY, "diesel-generator", "Diesel generator", "kWh", "0.70000"),
    (Category.DIET, "meal-beef", "Meal with beef", "meals", "6.61000"),
    (Category.DIET, "meal-chicken", "Meal with chicken", "meals", "1.82000"),
    (Category.DIET, "meal-vegetarian", "Vegetarian meal", "meals", "0.89000"),
    (Category.DIET, "meal-vegan", "Vegan meal", "meals", "0.68000"),
    (Category.DIET, "dairy-milk", "Milk", "kg", "1.29000"),
    (Category.SHOPPING, "clothing-item", "Clothing item", "items", "12.00000"),
    (Category.SHOPPING, "electronics-small", "Small electronics", "items", "28.00000"),
    (Category.SHOPPING, "electronics-large", "Large appliance", "items", "350.00000"),
    (Category.SHOPPING, "paper-books", "Books and paper goods", "kg", "1.84000"),
    (Category.WASTE, "landfill-mixed", "Mixed waste to landfill", "kg", "0.58000"),
    (Category.WASTE, "recycled-mixed", "Mixed recycling", "kg", "0.02100"),
    (Category.WASTE, "composted", "Composted organic waste", "kg", "0.01000"),
    (Category.WASTE, "food-waste", "Food waste to landfill", "kg", "0.62600"),
]


class Command(BaseCommand):
    help = "Create or refresh the activity emission factors for all five categories."

    @transaction.atomic
    def handle(self, *args, **options):
        by_category: dict[str, int] = {}

        for category, key, label, unit, factor in FACTORS:
            EmissionFactorRow.objects.update_or_create(
                key=key,
                defaults={
                    "category": category,
                    "label": label,
                    "quantity_unit": unit,
                    "kg_co2_per_unit": Decimal(factor),
                    "source": UNVERIFIED,
                    "is_verified": False,
                    "is_active": True,
                },
            )
            by_category[category] = by_category.get(category, 0) + 1

        for category, label in Category.choices:
            self.stdout.write(f"  {label}: {by_category.get(category, 0)} factor(s)")

        self.stdout.write(
            self.style.WARNING(
                "All factors are UNVERIFIED published estimates, flagged "
                "is_verified=False.\n  Their source text is shown beside every "
                "figure computed from them."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {len(FACTORS)} factors across 5 categories.")
        )
