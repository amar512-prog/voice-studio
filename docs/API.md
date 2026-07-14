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
      "capabilities": ["tts", "batch", "clone", "presets", "text_rules", "text_conversions"]
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
| POST | `/api/{provider}/voices/clone` | both | Multipart clone upload. ElevenLabs accepts repeated `samples`, accent plus optional gender/age labels, and optional `remove_background_noise`; English is fixed internally. OmniVoice accepts one `sample` and stores a local normalized reference WAV, selecting the best-scored continuous 3-10s pause-bounded clip when available, otherwise the longest continuous speech run capped to 10s (optional `reference_text`). |
| GET | `/api/{provider}/voices/options` | **elevenlabs** | Browse the ElevenLabs library/premade (paged/sorted/accent-filtered). 404 for OmniVoice. |
| POST | `/api/{provider}/voice-options/{voice_id}/save` | **elevenlabs** | Save a picked library/premade voice. |
| POST | `/api/{provider}/voices/by-id` | **elevenlabs** | Register a raw ElevenLabs voice id. |
| DELETE | `/api/{provider}/voices/cache` | **elevenlabs** | Clear the in-memory voice-library cache. |

### ElevenLabs instant clone fields

Use 1-2 minutes of clean, single-speaker audio for best results; avoid exceeding 3 minutes. Multiple files are uploaded as repeated `samples` multipart fields. The clone flow always sends English (`en`) plus the selected accent and optional gender/age labels, and keeps background-noise removal off unless explicitly enabled (behavior change: denoising was previously always on, so legacy clients that omit `remove_background_noise` now clone without it). Speech context is not stored by cloning; users select it independently on Generate or Batch. English is sent as the ElevenLabs `language_code` during TTS. Other labels remain voice metadata because the ElevenLabs TTS endpoint does not accept clone labels in its generation JSON.

### ElevenLabs speech-context settings

`PUT /api/{provider}/speech-contexts/{context_id}/voice-settings` retains its existing `voice_settings` wrapper and accepts a complete object for backward compatibility or a partial object containing any of stability, similarity boost, style, and speed. Omitted and null fields preserve the saved value, then fall back to the built-in context preset. The backend persists a complete normalized object, so existing stored data needs no migration. Saved values become the defaults for Generate and Batch, survive container rebuilds through the mounted provider data directory, and are returned by `/api/config`. Per-generation `voice_settings_override` values still take precedence.

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
| GET | `/api/{provider}/text-conversions` | **OmniVoice** conversion catalog. Returns available conversions, required inputs, purpose, rules, and editable default prompts. |
| POST | `/api/{provider}/text-conversions/{conversion_id}/convert` | **OmniVoice** text conversion. Returns converted text, prompts used, conversion warnings, and a text-rule check. |
| POST | `/api/{provider}/text-rules/check` | **OmniVoice** text check (non-blocking). Returns suggestions. |
| POST | `/api/{provider}/tts` | Generate one voice note (synchronous). |
| POST | `/api/{provider}/tts/batch` | Submit an `.xlsx` batch → **202** + a job to poll. |

### OmniVoice text conversions

Text conversions run before generation and before the lower-level text-rules
checker. The catalog currently includes:

- `founder_linkedin_voice_note`, which turns founder outreach copy into a warm,
  low-pressure LinkedIn voice-note script.
- `revvoice_emotional_voice_note`, which uses the OmniVoice Emotional
  Voice-Note Conversion prompt to prioritize spoken delivery, emotional
  authenticity, human connection, and preservation of the source message's
  facts and intent. It accepts only `source_text`.

The original natural-language `source_text` and context fields are sent to the
LLM unchanged. After conversion, the backend normalizes the LLM output with
WeTextProcessing English TN. Conversion warnings and the OmniVoice text-rules
check run against that final speech-ready text.

Conversion-specific quality rules remain separate. The founder-outreach
conversion additionally warns about selection language, inferred benefits, and
unverified compliments. The emotional conversion permits the prompt's requested
emotional amplification and selection intent, while the shared output-only,
marketing-language, pronunciation, contraction, duration, and spoken-sentence
checks still run.

Known TTS-safe tokens produced by the LLM, including `U-S`, `U.S.`, `P-E V-C`,
`G-T-M`, `C-R-O`, `C-M-O`, `B-to-B`, and bracketed CMU phonemes, are preserved
during WeTextProcessing. Raw forms such as `US` remain visible to the conversion
validator instead of being silently corrected.

WeTextProcessing uses Pynini. The Compose image defaults to `linux/amd64`
because Pynini publishes Linux Python 3.12 wheels for x86_64; this is native on
server 1 and runs through Docker emulation on Apple Silicon development hosts.

`GET /api/omnivoice/text-conversions` returns:

- the conversion id and purpose
- the input fields the frontend should collect
- output rules
- editable default system/user prompt templates
- whether OpenRouter is configured
- the server default `max_tokens` value shown in the frontend

`POST /api/omnivoice/text-conversions/{conversion_id}/convert` accepts:

```json
{
  "inputs": {
    "source_text": "Hi Anushua Roy, We're a NY-based PE/VC fund...",
    "founder_name": "Anushua Roy",
    "company_name": "Recro",
    "verified_observation": "",
    "pronunciation_notes": ""
  },
  "max_tokens": 5000
}
```

Optional edited prompts can be sent as:

```json
{
  "inputs": { "...": "..." },
  "max_tokens": 5000,
  "prompts": {
    "system_prompt": "edited system prompt",
    "user_prompt": "edited user prompt"
  }
}
```

The backend does **not** request, store, or return model reasoning. The response
contains the natural-language LLM output, its WeTextProcessing-normalized final
text, prompts used for that run, conversion warnings, estimated spoken duration,
and the existing OmniVoice `text-rules/check` result. WeTextProcessing details
are returned under the explicit `wetext_processing` field.

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
`speech_context`, `voice_settings_override`, `accent`, `target_seconds`, `wpm`,
`export_m4a`, …

- **ElevenLabs**: `speech_context` is one of the built-in delivery contexts.
  `founder_outreach_human` uses the tested human-like founder settings. The
  optional `voice_settings_override` object can override any of `stability`
  (0-1), `similarity_boost` (0-1), `style` (0-1), and `speed` (0.7-1.2).
  Any omitted field inherits the selected context default.
- **ElevenLabs `enhance_text`** (default `false`; the web UI sends `true` by
  default): an OpenRouter LLM first rewrites the written text into natural
  spoken form — numbers, currencies, dates, URLs, and abbreviations expanded —
  and, when the model is `eleven_v3`, adds a few bracketed audio tags that
  direct emotional delivery (the per-context leading tag is skipped in that
  case). Requires `OPENROUTER_API_KEY`; if the conversion is unavailable or
  fails, generation proceeds with the original text. The final spoken text is
  returned as `spoken_text` on the result row. The batch workbook accepts an
  optional `enhance_text` column with the same semantics per row.
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
curl -s -H "X-API-Key:$KEY" localhost:8000/api/omnivoice/text-conversions
curl -s -H "X-API-Key:$KEY" -X POST \
  localhost:8000/api/omnivoice/text-conversions/founder_linkedin_voice_note/convert \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"source_text":"Hi Anushua Roy, We are a NY-based PE/VC fund.","founder_name":"Anushua Roy","company_name":"Recro"},"max_tokens":5000}'
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
