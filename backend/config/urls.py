"""Root URL configuration for the EcoTrack backend.

Feature apps are mounted under /api/ by their own phases; this file stays the
single place where those includes are registered.
"""

from django.contrib import admin
from django.urls import include, path

from config.views import HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("accounts.urls")),
    path("api/spaces/", include("spaces.urls")),
    path("api/", include("telemetry.urls")),
    # Later phases add billing and insights routes here.
]
