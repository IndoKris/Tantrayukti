# EcoTrack ESP32 true-power meter

Samples mains voltage and current, computes **real** power, and posts to
`POST /api/readings/` every 30 seconds. Buffers to flash during an outage and
replays oldest-first when the network returns.

> ⚠️ **Mains voltage is lethal.** The ZMPT101B connects directly to live and
> neutral. Do not wire it with the circuit energised, do not work on it alone,
> and if you are not confident with mains wiring, have an electrician do this
> part. The SCT-013 clamp is the safe sensor — it clips *around* a conductor
> without contacting it — so prefer current-only measurement if you are at all
> unsure, and set a fixed nominal voltage instead.

## Build

```bash
cd firmware
cp include/config.example.h include/config.h   # then edit it
pio run                                        # compile
pio run -t upload                              # flash
pio device monitor                             # watch it
```

`include/config.h` is gitignored: it holds the WiFi password and the device
token.

## Getting a device token

Register the device through the API (needs the manager role). The raw token is
shown **once** — only its SHA-256 hash is stored server-side, so a lost token
must be rotated by an admin, not looked up.

```bash
curl -X POST "$API/api/devices/" \
  -H "Authorization: Bearer <jwt>" -H 'Content-Type: application/json' \
  -d '{"room": 3, "name": "Kitchen meter", "kind": "mains",
       "sample_interval_seconds": 30}'
```

Put the `token` from the response into `DEVICE_TOKEN`, and keep
`SAMPLE_INTERVAL_SECONDS` equal to the `sample_interval_seconds` you registered
— the server derives its online/offline threshold from that figure, so a
mismatch makes a healthy device look offline.

## Wiring

| Signal | ESP32 pin | Notes |
| --- | --- | --- |
| ZMPT101B OUT | GPIO 34 | ADC1 input-only pin |
| SCT-013 OUT | GPIO 35 | ADC1 input-only pin |
| ZMPT101B VCC | 3V3 | |
| SCT-013 bias | 3V3 / GND divider | see below |
| Common ground | GND | sensor grounds must share the ESP32 ground |

Use **ADC1** pins (32–39). ADC2 is unavailable while WiFi is active on the
ESP32, so a sensor on an ADC2 pin reads garbage exactly when you need to upload.

### SCT-013 burden and bias

```
        SCT-013 (100A : 50mA)
         ┌───────────────┐
    ─────┤ clamp around  ├─────  one conductor only: live OR neutral,
         │ ONE conductor │       never both (the fields would cancel)
         └───┬───────┬───┘
             │       │
            [R]     burden resistor, 22 Ω (omit for an SCT-013-030,
             │      which has one built in)
    3V3 ──[10k]──┬──┴── GPIO 35
                 │
    GND ──[10k]──┘      divider biases the AC swing to ~1.65 V so the
             │          ADC sees the whole waveform
          [10µF]        decoupling to ground
             │
            GND
```

Clamping both live and neutral together reads ~0 A, because the two currents are
equal and opposite. This is the single most common wiring mistake.

## Calibration — do this, or the numbers are meaningless

The firmware reports `"calibrated": false` and tags its uploads
`1.0.0-uncalibrated` until you set `CALIBRATION_CONFIRMED 1`. That is
deliberate: an uncalibrated meter produces confident, wrong readings, and the
project's honesty rule means it should say so rather than look authoritative.

**Voltage.** Measure the supply with a multimeter, then adjust
`VOLTAGE_CALIBRATION` until the serial output matches.

**Current.** For an SCT-013-000 (100 A : 50 mA) with a 22 Ω burden:

```
turns       = 100 A / 0.05 A = 2000
calibration = turns / burden = 2000 / 22 = 90.9
```

Then check against a known load — a 1000 W heater on a 230 V supply should read
about 4.3 A and about 1000 W. Adjust `CURRENT_CALIBRATION` by the ratio of
expected to observed.

**Phase.** `PHASE_CALIBRATION` corrects the timing offset between the two
sensors. A purely resistive load (an incandescent bulb or a heater) has a power
factor of ~1.0; adjust until the reported power factor reads near 1.00 for one.
If it reads 0.7 on a heater, the phase is wrong, not the heater.

## Why real power, not V × I

EmonLib integrates instantaneous V × I over whole mains cycles to get **real
power** in watts. `V_rms × I_rms` is *apparent* power in VA, and for a reactive
load — a motor, a fridge compressor, an AC — it overstates consumption
significantly, because current lags voltage and the two peaks do not coincide.

The server enforces this: a reading whose `active_power_w` exceeds
`voltage_v × current_a` (plus a 10% tolerance) is rejected with a 400. A
mis-wired or mis-scaled clamp is therefore caught rather than believed.

## Units sent

| Field | Unit | Meaning |
| --- | --- | --- |
| `active_power_w` | W | Real power, instantaneous |
| `energy_wh` | Wh | Energy for **this interval only** |
| `voltage_v` | V | RMS |
| `current_a` | A | RMS |
| `power_factor` | 0–1 | real / apparent |

`energy_wh` is interval energy, never a cumulative meter total. The server sums
these into kWh, so sending a running total would double-count on every upload.

## Offline buffering

| Behaviour | Detail |
| --- | --- |
| Capacity | `BUFFER_CAPACITY` readings (240 at 30 s ≈ 2 hours) |
| Storage | NVS flash, so a reboot mid-outage loses nothing |
| Order | Oldest first, so a backfill arrives in sample order |
| Overflow | Oldest row is overwritten and logged |
| Confirmation | Rows are dropped only after the server acknowledges them |
| Backlog | `buffer_count` is sent with each batch, so the digital twin shows the real queue depth |

Readings are **always queued first**, then an upload is attempted. Posting
directly and buffering only on failure would lose a reading whenever a POST hung
past the next interval.

Replaying is safe: the server's `(device, timestamp)` uniqueness means a retry
after a partially-failed upload creates no duplicates, and the response reports
`created` versus `duplicates`.

The buffer is written to flash as one block rather than row by row, because NVS
has limited erase cycles.

## Error handling

| Server response | Firmware behaviour |
| --- | --- |
| 200 / 201 | Drop the batch from the buffer |
| 400 / 422 | **Drop** the batch and log why — a bad reading must not wedge the queue forever |
| 401 | Keep buffering and log that the token is wrong or rotated |
| 5xx / timeout | Keep buffering and retry next interval |

No reading is sent before NTP has synced. An untrustworthy timestamp is worse
than a gap, and the server rejects anything more than 5 minutes in the future.

## TLS

`HTTPClient` over plain `http://` sends the device token in clear text. On
anything beyond a trusted LAN, use `https://` with `WiFiClientSecure` and pin
your server's certificate. The token is a bearer credential: whoever holds it
can post readings as this device. The server stores only its hash and compares
in constant time, but that protects the *database*, not the wire — see
`backend/telemetry/authentication.py`, which states this limitation rather than
implying the transport is secure.

## Build status in this repository

`pio run` has **not** been executed here — PlatformIO is not installed in this
environment, so the firmware is committed unbuilt. The source is complete and
the dependencies are pinned in `platformio.ini`; compile it before flashing.
