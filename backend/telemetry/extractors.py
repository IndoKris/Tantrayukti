"""
Extractors for chat-based ingestion.

A person sends "AC ran 4 hours today" or a photo of a meter, and something has to
turn that into a structured reading. That something is a provider behind this
interface.

**Mock extractors, honestly labelled.** No Gemini or Whisper credentials are
configured, so the registered providers are deterministic mocks:
`MockTextExtractor` parses with regular expressions, and the image and audio
extractors decline rather than inventing a value. Every result carries
`provider`, `is_mock` and `confidence`, and the ingestion endpoint refuses to
store anything a mock could not actually read.

That last point is the one that matters: a mock that returned a plausible-looking
number for a photo it cannot see would quietly poison the dataset. Declining is
the honest behaviour, and the API says so with a 422 rather than a silent zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol

#: Plausible bounds for a chat-reported figure. Outside these it is a typo or a
#: unit mix-up, not a reading.
MAX_PLAUSIBLE_KWH = Decimal("2000")
MAX_PLAUSIBLE_HOURS = Decimal("24")
MAX_PLAUSIBLE_POWER_W = Decimal("20000")


@dataclass
class Extraction:
    """What an extractor produced, and how much to trust it."""

    #: Energy in kWh, when the message implied one.
    energy_kwh: Decimal | None = None
    #: Instantaneous power in watts, when stated.
    power_w: Decimal | None = None
    #: Runtime in hours, when stated.
    hours: Decimal | None = None
    appliance: str = ""

    provider: str = ""
    is_mock: bool = True
    confidence: float = 0.0
    #: False when the extractor could not read the input at all.
    succeeded: bool = False
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "succeeded": self.succeeded,
            "energy_kwh": self.energy_kwh,
            "power_w": self.power_w,
            "hours": self.hours,
            "appliance": self.appliance,
            "provider": self.provider,
            "is_mock": self.is_mock,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "warnings": self.warnings,
        }


class Extractor(Protocol):
    """One modality's extractor."""

    name: str
    modality: str
    is_mock: bool

    def extract(self, payload: dict) -> Extraction: ...


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


@dataclass
class MockTextExtractor:
    """
    Regular-expression extractor for short English messages.

    Deterministic, so a test can rely on it, and it only reports what it
    actually matched. An unparseable message fails rather than guessing.
    """

    name: str = "mock-text-regex"
    modality: str = "text"
    is_mock: bool = True

    #: Appliance words it recognises, longest first so "water heater" wins over "heater".
    APPLIANCES = (
        "water heater",
        "washing machine",
        "air conditioner",
        "refrigerator",
        "microwave",
        "geyser",
        "fridge",
        "heater",
        "washer",
        "lights",
        "light",
        "fan",
        "tv",
        "ac",
    )

    def extract(self, payload: dict) -> Extraction:
        text = str(payload.get("text") or "").strip()
        if not text:
            return Extraction(
                provider=self.name,
                reason="No text supplied.",
            )

        lowered = text.lower()
        result = Extraction(provider=self.name, is_mock=True)

        appliance = next((word for word in self.APPLIANCES if word in lowered), "")
        result.appliance = appliance

        kwh = re.search(r"(\d+(?:\.\d+)?)\s*(?:kwh|kilowatt[- ]?hours?|units?)\b", lowered)
        watts = re.search(r"(\d+(?:\.\d+)?)\s*(?:w|watts?)\b", lowered)
        hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)\b", lowered)

        if kwh:
            result.energy_kwh = _decimal(kwh.group(1))
        if watts:
            result.power_w = _decimal(watts.group(1))
        if hours:
            result.hours = _decimal(hours.group(1))

        # Power plus runtime implies energy, which is the common phrasing
        # ("the 1500 W AC ran for 4 hours").
        if result.energy_kwh is None and result.power_w and result.hours:
            result.energy_kwh = (
                result.power_w * result.hours / Decimal("1000")
            ).quantize(Decimal("0.0001"))
            result.warnings.append(
                f"Energy derived from {result.power_w} W x {result.hours} h, "
                f"not stated directly."
            )

        if result.energy_kwh is None:
            result.reason = (
                "Could not find an energy figure. Say how many kWh, or give a "
                "wattage and a runtime (for example '1500 W AC ran 4 hours')."
            )
            return result

        result.succeeded = True
        # Confidence reflects how much was read directly rather than inferred.
        result.confidence = 0.8 if kwh else 0.55
        if not appliance:
            result.confidence -= 0.1
            result.warnings.append("No appliance recognised in the message.")

        return result


@dataclass
class DecliningExtractor:
    """
    Stands in for a vision or speech provider that is not configured.

    It **declines** rather than returning a number. The alternative - a mock that
    emits a plausible value for an image it cannot see - would put fabricated
    readings into the database, which the project's honesty rule forbids.
    """

    modality: str
    provider_name: str
    name: str = ""
    is_mock: bool = True

    def __post_init__(self):
        self.name = f"mock-{self.modality}-declining"

    def extract(self, payload: dict) -> Extraction:
        return Extraction(
            provider=self.name,
            is_mock=True,
            succeeded=False,
            confidence=0.0,
            reason=(
                f"No {self.provider_name} credentials are configured, so "
                f"{self.modality} input cannot be read. A mock value is not "
                f"returned, because an invented reading is worse than none. "
                f"Send the figure as text instead, for example "
                f"'AC used 6 kWh today'."
            ),
        )


#: Registered providers, by modality.
EXTRACTORS: dict[str, Extractor] = {
    "text": MockTextExtractor(),
    "image": DecliningExtractor(modality="image", provider_name="Gemini Vision"),
    "audio": DecliningExtractor(modality="audio", provider_name="Whisper"),
}


def extract(modality: str, payload: dict) -> Extraction:
    """Run the extractor for a modality, or report that none is registered."""
    extractor = EXTRACTORS.get(modality)
    if extractor is None:
        return Extraction(
            provider="none",
            reason=f"No extractor for modality '{modality}'. "
            f"One of: {', '.join(sorted(EXTRACTORS))}.",
        )
    return extractor.extract(payload)


def validate_ranges(extraction: Extraction) -> list[str]:
    """
    Range-check an extraction, returning the reasons it is implausible.

    A chat figure is the least trustworthy input the system takes, so it is
    checked harder than device telemetry: a typo turning 6 kWh into 600 would
    otherwise distort a whole month of rollups.
    """
    problems = []

    if extraction.energy_kwh is not None:
        if extraction.energy_kwh < 0:
            problems.append("Energy cannot be negative.")
        elif extraction.energy_kwh > MAX_PLAUSIBLE_KWH:
            problems.append(
                f"{extraction.energy_kwh} kWh exceeds the {MAX_PLAUSIBLE_KWH} kWh "
                f"plausibility limit for a single chat report."
            )

    if extraction.hours is not None and not (
        Decimal("0") <= extraction.hours <= MAX_PLAUSIBLE_HOURS
    ):
        problems.append(
            f"{extraction.hours} hours is outside 0-{MAX_PLAUSIBLE_HOURS} for one day."
        )

    if extraction.power_w is not None and not (
        Decimal("0") <= extraction.power_w <= MAX_PLAUSIBLE_POWER_W
    ):
        problems.append(
            f"{extraction.power_w} W is outside 0-{MAX_PLAUSIBLE_POWER_W} for a "
            f"single appliance."
        )

    return problems


def spread_over_interval(
    energy_kwh: Decimal, hours: Decimal | None, interval_seconds: int
) -> list[tuple[timedelta, Decimal]]:
    """
    Turn a lump of reported energy into interval readings.

    A chat report covers a span, not an instant, so storing it as one reading at
    one timestamp would create a spike that the Phase 13 detector would rightly
    flag as an anomaly. Spreading it evenly across the stated runtime is an
    assumption, and it is returned as one.
    """
    span_hours = hours if hours and hours > 0 else Decimal("1")
    steps = max(1, int(span_hours * 3600 / interval_seconds))
    per_step = (energy_kwh / steps).quantize(Decimal("0.000001"))

    return [
        (timedelta(seconds=interval_seconds * index), per_step) for index in range(steps)
    ]
