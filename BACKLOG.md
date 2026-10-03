# BACKLOG

Ideas and deferred work that do not belong to the phase currently being built. One line each.
Add here instead of expanding a phase's scope.

- [Phase 1] Replace Vite starter branding (`src/assets/hero.png`, `public/icons.svg`, `App.css`) with EcoTrack branding.
- [Phase 1] Decide whether `backend/main.py` stub and the empty `backend/README.md` get repurposed or left as-is.
- [Phase 1] Resolve AUDIT Q1: pin Python to 3.12 vs keep 3.13 (TensorFlow wheel availability).
- [Phase 1] Add a root-level `Makefile` or `npm`/`uv` task runner so both sides start with one command.
- [Phase 4] Server-side JWT revocation on logout via simplejwt's token_blacklist app (logout is currently client-side only).
- [Phase 4] Move the refresh token to an httpOnly cookie instead of localStorage, to harden against XSS.
- [Phase 4] Self-service registration and password reset; users are created with `createsuperuser` or the admin today.
- [Phase 4] `seed_users` management command for demo admin/manager/member accounts, to pair with Phase 5's `seed_spaces`.
- [Phase 4] Scope roles per organisation rather than globally, once Phase 5's hierarchy exists.
- [Phase 5] Organisation-level roles on `spaces.Membership`, so a user can be a manager in one organisation and a member in another.
- [Phase 5] Move list filtering to django-filter instead of hand-rolled query-param filters in `get_queryset`.
- [Phase 5] Bulk space import from CSV/XLSX, for onboarding a real building without hand-entering rooms.
- [Phase 5] Cache the derived `total_area_sqm` / `total_occupancy` rollups if the tree endpoint gets slow on large hierarchies.
- [Phase 6] Sign the reading payload on the device (HMAC over body + nonce) so telemetry integrity is provable, not just token possession.
- [Phase 6] Rate-limit `POST /api/readings/` per device token to blunt a leaked-token flood.
- [Phase 6] Emit UTC on every API route instead of the active timezone, if the frontend ever needs offset-free timestamps.
- [Phase 6] Retention/downsampling policy for `Reading` once the table grows past a few million rows.
- [Phase 6] Reconcile `reported_buffer_count` against observed late arrivals and alert when the device's buffer never drains.
- [Phase 7] Weather-driven AC load from a real temperature series instead of the sinusoidal proxy in `profiles.py`.
- [Phase 7] `--live` mode that posts one reading per interval in real time, for demoing the online/offline badge.
- [Phase 7] Extra faults: phase imbalance, failing compressor (rising current at constant power), meter drift.
- [Phase 7] Unit tests for the simulator itself; it is currently verified by CLI runs, not by the backend test suite.
- [Phase 7] Occupancy schedule as data (holidays, shift patterns) rather than hard-coded hour windows.
- [Phase 8] Optional zero-fill / gap markers on the usage series, if the Phase 17 chart needs a continuous x-axis.
- [Phase 8] Materialised hourly rollup table refreshed on ingest, if `/api/usage/` gets slow over months of data.
- [Phase 8] Let `metering=auto` mix a mains meter with appliance meters in *sibling* rooms that have none, instead of choosing one kind estate-wide.
- [Phase 8] Derive `mean_power_w` from energy over bucket duration as well as the sample mean, and expose both.
- [Phase 8] Accept a `tz` query parameter so a client can request buckets in a timezone other than the server's.
