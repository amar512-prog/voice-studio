from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import threading
import zipfile
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Path as ApiPath, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.sessions import SessionMiddleware

from app.auth import current_user, validate_basic_credentials, verify_google_credential
from app.config import get_settings
from app.models import (
    AudioResult,
    CacheClearResponse,
    ConfigResponse,
    ContextOption,
    ElevenLabsContextSettingsRequest,
    ElevenLabsVoiceSettings,
    HealthResponse,
    JobDetail,
    JobStatus,
    JobSummary,
    OmniVoiceContext,
    OmniVoiceContextPreview,
    OmniVoiceContextPreviewRequest,
    OmniVoiceContextRequest,
    OmniVoiceTextConversionRequest,
    OmniVoiceTextConversionResponse,
    OmniVoiceTextConversionsResponse,
    OmniVoiceTextConversionPrompts,
    OmniVoiceWeTextProcessing,
    OmniVoiceTextRuleRequest,
    OmniVoiceTextRuleResponse,
    LogoutResponse,
    ProviderVoiceByIdRequest,
    ProvidersResponse,
    ProviderVoiceOption,
    ProviderVoicePage,
    ProviderVoiceSaveRequest,
    TtsApiRequest,
    TtsRequest,
    AuthState,
    VoiceCreateRequest,
    VoiceRecord,
    WarningState,
)
from app.services.audio_export import AudioExportService, ReferenceClipSelectionError
from app.services.duration import DurationService
from app.services.elevenlabs import ElevenLabsClient, ElevenLabsError
from app.services.elevenlabs_text_enhance import build_enhance_prompts
from app.services.omnivoice import OmniVoiceClient, OmniVoiceError
from app.services.omnivoice_text_conversions import (
    OpenRouterTextConversionClient,
    TextConversionError,
    WeTextEnglishProcessor,
    apply_wetext_processing,
    build_conversion_prompts,
    count_spoken_words,
    estimate_voice_note_seconds,
    get_text_conversion,
    list_text_conversions,
    validate_converted_text,
)
from app.services.omnivoice_text_rules import (
    OmniVoiceTextRuleError,
    check_omnivoice_text,
    require_omnivoice_text_ready,
)
from app.services.speech_context import CONTEXT_LABELS, CONTEXT_NOTES, VOICE_SETTINGS_BY_CONTEXT
from app.services.storage import StorageService, new_id, now_utc, safe_filename
from app.services.voice_filter import ProviderVoiceProfile, provider_voice_profile, provider_voice_rank
from app.services.voice_registry import VoiceRegistry
from app.services.workbook import WorkbookError, WorkbookService

settings = get_settings()

# Providers are fully separated on disk under data/{provider}/. ElevenLabs is
# the active UI/generation path today; OmniVoice is now registered/configurable
# so Phase 2/3 can bind routes and UI without another storage migration.
DEFAULT_PROVIDER = "omnivoice"
PROVIDERS = ("elevenlabs", "omnivoice")
ProviderPath = Annotated[
    str,
    ApiPath(
        description="Provider id: `omnivoice` or `elevenlabs`.",
        examples=["omnivoice", "elevenlabs"],
    ),
]
ElevenLabsProviderPath = Annotated[
    str,
    ApiPath(
        description="Provider id: `elevenlabs` only.",
        examples=["elevenlabs"],
    ),
]
OmniVoiceProviderPath = Annotated[
    str,
    ApiPath(
        description="Provider id: `omnivoice` only.",
        examples=["omnivoice"],
    ),
]
CloneProviderPath = Annotated[
    str,
    ApiPath(
        description=(
            "Provider id: use `omnivoice` for local reference-audio cloning, "
            "or `elevenlabs` for provider-hosted instant voice cloning."
        ),
        examples=["omnivoice", "elevenlabs"],
    ),
]
PROVIDER_CATALOG = {
    "omnivoice": {
        "name": "OmniVoice",
        "capabilities": ["tts", "batch", "clone", "presets", "text_rules", "text_conversions"],
    },
    "elevenlabs": {
        "name": "ElevenLabs",
        "capabilities": ["tts", "batch", "clone", "voice_library"],
    },
}
_storages = {provider: StorageService(settings, provider) for provider in PROVIDERS}
for _provider_storage in _storages.values():
    _provider_storage.ensure()
_registries = {provider: VoiceRegistry(_storages[provider]) for provider in PROVIDERS}
_clients = {
    "elevenlabs": ElevenLabsClient(settings),
    "omnivoice": OmniVoiceClient(settings),
}


def storage_for(provider: str) -> StorageService:
    return _storages[provider]


def registry_for(provider: str) -> VoiceRegistry:
    return _registries[provider]


def client_for(provider: str) -> ElevenLabsClient | OmniVoiceClient:
    return _clients[provider]


# Active-provider singletons used by the (still single-provider) routes today.
storage = _storages["elevenlabs"]
voice_registry = _registries["elevenlabs"]
elevenlabs = _clients["elevenlabs"]
duration_service = DurationService()
audio_export_service = AudioExportService()
workbooks = WorkbookService()
text_conversion_client = OpenRouterTextConversionClient(settings)
wetext_processor = WeTextEnglishProcessor()
PROVIDER_LIBRARY_ACCENTS = {"us", "in"}
ACCENT_LABELS = {"us": "American", "in": "Indian", "neutral": "Neutral", "auto": "Auto"}
LANGUAGE_LABELS = {"en": "English", "eng": "English", "english": "English"}
# Maps the UI sort tabs to ElevenLabs shared-voices `sort` values.
PROVIDER_SORT_MAP = {
    "trending": "trending",
    "latest": "created_date",
    "most_users": "cloned_by_count",
    "characters": "usage_character_count_1y",
}
# Maps our accent ids to the shared-voices `accent` filter values.
PROVIDER_ACCENT_PARAM = {"us": "american", "in": "indian"}
PROVIDER_PAGE_SIZE_DEFAULT = 20
PROVIDER_PAGE_SIZE_MAX = 100
# In-memory caches so paging/sorting the ElevenLabs voice library does not re-hit
# the provider. Cleared manually via DELETE /api/{provider}/voices/cache.
_shared_page_cache: dict[str, dict] = {}
_shared_voice_cache: dict[str, dict] = {}
_elevenlabs_context_settings_lock = threading.Lock()

# Default OmniVoice design contexts use only attributes accepted by upstream.
OMNIVOICE_DEFAULT_CONTEXTS = [
    {
        "id": "english_american",
        "name": "English - American",
        "instruct": "american accent",
        "language": None,
        "settings": {
            "speed": 1.0,
            "duration": None,
            "num_step": 32,
            "guidance_scale": 2.0,
            "denoise": True,
            "preprocess_prompt": True,
            "postprocess_output": True,
        },
    },
    {
        "id": "english_indian",
        "name": "English - Indian",
        "instruct": "indian accent",
        "language": None,
        "settings": {
            "speed": 1.0,
            "duration": None,
            "num_step": 32,
            "guidance_scale": 2.0,
            "denoise": True,
            "preprocess_prompt": True,
            "postprocess_output": True,
        },
    },
]
OMNIVOICE_PRESET_VOICES = [
    {
        "display_name": "English - American",
        "voice_id": "ov_design_english_american",
        "accent": "us",
        "context_id": "english_american",
    },
    {
        "display_name": "English - Indian",
        "voice_id": "ov_design_english_indian",
        "accent": "in",
        "context_id": "english_indian",
    },
]

logger = logging.getLogger("voice_message_studio")
# Bounds concurrent TTS+ffmpeg work so parallel requests/batches can't spawn an
# unbounded number of ffmpeg processes and exhaust the container.
_generation_semaphore = asyncio.Semaphore(settings.max_concurrent_generations)
# Strong refs to in-flight background batch tasks so they are not garbage-collected.
_background_tasks: set[asyncio.Task] = set()


def validate_provider(provider: str) -> str:
    if provider not in PROVIDERS:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Invalid argument `provider`: `{provider}`. "
                f"Expected one of: {', '.join(PROVIDERS)}."
            ),
        )
    return provider


def audio_export_error_detail(exc: Exception) -> str:
    base = "Could not read the uploaded sample. Use a clear mp3, wav, m4a, or webm recording."
    if isinstance(exc, subprocess.CalledProcessError):
        output = "\n".join(part for part in [exc.stderr, exc.stdout] if part)
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if lines:
            reason = " ".join(lines[-6:])
            if len(reason) > 700:
                reason = reason[-700:]
            return f"{base} Audio conversion failed: {reason}"
        return f"{base} Audio conversion failed with exit code {exc.returncode}."
    if isinstance(exc, OSError) and str(exc):
        return f"{base} Audio conversion failed: {exc}"
    return base


def provider_configured(provider: str) -> bool:
    provider = validate_provider(provider)
    if provider == "elevenlabs":
        return bool(settings.elevenlabs_api_key)
    if provider == "omnivoice":
        return bool(settings.omnivoice_base_url)
    return False

API_DESCRIPTION = """
**Voice Message Studio** turns text into reviewable LinkedIn-ready voice notes
using provider-scoped ElevenLabs or OmniVoice generation, with single and batch
(Excel) generation, a voice registry, and a job history with per-job ZIP export.

### Workflow

1. **Pick a provider + voice** — use provider-scoped routes such as
   `GET /api/{provider}/voices`, `POST /api/{provider}/voices/sync`, and
   `GET /api/{provider}/voices/options` (ElevenLabs only).
2. **Generate** — one clip (`POST /api/{provider}/tts`) or a batch from an
   `.xlsx` (`POST /api/{provider}/tts/batch`). Each run becomes a **job**.
3. **History** — list jobs (`GET /api/{provider}/jobs`), inspect rows
   (`GET /api/{provider}/jobs/{job_id}`), and download a ZIP from
   `GET /api/{provider}/jobs/{job_id}/download`.

### Authentication

- **Browser** — sign in with Google or username/password; the session cookie
  authorizes every call automatically.
- **Machine / API** — send an `X-API-Key: <key>` header. On this page click
  **Authorize**, paste the key once, then use **Try it out**.
"""

OPENAPI_TAGS = [
    {"name": "System", "description": "Public service configuration and provider discovery."},
    {"name": "Voices", "description": "Saved voice registry and ElevenLabs voice picker."},
    {"name": "Generate", "description": "Single and batch text-to-speech generation."},
    {"name": "History", "description": "Generation jobs: list, inspect, and download."},
    {"name": "Files", "description": "Authenticated file downloads from DATA_DIR."},
]


def _basic_health_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "auth_mode": settings.auth_mode,
        "providers": {provider: provider_configured(provider) for provider in PROVIDERS},
        "ffmpeg_available": duration_service.has_ffmpeg(),
    }


def _provider_catalog_payload() -> dict[str, object]:
    ordered_providers = (DEFAULT_PROVIDER, *(provider for provider in PROVIDERS if provider != DEFAULT_PROVIDER))
    return {
        "default_provider": DEFAULT_PROVIDER,
        "providers": [
            {
                "id": provider,
                "name": PROVIDER_CATALOG[provider]["name"],
                "configured": provider_configured(provider),
                "capabilities": PROVIDER_CATALOG[provider]["capabilities"],
            }
            for provider in ordered_providers
        ],
    }


def _reconcile_interrupted_jobs(storage_service: StorageService) -> None:
    """Mark jobs left 'running' by a previous process as interrupted.

    Safe because this single-worker process starts with zero in-flight tasks, so
    any persisted 'running' job cannot still be alive. NOTE: this assumption breaks
    with multiple workers/processes — switch to heartbeat-based reaping if you scale.
    """
    for job_id in storage_service.list_job_ids():
        manifest = storage_service.read_job_manifest(job_id)
        if not manifest or manifest.get("status") != "running":
            continue
        manifest["status"] = "interrupted"
        manifest["error"] = "Generation was interrupted because the server restarted. Re-run this batch."
        completed = manifest.get("completed_rows", 0)
        total = manifest.get("total_rows", 0)
        manifest["failed_rows"] = max(manifest.get("failed_rows", 0), total - completed)
        storage_service.save_job_manifest(job_id, manifest)
        logger.warning("Marked interrupted job %s for provider %s on startup", job_id, storage_service.provider)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    for storage_service in _storages.values():
        storage_service.ensure()
        _reconcile_interrupted_jobs(storage_service)
    # Seed OmniVoice speech contexts once at startup (avoids a first-request race).
    if "omnivoice" in PROVIDERS:
        _load_omnivoice_contexts()
        omnivoice_store = storage_for("omnivoice")
        preset_marker = omnivoice_store.root / "presets-v1.json"
        if not preset_marker.exists():
            _sync_omnivoice_presets(registry_for("omnivoice"))
            omnivoice_store.write_json(preset_marker, {"seeded": True})
    yield


app = FastAPI(
    title="Voice Message Studio",
    version="1.0.0",
    description=API_DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters={"defaultModelsExpandDepth": 0},
    lifespan=lifespan,
)
app.state.settings = settings
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="voice_message_studio_session",
    same_site="lax",
    https_only=settings.session_secure,
    max_age=60 * 60 * 12,
)


class GoogleLogin(BaseModel):
    credential: str = Field(
        min_length=1,
        description="Google Identity Services credential JWT returned by the browser sign-in button.",
    )

    model_config = {"json_schema_extra": {"example": {"credential": "google-credential-jwt"}}}


class PasswordLogin(BaseModel):
    username: str = Field(..., description="The configured AUTH_USERNAME.")
    password: str = Field(..., description="The configured AUTH_PASSWORD.")

    model_config = {"json_schema_extra": {"example": {"username": "admin", "password": "your-password"}}}



@app.get(
    "/api/{provider}/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Service health",
    response_description="Provider and ffmpeg readiness.",
    include_in_schema=False,
)
def health(provider: ProviderPath) -> HealthResponse:
    """Report whether the active provider is configured and ffmpeg is available."""
    provider = validate_provider(provider)
    return HealthResponse(
        status="ok",
        provider_configured=provider_configured(provider),
        ffmpeg_available=duration_service.has_ffmpeg(),
    )


@app.get(
    "/api/health",
    tags=["System"],
    summary="Basic app health",
    response_description="Simple container-safe health check.",
    include_in_schema=False,
)
def api_health() -> dict[str, object]:
    """Return a lightweight unauthenticated health payload for Docker/nginx checks."""
    return _basic_health_payload()


@app.get(
    "/api/providers",
    response_model=ProvidersResponse,
    tags=["System"],
    summary="List supported providers",
    response_description="Default provider plus configuration and capability metadata for every provider.",
)
def list_providers(_user: dict = Depends(current_user)) -> dict[str, object]:
    """Return the provider catalog used for API and frontend discovery."""
    return _provider_catalog_payload()


_elevenlabs_context_settings_cache: tuple[int, dict[str, dict[str, float]]] | None = None


def _read_elevenlabs_context_settings() -> dict[str, dict[str, float]]:
    """Load saved per-context ElevenLabs settings, cached until the file changes on disk."""
    global _elevenlabs_context_settings_cache
    path = storage_for("elevenlabs").speech_contexts_path
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return {}
    cached = _elevenlabs_context_settings_cache
    if cached is not None and cached[0] == mtime_ns:
        return dict(cached[1])
    try:
        raw_settings = storage_for("elevenlabs").read_json(path, {})
    except json.JSONDecodeError:
        logger.warning("Ignoring malformed ElevenLabs speech-context settings file at %s", path)
        return {}
    if not isinstance(raw_settings, dict):
        return {}
    validated: dict[str, dict[str, float]] = {}
    for context_id, voice_settings in raw_settings.items():
        if context_id not in CONTEXT_LABELS or not isinstance(voice_settings, dict):
            continue
        try:
            validated[context_id] = ElevenLabsVoiceSettings.model_validate(voice_settings).model_dump()
        except ValidationError:
            continue
    _elevenlabs_context_settings_cache = (mtime_ns, validated)
    return dict(validated)


def _elevenlabs_context_voice_settings(context_id: str) -> dict[str, float]:
    fallback_id = context_id if context_id in VOICE_SETTINGS_BY_CONTEXT else "outreach_conversational"
    saved = _read_elevenlabs_context_settings().get(fallback_id)
    return dict(saved or VOICE_SETTINGS_BY_CONTEXT[fallback_id])


@app.get(
    "/api/config",
    response_model=ConfigResponse,
    tags=["System"],
    summary="Public UI configuration",
    response_description="Frontend-safe runtime configuration.",
    include_in_schema=False,
)
def api_config() -> dict:
    """
    Return unauthenticated configuration used by the React UI and Swagger users.

    This does not include secrets. Use it to discover active auth mode, duration
    defaults, speech-context ids, and supported accent buckets.
    """
    saved_context_settings = _read_elevenlabs_context_settings()
    return {
        "auth_mode": settings.auth_mode,
        "google_client_id": settings.google_client_id,
        "password_enabled": settings.password_enabled,
        "model_id": settings.elevenlabs_model_id,
        "default_target_seconds": settings.default_target_seconds,
        "default_wpm": settings.default_wpm,
        "max_duration_seconds": settings.max_duration_seconds,
        "openrouter_configured": text_conversion_client.configured,
        "contexts": [
            {
                "id": context,
                "label": CONTEXT_LABELS[context],
                "note": CONTEXT_NOTES[context],
                "voice_settings": dict(
                    saved_context_settings.get(context) or VOICE_SETTINGS_BY_CONTEXT[context]
                ),
            }
            for context in CONTEXT_LABELS
        ],
        "accents": [
            {"id": "us", "label": "American"},
            {"id": "in", "label": "Indian"},
            {"id": "neutral", "label": "Neutral"},
        ],
    }


@app.get(
    "/api/auth/me",
    response_model=AuthState,
    tags=["Auth"],
    summary="Get current session user",
    response_description="Current browser session user, or null when signed out.",
    include_in_schema=False,
)
def auth_me(request: Request) -> dict:
    """Read the session cookie and return the signed-in user, if any."""
    return {"user": request.session.get("user")}


@app.post(
    "/api/auth/google",
    response_model=AuthState,
    tags=["Auth"],
    summary="Login with Google credential",
    response_description="Authenticated Google session user.",
    include_in_schema=False,
)
def auth_google(payload: GoogleLogin, request: Request) -> dict:
    """
    Exchange a Google Identity Services credential for an app session.

    Only works when `AUTH_MODE=google`. In Swagger, prefer `X-API-Key`
    authorization for machine testing because this endpoint requires a real
    browser-issued Google credential.
    """
    if settings.auth_mode != "google":
        raise HTTPException(status_code=404, detail="Google login is not enabled")
    user = verify_google_credential(payload.credential, settings)
    request.session.clear()
    request.session["user"] = user
    return {"user": user}


@app.post(
    "/api/auth/password",
    response_model=AuthState,
    tags=["Auth"],
    summary="Login with configured username/password",
    response_description="Authenticated password-session user.",
    include_in_schema=False,
)
def auth_password(payload: PasswordLogin, request: Request) -> dict:
    """
    Create a browser session using `AUTH_USERNAME` and `AUTH_PASSWORD`.

    This works alongside Google/development mode only when both environment
    variables are configured. It is useful for local Swagger testing without
    Google OAuth.
    """
    if not settings.password_enabled:
        raise HTTPException(status_code=404, detail="Password login is not enabled")
    if not validate_basic_credentials(payload.username, payload.password, settings):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    user = {
        "sub": f"password:{payload.username}",
        "email": payload.username,
        "name": payload.username,
        "picture": "",
    }
    request.session.clear()
    request.session["user"] = user
    return {"user": user}


@app.post(
    "/api/auth/development",
    response_model=AuthState,
    tags=["Auth"],
    summary="Login as local development user",
    response_description="Authenticated local-development session user.",
    include_in_schema=False,
)
def auth_development(request: Request) -> dict:
    """
    Create a local test session.

    Only works when `AUTH_MODE=development`. Production Google-mode containers
    return 404 for this route.
    """
    if settings.auth_mode != "development":
        raise HTTPException(status_code=404, detail="Development login is disabled")
    user = {
        "sub": "local-development-user",
        "email": "developer@localhost",
        "name": "Local Developer",
        "picture": "",
    }
    request.session.clear()
    request.session["user"] = user
    return {"user": user}


@app.post(
    "/api/auth/logout",
    response_model=LogoutResponse,
    tags=["Auth"],
    summary="Logout current browser session",
    response_description="Logout confirmation.",
    include_in_schema=False,
)
def auth_logout(request: Request) -> dict[str, bool]:
    """Clear the session cookie. API-key authentication is stateless and is not affected."""
    request.session.clear()
    return {"ok": True}


@app.get(
    "/api/{provider}/voices",
    response_model=list[VoiceRecord],
    tags=["Voices"],
    summary="List saved voices",
    response_description="All registry voices that pass the local eligibility filter.",
)
def list_voices(
    provider: ProviderPath,
    _user: dict = Depends(current_user),
) -> list[VoiceRecord]:
    """
    Return the local persistent voice registry.

    This is the source used by the Generate page voice dropdown. Library voices
    are filtered to the supported English conversational accent buckets; manual
    and cloned voices are returned as long as their stored accent is supported.
    """
    provider = validate_provider(provider)
    return registry_for(provider).list()


@app.post(
    "/api/{provider}/voices",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Add/update a voice by id",
    response_description="Saved or updated voice registry record.",
    include_in_schema=False,
)
def add_voice(
    provider: ElevenLabsProviderPath,
    request: VoiceCreateRequest,
    _user: dict = Depends(current_user),
) -> VoiceRecord:
    """
    Save a known ElevenLabs voice id into the local registry.

    If `voice_id` already exists locally, the record is updated in place. This
    endpoint does not validate that the provider id can synthesize audio; use it
    when you already know the id is valid or want to test a provider id directly.
    """
    provider = validate_provider(provider)
    return registry_for(provider).upsert(request)


@app.delete(
    "/api/{provider}/voices/cache",
    response_model=CacheClearResponse,
    tags=["Voices"],
    summary="Clear the voice-library cache",
    response_description="Count of in-memory voice-library cache entries removed.",
    include_in_schema=False,
)
def clear_provider_voice_cache(provider: ElevenLabsProviderPath, _user: dict = Depends(current_user)) -> dict:
    """
    Clear cached shared voice-library pages and cached shared voice records.

    This static route must be registered before `/voices/{record_id}` so FastAPI
    does not interpret `cache` as a voice record id.
    """
    provider = validate_provider(provider)
    if provider != "elevenlabs":
        raise HTTPException(status_code=404, detail="Voice-library caching is available only for ElevenLabs.")
    cleared = len(_shared_page_cache) + len(_shared_voice_cache)
    _shared_page_cache.clear()
    _shared_voice_cache.clear()
    return {"ok": True, "cleared": cleared}


@app.delete(
    "/api/{provider}/voices/{record_id}",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Delete a saved voice",
    response_description="The removed voice record.",
)
def delete_voice(
    provider: ProviderPath,
    record_id: Annotated[
        str,
        ApiPath(
            description=(
                "Voice record `id` returned by `GET /api/{provider}/voices`. "
                "Use the `id` field from that response, not the provider `voice_id`."
            ),
        ),
    ],
    _user: dict = Depends(current_user),
) -> VoiceRecord:
    """
    Remove one voice from the local registry.

    This only removes the app's saved reference. It does not delete the voice
    from ElevenLabs or remove generated files that used this voice.
    """
    provider = validate_provider(provider)
    removed = registry_for(provider).delete(record_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="Voice record not found.")
    return removed


@app.get(
    "/api/{provider}/voices/{record_id}/preview",
    tags=["Voices"],
    summary="Redirect to a voice preview clip",
    response_class=RedirectResponse,
    include_in_schema=False,
    responses={
        307: {"description": "Redirect to provider-hosted preview audio."},
        404: {"description": "Voice not found or no preview is available."},
    },
)
async def voice_preview(
    provider: ProviderPath,
    record_id: Annotated[str, ApiPath(description="Local VoiceRecord.id to preview.")],
    _user: dict = Depends(current_user),
) -> RedirectResponse:
    """
    Redirect to the provider preview URL for a saved voice.

    The endpoint first checks cached provider metadata. If no preview is stored,
    it makes a best-effort ElevenLabs lookup by `voice_id`.
    """
    provider = validate_provider(provider)
    registry = registry_for(provider)
    record = next((item for item in registry.list() if item.id == record_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="Voice record not found.")

    metadata = record.provider_metadata or {}
    preview_url = metadata.get("preview_url") or (metadata.get("labels") or {}).get("preview_url")
    if not preview_url and provider == "elevenlabs":
        try:
            fetched = await elevenlabs.get_voice(record.voice_id)
            preview_url = fetched.get("preview_url")
        except ElevenLabsError:
            preview_url = None
    if not preview_url:
        raise HTTPException(status_code=404, detail="No preview available for this voice.")
    return RedirectResponse(url=preview_url)


async def _eligible_provider_voices() -> list[tuple[tuple[int, str], dict, ProviderVoiceProfile]]:
    try:
        provider_voices = await elevenlabs.list_voices()
    except ElevenLabsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    eligible_voices = []
    for voice in provider_voices:
        profile = provider_voice_profile(voice)
        if profile is None:
            continue
        eligible_voices.append((provider_voice_rank(voice, profile), voice, profile))

    eligible_voices.sort(key=lambda item: item[0])
    return eligible_voices


def _save_provider_voice(registry: VoiceRegistry, voice: dict, profile: ProviderVoiceProfile) -> VoiceRecord:
    voice_id = voice.get("voice_id") or voice.get("id")
    name = voice.get("name") or voice_id
    if not voice_id:
        raise HTTPException(status_code=502, detail="ElevenLabs voice did not include a voice_id.")
    return registry.upsert(
        VoiceCreateRequest(
            display_name=name,
            voice_id=voice_id,
            source_type="elevenlabs_library",
            accent=profile.accent,
            consent_status="not_required",
        ),
        provider_metadata={
            **voice,
            "voice_message_studio_profile": {
                "language": profile.language,
                "accent": profile.accent,
                "use_case": profile.use_case,
            },
        },
    )


def _saved_shared_ids(registry: VoiceRegistry) -> set[str]:
    """Workspace voice ids plus the original shared voice ids they were added from."""
    saved: set[str] = set()
    for record in registry.list():
        saved.add(record.voice_id)
        shared_id = (record.provider_metadata or {}).get("shared_voice_id")
        if shared_id:
            saved.add(str(shared_id))
    return saved


def _shared_voice_option(voice: dict, accent_id: str, saved_ids: set[str]) -> ProviderVoiceOption | None:
    voice_id = voice.get("voice_id") or voice.get("id")
    if not voice_id:
        return None
    use_case = voice.get("use_case") or "conversational"
    return ProviderVoiceOption(
        id=voice_id,
        display_name=voice.get("name") or voice_id,
        accent=accent_id,
        language="en",
        use_case=use_case,
        accent_label=ACCENT_LABELS.get(accent_id, accent_id.title()),
        language_label="English",
        use_case_label=_title_label(use_case),
        category=voice.get("category"),
        description=voice.get("description"),
        descriptive=voice.get("descriptive"),
        preview_url=voice.get("preview_url"),
        created_at_unix=_int_or_none(voice.get("date_unix")),
        usage_count=_first_int(voice.get("cloned_by_count"), voice.get("usage_character_count_1y")),
        gender=voice.get("gender"),
        age=voice.get("age"),
        public_owner_id=voice.get("public_owner_id"),
        saved=voice_id in saved_ids,
    )


def _premade_voice_option(voice: dict, accent_id: str, saved_ids: set[str]) -> ProviderVoiceOption | None:
    voice_id = voice.get("voice_id") or voice.get("id")
    if not voice_id:
        return None
    labels = voice.get("labels") or {}
    use_case = labels.get("use_case") or "conversational"
    return ProviderVoiceOption(
        id=voice_id,
        display_name=voice.get("name") or voice_id,
        accent=accent_id,
        language="en",
        use_case=use_case,
        accent_label=ACCENT_LABELS.get(accent_id, accent_id.title()),
        language_label="English",
        use_case_label=_title_label(use_case),
        category=voice.get("category"),
        description=voice.get("description") or labels.get("description"),
        descriptive=labels.get("descriptive"),
        preview_url=voice.get("preview_url"),
        created_at_unix=_int_or_none(voice.get("created_at_unix")),
        gender=labels.get("gender"),
        age=labels.get("age"),
        public_owner_id=None,
        saved=voice_id in saved_ids,
    )


def _sort_premade_options(options: list[ProviderVoiceOption], sort_id: str) -> None:
    # Premade voices have no trending/usage metrics; "latest" uses created_at_unix,
    # every other mode falls back to alphabetical by name.
    if sort_id == "latest":
        options.sort(key=lambda option: option.created_at_unix or 0, reverse=True)
    else:
        options.sort(key=lambda option: option.display_name.lower())


async def _premade_voice_page(
    registry: VoiceRegistry, accent_id: str, sort_id: str, page: int, page_size: int
) -> ProviderVoicePage:
    try:
        workspace = await elevenlabs.list_voices()
    except ElevenLabsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    saved_ids = _saved_shared_ids(registry)
    options: list[ProviderVoiceOption] = []
    for voice in workspace:
        if voice.get("category") != "premade":
            continue
        labels = voice.get("labels") or {}
        if _map_accent(labels.get("accent")) != accent_id:
            continue
        option = _premade_voice_option(voice, accent_id, saved_ids)
        # Already-saved premade voices are hidden from the picker (they live in the
        # registry), so exclude them here too — keeps the count and pagination honest.
        if option is not None and not option.saved:
            options.append(option)

    _sort_premade_options(options, sort_id)
    total = len(options)
    start = page * page_size
    return ProviderVoicePage(
        voices=options[start : start + page_size],
        page=page,
        page_size=page_size,
        has_more=start + page_size < total,
        total_count=total,
        sort=sort_id,
        accent=accent_id,
    )


@app.get(
    "/api/{provider}/voices/options",
    response_model=ProviderVoicePage,
    tags=["Voices"],
    summary="Browse ElevenLabs voices",
    response_description="One normalized page of provider voice options.",
    include_in_schema=False,
)
async def list_provider_voice_options(
    provider: ElevenLabsProviderPath,
    page: Annotated[int, Query(ge=0, description="Zero-based page index.")] = 0,
    page_size: Annotated[
        int,
        Query(
            ge=1,
            le=PROVIDER_PAGE_SIZE_MAX,
            description="Voices per page. Values above the maximum are clamped.",
        ),
    ] = PROVIDER_PAGE_SIZE_DEFAULT,
    sort: Annotated[
        str,
        Query(
            description="Sort tab id: trending, latest, most_users, or characters.",
            examples=["trending"],
        ),
    ] = "trending",
    accent: Annotated[
        str,
        Query(description="Accent filter id. Supported provider filters are us and in.", examples=["us"]),
    ] = "us",
    premade_only: Annotated[
        bool,
        Query(
            description=(
                "When true, browse workspace premade voices. When false, call the ElevenLabs shared "
                "voice library with language/accent/conversational filters."
            )
        ),
    ] = True,
    _user: dict = Depends(current_user),
) -> ProviderVoicePage:
    """
    Browse normalized ElevenLabs voice options for the voice picker.

    The default `premade_only=true` path reads workspace premade voices and does
    not copy anything into the registry. Set `premade_only=false` to query the
    shared voice library using the same English/conversational/American-or-Indian
    filters and the requested sort tab.
    """
    provider = validate_provider(provider)
    if provider != "elevenlabs":
        raise HTTPException(status_code=404, detail="Voice-library browsing is available only for ElevenLabs.")
    page = max(page, 0)
    page_size = max(1, min(page_size, PROVIDER_PAGE_SIZE_MAX))
    accent_id = accent if accent in PROVIDER_ACCENT_PARAM else "us"
    sort_id = sort if sort in PROVIDER_SORT_MAP else "trending"
    registry = registry_for(provider)

    if premade_only:
        return await _premade_voice_page(registry, accent_id, sort_id, page, page_size)

    cache_key = f"{accent_id}:{sort_id}:{page}:{page_size}"
    data = _shared_page_cache.get(cache_key)
    if data is None:
        try:
            data = await elevenlabs.list_shared_voices(
                page=page,
                page_size=page_size,
                sort=PROVIDER_SORT_MAP[sort_id],
                language="en",
                accent=PROVIDER_ACCENT_PARAM[accent_id],
                use_cases=["conversational"],
            )
        except ElevenLabsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _shared_page_cache[cache_key] = data
        for voice in data.get("voices", []):
            voice_id = voice.get("voice_id") or voice.get("id")
            if voice_id:
                _shared_voice_cache[voice_id] = voice

    saved_ids = _saved_shared_ids(registry)
    options: list[ProviderVoiceOption] = []
    for voice in data.get("voices", []):
        option = _shared_voice_option(voice, accent_id, saved_ids)
        if option is not None:
            options.append(option)

    return ProviderVoicePage(
        voices=options,
        page=page,
        page_size=page_size,
        has_more=bool(data.get("has_more")),
        total_count=_int_or_none(data.get("total_count")),
        sort=sort_id,
        accent=accent_id,
    )


def _map_accent(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"american", "us", "usa", "united states", "general american"}:
        return "us"
    if normalized in {"indian", "in", "india", "indian english"}:
        return "in"
    if normalized in {"neutral", "standard", "general", "international"}:
        return "neutral"
    return None


@app.post(
    "/api/{provider}/voices/by-id",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Add a voice by raw id",
    response_description="Saved registry record for the supplied provider id.",
    include_in_schema=False,
)
async def add_provider_voice_by_id(
    provider: ElevenLabsProviderPath,
    request: ProviderVoiceByIdRequest,
    _user: dict = Depends(current_user),
) -> VoiceRecord:
    """
    Register an arbitrary ElevenLabs voice id.

    The app tries to fetch provider metadata for a friendly name, preview URL,
    and accent. If ElevenLabs does not expose that metadata, the id is still
    saved as a manual voice so it can be used for TTS.
    """
    provider = validate_provider(provider)
    if provider != "elevenlabs":
        raise HTTPException(status_code=404, detail="Raw voice-id registration is available only for ElevenLabs.")
    registry = registry_for(provider)
    voice_id = request.voice_id.strip()
    if not voice_id:
        raise HTTPException(status_code=400, detail="A voice id is required.")

    existing = next(
        (
            record
            for record in registry.list()
            if record.voice_id == voice_id
            or (record.provider_metadata or {}).get("shared_voice_id") == voice_id
        ),
        None,
    )
    if existing is not None:
        return existing

    # Best-effort lookup for a friendly name/accent; never block on it. Library and
    # community voices are not in the workspace (/voices/{id} returns 400/404), but
    # they are still usable for TTS by id, so we register whatever id was provided.
    name: str | None = None
    accent_id = "neutral"
    preview_url: str | None = None

    cached = _shared_voice_cache.get(voice_id)
    if cached:
        name = cached.get("name")
        preview_url = cached.get("preview_url")
        accent_id = _map_accent(cached.get("accent")) or accent_id
    else:
        try:
            fetched = await elevenlabs.get_voice(voice_id)
        except ElevenLabsError:
            fetched = None
        if fetched:
            _shared_voice_cache[voice_id] = fetched
            name = fetched.get("name")
            preview_url = fetched.get("preview_url")
            labels = fetched.get("labels") or {}
            accent_id = _map_accent(labels.get("accent")) or accent_id

    return registry.upsert(
        VoiceCreateRequest(
            display_name=name or voice_id,
            voice_id=voice_id,
            source_type="manual",
            accent=accent_id,
            consent_status="not_required",
        ),
        provider_metadata={
            "added_by_voice_id": True,
            "preview_url": preview_url,
        },
    )


@app.post(
    "/api/{provider}/voice-options/{voice_id}/save",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Save a picked voice",
    response_description="Saved registry record for the selected provider voice.",
    include_in_schema=False,
)
async def save_provider_voice_option(
    provider: ElevenLabsProviderPath,
    voice_id: Annotated[str, ApiPath(description="Provider voice id selected from the voice picker.")],
    request: ProviderVoiceSaveRequest,
    _user: dict = Depends(current_user),
) -> VoiceRecord:
    """
    Save a voice selected from the ElevenLabs picker.

    Premade voices are saved directly by id. Shared/community voices require
    `public_owner_id`; those are first copied into the ElevenLabs workspace,
    then the newly returned workspace voice id is saved locally.
    """
    provider = validate_provider(provider)
    if provider != "elevenlabs":
        raise HTTPException(status_code=404, detail="Voice-library save is available only for ElevenLabs.")
    registry = registry_for(provider)
    accent_id = request.accent if request.accent in PROVIDER_LIBRARY_ACCENTS else "neutral"
    existing = next(
        (
            record
            for record in registry.list()
            if record.voice_id == voice_id
            or (record.provider_metadata or {}).get("shared_voice_id") == voice_id
        ),
        None,
    )
    if existing is not None:
        return existing

    # Premade/default voices have no public owner and are usable directly by id —
    # register them as-is. Shared library voices must first be copied into the
    # workspace via the owner id, which yields a new usable voice id.
    if not request.public_owner_id:
        return registry.upsert(
            VoiceCreateRequest(
                display_name=request.name,
                voice_id=voice_id,
                source_type="manual",
                accent=accent_id,
                consent_status="not_required",
            ),
            provider_metadata={
                "premade": True,
                "language": "en",
                "accent": accent_id,
            },
        )

    try:
        added = await elevenlabs.add_shared_voice(request.public_owner_id, voice_id, request.name)
    except ElevenLabsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    new_voice_id = added.get("voice_id")
    if not new_voice_id:
        raise HTTPException(status_code=502, detail="ElevenLabs did not return a voice_id.")

    return registry.upsert(
        VoiceCreateRequest(
            display_name=request.name,
            voice_id=new_voice_id,
            source_type="elevenlabs_library",
            accent=accent_id,
            consent_status="not_required",
        ),
        provider_metadata={
            "shared_voice_id": voice_id,
            "public_owner_id": request.public_owner_id,
            "language": "en",
            "accent": accent_id,
            "use_case": "conversational",
            "voice_message_studio_profile": {
                "language": "en",
                "accent": accent_id,
                "use_case": "conversational",
            },
        },
    )


@app.post(
    "/api/{provider}/voices/sync",
    response_model=list[VoiceRecord],
    tags=["Voices"],
    summary="Sync eligible workspace voices",
    response_description="Registry records created or updated from eligible workspace voices.",
)
async def sync_provider_voices(provider: ProviderPath, _user: dict = Depends(current_user)) -> list[VoiceRecord]:
    """
    Pull eligible voices from the ElevenLabs workspace into the local registry.

    Eligibility is intentionally narrow: English, conversational, and currently
    American or Indian accent only. Existing records are updated by `voice_id`.
    """
    provider = validate_provider(provider)
    registry = registry_for(provider)
    if provider == "omnivoice":
        return _sync_omnivoice_presets(registry)

    synced: list[VoiceRecord] = []
    for _rank, voice, profile in await _eligible_provider_voices():
        if profile.accent not in PROVIDER_LIBRARY_ACCENTS:
            continue
        synced.append(_save_provider_voice(registry, voice, profile))
    return synced


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(*values: object) -> int | None:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _title_label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


# ---- OmniVoice speech contexts (persisted, editable voice-design + settings) ----


@app.put(
    "/api/{provider}/speech-contexts/{context_id}/voice-settings",
    response_model=ContextOption,
    tags=["Speech Contexts"],
    summary="Save ElevenLabs speech-context voice settings",
    response_description="Updated speech context with its persisted ElevenLabs voice settings.",
)
def save_elevenlabs_context_settings(
    provider: ElevenLabsProviderPath,
    context_id: Annotated[
        str,
        ApiPath(
            description="Built-in ElevenLabs speech-context id returned by `/api/config`.",
            examples=["founder_outreach_human"],
        ),
    ],
    request: ElevenLabsContextSettingsRequest,
    _user: dict = Depends(current_user),
) -> ContextOption:
    """
    Partially update the persisted Generate and Batch defaults for one ElevenLabs context.

    The existing `voice_settings` wrapper and its stability, similarity_boost,
    style, and speed fields are preserved for backward compatibility. Clients
    may send one, several, all, or none of those fields. Null and omitted values
    leave the current effective value unchanged. The response always contains
    the complete effective settings. Model support for individual controls can
    vary; Eleven v3 expression primarily comes from prompting and audio tags.
    """
    provider = validate_provider(provider)
    if provider != "elevenlabs":
        raise HTTPException(status_code=404, detail="Saved voice settings are available only for ElevenLabs.")
    if context_id not in CONTEXT_LABELS:
        raise HTTPException(status_code=404, detail="ElevenLabs speech context not found.")

    provider_storage = storage_for(provider)
    with _elevenlabs_context_settings_lock:
        saved_settings = _read_elevenlabs_context_settings()
        effective_settings = dict(saved_settings.get(context_id) or VOICE_SETTINGS_BY_CONTEXT[context_id])
        if request.voice_settings is not None:
            effective_settings.update(request.voice_settings.model_dump(exclude_none=True))
        complete_settings = ElevenLabsVoiceSettings.model_validate(effective_settings)
        saved_settings[context_id] = complete_settings.model_dump()
        provider_storage.write_json(provider_storage.speech_contexts_path, saved_settings)

    return ContextOption(
        id=context_id,
        label=CONTEXT_LABELS[context_id],
        note=CONTEXT_NOTES[context_id],
        voice_settings=complete_settings,
    )


def _require_omnivoice(provider: str) -> str:
    provider = validate_provider(provider)
    if provider != "omnivoice":
        raise HTTPException(status_code=404, detail="Speech contexts are available only for OmniVoice.")
    return provider


def _load_omnivoice_contexts() -> list[dict]:
    """Read persisted OmniVoice contexts, seeding defaults the first time."""
    store = storage_for("omnivoice")
    contexts = store.read_json(store.speech_contexts_path, None)
    if not isinstance(contexts, list) or not contexts:
        contexts = [dict(ctx) for ctx in OMNIVOICE_DEFAULT_CONTEXTS]
        store.write_json(store.speech_contexts_path, contexts)
        return contexts

    changed = False
    old_conversational = next(
        (
            context
            for context in contexts
            if context.get("id") == "conversational"
            and context.get("instruct") == "neutral, conversational, american accent"
        ),
        None,
    )
    if old_conversational is not None:
        contexts.remove(old_conversational)
        changed = True

    existing_ids = {str(context.get("id")) for context in contexts}
    for default in OMNIVOICE_DEFAULT_CONTEXTS:
        if default["id"] not in existing_ids:
            contexts.append(dict(default))
            changed = True
    if changed:
        store.write_json(store.speech_contexts_path, contexts)
    return contexts


def _save_omnivoice_contexts(contexts: list[dict]) -> None:
    store = storage_for("omnivoice")
    store.write_json(store.speech_contexts_path, contexts)


def _get_omnivoice_context(context_id: str) -> dict | None:
    return next((ctx for ctx in _load_omnivoice_contexts() if ctx.get("id") == context_id), None)


def _sync_omnivoice_presets(registry: VoiceRegistry) -> list[VoiceRecord]:
    synced: list[VoiceRecord] = []
    for preset in OMNIVOICE_PRESET_VOICES:
        synced.append(
            registry.upsert(
                VoiceCreateRequest(
                    display_name=preset["display_name"],
                    voice_id=preset["voice_id"],
                    source_type="voice_design",
                    accent=preset["accent"],
                    consent_status="not_required",
                ),
                provider_metadata={
                    "provider": "omnivoice",
                    "mode": "design",
                    "context_id": preset["context_id"],
                    "voice_message_studio_profile": {
                        "language": "en",
                        "accent": preset["accent"],
                        "use_case": "conversational",
                    },
                },
            )
        )
    return synced


@app.get(
    "/api/{provider}/speech-contexts",
    response_model=list[OmniVoiceContext],
    tags=["Voices"],
    summary="List OmniVoice speech contexts",
    response_description="Saved voice-design contexts (seeded with defaults).",
)
def list_omnivoice_contexts(
    provider: OmniVoiceProviderPath,
    _user: dict = Depends(current_user),
) -> list[OmniVoiceContext]:
    _require_omnivoice(provider)
    return [OmniVoiceContext.model_validate(ctx) for ctx in _load_omnivoice_contexts()]


@app.post(
    "/api/{provider}/text-rules/check",
    response_model=OmniVoiceTextRuleResponse,
    tags=["Generate"],
    summary="Check text for OmniVoice generation",
    response_description="Blocking text-rule results plus deterministic spoken-text suggestions.",
)
def check_omnivoice_text_rules(
    provider: OmniVoiceProviderPath,
    request: OmniVoiceTextRuleRequest,
    _user: dict = Depends(current_user),
) -> OmniVoiceTextRuleResponse:
    """Check following rules in the text:

    - Replace slash `/` symbol because it is added as the word `slash` in the generated audio.
    """
    _require_omnivoice(provider)
    result = check_omnivoice_text(request.text)
    return OmniVoiceTextRuleResponse(
        ready=result.ready,
        original_text=result.original_text,
        suggested_text=result.suggested_text,
        changes=[change.__dict__ for change in result.changes],
        errors=list(result.errors),
    )


def _text_rule_response(text: str) -> OmniVoiceTextRuleResponse:
    result = check_omnivoice_text(text)
    return OmniVoiceTextRuleResponse(
        ready=result.ready,
        original_text=result.original_text,
        suggested_text=result.suggested_text,
        changes=[change.__dict__ for change in result.changes],
        errors=list(result.errors),
    )


@app.get(
    "/api/{provider}/text-conversions",
    response_model=OmniVoiceTextConversionsResponse,
    tags=["Generate"],
    summary="List OmniVoice text conversions",
    response_description="Available conversion templates plus required inputs and editable default prompts.",
)
def list_omnivoice_text_conversions(
    provider: OmniVoiceProviderPath,
    _user: dict = Depends(current_user),
) -> OmniVoiceTextConversionsResponse:
    """List OmniVoice-only text conversions and the inputs required by each conversion."""
    _require_omnivoice(provider)
    return OmniVoiceTextConversionsResponse(
        conversions=list_text_conversions(
            configured=text_conversion_client.configured,
            model=settings.openrouter_model,
            default_max_tokens=settings.openrouter_max_tokens,
        )
    )


@app.post(
    "/api/{provider}/text-conversions/{conversion_id}/convert",
    response_model=OmniVoiceTextConversionResponse,
    tags=["Generate"],
    summary="Convert text for OmniVoice",
    response_description="Converted text plus conversion warnings and OmniVoice text-rule results.",
)
async def convert_omnivoice_text(
    provider: OmniVoiceProviderPath,
    conversion_id: Annotated[str, ApiPath(description="Conversion id returned by GET /api/{provider}/text-conversions.")],
    request: OmniVoiceTextConversionRequest,
    _user: dict = Depends(current_user),
) -> OmniVoiceTextConversionResponse:
    """
    Convert source text into OmniVoice-ready text using the selected conversion.

    The original natural-language source is sent to OpenRouter. The LLM output
    is then normalized with WeTextProcessing English TN before conversion
    warnings and OmniVoice text-rule verification run.

    The backend does not request, store, or return model reasoning. Optional
    edited prompts are used only for this request.
    """
    _require_omnivoice(provider)
    definition = get_text_conversion(conversion_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Text conversion not found.")

    try:
        prompt_override = request.prompts.model_dump() if request.prompts else None
        system_prompt, user_prompt = build_conversion_prompts(definition, request.inputs, prompt_override)
        llm_text = await text_conversion_client.convert(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=request.max_tokens,
        )
        wetext_processing = await asyncio.to_thread(
            apply_wetext_processing,
            llm_text,
            wetext_processor.normalize,
        )
    except TextConversionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    converted = wetext_processing.text
    warnings = validate_converted_text(
        converted,
        request.inputs,
        profile=definition.validation_profile,
    )
    rule_check = _text_rule_response(converted)
    ready_for_omnivoice = rule_check.ready and not any(warning.severity == "error" for warning in warnings)
    return OmniVoiceTextConversionResponse(
        conversion_id=definition.id,
        text=converted,
        wetext_processing=OmniVoiceWeTextProcessing(
            engine=wetext_processing.engine,
            changed=wetext_processing.changed,
            original_text=wetext_processing.original_text,
            text=wetext_processing.text,
        ),
        prompts=OmniVoiceTextConversionPrompts(system_prompt=system_prompt, user_prompt=user_prompt),
        warnings=[warning.__dict__ for warning in warnings],
        rule_check=rule_check,
        ready_for_omnivoice=ready_for_omnivoice,
        spoken_words=count_spoken_words(converted),
        estimated_seconds=estimate_voice_note_seconds(converted),
    )


@app.post(
    "/api/{provider}/speech-contexts",
    response_model=OmniVoiceContext,
    tags=["Voices"],
    summary="Add or modify an OmniVoice speech context",
    response_description="The created or updated speech context.",
)
def upsert_omnivoice_context(
    provider: OmniVoiceProviderPath,
    request: OmniVoiceContextRequest,
    _user: dict = Depends(current_user),
) -> OmniVoiceContext:
    """Create a new speech context (omit id) or modify an existing one (with id)."""
    _require_omnivoice(provider)
    contexts = _load_omnivoice_contexts()
    context_id = (request.id or "").strip() or new_id("ctx")
    entry = {
        "id": context_id,
        "name": request.name,
        "instruct": request.instruct,
        "language": request.language,
        "settings": request.settings.model_dump(),
    }
    for index, existing in enumerate(contexts):
        if existing.get("id") == context_id:
            contexts[index] = entry
            break
    else:
        contexts.append(entry)
    _save_omnivoice_contexts(contexts)
    return OmniVoiceContext.model_validate(entry)


@app.delete(
    "/api/{provider}/speech-contexts/{context_id}",
    response_model=OmniVoiceContext,
    tags=["Voices"],
    summary="Delete an OmniVoice speech context",
    response_description="The removed speech context.",
)
def delete_omnivoice_context(
    provider: OmniVoiceProviderPath,
    context_id: Annotated[
        str,
        ApiPath(
            description=(
                "Speech-context `id` returned by `GET /api/{provider}/speech-contexts`. "
                "Use the `id` field from that response."
            ),
        ),
    ],
    _user: dict = Depends(current_user),
) -> OmniVoiceContext:
    _require_omnivoice(provider)
    if context_id in {context["id"] for context in OMNIVOICE_DEFAULT_CONTEXTS}:
        raise HTTPException(status_code=400, detail="Built-in OmniVoice accent presets cannot be deleted.")
    contexts = _load_omnivoice_contexts()
    removed = next((ctx for ctx in contexts if ctx.get("id") == context_id), None)
    if removed is None:
        raise HTTPException(status_code=404, detail="Speech context not found.")
    _save_omnivoice_contexts([ctx for ctx in contexts if ctx.get("id") != context_id])
    return OmniVoiceContext.model_validate(removed)


@app.post(
    "/api/{provider}/speech-contexts/preview",
    response_model=OmniVoiceContextPreview,
    tags=["Voices"],
    summary="Preview a speech context's voice design",
    response_description="Base64 WAV preview audio for the supplied design + settings.",
    include_in_schema=False,
)
async def preview_omnivoice_context(
    provider: OmniVoiceProviderPath,
    request: OmniVoiceContextPreviewRequest,
    _user: dict = Depends(current_user),
) -> OmniVoiceContextPreview:
    """Design-only preview (uses model's preset voice based on text and instruct): synthesize from instruct + settings."""
    _require_omnivoice(provider)
    try:
        require_omnivoice_text_ready(request.text)
    except OmniVoiceTextRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings = _omnivoice_settings({"settings": request.settings.model_dump()})
    item: dict = {"text": request.text, "language": str(request.language or "en")}
    if request.instruct.strip():
        item["instruct"] = request.instruct
    if settings.get("speed") is not None:
        item["speed"] = settings["speed"]
    if settings.get("duration"):
        item["duration"] = settings["duration"]
    try:
        payload = await client_for(provider).run_batch(
            {"items": [item], "audio_format": "wav", **_omnivoice_top_level(settings)}
        )
    except OmniVoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = (payload.get("results") or [{}])[0]
    if row.get("status") != "success" or not row.get("audio_b64"):
        raise HTTPException(status_code=400, detail=str(row.get("error") or "OmniVoice returned no audio. Try again."))
    return OmniVoiceContextPreview(audio_b64=row["audio_b64"], audio_format="wav", duration=row.get("duration"))


@app.post(
    "/api/{provider}/voices/clone",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Clone a voice from a sample",
    response_description="Saved registry record for the cloned OmniVoice or ElevenLabs voice.",
)
async def clone_voice(
    provider: CloneProviderPath,
    name: Annotated[str, Form(min_length=1, description="Name for the cloned voice.")],
    accent: Annotated[
        str | None,
        Form(
            description=(
                "Accent id. OmniVoice accepts `us` (American English), `in` (Indian English), "
                "or `auto` (detect from the reference sample), defaulting to `auto` when omitted. "
                "ElevenLabs accepts `us`, `in`, or `neutral`, defaulting to `neutral` when omitted."
            ),
            examples=["us", "in", "auto"],
        ),
    ] = None,
    consent_confirmed: Annotated[
        bool,
        Form(description="Must be true. Confirms the user has permission to clone this voice."),
    ] = False,
    description: Annotated[
        str,
        Form(description="Optional provider description. Omit or leave empty to use the existing safe default."),
    ] = "",
    reference_text: Annotated[
        str,
        Form(description="OmniVoice only: optional transcript of the sample to guide cloning."),
    ] = "",
    gender: Annotated[
        str,
        Form(
            description=(
                "ElevenLabs only: optional clone metadata label: `male`, `female`, or `neutral`. "
                "Omit or leave empty to send no gender label."
            )
        ),
    ] = "",
    age: Annotated[
        str,
        Form(
            description=(
                "ElevenLabs only: optional clone metadata label: `young`, `middle-aged`, or `old`. "
                "Omit or leave empty to send no age label."
            )
        ),
    ] = "",
    remove_background_noise: Annotated[
        bool,
        Form(
            description=(
                "ElevenLabs only: remove background noise before cloning. Leave false for an already clean sample "
                "because denoising can reduce clone quality. Defaults to false."
            )
        ),
    ] = False,
    sample: Annotated[
        UploadFile | None,
        File(
            description=(
                "Legacy-compatible single consented sample field. Required for OmniVoice and still accepted for "
                "existing ElevenLabs clients. At least one `sample` or `samples` upload is required operationally."
            )
        ),
    ] = None,
    samples: Annotated[
        list[UploadFile] | None,
        File(
            description=(
                "ElevenLabs only: optional multi-file form uploaded as repeated `samples` fields. At least one "
                "`sample` or `samples` upload is required operationally."
            )
        ),
    ] = None,
    _user: dict = Depends(current_user),
) -> VoiceRecord:
    """
    Clone a voice through OmniVoice or ElevenLabs and persist it locally.

    OmniVoice stores a normalized reference WAV locally. Longer OmniVoice
    recordings are analyzed as a whole and trimmed only to one continuous
    section: the best-scored 3-10 second pause-bounded clip when available
    (fluency, human-like delivery, and natural expression), otherwise the
    shortest pause/source-bounded clip. ElevenLabs uploads one or more samples
    for instant voice cloning. The legacy single `sample` field remains
    accepted, while repeated `samples` fields support multiple files. ElevenLabs
    sends a fixed English language label plus
    accent/gender/age labels and the optional background-noise setting. Speech
    context is deliberately selected later during generation. Both paths
    require explicit consent, and uploaded samples are retained under the app
    data directory for auditability.
    """
    provider = validate_provider(provider)
    accent_id = (accent or ("auto" if provider == "omnivoice" else "neutral")).strip().lower()
    allowed_accents = {"us", "in", "auto"} if provider == "omnivoice" else {"us", "in", "neutral"}
    if accent_id not in allowed_accents:
        choices = (
            "`us` (American English), `in` (Indian English), `auto` (detect from reference sample)"
            if provider == "omnivoice"
            else "`us` (American English), `in` (Indian English), `neutral` (unspecified)"
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid argument `accent` for provider `{provider}`: `{accent_id}`. "
                f"Expected one of: {choices}."
            ),
        )
    if not consent_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Invalid argument `consent_confirmed`: must be `true` before cloning.",
        )

    uploaded_samples = ([sample] if sample is not None else []) + list(samples or [])
    if not uploaded_samples:
        raise HTTPException(status_code=400, detail="Add at least one consented voice sample before cloning.")
    if provider == "omnivoice" and len(uploaded_samples) != 1:
        raise HTTPException(status_code=400, detail="OmniVoice cloning accepts exactly one voice sample.")

    language_code = "en"
    gender_label = gender.strip().lower()
    age_label = age.strip().lower()
    if provider == "elevenlabs":
        if gender_label not in {"", "male", "female", "neutral"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid argument `gender`: expected `male`, `female`, `neutral`, or empty.",
            )
        if age_label not in {"", "young", "middle-aged", "old"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid argument `age`: expected `young`, `middle-aged`, `old`, or empty.",
            )

    provider_storage = storage_for(provider)
    registry = registry_for(provider)
    record_id = new_id("voice")
    sample_payloads: list[tuple[UploadFile, bytes]] = []
    for index, uploaded_sample in enumerate(uploaded_samples, start=1):
        sample_bytes = await uploaded_sample.read()
        if not sample_bytes:
            raise HTTPException(status_code=400, detail=f"Voice sample {index} is empty.")
        sample_payloads.append((uploaded_sample, sample_bytes))

    stored_samples: list[tuple[Path, str | None]] = []
    for index, (uploaded_sample, sample_bytes) in enumerate(sample_payloads, start=1):
        source_path = provider_storage.source_audio_path(
            record_id,
            uploaded_sample.filename or "sample.audio",
            sample_index=index if len(uploaded_samples) > 1 else None,
        )
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(sample_bytes)
        stored_samples.append((source_path, uploaded_sample.content_type))

    source_path = stored_samples[0][0]

    if provider == "omnivoice":
        # The OmniVoice space reads the sample as reference audio (soundfile),
        # which can't decode browser recordings (webm/opus). Normalize to WAV,
        # analyze pauses, and use one continuous pause-bounded reference clip;
        # keep the original upload for audit.
        wav_path = source_path.with_suffix(".wav")
        if wav_path == source_path:
            wav_path = source_path.with_name(f"{source_path.stem}-normalized.wav")
        try:
            reference_clip = await asyncio.to_thread(audio_export_service.export_reference_wav, source_path, wav_path)
        except ReferenceClipSelectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (subprocess.CalledProcessError, OSError) as exc:
            raise HTTPException(
                status_code=400,
                detail=audio_export_error_detail(exc),
            ) from exc
        timestamp = now_utc()
        voice_id = new_id("ov_clone")
        omnivoice_metadata = {
            "provider": "omnivoice",
            "mode": "clone",
            "description": description,
            "reference_clip": reference_clip.to_metadata(),
            "voice_message_studio_profile": {
                "language": "en",
                "accent": accent_id,
                "use_case": "conversational",
            },
        }
        if reference_text.strip():
            omnivoice_metadata["reference_text"] = reference_text.strip()
        record = VoiceRecord(
            id=record_id,
            display_name=name,
            voice_id=voice_id,
            source_type="cloned",
            accent=accent_id,
            consent_status="confirmed",
            source_audio_path=provider_storage.relative_to_data(wav_path),
            provider_metadata=omnivoice_metadata,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return registry.upsert_record(record)

    try:
        clone_labels = {
            "language": language_code,
            "accent": ACCENT_LABELS[accent_id],
        }
        if gender_label:
            clone_labels["gender"] = gender_label
        if age_label:
            clone_labels["age"] = age_label
        clone_description = description or "Voice cloned from consented samples in Voice Message Studio."
        provider_voice = await elevenlabs.clone_voice(
            name=name,
            description=clone_description,
            sample_files=stored_samples,
            labels=clone_labels,
            remove_background_noise=remove_background_noise,
        )
    except ElevenLabsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    voice_id = provider_voice.get("voice_id")
    if not voice_id:
        raise HTTPException(status_code=502, detail="ElevenLabs did not return a voice_id.")

    timestamp = now_utc()
    record = VoiceRecord(
        id=record_id,
        display_name=name,
        voice_id=voice_id,
        source_type="cloned",
        accent=accent_id,
        consent_status="confirmed",
        source_audio_path=provider_storage.relative_to_data(source_path),
        provider_metadata={
            **provider_voice,
            "provider": "elevenlabs",
            "mode": "instant_voice_clone",
            "description": clone_description,
            "labels": clone_labels,
            "remove_background_noise": remove_background_noise,
            "source_audio_paths": [
                provider_storage.relative_to_data(path) for path, _content_type in stored_samples
            ],
        },
        created_at=timestamp,
        updated_at=timestamp,
    )
    return registry.upsert_record(record)


def _job_status(rows: list[AudioResult], total: int) -> str:
    """Terminal status for a finished job from its rows."""
    completed = sum(1 for row in rows if row.status == "completed")
    failed = sum(1 for row in rows if row.status == "failed")
    if completed == total:
        return "completed"
    if completed == 0 and failed == total:
        return "failed"
    return "partial"


def _save_job_manifest(
    provider_storage: StorageService,
    job_id: str,
    kind: str,
    created_at: datetime,
    rows: list[AudioResult],
    workbook_url: str | None = None,
) -> JobDetail:
    completed = sum(1 for row in rows if row.status == "completed")
    detail = JobDetail(
        job_id=job_id,
        kind=kind,
        status=_job_status(rows, len(rows)),
        created_at=created_at,
        total_rows=len(rows),
        completed_rows=completed,
        failed_rows=len(rows) - completed,
        rows=rows,
        workbook_url=workbook_url,
    )
    provider_storage.save_job_manifest(job_id, detail.model_dump(mode="json"))
    return detail


@app.post(
    "/api/{provider}/tts",
    response_model=AudioResult,
    tags=["Generate"],
    summary="Generate one voice note",
    response_description="Single-row generation result with download URLs when completed.",
)
async def create_tts(provider: ProviderPath, request: TtsApiRequest, _user: dict = Depends(current_user)) -> AudioResult:
    """
    Generate one MP3 voice note and persist it as a job.

    ElevenLabs uses `voice_id` as the provider voice id and `speech_context` as
    an optional built-in delivery style. Its optional `voice_settings_override`
    retains the existing nested schema and may provide stability,
    similarity_boost, style, and speed individually; omitted or null values
    inherit saved context settings and then the built-in context preset. Model
    support varies, and Eleven v3 expression primarily comes from prompting and
    audio tags. OmniVoice uses `voice_id` as a saved
    preset or cloned/sample voice and requires `speech_context` to be a saved
    OmniVoice speech-context id with voice design and generation settings.
    """
    provider = validate_provider(provider)
    tts_request = request.to_tts_request()
    if provider == "omnivoice":
        try:
            require_omnivoice_text_ready(tts_request.text)
        except OmniVoiceTextRuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider_storage = storage_for(provider)
    job_id = new_id("job")
    created_at = datetime.now(timezone.utc)
    row = await generate_row(provider, job_id, 1, tts_request)
    _save_job_manifest(provider_storage, job_id, "single", created_at, [row])
    return row


def _write_job_progress(
    provider_storage: StorageService,
    job_id: str,
    created_at: datetime,
    *,
    status: JobStatus,
    total_rows: int,
    rows: list[AudioResult],
    workbook_url: str | None = None,
    error: str | None = None,
) -> None:
    detail = JobDetail(
        job_id=job_id,
        kind="batch",
        status=status,
        created_at=created_at,
        total_rows=total_rows,
        completed_rows=sum(1 for row in rows if row.status == "completed"),
        failed_rows=sum(1 for row in rows if row.status == "failed"),
        rows=rows,
        workbook_url=workbook_url,
        error=error,
    )
    provider_storage.save_job_manifest(job_id, detail.model_dump(mode="json"))


async def _generate_rows_individually(
    provider: str,
    provider_storage: StorageService,
    job_id: str,
    created_at: datetime,
    requests: list[TtsRequest],
) -> dict[int, AudioResult]:
    """One provider call per row, concurrently (bounded by the generation semaphore)."""
    total = len(requests)
    results: dict[int, AudioResult] = {}

    async def run_one(index: int, request: TtsRequest) -> None:
        result = await generate_row(provider, job_id, index, request)
        # No await between mutation and the write, so it is atomic on the event loop.
        results[index] = result
        _write_job_progress(
            provider_storage,
            job_id,
            created_at,
            status="running",
            total_rows=total,
            rows=[results[i] for i in sorted(results)],
        )

    await asyncio.gather(*(run_one(i, r) for i, r in enumerate(requests, start=1)))
    return results


async def _generate_omnivoice_batch(
    provider_storage: StorageService,
    job_id: str,
    created_at: datetime,
    requests: list[TtsRequest],
) -> dict[int, AudioResult]:
    """Send rows to the OmniVoice space in chunks (one /batch call per chunk)."""
    registry = registry_for("omnivoice")
    omnivoice = client_for("omnivoice")
    total = len(requests)
    results: dict[int, AudioResult] = {}

    def write_running() -> None:
        _write_job_progress(
            provider_storage,
            job_id,
            created_at,
            status="running",
            total_rows=total,
            rows=[results[i] for i in sorted(results)],
        )

    # Build each row's item + its batch-global settings. Rows whose voice can't be
    # resolved fail immediately. The top-level settings (steps/guidance/denoise/...)
    # apply per /batch call, so rows are grouped by those settings before chunking.
    groups: dict[tuple, list[tuple[int, TtsRequest, dict]]] = {}
    for index, request in enumerate(requests, start=1):
        try:
            item, row_settings = _omnivoice_item(provider_storage, registry, request)
        except (OmniVoiceError, OmniVoiceTextRuleError) as exc:
            results[index] = _failed_audio_row("omnivoice", job_id, index, request, exc, now_utc())
            continue
        top_level = _omnivoice_top_level(row_settings)
        groups.setdefault(tuple(sorted(top_level.items())), []).append((index, request, item))
    if results:
        write_running()

    chunk_size = max(1, settings.omnivoice_batch_chunk)
    for signature, entries in groups.items():
        top_level = dict(signature)
        for start in range(0, len(entries), chunk_size):
            chunk = entries[start : start + chunk_size]
            async with _generation_semaphore:
                try:
                    response = await omnivoice.run_batch(
                        {"items": [item for (_, _, item) in chunk], "audio_format": "wav", **top_level}
                    )
                    out = response.get("results") or []
                except OmniVoiceError as exc:
                    for index, request, _item in chunk:
                        results[index] = _failed_audio_row("omnivoice", job_id, index, request, exc, now_utc())
                    write_running()
                    continue
                for offset, (index, request, _item) in enumerate(chunk):
                    created = now_utc()
                    row_payload = out[offset] if offset < len(out) else {}
                    if row_payload.get("status") != "success" or not row_payload.get("audio_b64"):
                        err = OmniVoiceError(str(row_payload.get("error") or "OmniVoice returned no audio."))
                        results[index] = _failed_audio_row("omnivoice", job_id, index, request, err, created)
                        continue
                    try:
                        wav_bytes = base64.b64decode(row_payload["audio_b64"])
                        results[index] = await _finalize_audio_row(
                            provider_storage,
                            job_id,
                            index,
                            request,
                            audio_bytes=wav_bytes,
                            source_format="wav",
                            model_id="omnivoice_batch_space",
                            created_at=created,
                        )
                    except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
                        results[index] = _failed_audio_row("omnivoice", job_id, index, request, exc, created)
            write_running()
    return results


async def run_batch_job(provider: str, job_id: str, created_at: datetime, requests: list[TtsRequest]) -> None:
    """Background runner: generate rows, keep the manifest updated, finalize the job."""
    provider_storage = storage_for(provider)
    total = len(requests)
    try:
        if provider == "omnivoice":
            results = await _generate_omnivoice_batch(provider_storage, job_id, created_at, requests)
        else:
            results = await _generate_rows_individually(provider, provider_storage, job_id, created_at, requests)
        rows = [results[i] for i in sorted(results)]
        workbook_path = provider_storage.job_folder(job_id) / "tts_results.xlsx"
        await asyncio.to_thread(
            workbooks.write_results, workbook_path, [row.model_dump(mode="json") for row in rows]
        )
        _write_job_progress(
            provider_storage,
            job_id,
            created_at,
            status=_job_status(rows, total),
            total_rows=total,
            rows=rows,
            workbook_url=provider_storage.file_url(workbook_path),
        )
    except Exception as exc:  # finalize as failed rather than leaving the job 'running'
        logger.exception("Batch job %s failed", job_id)
        _write_job_progress(
            provider_storage, job_id, created_at, status="failed", total_rows=total, rows=[], error=str(exc)
        )


@app.post(
    "/api/{provider}/tts/batch",
    status_code=202,
    response_model=JobSummary,
    tags=["Generate"],
    summary="Submit an .xlsx batch (async)",
    response_description="Accepted job. Poll GET /api/{provider}/jobs/{job_id} for status, progress, and results.",
)
async def create_batch(
    provider: ProviderPath,
    file: UploadFile = File(
        ...,
        description=(
            "Excel .xlsx workbook with a sheet named tts_requests. Required columns: "
            "text, voice_id. Optional: voice_name, accent, speech_context, target_seconds, wpm, export_m4a."
        ),
    ),
    _user: dict = Depends(current_user),
) -> JobSummary:
    """
    Accept an Excel workbook and generate audio for every non-empty row in the
    background, returning immediately with a job you can poll.

    The workbook is parsed and validated synchronously (bad file or over-limit row
    counts fail here with 400). Generation then runs asynchronously: poll
    `GET /api/{provider}/jobs/{job_id}` until `status` is `completed`, `partial`, `failed`, or
    `interrupted`, then download via `GET /api/{provider}/jobs/{job_id}/download`. CSV is
    rejected because message text may contain commas.
    """
    provider = validate_provider(provider)
    provider_storage = storage_for(provider)
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Upload an .xlsx workbook, not CSV.")

    job_id = new_id("job")
    created_at = datetime.now(timezone.utc)
    source_path = provider_storage.job_folder(job_id) / "source.xlsx"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(await file.read())

    try:
        requests = workbooks.parse_requests(source_path)
    except WorkbookError as exc:
        shutil.rmtree(provider_storage.job_folder(job_id), ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not requests:
        shutil.rmtree(provider_storage.job_folder(job_id), ignore_errors=True)
        raise HTTPException(status_code=400, detail="The workbook has no data rows.")
    if len(requests) > settings.max_batch_rows:
        shutil.rmtree(provider_storage.job_folder(job_id), ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail=(
                f"This batch has {len(requests)} rows, above the limit of "
                f"{settings.max_batch_rows}. Split it into smaller workbooks."
            ),
        )

    if provider == "omnivoice":
        rule_errors = []
        for row_number, request in enumerate(requests, start=2):
            try:
                require_omnivoice_text_ready(request.text)
            except OmniVoiceTextRuleError as exc:
                rule_errors.append(f"Row {row_number}: {exc}")
        if rule_errors:
            shutil.rmtree(provider_storage.job_folder(job_id), ignore_errors=True)
            preview = " | ".join(rule_errors[:10])
            if len(rule_errors) > 10:
                preview += f" | {len(rule_errors) - 10} more invalid row(s)."
            raise HTTPException(status_code=400, detail=f"OmniVoice text rules failed. {preview}")

    total = len(requests)
    _write_job_progress(provider_storage, job_id, created_at, status="running", total_rows=total, rows=[])

    task = asyncio.create_task(run_batch_job(provider, job_id, created_at, requests))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return JobSummary(
        job_id=job_id,
        kind="batch",
        status="running",
        created_at=created_at,
        total_rows=total,
        completed_rows=0,
        failed_rows=0,
    )


@app.get(
    "/api/{provider}/jobs",
    response_model=list[JobSummary],
    tags=["History"],
    summary="List generation jobs",
    response_description="Jobs sorted newest first.",
)
def list_jobs(provider: ProviderPath, _user: dict = Depends(current_user)) -> list[JobSummary]:
    """List persisted single and batch generation jobs from the data directory."""
    provider = validate_provider(provider)
    provider_storage = storage_for(provider)
    summaries: list[JobSummary] = []
    for job_id in provider_storage.list_job_ids():
        manifest = provider_storage.read_job_manifest(job_id)
        if not manifest:
            continue
        summaries.append(JobSummary.model_validate(manifest))
    return sorted(summaries, key=lambda summary: summary.created_at, reverse=True)


@app.get(
    "/api/{provider}/jobs/{job_id}/download",
    tags=["History"],
    summary="Download a job as a ZIP",
    response_class=Response,
    responses={
        200: {
            "description": "ZIP archive containing row transcripts and generated audio files.",
            "content": {"application/zip": {}},
        },
        404: {"description": "Job not found."},
    },
)
def download_job(
    provider: ProviderPath,
    job_id: Annotated[str, ApiPath(description="Job id returned by /api/{provider}/tts or /api/{provider}/tts/batch.")],
    _user: dict = Depends(current_user),
) -> Response:
    """
    Build and return a ZIP archive for a job.

    Each row can include transcript text, MP3, and M4A. If an M4A is missing but
    the MP3 exists, the endpoint attempts to create the M4A before zipping.
    """
    provider = validate_provider(provider)
    provider_storage = storage_for(provider)
    manifest = provider_storage.read_job_manifest(job_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Job not found.")
    detail = JobDetail.model_validate(manifest)
    if detail.status == "running":
        raise HTTPException(status_code=409, detail="Job is still running. Poll until it finishes.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in detail.rows:
            index = row.index or 0
            base = f"row-{index:03d}"
            label = safe_filename(row.voice_name or row.voice_id or base)
            stem = f"{base}-{label}"

            transcript_path = provider_storage.job_row_path(job_id, index, "txt")
            if transcript_path.exists():
                archive.write(transcript_path, f"{stem}.txt")
            elif row.text:
                archive.writestr(f"{stem}.txt", row.text)

            mp3_path = provider_storage.job_row_path(job_id, index, "mp3")
            if not mp3_path.exists():
                continue
            archive.write(mp3_path, f"{stem}.mp3")

            m4a_path = provider_storage.job_row_path(job_id, index, "m4a")
            if not m4a_path.exists():
                try:
                    audio_export_service.export_linkedin_m4a(mp3_path, m4a_path)
                except (subprocess.CalledProcessError, OSError, ValueError):
                    m4a_path = None
            if m4a_path and m4a_path.exists():
                archive.write(m4a_path, f"{stem}.m4a")

    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.zip"'},
    )


@app.get(
    "/api/{provider}/jobs/{job_id}",
    response_model=JobDetail,
    tags=["History"],
    summary="Get one job with rows",
    response_description="Full job manifest with row-level results.",
)
def get_job(
    provider: ProviderPath,
    job_id: Annotated[str, ApiPath(description="Job id returned by /api/{provider}/tts or /api/{provider}/tts/batch.")],
    _user: dict = Depends(current_user),
) -> JobDetail:
    """Return one persisted job manifest including all row results."""
    provider = validate_provider(provider)
    manifest = storage_for(provider).read_job_manifest(job_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobDetail.model_validate(manifest)


@app.get(
    "/api/{provider}/files/{relative_path:path}",
    tags=["Files"],
    summary="Download a generated file",
    response_class=FileResponse,
    responses={
        200: {"description": "Requested file from DATA_DIR."},
        400: {"description": "Path escapes the data directory."},
        404: {"description": "File not found."},
    },
)
def serve_data_file(
    provider: ProviderPath,
    relative_path: Annotated[
        str,
        ApiPath(
            description=(
                "Append only the file path after `/files/`, not the full API URL. "
                "Example: for `/api/omnivoice/files/jobs/job_xxx/row-001.mp3`, "
                "enter `jobs/job_xxx/row-001.mp3`."
            ),
            examples=["jobs/job_xxx/row-001.mp3"],
        ),
    ],
    _user: dict = Depends(current_user),
) -> FileResponse:
    """
    Download a generated audio, transcript, workbook, source, or metadata file.

    Use only the path segment after `/files/`; the path is resolved strictly
    under the selected provider's `DATA_DIR` subtree. Attempts to paste a full
    API path or escape the data directory are rejected.
    """
    provider = validate_provider(provider)
    provider_storage = storage_for(provider)
    try:
        path = provider_storage.resolve_file(relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)


@app.get("/files/{relative_path:path}", include_in_schema=False)
def serve_legacy_elevenlabs_file(
    relative_path: str,
    _user: dict = Depends(current_user),
) -> FileResponse:
    """Backward-compatible file route for older ElevenLabs manifests."""
    try:
        path = storage_for("elevenlabs").resolve_file(relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)


_GENERATION_ERRORS = (
    ElevenLabsError,
    OmniVoiceError,
    subprocess.CalledProcessError,
    ValidationError,
    OSError,
    ValueError,
)


_OMNIVOICE_DEFAULT_SETTINGS = {
    "speed": 1.0,
    "duration": None,
    "num_step": 32,
    "guidance_scale": 2.0,
    "denoise": True,
    "preprocess_prompt": True,
    "postprocess_output": True,
}


def _omnivoice_settings(metadata: dict) -> dict:
    """Merge a voice/tone's saved generation settings over the Space defaults."""
    settings = dict(_OMNIVOICE_DEFAULT_SETTINGS)
    saved = metadata.get("settings")
    if isinstance(saved, dict):
        settings.update({key: saved[key] for key in settings if key in saved})
    return settings


def _omnivoice_top_level(settings: dict) -> dict:
    """Batch-global OmniVoice payload keys (apply to every item in one /batch call)."""
    return {
        "num_step": settings["num_step"],
        "guidance_scale": settings["guidance_scale"],
        "denoise": settings["denoise"],
        "preprocess_prompt": settings["preprocess_prompt"],
        "postprocess_output": settings["postprocess_output"],
    }


def _omnivoice_item(
    provider_storage: StorageService, registry: VoiceRegistry, request: TtsRequest
) -> tuple[dict, dict]:
    """Build one OmniVoice batch item for a design preset or a sample clone."""
    require_omnivoice_text_ready(request.text)
    record = registry.find_by_provider_voice_id(request.voice_id)
    if record is None:
        raise OmniVoiceError("Select a saved OmniVoice preset or uploaded voice sample before generating audio.")

    voice_meta = record.provider_metadata or {}
    mode = str(voice_meta.get("mode") or "clone")
    context_id = str(voice_meta.get("context_id") or request.speech_context)
    context = _get_omnivoice_context(context_id)
    if context is None:
        raise OmniVoiceError("Select a saved OmniVoice speech context before generating audio.")

    settings = _omnivoice_settings(context)
    item: dict = {
        "text": request.text,
        "language": str(context.get("language") or "en"),
    }
    if mode == "design":
        instruct = str(context.get("instruct") or "").strip()
        if not instruct:
            raise OmniVoiceError("The selected OmniVoice design preset has no voice-design instruction.")
        item["instruct"] = instruct
    else:
        if not record.source_audio_path:
            raise OmniVoiceError("The selected OmniVoice clone has no saved source sample.")
        source_path = provider_storage.resolve_file(record.source_audio_path)
        item["ref_audio_b64"] = base64.b64encode(source_path.read_bytes()).decode("ascii")
        if voice_meta.get("reference_text"):
            item["ref_text"] = str(voice_meta["reference_text"])
    if settings.get("speed") is not None:
        item["speed"] = settings["speed"]
    if settings.get("duration"):
        item["duration"] = settings["duration"]
    return item, settings


async def _finalize_audio_row(
    provider_storage: StorageService,
    job_id: str,
    index: int,
    request: TtsRequest,
    *,
    audio_bytes: bytes,
    source_format: str,
    model_id: str | None,
    created_at: datetime,
    spoken_text: str | None = None,
) -> AudioResult:
    """Persist audio (transcoding wav->mp3 when needed), measure, optional m4a, build the result."""
    estimated_seconds = duration_service.estimate_seconds(request.text, request.wpm)
    max_seconds = settings.max_duration_seconds
    mp3_path = provider_storage.job_row_path(job_id, index, "mp3")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    if source_format == "mp3":
        mp3_path.write_bytes(audio_bytes)
        measure_path = mp3_path
    else:
        wav_path = provider_storage.job_row_path(job_id, index, "wav")
        wav_path.write_bytes(audio_bytes)
        await asyncio.to_thread(audio_export_service.export_mp3, wav_path, mp3_path)
        measure_path = wav_path

    transcript_path = provider_storage.job_row_path(job_id, index, "txt")
    transcript_path.write_text(request.text, encoding="utf-8")

    actual_seconds = await asyncio.to_thread(duration_service.measure_seconds, measure_path)
    warning = None
    if actual_seconds > max_seconds:
        warning = WarningState(
            level="red",
            code="hard_limit_exceeded",
            message=(
                f"Generated audio is {actual_seconds:.1f}s, above the "
                f"{max_seconds}s LinkedIn voice-note limit."
            ),
        )

    m4a_url = None
    if request.export_m4a:
        m4a_path = provider_storage.job_row_path(job_id, index, "m4a")
        await asyncio.to_thread(audio_export_service.export_linkedin_m4a, mp3_path, m4a_path)
        m4a_url = provider_storage.file_url(m4a_path)

    return AudioResult(
        job_id=job_id,
        index=index,
        status="completed",
        text=request.text,
        spoken_text=spoken_text,
        voice_id=request.voice_id,
        voice_name=request.voice_name,
        model_id=model_id,
        speech_context=request.speech_context,
        accent=request.accent,
        estimated_seconds=estimated_seconds,
        target_seconds=request.target_seconds,
        max_seconds=max_seconds,
        actual_seconds=actual_seconds,
        warning=warning,
        mp3_url=provider_storage.file_url(mp3_path),
        m4a_url=m4a_url,
        transcript_url=provider_storage.file_url(transcript_path),
        created_at=created_at,
    )


def _failed_audio_row(
    provider: str,
    job_id: str,
    index: int,
    request: TtsRequest,
    exc: Exception,
    created_at: datetime,
) -> AudioResult:
    logger.warning("Generation failed for job %s row %s: %s", job_id, index, exc)
    estimated_seconds = duration_service.estimate_seconds(request.text, request.wpm)
    warning = None
    if estimated_seconds > request.target_seconds:
        warning = WarningState(
            level="yellow",
            code="estimated_target_exceeded",
            message=(
                f"Estimated duration is {estimated_seconds:.1f}s, above the "
                f"{request.target_seconds}s target. Generation failed before measuring actual audio."
            ),
        )
    return AudioResult(
        job_id=job_id,
        index=index,
        status="failed",
        text=request.text,
        voice_id=request.voice_id,
        voice_name=request.voice_name,
        model_id=settings.elevenlabs_model_id if provider == "elevenlabs" else "omnivoice_batch_space",
        speech_context=request.speech_context,
        accent=request.accent,
        estimated_seconds=estimated_seconds,
        target_seconds=request.target_seconds,
        max_seconds=settings.max_duration_seconds,
        warning=warning,
        error=str(exc),
        created_at=created_at,
    )


async def generate_row(provider: str, job_id: str, index: int, request: TtsRequest) -> AudioResult:
    """Generate one row for the given provider (single call). Never raises."""
    provider = validate_provider(provider)
    provider_storage = storage_for(provider)
    provider_registry = registry_for(provider)
    created_at = now_utc()

    # Bound concurrent generation, and run blocking ffmpeg/ffprobe off the event loop.
    async with _generation_semaphore:
        try:
            if provider == "elevenlabs":
                language_code = None
                voice_record = provider_registry.find_by_provider_voice_id(request.voice_id)
                if voice_record:
                    saved_language = (voice_record.provider_metadata.get("labels") or {}).get("language")
                    if isinstance(saved_language, str) and re.fullmatch(r"[A-Za-z]{2}", saved_language.strip()):
                        language_code = saved_language.strip().lower()
                effective_voice_settings = _elevenlabs_context_voice_settings(request.speech_context)
                if request.voice_settings_override:
                    effective_voice_settings.update(
                        request.voice_settings_override.model_dump(exclude_none=True)
                    )
                spoken_text = None
                if request.enhance_text and text_conversion_client.configured:
                    context_id = (
                        request.speech_context
                        if request.speech_context in CONTEXT_LABELS
                        else "outreach_conversational"
                    )
                    system_prompt, user_prompt = build_enhance_prompts(
                        text=request.text,
                        context_label=CONTEXT_LABELS[context_id],
                        context_note=CONTEXT_NOTES[context_id],
                        model_id=settings.elevenlabs_model_id,
                        target_seconds=request.target_seconds,
                    )
                    try:
                        spoken_text = await text_conversion_client.convert(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            max_tokens=1200,
                        )
                    except TextConversionError as exc:
                        logger.warning(
                            "Spoken-text enhancement failed for job %s row %s; using original text: %s",
                            job_id,
                            index,
                            exc,
                        )
                mp3_bytes = await elevenlabs.text_to_speech(
                    voice_id=request.voice_id,
                    text=spoken_text or request.text,
                    speech_context=request.speech_context,
                    voice_settings=effective_voice_settings,
                    language_code=language_code,
                    apply_delivery_tag=spoken_text is None,
                )
                return await _finalize_audio_row(
                    provider_storage,
                    job_id,
                    index,
                    request,
                    audio_bytes=mp3_bytes,
                    source_format="mp3",
                    model_id=settings.elevenlabs_model_id,
                    created_at=created_at,
                    spoken_text=spoken_text,
                )

            item, gen_settings = _omnivoice_item(provider_storage, provider_registry, request)
            payload = await client_for(provider).run_batch(
                {"items": [item], "audio_format": "wav", **_omnivoice_top_level(gen_settings)}
            )
            row_payload = (payload.get("results") or [{}])[0]
            if row_payload.get("status") != "success" or not row_payload.get("audio_b64"):
                raise OmniVoiceError(str(row_payload.get("error") or "OmniVoice returned no audio."))
            return await _finalize_audio_row(
                provider_storage,
                job_id,
                index,
                request,
                audio_bytes=base64.b64decode(row_payload["audio_b64"]),
                source_format="wav",
                model_id="omnivoice_batch_space",
                created_at=created_at,
            )
        except _GENERATION_ERRORS as exc:
            return _failed_audio_row(provider, job_id, index, request, exc, created_at)

if settings.static_dir.exists():
    app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def unknown_api_route(full_path: str) -> None:
    raise HTTPException(status_code=404, detail=f"API route not found: /api/{full_path}")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_react_app(full_path: str) -> FileResponse:
    index_path = settings.static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="React build not found. Run the Docker image or build frontend.")
