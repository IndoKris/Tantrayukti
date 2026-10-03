// EcoTrack ESP32 configuration.
//
// Copy this file to `config.h` and fill it in. `config.h` is gitignored because
// it holds the WiFi password and the device token.
//
//     cp include/config.example.h include/config.h
//
// Get a device token by registering the device through the API (manager role):
//
//     curl -X POST "$API/api/devices/" \
//       -H "Authorization: Bearer <jwt>" -H 'Content-Type: application/json' \
//       -d '{"room": 3, "name": "Kitchen meter", "kind": "mains",
//            "sample_interval_seconds": 30}'
//
// The response contains the raw token **once**. It is stored only as a hash
// server-side, so if it is lost an admin must rotate it rather than look it up.

#pragma once

// --- Network ----------------------------------------------------------------

#define WIFI_SSID "your-network"
#define WIFI_PASSWORD "your-password"

// Seconds to wait for WiFi before giving up and buffering to flash instead.
#define WIFI_TIMEOUT_SECONDS 20

// --- EcoTrack API -----------------------------------------------------------

// No trailing slash. Use https:// in production; see the TLS note in README.md.
#define API_BASE_URL "http://192.168.1.50:8000"

// The raw token from device registration. Sent as: Authorization: Device <token>
#define DEVICE_TOKEN "paste-the-token-shown-once-at-registration"

// Must match `sample_interval_seconds` on the device record, or the server's
// online/offline threshold and its derived energy will disagree with reality.
#define SAMPLE_INTERVAL_SECONDS 30

// --- Sensor wiring ----------------------------------------------------------
// See README.md for the wiring diagram and the burden-resistor maths.

// ZMPT101B voltage sensor output.
#define VOLTAGE_PIN 34
// SCT-013 current clamp output.
#define CURRENT_PIN 35

// --- Calibration ------------------------------------------------------------
//
// These two numbers decide whether your readings mean anything. Both MUST be
// calibrated against a known reference; the defaults are starting points, not
// correct values.
//
// VOLTAGE_CALIBRATION: multiply until the reported RMS voltage matches a
// multimeter reading on the same supply.
//
// CURRENT_CALIBRATION: for an SCT-013-000 (100 A : 50 mA) with a 22 ohm burden
// resistor, the ratio is 100 A / 0.05 A = 2000 turns, and
// calibration = turns / burden = 2000 / 22 = 90.9. Adjust against a known load.
//
// An uncalibrated meter produces confident, wrong numbers. The firmware reports
// `"calibrated": false` in its payload until you set CALIBRATION_CONFIRMED,
// so the server and the dashboard can say so.

#define VOLTAGE_CALIBRATION 234.26
#define CURRENT_CALIBRATION 90.9
#define PHASE_CALIBRATION 1.7

// Set to 1 only after checking both figures against a reference instrument.
#define CALIBRATION_CONFIRMED 0

// --- Sampling ---------------------------------------------------------------

// Mains half-cycles to integrate per sample. 20 cycles at 50 Hz is about 400 ms,
// long enough to average out flicker without blocking the loop for a second.
#define SAMPLE_HALF_CYCLES 20
// Milliseconds before EmonLib abandons a sample it cannot complete.
#define SAMPLE_TIMEOUT_MS 2000

// --- Flash buffer -----------------------------------------------------------

// Readings held in flash while the network is down. 240 at 30 s is two hours.
// Raising this shortens flash life; the ring buffer is sized for the worst
// realistic outage, not the longest conceivable one.
#define BUFFER_CAPACITY 240

// Readings per upload when flushing the buffer. The server accepts batches and
// dedupes by (device, timestamp), so an over-large batch is wasteful rather than
// dangerous.
#define UPLOAD_BATCH_SIZE 30

// --- Time -------------------------------------------------------------------

// NTP is required: a reading is worthless without a trustworthy timestamp, and
// the server rejects anything more than 5 minutes in the future.
#define NTP_SERVER_1 "pool.ntp.org"
#define NTP_SERVER_2 "time.google.com"
// Offset in seconds. India Standard Time is UTC+5:30 = 19800. Timestamps are
// sent as UTC regardless; this only affects local logging.
#define NTP_GMT_OFFSET_SECONDS 19800
#define NTP_DAYLIGHT_OFFSET_SECONDS 0
