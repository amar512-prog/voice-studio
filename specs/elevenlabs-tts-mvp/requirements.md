# Requirements Document

## Introduction

This document defines the testable requirements for the ElevenLabs TTS MVP. The system generates reviewed audio assets from text or Excel input, manages approved voices, supports consented voice cloning, estimates and measures duration, and stores MP3 plus optional `.m4a` export files.

## Glossary

- **SingleGenerationUI**: UI for one text-to-speech request.
- **VoiceCloneUI**: UI for uploading or recording clone-source audio with consent metadata.
- **BulkGenerationUI**: UI for workbook upload, batch status, and results.
- **ApiService**: HTTP API layer.
- **VoiceRegistry**: Persistent voice catalog and consent state.
- **VoiceCloneService**: ElevenLabs Instant Voice Clone workflow.
- **TtsGenerationService**: ElevenLabs Text to Speech generation workflow.
- **DurationService**: Duration estimation, measurement, and warning logic.
- **AudioExportService**: MP3-to-`.m4a` conversion.
- **BulkWorkbookService**: Excel workbook parser/writer.
- **JobQueue**: Idempotent asynchronous job execution.
- **StorageService**: File and metadata persistence.
- **ReviewService**: Human review state and audit trail.

## Requirements

### Requirement 1: Voice Registry
**Description**: Approved voice records must be persisted and reused safely.

#### Acceptance Criteria
1. WHEN an approved ElevenLabs voice is added, THE **VoiceRegistry** SHALL store its internal voice ID, ElevenLabs voice ID, display name, source type, consent status, supported accents, and default settings.
2. WHEN the generation UI requests voices, THE **VoiceRegistry** SHALL return only voices whose consent status is `not_required` or `approved`.
3. WHEN a stored ElevenLabs voice is no longer available, THE **VoiceRegistry** SHALL mark it `unavailable` and prevent new generation with that voice.

### Requirement 2: Voice Cloning
**Description**: The app must create cloned voices only from consented audio.

#### Acceptance Criteria
1. WHEN a user uploads an audio file for cloning, THE **VoiceCloneService** SHALL validate file presence, supported extension, non-empty audio, minimum duration, and consent metadata before calling ElevenLabs.
2. WHEN a user records live audio for cloning, THE **VoiceCloneUI** SHALL save the recording as an audio file and submit it through the same validation path as uploaded audio.
3. WHEN ElevenLabs returns a cloned voice ID, THE **VoiceCloneService** SHALL create a **VoiceRegistry** record and persist source, normalized, consent, and preview artifacts through **StorageService**.

### Requirement 3: Single Generation
**Description**: Users must generate one audio file from text and selected controls.

#### Acceptance Criteria
1. WHEN a valid request is submitted, THE **ApiService** SHALL resolve `voice_name + accent` to an approved **VoiceRegistry** voice.
2. WHEN the voice is approved, THE **TtsGenerationService** SHALL call ElevenLabs Text to Speech and store the returned MP3 through **StorageService**.
3. WHEN generation completes, THE **SingleGenerationUI** SHALL show a playable preview and download link for the MP3.

### Requirement 4: Speech Context Presets
**Description**: Delivery style must be controlled by safe presets.

#### Acceptance Criteria
1. WHEN a request includes `speech_context`, THE **ApiService** SHALL accept only configured preset values.
2. WHEN `speech_context` is accepted, THE **TtsGenerationService** SHALL map it to model, voice settings, and optional tag behavior before calling ElevenLabs.
3. WHEN a high-risk preset such as `character_dialogue` is requested, THE **ReviewService** SHALL require explicit human review before downstream use.

### Requirement 5: Duration Warnings
**Description**: The app must warn on duration risk without blocking estimated overages.

#### Acceptance Criteria
1. WHEN text is entered, THE **DurationService** SHALL estimate duration using `default_words_per_minute`.
2. WHEN estimated duration exceeds `target_duration_seconds`, THE **DurationService** SHALL return a yellow warning and still allow generation.
3. WHEN actual generated audio exceeds `max_duration_seconds`, THE **DurationService** SHALL return a red warning and replace any yellow warning.
4. WHEN actual generated audio is within `max_duration_seconds`, THE **DurationService** SHALL clear duration warnings.

### Requirement 6: M4A Export
**Description**: The app must optionally export LinkedIn-ready audio without automating sending.

#### Acceptance Criteria
1. WHEN `export_format` is `mp3_only`, THE **AudioExportService** SHALL skip `.m4a` conversion and return only MP3 output.
2. WHEN `export_format` is `linkedin_m4a`, THE **AudioExportService** SHALL convert the generated MP3 into AAC `.m4a`, mono, 64k bitrate, capped at 60 seconds.
3. WHEN `.m4a` export fails, THE **AudioExportService** SHALL mark the job with `m4a_export_failed` without deleting the MP3.

### Requirement 7: Excel Bulk Generation
**Description**: Operators must submit bulk requests with `.xlsx`, not CSV.

#### Acceptance Criteria
1. WHEN a workbook is uploaded, THE **BulkWorkbookService** SHALL require a worksheet named `tts_requests`.
2. WHEN the worksheet is present, THE **BulkWorkbookService** SHALL require `request_id`, `text`, `voice_name`, `accent`, `speech_context`, `target_duration_seconds`, `default_words_per_minute`, `output_format`, and `export_format`.
3. WHEN rows are valid, THE **JobQueue** SHALL create idempotent generation jobs using a stable hash of text, voice, accent, context, duration, model, settings version, and export format.
4. WHEN batch processing completes, THE **BulkWorkbookService** SHALL append status, estimated duration, actual duration, warning level, warning message, audio URL, export audio URL, error code, and error message.

### Requirement 8: API Contracts
**Description**: The system must expose stable APIs for current UI and future internal tools.

#### Acceptance Criteria
1. WHEN clients call `POST /api/tts`, THE **ApiService** SHALL validate the request and return a `job_id`, status, warning state, and audio URLs when complete.
2. WHEN clients call `POST /api/tts/batch`, THE **ApiService** SHALL accept an `.xlsx` file and return a batch job ID.
3. WHEN clients call `GET /api/jobs/{job_id}`, THE **ApiService** SHALL return job status, warnings, audio URLs, and error details.
4. WHEN clients call `GET /api/voices`, THE **ApiService** SHALL return only usable voices from **VoiceRegistry**.

### Requirement 9: Storage and Audit
**Description**: Generated audio, clone artifacts, and review metadata must be auditable.

#### Acceptance Criteria
1. WHEN a file is generated or uploaded, THE **StorageService** SHALL store it under the configured `data/` layout and return a stable URL or path.
2. WHEN clone or generation events occur, THE **StorageService** SHALL persist event metadata sufficient to reconstruct source, voice, settings, duration, and output files.
3. WHEN a reviewer approves or rejects output, THE **ReviewService** SHALL record reviewer, timestamp, status, and notes.

### Requirement 10: Operational Safety
**Description**: The MVP must prevent high-cost or unsafe misuse.

#### Acceptance Criteria
1. WHEN required fields are missing or unknown, THE **ApiService** SHALL reject the request with a deterministic error code.
2. WHEN `target_duration_seconds` exceeds 60, THE **ApiService** SHALL reject the request with `target_duration_too_long`.
3. WHEN provider calls fail or rate-limit, THE **JobQueue** SHALL retry only safe transient failures and persist final failure details.
4. WHEN outreach sending is requested, THE **ApiService** SHALL reject it because LinkedIn sending is out of MVP scope.
