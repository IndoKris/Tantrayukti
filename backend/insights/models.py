"""
Anomalies, their causes and the recommendations attached to them.

An `Anomaly` is a durable record with a lifecycle (open -> acknowledged ->
resolved), not a transient score, because the Mission requires a feed people can
act on and the plan requires states.

`detector` records which rule or model raised it, and `evidence` holds the
structured facts behind it. Phase 14 ranks causes from that evidence and Phase 15
attaches savings, so nothing downstream has to re-derive why the anomaly fired.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class Severity(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


#: Ordering for display and for picking the worst of a set.
SEVERITY_RANK = {
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class Detector(models.TextChoices):
    """What raised the anomaly. Kept explicit so evaluation can score each."""

    ISOLATION_FOREST = "isolation_forest", "Isolation Forest"
    SEASONAL_ZSCORE = "seasonal_zscore", "Seasonal baseline z-score"
    NIGHT_LOAD = "rule_night_load", "Rule: load during unoccupied night hours"
    BASELOAD_JUMP = "rule_baseload_jump", "Rule: baseload step change"
    DEVICE_LEFT_ON = "rule_device_left_on", "Rule: device left running"


class AnomalyState(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    RESOLVED = "resolved", "Resolved"
    DISMISSED = "dismissed", "Dismissed as not a problem"


class Anomaly(models.Model):
    """
    One detected period of abnormal usage.

    `(device, detector, window_start)` is unique, so re-running detection over
    the same window updates the existing record instead of flooding the feed
    with duplicates.
    """

    device = models.ForeignKey(
        "telemetry.Device", on_delete=models.CASCADE, related_name="anomalies"
    )
    detector = models.CharField(max_length=32, choices=Detector.choices)
    severity = models.CharField(max_length=16, choices=Severity.choices)

    window_start = models.DateTimeField(db_index=True)
    window_end = models.DateTimeField()

    observed_kwh = models.DecimalField(max_digits=12, decimal_places=4)
    expected_kwh = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="What the seasonal baseline expected. Null when the detector has no baseline.",
    )
    excess_kwh = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    score = models.FloatField(
        null=True,
        blank=True,
        help_text="Detector score: z-score, or Isolation Forest decision function.",
    )

    title = models.CharField(max_length=160)
    #: Structured facts behind the detection. Phase 14 ranks causes from this.
    evidence = models.JSONField(default=dict, blank=True)

    state = models.CharField(
        max_length=16, choices=AnomalyState.choices, default=AnomalyState.OPEN
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_anomalies",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-window_start", "-severity"]
        verbose_name_plural = "anomalies"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "detector", "window_start"],
                name="unique_anomaly_per_device_detector_window",
            )
        ]
        indexes = [
            models.Index(fields=["state", "-window_start"], name="anomaly_state_time_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title} ({self.device.name})"

    @property
    def organisation(self):
        return self.device.room.organisation

    @property
    def severity_rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 0)

    @property
    def is_open(self) -> bool:
        return self.state in {AnomalyState.OPEN, AnomalyState.ACKNOWLEDGED}

    def acknowledge(self, user) -> None:
        from django.utils import timezone

        self.state = AnomalyState.ACKNOWLEDGED
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.save(update_fields=["state", "acknowledged_by", "acknowledged_at", "updated_at"])

    def resolve(self, note: str = "") -> None:
        from django.utils import timezone

        self.state = AnomalyState.RESOLVED
        self.resolved_at = timezone.now()
        self.resolution_note = note
        self.save(update_fields=["state", "resolved_at", "resolution_note", "updated_at"])

    def dismiss(self, note: str = "") -> None:
        from django.utils import timezone

        self.state = AnomalyState.DISMISSED
        self.resolved_at = timezone.now()
        self.resolution_note = note
        self.save(update_fields=["state", "resolved_at", "resolution_note", "updated_at"])
