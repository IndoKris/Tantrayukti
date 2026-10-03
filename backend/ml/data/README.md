# ML data: provenance and units

Everything the models train on is produced by `ml/data/prepare.py`. Run it from
`backend/`:

```bash
python -m ml.data.prepare --small      # reduced slice, for the phase check and CI
python -m ml.data.prepare              # full pipeline
python -m ml.data.prepare --synthetic  # skip the download, generate instead
```

Outputs land in `ml/data/processed/` (gitignored), each with a
`<file>.provenance.json` sidecar recording its source, units, row count, date
range, whether it is synthetic, and what cleaning removed. **Read the sidecar
before quoting any number derived from these files.**

| File | Feeds | Source |
| --- | --- | --- |
| `household_hourly.csv` | Phase 11 LSTM forecasting | UCI dataset, or synthetic fallback |
| `emission_factors_hourly.csv` | Phase 12 emission-factor random forest | **Always synthetic** |

---

## 1. Household load — real where possible

**Source.** [UCI Machine Learning Repository dataset 235, "Individual household
electric power consumption"](https://archive.ics.uci.edu/dataset/235) —
measurements from a single household in Sceaux, near Paris, sampled every minute
from December 2006 to November 2010. Licensed **CC BY 4.0**.

**One download attempt.** `prepare.py` tries once. On any failure it falls back
to `synthetic.synthetic_hourly_load`, flags every row `is_synthetic=1`, and
records the failure reason in the provenance. It never retries in a loop and
never blocks the pipeline.

**Honest limitation.** This is one French household. Its load shape is *not*
representative of an Indian home or office. It is used because it is a long,
real, freely licensed series suitable for training a forecaster — not as a local
baseline. Anything comparing EcoTrack spaces to each other uses the Phase 7
simulator or real telemetry instead.

### Units — the trap this pipeline exists to handle

The raw file mixes unit families:

| Raw column | Unit |
| --- | --- |
| `Global_active_power` | **kilowatts** (instantaneous) |
| `Global_reactive_power` | kilovolt-amperes reactive |
| `Voltage` | volts |
| `Global_intensity` | amperes |
| `Sub_metering_1/2/3` | **watt-hours per minute** |

Averaging kilowatts over an hour yields kilowatts, **not** kilowatt-hours. The
plan forbids mixing the two, so every processed column is named for its unit:

| Processed column | Unit | Definition |
| --- | --- | --- |
| `energy_kwh` | kWh | `mean(kW) × 1 h` — energy used in the hour |
| `mean_power_kw` | kW | mean instantaneous power in the hour |
| `peak_power_kw` | kW | maximum instantaneous power in the hour |
| `mean_voltage_v` | V | mean voltage |
| `mean_current_a` | A | mean current |

Over a complete hour `energy_kwh` and `mean_power_kw` are numerically equal,
which is exactly why they need distinct names — the equality is a coincidence of
the one-hour window, not an identity.

### Cleaning

| Step | Behaviour |
| --- | --- |
| Missing `Global_active_power` | **Dropped, not imputed.** It is the forecasting target; filling it would fabricate the label. |
| Power < 0 or > 20 kW | Dropped. On a domestic supply that is a sensor fault, not a large load. |
| Voltage outside 180–280 V | Dropped. |
| Hours with < 80% of their 60 samples | Dropped. Scaling a partial hour up would bias every model trained on it. |

Counts for each step go into the provenance sidecar, so the cleaning is
reportable rather than invisible.

### Splitting

`clean.time_ordered_split` splits **chronologically** — 70% train, 15%
validation, 15% test — never randomly. A random split on a time series leaks the
future into training and produces scores that cannot be reproduced in
production. The plan requires a time-ordered split; it is done once here for
every model to reuse.

---

## 2. Grid emission factor — always synthetic

`emission_factors_hourly.csv` is **generated, not measured.** There is no public
hourly CO₂-intensity series for the Indian grid that this project downloads, so
there is nothing real to fall back to — which is precisely why the labelling
matters.

**Features:** `hour`, `month`, `day_of_week`, `is_weekend`, sine/cosine
encodings of hour and month, and `load_mw` (a national demand proxy).
**Target:** `kg_co2_per_kwh`.

**What the shape encodes.** Three real mechanisms:

1. coal-heavy baseload overnight → highest intensity,
2. solar generation diluting the mix around midday → lowest intensity,
3. gas and liquid-fuel peakers on the evening ramp → high again,

plus a load-driven term, because peaking plants are dirtier than baseload. A
typical run produces a mean near **0.83 kg CO₂/kWh**, cleanest around **12:00**
and dirtiest around **19:00**, which straddles the project's static 0.82 default.

**What it does not mean.** The *shape* is defensible; the *values* are invented.
A model trained on this learns the generator's assumptions, not the grid. Phase
12 must state that beside its metrics, and the Phase 9 CO₂ engine keeps the
static factor as the default with the modelled factor as an explicitly-labelled
option.

---

## 3. Reproducibility

Both generators are seeded (`synthetic.DEFAULT_SEED`), so repeated runs produce
identical data. Phase 12 and Phase 13 compare metrics across runs; data that
drifted between runs would make those comparisons meaningless.

## 4. The honesty rule in practice

The project plan states that no accuracy figure may be invented, and that every
metric shown in the UI or docs must come from
`backend/ml/artifacts/metrics.json` produced by evaluation code. These datasets
are the upstream half of that rule: a metric is only as honest as the provenance
of the data behind it. Hence the sidecars, the `is_synthetic` column on every
row, and the explicit `NOTE:` lines `prepare.py` prints when it falls back.
