from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import io
import logging
import shutil
import subprocess
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
    HealthResponse,
    JobDetail,
    JobStatus,
    JobSummary,
    LogoutResponse,
    ProviderVoiceByIdRequest,
    ProviderVoiceOption,
    ProviderVoicePage,
    ProviderVoiceSaveRequest,
    TtsRequest,
    AuthState,
    VoiceCreateRequest,
    VoiceRecord,
    WarningState,
)
from app.services.audio_export import AudioExportService
from app.services.duration import DurationService
from app.services.elevenlabs import ElevenLabsClient, ElevenLabsError
from app.services.speech_context import CONTEXT_LABELS, CONTEXT_NOTES
from app.services.storage import StorageService, new_id, now_utc, safe_filename
from app.services.voice_filter import ProviderVoiceProfile, provider_voice_profile, provider_voice_rank
from app.services.voice_registry import VoiceRegistry
from app.services.workbook import WorkbookError, WorkbookService

settings = get_settings()
storage = StorageService(settings)
storage.ensure()
voice_registry = VoiceRegistry(storage)
duration_service = DurationService()
audio_export_service = AudioExportService()
elevenlabs = ElevenLabsClient(settings)
workbooks = WorkbookService()
PROVIDER_LIBRARY_ACCENTS = {"us", "in"}
ACCENT_LABELS = {"us": "American", "in": "Indian", "neutral": "Neutral"}
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
# In-memory caches so paging/sorting the voice library does not re-hit ElevenLabs.
# Cleared manually via DELETE /api/elevenlabs/voices/cache.
_shared_page_cache: dict[str, dict] = {}
_shared_voice_cache: dict[str, dict] = {}

logger = logging.getLogger("voice_message_studio")
# Bounds concurrent TTS+ffmpeg work so parallel requests/batches can't spawn an
# unbounded number of ffmpeg processes and exhaust the container.
_generation_semaphore = asyncio.Semaphore(settings.max_concurrent_generations)
# Strong refs to in-flight background batch tasks so they are not garbage-collected.
_background_tasks: set[asyncio.Task] = set()

API_DESCRIPTION = """
**Voice Message Studio** turns text into reviewable LinkedIn-ready voice notes
using ElevenLabs, with single and batch (Excel) generation, a voice registry,
and a job history with per-job ZIP export.

### Workflow

1. **Pick a voice** — browse premade/library voices (`GET /api/elevenlabs/voices`)
   and save one (`POST /api/elevenlabs/voices/{voice_id}`), or list your saved
   voices (`GET /api/voices`).
2. **Generate** — one clip (`POST /api/tts`) or a batch from an `.xlsx`
   (`POST /api/tts/batch`). Each run becomes a **job**.
3. **History** — list jobs (`GET /api/jobs`), inspect rows
   (`GET /api/jobs/{job_id}`), and download a ZIP of text + mp3 + m4a
   (`GET /api/jobs/{job_id}/download`).

### Authentication

- **Browser** — sign in with Google or username/password; the session cookie
  authorizes every call automatically.
- **Machine / API** — send an `X-API-Key: <key>` header. On this page click
  **Authorize**, paste the key once, then use **Try it out**.
"""

OPENAPI_TAGS = [
    {"name": "Voices", "description": "Saved voice registry and ElevenLabs voice picker."},
    {"name": "Generate", "description": "Single and batch text-to-speech generation."},
    {"name": "History", "description": "Generation jobs: list, inspect, and download."},
    {"name": "Files", "description": "Authenticated file downloads from DATA_DIR."},
]

def _reconcile_interrupted_jobs() -> None:
    """Mark jobs left 'running' by a previous process as interrupted.

    Safe because this single-worker process starts with zero in-flight tasks, so
    any persisted 'running' job cannot still be alive. NOTE: this assumption breaks
    with multiple workers/processes — switch to heartbeat-based reaping if you scale.
    """
    for job_id in storage.list_job_ids():
        manifest = storage.read_job_manifest(job_id)
        if not manifest or manifest.get("status") != "running":
            continue
        manifest["status"] = "interrupted"
        manifest["error"] = "Generation was interrupted because the server restarted. Re-run this batch."
        completed = manifest.get("completed_rows", 0)
        total = manifest.get("total_rows", 0)
        manifest["failed_rows"] = max(manifest.get("failed_rows", 0), total - completed)
        storage.save_job_manifest(job_id, manifest)
        logger.warning("Marked interrupted job %s on startup", job_id)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.ensure()
    _reconcile_interrupted_jobs()
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
    "/api/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Service health",
    response_description="Provider and ffmpeg readiness.",
    include_in_schema=False,
)
def health() -> HealthResponse:
    """Report whether the ElevenLabs key is configured and ffmpeg is available."""
    return HealthResponse(
        status="ok",
        provider_configured=bool(settings.elevenlabs_api_key),
        ffmpeg_available=duration_service.has_ffmpeg(),
    )


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
    return {
        "auth_mode": settings.auth_mode,
        "google_client_id": settings.google_client_id,
        "password_enabled": settings.password_enabled,
        "model_id": settings.elevenlabs_model_id,
        "default_target_seconds": settings.default_target_seconds,
        "default_wpm": settings.default_wpm,
        "max_duration_seconds": settings.max_duration_seconds,
        "contexts": [
            {"id": context, "label": CONTEXT_LABELS[context], "note": CONTEXT_NOTES[context]}
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
    "/api/voices",
    response_model=list[VoiceRecord],
    tags=["Voices"],
    summary="List saved voices",
    response_description="All registry voices that pass the local eligibility filter.",
)
def list_voices(_user: dict = Depends(current_user)) -> list[VoiceRecord]:
    """
    Return the local persistent voice registry.

    This is the source used by the Generate page voice dropdown. Library voices
    are filtered to the supported English conversational accent buckets; manual
    and cloned voices are returned as long as their stored accent is supported.
    """
    return voice_registry.list()


@app.post(
    "/api/voices",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Add/update a voice by id",
    response_description="Saved or updated voice registry record.",
)
def add_voice(request: VoiceCreateRequest, _user: dict = Depends(current_user)) -> VoiceRecord:
    """
    Save a known ElevenLabs voice id into the local registry.

    If `voice_id` already exists locally, the record is updated in place. This
    endpoint does not validate that the provider id can synthesize audio; use it
    when you already know the id is valid or want to test a provider id directly.
    """
    return voice_registry.upsert(request)


@app.delete(
    "/api/voices/{record_id}",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Delete a saved voice",
    response_description="The removed voice record.",
)
def delete_voice(
    record_id: Annotated[str, ApiPath(description="Local VoiceRecord.id to remove.")],
    _user: dict = Depends(current_user),
) -> VoiceRecord:
    """
    Remove one voice from the local registry.

    This only removes the app's saved reference. It does not delete the voice
    from ElevenLabs or remove generated files that used this voice.
    """
    removed = voice_registry.delete(record_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="Voice record not found.")
    return removed


@app.get(
    "/api/voices/{record_id}/preview",
    tags=["Voices"],
    summary="Redirect to a voice preview clip",
    response_class=RedirectResponse,
    responses={
        307: {"description": "Redirect to provider-hosted preview audio."},
        404: {"description": "Voice not found or no preview is available."},
    },
)
async def voice_preview(
    record_id: Annotated[str, ApiPath(description="Local VoiceRecord.id to preview.")],
    _user: dict = Depends(current_user),
) -> RedirectResponse:
    """
    Redirect to the provider preview URL for a saved voice.

    The endpoint first checks cached provider metadata. If no preview is stored,
    it makes a best-effort ElevenLabs lookup by `voice_id`.
    """
    record = next((item for item in voice_registry.list() if item.id == record_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="Voice record not found.")

    metadata = record.provider_metadata or {}
    preview_url = metadata.get("preview_url") or (metadata.get("labels") or {}).get("preview_url")
    if not preview_url:
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


def _save_provider_voice(voice: dict, profile: ProviderVoiceProfile) -> VoiceRecord:
    voice_id = voice.get("voice_id") or voice.get("id")
    name = voice.get("name") or voice_id
    if not voice_id:
        raise HTTPException(status_code=502, detail="ElevenLabs voice did not include a voice_id.")
    return voice_registry.upsert(
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


def _saved_shared_ids() -> set[str]:
    """Workspace voice ids plus the original shared voice ids they were added from."""
    saved: set[str] = set()
    for record in voice_registry.list():
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
    accent_id: str, sort_id: str, page: int, page_size: int
) -> ProviderVoicePage:
    try:
        workspace = await elevenlabs.list_voices()
    except ElevenLabsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    saved_ids = _saved_shared_ids()
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
    "/api/elevenlabs/voices",
    response_model=ProviderVoicePage,
    tags=["Voices"],
    summary="Browse ElevenLabs voices",
    response_description="One normalized page of provider voice options.",
)
async def list_provider_voice_options(
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
    page = max(page, 0)
    page_size = max(1, min(page_size, PROVIDER_PAGE_SIZE_MAX))
    accent_id = accent if accent in PROVIDER_ACCENT_PARAM else "us"
    sort_id = sort if sort in PROVIDER_SORT_MAP else "trending"

    if premade_only:
        return await _premade_voice_page(accent_id, sort_id, page, page_size)

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

    saved_ids = _saved_shared_ids()
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


@app.delete(
    "/api/elevenlabs/voices/cache",
    response_model=CacheClearResponse,
    tags=["Voices"],
    summary="Clear the voice-library cache",
    response_description="Count of in-memory voice-library cache entries removed.",
)
def clear_provider_voice_cache(_user: dict = Depends(current_user)) -> dict:
    """
    Clear cached shared voice-library pages and cached shared voice records.

    Use this when ElevenLabs library results look stale, after changing filters,
    or while debugging provider picker behavior.
    """
    cleared = len(_shared_page_cache) + len(_shared_voice_cache)
    _shared_page_cache.clear()
    _shared_voice_cache.clear()
    return {"ok": True, "cleared": cleared}


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
    "/api/elevenlabs/voices/by-id",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Add a voice by raw id",
    response_description="Saved registry record for the supplied provider id.",
)
async def add_provider_voice_by_id(
    request: ProviderVoiceByIdRequest,
    _user: dict = Depends(current_user),
) -> VoiceRecord:
    """
    Register an arbitrary ElevenLabs voice id.

    The app tries to fetch provider metadata for a friendly name, preview URL,
    and accent. If ElevenLabs does not expose that metadata, the id is still
    saved as a manual voice so it can be used for TTS.
    """
    voice_id = request.voice_id.strip()
    if not voice_id:
        raise HTTPException(status_code=400, detail="A voice id is required.")

    existing = next(
        (
            record
            for record in voice_registry.list()
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

    return voice_registry.upsert(
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
    "/api/elevenlabs/voices/{voice_id}",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Save a picked voice",
    response_description="Saved registry record for the selected provider voice.",
)
async def save_provider_voice_option(
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
    accent_id = request.accent if request.accent in PROVIDER_LIBRARY_ACCENTS else "neutral"
    existing = next(
        (
            record
            for record in voice_registry.list()
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
        return voice_registry.upsert(
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

    return voice_registry.upsert(
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
    "/api/voices/sync",
    response_model=list[VoiceRecord],
    tags=["Voices"],
    summary="Sync eligible workspace voices",
    response_description="Registry records created or updated from eligible workspace voices.",
)
async def sync_provider_voices(_user: dict = Depends(current_user)) -> list[VoiceRecord]:
    """
    Pull eligible voices from the ElevenLabs workspace into the local registry.

    Eligibility is intentionally narrow: English, conversational, and currently
    American or Indian accent only. Existing records are updated by `voice_id`.
    """
    synced: list[VoiceRecord] = []
    for _rank, voice, profile in await _eligible_provider_voices():
        if profile.accent not in PROVIDER_LIBRARY_ACCENTS:
            continue
        synced.append(_save_provider_voice(voice, profile))
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


@app.post(
    "/api/voices/clone",
    response_model=VoiceRecord,
    tags=["Voices"],
    summary="Clone a voice from a sample",
    response_description="Saved registry record for the cloned ElevenLabs voice.",
)
async def clone_voice(
    name: Annotated[str, Form(min_length=1, description="Name for the cloned voice.")],
    accent: Annotated[str, Form(description="Accent bucket to store with the cloned voice.")] = "neutral",
    consent_confirmed: Annotated[
        bool,
        Form(description="Must be true. Confirms the user has permission to clone this voice."),
    ] = False,
    description: Annotated[
        str,
        Form(description="Optional provider description. A safe default is used when empty."),
    ] = "",
    sample: UploadFile = File(..., description="Consented voice sample file, such as mp3, wav, m4a, or webm."),
    _user: dict = Depends(current_user),
) -> VoiceRecord:
    """
    Clone a voice through ElevenLabs and persist it in the local registry.

    This endpoint requires explicit consent confirmation and an ElevenLabs plan
    that supports instant voice cloning. The uploaded sample is stored under the
    app data directory for auditability.
    """
    if not consent_confirmed:
        raise HTTPException(status_code=400, detail="Consent confirmation is required before cloning.")

    record_id = new_id("voice")
    source_path = storage.source_audio_path(record_id, sample.filename or "sample.audio")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(await sample.read())

    try:
        provider_voice = await elevenlabs.clone_voice(
            name=name,
            description=description or "Voice cloned from a consented sample in Voice Message Studio.",
            sample_path=source_path,
            content_type=sample.content_type,
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
        accent=accent,
        consent_status="confirmed",
        source_audio_path=storage.relative_to_data(source_path),
        provider_metadata=provider_voice,
        created_at=timestamp,
        updated_at=timestamp,
    )
    return voice_registry.upsert_record(record)


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
    storage.save_job_manifest(job_id, detail.model_dump(mode="json"))
    return detail


@app.post(
    "/api/tts",
    response_model=AudioResult,
    tags=["Generate"],
    summary="Generate one voice note",
    response_description="Single-row generation result with download URLs when completed.",
)
async def create_tts(request: TtsRequest, _user: dict = Depends(current_user)) -> AudioResult:
    """
    Generate one MP3 voice note and persist it as a job.

    `target_seconds` is a soft warning threshold; generation is still allowed.
    `max_seconds` is the hard LinkedIn-style limit used for red measured-duration
    warnings. Set `export_m4a=true` to also write a mono AAC `.m4a` file.
    """
    job_id = new_id("job")
    created_at = datetime.now(timezone.utc)
    row = await generate_row(job_id, 1, request)
    _save_job_manifest(job_id, "single", created_at, [row])
    return row


def _write_job_progress(
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
    storage.save_job_manifest(job_id, detail.model_dump(mode="json"))


async def run_batch_job(job_id: str, created_at: datetime, requests: list[TtsRequest]) -> None:
    """Background runner: generate rows concurrently and keep the manifest updated."""
    total = len(requests)
    results: dict[int, AudioResult] = {}

    def ordered_rows() -> list[AudioResult]:
        return [results[index] for index in sorted(results)]

    async def run_one(index: int, request: TtsRequest) -> None:
        result = await generate_row(job_id, index, request)
        # No await between mutation and the write, so it is atomic on the event loop.
        results[index] = result
        _write_job_progress(job_id, created_at, status="running", total_rows=total, rows=ordered_rows())

    try:
        await asyncio.gather(*(run_one(i, r) for i, r in enumerate(requests, start=1)))
        rows = ordered_rows()
        workbook_path = storage.job_folder(job_id) / "tts_results.xlsx"
        await asyncio.to_thread(
            workbooks.write_results, workbook_path, [row.model_dump(mode="json") for row in rows]
        )
        _write_job_progress(
            job_id,
            created_at,
            status=_job_status(rows, total),
            total_rows=total,
            rows=rows,
            workbook_url=storage.file_url(workbook_path),
        )
    except Exception as exc:  # finalize as failed rather than leaving the job 'running'
        logger.exception("Batch job %s failed", job_id)
        _write_job_progress(
            job_id, created_at, status="failed", total_rows=total, rows=ordered_rows(), error=str(exc)
        )


@app.post(
    "/api/tts/batch",
    status_code=202,
    response_model=JobSummary,
    tags=["Generate"],
    summary="Submit an .xlsx batch (async)",
    response_description="Accepted job. Poll GET /api/jobs/{job_id} for status, progress, and results.",
)
async def create_batch(
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
    `GET /api/jobs/{job_id}` until `status` is `completed`, `partial`, `failed`, or
    `interrupted`, then download via `GET /api/jobs/{job_id}/download`. CSV is
    rejected because message text may contain commas.
    """
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Upload an .xlsx workbook, not CSV.")

    job_id = new_id("job")
    created_at = datetime.now(timezone.utc)
    source_path = storage.job_folder(job_id) / "source.xlsx"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(await file.read())

    try:
        requests = workbooks.parse_requests(source_path)
    except WorkbookError as exc:
        shutil.rmtree(storage.job_folder(job_id), ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not requests:
        shutil.rmtree(storage.job_folder(job_id), ignore_errors=True)
        raise HTTPException(status_code=400, detail="The workbook has no data rows.")
    if len(requests) > settings.max_batch_rows:
        shutil.rmtree(storage.job_folder(job_id), ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail=(
                f"This batch has {len(requests)} rows, above the limit of "
                f"{settings.max_batch_rows}. Split it into smaller workbooks."
            ),
        )

    total = len(requests)
    _write_job_progress(job_id, created_at, status="running", total_rows=total, rows=[])

    task = asyncio.create_task(run_batch_job(job_id, created_at, requests))
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
    "/api/jobs",
    response_model=list[JobSummary],
    tags=["History"],
    summary="List generation jobs",
    response_description="Jobs sorted newest first.",
)
def list_jobs(_user: dict = Depends(current_user)) -> list[JobSummary]:
    """List persisted single and batch generation jobs from the data directory."""
    summaries: list[JobSummary] = []
    for job_id in storage.list_job_ids():
        manifest = storage.read_job_manifest(job_id)
        if not manifest:
            continue
        summaries.append(JobSummary.model_validate(manifest))
    return sorted(summaries, key=lambda summary: summary.created_at, reverse=True)


@app.get(
    "/api/jobs/{job_id}/download",
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
    job_id: Annotated[str, ApiPath(description="Job id returned by /api/tts or /api/tts/batch.")],
    _user: dict = Depends(current_user),
) -> Response:
    """
    Build and return a ZIP archive for a job.

    Each row can include transcript text, MP3, and M4A. If an M4A is missing but
    the MP3 exists, the endpoint attempts to create the M4A before zipping.
    """
    manifest = storage.read_job_manifest(job_id)
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

            transcript_path = storage.job_row_path(job_id, index, "txt")
            if transcript_path.exists():
                archive.write(transcript_path, f"{stem}.txt")
            elif row.text:
                archive.writestr(f"{stem}.txt", row.text)

            mp3_path = storage.job_row_path(job_id, index, "mp3")
            if not mp3_path.exists():
                continue
            archive.write(mp3_path, f"{stem}.mp3")

            m4a_path = storage.job_row_path(job_id, index, "m4a")
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
    "/api/jobs/{job_id}",
    response_model=JobDetail,
    tags=["History"],
    summary="Get one job with rows",
    response_description="Full job manifest with row-level results.",
)
def get_job(
    job_id: Annotated[str, ApiPath(description="Job id returned by /api/tts or /api/tts/batch.")],
    _user: dict = Depends(current_user),
) -> JobDetail:
    """Return one persisted job manifest including all row results."""
    manifest = storage.read_job_manifest(job_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobDetail.model_validate(manifest)


@app.get(
    "/files/{relative_path:path}",
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
    relative_path: Annotated[str, ApiPath(description="Path relative to DATA_DIR, as returned in result URLs.")],
    _user: dict = Depends(current_user),
) -> FileResponse:
    """
    Download a generated audio, transcript, workbook, source, or metadata file.

    The path is resolved strictly under `DATA_DIR`; attempts to escape the data
    directory are rejected.
    """
    try:
        path = storage.resolve_file(relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)


async def generate_row(job_id: str, index: int, request: TtsRequest) -> AudioResult:
    created_at = datetime.now(timezone.utc)
    estimated_seconds = duration_service.estimate_seconds(request.text, request.wpm)
    max_seconds = settings.max_duration_seconds

    # Bound concurrent generation, and run blocking ffmpeg/ffprobe off the event loop.
    async with _generation_semaphore:
        try:
            mp3_bytes = await elevenlabs.text_to_speech(
                voice_id=request.voice_id,
                text=request.text,
                speech_context=request.speech_context,
            )
            mp3_path = storage.job_row_path(job_id, index, "mp3")
            mp3_path.parent.mkdir(parents=True, exist_ok=True)
            mp3_path.write_bytes(mp3_bytes)

            transcript_path = storage.job_row_path(job_id, index, "txt")
            transcript_path.write_text(request.text, encoding="utf-8")

            actual_seconds = await asyncio.to_thread(duration_service.measure_seconds, mp3_path)
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
                m4a_path = storage.job_row_path(job_id, index, "m4a")
                await asyncio.to_thread(
                    audio_export_service.export_linkedin_m4a, mp3_path, m4a_path
                )
                m4a_url = storage.file_url(m4a_path)

            result = AudioResult(
                job_id=job_id,
                index=index,
                status="completed",
                text=request.text,
                voice_id=request.voice_id,
                voice_name=request.voice_name,
                model_id=settings.elevenlabs_model_id,
                speech_context=request.speech_context,
                accent=request.accent,
                estimated_seconds=estimated_seconds,
                target_seconds=request.target_seconds,
                max_seconds=max_seconds,
                actual_seconds=actual_seconds,
                warning=warning,
                mp3_url=storage.file_url(mp3_path),
                m4a_url=m4a_url,
                transcript_url=storage.file_url(transcript_path),
                created_at=created_at,
            )
            return result
        except (ElevenLabsError, subprocess.CalledProcessError, ValidationError, OSError, ValueError) as exc:
            logger.warning("Generation failed for job %s row %s: %s", job_id, index, exc)
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
            result = AudioResult(
                job_id=job_id,
                index=index,
                status="failed",
                text=request.text,
                voice_id=request.voice_id,
                voice_name=request.voice_name,
                model_id=settings.elevenlabs_model_id,
                speech_context=request.speech_context,
                accent=request.accent,
                estimated_seconds=estimated_seconds,
                target_seconds=request.target_seconds,
                max_seconds=max_seconds,
                warning=warning,
                error=str(exc),
                created_at=created_at,
            )

    return result

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
