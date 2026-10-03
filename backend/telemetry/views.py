"""
Reading ingestion and the device API.

Ingestion accepts either a single reading or a batch, and is **idempotent**: the
`(device, timestamp)` unique constraint means a device replaying its buffer after
a failed upload cannot create duplicates. Rows are inserted in chronological
order so a backfill lands in the same order it was sampled.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin, IsManagerOrAbove
from spaces.models import Organisation
from telemetry import rollups
from telemetry.authentication import DeviceTokenAuthentication, DeviceUser
from telemetry.models import BUFFERED_AFTER, Device, Reading
from telemetry.serializers import (
    DeviceCreateSerializer,
    DeviceSerializer,
    ReadingBatchSerializer,
    ReadingSerializer,
)


def local_iso(value):
    """
    Render a datetime the way DRF's serializer fields do.

    DRF converts datetimes to the active timezone (`TIME_ZONE`, Asia/Kolkata),
    so a hand-built response dict must do the same or the API would emit two
    different offsets for the same instant on different routes.
    """
    return timezone.localtime(value).isoformat() if value is not None else None


class IsDevice(BasePermission):
    """Only an authenticated device may post readings."""

    message = "A valid device token is required."

    def has_permission(self, request, view) -> bool:
        return isinstance(request.user, DeviceUser)


class ReadingIngestView(APIView):
    """
    POST /api/readings/

    Authenticated with a device token, not a user JWT.

    Accepts three shapes:

    * a single reading object
    * a bare list of reading objects
    * `{"readings": [...], "buffer_count": 12, "firmware_version": "1.2.0"}`

    Returns the counts actually written, so a device can trim its flash buffer
    with confidence:

        {"created": 10, "duplicates": 2, "received": 12, "device": {...}}
    """

    authentication_classes = [DeviceTokenAuthentication]
    permission_classes = [IsDevice]

    def post(self, request):
        device: Device = request.user.device
        payload = request.data

        # Normalise the three accepted shapes into one.
        if isinstance(payload, list):
            payload = {"readings": payload}
        elif isinstance(payload, dict) and "readings" not in payload:
            payload = {"readings": [payload]}

        batch = ReadingBatchSerializer(data=payload)
        batch.is_valid(raise_exception=True)
        rows = batch.validated_data["readings"]

        created, duplicates = self._store(device, rows)
        self._update_twin(device, batch.validated_data, rows)

        return Response(
            {
                "received": len(rows),
                "created": created,
                "duplicates": duplicates,
                "device": DeviceSerializer(device).data,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # --- internals -----------------------------------------------------------

    def _store(self, device: Device, rows) -> tuple[int, int]:
        """
        Insert readings in chronological order, skipping ones already stored.

        `ignore_conflicts` makes a replayed buffer harmless, and sorting means a
        backfill is written in sample order rather than upload order.
        """
        now = timezone.now()
        interval_hours = Decimal(device.sample_interval_seconds) / Decimal("3600")

        ordered = sorted(rows, key=lambda row: row["timestamp"])
        existing = set(
            device.readings.filter(
                timestamp__in=[row["timestamp"] for row in ordered]
            ).values_list("timestamp", flat=True)
        )

        to_create = []
        for row in ordered:
            if row["timestamp"] in existing:
                continue
            energy = row.get("energy_wh")
            if energy is None:
                # Derive interval energy from power when the device did not integrate.
                energy = (row["active_power_w"] * interval_hours).quantize(Decimal("0.0001"))
            to_create.append(
                Reading(
                    device=device,
                    timestamp=row["timestamp"],
                    active_power_w=row["active_power_w"],
                    energy_wh=energy,
                    voltage_v=row.get("voltage_v"),
                    current_a=row.get("current_a"),
                    power_factor=row.get("power_factor"),
                    source=row.get("source", Reading.Source.DEVICE),
                    was_buffered=(now - row["timestamp"]) > BUFFERED_AFTER,
                )
            )

        with transaction.atomic():
            Reading.objects.bulk_create(to_create, ignore_conflicts=True)

        return len(to_create), len(ordered) - len(to_create)

    def _update_twin(self, device: Device, validated: dict, rows) -> None:
        """Refresh the digital-twin fields after a successful upload."""
        device.last_seen_at = timezone.now()
        newest = max(row["timestamp"] for row in rows)
        if device.last_reading_at is None or newest > device.last_reading_at:
            device.last_reading_at = newest

        fields = ["last_seen_at", "last_reading_at", "updated_at"]
        if "buffer_count" in validated:
            device.reported_buffer_count = validated["buffer_count"]
            fields.append("reported_buffer_count")
        if validated.get("firmware_version"):
            device.firmware_version = validated["firmware_version"]
            fields.append("firmware_version")

        device.save(update_fields=fields)


class ReadAnyMemberWriteManager(IsAuthenticated):
    """Safe methods: any authenticated user. Writes: manager or above."""

    message = IsManagerOrAbove.message

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        return IsManagerOrAbove().has_permission(request, view)


class DeviceViewSet(viewsets.ModelViewSet):
    """
    /api/devices/

    Scoped to the caller's organisations, like everything in `spaces`. Filter
    with `?room=`, `?building=` or `?organisation=`.
    """

    queryset = Device.objects.select_related("room__floor__building__organisation")
    permission_classes = [ReadAnyMemberWriteManager]

    def get_serializer_class(self):
        # Only a creation response reveals the raw token.
        return DeviceCreateSerializer if self.action == "create" else DeviceSerializer

    def visible_organisations(self):
        user = self.request.user
        if user.is_superuser:
            return Organisation.objects.all()
        return Organisation.objects.filter(memberships__user=user)

    def get_queryset(self):
        queryset = self.queryset.filter(
            room__floor__building__organisation__in=self.visible_organisations()
        )
        params = self.request.query_params
        if room := params.get("room"):
            queryset = queryset.filter(room_id=room)
        if building := params.get("building"):
            queryset = queryset.filter(room__floor__building_id=building)
        if organisation := params.get("organisation"):
            queryset = queryset.filter(
                room__floor__building__organisation_id=organisation
            )
        return queryset

    def perform_create(self, serializer):
        device = serializer.save()
        # Device.save() issued a token but its raw value was not kept. Rotate once
        # here so the response can show it exactly this once.
        device._raw_token = device.rotate_token()

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        """
        GET /api/devices/<id>/status/ - the digital twin.

        Reports online state, silence duration, the newest stored reading and
        both buffer counts: what the device claims it holds, and how many late
        arrivals the server actually saw.
        """
        device = self.get_object()
        return Response(
            {
                "id": device.pk,
                "name": device.name,
                "status": device.status,
                "is_online": device.is_online,
                "is_active": device.is_active,
                "last_seen_at": local_iso(device.last_seen_at),
                "last_reading_at": local_iso(device.last_reading_at),
                "seconds_since_last_seen": device.seconds_since_last_seen,
                "offline_after_seconds": int(device.offline_after.total_seconds()),
                "sample_interval_seconds": device.sample_interval_seconds,
                "reported_buffer_count": device.reported_buffer_count,
                "buffered_count_24h": device.buffered_reading_count(),
                "reading_count": device.readings.count(),
                "firmware_version": device.firmware_version,
            }
        )

    @action(detail=True, methods=["post"], url_path="rotate-token", permission_classes=[IsAdmin])
    def rotate_token(self, request, pk=None):
        """
        POST /api/devices/<id>/rotate-token/

        Returns the new token once and invalidates the old one immediately.
        Admin only, since it can take a device offline.
        """
        device = self.get_object()
        raw = device.rotate_token()
        return Response({"id": device.pk, "token": raw, "token_prefix": device.token_prefix})

    @action(detail=True, methods=["get"])
    def readings(self, request, pk=None):
        """GET /api/devices/<id>/readings/ - most recent first, paginated."""
        device = self.get_object()
        page = self.paginate_queryset(device.readings.all())
        serializer = ReadingSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class UsageView(APIView):
    """
    GET /api/usage/

    Energy and power rolled up by time bucket, device or room.

    Query parameters
    ----------------
    `space`
        `<kind>:<id>`, e.g. `building:3`. Kinds: organisation, building, floor, room.
        Alternatively use the explicit `organisation=`, `building=`, `floor=`,
        `room=` or `device=`. Omitted means every device the caller can see.
    `period`
        `hour` (default), `day` or `month`. Buckets are **local** days/hours.
    `from`, `to`
        ISO-8601 date or datetime. Defaults to the last 24 h / 30 d / 365 d
        depending on `period`.
    `group_by`
        `time` (default), `device` or `room`.
    `metering`
        `auto` (default), `mains`, `appliance` or `all`. See `rollups` for why
        this exists: summing a mains meter together with the appliance meters
        underneath it double counts.

    The response always reports the scope, window, metering mode actually used
    and the devices included, so no figure appears without saying how it was
    produced.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = request.query_params
        period = params.get("period", "hour")
        group_by = params.get("group_by", "time")

        if group_by not in {"time", "device", "room"}:
            return Response(
                {"detail": f"Unknown group_by '{group_by}'. One of: time, device, room."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Validate the period first: it indexes the default-window table, so
            # an unknown value must not reach it.
            rollups.validate_period(period)
            scope = rollups.resolve_scope(params, self.visible_organisations())
            devices, metering = rollups.select_devices(
                scope.devices, params.get("metering", "auto")
            )
            start, end = rollups.resolve_window(params, period)
        except rollups.ScopeError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        readings = rollups.readings_for(devices, start, end)

        if group_by == "device":
            results = rollups.by_device(readings)
        elif group_by == "room":
            results = rollups.by_room(readings)
        else:
            results = rollups.time_series(readings, period)

        return Response(
            {
                "scope": scope.as_dict(),
                "window": {"from": local_iso(start), "to": local_iso(end)},
                "period": period if group_by == "time" else None,
                "group_by": group_by,
                "metering": {
                    "requested": params.get("metering", "auto"),
                    "applied": metering,
                    "device_count": devices.count(),
                    "device_ids": list(devices.values_list("id", flat=True)),
                    "note": (
                        "A whole-space mains meter supersedes the appliance meters "
                        "beneath it; summing both would double count."
                    ),
                },
                "totals": rollups.totals(readings),
                "results": results,
            }
        )

    def visible_organisations(self):
        user = self.request.user
        if user.is_superuser:
            return Organisation.objects.all()
        return Organisation.objects.filter(memberships__user=user)


class ChatIngestView(APIView):
    """
    POST /api/ingest/chat/

    Ingest a reading described in a chat message. Authenticated as a **user**
    (not a device), because a person is reporting it.

    Body:
        {"device": 3, "modality": "text", "text": "AC ran 4 hours at 1500 W",
         "occurred_on": "2026-10-03"}

    Readings created here are marked `source=import`, so chat-derived data stays
    distinguishable from metered telemetry in every rollup and query.

    Three refusals, all deliberate:

    * a modality with no configured provider returns **422** with the reason -
      never a fabricated value;
    * an unparseable message returns **422** with guidance on how to phrase it;
    * an implausible figure returns **422** listing what failed the range check.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from datetime import date as date_type

        from telemetry import extractors

        device_id = request.data.get("device")
        modality = str(request.data.get("modality") or "text").lower()

        device = (
            Device.objects.filter(
                pk=device_id,
                room__floor__building__organisation__in=self._visible_organisations(request),
            )
            .select_related("room__floor__building__organisation")
            .first()
        )
        if device is None:
            return Response(
                {"detail": "No visible device with that id."},
                status=status.HTTP_404_NOT_FOUND,
            )

        extraction = extractors.extract(modality, request.data)

        if not extraction.succeeded:
            return Response(
                {
                    "detail": "Could not extract a reading from that message.",
                    "extraction": extraction.as_dict(),
                    "stored": 0,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        problems = extractors.validate_ranges(extraction)
        if problems:
            return Response(
                {
                    "detail": "The extracted values are not plausible.",
                    "problems": problems,
                    "extraction": extraction.as_dict(),
                    "stored": 0,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Anchor the span. A date puts it at local midday; otherwise it ends now.
        raw_date = request.data.get("occurred_on")
        if raw_date:
            try:
                parsed = date_type.fromisoformat(str(raw_date))
            except ValueError:
                return Response(
                    {"detail": f"occurred_on must be an ISO date, got '{raw_date}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            anchor = timezone.make_aware(
                timezone.datetime.combine(parsed, timezone.datetime.min.time())
            ) + timedelta(hours=12)
        else:
            anchor = timezone.now().replace(minute=0, second=0, microsecond=0)

        interval = device.sample_interval_seconds
        spread = extractors.spread_over_interval(
            extraction.energy_kwh, extraction.hours, interval
        )

        interval_hours = Decimal(interval) / Decimal("3600")
        rows = []
        for offset, energy_kwh in spread:
            energy_wh = (energy_kwh * Decimal("1000")).quantize(Decimal("0.0001"))
            rows.append(
                Reading(
                    device=device,
                    timestamp=anchor + offset,
                    active_power_w=(energy_wh / interval_hours).quantize(Decimal("0.01"))
                    if interval_hours > 0
                    else Decimal("0"),
                    energy_wh=energy_wh,
                    source=Reading.Source.IMPORT,
                    was_buffered=False,
                )
            )

        with transaction.atomic():
            created = Reading.objects.bulk_create(rows, ignore_conflicts=True)

        return Response(
            {
                "detail": "Reading ingested.",
                "device": {"id": device.pk, "name": device.name},
                "extraction": extraction.as_dict(),
                "stored": len(rows),
                "created": len(created),
                "window": {
                    "from": local_iso(anchor),
                    "to": local_iso(anchor + spread[-1][0]),
                    "interval_seconds": interval,
                },
                "assumptions": [
                    f"The reported {extraction.energy_kwh} kWh was spread evenly "
                    f"across {len(rows)} interval(s) of {interval} s, because a "
                    f"chat report covers a span rather than an instant. Storing it "
                    f"as a single spike would look like an anomaly.",
                    "Stored with source=import, so it stays distinguishable from "
                    "metered telemetry.",
                    f"Extracted by {extraction.provider} "
                    f"({'mock' if extraction.is_mock else 'live'} provider, "
                    f"confidence {extraction.confidence:.2f}).",
                ],
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _visible_organisations(request):
        if request.user.is_superuser:
            return Organisation.objects.all()
        return Organisation.objects.filter(memberships__user=request.user)
