# Voice Message Studio

Dockerized React + FastAPI app for creating reviewable voice-message audio.

## Run

```bash
docker build -t voice-message-studio .
docker run --rm -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  voice-message-studio
```

Open `http://localhost:8000`.

Copy `.env.example` to `.env`, then set `GOOGLE_CLIENT_ID`, `SESSION_SECRET`, and `ELEVENLABS_API_KEY`. The Google client must allow `http://localhost:8000` as an authorized JavaScript origin. Set `SESSION_SECURE=true` behind HTTPS in production.

For the OmniVoice Hugging Face Space integration, the backend now also accepts:

- `HUGGINGFACE_TOKEN`
- `OMNIVOICE_BASE_URL`
- `OMNIVOICE_TIMEOUT_SECONDS`
- `OMNIVOICE_BATCH_CHUNK` (1-20 rows per upstream batch request; defaults to 6)
- `OPENROUTER_API_KEY` (optional; enables OmniVoice Text Conversion)
- `OPENROUTER_MODEL` (defaults to `deepseek/deepseek-v4-flash`)
- `OPENROUTER_MAX_TOKENS` (defaults to `5000`)
- `OPENROUTER_TIMEOUT_SECONDS` (defaults to `120`)

The product now supports provider-scoped flows for both ElevenLabs and OmniVoice. OmniVoice uses curated preset voices plus local sample-based clones, and its voice-design prompts intentionally stay close to the upstream supported attribute format.

OmniVoice includes built-in American and Indian design presets, exposed in the frontend under RevVoice URLs such as `/revvoice/text-conversion`, with both low-pressure founder outreach and emotional RevVoice voice-note conversions, and a `/revvoice/rules` checker. Text Conversion uses OpenRouter from the backend and does not request or log model reasoning. Generation is blocked when text still contains `/`; recognized dates such as `15/12/2025` and uppercase shorthand such as `PE/VC` receive reviewable spoken-text suggestions before the user applies them.

For a shared server, set `HOST_BIND=127.0.0.1` and an unused `HOST_PORT` such as `8011`, then point the existing HTTPS reverse proxy to that local port. The generated audio and saved voices persist under `./data`.

The UI is split into provider-scoped task pages such as `/elevenlabs/generate`, `/elevenlabs/voices`, `/revvoice/text-conversion`, `/revvoice/clone`, and `/revvoice/history`. Authenticated downloads use `/api/{provider}/files/...`; RevVoice frontend pages continue to call the backend OmniVoice provider API under `/api/omnivoice/...`.

The full API surface is documented in [docs/API.md](docs/API.md); interactive Swagger UI is served at `/docs`.

The browser receives only the public Google client ID. Google credentials are verified by FastAPI, and generation, cloning, voice registry, batch, and saved-file routes require the signed session cookie.

The default speech model is `eleven_v3`. Conversational generation uses ElevenLabs' Natural stability mode, a restrained delivery cue, and slightly slower pacing. The Generate page includes a `Founder outreach — human-like` context and optional overrides for stability, similarity boost, style exaggeration, and speed. Blank overrides inherit the selected context. Set `ELEVENLABS_MODEL_ID=eleven_multilingual_v2` to use the previous model without v3 delivery tags. Context presets no longer send `use_speaker_boost` (Eleven v3 ignores it); on older models ElevenLabs now applies each voice's own stored default, which can change output loudness compared with earlier releases.

Generate and Batch include a "Prepare spoken delivery" checkbox (on by default) for ElevenLabs. When enabled, an OpenRouter LLM rewrites the written message into natural spoken text — expanding numbers, dates, URLs, and abbreviations — and adds Eleven v3 audio tags for emotional delivery before generation; untick it to send the text exactly as written. It requires `OPENROUTER_API_KEY` and falls back to the original text if the conversion fails.

The expanded ElevenLabs voice-settings panel includes a Save context settings button. Saving promotes the current overrides to persistent defaults for the selected speech context, so Generate and Batch reuse them after reloads and Docker rebuilds. The existing API wrapper accepts complete settings objects and backward-compatible partial updates; omitted or null values keep the current context defaults.

Voice sync mirrors the ElevenLabs account's My Voices: every workspace voice is saved (accents outside US/India/Neutral are recorded as neutral), and voices deleted in ElevenLabs are removed from the registry on the next sync. Deleting a non-premade voice in the app also deletes it from the ElevenLabs account after a confirmation prompt. The registry panel scrolls when more than five matching voices are available.

ElevenLabs instant cloning supports one or more consented samples, fixed English plus accent/gender/age labels, and an optional background-noise removal switch. The UI recommends 1-2 minutes of clean, consistent, single-speaker audio and leaves denoising off for clean recordings. Speech context is selected independently on Generate or Batch, and English is sent to ElevenLabs as `language_code` during generation.

## Excel Batch Format

Use sheet name `tts_requests`.

Required columns:

- `text`
- `voice_id`

Optional columns:

- `voice_name`
- `accent`
- `speech_context`
- `target_seconds`
- `wpm`
- `export_m4a`

The app returns per-row status and generated file links. CSV is intentionally not used because message text can contain commas.
