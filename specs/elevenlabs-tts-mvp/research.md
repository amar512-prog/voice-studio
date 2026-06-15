# Verifiable Research and Technology Proposal

## 1. Core Problem Analysis

The system must convert operator-provided text into reusable audio assets through ElevenLabs, with support for approved generic voices, consented cloned voices, controlled speech-context presets, duration warnings, MP3 storage, and optional AAC `.m4a` export. The first release explicitly excludes LinkedIn sending and outreach automation; it only prepares audio assets for review and downstream use.

The main architecture risks are provider dependence, voice-consent misuse, approximate duration estimation, and batch jobs that can spend credits quickly. The system should therefore make voice approval, idempotent job creation, generated-audio measurement, and audit-friendly storage first-class behavior.

## 2. Verifiable Technology Recommendations

| Technology/Pattern | Rationale & Evidence |
|---|---|
| **ElevenLabs Text to Speech API** | ElevenLabs documents `POST /v1/text-to-speech/:voice_id`, where text is converted into speech using a selected `voice_id`, with an `output_format` query parameter defaulting to `mp3_44100_128`. This supports the MP3-first MVP. [cite:1] |
| **ElevenLabs Instant Voice Cloning** | ElevenLabs documents an Instant Voice Clone API under its Voices API. The MVP should use this for consented quick test voices and persist the returned ElevenLabs voice identifier locally. [cite:2] |
| **ElevenLabs Voice Design** | ElevenLabs describes Voice Design as creating voices from text prompts, including prompt guidance for accent, pacing, emotion, quality, and persona. This supports controlled generic/persona voice creation when library voices are insufficient. [cite:3] |
| **Application-owned duration controls** | LinkedIn Help states voice messages can be up to one minute long and are mobile-app-only. Since ElevenLabs TTS exposes audio generation controls but no hard `max_duration_seconds` cap, the app must estimate before generation and measure after generation. [cite:1] [cite:4] |
| **FastAPI backend** | FastAPI is a Python API framework with built-in OpenAPI/JSON Schema support and examples for file handling, background tasks, static files, and testing. This matches an API-first MVP with audio file uploads, generated files, and job status endpoints. [cite:5] |
| **openpyxl for Excel bulk input** | openpyxl is documented as a Python library for reading and writing Excel 2010 `.xlsx` and `.xlsm` files, matching the operator-facing workbook requirement. [cite:6] |
| **ffmpeg for `.m4a` export and ffprobe duration checks** | ffmpeg is the canonical command-line media tool for audio/video processing. Its documentation covers command-line media conversion, and the MVP can use it to create AAC mono `.m4a` exports and probe generated audio duration. [cite:7] |

Assumptions:

- The deployment server can run Python and install `ffmpeg`.
- ElevenLabs credentials will be provided as `ELEVENLABS_API_KEY`.
- Local disk persistence is acceptable for the MVP; object storage can be introduced later.
- LinkedIn sending is deliberately out of scope even though LinkedIn's one-minute limit informs duration warnings.

## 3. Browsed Sources

- [1] https://elevenlabs.io/docs/api-reference/text-to-speech/convert - Verified ElevenLabs TTS endpoint, `voice_id`, and `output_format`.
- [2] https://elevenlabs.io/docs/api-reference/voices/ivc/create - Verified ElevenLabs Instant Voice Clone API exists under Voices.
- [3] https://elevenlabs.io/docs/eleven-creative/voices/voice-design - Verified Voice Design prompt-based voice creation and prompt guidance.
- [4] https://www.linkedin.com/help/linkedin/answer/a548233 - Verified one-minute LinkedIn voice-message limit and mobile-app-only flow.
- [5] https://fastapi.tiangolo.com/ - Verified FastAPI API framework and documented support areas relevant to the MVP.
- [6] https://openpyxl.readthedocs.io/en/stable/ - Verified openpyxl reads/writes Excel `.xlsx`/`.xlsm` files.
- [7] https://ffmpeg.org/ffmpeg.html - Verified ffmpeg documentation for command-line media processing.
