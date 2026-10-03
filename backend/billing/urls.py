"""Billing routes, mounted under /api/billing/ by config.urls."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from billing.views import (
    BillEstimateView,
    BillingSettingsViewSet,
    EmissionFactorViewSet,
    MonthProjectionView,
    TariffSlabViewSet,
    TariffViewSet,
    TimeOfUseRateViewSet,
)

app_name = "billing"

router = DefaultRouter()
router.register("tariffs", TariffViewSet, basename="tariff")
router.register("slabs", TariffSlabViewSet, basename="slab")
router.register("tou-rates", TimeOfUseRateViewSet, basename="tou-rate")
router.register("emission-factors", EmissionFactorViewSet, basename="emission-factor")
router.register("settings", BillingSettingsViewSet, basename="settings")

urlpatterns = [
    path("estimate/", BillEstimateView.as_view(), name="estimate"),
    path("projection/", MonthProjectionView.as_view(), name="projection"),
    path("", include(router.urls)),
]
