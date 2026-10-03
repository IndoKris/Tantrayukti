"""
Devices and their readings.

**Units are fixed and named in every field**, because the plan forbids mixing kW
with kWh anywhere in the project:

* `active_power_w`  - instantaneous real power, **watts**
* `energy_wh`       - energy accumulated **during this sampling interval**, watt-hours
* `voltage_v`       - RMS volts
* `current_a`       - RMS amperes
* `power_factor`    - dimensionless, 0..1

`energy_wh` is interval energy, never a cumulative meter total. Phase 8 sums it
to produce hourly/daily/monthly kWh, so a cumulative value here would be
double counted.

**Device authentication** is a shared secret presented as a bearer token. The
raw token is shown exactly once at issue; only its SHA-256 hash is stored, and
incoming tokens are compared in constant time. This is deliberately *not*
described as cryptographic verification of the payload: the server checks that
the caller knows the secret, it does not verify a signature over the reading
itself. See `authentication.py`.
"""

import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

#: Readings arriving later than this after their timestamp came from the device's
#: offline buffer rather than from a live sample.
BUFFERED_AFTER = timedelta(minutes=2)

#: A device is considered offline once it has missed this many sampling intervals.
OFFLINE_AFTER_INTERVALS = 3

#: Never treat a device as offline faster than this, however short its interval.
MIN_OFFLINE_GRACE = timedelta(minutes=2)


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw device token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class Device(models.Model):
    """
    A metering device attached to a room.

    Also the "digital twin" record: it carries the last-seen stamp, the online
    state derived from it, and how many readings the device still holds in its
    flash buffer.
    """

    class Kind(models.TextChoices):
        MAINS = "mains", "Whole-space mains meter"
        APPLIANCE = "appliance", "Single appliance meter"
        SIMULATED = "simulated", "Simulator"

    room = models.ForeignKey(
        "spaces.Room", on_delete=models.CASCADE, related_name="devices"
    )
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.MAINS)
    is_active = models.BooleanField(
        default=True, help_text="Inactive devices are refused at ingestion."
    )

    sample_interval_seconds = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1)],
        help_text="How often the device is expected to post. Drives the online check.",
    )
    firmware_version = models.CharField(max_length=32, blank=True)

    # --- Authentication ------------------------------------------------------
    # Only the hash is stored, so a database leak does not expose usable tokens.
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    token_prefix = models.CharField(
        max_length=8,
        editable=False,
        help_text="First characters of the token, to identify it in the UI.",
    )
    token_issued_at = models.DateTimeField(null=True, blank=True, editable=False)

    # --- Digital twin --------------------------------------------------------
    last_seen_at = models.DateTimeField(
        null=True, blank=True, help_text="Last successful request from this device."
    )
    last_reading_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the newest reading stored, which may predate last_seen_at.",
    )
    reported_buffer_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Readings still queued in the device's flash, as the device reports them.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["room__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["room", "name"], name="unique_device_name_per_room")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.room})"

    def save(self, *args, **kwargs):
        # A device is unusable without a token, so issue one on creation.
        if not self.token_hash:
            self.issue_token()
        super().save(*args, **kwargs)

    # --- Token handling ------------------------------------------------------

    def issue_token(self) -> str:
        """
        Generate a new token, store its hash, and return the raw value.

        The raw token cannot be recovered afterwards. Calling this again rotates
        the credential and immediately invalidates the previous one.
        """
        raw = secrets.token_urlsafe(32)
        self.token_hash = hash_token(raw)
        self.token_prefix = raw[:8]
        self.token_issued_at = timezone.now()
        return raw

    def rotate_token(self) -> str:
        """Issue a replacement token and persist it."""
        raw = self.issue_token()
        self.save(update_fields=["token_hash", "token_prefix", "token_issued_at", "updated_at"])
        return raw

    # --- Digital twin --------------------------------------------------------

    @property
    def organisation(self):
        return self.room.organisation

    @property
    def offline_after(self) -> timedelta:
        """How much silence is tolerated before the device counts as offline."""
        return max(
            timedelta(seconds=self.sample_interval_seconds * OFFLINE_AFTER_INTERVALS),
            MIN_OFFLINE_GRACE,
        )

    @property
    def is_online(self) -> bool:
        if not self.is_active or self.last_seen_at is None:
            return False
        return timezone.now() - self.last_seen_at <= self.offline_after

    @property
    def status(self) -> str:
        if not self.is_active:
            return "disabled"
        if self.last_seen_at is None:
            return "never-seen"
        return "online" if self.is_online else "offline"

    @property
    def seconds_since_last_seen(self) -> int | None:
        if self.last_seen_at is None:
            return None
        return int((timezone.now() - self.last_seen_at).total_seconds())

    def buffered_reading_count(self, since: timedelta = timedelta(days=1)) -> int:
        """Readings stored in the window that arrived late, i.e. from the buffer."""
        return self.readings.filter(
            was_buffered=True, timestamp__gte=timezone.now() - since
        ).count()


class Reading(models.Model):
    """
    One sample from a device.

    `(device, timestamp)` is unique, which makes ingestion idempotent: a device
    replaying its buffer after a failed upload cannot create duplicates.
    """

    class Source(models.TextChoices):
        DEVICE = "device", "Device"
        SIMULATOR = "simulator", "Simulator"
        IMPORT = "import", "Manual import"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="readings")
    timestamp = models.DateTimeField(
        db_index=True, help_text="When the sample was taken on the device."
    )
    received_at = models.DateTimeField(
        auto_now_add=True, help_text="When the server stored it."
    )

    voltage_v = models.DecimalField(
        "voltage (V)",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("500"))],
    )
    current_a = models.DecimalField(
        "current (A)",
        max_digits=8,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("200"))],
    )
    power_factor = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    active_power_w = models.DecimalField(
        "active power (W)",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Instantaneous real power in watts.",
    )
    energy_wh = models.DecimalField(
        "energy this interval (Wh)",
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Energy for this interval only, never a cumulative meter total.",
    )

    source = models.CharField(max_length=16, choices=Source.choices, default=Source.DEVICE)
    was_buffered = models.BooleanField(
        default=False,
        help_text="Arrived well after its timestamp, i.e. replayed from the device buffer.",
    )

    class Meta:
        ordering = ["-timestamp"]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "timestamp"], name="unique_reading_per_device_timestamp"
            )
        ]
        indexes = [
            # Phase 8 rolls up by device over a time range.
            models.Index(fields=["device", "timestamp"], name="reading_device_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.device.name} @ {self.timestamp.isoformat()}: {self.active_power_w} W"

    @property
    def energy_kwh(self) -> Decimal:
        """Interval energy in kWh. Provided so callers never divide by 1000 by hand."""
        return self.energy_wh / Decimal("1000")
