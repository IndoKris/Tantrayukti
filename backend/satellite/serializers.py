"""Serializers for the satellite module."""

from rest_framework import serializers

from satellite.models import NO2_UNIT, NO2_UNIT_NOTE, CityNo2, CommunityPoint


class CityNo2Serializer(serializers.ModelSerializer):
    unit = serializers.SerializerMethodField()
    unit_note = serializers.SerializerMethodField()

    class Meta:
        model = CityNo2
        fields = [
            "id",
            "city",
            "state",
            "latitude",
            "longitude",
            "no2_umol_per_m2",
            "unit",
            "unit_note",
            "population_millions",
            "observed_on",
            "source",
            "is_measured",
            "anomaly_score",
            "is_hotspot",
            "hotspot_note",
        ]
        read_only_fields = fields

    def get_unit(self, obj) -> str:
        return NO2_UNIT

    def get_unit_note(self, obj) -> str:
        return NO2_UNIT_NOTE


class CommunityPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommunityPoint
        fields = [
            "id",
            "latitude",
            "longitude",
            "label",
            "building_count",
            "total_kwh",
            "total_area_sqm",
            "kwh_per_sqm",
            "window_start",
            "window_end",
            "computed_at",
        ]
        read_only_fields = fields
