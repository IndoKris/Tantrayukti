"""
Activity logging API and reports.

Entries are **private to the user who logged them**: `get_queryset` filters to
`request.user`, so there is no way to read or edit someone else's log. That is
stricter than the organisation scoping elsewhere in the project, because a diet
or travel log is personal data rather than building data.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from activity.models import ActivityEntry, Category, EmissionFactorRow, MonthlyBudget
from activity.serializers import (
    ActivityEntrySerializer,
    EmissionFactorRowSerializer,
    MonthlyBudgetSerializer,
)


class EmissionFactorRowViewSet(viewsets.ReadOnlyModelViewSet):
    """
    /api/activity/factors/

    The activity types available to log, with their factors and sources.
    Read-only: corrections go through the admin or the seed command, so a factor
    cannot be edited by whoever happens to be logging against it.
    """

    serializer_class = EmissionFactorRowSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = EmissionFactorRow.objects.filter(is_active=True)
        if category := self.request.query_params.get("category"):
            queryset = queryset.filter(category=category)
        return queryset


class ActivityEntryViewSet(viewsets.ModelViewSet):
    """
    /api/activity/entries/

    Full CRUD over the caller's own entries. Filter with `?category=`,
    `?from=`, `?to=`.
    """

    serializer_class = ActivityEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = ActivityEntry.objects.filter(user=self.request.user).select_related(
            "factor"
        )
        params = self.request.query_params
        if category := params.get("category"):
            queryset = queryset.filter(factor__category=category)
        if start := params.get("from"):
            queryset = queryset.filter(occurred_on__gte=start)
        if end := params.get("to"):
            queryset = queryset.filter(occurred_on__lte=end)
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


def month_bounds(reference: date | None = None) -> tuple[date, date]:
    """First and last day of the local month containing `reference`."""
    today = reference or timezone.localdate()
    first = today.replace(day=1)
    next_first = (first + timedelta(days=31)).replace(day=1)
    return first, next_first - timedelta(days=1)


def build_report(user, start: date, end: date) -> dict:
    """
    Category totals, top emitters and budget position for a window.

    Every figure carries the factor sources behind it, so a reader can trace a
    category total back to the published estimates it came from.
    """
    entries = (
        ActivityEntry.objects.filter(user=user, occurred_on__gte=start, occurred_on__lte=end)
        .select_related("factor")
        .order_by("-kg_co2")
    )

    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: dict[str, int] = defaultdict(int)
    sources: dict[str, set[str]] = defaultdict(set)

    for entry in entries:
        totals[entry.category] += entry.kg_co2
        counts[entry.category] += 1
        sources[entry.category].add(entry.factor.source)

    total_kg = sum(totals.values(), Decimal("0"))

    categories = [
        {
            "category": value,
            "label": label,
            "kg_co2": totals.get(value, Decimal("0")).quantize(Decimal("0.0001")),
            "entry_count": counts.get(value, 0),
            "share_percent": (
                (totals.get(value, Decimal("0")) / total_kg * 100).quantize(Decimal("0.01"))
                if total_kg > 0
                else None
            ),
            "factor_sources": sorted(sources.get(value, set())),
        }
        for value, label in Category.choices
    ]
    categories.sort(key=lambda row: row["kg_co2"], reverse=True)

    budget = MonthlyBudget.objects.filter(user=user).first()
    budget_block = None
    if budget:
        remaining = Decimal(budget.kg_co2_per_month) - total_kg
        budget_block = {
            "kg_co2_per_month": budget.kg_co2_per_month,
            "used_kg_co2": total_kg.quantize(Decimal("0.0001")),
            "remaining_kg_co2": remaining.quantize(Decimal("0.0001")),
            "used_percent": (
                (total_kg / Decimal(budget.kg_co2_per_month) * 100).quantize(Decimal("0.01"))
                if budget.kg_co2_per_month > 0
                else None
            ),
            "over_budget": bool(remaining < 0),
        }

    return {
        "window": {"from": start, "to": end},
        "total_kg_co2": total_kg.quantize(Decimal("0.0001")),
        "entry_count": entries.count(),
        "categories": categories,
        "top_emitters": [
            {
                "id": entry.pk,
                "label": entry.factor.label,
                "category": entry.category,
                "occurred_on": entry.occurred_on,
                "quantity": entry.quantity,
                "quantity_unit": entry.factor.quantity_unit,
                "kg_co2": entry.kg_co2,
                "formula": entry.formula,
            }
            for entry in entries[:10]
        ],
        "budget": budget_block,
        "caveats": [
            "Self-reported entries. Every one is tagged is_verified=false and is "
            "excluded from the Phase 21 leaderboard, unlike metered telemetry.",
            "Emission factors are published estimates, not measurements of your "
            "own activity. Each category lists the sources behind its total.",
            "A figure is computed with the factor in force when the entry was "
            "logged, so correcting a factor later does not rewrite history.",
        ],
    }


class ActivityReportView(APIView):
    """
    GET /api/activity/report/

    Category totals, top emitters and budget position. Defaults to the current
    local month; override with `?from=` and `?to=`.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        default_start, default_end = month_bounds()
        try:
            start = (
                date.fromisoformat(request.query_params["from"])
                if "from" in request.query_params
                else default_start
            )
            end = (
                date.fromisoformat(request.query_params["to"])
                if "to" in request.query_params
                else default_end
            )
        except ValueError as error:
            return Response(
                {"detail": f"from and to must be ISO dates (YYYY-MM-DD): {error}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if start > end:
            return Response(
                {"detail": "'from' must not be after 'to'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(build_report(request.user, start, end))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def activity_csv(request):
    """
    GET /api/activity/report.csv

    The caller's own entries as CSV, including the formula column so the export
    is auditable rather than a bare total.
    """
    entries = (
        ActivityEntry.objects.filter(user=request.user)
        .select_related("factor")
        .order_by("occurred_on")
    )

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ecotrack-activity.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "occurred_on",
            "category",
            "activity",
            "quantity",
            "quantity_unit",
            "kg_co2e_per_unit",
            "kg_co2e",
            "formula",
            "is_verified",
            "factor_source",
            "note",
        ]
    )
    for entry in entries:
        writer.writerow(
            [
                entry.occurred_on.isoformat(),
                entry.category,
                entry.factor.label,
                entry.quantity,
                entry.factor.quantity_unit,
                entry.factor_snapshot,
                entry.kg_co2,
                entry.formula,
                "false",
                entry.factor.source,
                entry.note,
            ]
        )

    return response


class MonthlyBudgetView(APIView):
    """GET/PUT /api/activity/budget/ - the caller's own monthly CO2e budget."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        budget = MonthlyBudget.objects.filter(user=request.user).first()
        if budget is None:
            return Response({"kg_co2_per_month": None, "detail": "No budget set."})
        return Response(MonthlyBudgetSerializer(budget).data)

    def put(self, request):
        budget = MonthlyBudget.objects.filter(user=request.user).first()
        serializer = MonthlyBudgetSerializer(budget, data=request.data, partial=budget is None)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data)
