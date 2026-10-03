"""
Insights API: anomaly feed, causes, recommendations, comparisons, demo mode.

Everything here is scoped to the caller's organisations, like the rest of the
project, and scoping lives in `get_queryset` so a foreign object is a 404 rather
than relying on an object-level check.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsManagerOrAbove
from billing.models import EmissionFactor, Tariff
from insights import causes as cause_engine
from insights import comparison, detection
from insights import recommendations as recommendation_engine
from insights.models import Anomaly, AnomalyState
from insights.serializers import AnomalySerializer
from spaces.models import Organisation
from telemetry import rollups
from telemetry.models import Device


def visible_organisations(request):
    if request.user.is_superuser:
        return Organisation.objects.all()
    return Organisation.objects.filter(memberships__user=request.user)


class AnomalyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    /api/anomalies/

    Read-only list and detail, plus acknowledge/resolve/dismiss actions and
    nested cause and recommendation routes. Filter with `?state=`, `?severity=`,
    `?device=`, `?organisation=`.
    """

    serializer_class = AnomalySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Anomaly.objects.filter(
            device__room__floor__building__organisation__in=visible_organisations(
                self.request
            )
        ).select_related("device__room__floor__building__organisation")

        params = self.request.query_params
        if state := params.get("state"):
            queryset = queryset.filter(state=state)
        if severity := params.get("severity"):
            queryset = queryset.filter(severity=severity)
        if device := params.get("device"):
            queryset = queryset.filter(device_id=device)
        if organisation := params.get("organisation"):
            queryset = queryset.filter(
                device__room__floor__building__organisation_id=organisation
            )
        if params.get("open") in {"1", "true", "yes"}:
            queryset = queryset.filter(
                state__in=[AnomalyState.OPEN, AnomalyState.ACKNOWLEDGED]
            )
        return queryset

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        anomaly = self.get_object()
        anomaly.acknowledge(request.user)
        return Response(AnomalySerializer(anomaly).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        anomaly = self.get_object()
        anomaly.resolve(note=request.data.get("note", ""))
        return Response(AnomalySerializer(anomaly).data)

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        anomaly = self.get_object()
        anomaly.dismiss(note=request.data.get("note", ""))
        return Response(AnomalySerializer(anomaly).data)

    @action(detail=True, methods=["get"])
    def causes(self, request, pk=None):
        """Ranked likely causes with the evidence behind each."""
        anomaly = self.get_object()
        use_llm = request.query_params.get("llm") in {"1", "true", "yes"}
        return Response(cause_engine.explain(anomaly, use_llm=use_llm))

    @action(detail=True, methods=["get"])
    def recommendations(self, request, pk=None):
        """Actions with kWh / INR / kg CO2 saved per month, and their formulas."""
        anomaly = self.get_object()
        tariff = Tariff.resolve(
            organisation=anomaly.organisation,
            tariff_id=request.query_params.get("tariff"),
        )
        factor = EmissionFactor.resolve(
            factor_id=request.query_params.get("emission_factor")
        )
        return Response(
            recommendation_engine.recommend(anomaly, tariff=tariff, factor=factor)
        )


class DetectView(APIView):
    """
    POST /api/anomalies/detect/

    Run detection over a device's recent history and store the findings.
    Manager or above, because it writes to the feed.
    """

    permission_classes = [IsManagerOrAbove]

    def post(self, request):
        device_id = request.data.get("device")
        days = int(request.data.get("days", 14))

        device = (
            Device.objects.filter(
                pk=device_id,
                room__floor__building__organisation__in=visible_organisations(request),
            )
            .select_related("room__floor__building__organisation")
            .first()
        )
        if device is None:
            return Response(
                {"detail": "No visible device with that id."},
                status=status.HTTP_404_NOT_FOUND,
            )

        end = timezone.now()
        start = end - timedelta(days=days)
        series = rollups.time_series(
            rollups.readings_for(Device.objects.filter(pk=device.pk), start, end), "hour"
        )
        observations = detection.observations_from_series(series)

        if len(observations) < 48:
            return Response(
                {
                    "detail": "Not enough history to run detection.",
                    "hours_available": len(observations),
                    "hours_required": 48,
                },
                status=status.HTTP_409_CONFLICT,
            )

        findings = detection.detect_all(observations)
        result = detection.persist_findings(device, findings)

        return Response(
            {
                "device": {"id": device.pk, "name": device.name},
                "window": {"from": start, "to": end, "hours": len(observations)},
                **result,
                "anomalies": AnomalySerializer(
                    Anomaly.objects.filter(device=device).order_by("-window_start")[:50],
                    many=True,
                ).data,
            }
        )


class SpaceComparisonView(APIView):
    """
    GET /api/compare/spaces/

    Compare the spaces one level below a scope, normalised per m2 or per person
    and ranked. Spaces missing the denominator are excluded and listed.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = request.query_params
        space = params.get("space", "")
        if ":" not in space:
            return Response(
                {
                    "detail": "space must be '<kind>:<id>', e.g. 'building:3'. "
                    "Comparable kinds: organisation, building, floor."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        kind, _, raw_id = space.partition(":")

        try:
            start, end = rollups.resolve_window(params, params.get("period", "day"))
            result = comparison.compare_spaces(
                scope_kind=kind.strip().lower(),
                scope_id=int(raw_id),
                visible_organisations=visible_organisations(request),
                start=start,
                end=end,
                metering=params.get("metering", "auto"),
                normalise_by=params.get("normalise_by", "area"),
            )
        except (rollups.ScopeError, ValueError) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


class PeriodComparisonView(APIView):
    """
    GET /api/compare/periods/

    Compare a scope across two consecutive periods: `day`, `week`, `month` or
    `same_weekday_last_week`. Pro-rates an incomplete current period so a
    part-way-through month does not look like a saving.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = request.query_params
        try:
            scope = rollups.resolve_scope(params, visible_organisations(request))
            result = comparison.compare_periods(
                devices=scope.devices,
                period=params.get("period", "day"),
                metering=params.get("metering", "auto"),
            )
        except rollups.ScopeError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"scope": scope.as_dict(), **result})


class DemoFaultView(APIView):
    """
    POST /api/demo/inject-fault/

    Injects a synthetic fault into a device's recent readings, runs detection,
    and returns the anomaly with its ranked causes and priced recommendations -
    the full detect -> explain -> recommend chain in one call, for the Phase 19
    demo button.

    Every reading it writes is marked `source=simulator`, so demo data is
    distinguishable from real telemetry in the database afterwards.
    """

    permission_classes = [IsManagerOrAbove]

    FAULTS = ("night_load", "baseload_jump", "device_left_on")

    def post(self, request):
        from decimal import Decimal

        from telemetry.models import Reading

        device_id = request.data.get("device")
        fault = request.data.get("fault", "night_load")
        days = int(request.data.get("days", 10))

        if fault not in self.FAULTS:
            return Response(
                {"detail": f"Unknown fault '{fault}'. One of: {', '.join(self.FAULTS)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device = (
            Device.objects.filter(
                pk=device_id,
                room__floor__building__organisation__in=visible_organisations(request),
            )
            .select_related("room__floor__building__organisation")
            .first()
        )
        if device is None:
            return Response(
                {"detail": "No visible device with that id."},
                status=status.HTTP_404_NOT_FOUND,
            )

        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        written = 0

        # A clean daily shape, then the fault laid on top of the recent part.
        shape = [0.4, 0.35, 0.33, 0.33, 0.35, 0.5, 0.8, 1.1, 1.2, 1.0, 0.9, 0.9,
                 0.95, 0.9, 0.85, 0.9, 1.05, 1.3, 1.6, 1.75, 1.6, 1.3, 0.9, 0.6]
        base_kw = 1.2

        for index in range(days * 24):
            stamp = now - timedelta(hours=days * 24 - index)
            local_hour = timezone.localtime(stamp).hour
            kw = base_kw * shape[local_hour]

            in_fault_window = index >= days * 24 * 0.6
            if in_fault_window:
                if fault == "night_load" and local_hour in (1, 2, 3):
                    kw += 3.2
                elif fault == "baseload_jump":
                    kw += 1.1
                elif fault == "device_left_on" and 20 <= local_hour <= 23:
                    kw = 4.0

            _, created = Reading.objects.update_or_create(
                device=device,
                timestamp=stamp,
                defaults={
                    "active_power_w": Decimal(str(round(kw * 1000, 2))),
                    "energy_wh": Decimal(str(round(kw * 1000, 4))),
                    "source": Reading.Source.SIMULATOR,
                },
            )
            written += int(created)

        series = rollups.time_series(
            rollups.readings_for(
                Device.objects.filter(pk=device.pk), now - timedelta(days=days), now
            ),
            "hour",
        )
        observations = detection.observations_from_series(series)
        findings = detection.detect_all(observations)
        persisted = detection.persist_findings(device, findings)

        anomalies = list(
            Anomaly.objects.filter(device=device, state=AnomalyState.OPEN).order_by(
                "-severity", "-window_start"
            )[:5]
        )

        chain = []
        tariff = Tariff.resolve(organisation=device.room.organisation)
        factor = EmissionFactor.resolve()
        for anomaly in anomalies:
            chain.append(
                {
                    "anomaly": AnomalySerializer(anomaly).data,
                    "causes": cause_engine.explain(anomaly),
                    "recommendations": recommendation_engine.recommend(
                        anomaly, tariff=tariff, factor=factor
                    ),
                }
            )

        return Response(
            {
                "demo": True,
                "fault_injected": fault,
                "device": {"id": device.pk, "name": device.name},
                "readings_written": written,
                "hours_simulated": days * 24,
                "detection": persisted,
                "chain": chain,
                "note": (
                    "Demo data. Every reading written here has source=simulator, "
                    "so it can be told apart from real telemetry."
                ),
            },
            status=status.HTTP_201_CREATED,
        )
