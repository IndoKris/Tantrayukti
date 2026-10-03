#!/usr/bin/env python
"""
EcoTrack load simulator.

Generates realistic appliance load for a home and an office and either prints a
summary, writes CSV, or posts it to the API as real device telemetry.

    # Summary only, nothing written (the Phase 7 check):
    python simulator/run.py --days 7 --dry-run

    # CSV for offline work and ML training:
    python simulator/run.py --days 30 --csv data/load.csv

    # Inject faults for the anomaly demo:
    python simulator/run.py --days 14 --fault ac-left-on --fault night-load --dry-run

    # Post to a running backend, registering devices as needed:
    python simulator/run.py --days 2 --post --register --username demo --password ...

Stdlib only, so it runs on a bare Python with no virtualenv.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow `python simulator/run.py` and `python -m simulator.run` to both work.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import ApiError, EcoTrackClient  # noqa: E402
from generator import FAULTS, Series, generate  # noqa: E402
from profiles import SITES  # noqa: E402

#: Where --register caches device tokens so repeat runs reuse the same devices.
TOKEN_CACHE = Path(__file__).resolve().parent / ".tokens.json"

#: Readings per POST. Matches what an ESP32 flushing its buffer would send.
BATCH_SIZE = 500


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="simulator/run.py",
        description="Generate EcoTrack appliance load, with optional fault injection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days", type=float, default=7, help="Days of data to generate (default: 7)."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Sampling interval in seconds (default: 300).",
    )
    parser.add_argument(
        "--site",
        choices=[*SITES, "both"],
        default="both",
        help="Which site to simulate (default: both).",
    )
    parser.add_argument(
        "--seed", type=int, default=20261003, help="Random seed; runs are reproducible."
    )
    parser.add_argument(
        "--start",
        metavar="ISO8601",
        help="UTC start time. Default: now, rounded down, minus --days.",
    )
    parser.add_argument(
        "--fault",
        action="append",
        choices=FAULTS,
        default=[],
        metavar="NAME",
        dest="faults",
        help=f"Inject a fault; repeatable. One of: {', '.join(FAULTS)}.",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the per-appliance summary and write nothing.",
    )
    output.add_argument("--csv", metavar="PATH", help="Write all samples to a CSV file.")
    output.add_argument("--post", action="store_true", help="Post readings to the API.")

    api = parser.add_argument_group("api (with --post)")
    api.add_argument("--api-url", default="http://127.0.0.1:8000", help="Backend base URL.")
    api.add_argument(
        "--register",
        action="store_true",
        help="Create or reuse devices for each appliance and cache their tokens.",
    )
    api.add_argument("--username", help="User for --register (needs the manager role).")
    api.add_argument("--password", help="Password for --register.")
    api.add_argument(
        "--tokens",
        metavar="PATH",
        help="JSON file mapping '<site>.<appliance>' to a device token. "
        "Used instead of --register.",
    )

    args = parser.parse_args(argv)

    if args.days <= 0:
        parser.error("--days must be greater than 0.")
    if args.interval <= 0:
        parser.error("--interval must be greater than 0.")
    if not (args.dry_run or args.csv or args.post):
        # Printing a summary is the safe default: never silently do nothing.
        args.dry_run = True
    if args.post and not (args.register or args.tokens):
        parser.error("--post needs either --register or --tokens.")
    if args.register and not (args.username and args.password):
        parser.error("--register needs --username and --password.")

    return args


def resolve_start(args: argparse.Namespace) -> datetime:
    if args.start:
        parsed = datetime.fromisoformat(args.start)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    # End the series at the current interval boundary so the newest sample is "now".
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return now - timedelta(days=args.days)


# --- Output ---------------------------------------------------------------------


def print_summary(series_list: list[Series], args: argparse.Namespace, start: datetime) -> None:
    """Per-appliance counts, which is what the phase check asserts."""
    print(
        f"EcoTrack simulator | seed {args.seed} | {args.days:g} day(s) "
        f"@ {args.interval}s | start {start.isoformat()}"
    )
    print(f"faults: {', '.join(args.faults) if args.faults else 'none'}")

    for site_key in dict.fromkeys(s.site_key for s in series_list):
        site = SITES[site_key]
        rows = [s for s in series_list if s.site_key == site_key]
        print(f"\n{site.label}  (organisation: {site.organisation})")
        print(
            f"  {'appliance':<24}{'room':<16}{'samples':>9}{'kWh':>10}"
            f"{'mean W':>10}{'peak W':>10}{'faulted':>9}"
        )
        for row in rows:
            marker = " *" if row.appliance_key == "mains" else "  "
            print(
                f"{marker}{row.label:<24}{row.room:<16}{len(row.samples):>9}"
                f"{row.energy_kwh:>10.2f}{row.mean_w:>10.1f}{row.peak_w:>10.1f}"
                f"{row.faulted_samples:>9}"
            )

        appliances = [r for r in rows if r.appliance_key != "mains"]
        mains = next((r for r in rows if r.appliance_key == "mains"), None)
        total = sum(r.energy_kwh for r in appliances)
        print(f"  {'':<24}{'':<16}{'':>9}{'-' * 9:>10}")
        print(f"  {'appliance total':<24}{'':<16}{'':>9}{total:>10.2f} kWh")
        if mains:
            print(f"  {'mains (sum check)':<24}{'':<16}{'':>9}{mains.energy_kwh:>10.2f} kWh")

    grand = sum(r.energy_kwh for r in series_list if r.appliance_key != "mains")
    print(f"\ntotal across sites: {grand:.2f} kWh ({len(series_list)} series)")
    print("Sample data from a synthetic generator - not measured consumption.")


def write_csv(series_list: list[Series], path: str) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "site",
                "appliance",
                "room",
                "timestamp",
                "active_power_w",
                "energy_wh",
                "voltage_v",
                "current_a",
                "power_factor",
                "fault",
            ]
        )
        for series in series_list:
            for sample in series.samples:
                writer.writerow(
                    [
                        series.site_key,
                        series.appliance_key,
                        series.room,
                        sample.timestamp.isoformat(),
                        f"{sample.active_power_w:.2f}",
                        f"{sample.energy_wh:.4f}",
                        f"{sample.voltage_v:.2f}",
                        f"{sample.current_a:.3f}",
                        f"{sample.power_factor:.3f}",
                        sample.fault,
                    ]
                )
                written += 1

    print(f"Wrote {written} rows to {target}")
    return written


# --- Posting --------------------------------------------------------------------


def read_token_file(path: Path) -> dict:
    """
    Load a token map, failing with a readable message rather than a traceback.

    Raises `ApiError` so the caller's existing error handling reports it the same
    way as a failed request.
    """
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ApiError(f"Could not read token file {path}: {error}") from error

    if not raw:
        raise ApiError(f"Token file {path} is empty.")

    try:
        tokens = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ApiError(f"Token file {path} is not valid JSON: {error}") from error

    if not isinstance(tokens, dict):
        raise ApiError(
            f"Token file {path} must hold an object mapping "
            f"'<site>.<appliance>' to a device token."
        )
    return tokens


def load_token_cache() -> dict:
    if not TOKEN_CACHE.exists():
        return {}
    try:
        return read_token_file(TOKEN_CACHE)
    except ApiError as error:
        # A corrupt cache must not block a run; re-registering is cheap.
        print(f"  ! ignoring token cache: {error}", file=sys.stderr)
        return {}


def save_token_cache(tokens: dict) -> None:
    TOKEN_CACHE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def device_name(series: Series) -> str:
    return f"SIM {series.site_key}/{series.appliance_key}"


def register_devices(
    client: EcoTrackClient, series_list: list[Series], interval: int
) -> dict:
    """
    Create a device per series, reusing anything already registered.

    Tokens are cached in `.tokens.json` (gitignored) because the API reveals a
    raw token only at creation; a device that already exists needs a rotation
    instead, which requires the admin role.
    """
    tokens = load_token_cache()
    rooms = {(room["organisation"], room["name"]): room["id"] for room in client.rooms()}
    existing = {device["name"]: device for device in client.devices()}

    for series in series_list:
        key = f"{series.site_key}.{series.appliance_key}"
        if key in tokens:
            continue

        site = SITES[series.site_key]
        room_id = rooms.get((site.organisation, series.room))
        if room_id is None:
            print(
                f"  ! no room '{series.room}' in '{site.organisation}' - "
                f"run `python manage.py seed_spaces` first. Skipping {key}.",
                file=sys.stderr,
            )
            continue

        name = device_name(series)
        if name in existing:
            try:
                tokens[key] = client.rotate_token(existing[name]["id"])
                print(f"  rotated token for existing device {name}")
            except ApiError as error:
                print(
                    f"  ! {name} already exists and its token could not be rotated "
                    f"({error}). Needs the admin role. Skipping {key}.",
                    file=sys.stderr,
                )
                continue
        else:
            kind = "mains" if series.appliance_key == "mains" else "appliance"
            created = client.create_device(room_id, name, kind, interval)
            tokens[key] = created["token"]
            print(f"  registered {name} in room {series.room}")

    save_token_cache(tokens)
    return tokens


def post_series(client: EcoTrackClient, series_list: list[Series], tokens: dict) -> int:
    """
    Post every series in batches, oldest first.

    Returns the number of series that failed, so the process can exit non-zero.
    A silent exit 0 after a failed upload would let a scripted run believe the
    data landed.
    """
    total_created = total_duplicate = failures = 0

    for series in series_list:
        key = f"{series.site_key}.{series.appliance_key}"
        token = tokens.get(key)
        if not token:
            print(f"  ! no token for {key}; skipping", file=sys.stderr)
            failures += 1
            continue

        payloads = [sample.as_payload() for sample in series.samples]
        created = duplicates = 0

        for index in range(0, len(payloads), BATCH_SIZE):
            batch = payloads[index : index + BATCH_SIZE]
            remaining = len(payloads) - (index + len(batch))
            try:
                result = client.post_readings(token, batch, buffer_count=remaining)
            except ApiError as error:
                print(f"  ! {key} batch failed: {error}", file=sys.stderr)
                if error.payload:
                    print(f"    {error.payload}", file=sys.stderr)
                failures += 1
                break
            created += result["created"]
            duplicates += result["duplicates"]

        print(f"  {key:<24} created {created:>6}  duplicates {duplicates:>6}")
        total_created += created
        total_duplicate += duplicates

    print(f"\nPosted {total_created} new readings ({total_duplicate} already present).")
    if failures:
        print(f"{failures} of {len(series_list)} series failed to upload.", file=sys.stderr)
    return failures


# --- Entry point ----------------------------------------------------------------


def main(argv=None) -> int:
    args = parse_args(argv)
    start = resolve_start(args)
    site_keys = list(SITES) if args.site == "both" else [args.site]

    series_list = generate(
        site_keys=site_keys,
        start=start,
        days=args.days,
        interval_seconds=args.interval,
        seed=args.seed,
        fault_names=tuple(args.faults),
    )

    if args.dry_run or not (args.csv or args.post):
        print_summary(series_list, args, start)

    if args.csv:
        write_csv(series_list, args.csv)

    if args.post:
        client = EcoTrackClient(base_url=args.api_url)
        try:
            if args.register:
                user = client.login(args.username, args.password)
                print(f"Logged in as {user['username']} ({user['role']})")
                tokens = register_devices(client, series_list, args.interval)
            else:
                tokens = read_token_file(Path(args.tokens))
            print("\nPosting readings:")
            if post_series(client, series_list, tokens):
                return 1
        except ApiError as error:
            print(f"error: {error}", file=sys.stderr)
            if error.payload:
                print(f"  {error.payload}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
