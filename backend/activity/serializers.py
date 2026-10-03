"""Serializers for activity logging."""

from rest_framework import serializers

from activity.models import ActivityEntry, Category, EmissionFactorRow, MonthlyBudget


class EmissionFactorRowSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = EmissionFactorRow
        fields = [
            "id",
            "category",
            "category_display",
            "key",
            "label",
            "quantity_unit",
            "kg_co2_per_unit",
            "source",
            "is_verified",
        ]
        read_only_fields = fields


class ActivityEntrySerializer(serializers.ModelSerializer):
    category = serializers.CharField(read_only=True)
    category_display = serializers.CharField(
        source="factor.get_category_display", read_only=True
    )
    factor_label = serializers.CharField(source="factor.label", read_only=True)
    quantity_unit = serializers.CharField(source="factor.quantity_unit", read_only=True)
    factor_source = serializers.CharField(source="factor.source", read_only=True)
    formula = serializers.CharField(read_only=True)

    class Meta:
        model = ActivityEntry
        fields = [
            "id",
            "factor",
            "factor_label",
            "category",
            "category_display",
            "quantity",
            "quantity_unit",
            "occurred_on",
            "note",
            "kg_co2",
            "factor_snapshot",
            "factor_source",
            "formula",
            "is_verified",
            "created_at",
        ]
        read_only_fields = [
            "kg_co2",
            "factor_snapshot",
            "is_verified",
            "created_at",
        ]

    def validate_factor(self, value):
        if not value.is_active:
            raise serializers.ValidationError("That activity type is no longer available.")
        return value

    def validate_occurred_on(self, value):
        from django.utils import timezone

        if value > timezone.localdate():
            raise serializers.ValidationError("Cannot log an activity in the future.")
        return value


class MonthlyBudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonthlyBudget
        fields = ["id", "kg_co2_per_month", "updated_at"]
        read_only_fields = ["updated_at"]
