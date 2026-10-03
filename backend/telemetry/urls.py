"""Telemetry routes, mounted under /api/ by config.urls."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from telemetry.views import DeviceViewSet, ReadingIngestView, UsageView

app_name = "telemetry"

router = DefaultRouter()
router.register("devices", DeviceViewSet, basename="device")

urlpatterns = [
    # Device-token authenticated ingestion. Kept at a flat, stable path because
    # it is baked into the ESP32 firmware in Phase 24.
    path("readings/", ReadingIngestView.as_view(), name="reading-ingest"),
    path("usage/", UsageView.as_view(), name="usage"),
    path("", include(router.urls)),
]
