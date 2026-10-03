/*
 * EcoTrack ESP32 true-power meter.
 *
 * Samples a ZMPT101B voltage sensor and an SCT-013 current clamp with EmonLib,
 * which computes RMS voltage, RMS current, **real** power and power factor by
 * integrating instantaneous V x I over whole mains cycles. That distinction
 * matters: V_rms x I_rms is apparent power (VA), and using it for a reactive
 * load like a motor or an AC compressor overstates consumption badly. The
 * server also rejects a reading whose active power exceeds apparent power, so a
 * mis-wired or mis-calibrated meter is caught rather than believed.
 *
 * Posts every SAMPLE_INTERVAL_SECONDS to POST /api/readings/ with the device
 * token. When the network is down, readings go to a flash ring buffer and are
 * replayed **oldest first** once it returns - the server dedupes on
 * (device, timestamp), so a replay after a partially-failed upload is harmless.
 *
 * Units sent, matching the server's field names exactly:
 *   active_power_w  watts        (real power, not VA)
 *   energy_wh       watt-hours   (this interval only, never a running total)
 *   voltage_v       volts RMS
 *   current_a       amperes RMS
 *   power_factor    0..1
 */

#include <Arduino.h>
#include <ArduinoJson.h>
#include <EmonLib.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <time.h>

#include "config.h"

// --- Types ------------------------------------------------------------------

struct Reading {
  time_t timestamp;  // Unix seconds, UTC
  float voltage_v;
  float current_a;
  float active_power_w;
  float power_factor;
  float energy_wh;  // energy for this interval only
};

// --- State ------------------------------------------------------------------

EnergyMonitor emon;
Preferences preferences;

// Flash-backed ring buffer. Only the indices live in NVS alongside the rows, so
// a reboot mid-outage does not lose what was already queued.
static Reading buffer[BUFFER_CAPACITY];
static uint16_t bufferHead = 0;   // next write position
static uint16_t bufferCount = 0;  // rows currently queued

static unsigned long lastSampleMs = 0;
static bool timeSynced = false;

// --- Flash buffer -----------------------------------------------------------

static void bufferLoad() {
  preferences.begin("ecotrack", /* readOnly */ true);
  bufferCount = preferences.getUShort("count", 0);
  bufferHead = preferences.getUShort("head", 0);

  if (bufferCount > BUFFER_CAPACITY) {
    bufferCount = 0;  // corrupt or capacity changed; start clean
    bufferHead = 0;
  }
  if (bufferCount > 0) {
    preferences.getBytes("rows", buffer, sizeof(Reading) * BUFFER_CAPACITY);
  }
  preferences.end();

  Serial.printf("[buffer] restored %u reading(s) from flash\n", bufferCount);
}

static void bufferPersist() {
  // One write for the whole array: NVS has limited erase cycles, so the buffer
  // is flushed as a block rather than row by row.
  preferences.begin("ecotrack", /* readOnly */ false);
  preferences.putUShort("count", bufferCount);
  preferences.putUShort("head", bufferHead);
  preferences.putBytes("rows", buffer, sizeof(Reading) * BUFFER_CAPACITY);
  preferences.end();
}

static void bufferPush(const Reading &reading) {
  buffer[bufferHead] = reading;
  bufferHead = (bufferHead + 1) % BUFFER_CAPACITY;

  if (bufferCount < BUFFER_CAPACITY) {
    bufferCount++;
  } else {
    // Full: the oldest row is overwritten. Dropping the oldest is the right
    // choice - recent data is what the dashboard and the detectors need, and
    // refusing new readings would lose the present to preserve the past.
    Serial.println("[buffer] FULL - overwrote the oldest reading");
  }
  bufferPersist();
}

/* Index of the oldest queued reading, so replay is chronological. */
static uint16_t bufferOldestIndex() {
  return (bufferHead + BUFFER_CAPACITY - bufferCount) % BUFFER_CAPACITY;
}

static void bufferDropOldest(uint16_t howMany) {
  if (howMany > bufferCount) howMany = bufferCount;
  bufferCount -= howMany;
  bufferPersist();
}

// --- Network ----------------------------------------------------------------

static bool wifiConnect() {
  if (WiFi.status() == WL_CONNECTED) return true;

  Serial.printf("[wifi] connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  const unsigned long deadline = millis() + (WIFI_TIMEOUT_SECONDS * 1000UL);
  while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
    delay(250);
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[wifi] connected, ip %s\n", WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.println("[wifi] failed - readings will be buffered to flash");
  return false;
}

static bool timeSync() {
  if (timeSynced) return true;
  if (WiFi.status() != WL_CONNECTED) return false;

  configTime(NTP_GMT_OFFSET_SECONDS, NTP_DAYLIGHT_OFFSET_SECONDS, NTP_SERVER_1,
             NTP_SERVER_2);

  struct tm info;
  // A reading without a trustworthy timestamp is useless, and the server rejects
  // anything over 5 minutes in the future, so sampling waits for this.
  if (!getLocalTime(&info, 10000)) {
    Serial.println("[time] NTP sync failed - not sampling yet");
    return false;
  }

  timeSynced = true;
  Serial.printf("[time] synced: %s", asctime(&info));
  return true;
}

/* ISO-8601 UTC, which is what the API expects. */
static void isoTimestamp(time_t when, char *out, size_t size) {
  struct tm utc;
  gmtime_r(&when, &utc);
  strftime(out, size, "%Y-%m-%dT%H:%M:%SZ", &utc);
}

// --- Sampling ---------------------------------------------------------------

static Reading sampleNow() {
  emon.calcVI(SAMPLE_HALF_CYCLES, SAMPLE_TIMEOUT_MS);

  Reading reading;
  reading.timestamp = time(nullptr);
  reading.voltage_v = emon.Vrms;
  reading.current_a = emon.Irms;
  reading.active_power_w = emon.realPower;  // real power, not Vrms x Irms
  reading.power_factor = emon.powerFactor;

  // Interval energy, not a cumulative meter total: the server sums these, so a
  // running total would be double counted on every upload.
  reading.energy_wh =
      emon.realPower * (SAMPLE_INTERVAL_SECONDS / 3600.0f);

  // Guard the obviously impossible before it reaches the wire. EmonLib can emit
  // NaN or a negative power factor on a floating input.
  if (isnan(reading.active_power_w) || reading.active_power_w < 0) {
    reading.active_power_w = 0;
    reading.energy_wh = 0;
  }
  if (isnan(reading.power_factor) || reading.power_factor < 0) {
    reading.power_factor = 0;
  }
  if (reading.power_factor > 1) reading.power_factor = 1;
  if (isnan(reading.voltage_v) || reading.voltage_v < 0) reading.voltage_v = 0;
  if (isnan(reading.current_a) || reading.current_a < 0) reading.current_a = 0;

  return reading;
}

static void appendReading(JsonArray array, const Reading &reading) {
  char stamp[32];
  isoTimestamp(reading.timestamp, stamp, sizeof(stamp));

  JsonObject row = array.add<JsonObject>();
  row["timestamp"] = stamp;
  row["active_power_w"] = serialized(String(reading.active_power_w, 2));
  row["energy_wh"] = serialized(String(reading.energy_wh, 4));
  row["voltage_v"] = serialized(String(reading.voltage_v, 2));
  row["current_a"] = serialized(String(reading.current_a, 3));
  row["power_factor"] = serialized(String(reading.power_factor, 3));
}

// --- Upload -----------------------------------------------------------------

/*
 * Post up to UPLOAD_BATCH_SIZE of the oldest queued readings.
 *
 * Returns the number accepted, or -1 on a transport failure. Rows are only
 * dropped from the buffer once the server has acknowledged them, so a failed
 * upload loses nothing.
 */
static int uploadOldestBatch() {
  if (bufferCount == 0) return 0;
  if (WiFi.status() != WL_CONNECTED) return -1;

  const uint16_t count =
      bufferCount < UPLOAD_BATCH_SIZE ? bufferCount : UPLOAD_BATCH_SIZE;

  JsonDocument document;
  JsonArray readings = document["readings"].to<JsonArray>();

  const uint16_t start = bufferOldestIndex();
  for (uint16_t offset = 0; offset < count; offset++) {
    appendReading(readings, buffer[(start + offset) % BUFFER_CAPACITY]);
  }

  // Tell the server what is still queued after this batch, so its digital twin
  // shows the real backlog rather than guessing from arrival times.
  document["buffer_count"] = bufferCount - count;
  document["firmware_version"] = CALIBRATION_CONFIRMED ? "1.0.0" : "1.0.0-uncalibrated";
  document["calibrated"] = CALIBRATION_CONFIRMED ? true : false;

  String body;
  serializeJson(document, body);

  HTTPClient http;
  http.begin(String(API_BASE_URL) + "/api/readings/");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Device ") + DEVICE_TOKEN);
  http.setTimeout(15000);

  const int status = http.POST(body);
  const String response = http.getString();
  http.end();

  if (status == 200 || status == 201) {
    Serial.printf("[upload] %u reading(s) accepted (HTTP %d), %u still queued\n",
                  count, status, bufferCount - count);
    return count;
  }

  if (status == 400 || status == 422) {
    // The server rejected the *content*. Retrying forever would wedge the
    // buffer, so the batch is dropped and the reason logged - a bad reading is
    // not worth blocking every later one.
    Serial.printf("[upload] REJECTED (HTTP %d): %s\n", status, response.c_str());
    Serial.println("[upload] dropping the batch so the buffer can drain");
    return count;
  }

  if (status == 401) {
    Serial.println("[upload] 401 - the device token is wrong or was rotated. "
                   "Readings stay buffered. Re-flash with a valid token.");
    return -1;
  }

  Serial.printf("[upload] failed (HTTP %d): %s\n", status, response.c_str());
  return -1;
}

static void drainBuffer() {
  // Oldest first, so a backfill arrives in sample order.
  while (bufferCount > 0) {
    const int accepted = uploadOldestBatch();
    if (accepted <= 0) break;
    bufferDropOldest((uint16_t)accepted);
  }
}

// --- Arduino ----------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(200);

  Serial.println();
  Serial.println("EcoTrack ESP32 true-power meter");
  Serial.printf("  interval      %d s\n", SAMPLE_INTERVAL_SECONDS);
  Serial.printf("  buffer        %d readings (%.1f h of outage)\n", BUFFER_CAPACITY,
                (BUFFER_CAPACITY * SAMPLE_INTERVAL_SECONDS) / 3600.0);
  Serial.printf("  api           %s\n", API_BASE_URL);

  if (!CALIBRATION_CONFIRMED) {
    Serial.println("  !! CALIBRATION NOT CONFIRMED - readings will be wrong by an");
    Serial.println("     unknown factor. Check VOLTAGE_CALIBRATION and");
    Serial.println("     CURRENT_CALIBRATION against a reference instrument, then");
    Serial.println("     set CALIBRATION_CONFIRMED to 1. Uploads are tagged");
    Serial.println("     '1.0.0-uncalibrated' until you do.");
  }

  // 12-bit ADC over the full range; the sensor outputs swing around a midpoint.
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  emon.voltage(VOLTAGE_PIN, VOLTAGE_CALIBRATION, PHASE_CALIBRATION);
  emon.current(CURRENT_PIN, CURRENT_CALIBRATION);

  bufferLoad();
  wifiConnect();
  timeSync();

  lastSampleMs = millis() - (SAMPLE_INTERVAL_SECONDS * 1000UL);
}

void loop() {
  const unsigned long now = millis();

  if (now - lastSampleMs < (SAMPLE_INTERVAL_SECONDS * 1000UL)) {
    delay(50);
    return;
  }
  lastSampleMs = now;

  // No clock, no reading: an untrustworthy timestamp is worse than a gap.
  if (!timeSynced) {
    wifiConnect();
    if (!timeSync()) {
      Serial.println("[loop] waiting for NTP before sampling");
      return;
    }
  }

  const Reading reading = sampleNow();
  Serial.printf("[sample] %.1f V  %.3f A  %.1f W  pf %.2f  %.4f Wh\n",
                reading.voltage_v, reading.current_a, reading.active_power_w,
                reading.power_factor, reading.energy_wh);

  // Always queue first, then try to drain. Uploading directly and only
  // buffering on failure would lose a reading if the POST hung past the next
  // interval.
  bufferPush(reading);

  if (wifiConnect()) {
    drainBuffer();
  }
}
