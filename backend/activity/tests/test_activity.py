"""Tests for activity logging, reports and the CSV export."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from activity.models import ActivityEntry, Category, EmissionFactorRow, MonthlyBudget

User = get_user_model()


class ActivityTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_activity_factors", stdout=StringIO(), stderr=StringIO())
        cls.user = User.objects.create_user(
            username="logger", email="l@example.com", password="pw"
        )
        cls.other = User.objects.create_user(
            username="other", email="o@example.com", password="pw"
        )
        cls.car = EmissionFactorRow.objects.get(key="car-petrol")
        cls.beef = EmissionFactorRow.objects.get(key="meal-beef")

    def log(self, factor=None, quantity="100", days_ago=0, user=None):
        return ActivityEntry.objects.create(
            user=user or self.user,
            factor=factor or self.car,
            quantity=Decimal(quantity),
            occurred_on=timezone.localdate() - timedelta(days=days_ago),
        )


class SeedTests(ActivityTestCase):
    def test_all_five_categories_have_factors(self):
        for value, _ in Category.choices:
            self.assertTrue(
                EmissionFactorRow.objects.filter(category=value).exists(), value
            )

    def test_every_factor_is_flagged_unverified_with_a_source(self):
        """The plan forbids presenting unchecked numbers as authoritative."""
        for factor in EmissionFactorRow.objects.all():
            self.assertFalse(factor.is_verified, factor.key)
            self.assertIn("UNVERIFIED", factor.source)

    def test_re_running_the_seed_is_idempotent(self):
        before = EmissionFactorRow.objects.count()
        call_command("seed_activity_factors", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(EmissionFactorRow.objects.count(), before)

    def test_diet_factors_rank_plausibly(self):
        beef = EmissionFactorRow.objects.get(key="meal-beef").kg_co2_per_unit
        vegan = EmissionFactorRow.objects.get(key="meal-vegan").kg_co2_per_unit
        self.assertGreater(beef, vegan)


class EntryTests(ActivityTestCase):
    def test_co2_is_computed_from_quantity_and_factor(self):
        entry = self.log(quantity="100")  # 100 km x 0.17 = 17 kg
        self.assertEqual(entry.kg_co2, Decimal("17.0000"))

    def test_the_factor_is_snapshotted_at_entry_time(self):
        """A later factor correction must not rewrite history."""
        entry = self.log(quantity="100")
        self.assertEqual(entry.factor_snapshot, Decimal("0.17000"))

        self.car.kg_co2_per_unit = Decimal("0.50000")
        self.car.save()
        entry.refresh_from_db()

        self.assertEqual(entry.factor_snapshot, Decimal("0.17000"))
        self.assertEqual(entry.kg_co2, Decimal("17.0000"))

    def test_entries_are_always_unverified(self):
        """Self-reported data is not evidence the way metered telemetry is."""
        self.assertFalse(self.log().is_verified)

    def test_the_formula_is_exposed_for_audit(self):
        entry = self.log(quantity="100")
        self.assertEqual(
            entry.formula, "100.000 km x 0.17000 kg CO2e/km = 17.0000 kg CO2e"
        )

    def test_the_category_comes_from_the_factor(self):
        self.assertEqual(self.log().category, Category.TRANSPORT)


class EntryApiTests(ActivityTestCase):
    def setUp(self):
        self.url = reverse("activity:entry-list")

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_a_user_can_log_an_entry(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            {
                "factor": self.beef.pk,
                "quantity": "3",
                "occurred_on": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Decimal(response.json()["kg_co2"]), Decimal("19.8300"))

    def test_the_response_carries_the_formula_and_factor_source(self):
        self.client.force_authenticate(self.user)
        body = self.client.post(
            self.url,
            {
                "factor": self.car.pk,
                "quantity": "10",
                "occurred_on": timezone.localdate().isoformat(),
            },
        ).json()
        self.assertIn("formula", body)
        self.assertIn("UNVERIFIED", body["factor_source"])

    def test_a_future_date_is_rejected(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            {
                "factor": self.car.pk,
                "quantity": "10",
                "occurred_on": (timezone.localdate() + timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_a_negative_quantity_is_rejected(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            {
                "factor": self.car.pk,
                "quantity": "-5",
                "occurred_on": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_entries_are_private_to_their_owner(self):
        """A travel or diet log is personal data, stricter than org scoping."""
        mine = self.log()
        theirs = self.log(user=self.other)

        self.client.force_authenticate(self.user)
        ids = [row["id"] for row in self.client.get(self.url).json()["results"]]

        self.assertIn(mine.pk, ids)
        self.assertNotIn(theirs.pk, ids)

    def test_an_entry_of_another_user_cannot_be_read(self):
        theirs = self.log(user=self.other)
        self.client.force_authenticate(self.user)
        response = self.client.get(reverse("activity:entry-detail", args=[theirs.pk]))
        self.assertEqual(response.status_code, 404)

    def test_filtering_by_category_works(self):
        self.log(factor=self.car)
        self.log(factor=self.beef)
        self.client.force_authenticate(self.user)

        body = self.client.get(self.url, {"category": "diet"}).json()
        self.assertEqual(body["count"], 1)

    def test_factors_are_readable_but_not_writable(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(reverse("activity:factor-list")).status_code, 200)
        self.assertEqual(
            self.client.post(reverse("activity:factor-list"), {"key": "x"}).status_code, 405
        )


class ReportTests(ActivityTestCase):
    def setUp(self):
        self.url = reverse("activity:report")
        self.log(factor=self.car, quantity="100")  # 17 kg transport
        self.log(factor=self.beef, quantity="10")  # 66.1 kg diet
        self.client.force_authenticate(self.user)

    def test_the_report_totals_every_category(self):
        body = self.client.get(self.url).json()
        self.assertEqual(Decimal(body["total_kg_co2"]), Decimal("83.1000"))
        self.assertEqual(body["entry_count"], 2)

    def test_categories_are_ranked_by_emissions(self):
        body = self.client.get(self.url).json()
        self.assertEqual(body["categories"][0]["category"], "diet")
        self.assertEqual(body["categories"][1]["category"], "transport")

    def test_all_five_categories_appear_even_when_empty(self):
        body = self.client.get(self.url).json()
        self.assertEqual(len(body["categories"]), 5)

    def test_each_category_lists_its_factor_sources(self):
        body = self.client.get(self.url).json()
        diet = next(row for row in body["categories"] if row["category"] == "diet")
        self.assertTrue(diet["factor_sources"])

    def test_top_emitters_are_listed_with_their_formulas(self):
        body = self.client.get(self.url).json()
        self.assertEqual(body["top_emitters"][0]["label"], "Meal with beef")
        self.assertIn("formula", body["top_emitters"][0])

    def test_budget_versus_usage_is_reported(self):
        MonthlyBudget.objects.create(user=self.user, kg_co2_per_month=Decimal("100.00"))
        body = self.client.get(self.url).json()

        self.assertEqual(Decimal(body["budget"]["used_kg_co2"]), Decimal("83.1000"))
        self.assertEqual(Decimal(body["budget"]["remaining_kg_co2"]), Decimal("16.9000"))
        self.assertFalse(body["budget"]["over_budget"])

    def test_going_over_budget_is_flagged(self):
        MonthlyBudget.objects.create(user=self.user, kg_co2_per_month=Decimal("50.00"))
        body = self.client.get(self.url).json()
        self.assertTrue(body["budget"]["over_budget"])

    def test_no_budget_yields_null_rather_than_a_guess(self):
        self.assertIsNone(self.client.get(self.url).json()["budget"])

    def test_the_report_states_that_entries_are_self_reported(self):
        caveats = self.client.get(self.url).json()["caveats"]
        self.assertTrue(any("Self-reported" in caveat for caveat in caveats))
        self.assertTrue(any("estimates, not measurements" in caveat for caveat in caveats))

    def test_a_reversed_window_is_a_400(self):
        response = self.client.get(self.url, {"from": "2026-03-10", "to": "2026-03-01"})
        self.assertEqual(response.status_code, 400)

    def test_a_malformed_date_is_a_400(self):
        response = self.client.get(self.url, {"from": "last tuesday"})
        self.assertEqual(response.status_code, 400)

    def test_entries_of_another_user_are_not_counted(self):
        self.log(factor=self.beef, quantity="1000", user=self.other)
        body = self.client.get(self.url).json()
        self.assertEqual(Decimal(body["total_kg_co2"]), Decimal("83.1000"))


class CsvExportTests(ActivityTestCase):
    def setUp(self):
        self.log(factor=self.car, quantity="100")
        self.client.force_authenticate(self.user)

    def test_the_export_is_csv(self):
        response = self.client.get(reverse("activity:report-csv"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_the_export_includes_the_formula_and_source(self):
        """An export of bare totals would not be auditable."""
        body = self.client.get(reverse("activity:report-csv")).content.decode()
        self.assertIn("formula", body)
        self.assertIn("factor_source", body)
        self.assertIn("100.000 km x 0.17000", body)

    def test_the_export_marks_entries_unverified(self):
        body = self.client.get(reverse("activity:report-csv")).content.decode()
        self.assertIn("false", body)

    def test_the_export_only_contains_the_entries_of_the_caller(self):
        self.log(factor=self.beef, quantity="99", user=self.other)
        body = self.client.get(reverse("activity:report-csv")).content.decode()
        self.assertNotIn("Meal with beef", body)


class BudgetApiTests(ActivityTestCase):
    def setUp(self):
        self.url = reverse("activity:budget")
        self.client.force_authenticate(self.user)

    def test_no_budget_reports_null(self):
        self.assertIsNone(self.client.get(self.url).json()["kg_co2_per_month"])

    def test_a_budget_can_be_set_and_read_back(self):
        response = self.client.put(self.url, {"kg_co2_per_month": "120.50"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            Decimal(self.client.get(self.url).json()["kg_co2_per_month"]),
            Decimal("120.50"),
        )

    def test_a_budget_can_be_updated(self):
        self.client.put(self.url, {"kg_co2_per_month": "120.50"})
        self.client.put(self.url, {"kg_co2_per_month": "90.00"})
        self.assertEqual(MonthlyBudget.objects.filter(user=self.user).count(), 1)

    def test_a_negative_budget_is_rejected(self):
        self.assertEqual(
            self.client.put(self.url, {"kg_co2_per_month": "-5"}).status_code, 400
        )
