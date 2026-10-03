"""
Cost and CO2 endpoints.

Energy comes from the Phase 8 rollups, which means billing inherits the
`metering=auto` guard against double counting a mains meter together with the
appliance meters beneath it. Billing a doubled kWh figure would double every
rupee and every kilogram of CO2, so this reuse is deliberate rather than
incidental.
"""

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsManagerOrAbove
from billing import engines, ml_factors
from billing.models import BillingSettings, EmissionFactor, Tariff, TariffSlab, TimeOfUseRate
from billing.serializers import (
    BillingSettingsSerializer,
    EmissionFactorSerializer,
    TariffSerializer,
    TariffSlabSerializer,
    TimeOfUseRateSerializer,
)
from spaces.models import Organisation
from telemetry import rollups
from telemetry.views import local_iso


class ReadAnyMemberWriteManager(IsAuthenticated):
    """Safe methods: any authenticated user. Writes: manager or above."""

    message = IsManagerOrAbove.message

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        return IsManagerOrAbove().has_permission(request, view)


def visible_organisations(request):
    if request.user.is_superuser:
        return Organisation.objects.all()
    return Organisation.objects.filter(memberships__user=request.user)


class _ScopedEnergyView(APIView):
    """Shared scope/energy resolution for the estimate and projection endpoints."""

    permission_classes = [IsAuthenticated]

    def resolve(self, request, params=None, period="hour"):
        """
        Resolve scope, tariff, emission factor and energy for the request.

        `params` defaults to the query string; the projection endpoint passes an
        overridden mapping so it can force a month-to-date window without
        mutating the underlying request.

        Returns `(context, None)` on success or `(None, error_response)`.
        """
        params = request.query_params if params is None else params
        try:
            rollups.validate_period(period)
            scope = rollups.resolve_scope(params, visible_organisations(request))
            devices, metering = rollups.select_devices(
                scope.devices, params.get("metering", "auto")
            )
            start, end = rollups.resolve_window(params, period)
        except rollups.ScopeError as error:
            return None, Response(
                {"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST
            )

        organisation = self._scope_organisation(scope)
        settings_row = (
            BillingSettings.objects.filter(organisation=organisation).first()
            if organisation
            else None
        )

        tariff = Tariff.resolve(
            organisation=organisation,
            tariff_id=params.get("tariff") or (settings_row.tariff_id if settings_row else None),
        )
        factor = EmissionFactor.resolve(
            factor_id=params.get("emission_factor")
            or (settings_row.emission_factor_id if settings_row else None)
        )

        readings = rollups.readings_for(devices, start, end)
        series = rollups.time_series(readings, "hour")
        totals = rollups.totals(readings)

        return {
            "scope": scope,
            "devices": devices,
            "metering": metering,
            "metering_requested": params.get("metering", "auto"),
            "start": start,
            "end": end,
            "tariff": tariff,
            "factor": factor,
            "series": series,
            "totals": totals,
            "total_kwh": Decimal(totals["energy_kwh"]),
            "hourly_kwh": engines.hourly_kwh_from_series(series),
        }, None

    @staticmethod
    def _scope_organisation(scope):
        """The organisation a scope belongs to, when it maps to exactly one."""
        first = scope.devices.first()
        return first.room.organisation if first else None

    @staticmethod
    def energy_block(context) -> dict:
        return {
            "scope": context["scope"].as_dict(),
            "window": {
                "from": local_iso(context["start"]),
                "to": local_iso(context["end"]),
            },
            "metering": {
                "requested": context["metering_requested"],
                "applied": context["metering"],
                "device_count": context["devices"].count(),
                "note": (
                    "A whole-space mains meter supersedes the appliance meters "
                    "beneath it; summing both would double count energy, cost and CO2."
                ),
            },
            "energy": {
                "total_kwh": context["totals"]["energy_kwh"],
                "peak_power_w": context["totals"]["peak_power_w"],
                "sample_count": context["totals"]["sample_count"],
                "first_reading_at": local_iso(context["totals"]["first_reading_at"]),
                "last_reading_at": local_iso(context["totals"]["last_reading_at"]),
            },
        }


class BillEstimateView(_ScopedEnergyView):
    """
    GET /api/billing/estimate/

    Cost and CO2 for a window. Takes the same scope and window parameters as
    `/api/usage/`, plus `tariff=<id>` and `emission_factor=<id>`.

    `include_fixed_charge` defaults to false for windows shorter than 28 days,
    because charging a full month's standing charge for three days would
    overstate the cost. Pass `fixed_charge=true|false` to force it either way.
    """

    def get(self, request):
        context, error = self.resolve(request)
        if error:
            return error

        window_days = (context["end"] - context["start"]).total_seconds() / 86400
        raw_flag = request.query_params.get("fixed_charge")
        if raw_flag is None:
            include_fixed = window_days >= 28
        else:
            include_fixed = raw_flag.strip().lower() in {"1", "true", "yes", "on"}

        bill = engines.estimate_bill(
            context["total_kwh"],
            context["tariff"],
            hourly_kwh=context["hourly_kwh"],
            include_fixed_charge=include_fixed,
        )
        emissions = engines.estimate_co2(context["total_kwh"], context["factor"])
        payload = {
            **self.energy_block(context),
            "window_days": round(window_days, 3),
            "cost": bill.as_dict(),
            "co2": emissions.as_dict(),
        }

        # Optional Phase 12 hourly modelled factor. The static factor above stays
        # the default and the response always says which was applied.
        if request.query_params.get("emission_model") == "rf":
            payload["co2_modelled"] = self._modelled_co2(context)

        return Response(payload)

    @staticmethod
    def _modelled_co2(context) -> dict:
        """Hourly modelled CO2, or an explanation of why the static factor stands."""
        hourly = context["hourly_kwh"]
        if not hourly:
            return {
                "applied": "static",
                "reason": "No hourly breakdown in this window, so the hourly "
                "model cannot be applied. The static factor above stands.",
            }
        try:
            result = ml_factors.modelled_co2(
                hourly, month=context["start"].month, day_of_week=context["start"].weekday()
            )
        except ml_factors.EmissionModelUnavailable as error:
            return {
                "applied": "static",
                "reason": str(error),
                "note": "The static factor above stands; nothing was substituted.",
            }
        return result


class MonthProjectionView(_ScopedEnergyView):
    """
    GET /api/billing/projection/

    Month-to-date consumption and a naive month-end projection.

    The window is forced to the current **local** month, so `from`/`to` are
    ignored here. The projection holds the mean daily rate so far for the rest of
    the month and lists that assumption explicitly; it is not a forecast. Phase
    11 adds the LSTM forecast that can replace it.
    """

    def get(self, request):
        now = timezone.localtime()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # A projection is always month-to-date, so the window is overridden here
        # rather than taken from the caller.
        params = request.query_params.copy()
        params["from"] = month_start.isoformat()
        params["to"] = now.isoformat()

        context, error = self.resolve(request, params=params)
        if error:
            return error

        projection = engines.project_month(
            context["total_kwh"],
            as_of=now,
            tariff=context["tariff"],
            hourly_kwh=context["hourly_kwh"],
        )
        emissions_to_date = engines.estimate_co2(context["total_kwh"], context["factor"])
        projected_emissions = engines.estimate_co2(
            projection.projected_kwh, context["factor"]
        )

        return Response(
            {
                **self.energy_block(context),
                "projection": projection.as_dict(),
                "co2_to_date": emissions_to_date.as_dict(),
                "co2_projected": projected_emissions.as_dict(),
            }
        )


class TariffViewSet(viewsets.ModelViewSet):
    """/api/billing/tariffs/ - shared sample tariffs plus the caller's own."""

    serializer_class = TariffSerializer
    permission_classes = [ReadAnyMemberWriteManager]

    def get_queryset(self):
        return (
            Tariff.objects.filter(
                Q(organisation__isnull=True)
                | Q(organisation__in=visible_organisations(self.request))
            )
            .prefetch_related("slabs", "tou_rates")
            .distinct()
        )


class TariffSlabViewSet(viewsets.ModelViewSet):
    serializer_class = TariffSlabSerializer
    permission_classes = [ReadAnyMemberWriteManager]

    def get_queryset(self):
        return TariffSlab.objects.filter(
            Q(tariff__organisation__isnull=True)
            | Q(tariff__organisation__in=visible_organisations(self.request))
        ).distinct()


class TimeOfUseRateViewSet(viewsets.ModelViewSet):
    serializer_class = TimeOfUseRateSerializer
    permission_classes = [ReadAnyMemberWriteManager]

    def get_queryset(self):
        return TimeOfUseRate.objects.filter(
            Q(tariff__organisation__isnull=True)
            | Q(tariff__organisation__in=visible_organisations(self.request))
        ).distinct()


class EmissionFactorViewSet(viewsets.ModelViewSet):
    """
    /api/billing/emission-factors/

    Factors are global reference data, readable by anyone and editable by a
    manager. `source` and `is_verified` travel with every factor so a figure is
    never shown without its provenance.
    """

    queryset = EmissionFactor.objects.all()
    serializer_class = EmissionFactorSerializer
    permission_classes = [ReadAnyMemberWriteManager]


class BillingSettingsViewSet(viewsets.ModelViewSet):
    """/api/billing/settings/ - which tariff and factor an organisation uses."""

    serializer_class = BillingSettingsSerializer
    permission_classes = [ReadAnyMemberWriteManager]

    def get_queryset(self):
        return BillingSettings.objects.filter(
            organisation__in=visible_organisations(self.request)
        )

    def perform_create(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
