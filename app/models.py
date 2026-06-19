from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


Accent = Literal["us", "in", "neutral", "auto"]
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
ProviderCapability = Literal[
    "tts",
    "batch",
    "clone",
    "presets",
    "text_rules",
    "text_conversions",
    "voice_library",
]


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


class ProviderInfo(BaseModel):
    id: str = Field(description="Stable provider id used in provider-scoped API paths.")
    name: str = Field(description="Human-readable provider name.")
    configured: bool = Field(description="Whether the provider has the required server configuration.")
    capabilities: list[ProviderCapability] = Field(description="Provider features supported by this application.")


class ProvidersResponse(BaseModel):
    default_provider: str = Field(description="Provider id selected by default for new frontend sessions.")
    providers: list[ProviderInfo] = Field(description="Supported providers in preferred display order.")


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


class OmniVoiceToneSettings(BaseModel):
    """OmniVoice generation settings captured in a tone (maps to the Space payload)."""

    speed: float = Field(
        1.0,
        ge=0.5,
        le=1.5,
        multiple_of=0.05,
        description=(
            "Speech-rate multiplier from 0.5 to 1.5 in 0.05 increments. "
            "Use 1.0 for normal speed, below 1.0 for slower speech with more pause, "
            "or above 1.0 for faster speech. Ignored when duration is greater than 0."
        ),
    )
    duration: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Fixed output duration in seconds. A value greater than 0 overrides speed; "
            "use 0 or null to let speed control the audio duration."
        ),
    )
    num_step: int = Field(
        32,
        ge=4,
        le=64,
        description=(
            "Inference steps from 4 to 64. Higher values generally improve audio quality "
            "but take longer to generate."
        ),
    )
    guidance_scale: float = Field(
        2.0,
        ge=0,
        le=4,
        description=(
            "Context-guidance strength from 0 to 4. Higher values make the model follow "
            "the supplied voice design and generation context more strongly."
        ),
    )
    denoise: bool = Field(
        True,
        description="When true, apply denoising to the generated audio.",
    )
    preprocess_prompt: bool = Field(
        True,
        description=(
            "When true, remove silence and trim the reference audio, and append ending "
            "punctuation to the reference text when it is missing."
        ),
    )
    postprocess_output: bool = Field(
        True,
        description="When true, remove long silences from the generated audio.",
    )


class OmniVoiceContext(BaseModel):
    """A saved OmniVoice speech context: a named voice-design + generation settings."""

    id: str = Field(description="Stable speech-context id.")
    name: str = Field(description="Display name shown in the Generate context picker.")
    instruct: str = Field(description="Voice-design attributes, e.g. 'male, american accent, middle-aged'.")
    language: str | None = Field(default=None, description="Language code, or null to auto-detect.")
    settings: OmniVoiceToneSettings = Field(default_factory=OmniVoiceToneSettings)


class OmniVoiceContextRequest(BaseModel):
    """Create or modify an OmniVoice speech context."""

    id: str | None = Field(
        default=None,
        description="Existing speech-context id to update. Omit or use null to create a new context.",
    )
    name: str = Field(
        min_length=1,
        description=(
            "Human-readable context name associated with the voice, clone owner, or intended voice persona."
        ),
        examples=["Amar outreach voice"],
    )
    instruct: str = Field(
        description=(
            "Optional comma-separated voice-design attributes. Leave empty for a clone-only context. "
            "A non-empty value is required when using the context for voice design. Supported choices: "
            "Gender: male or female; "
            "Age: child, teenager, young adult, middle-aged, or elderly; "
            "Pitch: very low pitch, low pitch, moderate pitch, high pitch, or very high pitch; "
            "Style: whisper; "
            "English accent: american accent or indian accent."
        ),
        examples=["male, young adult, moderate pitch, american accent"],
    )
    language: str | None = Field(
        default=None,
        description="Language code such as `en`, or null to let OmniVoice auto-detect the language.",
        examples=["en"],
    )
    settings: OmniVoiceToneSettings = Field(
        default_factory=OmniVoiceToneSettings,
        description="OmniVoice generation-quality, timing, and audio-processing settings.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Amar outreach voice",
                "instruct": "male, young adult, moderate pitch, american accent",
                "language": "en",
                "settings": {
                    "speed": 1.0,
                    "duration": 0,
                    "num_step": 64,
                    "guidance_scale": 4.0,
                    "denoise": True,
                    "preprocess_prompt": True,
                    "postprocess_output": True,
                },
            }
        }
    }


class OmniVoiceContextPreviewRequest(BaseModel):
    """Preview a speech-context's design audio without saving (design-only, no sample)."""

    text: str = Field(min_length=1, description="Text to synthesize for the preview.")
    instruct: str = Field(
        description=(
            "Optional comma-separated voice-design attributes. Leave empty to let OmniVoice use "
            "its model defaults based on the supplied text and language."
        ),
        examples=["male, young adult, moderate pitch, american accent", ""],
    )
    language: str | None = Field(default=None, description="Language code, or null to auto-detect.")
    settings: OmniVoiceToneSettings = Field(default_factory=OmniVoiceToneSettings)


class OmniVoiceContextPreview(BaseModel):
    audio_b64: str = Field(description="Base64 WAV preview audio.")
    audio_format: str = Field(default="wav", description="Preview audio format.")
    duration: float | None = Field(default=None, description="Reported duration in seconds when available.")


class OmniVoiceTextRuleRequest(BaseModel):
    text: str = Field(min_length=1, description="Text to check before OmniVoice generation.")


class OmniVoiceTextRuleChange(BaseModel):
    rule: str = Field(description="Stable rule id that produced the suggestion.")
    original: str = Field(description="Original matched text.")
    replacement: str = Field(description="Suggested spoken-text replacement.")


class OmniVoiceTextRuleResponse(BaseModel):
    ready: bool = Field(description="True when the original text contains no blocking OmniVoice rule violations.")
    original_text: str = Field(description="Submitted text.")
    suggested_text: str = Field(description="Reviewable suggestion with recognized slash patterns rewritten.")
    changes: list[OmniVoiceTextRuleChange] = Field(description="Deterministic replacements proposed by the checker.")
    errors: list[str] = Field(description="Blocking rule messages. Empty when ready is true.")


TextConversionInputControl = Literal["text", "textarea"]
TextConversionWarningSeverity = Literal["info", "warning", "error"]


class OmniVoiceTextConversionInputField(BaseModel):
    id: str = Field(description="Stable input id accepted by the conversion endpoint.")
    label: str = Field(description="Human-readable input label.")
    control: TextConversionInputControl = Field(description="Frontend control type.")
    required: bool = Field(description="Whether this input is required before conversion.")
    placeholder: str = Field(default="", description="Example or placeholder text.")
    help: str = Field(default="", description="Short guidance shown near the input.")
    empty_value: str = Field(default="not provided", description="Prompt value used when the input is empty.")


class OmniVoiceTextConversionInfo(BaseModel):
    id: str = Field(description="Stable conversion id.")
    label: str = Field(description="Display label.")
    purpose: str = Field(description="What this conversion is for.")
    description: str = Field(description="Detailed operator guidance.")
    configured: bool = Field(description="Whether the server is configured to run this conversion.")
    model: str = Field(description="Backend model/provider label used for conversion.")
    default_max_tokens: int = Field(description="Default OpenRouter max_tokens value for this conversion.")
    input_fields: list[OmniVoiceTextConversionInputField] = Field(description="Inputs the frontend should collect.")
    output_rules: list[str] = Field(description="Rules the converted text should satisfy.")
    default_system_prompt: str = Field(description="Editable default system prompt.")
    default_user_prompt_template: str = Field(description="Editable default user prompt template with {{field_id}} tokens.")


class OmniVoiceTextConversionsResponse(BaseModel):
    conversions: list[OmniVoiceTextConversionInfo] = Field(description="Available OmniVoice text conversions.")


class OmniVoiceTextConversionPrompts(BaseModel):
    system_prompt: str = Field(min_length=1, description="System prompt used for the conversion.")
    user_prompt: str = Field(min_length=1, description="User prompt used for the conversion.")


class OmniVoiceTextConversionRequest(BaseModel):
    inputs: dict[str, str] = Field(description="Conversion inputs keyed by field id.")
    max_tokens: int | None = Field(
        default=None,
        ge=256,
        le=20000,
        description="Optional OpenRouter max_tokens override for this conversion run.",
    )
    prompts: OmniVoiceTextConversionPrompts | None = Field(
        default=None,
        description="Optional edited prompts. Omit to let the backend compose prompts from the selected conversion.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "inputs": {
                    "source_text": "Hi Anushua Roy, We're a NY-based PE/VC fund...",
                    "founder_name": "Anushua Roy",
                    "company_name": "Recro",
                    "verified_observation": "",
                    "pronunciation_notes": "",
                },
                "max_tokens": 5000,
            }
        }
    }


class OmniVoiceTextConversionWarning(BaseModel):
    severity: TextConversionWarningSeverity = Field(description="Warning severity.")
    rule: str = Field(description="Stable warning rule id.")
    message: str = Field(description="Human-readable warning.")


class OmniVoiceTextConversionResponse(BaseModel):
    conversion_id: str = Field(description="Conversion id that was run.")
    text: str = Field(description="Converted OmniVoice-ready text.")
    prompts: OmniVoiceTextConversionPrompts = Field(description="Prompts used for the conversion.")
    warnings: list[OmniVoiceTextConversionWarning] = Field(description="Conversion quality warnings.")
    rule_check: OmniVoiceTextRuleResponse = Field(description="Existing OmniVoice text-rule result for converted text.")
    ready_for_omnivoice: bool = Field(description="True when there are no conversion errors and no blocking text rules.")
    spoken_words: int = Field(description="Estimated spoken word count.")
    estimated_seconds: float = Field(description="Estimated duration in seconds.")


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, description="Text to synthesize into one voice note.")
    voice_id: str = Field(
        min_length=1,
        description=(
            "Voice id to synthesize with. ElevenLabs: provider voice id. OmniVoice: saved "
            "OmniVoice preset or cloned/sample voice id from the local registry."
        ),
    )
    voice_name: str | None = Field(default=None, description="Optional display name stored with the result.")
    accent: Accent = Field(default="neutral", description="Accent bucket recorded with the generated result.")
    speech_context: str = Field(
        default="outreach_conversational",
        description=(
            "ElevenLabs: optional built-in delivery context; defaults to "
            "`outreach_conversational`. OmniVoice: required saved speech-context id "
            "carrying the voice design and generation settings, for example "
            "`english_american` or `english_indian`."
        ),
    )
    target_seconds: int = Field(default=55, ge=1, le=60, description="Soft target duration for yellow warnings.")
    wpm: int = Field(default=135, ge=60, le=240, description="Words-per-minute estimate used before generation.")
    export_m4a: bool = Field(
        default=True,
        description="Defaults to true. Also export a LinkedIn-compatible mono AAC .m4a file.",
    )

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


class TtsApiRequest(BaseModel):
    """Public /tts request body shown in Swagger."""

    text: str = Field(min_length=1, description="Text to synthesize into one voice note.")
    voice_id: str = Field(
        min_length=1,
        description=(
            "Voice id to synthesize with. ElevenLabs: provider voice id. OmniVoice: saved "
            "OmniVoice preset or cloned/sample voice id from the local registry."
        ),
    )
    speech_context: str = Field(
        default="outreach_conversational",
        description=(
            "ElevenLabs: optional built-in delivery context; defaults to "
            "`outreach_conversational`. OmniVoice: required saved speech-context id "
            "carrying the voice design and generation settings, for example "
            "`english_american` or `english_indian`."
        ),
    )

    model_config = {
        "extra": "allow",
        "json_schema_extra": {
            "example": {
                "text": "Hey Priya, quick one. I noticed your team is hiring across outbound roles.",
                "voice_id": "21m00Tcm4TlvDq8ikWAM",
                "speech_context": "outreach_conversational",
            }
        },
    }

    def to_tts_request(self) -> TtsRequest:
        """Convert the public body into the full internal TTS request.

        Extra fields are intentionally accepted for frontend/backward
        compatibility but omitted from Swagger.
        """
        advanced_fields = {"voice_name", "accent", "target_seconds", "wpm", "export_m4a"}
        extras = {key: value for key, value in (self.model_extra or {}).items() if key in advanced_fields}
        return TtsRequest(
            text=self.text,
            voice_id=self.voice_id,
            speech_context=self.speech_context,
            **extras,
        )


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
    speech_context: str = Field(description="Speech context used for this row (delivery context id or OmniVoice context id).")
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


JobStatus = Literal["running", "completed", "partial", "failed", "interrupted"]


class JobSummary(BaseModel):
    job_id: str = Field(description="Persistent job id.")
    kind: Literal["single", "batch"] = Field(description="Whether this job came from single or batch generation.")
    status: JobStatus = Field(
        default="completed",
        description=(
            "Job lifecycle state. running=in progress; completed=all rows ok; "
            "partial=some rows failed; failed=all rows failed or a job-level error; "
            "interrupted=the server restarted mid-run."
        ),
    )
    created_at: datetime = Field(description="Job creation timestamp.")
    total_rows: int = Field(description="Total rows in the job.")
    completed_rows: int = Field(description="Rows completed successfully so far.")
    failed_rows: int = Field(description="Rows that failed so far.")


class JobDetail(JobSummary):
    rows: list[AudioResult] = Field(description="Per-row results available so far (grows while running).")
    workbook_url: str | None = Field(default=None, description="Results workbook URL, set once the batch finishes.")
    error: str | None = Field(default=None, description="Job-level error when status is failed or interrupted.")


class HealthResponse(BaseModel):
    status: str = Field(description="Service health status.")
    provider_configured: bool = Field(description="Whether ELEVENLABS_API_KEY is configured.")
    ffmpeg_available: bool = Field(description="Whether ffmpeg is available for duration/M4A work.")
