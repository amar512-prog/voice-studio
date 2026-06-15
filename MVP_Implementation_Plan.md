# ElevenLabs TTS MVP Implementation Plan

Date: 2026-06-15

## Recommendation

Build a narrow MVP that stops at generated audio files:

```text
Text / Excel input
-> ElevenLabs voice selection or clone
-> speech context preset
-> duration warning
-> MP3 preview/source
-> optional AAC mono .m4a export
```

Do not build LinkedIn sending in this version. The highest-confidence path is to first prove reliable voice creation, MP3 generation, duration checks, and batch output.

## Analysis

The current product risk is not UI complexity. The real risks are voice consent, unreliable duration control, provider cost, and operator misuse.

The MVP should therefore optimize for:

- Fast single-generation flow.
- Persistent approved voice registry.
- Clear consent boundary for cloned voices.
- Deterministic validation and audit logs.
- Excel bulk generation with resumable jobs.
- Human review before any downstream outreach use.

ElevenLabs is the right provider for this phase because it handles generic voices, Voice Design, Instant Voice Cloning, Professional Voice Cloning, and Text to Speech under one API surface. The app still owns duration logic because ElevenLabs does not provide a hard output-duration cap.

## Growth Mechanism

The tool creates short, reviewed audio snippets for outbound workflows. It should only run after the account/contact has already passed qualification; otherwise the team will burn credits producing audio for weak leads.

The commercially useful mechanism is:

```text
Qualified lead
-> reviewed script
-> selected approved voice
-> generated audio
-> human approval
-> downstream use
```

## MVP Scope

In scope:

- Single text-to-speech UI.
- ElevenLabs API integration.
- Generic/library voices.
- Instant voice clone from uploaded audio.
- Instant voice clone from browser recording.
- Persistent local voice registry.
- Speech context presets.
- Duration estimate and warning states.
- MP3 output.
- Optional `.m4a` export using AAC, mono, max 60 seconds.
- Excel bulk upload and result workbook.
- API endpoints for single and batch generation.

Out of scope:

- LinkedIn sending.
- Unipile/Prosp integration.
- Browser/device automation.
- CRM integration.
- Paid enrichment.
- Fully automated outreach.
- Professional Voice Cloning as a default path.

## Workflow

1. Voice registry
   - Admin adds ElevenLabs library/Voice Design voice, or creates an Instant Clone.
   - App stores internal `voice_id`, `elevenlabs_voice_id`, display name, source type, consent status, supported accents, and local audit files.
   - Only `approved` voices appear in generation dropdowns.

2. Voice cloning
   - User uploads MP3/WAV/M4A or records live in browser.
   - App validates audio file exists, has speech, meets minimum duration, and is tied to explicit consent.
   - App calls ElevenLabs Instant Voice Clone and stores returned `elevenlabs_voice_id`.
   - App saves original sample, normalized sample, consent artifact, preview clip, and registry metadata.

3. Single generation
   - User enters text.
   - User selects voice, accent, speech context, target duration, WPM estimate, and export format.
   - App estimates duration.
   - If estimate exceeds target, show yellow warning but allow generation.
   - App calls ElevenLabs TTS.
   - App measures actual MP3 duration.
   - If actual duration exceeds 60 seconds, show red warning and clear yellow.
   - App optionally exports `.m4a`.

4. Bulk generation
   - User uploads `.xlsx` with `tts_requests` worksheet.
   - App validates required columns.
   - App creates idempotent jobs.
   - Worker processes rows with rate-limit-aware retries.
   - App returns completed workbook with status, warnings, audio links, and errors.

5. Review
   - User reviews generated audio.
   - App logs reviewer, approval status, and timestamp.
   - Sending happens outside this MVP.

## Qualification Rules

Hard filters:

- No cloned voice without explicit consent.
- No celebrity/public-figure voice cloning without rights.
- No unapproved cloned voice in dropdown.
- Reject unknown `voice_name`, `accent`, `speech_context`, or `export_format`.
- Reject missing Excel headers.
- Reject text above configured internal character limit.
- Reject `target_duration_seconds > 60`.

Warnings:

- Yellow before generation when estimated duration exceeds target.
- Red after generation when actual duration exceeds hard cap.
- Red warning replaces yellow warning.

Recommended first limits:

- `target_duration_seconds`: default `55`.
- `max_duration_seconds`: `60`.
- `default_words_per_minute`: `135`.
- First-pilot text limit: `1,000` characters.
- LinkedIn-style script guidance: roughly `110-125` words.

## Implementation

Recommended stack if no existing app exists:

- Backend: Python FastAPI.
- Queue: SQLite-backed job table for MVP, Redis/RQ later if needed.
- Excel: `openpyxl`.
- Audio duration: `ffprobe` or Python audio metadata library.
- Audio conversion: `ffmpeg`.
- Storage: local `data/` directory first, object storage later.
- UI: simple server-rendered page or lightweight React only if needed.

Core endpoints:

```text
GET  /api/voices
POST /api/voices/clone
POST /api/tts
POST /api/tts/batch
GET  /api/jobs/{job_id}
GET  /audio/{filename}
```

Minimum tables/files:

- `voices`
- `tts_jobs`
- `voice_clone_events`
- `data/voices/<voice_id>/registry.json`
- `data/generated_audio/<job_id>.mp3`
- `data/generated_audio/<job_id>.m4a`

M4A export command:

```bash
ffmpeg -i input.mp3 -ac 1 -c:a aac -b:a 64k -t 60 output.m4a
```

Important: trimming with `-t 60` creates a compatible file, but if the original audio was longer than 60 seconds, the UI must still show a red warning because the content may be cut off.

## Phased Plan

Phase 0: Spike

- Create ElevenLabs API key.
- Pick 2 library voices.
- Clone 1 consented test voice.
- Generate 6 MP3 files.
- Measure latency, cost, voice quality, and duration accuracy.

Phase 1: Backend MVP

- Create FastAPI app.
- Add voice registry persistence.
- Add ElevenLabs TTS client.
- Save MP3 output.
- Measure audio duration.
- Add warning logic.
- Add `.m4a` export.

Phase 2: Single UI

- Text box.
- Voice dropdown.
- Accent dropdown.
- Speech context dropdown.
- Duration/WPM inputs.
- Export format toggle.
- Audio preview and download.
- Yellow/red warning states.

Phase 3: Voice Clone UI

- Upload audio file.
- Browser recording.
- Consent checkbox/metadata.
- Clone submission.
- Voice approval state.
- Preview generated test clip.

Phase 4: Excel Bulk

- Upload `.xlsx`.
- Validate worksheet and columns.
- Queue rows.
- Show progress.
- Return completed workbook.
- Zip generated files if needed.

Phase 5: Deployment

- Deploy on `wenotes.re.ai` or the painpoint engine server.
- Configure `ELEVENLABS_API_KEY`.
- Ensure `ffmpeg` is installed.
- Add backup strategy for `data/voices` and generated audio.

## Experiment

Smallest useful pilot:

- 2 generic voices.
- 1 cloned consented voice.
- 30 generated clips.
- 10 India accent, 10 US accent, 10 cloned voice.
- Every clip reviewed by a human.

Success metrics:

- 95% generation success.
- Under 2 minutes for single clip.
- Under 60 minutes for 100-row Excel batch.
- 100% measured duration available.
- 0 unapproved cloned voices usable.
- 80% reviewer approval.

Stopping conditions:

- Consent process is unclear.
- Clone quality is not good enough.
- Cost per usable clip is too high.
- Duration warnings are too noisy to trust.
- ElevenLabs blocks/flags the use case.

## Risks

- Voice impersonation and consent are the highest-risk areas.
- Duration estimates are approximate; only measured audio duration is authoritative.
- Accent is voice-dependent, not a guaranteed API switch.
- `.m4a` export can trim content if the generated audio is too long.
- Bulk jobs can burn credits quickly without strong validation.
- Local disk persistence needs backup before production usage.

## Next Action

Build Phase 0 and Phase 1 only:

1. Scaffold a minimal FastAPI app.
2. Add ElevenLabs key configuration.
3. Implement `POST /api/tts`.
4. Save MP3 output.
5. Measure duration.
6. Export `.m4a` with ffmpeg.
7. Return audio URLs and warning state.

Once this works, add the UI and clone workflow.
