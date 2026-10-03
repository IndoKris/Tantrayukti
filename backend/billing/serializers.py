"""Serializers for tariffs and emission factors."""

from rest_framework import serializers

from billing.models import BillingSettings, EmissionFactor, Tariff, TariffSlab, TimeOfUseRate


class TariffSlabSerializer(serializers.ModelSerializer):
    class Meta:
        model = TariffSlab
        fields = ["id", "tariff", "from_kwh", "to_kwh", "rate_inr_per_kwh", "label"]


class TimeOfUseRateSerializer(serializers.ModelSerializer):
    window = serializers.SerializerMethodField()

    class Meta:
        model = TimeOfUseRate
        fields = ["id", "tariff", "name", "start_hour", "end_hour", "multiplier", "window"]

    def get_window(self, obj) -> str:
        return f"{obj.start_hour:02d}:00-{obj.end_hour:02d}:00"

    def validate(self, attrs):
        start = attrs.get("start_hour", getattr(self.instance, "start_hour", None))
        end = attrs.get("end_hour", getattr(self.instance, "end_hour", None))
        if start is not None and not 0 <= start <= 23:
            raise serializers.ValidationError({"start_hour": "Must be between 0 and 23."})
        if end is not None and not 1 <= end <= 24:
            raise serializers.ValidationError({"end_hour": "Must be between 1 and 24."})
        if start is not None and end is not None and start == end:
            raise serializers.ValidationError(
                "start_hour and end_hour cannot be equal; that is a zero-length window."
            )
        return attrs


class TariffSerializer(serializers.ModelSerializer):
    slabs = TariffSlabSerializer(many=True, read_only=True)
    tou_rates = TimeOfUseRateSerializer(many=True, read_only=True)

    class Meta:
        model = Tariff
        fields = [
            "id",
            "name",
            "organisation",
            "currency",
            "fixed_charge_inr_month",
            "tax_percent",
            "is_sample",
            "source",
            "effective_from",
            "is_active",
            "is_default",
            "slabs",
            "tou_rates",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class EmissionFactorSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmissionFactor
        fields = [
            "id",
            "name",
            "region",
            "kg_co2_per_kwh",
            "kind",
            "source",
            "is_verified",
            "is_default",
            "valid_from",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class BillingSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingSettings
        fields = ["id", "organisation", "tariff", "emission_factor", "updated_at"]
        read_only_fields = ["updated_at"]
