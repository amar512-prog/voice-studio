# TTS Voice Cloning Research

Date: 2026-06-15

## Recommendation

Build the MVP on ElevenLabs only.

This is the right call if speech context, voice design, cloned voices, and production-quality delivery matter more than cheapest generation cost. ElevenLabs has the best fit for the requested product because it combines Text to Speech, Voice Library, Instant Voice Cloning, Professional Voice Cloning, and Voice Design under one platform.

The MVP should use ElevenLabs generic/library voices and Instant Voice Cloning first. Professional Voice Cloning should be reserved for approved, high-value voices because training takes longer and is not necessary for the first working tool.

Do not clone a celebrity, public figure, employee, customer, or third-party speaker unless there is explicit recorded consent and usage permission. For the pilot, use either Amar's own voice, Salman voice with consent, or ElevenLabs library/Voice Design voices.

## Requirement From Transcript

The requested product is a small UI plus API:

- UI input 1: pasted text.
- UI input 2: selected voice name, either cloned/person-specific or generic.
- UI input 3: accent, at minimum `us` and `in`.
- UI input 4: speech context / delivery preset, for example `outreach_conversational`, `narration`, `character_dialogue`, `customer_support`, or `announcement`.
- UI input 5: target length / duration, with LinkedIn default `55` seconds and hard maximum `60` seconds.
- UI input 6: default words per minute, default `135`, used only for estimated duration warnings before generation.
- Voice clone input: upload audio file, for example MP3/WAV/M4A, or record live audio in the browser and submit it for cloning.
- Output: MP3 source/preview audio from ElevenLabs plus final `.m4a` export when LinkedIn voice-note compatibility is needed.
- API input: text, voice/person name, accent, speech context, target/max duration, default words per minute.
- API output: MP3 source audio URL and optional LinkedIn-ready `.m4a` export URL.
- Bulk mode: Excel workbook (`.xlsx`) with `text`, `voice_name`, `accent`, `speech_context`, `target_duration_seconds`, `default_words_per_minute`; run asynchronously and let BDR/users download all generated files later.
- Deployment target: the existing "painpoint engine" server, likely under `wenotes.re.ai`.

## Speech Context Layer

Add speech context as a controlled preset, not a loose prompt box.

My recommendation: make `speech_context` required and `delivery_notes` optional/admin-only. This gives users useful control without letting operators accidentally create overacted, misleading, or inconsistent audio.

LinkedIn Help says LinkedIn Messaging voice messages can be up to one minute long, and the feature is available only on the LinkedIn mobile app. Treat `60` seconds as the product cap and default to `55` seconds to leave a safety buffer. The app should estimate duration before generation and verify actual audio duration after generation.

LinkedIn sending is out of scope for the first build. The MVP can still prepare the audio file in a LinkedIn-compatible voice-note format: AAC-encoded `.m4a` MPEG-4 audio, mono, `<=60` seconds. Treat the ElevenLabs MP3 as source/preview audio and the `.m4a` as the provider-ready export.

ElevenLabs does not expose a native hard `max_duration_seconds` control in the Text to Speech request. Duration handling must be implemented in our app: estimate before generation, show a yellow warning if the estimate is likely too long, optionally adjust voice speed within quality-safe bounds, then measure the generated audio. If the actual audio crosses the hard cap, show a red warning and remove the earlier yellow warning from the visible UI state.

Recommended MVP presets:

| Preset | Use case | Delivery | Risk |
|---|---|---|---|
| `outreach_conversational` | LinkedIn/outbound snippets | Warm, direct, natural, low-performance | Low |
| `customer_support` | Helpful explanation or follow-up | Clear, reassuring, measured | Low |
| `narration` | Longer explainers or product walkthroughs | Steady, polished, slightly slower | Low |
| `announcement` | Short update or CTA | Confident, concise, higher energy | Medium |
| `character_dialogue` | Demos, content, roleplay, multi-speaker scenes | Expressive, persona-driven | High |
| `dramatic_storytelling` | Creative content only | Emotional, theatrical | High |

For outreach, default to `outreach_conversational`. Do not allow `character_dialogue` or `dramatic_storytelling` in production outbound unless a reviewer explicitly approves the row. Character delivery can feel deceptive if it implies a persona or relationship that does not exist.

ElevenLabs-specific notes:

- ElevenLabs says voice selection is the most important control, because it determines gender, tone, accent, cadence, and delivery; model choice comes next, then settings.
- ElevenLabs Voice Design prompts can specify persona, emotion, timbre, pacing, accent, language, and style. This is useful when creating synthetic/generic voices, but less predictable than using a well-matched cloned or library voice.
- Eleven v3 supports richer delivery via audio tags such as `[whispers]`, `[sighs]`, `[sarcastic]`, `[curious]`, and `[excited]`; punctuation and capitalization also influence delivery.
- Eleven v3 can do multi-speaker dialogue, but this should be treated as a creative/content feature, not the default outreach flow.
- For stable outbound clips, start with natural/professional voices and conservative settings. Use expressive tags only after QA proves the voice still sounds credible.

## Provider Decision

Use ElevenLabs only for the first version.

Why this is best now:

- It directly supports the user's requirement for named voices, generic voices, cloned voices, and downloadable speech output.
- It supports Voice Design from text prompts, which is useful for creating generic persona voices such as "warm Indian business narrator" or "calm US customer-support voice".
- It supports Instant Voice Cloning for fast tests and Professional Voice Cloning for higher-quality approved voices.
- The Text to Speech API supports request-level `voice_id`, `model_id`, `language_code`, `voice_settings`, pronunciation dictionaries, seed, previous/next context, and output format.
- It does not provide a direct output-duration cap, so our system owns LinkedIn's one-minute enforcement.
- It avoids a provider abstraction too early. Build one clean ElevenLabs integration first; add adapters only if cost or rate limits become a real blocker.

Tradeoffs:

- Higher cost risk at bulk volume.
- Voice settings and emotional delivery still require QA; they are not deterministic.
- Accent should be implemented through selected voice/voice design/cloned sample quality, not treated as a guaranteed API-level accent switch.
- Professional Voice Cloning is not a same-day setup path because training can take hours.

## Growth Mechanism

The tool creates personalized audio snippets for outbound and LinkedIn workflows. The growth value is not "AI voice" by itself; it is faster production of human-reviewed, account-specific audio that can be attached to outreach after SDR approval.

The highest-value use case is batch generation after an outreach list has already passed account and contact qualification. Paid enrichment and audio generation should happen after the lead passes the normal company/person gates, because every generated clip costs money and review time.

## Workflow

1. Voice setup
   - Create approved generic voices from ElevenLabs Voice Library or Voice Design.
   - Create cloned voices only from consented speaker samples.
   - Accept two clone-source paths:
     - Uploaded audio file, for example MP3/WAV/M4A.
     - Live browser recording, saved as an audio file before cloning.
   - Normalize/validate clone samples before sending to ElevenLabs: supported file type, non-empty audio, minimum duration, readable speech, and acceptable background noise.
   - Call ElevenLabs Instant Voice Cloning using multipart file upload; persist the returned `voice_id`.
   - Store ElevenLabs `voice_id`, voice source, allowed accents/variants, consent status, and owner.
   - Save local persistence files for future use: source sample, consent artifact, preview clip, and voice registry metadata.
   - Important: the cloned model itself is stored in ElevenLabs. The local app persists the `elevenlabs_voice_id` and audit files on disk so the voice can be reused in later sessions.
   - For accent support, create or select separate voices/variants rather than assuming one voice can reliably switch accents.

2. Single generation
   - User pastes text, picks voice, picks accent.
   - User selects target length, default `55` seconds, maximum `60` seconds for LinkedIn.
   - User can adjust default words per minute, default `135`, for duration estimation.
   - Backend validates text length, estimated duration, voice permission, and accent support.
   - Backend shows a yellow warning if estimated duration exceeds `target_duration_seconds`, but still allows generation.
   - Backend maps `voice_name + accent` to an ElevenLabs `voice_id`.
   - Backend maps `speech_context` to ElevenLabs model/settings/tags.
   - Backend calls ElevenLabs Text to Speech API.
   - Backend measures the generated audio duration.
   - If audio exceeds `max_duration_seconds`, show a red warning and remove/replace any yellow pre-generation warning.
   - Save MP3 to local storage or object storage for preview, download, and audit.
   - If `export_format = linkedin_m4a`, convert the MP3 to AAC `.m4a`, mono, `<=60` seconds.
   - Return playable/downloadable MP3 and, when requested, downloadable `.m4a`.

3. Bulk generation
   - User uploads an Excel workbook with one worksheet named `tts_requests`.
   - System validates rows and dedupes by content hash.
   - Queue jobs with idempotency key: `sha256(text + voice_id + accent + speech_context + target_duration_seconds + model_id + voice_settings_version)`.
   - Worker processes rows with retries and rate-limit handling.
   - UI shows status: pending, processing, complete, failed, rejected.
   - User downloads ZIP, individual files, or a completed Excel workbook with status/audio links appended.

4. Generation API
   - Internal tools or future outreach systems call `POST /api/tts`.
   - For bulk, it calls `POST /api/tts/batch`.
   - API returns `job_id` immediately, then provides MP3 and optional `.m4a` audio URLs when complete.

5. Human review
   - BDR reviews text and generated audio before sending.
   - System logs reviewer, timestamp, and final approval.

6. Voice reuse
   - On app startup, load persisted voice records from disk/database.
   - Verify each stored `elevenlabs_voice_id` still exists through ElevenLabs `List voices` or `Get voice`.
   - Show only approved voices in the generation dropdown.
   - If a local voice record exists but ElevenLabs no longer has the voice, mark it `unavailable` and block generation until repaired or re-cloned.

## Qualification Rules

Hard filters:

- Reject cloned voice if `consent_status != approved`.
- Reject voice if usage rights do not allow commercial/outbound use.
- Reject clone creation without explicit speaker consent.
- Reject clone sample if it is missing, corrupted, too short, or mostly noise/music.
- Reject public figure / celebrity voice cloning unless a licensed marketplace/rightsholder agreement exists.
- Reject text that includes unsupported claims, fabricated personalization, sensitive attributes, or legal/medical/financial deception.
- Reject rows without `text`, `voice_name`, `accent`, `speech_context`, `target_duration_seconds`, `default_words_per_minute`, and `output_format`.
- Reject workbooks missing the `tts_requests` sheet or required headers.
- Reject unknown or disallowed `speech_context` values.
- Reject `character_dialogue` and `dramatic_storytelling` for outbound unless `review_required = true`.
- Reject text above ElevenLabs/API limits or the configured internal limit, for example 1,000 characters for first pilot.
- Reject `target_duration_seconds > 60` for LinkedIn voice-message output.
- Show a yellow warning, not a rejection, when estimated duration exceeds `target_duration_seconds`.
- Show a red warning when measured audio duration exceeds `max_duration_seconds`; red replaces/removes yellow warning state.

Scoring criteria:

- `+2` concise message under 45 seconds of generated audio.
- `+1` generated audio between 45 and 55 seconds.
- `-4` generated audio above 55 seconds for LinkedIn, because it is near the hard 60-second cap.
- `+2` company/contact already passed outreach qualification.
- `+1` accent matches prospect region.
- `-3` generic, spammy, or unverifiable personalization.
- `-5` no consent for cloned voice.

Rejection reasons:

- `missing_required_column`
- `missing_required_sheet`
- `unsupported_speech_context`
- `speech_context_not_allowed_for_channel`
- `unknown_voice`
- `unsupported_accent`
- `voice_not_approved`
- `clone_sample_invalid`
- `clone_consent_missing`
- `unlicensed_voice`
- `text_too_long`
- `target_duration_too_long`
- `generated_audio_too_long`
- `m4a_export_failed`
- `unsafe_or_deceptive_copy`
- `elevenlabs_generation_failed`

## Implementation

Recommended first schema:

```sql
voices(
  id text primary key,
  elevenlabs_voice_id text not null,
  display_name text not null,
  voice_type text check (voice_type in ('library','voice_design','instant_clone','professional_clone')),
  source_type text check (source_type in ('elevenlabs_library','voice_design','uploaded_audio','live_recording')),
  source_audio_path text,
  consent_artifact_path text,
  preview_audio_path text,
  consent_status text check (consent_status in ('not_required','pending','approved','rejected')),
  consent_owner text,
  allowed_use text,
  supported_accents jsonb,
  default_model_id text not null default 'eleven_multilingual_v2',
  default_voice_settings jsonb,
  created_at timestamptz default now()
);

tts_jobs(
  id text primary key,
  idempotency_key text unique not null,
  source text check (source in ('ui','api','xlsx')),
  input_text text not null,
  voice_id text references voices(id),
  accent text not null,
  speech_context text not null,
  target_duration_seconds integer not null default 55,
  max_duration_seconds integer not null default 60,
  default_words_per_minute integer not null default 135,
  estimated_duration_seconds numeric,
  actual_duration_seconds numeric,
  duration_warning_level text check (duration_warning_level in ('none','yellow','red')) default 'none',
  duration_warning_message text,
  delivery_notes text,
  elevenlabs_voice_id text not null,
  model_id text not null,
  voice_settings jsonb,
  output_format text not null default 'mp3_44100_128',
  export_format text check (export_format in ('mp3_only','linkedin_m4a')) default 'mp3_only',
  status text check (status in ('queued','processing','complete','failed','rejected')),
  audio_url text,
  export_audio_url text,
  error_code text,
  error_message text,
  created_at timestamptz default now(),
  completed_at timestamptz
);
```

Optional operational table:

```sql
voice_clone_events(
  id text primary key,
  voice_id text references voices(id),
  event_type text check (event_type in ('uploaded','recorded','normalized','submitted_to_elevenlabs','created','failed','verified_unavailable')),
  event_payload jsonb,
  created_at timestamptz default now()
);
```

Recommended disk layout for persistence:

```text
data/
  voices/
    voice_<internal_voice_id>/
      source/
        original.<ext>
        normalized.wav
      consent/
        consent.json
        consent_recording.<ext>
      previews/
        first_preview.mp3
      registry.json
  generated_audio/
    tts_<job_id>.mp3
    tts_<job_id>.m4a
```

LinkedIn-compatible `.m4a` export:

```bash
ffmpeg -i input.mp3 -ac 1 -c:a aac -b:a 64k -t 60 output.m4a
```

Export rules:

- Source file: ElevenLabs MP3.
- Final file extension: `.m4a`.
- Container/codec: MPEG-4 audio with AAC.
- Channels: mono (`-ac 1`).
- Bitrate: `64k` is sufficient for speech.
- Duration: trim/cap at `60` seconds with `-t 60`.
- If actual generated audio is longer than 60 seconds, still show the red warning; trimming creates a compatible file but may cut off the message, so reviewer approval is required before use.

`registry.json` example:

```json
{
  "internal_voice_id": "voice_amar_in_001",
  "elevenlabs_voice_id": "c38kUX8pkfYO2kHyqfFy",
  "display_name": "Amar - India",
  "voice_type": "instant_clone",
  "source_type": "live_recording",
  "source_audio_path": "data/voices/voice_amar_in_001/source/normalized.wav",
  "consent_status": "approved",
  "consent_owner": "Amar Agnihotri",
  "allowed_use": "internal_outreach_audio_generation",
  "supported_accents": ["in"],
  "created_at": "2026-06-15T00:00:00Z"
}
```

API contract:

```json
POST /api/tts
{
  "text": "Hi Amar, quick note...",
  "voice_name": "amar_clone",
  "accent": "in",
  "speech_context": "outreach_conversational",
  "target_duration_seconds": 55,
  "max_duration_seconds": 60,
  "default_words_per_minute": 135,
  "delivery_notes": "warm, natural, not salesy",
  "model_id": "eleven_multilingual_v2",
  "output_format": "mp3_44100_128",
  "export_format": "linkedin_m4a"
}
```

```json
{
  "job_id": "tts_123",
  "status": "complete",
  "duration_warning_level": "none",
  "actual_duration_seconds": 43.8,
  "audio_url": "https://wenotes.re.ai/audio/tts_123.mp3",
  "export_audio_url": "https://wenotes.re.ai/audio/tts_123.m4a"
}
```

Excel workbook format:

Worksheet name: `tts_requests`

Required columns:

| request_id | text | voice_name | accent | speech_context | target_duration_seconds | default_words_per_minute | output_format | export_format |
|---|---|---|---|---|---:|---:|---|---|
| req_001 | Hi Priya, quick note, I noticed your team is hiring SDRs. | generic_female_in | in | outreach_conversational | 55 | 135 | mp3_44100_128 | linkedin_m4a |
| req_002 | Hi John, quick note, saw your recent expansion update. | generic_male_us | us | outreach_conversational | 55 | 135 | mp3_44100_128 | mp3_only |

Why Excel instead of CSV:

- Outreach text often contains commas, quotes, line breaks, and personalization snippets.
- Excel is easier for BDR/operators to review, filter, and correct before generation.
- Data validation dropdowns can restrict `voice_name`, `accent`, `speech_context`, `target_duration_seconds`, `default_words_per_minute`, `output_format`, and `export_format`.
- The same workbook can be returned with appended `status`, `estimated_duration_seconds`, `actual_duration_seconds`, `duration_warning_level`, `duration_warning_message`, `audio_url`, `export_audio_url`, `error_code`, and `error_message` columns.

Optional import support:

- CSV can be supported later for API/internal pipelines, but `.xlsx` should be the default UI upload format.

ElevenLabs generation interface:

```ts
interface ElevenLabsTts {
  listVoices(): Promise<Voice[]>;
  createInstantClone(input: {
    name: string;
    audioPaths: string[];
    consentOwner: string;
    sourceType: "uploaded_audio" | "live_recording";
    removeBackgroundNoise?: boolean;
  }): Promise<Voice>;
  synthesize(input: {
    text: string;
    voiceId: string;
    modelId: string;
    speechContext: string;
    targetDurationSeconds: number;
    maxDurationSeconds: number;
    defaultWordsPerMinute: number;
    deliveryNotes?: string;
    outputFormat: string;
    exportFormat: "mp3_only" | "linkedin_m4a";
  }): Promise<Buffer>;
}
```

Duration validation:

```ts
function estimateDurationSeconds(text: string, wordsPerMinute = 135): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return (words / wordsPerMinute) * 60;
}

function getPreGenerationDurationWarning(input: {
  text: string;
  targetDurationSeconds: number;
  maxDurationSeconds: number;
  defaultWordsPerMinute: number;
}) {
  if (input.maxDurationSeconds > 60) return "target_duration_too_long";
  if (input.targetDurationSeconds > input.maxDurationSeconds) return "target_duration_too_long";

  const estimated = estimateDurationSeconds(input.text, input.defaultWordsPerMinute);
  if (estimated > input.targetDurationSeconds) {
    return {
      level: "yellow",
      message: `Estimated duration is ${estimated.toFixed(1)}s, above the ${input.targetDurationSeconds}s target.`
    };
  }

  return { level: "none", message: null };
}

function getPostGenerationDurationWarning(input: { actualDurationSeconds: number; maxDurationSeconds: number }) {
  if (input.actualDurationSeconds > input.maxDurationSeconds) {
    return {
      level: "red",
      message: `Generated audio is ${input.actualDurationSeconds.toFixed(1)}s, above the ${input.maxDurationSeconds}s hard limit.`
    };
  }

  return { level: "none", message: null };
}
```

UI rule: before generation, show at most one yellow estimated-duration warning. After generation, recompute warning state from the actual audio duration. If actual duration crosses the hard limit, show only the red warning and remove the yellow warning. If actual duration is within limit, clear the warning.

For the first pilot, use a conservative copy guideline: keep LinkedIn audio scripts under roughly `110-125` spoken words at the default `135` WPM estimate. The exact limit depends on voice speed, accent, pauses, and delivery preset, so the generated file must still be measured after creation.

ElevenLabs rendering logic:

```ts
const deliveryPresets = {
  outreach_conversational: {
    modelId: "eleven_multilingual_v2",
    textPrefix: "",
    style: "warm, direct, conversational, lightly upbeat, not theatrical",
    voiceSettings: {
      stability: 0.55,
      similarity_boost: 0.75,
      style: 0.15,
      use_speaker_boost: true,
      speed: 1.0
    },
    elevenLabsTags: [],
    reviewRequired: false
  },
  customer_support: {
    modelId: "eleven_multilingual_v2",
    style: "clear, patient, reassuring",
    voiceSettings: {
      stability: 0.65,
      similarity_boost: 0.75,
      style: 0.1,
      use_speaker_boost: true,
      speed: 0.95
    },
    elevenLabsTags: [],
    reviewRequired: false
  },
  narration: {
    modelId: "eleven_multilingual_v2",
    style: "steady, polished, articulate, measured",
    voiceSettings: {
      stability: 0.7,
      similarity_boost: 0.75,
      style: 0.2,
      use_speaker_boost: true,
      speed: 0.95
    },
    elevenLabsTags: [],
    reviewRequired: false
  },
  character_dialogue: {
    modelId: "eleven_multilingual_v2",
    style: "persona-driven, emotionally expressive",
    voiceSettings: {
      stability: 0.35,
      similarity_boost: 0.7,
      style: 0.6,
      use_speaker_boost: true,
      speed: 1.0
    },
    elevenLabsTags: ["[curious]", "[excited]", "[sighs]"],
    reviewRequired: true
  }
};
```

Important implementation note: the numeric `voiceSettings` above are starting presets, not guaranteed final values. Test each voice because ElevenLabs voice selection and source samples strongly affect pacing, accent, and expressiveness.

## Experiment

Smallest useful pilot:

- Create 2 generic voices and 1 consented cloned voice.
- Generate 30 audio clips: 10 India accent, 10 US accent, 10 generic control.
- Use only already-qualified prospects.
- BDR reviews every generated clip before use.
- Measure generation success rate, average cost per clip, average turnaround time, reviewer approval rate, reply rate, and positive reply rate.

Success threshold:

- 95% generation success.
- Under 2 minutes for single clip.
- Under 60 minutes for a 100-row Excel batch.
- 100% of LinkedIn-targeted clips measured at or below 60 seconds.
- 80%+ reviewer approval.
- Positive reply rate beats non-audio control by at least 20% relative, or produces clear qualitative learning.

Stopping conditions:

- ElevenLabs blocks the account or flags the use case.
- Reviewer approval below 60%.
- Prospects complain about deception or voice impersonation.
- Cost per usable clip is too high for the reply-rate lift.

## Risks

- Consent and impersonation risk is the biggest issue. Cloned voices must be opt-in and logged.
- Outreach delivery is explicitly out of scope for the MVP; do not automate LinkedIn sending in this phase.
- Accent control is voice-dependent and may sound unnatural if the selected voice/sample does not match the requested accent.
- Bulk generation can burn credits quickly if workbook validation is weak.
- Same text generated twice can produce different audio; use idempotency if repeatability matters.
- ElevenLabs pricing, rate limits, and voice-cloning policies can change.

## Next Action

Run a same-day technical spike with ElevenLabs:

1. Create or confirm an ElevenLabs account and API key.
2. Select two generic/library voices: one India-suitable and one US-suitable.
3. Create one Instant Voice Clone from a consented test speaker.
4. Generate 6 clips: 2 generic India, 2 generic US, 2 cloned voice.
5. Use `outreach_conversational` for all first-pass clips.
6. Save outputs, record latency/cost/quality notes, then lock the voice IDs for the MVP.

## Sources Checked

- ElevenLabs pricing: https://elevenlabs.io/pricing
- ElevenLabs text-to-speech API: https://elevenlabs.io/docs/api-reference/text-to-speech/convert
- ElevenLabs Instant Voice Clone API: https://elevenlabs.io/docs/api-reference/voices/ivc/create
- ElevenLabs Professional Voice Clone API: https://elevenlabs.io/docs/api-reference/voices/pvc/create
- ElevenLabs voice cloning overview: https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning
- ElevenLabs text-to-speech best practices: https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices
- ElevenLabs Voice Design prompting: https://elevenlabs.io/docs/eleven-creative/voices/voice-design
- LinkedIn voice message limit: https://www.linkedin.com/help/linkedin/answer/a548233
