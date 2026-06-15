# Voice Message Studio

Dockerized React + FastAPI app for creating reviewable ElevenLabs voice-message audio.

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

The UI is split into task pages: `/generate`, `/voices`, `/clone`, `/batch`, and `/saved-files`. The `/files/...` path is reserved for authenticated downloads.

The browser receives only the public Google client ID. Google credentials are verified by FastAPI, and generation, cloning, voice registry, batch, and saved-file routes require the signed session cookie.

The default speech model is `eleven_v3`. Conversational generation uses ElevenLabs' Natural stability mode, a restrained delivery cue, and slightly slower pacing. Set `ELEVENLABS_MODEL_ID=eleven_multilingual_v2` to use the previous model without v3 delivery tags.

Voice sync fetches the full ElevenLabs voice list and saves every English voice with a US, India, or neutral accent whose provider use case is conversational. The registry panel scrolls when more than five matching voices are available.

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
