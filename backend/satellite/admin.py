"""Admin registration for the satellite module."""

from django.contrib import admin

from satellite.models import CityNo2, CommunityPoint


@admin.register(CityNo2)
class CityNo2Admin(admin.ModelAdmin):
    list_display = ["city", "state", "no2_umol_per_m2", "is_hotspot", "is_measured", "anomaly_score"]
    list_filter = ["is_hotspot", "is_measured", "state"]
    search_fields = ["city", "state"]
    readonly_fields = ["anomaly_score", "is_hotspot", "hotspot_note", "updated_at"]


@admin.register(CommunityPoint)
class CommunityPointAdmin(admin.ModelAdmin):
    list_display = ["label", "latitude", "longitude", "building_count", "total_kwh", "kwh_per_sqm"]
    readonly_fields = ["computed_at"]
