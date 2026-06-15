# Design Document

## Overview

The MVP is a small API-first web app around ElevenLabs. It persists approved voices, creates consented clones, generates MP3 audio, measures duration, optionally exports `.m4a`, supports `.xlsx` bulk jobs, and records review metadata. LinkedIn sending is not implemented.

## Design Principles

- Keep provider logic isolated in **TtsGenerationService** and **VoiceCloneService**.
- Persist every generated artifact through **StorageService**.
- Treat duration estimation as advisory and actual audio measurement as authoritative.
- Require explicit voice approval before generation.
- Make bulk jobs idempotent and resumable.
- Make unsafe requests fail with deterministic error codes.

## Component Specifications

### Component: SingleGenerationUI
**Purpose**: Collect single-generation inputs, show warnings, preview audio, and expose downloads.
**Location**: `app/ui/single_generation.py` or `app/templates/single_generation.html`

**Interface**:
```text
GET /
POST /api/tts
Consumes: text, voice_name, accent, speech_context, target_duration_seconds,
          max_duration_seconds, default_words_per_minute, output_format, export_format
Implements: Req 3.3, Req 5.2, Req 5.3, Req 5.4
```

**Dependencies**:
- **ApiService**: submits generation requests and polls job status.

**Data Model**:
```text
SingleGenerationForm {
  text: string
  voice_name: string
  accent: string
  speech_context: string
  target_duration_seconds: int = 55
  max_duration_seconds: int = 60
  default_words_per_minute: int = 135
  output_format: string = "mp3_44100_128"
  export_format: "mp3_only" | "linkedin_m4a"
}
```

### Component: VoiceCloneUI
**Purpose**: Collect clone-source audio and consent metadata for approved voice creation.
**Location**: `app/ui/voice_clone.py` or `app/templates/voice_clone.html`

**Interface**:
```text
POST /api/voices/clone
Consumes: audio file or browser recording, display_name, source_type, consent_owner,
          consent_status, supported_accents
Implements: Req 2.2
```

**Dependencies**:
- **ApiService**: submits clone requests.
- Browser MediaRecorder API: records live audio before upload.

**Data Model**:
```text
VoiceCloneForm {
  display_name: string
  source_type: "uploaded_audio" | "live_recording"
  audio_file: file
  consent_owner: string
  consent_status: "approved"
  supported_accents: string[]
}
```

### Component: BulkGenerationUI
**Purpose**: Upload workbooks, display batch progress, and download result workbooks/files.
**Location**: `app/ui/bulk_generation.py` or `app/templates/bulk_generation.html`

**Interface**:
```text
POST /api/tts/batch
GET /api/jobs/{job_id}
Implements: Req 7.1, Req 7.4, Req 8.2, Req 8.3
```

**Dependencies**:
- **ApiService**: uploads workbook and polls batch status.

**Data Model**:
```text
BulkUpload {
  workbook: .xlsx file
}
```

### Component: ApiService
**Purpose**: Expose HTTP endpoints and enforce request/response contracts.
**Location**: `app/api.py`

**Interface**:
```text
GET  /api/voices
POST /api/voices/clone
POST /api/tts
POST /api/tts/batch
GET  /api/jobs/{job_id}
GET  /audio/{filename}
Implements: Req 3.1, Req 4.1, Req 8.1, Req 8.2, Req 8.3, Req 8.4, Req 10.1, Req 10.2, Req 10.4
```

**Dependencies**:
- **VoiceRegistry**
- **VoiceCloneService**
- **TtsGenerationService**
- **DurationService**
- **BulkWorkbookService**
- **JobQueue**
- **StorageService**
- **ReviewService**

**Data Model**:
```text
TtsRequest {
  text: string
  voice_name: string
  accent: string
  speech_context: string
  target_duration_seconds: int
  max_duration_seconds: int
  default_words_per_minute: int
  delivery_notes?: string
  model_id: string
  output_format: string
  export_format: "mp3_only" | "linkedin_m4a"
}

TtsResponse {
  job_id: string
  status: string
  duration_warning_level: "none" | "yellow" | "red"
  duration_warning_message?: string
  actual_duration_seconds?: float
  audio_url?: string
  export_audio_url?: string
  error_code?: string
  error_message?: string
}
```

### Component: VoiceRegistry
**Purpose**: Persist approved voices, consent metadata, ElevenLabs voice IDs, and voice availability state.
**Location**: `app/services/voice_registry.py`

**Interface**:
```text
list_usable_voices() -> list[VoiceRecord]
get_approved_voice(voice_name: str, accent: str) -> VoiceRecord
create_voice(record: VoiceRecord) -> VoiceRecord
mark_unavailable(internal_voice_id: str) -> None
verify_remote_voice(record: VoiceRecord) -> VoiceAvailability
Implements: Req 1.1, Req 1.2, Req 1.3, Req 3.1, Req 8.4
```

**Dependencies**:
- **StorageService**: reads and writes voice registry JSON/database rows.
- ElevenLabs Voices API: verifies remote voice availability.

**Data Model**:
```text
VoiceRecord {
  id: string
  elevenlabs_voice_id: string
  display_name: string
  voice_type: "library" | "voice_design" | "instant_clone" | "professional_clone"
  source_type: "elevenlabs_library" | "voice_design" | "uploaded_audio" | "live_recording"
  consent_status: "not_required" | "pending" | "approved" | "rejected"
  consent_owner?: string
  supported_accents: string[]
  default_model_id: string
  default_voice_settings: object
  availability: "available" | "unavailable"
}
```

### Component: VoiceCloneService
**Purpose**: Validate clone samples and create ElevenLabs Instant Voice Clones.
**Location**: `app/services/voice_clone_service.py`

**Interface**:
```text
validate_clone_request(input: CloneRequest) -> ValidationResult
create_instant_clone(input: CloneRequest) -> VoiceRecord
Implements: Req 2.1, Req 2.3, Req 9.2
```

**Dependencies**:
- ElevenLabs IVC API
- **StorageService**
- **VoiceRegistry**
- **DurationService** for sample duration checks

**Data Model**:
```text
CloneRequest {
  display_name: string
  audio_paths: string[]
  source_type: "uploaded_audio" | "live_recording"
  consent_owner: string
  consent_status: "approved"
  supported_accents: string[]
  remove_background_noise?: bool
}
```

### Component: TtsGenerationService
**Purpose**: Call ElevenLabs Text to Speech and create MP3 source audio.
**Location**: `app/services/tts_generation_service.py`

**Interface**:
```text
synthesize(request: TtsRequest, voice: VoiceRecord) -> GeneratedAudio
resolve_preset(speech_context: string) -> DeliveryPreset
Implements: Req 3.2, Req 4.2
```

**Dependencies**:
- ElevenLabs TTS API
- **StorageService**
- **DurationService**

**Data Model**:
```text
DeliveryPreset {
  speech_context: string
  model_id: string
  voice_settings: object
  review_required: bool
}

GeneratedAudio {
  job_id: string
  audio_path: string
  audio_url: string
  output_format: string
}
```

### Component: DurationService
**Purpose**: Estimate text duration, measure generated audio duration, and produce yellow/red warning states.
**Location**: `app/services/duration_service.py`

**Interface**:
```text
estimate_duration_seconds(text: str, words_per_minute: int) -> float
pre_generation_warning(text: str, target_seconds: int, max_seconds: int, wpm: int) -> DurationWarning
measure_audio_duration(path: str) -> float
post_generation_warning(actual_seconds: float, max_seconds: int) -> DurationWarning
Implements: Req 5.1, Req 5.2, Req 5.3, Req 5.4
```

**Dependencies**:
- `ffprobe` or media metadata parser.

**Data Model**:
```text
DurationWarning {
  level: "none" | "yellow" | "red"
  message?: string
  estimated_duration_seconds?: float
  actual_duration_seconds?: float
}
```

### Component: AudioExportService
**Purpose**: Convert generated MP3 files into AAC mono `.m4a` exports when requested.
**Location**: `app/services/audio_export_service.py`

**Interface**:
```text
export_if_requested(job: TtsJob) -> ExportResult
export_linkedin_m4a(input_mp3: str, output_m4a: str) -> ExportResult
Implements: Req 6.1, Req 6.2, Req 6.3
```

**Dependencies**:
- `ffmpeg`
- **StorageService**

**Data Model**:
```text
ExportResult {
  export_format: "mp3_only" | "linkedin_m4a"
  export_audio_path?: string
  export_audio_url?: string
  error_code?: "m4a_export_failed"
}
```

### Component: BulkWorkbookService
**Purpose**: Parse, validate, and write `.xlsx` bulk-generation workbooks.
**Location**: `app/services/bulk_workbook_service.py`

**Interface**:
```text
parse_workbook(path: str) -> list[BulkRequestRow]
validate_headers(workbook) -> ValidationResult
write_results(original_path: str, rows: list[BulkResultRow]) -> str
Implements: Req 7.1, Req 7.2, Req 7.4
```

**Dependencies**:
- openpyxl
- **StorageService**

**Data Model**:
```text
BulkRequestRow {
  request_id: string
  text: string
  voice_name: string
  accent: string
  speech_context: string
  target_duration_seconds: int
  default_words_per_minute: int
  output_format: string
  export_format: "mp3_only" | "linkedin_m4a"
}
```

### Component: JobQueue
**Purpose**: Create idempotent jobs, run batch rows, retry provider-safe failures, and expose status.
**Location**: `app/services/job_queue.py`

**Interface**:
```text
create_job(request: TtsRequest) -> TtsJob
create_batch_jobs(rows: list[BulkRequestRow]) -> BatchJob
run_job(job_id: str) -> TtsJob
get_job(job_id: str) -> TtsJob
Implements: Req 7.3, Req 8.3, Req 10.3
```

**Dependencies**:
- **TtsGenerationService**
- **DurationService**
- **AudioExportService**
- **StorageService**

**Data Model**:
```text
TtsJob {
  id: string
  idempotency_key: string
  status: "queued" | "processing" | "complete" | "failed" | "rejected"
  request: TtsRequest
  audio_url?: string
  export_audio_url?: string
  error_code?: string
  error_message?: string
}
```

### Component: StorageService
**Purpose**: Store voice artifacts, generated audio, registry JSON, and downloadable file URLs.
**Location**: `app/services/storage_service.py`

**Interface**:
```text
save_voice_artifact(voice_id: str, kind: str, file: bytes) -> str
save_generated_audio(job_id: str, ext: str, file: bytes) -> str
write_registry(record: VoiceRecord) -> str
write_event(event: AuditEvent) -> None
public_url(path: str) -> str
Implements: Req 2.3, Req 9.1, Req 9.2
```

**Dependencies**:
- Local filesystem under `data/`.

**Data Model**:
```text
data/
  voices/<voice_id>/
  generated_audio/<job_id>.mp3
  generated_audio/<job_id>.m4a
```

### Component: ReviewService
**Purpose**: Record human review status and prevent silent use of risky outputs.
**Location**: `app/services/review_service.py`

**Interface**:
```text
mark_review(job_id: str, reviewer: str, status: ReviewStatus, notes?: str) -> ReviewRecord
requires_review(job: TtsJob) -> bool
Implements: Req 4.3, Req 9.3
```

**Dependencies**:
- **StorageService** or database.

**Data Model**:
```text
ReviewRecord {
  job_id: string
  reviewer: string
  status: "pending" | "approved" | "rejected"
  notes?: string
  reviewed_at: datetime
}
```
