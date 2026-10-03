"""Activity routes, mounted under /api/activity/ by config.urls."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from activity.views import (
    ActivityEntryViewSet,
    ActivityReportView,
    EmissionFactorRowViewSet,
    MonthlyBudgetView,
    activity_csv,
)

app_name = "activity"

router = DefaultRouter()
router.register("entries", ActivityEntryViewSet, basename="entry")
router.register("factors", EmissionFactorRowViewSet, basename="factor")

urlpatterns = [
    path("report/", ActivityReportView.as_view(), name="report"),
    path("report.csv", activity_csv, name="report-csv"),
    path("budget/", MonthlyBudgetView.as_view(), name="budget"),
    path("", include(router.urls)),
]
