"""Admin registration for tariffs and emission factors."""

from django.contrib import admin

from billing.models import BillingSettings, EmissionFactor, Tariff, TariffSlab, TimeOfUseRate


class TariffSlabInline(admin.TabularInline):
    model = TariffSlab
    extra = 1
    fields = ["from_kwh", "to_kwh", "rate_inr_per_kwh", "label"]


class TimeOfUseRateInline(admin.TabularInline):
    model = TimeOfUseRate
    extra = 0
    fields = ["name", "start_hour", "end_hour", "multiplier"]


@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "organisation",
        "is_sample",
        "is_default",
        "is_active",
        "fixed_charge_inr_month",
        "tax_percent",
        "slab_count",
    ]
    list_filter = ["is_sample", "is_active", "is_default", "organisation"]
    search_fields = ["name", "source"]
    inlines = [TariffSlabInline, TimeOfUseRateInline]

    @admin.display(description="slabs")
    def slab_count(self, obj) -> int:
        return obj.slabs.count()


@admin.register(EmissionFactor)
class EmissionFactorAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "region",
        "kg_co2_per_kwh",
        "kind",
        "is_verified",
        "is_default",
        "valid_from",
    ]
    list_filter = ["kind", "is_verified", "is_default"]
    search_fields = ["name", "region", "source"]


@admin.register(BillingSettings)
class BillingSettingsAdmin(admin.ModelAdmin):
    list_display = ["organisation", "tariff", "emission_factor", "updated_at"]
    list_filter = ["organisation"]
