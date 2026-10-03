"""
Time-series generation and fault injection.

A run produces, for each site, one series per appliance plus a `mains` series
that is the sum of them. Both are needed downstream: per-appliance series drive
device-level anomaly detection (Phase 13), and the mains aggregate is what NILM
disaggregates (Phase 23).

**Faults are labelled.** Every sample records whether a fault was active and
which one, because Phase 13 measures precision/recall of the detector against
exactly these labels. A fault that was injected but not recorded would make the
evaluation meaningless.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from profiles import SITES, Site

# --- Faults --------------------------------------------------------------------

#: Fault identifiers accepted by --fault.
FAULTS = ("ac-left-on", "night-load", "baseload-jump")

#: A fault starts this far into the run, so there is clean history to learn from
#: before anything goes wrong.
FAULT_START_FRACTION = 0.6

#: Extra constant load for the baseload-jump fault, in watts.
BASELOAD_JUMP_W = 420.0

#: The night-load fault runs between these hours.
NIGHT_LOAD_HOURS = (1.0, 5.0)
NIGHT_LOAD_W = 900.0


@dataclass
class FaultPlan:
    """Which faults are active, and from when."""

    names: tuple[str, ...] = ()
    starts_at: datetime | None = None

    def active(self, name: str, when: datetime) -> bool:
        if name not in self.names:
            return False
        return self.starts_at is None or when >= self.starts_at


# --- Samples -------------------------------------------------------------------


@dataclass
class Sample:
    timestamp: datetime
    active_power_w: float
    energy_wh: float
    voltage_v: float
    current_a: float
    power_factor: float
    fault: str = ""

    def as_payload(self) -> dict:
        """The shape `POST /api/readings/` expects."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "active_power_w": f"{self.active_power_w:.2f}",
            "energy_wh": f"{self.energy_wh:.4f}",
            "voltage_v": f"{self.voltage_v:.2f}",
            "current_a": f"{self.current_a:.3f}",
            "power_factor": f"{self.power_factor:.3f}",
            "source": "simulator",
        }


@dataclass
class Series:
    """One device's worth of samples, plus the totals the CLI reports."""

    site_key: str
    appliance_key: str
    label: str
    room: str
    samples: list[Sample] = field(default_factory=list)

    @property
    def energy_kwh(self) -> float:
        return sum(sample.energy_wh for sample in self.samples) / 1000

    @property
    def peak_w(self) -> float:
        return max((sample.active_power_w for sample in self.samples), default=0.0)

    @property
    def mean_w(self) -> float:
        if not self.samples:
            return 0.0
        return sum(sample.active_power_w for sample in self.samples) / len(self.samples)

    @property
    def faulted_samples(self) -> int:
        return sum(1 for sample in self.samples if sample.fault)


def _electrical(power_w: float, voltage_v: float, power_factor: float) -> tuple[float, float]:
    """
    Derive RMS current from active power.

    `P = V x I x pf`, so `I = P / (V x pf)`. Returned alongside the voltage so the
    posted reading is internally consistent and passes the server-side check that
    active power cannot exceed apparent power.
    """
    if power_w <= 0:
        return 0.0, power_factor
    current_a = power_w / (voltage_v * power_factor)
    return current_a, power_factor


def generate_site(
    site: Site,
    start: datetime,
    days: float,
    interval_seconds: int,
    seed: int,
    faults: FaultPlan,
) -> list[Series]:
    """
    Generate every appliance series for one site, plus the mains aggregate.

    Each appliance gets its own seeded RNG derived from the run seed and the
    appliance key, so adding an appliance does not shift the numbers produced for
    the others.
    """
    interval = timedelta(seconds=interval_seconds)
    interval_hours = interval_seconds / 3600
    steps = int(days * 24 * 3600 / interval_seconds)

    series_by_key: dict[str, Series] = {}
    rngs: dict[str, random.Random] = {}
    states: dict[str, dict] = {}

    for appliance in site.appliances:
        series_by_key[appliance.key] = Series(
            site_key=site.key,
            appliance_key=appliance.key,
            label=appliance.label,
            room=appliance.room,
        )
        rngs[appliance.key] = random.Random(f"{seed}:{site.key}:{appliance.key}")
        states[appliance.key] = {"interval_minutes": interval_seconds / 60}

    mains = Series(
        site_key=site.key,
        appliance_key="mains",
        label="Whole-site mains",
        room=site.appliances[0].room if site.appliances else "",
    )
    mains_rng = random.Random(f"{seed}:{site.key}:mains")

    for step in range(steps):
        when = start + interval * step
        total_w = 0.0
        total_apparent = 0.0
        active_faults: list[str] = []

        for appliance in site.appliances:
            rng = rngs[appliance.key]
            power_w = appliance.power_w(when, rng, states[appliance.key])
            fault_label = ""

            # AC left on: the unit keeps running outside occupied hours.
            if appliance.key in {"ac", "hvac"} and faults.active("ac-left-on", when):
                idle = power_w < appliance.behaviour.rated_w * 0.1
                if idle:
                    power_w = appliance.behaviour.rated_w * rng.uniform(0.55, 0.75)
                    fault_label = "ac-left-on"

            # Baseload jump: the always-on draw steps up and stays up.
            if appliance.key == "standby" and faults.active("baseload-jump", when):
                power_w += BASELOAD_JUMP_W * rng.uniform(0.95, 1.05)
                fault_label = "baseload-jump"

            # Night load: something runs in the small hours that should not.
            if appliance.key in {"lights", "workstations"} and faults.active(
                "night-load", when
            ):
                hours = when.hour + when.minute / 60
                if NIGHT_LOAD_HOURS[0] <= hours < NIGHT_LOAD_HOURS[1]:
                    power_w += NIGHT_LOAD_W * rng.uniform(0.9, 1.1)
                    fault_label = "night-load"

            voltage = site.nominal_voltage_v * rng.uniform(0.985, 1.015)
            current, power_factor = _electrical(power_w, voltage, appliance.power_factor)

            series_by_key[appliance.key].samples.append(
                Sample(
                    timestamp=when,
                    active_power_w=power_w,
                    energy_wh=power_w * interval_hours,
                    voltage_v=voltage,
                    current_a=current,
                    power_factor=power_factor,
                    fault=fault_label,
                )
            )

            total_w += power_w
            total_apparent += power_w / appliance.power_factor if power_w > 0 else 0.0
            if fault_label:
                active_faults.append(fault_label)

        # Mains: the site total, with a power factor blended from the mix of loads.
        mains_pf = min(0.99, total_w / total_apparent) if total_apparent > 0 else 0.95
        mains_voltage = site.nominal_voltage_v * mains_rng.uniform(0.985, 1.015)
        mains_current, _ = _electrical(total_w, mains_voltage, mains_pf)
        mains.samples.append(
            Sample(
                timestamp=when,
                active_power_w=total_w,
                energy_wh=total_w * interval_hours,
                voltage_v=mains_voltage,
                current_a=mains_current,
                power_factor=mains_pf,
                fault=",".join(sorted(set(active_faults))),
            )
        )

    return [*series_by_key.values(), mains]


def generate(
    site_keys: list[str],
    start: datetime,
    days: float,
    interval_seconds: int,
    seed: int,
    fault_names: tuple[str, ...] = (),
) -> list[Series]:
    """Generate every requested site. Faults begin partway in, leaving clean history."""
    fault_start = (
        start + timedelta(days=days * FAULT_START_FRACTION) if fault_names else None
    )
    plan = FaultPlan(names=tuple(fault_names), starts_at=fault_start)

    results: list[Series] = []
    for key in site_keys:
        results.extend(
            generate_site(SITES[key], start, days, interval_seconds, seed, plan)
        )
    return results
