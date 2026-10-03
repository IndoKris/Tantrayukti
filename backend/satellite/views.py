"""
Satellite and community map endpoints.

Every NO2 response states its unit and that the value is a **column density**,
not a surface concentration, because the plan calls out that confusion
specifically.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ml.config import ArtifactPaths
from satellite import hotspots as hotspot_engine
from satellite.models import NO2_UNIT, NO2_UNIT_NOTE, CityNo2
from satellite.serializers import CityNo2Serializer, CommunityPointSerializer
from spaces.models import Organisation


def visible_organisations(request):
    if request.user.is_superuser:
        return Organisation.objects.all()
    return Organisation.objects.filter(memberships__user=request.user)


class CityNo2ListView(APIView):
    """GET /api/satellite/cities/ - every city reading, highest NO2 first."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cities = CityNo2.objects.all()
        measured = cities.filter(is_measured=True).count()

        return Response(
            {
                "unit": NO2_UNIT,
                "unit_note": NO2_UNIT_NOTE,
                "count": cities.count(),
                "measured_count": measured,
                "provenance_note": (
                    "Static fallback values; no Earth Engine or Sentinel-5P "
                    "credentials are configured, so none of these are measurements."
                )
                if measured == 0
                else "Some values are measured; check `is_measured` per row.",
                "results": CityNo2Serializer(cities, many=True).data,
            }
        )


class SatelliteHotspotsView(APIView):
    """
    GET /api/satellite-hotspots/

    NO2 hotspot cities, with the validated threshold that produced them.

    `POST` re-runs detection and stores the result (manager or above via the
    standard permission on write is not required here because nothing
    user-specific is written, but the result is cached on the rows).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        result = hotspot_engine.detect_hotspots(persist=False)
        return self._respond(result)

    def post(self, request):
        result = hotspot_engine.detect_hotspots(persist=True)
        return self._respond(result, created=True)

    @staticmethod
    def _respond(result: dict, created: bool = False) -> Response:
        if result["status"] != "evaluated":
            return Response(result, status=status.HTTP_409_CONFLICT)

        payload = {
            **{key: value for key, value in result.items() if key != "hotspots"},
            "hotspot_count": len(result["hotspots"]),
            "hotspots": CityNo2Serializer(result["hotspots"], many=True).data,
            "note": (
                "An empty list means no city stands out from the rest, which is a "
                "real answer: no fixed fraction of cities is labelled a hotspot."
            ),
        }
        return Response(
            payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class CommunityMapView(APIView):
    """
    GET /api/community/map/

    Energy aggregated onto city-level coordinates for the heatmap, alongside the
    city NO2 layer.

    Coordinates are rounded to 3 decimal places (about 100 m) before storage, so
    the map cannot resolve to a household.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = min(int(request.query_params.get("days", 30)), 365)
        end = timezone.now()
        start = end - timedelta(days=days)

        points = hotspot_engine.community_points(
            visible_organisations(request),
            start,
            end,
            metering=request.query_params.get("metering", "auto"),
        )

        return Response(
            {
                "window": {"from": start, "to": end, "days": days},
                "privacy": (
                    "Coordinates are rounded to 3 decimal places (about 100 m) "
                    "before being stored, so no point identifies a household."
                ),
                "energy_points": CommunityPointSerializer(points, many=True).data,
                "no2": {
                    "unit": NO2_UNIT,
                    "unit_note": NO2_UNIT_NOTE,
                    "results": CityNo2Serializer(CityNo2.objects.all(), many=True).data,
                },
            }
        )


class Co2TrendView(APIView):
    """
    GET /api/community/co2-trend/

    The Phase 12 linear CO2 trend with its prediction interval, served from the
    training manifest so the figures match `metrics.json` exactly.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        manifest_path = ArtifactPaths(slug="co2_trend").manifest

        if not manifest_path.exists():
            return Response(
                {
                    "detail": "No CO2 trend has been fitted yet.",
                    "how_to_fix": "cd backend && python -m ml.training.train_co2_trend",
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            return Response(
                {"detail": f"The CO2 trend manifest is not valid JSON: {error}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(manifest)
