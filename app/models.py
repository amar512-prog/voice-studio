from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


Accent = Literal["us", "in", "neutral"]
SpeechContext = Literal[
    "outreach_conversational",
    "customer_support",
    "narration",
    "announcement",
    "character_dialogue",
    "dramatic_storytelling",
]
VoiceSourceType = Literal["elevenlabs_library", "voice_design", "cloned", "manual"]
ConsentStatus = Literal["not_required", "confirmed", "missing"]


class UserProfile(BaseModel):
    sub: str = Field(description="Authenticated subject id.")
    email: str = Field(description="User email or api-key marker.")
    name: str = Field(description="Display name.")
    picture: str = Field(default="", description="Optional avatar URL.")


class AuthState(BaseModel):
    user: UserProfile | None = Field(default=None, description="Current session user, or null when signed out.")


class LogoutResponse(BaseModel):
    ok: bool = Field(description="True when the session was cleared.")


class ContextOption(BaseModel):
    id: SpeechContext = Field(description="Speech context id accepted by TTS requests.")
    label: str = Field(description="UI label.")
    note: str = Field(description="Short delivery guidance.")


class AccentOption(BaseModel):
    id: Accent = Field(description="Accent id accepted by voice and TTS requests.")
    label: str = Field(description="UI label.")


class ConfigResponse(BaseModel):
    auth_mode: str = Field(description="Active login mode: google or development.")
    google_client_id: str = Field(description="Google OAuth client id for browser login.")
    password_enabled: bool = Field(description="Whether username/password login is configured.")
    model_id: str = Field(description="ElevenLabs model id used for generation.")
    default_target_seconds: int = Field(description="Default soft target duration.")
    default_wpm: int = Field(description="Default words-per-minute estimate.")
    max_duration_seconds: int = Field(description="Hard LinkedIn duration limit.")
    contexts: list[ContextOption] = Field(description="Available speech contexts.")
    accents: list[AccentOption] = Field(description="Available accent buckets.")


class CacheClearResponse(BaseModel):
    ok: bool = Field(description="True when cache clearing completed.")
    cleared: int = Field(description="Number of in-memory cache entries removed.")


class VoiceRecord(BaseModel):
    id: str = Field(description="Local persistent registry id.")
    display_name: str = Field(description="Human-readable voice name shown in the UI.")
    voice_id: str = Field(description="ElevenLabs voice id used for TTS calls.")
    source_type: VoiceSourceType = Field(default="manual", description="How this voice entered the registry.")
    accent: Accent = Field(default="neutral", description="App-level accent bucket used for filtering.")
    consent_status: ConsentStatus = Field(
        default="not_required",
        description="Consent state for cloned voices. Library/manual voices normally use not_required.",
    )
    source_audio_path: str | None = Field(default=None, description="Relative path to the source sample for cloned voices.")
    provider_metadata: dict = Field(default_factory=dict, description="Raw or normalized provider metadata.")
    created_at: datetime = Field(description="Record creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class VoiceCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, description="Name to show in the saved voice registry.")
    voice_id: str = Field(min_length=1, description="ElevenLabs voice id to save or update.")
    source_type: VoiceSourceType = Field(default="manual", description="Source classification for the saved voice.")
    accent: Accent = Field(default="neutral", description="Accent filter bucket for this voice.")
    consent_status: ConsentStatus = Field(default="not_required", description="Consent status for the source voice.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "display_name": "Founder voice",
                "voice_id": "21m00Tcm4TlvDq8ikWAM",
                "source_type": "manual",
                "accent": "us",
                "consent_status": "not_required",
            }
        }
    }


class ProviderVoiceOption(BaseModel):
    id: str = Field(description="Provider voice id. For shared voices this may be the public library id.")
    display_name: str = Field(description="Voice name from ElevenLabs.")
    accent: Accent = Field(description="Normalized app accent bucket.")
    language: str = Field(default="en", description="Normalized language code.")
    use_case: str = Field(description="Provider use-case label, typically conversational.")
    accent_label: str | None = Field(default=None, description="Display label for accent.")
    language_label: str | None = Field(default=None, description="Display label for language.")
    use_case_label: str | None = Field(default=None, description="Display label for use case.")
    category: str | None = Field(default=None, description="Provider category such as premade.")
    description: str | None = Field(default=None, description="Provider description shown in the picker.")
    descriptive: str | None = Field(default=None, description="Short style descriptor such as calm or casual.")
    preview_url: str | None = Field(default=None, description="Provider-hosted preview audio URL.")
    created_at_unix: int | None = Field(default=None, description="Provider creation timestamp when available.")
    usage_count: int | None = Field(default=None, description="Provider popularity metric when available.")
    gender: str | None = Field(default=None, description="Provider gender label when available.")
    age: str | None = Field(default=None, description="Provider age label when available.")
    public_owner_id: str | None = Field(
        default=None,
        description="Required owner id for shared library voices that must be copied into the workspace.",
    )
    saved: bool = Field(default=False, description="Whether this provider voice is already saved locally.")


class ProviderVoicePage(BaseModel):
    voices: list[ProviderVoiceOption] = Field(description="Current page of provider voice options.")
    page: int = Field(description="Zero-based page index.")
    page_size: int = Field(description="Requested page size after clamping.")
    has_more: bool = Field(description="Whether another page is available.")
    total_count: int | None = Field(default=None, description="Provider-reported total count when available.")
    sort: str = Field(description="Normalized sort id used for this page.")
    accent: str = Field(description="Normalized accent id used for this page.")


class ProviderVoiceSaveRequest(BaseModel):
    public_owner_id: str | None = Field(
        default=None,
        description="Owner id for shared/community voices. Omit for premade voices.",
    )
    name: str = Field(min_length=1, description="Name to save in the local registry.")
    accent: Accent = Field(default="neutral", description="Accent bucket to store with the saved voice.")

    model_config = {
        "json_schema_extra": {
            "example": {"public_owner_id": None, "name": "Chris - Charming, Down-to-Earth", "accent": "us"}
        }
    }


class ProviderVoiceByIdRequest(BaseModel):
    voice_id: str = Field(min_length=1, description="Raw ElevenLabs voice id to register.")

    model_config = {"json_schema_extra": {"example": {"voice_id": "21m00Tcm4TlvDq8ikWAM"}}}


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, description="Text to synthesize into one voice note.")
    voice_id: str = Field(min_length=1, description="ElevenLabs voice id to use.")
    voice_name: str | None = Field(default=None, description="Optional display name stored with the result.")
    accent: Accent = Field(default="neutral", description="Accent bucket recorded with the generated result.")
    speech_context: SpeechContext = Field(
        default="outreach_conversational",
        description="Delivery context that maps to ElevenLabs voice settings and optional v3 delivery tags.",
    )
    target_seconds: int = Field(default=55, ge=1, le=60, description="Soft target duration for yellow warnings.")
    wpm: int = Field(default=135, ge=60, le=240, description="Words-per-minute estimate used before generation.")
    export_m4a: bool = Field(default=False, description="Also export a LinkedIn-compatible mono AAC .m4a file.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "text": "Hey Priya, quick one. I noticed your team is hiring across outbound roles.",
                "voice_id": "21m00Tcm4TlvDq8ikWAM",
                "voice_name": "Founder voice",
                "accent": "us",
                "speech_context": "outreach_conversational",
                "target_seconds": 55,
                "wpm": 135,
                "export_m4a": True,
            }
        }
    }


class WarningState(BaseModel):
    level: Literal["yellow", "red"] = Field(description="Warning severity.")
    code: str = Field(description="Stable warning code.")
    message: str = Field(description="Human-readable warning message.")


class AudioResult(BaseModel):
    job_id: str = Field(description="Generation job id.")
    index: int | None = Field(default=None, description="1-based row index within the job.")
    status: Literal["completed", "failed"] = Field(description="Generation outcome for this row.")
    text: str = Field(description="Input text for this row.")
    voice_id: str = Field(description="ElevenLabs voice id used for this row.")
    voice_name: str | None = Field(default=None, description="Optional voice display name.")
    model_id: str | None = Field(default=None, description="ElevenLabs model id used.")
    speech_context: SpeechContext = Field(description="Speech context used for voice settings.")
    accent: Accent = Field(description="Accent bucket recorded with this row.")
    estimated_seconds: float = Field(description="Estimated duration from text and WPM.")
    target_seconds: int = Field(description="Soft target duration.")
    max_seconds: int = Field(description="Hard LinkedIn duration limit.")
    actual_seconds: float | None = Field(default=None, description="Measured audio duration after generation.")
    warning: WarningState | None = Field(default=None, description="Duration or generation warning, if any.")
    mp3_url: str | None = Field(default=None, description="Authenticated download URL for the MP3.")
    m4a_url: str | None = Field(default=None, description="Authenticated download URL for the optional M4A.")
    transcript_url: str | None = Field(default=None, description="Authenticated download URL for the transcript.")
    error: str | None = Field(default=None, description="Failure message when status is failed.")
    created_at: datetime = Field(description="Result timestamp.")


class BatchResult(BaseModel):
    batch_id: str = Field(description="Batch job id.")
    total_rows: int = Field(description="Rows parsed from the uploaded workbook.")
    completed_rows: int = Field(description="Rows that generated successfully.")
    failed_rows: int = Field(description="Rows that failed.")
    results: list[AudioResult] = Field(description="Per-row generation results.")
    workbook_url: str | None = Field(default=None, description="Authenticated download URL for the results workbook.")


class JobSummary(BaseModel):
    job_id: str = Field(description="Persistent job id.")
    kind: Literal["single", "batch"] = Field(description="Whether this job came from single or batch generation.")
    created_at: datetime = Field(description="Job creation timestamp.")
    total_rows: int = Field(description="Total rows in the job.")
    completed_rows: int = Field(description="Rows completed successfully.")
    failed_rows: int = Field(description="Rows that failed.")


class JobDetail(JobSummary):
    rows: list[AudioResult] = Field(description="Per-row generation results.")
    workbook_url: str | None = Field(default=None, description="Results workbook URL for batch jobs.")


class HealthResponse(BaseModel):
    status: str = Field(description="Service health status.")
    provider_configured: bool = Field(description="Whether ELEVENLABS_API_KEY is configured.")
    ffmpeg_available: bool = Field(description="Whether ffmpeg is available for duration/M4A work.")
