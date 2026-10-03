"""Admin registration for activity logging."""

from django.contrib import admin

from activity.models import ActivityEntry, EmissionFactorRow, MonthlyBudget


@admin.register(EmissionFactorRow)
class EmissionFactorRowAdmin(admin.ModelAdmin):
    list_display = ["label", "category", "kg_co2_per_unit", "quantity_unit", "is_verified", "is_active"]
    list_filter = ["category", "is_verified", "is_active"]
    search_fields = ["label", "key", "source"]


@admin.register(ActivityEntry)
class ActivityEntryAdmin(admin.ModelAdmin):
    list_display = ["occurred_on", "user", "factor", "quantity", "kg_co2", "is_verified"]
    list_filter = ["factor__category", "user"]
    date_hierarchy = "occurred_on"
    readonly_fields = ["kg_co2", "factor_snapshot", "is_verified", "created_at", "updated_at"]


@admin.register(MonthlyBudget)
class MonthlyBudgetAdmin(admin.ModelAdmin):
    list_display = ["user", "kg_co2_per_month", "updated_at"]
