# Voice Message Studio — API Reference

Interactive docs (Swagger UI) are served at **`/docs`**; the raw schema is at
**`/openapi.json`**. This file documents the same surface for quick reference.

## Authentication

Every `/api/{provider}/...` route requires authentication. Two ways:

- **Browser** — sign in (Google, username/password, or development login). The
  session cookie authorizes calls automatically.
- **Machine / Swagger** — send an `X-API-Key: <API_KEY>` header. In Swagger,
  click **Authorize**, paste the key, then **Try it out**.

Unauthenticated calls return **401**.

## Providers

All generation routes are **provider-scoped**: `{provider}` is `elevenlabs` or
`omnivoice` (an unknown provider returns **404**). Each provider has fully
separate data under `data/{provider}/` and its own voices, jobs, and files.

Health/config (not provider-scoped):

| Method | Path | Notes |
|---|---|---|
| GET | `/api/providers` | Protected, Swagger-visible provider catalog. Returns the default provider, configuration state, and supported capabilities. |
| GET | `/api/health` | Basic, unauthenticated. Reports each provider's `configured` flag + ffmpeg. Used by the Docker healthcheck. |
| GET | `/api/{provider}/health` | Per-provider readiness. |
| GET | `/api/config` | Public UI config (auth mode, defaults, accents). |

Example:

```json
{
  "default_provider": "omnivoice",
  "providers": [
    {
      "id": "omnivoice",
      "name": "OmniVoice",
      "configured": true,
      "capabilities": ["tts", "batch", "clone", "presets", "text_rules"]
    },
    {
      "id": "elevenlabs",
      "name": "ElevenLabs",
      "configured": true,
      "capabilities": ["tts", "batch", "clone", "voice_library"]
    }
  ]
}
```

---

## Voices

| Method | Path | Provider | Summary |
|---|---|---|---|
| GET | `/api/{provider}/voices` | both | List the saved voice registry. |
| POST | `/api/{provider}/voices` | both | Add/update a voice by id. |
| DELETE | `/api/{provider}/voices/{record_id}` | both | Delete a saved voice. |
| GET | `/api/{provider}/voices/{record_id}/preview` | both | 307-redirect to a preview clip (best-effort). |
| POST | `/api/{provider}/voices/sync` | both | ElevenLabs: pull eligible workspace voices. OmniVoice: seed/refresh the design presets. |
| POST | `/api/{provider}/voices/clone` | both | Multipart upload of a consented sample. ElevenLabs clones server-side; OmniVoice stores the sample locally (optional `reference_text`). |
| GET | `/api/{provider}/voices/options` | **elevenlabs** | Browse the ElevenLabs library/premade (paged/sorted/accent-filtered). 404 for OmniVoice. |
| POST | `/api/{provider}/voice-options/{voice_id}/save` | **elevenlabs** | Save a picked library/premade voice. |
| POST | `/api/{provider}/voices/by-id` | **elevenlabs** | Register a raw ElevenLabs voice id. |
| DELETE | `/api/{provider}/voices/cache` | **elevenlabs** | Clear the in-memory voice-library cache. |

### OmniVoice speech contexts (OmniVoice only; 404 for ElevenLabs)

A **speech context** carries the OmniVoice *voice design* (instruct attributes) +
generation settings (speed, duration, inference steps, guidance scale, denoise,
preprocess/postprocess). The built-in **`english_american`** and
**`english_indian`** contexts cannot be deleted (returns **400**).

| Method | Path | Summary |
|---|---|---|
| GET | `/api/{provider}/speech-contexts` | List contexts (seeded with the built-in presets). |
| POST | `/api/{provider}/speech-contexts` | Add a context (omit `id`) or modify one (with `id`). |
| DELETE | `/api/{provider}/speech-contexts/{context_id}` | Delete a custom context (built-ins are protected). |
| POST | `/api/{provider}/speech-contexts/preview` | Design-only preview (no sample) → `{audio_b64, audio_format, duration}`. |

---

## Generate

| Method | Path | Summary |
|---|---|---|
| POST | `/api/{provider}/text-rules/check` | **OmniVoice** text check (non-blocking). Returns suggestions. |
| POST | `/api/{provider}/tts` | Generate one voice note (synchronous). |
| POST | `/api/{provider}/tts/batch` | Submit an `.xlsx` batch → **202** + a job to poll. |

### OmniVoice text rules

OmniVoice reads `/` as the spoken word "slash", so **generation is blocked when
the text still contains `/`** (returns **400** on `tts`/`tts/batch` rows and
`speech-contexts/preview`). Use `text-rules/check` first to get deterministic
spoken-text suggestions:

- Dates `DD/MM/YYYY` → `Nth Month, YYYY` (e.g. `05/07/2026` → `5th July, 2026`).
- Uppercase shorthand `PE/VC` → `PE VC`.

```bash
curl -s -H "X-API-Key: $KEY" -X POST localhost:8000/api/omnivoice/text-rules/check \
  -H 'Content-Type: application/json' \
  -d '{"text":"Call on 05/07/2026 about the PE/VC fund."}'
# -> { "ready": false, "suggested_text": "Call on 5th July, 2026 about the PE VC fund.",
#      "changes": [...], "errors": ["OmniVoice reads '/' as the word 'slash'. ..."] }
```

### Single generation

`POST /api/{provider}/tts` body (`TtsRequest`): `text`, `voice_id`,
`speech_context`, `accent`, `target_seconds`, `wpm`, `export_m4a`, …

- **ElevenLabs**: `speech_context` is one of the built-in delivery contexts.
- **OmniVoice**: `voice_id` is either a **design preset** (`ov_design_*`, no
  sample — the preset bundles its own context) or a **clone** (uploaded sample,
  uses the selected `speech_context`). The payload combines the sample's
  `ref_audio` (clones) or the context `instruct` (design) with the context
  settings.

---

## History

Each generation run is a **job** stored under `data/{provider}/jobs/{job_id}/`.

| Method | Path | Summary |
|---|---|---|
| GET | `/api/{provider}/jobs` | List jobs (newest first). |
| GET | `/api/{provider}/jobs/{job_id}` | One job with per-row results + `status`. |
| GET | `/api/{provider}/jobs/{job_id}/download` | ZIP of text + mp3 + m4a per row. **409** while still running. |

**Batch (async) flow:** `POST /tts/batch` (multipart `.xlsx`, sheet
`tts_requests`) returns **202** + `{job_id, status:"running", ...}`. Poll
`GET /jobs/{job_id}` until `status` ∈ {`completed`, `partial`, `failed`,
`interrupted`}, then download. Row cap is `MAX_BATCH_ROWS`; OmniVoice rows are
sent upstream in chunks of `OMNIVOICE_BATCH_CHUNK` (1–20).

---

## Files

| Method | Path | Summary |
|---|---|---|
| GET | `/api/{provider}/files/{relative_path}` | Download a generated artifact (path sandboxed under `data/{provider}/`). The URLs in job results point here. |
| GET | `/files/{relative_path}` | Legacy, ElevenLabs-rooted; serves pre-migration manifests. |

---

## End-to-end example (Swagger / API key)

```bash
KEY=...   # your API_KEY

# 1) OmniVoice: check + fix text, then generate from a design preset (no sample)
curl -s -H "X-API-Key:$KEY" -X POST localhost:8000/api/omnivoice/text-rules/check \
  -H 'Content-Type: application/json' -d '{"text":"Meet on 1/2/2026."}'
curl -s -H "X-API-Key:$KEY" -X POST localhost:8000/api/omnivoice/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"Meet on 1st February, 2026.","voice_id":"ov_design_english_american","speech_context":"english_american"}'

# 2) Batch: submit -> poll -> download
JOB=$(curl -s -H "X-API-Key:$KEY" -X POST localhost:8000/api/omnivoice/tts/batch \
  -F "file=@batch.xlsx" | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
curl -s -H "X-API-Key:$KEY" localhost:8000/api/omnivoice/jobs/$JOB        # poll status
curl -s -H "X-API-Key:$KEY" -o job.zip localhost:8000/api/omnivoice/jobs/$JOB/download
```

## Tests

- `python -m pytest tests/` — unit tests (OmniVoice text rules).
- `python scripts/test_swagger_endpoints.py` — TestClient smoke test over every
  documented Swagger operation (uses fake providers; no network).
