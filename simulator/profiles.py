"""
Appliance load profiles for the EcoTrack simulator.

Everything here is stdlib-only and fully determined by the seed, so two runs with
the same arguments produce byte-identical output. That matters because Phase 13
evaluates anomaly detection against faults injected here: if the data moved
between runs, the precision/recall numbers would not be comparable.

Power is always in **watts**. Energy is derived by the generator from power over
the sampling interval, in **watt-hours**, matching `telemetry.Reading`.

The behaviour classes are deliberately simple - a duty-cycling fridge, scheduled
lighting, a thermostatic AC driven by a sinusoidal outdoor-temperature proxy, an
occasional washer and a constant standby draw. The goal is a load curve with
realistic *shape* (diurnal peaks, weekday/weekend difference, cycling baseload),
not a validated building-physics model. Nothing here is presented as measured
data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

# Nagpur-ish daily temperature swing used as the AC driver. A proxy, not a forecast.
TEMP_MIN_C = 24.0
TEMP_MAX_C = 38.0
TEMP_PEAK_HOUR = 15  # hottest part of the afternoon


def outdoor_temp_c(when: datetime) -> float:
    """Sinusoidal daily temperature proxy, peaking mid-afternoon."""
    mid = (TEMP_MAX_C + TEMP_MIN_C) / 2
    swing = (TEMP_MAX_C - TEMP_MIN_C) / 2
    hours = when.hour + when.minute / 60
    return mid + swing * math.sin((hours - TEMP_PEAK_HOUR) / 24 * 2 * math.pi + math.pi / 2)


def is_weekend(when: datetime) -> bool:
    return when.weekday() >= 5


def in_windows(when: datetime, windows: list[tuple[float, float]]) -> bool:
    """True when the time of day falls inside any (start_hour, end_hour) window."""
    hours = when.hour + when.minute / 60
    return any(start <= hours < end for start, end in windows)


# --- Behaviours ----------------------------------------------------------------


@dataclass
class Behaviour:
    """Base class: return the watts drawn at `when`."""

    def power_w(self, when: datetime, rng, state: dict) -> float:
        raise NotImplementedError


@dataclass
class AlwaysOn(Behaviour):
    """Constant draw, e.g. a router, a server or aggregate standby."""

    rated_w: float
    jitter: float = 0.05

    def power_w(self, when, rng, state) -> float:
        return self.rated_w * (1 + rng.uniform(-self.jitter, self.jitter))


@dataclass
class Cycling(Behaviour):
    """
    Thermostatic cycling independent of occupancy, e.g. a refrigerator.

    Holds its on/off state across samples so the compressor runs in realistic
    blocks rather than flickering every sample.
    """

    rated_w: float
    standby_w: float = 2.0
    duty: float = 0.35
    on_minutes: float = 18.0

    def power_w(self, when, rng, state) -> float:
        remaining = state.get("remaining", 0.0)
        running = state.get("running", False)
        step = state["interval_minutes"]

        if remaining <= 0:
            running = not running
            if running:
                remaining = self.on_minutes * rng.uniform(0.8, 1.2)
            else:
                off = self.on_minutes * (1 - self.duty) / self.duty
                remaining = off * rng.uniform(0.8, 1.2)

        state["remaining"] = remaining - step
        state["running"] = running

        if not running:
            return self.standby_w
        # Compressors draw a little more when the ambient is hotter.
        warmth = 1 + max(0.0, (outdoor_temp_c(when) - 30) / 100)
        return self.rated_w * warmth * rng.uniform(0.95, 1.05)


@dataclass
class Scheduled(Behaviour):
    """
    On during set hours, e.g. lighting, office HVAC or workstations.

    `weekend_windows` defaults to empty, which is what makes an office load curve
    collapse at the weekend.
    """

    rated_w: float
    standby_w: float = 0.0
    weekday_windows: list[tuple[float, float]] = field(default_factory=list)
    weekend_windows: list[tuple[float, float]] = field(default_factory=list)
    #: Fraction of rated power actually drawn, to model partial use.
    load_factor: float = 0.85

    def power_w(self, when, rng, state) -> float:
        windows = self.weekend_windows if is_weekend(when) else self.weekday_windows
        if not in_windows(when, windows):
            return self.standby_w
        return self.rated_w * self.load_factor * rng.uniform(0.85, 1.1)


@dataclass
class Thermostatic(Behaviour):
    """
    Air conditioning: runs when it is hot *and* someone is there.

    This is the appliance the "left on" fault targets, because an AC running in
    an empty space overnight is both common and expensive.
    """

    rated_w: float
    standby_w: float = 3.0
    setpoint_c: float = 26.0
    weekday_windows: list[tuple[float, float]] = field(default_factory=list)
    weekend_windows: list[tuple[float, float]] = field(default_factory=list)

    def power_w(self, when, rng, state) -> float:
        windows = self.weekend_windows if is_weekend(when) else self.weekday_windows
        occupied = in_windows(when, windows)
        if not occupied:
            return self.standby_w

        excess = outdoor_temp_c(when) - self.setpoint_c
        if excess <= 0:
            return self.standby_w
        # Compressor modulates with how far above setpoint the ambient is.
        duty = min(1.0, 0.35 + excess / 12)
        return self.rated_w * duty * rng.uniform(0.9, 1.05)


@dataclass
class Intermittent(Behaviour):
    """
    Occasional long runs, e.g. a washing machine or water heater.

    Starts are drawn per day so the weekly count is right on average without a
    fixed, unrealistic schedule.
    """

    rated_w: float
    standby_w: float = 1.0
    runs_per_week: float = 3.0
    run_minutes: float = 55.0
    earliest_hour: float = 7.0
    latest_hour: float = 21.0

    def power_w(self, when, rng, state) -> float:
        step = state["interval_minutes"]
        remaining = state.get("remaining", 0.0)

        if remaining > 0:
            state["remaining"] = remaining - step
            return self.rated_w * rng.uniform(0.9, 1.05)

        # Decide starts once per day, then hold the plan for that day.
        day = when.date()
        if state.get("day") != day:
            state["day"] = day
            state["starts"] = []
            # Thin the weekly rate down to this day, allowing more at weekends.
            chance = self.runs_per_week / 7 * (1.6 if is_weekend(when) else 0.85)
            while chance > 0:
                if rng.random() < min(chance, 1.0):
                    state["starts"].append(
                        rng.uniform(self.earliest_hour, self.latest_hour)
                    )
                chance -= 1.0

        hours = when.hour + when.minute / 60
        for start in list(state.get("starts", [])):
            if start <= hours < start + step / 60:
                state["starts"].remove(start)
                state["remaining"] = self.run_minutes
                return self.rated_w * rng.uniform(0.9, 1.05)

        return self.standby_w


# --- Appliance and site catalogue ---------------------------------------------


@dataclass
class Appliance:
    key: str
    label: str
    behaviour: Behaviour
    #: Typical power factor. Motors and compressors are well below 1.
    power_factor: float = 0.95
    #: Room name to attach the device to, matched against `seed_spaces` output.
    room: str = ""

    def power_w(self, when: datetime, rng, state: dict) -> float:
        return max(0.0, self.behaviour.power_w(when, rng, state))


@dataclass
class Site:
    key: str
    label: str
    #: Organisation name created by `manage.py seed_spaces`.
    organisation: str
    appliances: list[Appliance]
    nominal_voltage_v: float = 230.0


HOME = Site(
    key="home",
    label="Sample home",
    organisation="Sample Home",
    appliances=[
        Appliance(
            key="fridge",
            label="Refrigerator",
            room="Kitchen",
            power_factor=0.78,
            behaviour=Cycling(rated_w=140, standby_w=2, duty=0.38, on_minutes=20),
        ),
        Appliance(
            key="ac",
            label="Bedroom AC",
            room="Bedroom 1",
            power_factor=0.88,
            behaviour=Thermostatic(
                rated_w=1500,
                setpoint_c=26.0,
                # Home evenings and overnight, later at weekends.
                weekday_windows=[(13.0, 16.0), (21.0, 24.0), (0.0, 6.5)],
                weekend_windows=[(11.0, 17.0), (21.0, 24.0), (0.0, 7.5)],
            ),
        ),
        Appliance(
            key="lights",
            label="Lighting",
            room="Living room",
            power_factor=0.95,
            behaviour=Scheduled(
                rated_w=180,
                standby_w=0,
                weekday_windows=[(6.0, 8.0), (18.5, 23.0)],
                weekend_windows=[(7.0, 9.5), (18.0, 23.5)],
                load_factor=0.8,
            ),
        ),
        Appliance(
            key="washer",
            label="Washing machine",
            room="Kitchen",
            power_factor=0.82,
            behaviour=Intermittent(
                rated_w=520, runs_per_week=4, run_minutes=55, earliest_hour=8, latest_hour=19
            ),
        ),
        Appliance(
            key="tv",
            label="Television",
            room="Living room",
            power_factor=0.92,
            behaviour=Scheduled(
                rated_w=110,
                standby_w=4,
                weekday_windows=[(19.0, 23.0)],
                weekend_windows=[(10.0, 13.0), (18.0, 23.5)],
                load_factor=0.95,
            ),
        ),
        Appliance(
            key="standby",
            label="Standby and always-on",
            room="Living room",
            power_factor=0.9,
            behaviour=AlwaysOn(rated_w=34),
        ),
    ],
)


OFFICE = Site(
    key="office",
    label="Tantrayukti office",
    organisation="Tantrayukti Office",
    appliances=[
        Appliance(
            key="hvac",
            label="Office HVAC",
            room="Open workspace",
            power_factor=0.86,
            behaviour=Thermostatic(
                rated_w=3600,
                setpoint_c=25.0,
                weekday_windows=[(9.0, 19.0)],
                weekend_windows=[],
            ),
        ),
        Appliance(
            key="lights",
            label="Office lighting",
            room="Open workspace",
            power_factor=0.96,
            behaviour=Scheduled(
                rated_w=850,
                standby_w=0,
                weekday_windows=[(8.5, 19.5)],
                weekend_windows=[(10.0, 13.0)],
                load_factor=0.9,
            ),
        ),
        Appliance(
            key="workstations",
            label="Workstations",
            room="Open workspace",
            power_factor=0.93,
            behaviour=Scheduled(
                rated_w=1250,
                standby_w=65,
                weekday_windows=[(9.0, 19.0)],
                weekend_windows=[],
                load_factor=0.7,
            ),
        ),
        Appliance(
            key="server",
            label="Server rack",
            room="Server room",
            power_factor=0.97,
            behaviour=AlwaysOn(rated_w=420, jitter=0.08),
        ),
        Appliance(
            key="canteen_fridge",
            label="Canteen refrigerator",
            room="Canteen",
            power_factor=0.76,
            behaviour=Cycling(rated_w=210, standby_w=3, duty=0.42, on_minutes=22),
        ),
        Appliance(
            key="standby",
            label="Standby and always-on",
            room="Reception",
            power_factor=0.9,
            behaviour=AlwaysOn(rated_w=95),
        ),
    ],
)


SITES: dict[str, Site] = {site.key: site for site in (HOME, OFFICE)}
