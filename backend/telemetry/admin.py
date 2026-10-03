"""Admin registration for devices and readings."""

from django.contrib import admin, messages

from telemetry.models import Device, Reading


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "room", "kind", "status", "last_seen_at", "token_prefix"]
    list_filter = ["kind", "is_active", "room__floor__building__organisation"]
    search_fields = ["name", "room__name", "firmware_version"]
    readonly_fields = [
        "token_prefix",
        "token_issued_at",
        "last_seen_at",
        "last_reading_at",
        "reported_buffer_count",
        "created_at",
        "updated_at",
    ]
    actions = ["rotate_tokens"]

    @admin.display(description="status")
    def status(self, obj) -> str:
        return obj.status

    @admin.action(description="Rotate the device token (invalidates the old one)")
    def rotate_tokens(self, request, queryset):
        """
        Rotate tokens and show the new ones once.

        Shown in a message because they cannot be recovered afterwards; only the
        hash is stored.
        """
        for device in queryset:
            raw = device.rotate_token()
            self.message_user(
                request,
                f"{device.name}: new token {raw} - copy it now, it will not be shown again.",
                level=messages.WARNING,
            )


@admin.register(Reading)
class ReadingAdmin(admin.ModelAdmin):
    list_display = [
        "timestamp",
        "device",
        "active_power_w",
        "energy_wh",
        "voltage_v",
        "current_a",
        "power_factor",
        "source",
        "was_buffered",
    ]
    list_filter = ["source", "was_buffered", "device"]
    date_hierarchy = "timestamp"
    # Readings are machine-written; the admin is for inspection only.
    readonly_fields = [field.name for field in Reading._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False
