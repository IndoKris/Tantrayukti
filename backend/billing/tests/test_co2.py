"""
Tests for the CO2 engine.

The behaviour that matters as much as the arithmetic: **a CO2 figure must never
appear without naming where its factor came from.** The plan calls out the static
0.82 kg/kWh default specifically, so these tests pin the fallback, its source
text and its `is_verified=False` flag.
"""

from decimal import Decimal

from django.test import TestCase

from billing import engines
from billing.models import DEFAULT_KG_CO2_PER_KWH, EmissionFactor


class Co2ArithmeticTests(TestCase):
    def setUp(self):
        self.factor = EmissionFactor.objects.create(
            name="Test factor",
            kg_co2_per_kwh=Decimal("0.50000"),
            source="Test fixture",
            is_verified=True,
            is_default=True,
        )

    def test_co2_is_energy_times_factor(self):
        result = engines.estimate_co2(Decimal("100"), self.factor)
        self.assertEqual(result.kg_co2, Decimal("50.000"))

    def test_zero_energy_is_zero_co2(self):
        self.assertEqual(engines.estimate_co2(Decimal("0"), self.factor).kg_co2, Decimal("0"))

    def test_fractional_energy_is_not_rounded_away(self):
        result = engines.estimate_co2(Decimal("1.5"), self.factor)
        self.assertEqual(result.kg_co2, Decimal("0.750"))

    def test_the_formula_is_returned_for_display(self):
        payload = engines.estimate_co2(Decimal("100"), self.factor).as_dict()
        self.assertEqual(
            payload["formula"],
            "100.000000 kWh x 0.50000 kg CO2/kWh = 50.000000 kg CO2",
        )


class FactorProvenanceTests(TestCase):
    def test_a_supplied_factor_reports_its_own_metadata(self):
        factor = EmissionFactor.objects.create(
            name="CEA 2024",
            region="India (national grid)",
            kg_co2_per_kwh=Decimal("0.71000"),
            kind=EmissionFactor.Kind.STATIC,
            source="Checked against a primary source in this test",
            is_verified=True,
        )
        payload = engines.estimate_co2(Decimal("10"), factor).as_dict()["factor"]

        self.assertEqual(payload["name"], "CEA 2024")
        self.assertEqual(payload["kg_co2_per_kwh"], Decimal("0.71000"))
        self.assertTrue(payload["is_verified"])
        self.assertFalse(payload["is_fallback"])

    def test_with_no_factor_the_documented_default_is_used(self):
        result = engines.estimate_co2(Decimal("100"), None)
        self.assertEqual(result.kg_co2_per_kwh, DEFAULT_KG_CO2_PER_KWH)
        self.assertEqual(result.kg_co2_per_kwh, Decimal("0.82"))
        self.assertEqual(result.kg_co2, Decimal("82.00"))

    def test_the_fallback_is_marked_as_a_fallback(self):
        payload = engines.estimate_co2(Decimal("100"), None).as_dict()["factor"]
        self.assertTrue(payload["is_fallback"])

    def test_the_fallback_is_marked_unverified(self):
        """The plan requires the static default not to be presented as checked."""
        payload = engines.estimate_co2(Decimal("100"), None).as_dict()["factor"]
        self.assertFalse(payload["is_verified"])

    def test_the_fallback_source_names_the_value_and_how_to_check_it(self):
        source = engines.estimate_co2(Decimal("1"), None).as_dict()["factor"]["source"]
        self.assertIn("0.82", source)
        self.assertIn("CEA", source)
        self.assertIn("static", source.lower())

    def test_a_modelled_factor_declares_its_kind(self):
        """Phase 12 adds a random-forest factor; it must be distinguishable."""
        modelled = EmissionFactor.objects.create(
            name="RF hourly factor",
            kg_co2_per_kwh=Decimal("0.64000"),
            kind=EmissionFactor.Kind.MODELLED,
            source="Phase 12 random forest",
        )
        payload = engines.estimate_co2(Decimal("10"), modelled).as_dict()["factor"]
        self.assertEqual(payload["kind"], "modelled")


class FactorResolutionTests(TestCase):
    def test_resolve_returns_none_when_there_are_no_factors(self):
        self.assertIsNone(EmissionFactor.resolve())

    def test_resolve_prefers_the_default_factor(self):
        EmissionFactor.objects.create(
            name="Other", kg_co2_per_kwh=Decimal("0.5"), source="x"
        )
        default = EmissionFactor.objects.create(
            name="Default", kg_co2_per_kwh=Decimal("0.82"), source="y", is_default=True
        )
        self.assertEqual(EmissionFactor.resolve(), default)

    def test_resolve_honours_an_explicit_id(self):
        EmissionFactor.objects.create(
            name="Default", kg_co2_per_kwh=Decimal("0.82"), source="y", is_default=True
        )
        other = EmissionFactor.objects.create(
            name="Other", kg_co2_per_kwh=Decimal("0.5"), source="x"
        )
        self.assertEqual(EmissionFactor.resolve(factor_id=other.pk), other)

    def test_resolve_falls_back_to_any_factor_when_none_is_default(self):
        only = EmissionFactor.objects.create(
            name="Only", kg_co2_per_kwh=Decimal("0.5"), source="x"
        )
        self.assertEqual(EmissionFactor.resolve(), only)
