"""Shared fixtures for the insights tests."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model

from accounts.models import Role
from billing.models import EmissionFactor, Tariff, TariffSlab
from insights.models import Anomaly, Detector, Severity
from spaces.models import Building, Floor, Membership, Organisation, Room
from telemetry.models import Device, Reading

User = get_user_model()
IST = ZoneInfo("Asia/Kolkata")


def build_world():
    """An organisation with two rooms of different sizes, devices and a tariff."""
    org = Organisation.objects.create(name="Org")
    building = Building.objects.create(organisation=org, name="HQ")
    floor = Floor.objects.create(building=building, name="Ground", level=0)

    big = Room.objects.create(
        floor=floor, name="Open workspace", area_sqm=Decimal("200.00"), occupancy=40
    )
    small = Room.objects.create(
        floor=floor, name="Store", area_sqm=Decimal("10.00"), occupancy=1
    )
    unmeasured = Room.objects.create(floor=floor, name="Corridor")

    devices = {
        "big": Device.objects.create(room=big, name="Big mains", kind=Device.Kind.MAINS),
        "small": Device.objects.create(room=small, name="Small mains", kind=Device.Kind.MAINS),
        "unmeasured": Device.objects.create(
            room=unmeasured, name="Corridor mains", kind=Device.Kind.MAINS
        ),
    }

    manager = User.objects.create_user(
        username="manager", email="mg@example.com", password="pw", role=Role.MANAGER
    )
    member = User.objects.create_user(
        username="member", email="mb@example.com", password="pw", role=Role.MEMBER
    )
    for user in (manager, member):
        Membership.objects.create(user=user, organisation=org)

    tariff = Tariff.objects.create(
        name="Sample",
        fixed_charge_inr_month=Decimal("100.00"),
        tax_percent=Decimal("0.00"),
        is_sample=True,
        source="Test fixture",
        is_default=True,
    )
    for lower, upper, rate in ((0, 100, 5), (100, None, 10)):
        TariffSlab.objects.create(
            tariff=tariff,
            from_kwh=Decimal(lower),
            to_kwh=None if upper is None else Decimal(upper),
            rate_inr_per_kwh=Decimal(rate),
        )

    factor = EmissionFactor.objects.create(
        name="Static default",
        kg_co2_per_kwh=Decimal("0.82000"),
        source="Static unverified default",
        is_default=True,
    )

    return {
        "org": org,
        "building": building,
        "floor": floor,
        "rooms": {"big": big, "small": small, "unmeasured": unmeasured},
        "devices": devices,
        "manager": manager,
        "member": member,
        "tariff": tariff,
        "factor": factor,
    }


def add_readings(device, hours: int, kwh_per_hour: float, end: datetime | None = None):
    """Flat readings ending at `end` (default: now, on the hour)."""
    from django.utils import timezone

    end = end or timezone.now().replace(minute=0, second=0, microsecond=0)
    for index in range(hours):
        Reading.objects.update_or_create(
            device=device,
            timestamp=end - timedelta(hours=hours - index),
            defaults={
                "active_power_w": Decimal(str(round(kwh_per_hour * 1000, 2))),
                "energy_wh": Decimal(str(round(kwh_per_hour * 1000, 4))),
            },
        )


def make_anomaly(device, detector=Detector.NIGHT_LOAD, **overrides):
    """An anomaly with evidence shaped like the real detectors produce."""
    evidence_by_detector = {
        Detector.NIGHT_LOAD: {
            "hour": 2,
            "night_median_kwh": 0.4,
            "multiple_of_night_median": 8.5,
            "night_hours": [1, 2, 3, 4],
            "rule": "Energy during unoccupied night hours.",
        },
        Detector.BASELOAD_JUMP: {
            "baseload_before_kwh_per_hour": 0.4,
            "baseload_after_kwh_per_hour": 1.5,
            "increase_fraction": 2.75,
            "changed_on": "2026-03-08",
            "extra_kwh_per_day": 26.4,
            "rule": "Median daily minimum stepped up.",
        },
        Detector.DEVICE_LEFT_ON: {
            "run_hours": 9,
            "run_start": "2026-03-08T20:00:00+05:30",
            "run_end": "2026-03-09T05:00:00+05:30",
            "mean_kwh_per_hour": 3.2,
            "median_kwh_per_hour": 0.9,
            "flatness": 0.12,
            "rule": "Sustained near-constant load.",
        },
        Detector.SEASONAL_ZSCORE: {
            "hour": 3,
            "is_weekend": False,
            "z_score": 9.4,
            "baseline_median_kwh": 0.4,
            "baseline_robust_sigma_kwh": 0.05,
            "multiple_of_expected": 8.5,
            "baseline_samples": 12,
        },
        Detector.ISOLATION_FOREST: {
            "isolation_forest_score": -0.21,
            "magnitude_fence_kwh": 2.4,
            "features": ["energy_kwh", "peak_power_w", "hour", "is_weekend"],
        },
    }

    defaults = {
        "detector": detector,
        "severity": Severity.HIGH,
        "window_start": datetime(2026, 3, 9, 2, tzinfo=IST),
        "window_end": datetime(2026, 3, 9, 3, tzinfo=IST),
        "observed_kwh": Decimal("3.4000"),
        "expected_kwh": Decimal("0.4000"),
        "excess_kwh": Decimal("3.0000"),
        "score": 9.4,
        "title": "Test anomaly",
        "evidence": evidence_by_detector.get(detector, {}),
    }
    defaults.update(overrides)
    return Anomaly.objects.create(device=device, **defaults)
