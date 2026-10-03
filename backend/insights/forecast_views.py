"""
Forecast endpoint.

`GET /api/forecast/<device_id>/` builds the last 24 hours of hourly energy for a
device from the Phase 8 rollups, then applies the trained one-step model
recursively to produce a 24-hour forward series.

When no model has been trained, or the device has too little history, the
response says so with a 409 and an actionable reason. It never returns an
invented curve - a fabricated forecast on a dashboard is worse than no forecast.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ml import inference
from spaces.models import Organisation
from telemetry import rollups
from telemetry.models import Device
from telemetry.views import local_iso


class DeviceForecastView(APIView):
    """24-hour recursive load forecast for one device."""

    permission_classes = [IsAuthenticated]

    def get(self, request, device_id: int):
        device = self._visible_device(request, device_id)
        if device is None:
            return Response(
                {"detail": "No visible device with that id."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            model = inference.load_model()
        except inference.ModelUnavailable as error:
            return Response(
                {
                    "detail": "No trained forecasting model is available.",
                    "reason": str(error),
                    "how_to_fix": (
                        "cd backend && python -m ml.data.prepare --small && "
                        "python -m ml.training.train_lstm --small"
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        lookback = model.lookback
        end = timezone.now()
        start = end - timedelta(hours=lookback * 3)

        readings = rollups.readings_for(
            Device.objects.filter(pk=device.pk), start, end
        )
        series = rollups.time_series(readings, "hour")

        if len(series) < lookback:
            return Response(
                {
                    "detail": "Not enough history to forecast.",
                    "device": device.name,
                    "hours_available": len(series),
                    "hours_required": lookback,
                    "how_to_fix": (
                        "Post more readings, or backfill with: python simulator/run.py "
                        "--days 7 --post --register ..."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        recent = series[-lookback:]
        history_kwh = [float(row["energy_kwh"]) for row in recent]
        last_bucket = recent[-1]["bucket"]

        result = inference.forecast_from_history(model, history_kwh, last_bucket)

        return Response(
            {
                "device": {
                    "id": device.pk,
                    "name": device.name,
                    "room": device.room.name,
                    "kind": device.kind,
                },
                "history": {
                    "hours": lookback,
                    "from": local_iso(recent[0]["bucket"]),
                    "to": local_iso(last_bucket),
                    "total_kwh": round(sum(history_kwh), 6),
                    "points": [
                        {
                            "timestamp": local_iso(row["bucket"]),
                            "energy_kwh": row["energy_kwh"],
                        }
                        for row in recent
                    ],
                },
                "forecast": result,
                "metrics_source": (
                    "Error metrics for this model are in "
                    "backend/ml/artifacts/metrics.json, produced by "
                    "ml/evaluation/evaluate_all.py. They are error measures, not accuracy."
                ),
            }
        )

    @staticmethod
    def _visible_device(request, device_id):
        user = request.user
        organisations = (
            Organisation.objects.all()
            if user.is_superuser
            else Organisation.objects.filter(memberships__user=user)
        )
        return (
            Device.objects.filter(
                pk=device_id, room__floor__building__organisation__in=organisations
            )
            .select_related("room__floor__building__organisation")
            .first()
        )


class MlMetricsView(APIView):
    """
    GET /api/ml/metrics/

    Serves `ml/artifacts/metrics.json` verbatim.

    The Phase 19 metrics page reads this. Serving the file rather than
    recomputing or re-describing it is what keeps the plan's honesty rule
    enforceable: there is exactly one place numbers can come from.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        import json

        from ml.config import METRICS_PATH

        if not METRICS_PATH.exists():
            return Response(
                {
                    "detail": "No metrics have been produced yet.",
                    "how_to_fix": (
                        "cd backend && python -m ml.training.train_lstm --small && "
                        "python -m ml.evaluation.evaluate_all"
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            payload = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            return Response(
                {"detail": f"metrics.json is not valid JSON: {error}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(payload)
