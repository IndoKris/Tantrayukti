"""Insights routes, mounted under /api/ by config.urls."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from insights.forecast_views import DeviceForecastView, MlMetricsView
from insights.views import (
    AnomalyViewSet,
    DemoFaultView,
    DetectView,
    PeriodComparisonView,
    SpaceComparisonView,
)

app_name = "insights"

router = DefaultRouter()
router.register("anomalies", AnomalyViewSet, basename="anomaly")

urlpatterns = [
    path("forecast/<int:device_id>/", DeviceForecastView.as_view(), name="device-forecast"),
    path("ml/metrics/", MlMetricsView.as_view(), name="ml-metrics"),
    # Registered before the router so it is not shadowed by the detail route.
    path("anomalies/detect/", DetectView.as_view(), name="anomaly-detect"),
    path("compare/spaces/", SpaceComparisonView.as_view(), name="compare-spaces"),
    path("compare/periods/", PeriodComparisonView.as_view(), name="compare-periods"),
    path("demo/inject-fault/", DemoFaultView.as_view(), name="demo-inject-fault"),
    path("", include(router.urls)),
]
