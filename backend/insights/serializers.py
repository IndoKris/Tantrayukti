"""Serializers for the insights API."""

from rest_framework import serializers

from insights.models import Anomaly


class AnomalySerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device.name", read_only=True)
    room_name = serializers.CharField(source="device.room.name", read_only=True)
    organisation_id = serializers.PrimaryKeyRelatedField(
        source="organisation", read_only=True
    )
    detector_display = serializers.CharField(source="get_detector_display", read_only=True)
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    acknowledged_by_username = serializers.CharField(
        source="acknowledged_by.username", read_only=True, default=None
    )
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Anomaly
        fields = [
            "id",
            "device",
            "device_name",
            "room_name",
            "organisation_id",
            "detector",
            "detector_display",
            "severity",
            "severity_display",
            "window_start",
            "window_end",
            "observed_kwh",
            "expected_kwh",
            "excess_kwh",
            "score",
            "title",
            "evidence",
            "state",
            "state_display",
            "is_open",
            "acknowledged_by_username",
            "acknowledged_at",
            "resolved_at",
            "resolution_note",
            "created_at",
        ]
        read_only_fields = fields
