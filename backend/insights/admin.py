"""Admin registration for anomalies."""

from django.contrib import admin

from insights.models import Anomaly


@admin.register(Anomaly)
class AnomalyAdmin(admin.ModelAdmin):
    list_display = ["title", "device", "detector", "severity", "state", "window_start"]
    list_filter = ["state", "severity", "detector", "device__room__floor__building__organisation"]
    search_fields = ["title", "device__name"]
    date_hierarchy = "window_start"
    readonly_fields = ["evidence", "created_at", "updated_at"]
