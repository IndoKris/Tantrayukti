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
