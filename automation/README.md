# n8n chat-ingestion workflow

Receives a chat message (text, image or audio), routes it by modality, posts it
to EcoTrack's chat-ingestion endpoint, and replies with **what was actually
stored** rather than a generic confirmation.

`ecotrack-chat-ingest.json` is importable into any n8n instance.

## Setup

1. **Import.** n8n → *Workflows* → *Import from File* → `ecotrack-chat-ingest.json`.

2. **Set the API URL.** The HTTP node reads `$env.ECOTRACK_API_URL`. Set it in
   your n8n environment, for example:

   ```
   ECOTRACK_API_URL=http://host.docker.internal:8000
   ```

   (Use `host.docker.internal` when n8n runs in Docker and EcoTrack runs on the
   host; a plain `localhost` would resolve to the container.)

3. **Create the credential.** The HTTP node uses a *Header Auth* credential:

   | Field | Value |
   | --- | --- |
   | Name | `Authorization` |
   | Value | `Bearer <access token>` |

   Get a token from the Phase 4 login endpoint:

   ```bash
   curl -s -X POST "$ECOTRACK_API_URL/api/auth/login/" \
     -H 'Content-Type: application/json' \
     -d '{"username":"demo","password":"..."}' | jq -r .access
   ```

   Access tokens expire (60 minutes by default). For an unattended workflow, add
   a node that calls `/api/auth/refresh/` first, or issue a long-lived token for
   a dedicated service account.

4. **Activate** the workflow and note the production webhook URL
   (`.../webhook/ecotrack-chat`).

## Calling it

```bash
curl -X POST "$N8N_URL/webhook/ecotrack-chat" \
  -H 'Content-Type: application/json' \
  -d '{"device": 3, "modality": "text", "text": "AC ran 4 hours at 1500 W", "occurred_on": "2026-10-03"}'
```

Reply:

```json
{
  "ok": true,
  "reply": "Logged 6.0000 kWh for SIM home/ac across 4 interval(s). The reported 6.0000 kWh was spread evenly across 4 interval(s) of 3600 s, because a chat report covers a span rather than an instant."
}
```

## Node graph

```
Webhook
  └─ Switch on modality ──┬─ text  ─→ Build text payload  ─┐
                          ├─ image ─→ Build image payload ─┤
                          ├─ audio ─→ Build audio payload ─┼─→ POST /api/ingest/chat/
                          └─ other ─→ (treated as text)   ─┘        │
                                                                     ↓
                                                              Build reply
                                                                     ↓
                                                          Respond to webhook
```

The switch's fallback output routes an unknown modality to the text branch
rather than dropping the message silently.

## What the endpoint will and will not do

`POST /api/ingest/chat/` is deliberately strict, and the workflow surfaces each
refusal verbatim instead of smoothing it over.

| Situation | Response | Reply the user sees |
| --- | --- | --- |
| Parseable text | **201** | What was stored, and the spreading assumption |
| Image or audio | **422** | That no vision/speech provider is configured, and to send text instead |
| Unparseable text | **422** | How to phrase it (`"1500 W AC ran 4 hours"`) |
| Implausible figure | **422** | Which range check failed |
| Unknown device | **404** | — |

**Image and audio decline rather than guessing.** No Gemini or Whisper
credentials are configured, so those extractors return a reason instead of a
number. A mock that emitted a plausible reading for a photo it cannot see would
put fabricated data into the database, which is worse than refusing.

**Chat readings are stored with `source=import`**, so they remain
distinguishable from metered telemetry in every rollup, bill and comparison.

**A reported figure is spread across intervals, not stored as a spike.** A chat
report covers a span; a single large reading at one timestamp would look exactly
like the anomaly the Phase 13 detector exists to catch. The assumption is
returned in the response and quoted in the reply.

## Going live with real extractors

Replace the mock providers in `backend/telemetry/extractors.py`. The interface is
small — one `extract(payload) -> Extraction` method — and the registry at the
bottom of that module maps a modality to a provider:

```python
EXTRACTORS = {
    "text": MockTextExtractor(),
    "image": DecliningExtractor(modality="image", provider_name="Gemini Vision"),
    "audio": DecliningExtractor(modality="audio", provider_name="Whisper"),
}
```

A real provider must set `is_mock=False` and an honest `confidence`. Nothing else
in the pipeline changes: the range checks, the interval spreading, the
`source=import` tagging and the workflow all keep working.
