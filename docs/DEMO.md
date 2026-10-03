# Demo script

Twelve minutes, end to end: inject a fault, watch it be detected, see the ranked
cause with its evidence, and get a recommendation with kWh, rupee and CO₂
savings.

Everything below has been run. Where a figure is quoted it came from an actual
run, and where something is a fallback or an estimate the demo says so — that
honesty is part of what is being demonstrated.

---

## 0 · Setup (once, about 5 minutes)

```bash
# Backend
cd backend
uv sync --extra ml                  # add --extra deep for the real LSTM
cp .env.example .env                # optional; every value has a default
uv run python manage.py migrate
uv run python manage.py createsuperuser

# Seed data
uv run python manage.py seed_spaces              # office + home
uv run python manage.py seed_tariffs             # sample tariffs + CO₂ factor
uv run python manage.py seed_activity_factors    # 23 activity factors
uv run python manage.py seed_gamification        # badges + a challenge
uv run python manage.py seed_no2                 # 20-city NO₂ fallback

# ML pipeline
uv run python -m ml.data.prepare --small
uv run python -m ml.training.train_lstm --small
uv run python -m ml.training.train_emission_rf --small
uv run python -m ml.training.train_co2_trend
uv run python -m ml.training.train_nilm --small
uv run python -m ml.evaluation.evaluate_all
uv run python -m ml.evaluation.report

uv run python manage.py runserver
```

```bash
# Telemetry (new terminal, repo root)
python simulator/run.py --days 7 --post --register \
  --username <you> --password <your-password>

# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173** and sign in.

> On this machine Vite binds IPv6-only, so use `localhost`, not `127.0.0.1`.

---

## 1 · Dashboard — it is measuring something real (1 min)

Say: *"Fifteen devices reporting. The badges are driven by last-seen
timestamps."*

Point out the four tiles. Then open **"Where these cost and CO₂ numbers come
from"** and read the CO₂ formula aloud:

```
13.852328 kWh x 0.82000 kg CO2/kWh = 11.358909 kg CO2
```

Say: *"That factor is flagged unverified, with a note pointing at the CEA
database. We did not invent a number and we are not pretending it is measured."*

**The point to land:** the footnote says metering `mains` across 3 devices.
Switch the URL to `?metering=all` if asked — it reports **27.5 kWh** instead of
**13.85 kWh**, because the room has both a mains meter and appliance meters.
Nearly double. That guard runs under every bill, comparison and savings figure.

---

## 2 · Spaces — normalised comparison (1 min)

Pick a floor in the tree, then toggle **per m²** → **raw total**.

The ranking **inverts**: raw energy puts the big open workspace first, per m² puts
the little store room first.

Say: *"Raw energy just finds the biggest room. Per square metre finds the one
actually wasting energy."*

Note the excluded list: a space with no recorded area is **excluded and named**,
not ranked on raw energy.

---

## 3 · Reports — bill projection with its assumptions (1 min)

Month-to-date, projected total, bill to date, projected bill. Expand the slab
breakdown:

```
100 kWh × 4.71 INR/kWh = 471.00 INR
66.45 kWh × 10.29 INR/kWh = 683.77 INR
```

Say: *"Cumulative slabs, so the projection re-slabs the whole month rather than
scaling the bill."*

Then read one assumption aloud: *"No seasonal, weekday or weather adjustment is
applied."* Say: *"It is a flat extrapolation and it says so. The LSTM forecast is
on the dashboard; this is deliberately not dressed up as one."*

---

## 4 · The main event — detect → explain → recommend (4 min)

Go to **Insights**. The feed should be empty. Say: *"Nothing wrong, so nothing
reported. The detector has no quota to fill."*

Under **Demo mode**, pick **Night load** and press **Run demo**.

It writes ten days of history with the fault in the last 40%, runs all five
detectors, and builds the whole chain. You should see something like:

```
Injected night_load into SIM home/mains: 240 readings written,
12 finding(s), 5 anomaly chain(s) built.
```

Press **Refresh**, then open **Cause and fix** on the top anomaly.

### The cause card

Read the most-likely cause, then **expand Evidence**:

```
hour: 2
night_median_kwh: 0.4
multiple_of_night_median: 8.5
threshold_multiple: 2.5
```

Say: *"Rules over recorded evidence — not a language model. The footnote says so.
There is an optional LLM flag, and it may only reword these facts; it cannot
introduce a number or reorder the list."*

### The recommendation card

Three figures per action — kWh, ₹, kg CO₂ per month. Expand **"How this was
calculated"**:

```
91.32 kWh/month extra baseload × 0.85 recoverable = 77.62 kWh/month
```

plus the assumptions, plus:

> *An estimate derived from the stated assumptions, not a measured or guaranteed
> saving.*

Say: *"Priced at the top slab rate, because a saving comes off the most expensive
units first. Averaging would understate it."*

Then press **Resolve** and show the anomaly leaving the open feed. Re-running
detection will **not** reopen it.

**If you only have 90 seconds, this section is the demo.** Everything else is
supporting evidence.

---

## 5 · ML metrics — the honest part (2 min)

Open **/insights/metrics**.

Say: *"Read straight from `metrics.json`, which only evaluation code writes.
Nothing on this page is typed by hand."*

Then volunteer the bad news before anyone finds it:

> **The forecast is poor.** MAE 0.765 kWh, MAPE 158.8%, **R² −0.044**. It beats
> the seasonal-naive baseline on MAE by 16% but is worse than predicting the mean
> on R².

And why: the TensorFlow download failed with a DNS error, so this is the labelled
**sklearn MLP fallback**, trained for 5 epochs on ~2000 hours of one noisy
household. The page says `is_fallback`, and the plan forbids re-training to chase
a number, so it was left alone.

Then show what does work:

| Model | Result |
| --- | --- |
| Emission factor RF | CV MAE **0.019** vs baseline **0.118** — 84% better |
| CO₂ trend | slope −0.000315/day, R² 0.661, p < 0.001, significant |
| Anomaly: night load | precision **1.00**, recall **1.00**, F1 **1.00** |
| Anomaly: AC left on | precision 0.98, recall 0.74, F1 **0.85** |
| NILM | **not evaluated** — no UK-DALE labels exist |

Say: *"Baseload-jump recall looks weak at 0.45. That is by design — it reports
one finding for a multi-day condition, so most faulty hours count as misses. The
caveat says exactly that rather than hiding behind the number."*

---

## 6 · Profile — proof of saving (1 min)

Say: *"Anyone can claim they saved energy. This checks."*

Submit a claim naming a device, a baseline window and an after window.
Verification reads the meter for both, **scales the baseline to the claim
window's length**, and credits the *measured* saving — so over-claiming earns
nothing extra.

Point at the leaderboard columns: **Verified XP** ranks; **Unverified
(excluded)** does not. Say: *"Logged journeys are visible on your own profile and
never move you up. A self-reported bus ride is not evidence the way a metered kWh
is."*

---

## 7 · Community (1 min, optional)

The map shows your aggregated energy alongside 20-city NO₂.

Say two things:

1. **Units.** µmol/m² of **tropospheric column** — not surface ppb. Converting
   needs a vertical profile we do not model, so no conversion exists anywhere in
   the codebase.
2. **Privacy.** Coordinates are rounded to ~100 m **before storage**, so the map
   cannot resolve to a household.

Three cities are flagged hotspots, above a threshold derived from the data —
`median + 1.5 × robust σ` **and** an Isolation Forest outlier. Say: *"No fixed
fraction. Give it twenty similar cities and it flags none."*

---

## If something is not working

| Symptom | Cause and fix |
| --- | --- |
| Dashboard: "No devices registered" | Run the simulator with `--post --register` |
| Forecast panel: 409 | `python -m ml.training.train_lstm --small` |
| Metrics page: 409 | `python -m ml.evaluation.evaluate_all` |
| Demo button absent | It needs the **manager** role or above |
| Spaces tree empty | `python manage.py seed_spaces` |
| Cost shows ₹0 | `python manage.py seed_tariffs` |
| `127.0.0.1:5173` refuses | Vite binds IPv6-only here — use `localhost` |

---

## Questions you should expect

**"Is the LSTM real?"** The architecture is implemented as specified (128, 64,
dropout 0.2) and runs whenever Keras imports. TensorFlow would not download
here, so the active model is the labelled fallback. `uv sync --extra ml --extra
deep` and re-run the two training commands — no code changes.

**"Are the tariffs real?"** No, and they say so: `is_sample=true` with a source
starting "ILLUSTRATIVE SAMPLE RATES". Replace them with your utility's schedule.

**"Is the NO₂ from a satellite?"** No. No Earth Engine credentials, so it is the
documented static fallback, `is_measured=false` on every row.

**"Why is the forecast bad?"** Fallback architecture, 5 epochs, ~2000 hours of
one French household. It is reported as-is because the plan forbids tuning
against the test set, and the causes are in `BACKLOG.md`.

**"How do I know the savings are real?"** You do not, from the recommendation —
it is an estimate with its formula and assumptions shown. Proof of saving on the
Profile page is the part that checks a claim against the meter.
