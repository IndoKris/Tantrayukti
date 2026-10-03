"""
Serializers for device registration, status and reading ingestion.

Validation is deliberately strict: a bad reading that reaches the database
corrupts every rollup, cost estimate and anomaly score downstream, and is far
harder to find later than a 400 at the door.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from telemetry.models import BUFFERED_AFTER, Device, Reading

#: Clock skew allowed on a device timestamp before it is rejected as in the future.
MAX_CLOCK_SKEW = timedelta(minutes=5)

#: Oldest backfill accepted. Anything older is almost certainly a wrong clock.
MAX_BACKFILL_AGE = timedelta(days=90)

#: Active power may exceed V x A by this factor before the reading is rejected.
#: Real power cannot exceed apparent power; the margin absorbs rounding and
#: sensor error rather than permitting physically impossible values.
APPARENT_POWER_TOLERANCE = Decimal("1.10")


class ReadingInputSerializer(serializers.Serializer):
    """
    One incoming reading.

    `energy_wh` is optional: when the device omits it, it is derived from
    `active_power_w` over the device's sampling interval. The device is the
    better source when it can integrate properly, so a supplied value wins.
    """

    timestamp = serializers.DateTimeField()
    active_power_w = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0")
    )
    energy_wh = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("0"), required=False
    )
    voltage_v = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("500"),
        required=False,
        allow_null=True,
    )
    current_a = serializers.DecimalField(
        max_digits=8,
        decimal_places=3,
        min_value=Decimal("0"),
        max_value=Decimal("200"),
        required=False,
        allow_null=True,
    )
    power_factor = serializers.DecimalField(
        max_digits=4,
        decimal_places=3,
        min_value=Decimal("0"),
        max_value=Decimal("1"),
        required=False,
        allow_null=True,
    )
    source = serializers.ChoiceField(
        choices=Reading.Source.choices, required=False, default=Reading.Source.DEVICE
    )

    def validate_timestamp(self, value):
        now = timezone.now()
        if value > now + MAX_CLOCK_SKEW:
            raise serializers.ValidationError(
                "Timestamp is in the future; check the device clock."
            )
        if value < now - MAX_BACKFILL_AGE:
            raise serializers.ValidationError(
                f"Timestamp is older than the {MAX_BACKFILL_AGE.days}-day backfill limit."
            )
        return value

    def validate(self, attrs):
        voltage = attrs.get("voltage_v")
        current = attrs.get("current_a")
        power = attrs["active_power_w"]

        # Real power cannot exceed apparent power (V x A).
        if voltage is not None and current is not None:
            apparent = voltage * current
            if apparent > 0 and power > apparent * APPARENT_POWER_TOLERANCE:
                raise serializers.ValidationError(
                    {
                        "active_power_w": (
                            f"{power} W exceeds apparent power {apparent} VA "
                            f"(voltage x current); check the sensors."
                        )
                    }
                )
        return attrs


class ReadingBatchSerializer(serializers.Serializer):
    """
    A batch upload, as the ESP32 sends when flushing its flash buffer.

    `buffer_count` lets the device report how many samples it still holds, which
    the status endpoint surfaces without the server having to guess.
    """

    readings = ReadingInputSerializer(many=True, allow_empty=False)
    buffer_count = serializers.IntegerField(required=False, min_value=0)
    firmware_version = serializers.CharField(required=False, max_length=32)

    def validate_readings(self, value):
        timestamps = [row["timestamp"] for row in value]
        if len(set(timestamps)) != len(timestamps):
            raise serializers.ValidationError(
                "The batch contains duplicate timestamps for the same device."
            )
        return value


class ReadingSerializer(serializers.ModelSerializer):
    """Read representation of a stored reading."""

    energy_kwh = serializers.DecimalField(max_digits=12, decimal_places=6, read_only=True)

    class Meta:
        model = Reading
        fields = [
            "id",
            "device",
            "timestamp",
            "received_at",
            "voltage_v",
            "current_a",
            "power_factor",
            "active_power_w",
            "energy_wh",
            "energy_kwh",
            "source",
            "was_buffered",
        ]
        read_only_fields = fields


class DeviceSerializer(serializers.ModelSerializer):
    """
    Device with its digital-twin state.

    The token is never included - only its prefix, so a person can tell which
    credential a device holds without the credential being readable.
    """

    status = serializers.CharField(read_only=True)
    is_online = serializers.BooleanField(read_only=True)
    seconds_since_last_seen = serializers.IntegerField(read_only=True)
    buffered_count = serializers.SerializerMethodField()
    room_name = serializers.CharField(source="room.name", read_only=True)
    organisation_id = serializers.PrimaryKeyRelatedField(
        source="organisation", read_only=True
    )
    reading_count = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            "id",
            "room",
            "room_name",
            "organisation_id",
            "name",
            "kind",
            "is_active",
            "sample_interval_seconds",
            "firmware_version",
            "token_prefix",
            "token_issued_at",
            "status",
            "is_online",
            "last_seen_at",
            "last_reading_at",
            "seconds_since_last_seen",
            "reported_buffer_count",
            "buffered_count",
            "reading_count",
            "created_at",
        ]
        read_only_fields = [
            "token_prefix",
            "token_issued_at",
            "last_seen_at",
            "last_reading_at",
            "reported_buffer_count",
            "created_at",
        ]

    def get_buffered_count(self, device: Device) -> int:
        """Readings in the last 24 h that the server saw arrive late."""
        return device.buffered_reading_count()

    def get_reading_count(self, device: Device) -> int:
        return device.readings.count()


class DeviceCreateSerializer(DeviceSerializer):
    """
    Device creation, which returns the raw token exactly once.

    `token` appears only in this response. It is not stored in recoverable form,
    so if it is lost the device needs a rotation rather than a lookup.
    """

    token = serializers.SerializerMethodField()

    class Meta(DeviceSerializer.Meta):
        fields = DeviceSerializer.Meta.fields + ["token"]

    def get_token(self, device: Device) -> str | None:
        return getattr(device, "_raw_token", None)
