"""MCP server for Voice Message Studio.

Exposes the studio's text-to-speech workflow as MCP tools so agents (Claude Code
CLI + web app, Codex) can generate LinkedIn-style voice notes directly. The
server is served over streamable-HTTP and mounted onto the studio's FastAPI app
at ``/mcp`` (see ``main.py``); there is no standalone/stdio distribution.

The tools call the same in-process helpers the REST routes use (``generate_row``,
the per-provider storage/registry singletons), so a job created here is
identical to one created from the browser. Client requests are authenticated by
OAuth (see ``mcp_auth.py``); the tools do not need the studio's ``X-API-Key``.

To avoid a circular import (``main`` imports this module at startup to mount the
routes), the tools import ``app.main`` lazily, inside each function body.
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.mcp_auth import build_auth

# Build the FastMCP instance with OAuth enabled. ``build_auth`` returns the
# provider + AuthSettings (or (None, None) when auth is disabled for local
# testing via MCP_DISABLE_AUTH=1).
_auth_provider, _auth_settings = build_auth()
mcp = FastMCP(
    "voicestudio",
    instructions=(
        "Generate LinkedIn-style voice notes from text. List saved voices with "
        "list_voices and delivery styles with list_speech_contexts, then call "
        "generate_voice_note to synthesize one message and get its audio. Browse "
        "past runs with list_jobs / get_job and copy their files to disk with "
        "save_job_audio. Providers are 'elevenlabs' (default) and 'omnivoice'."
    ),
    auth_server_provider=_auth_provider,
    auth=_auth_settings,
    # This server is public, OAuth-protected, and sits behind a trusted reverse
    # proxy that terminates TLS and forwards over HTTP to 127.0.0.1. FastMCP
    # would otherwise auto-enable DNS-rebinding protection (because the default
    # bind host is loopback) and reject legitimate clients like claude.ai with a
    # 421 Misdirected Request. That protection targets localhost dev servers and
    # ambient-cookie auth; it does not apply to a bearer-token API, so disable it.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _current_user() -> dict[str, str]:
    """Identity for job attribution, derived from the OAuth access token.

    Jobs are stored per provider on disk (not per user), so attribution is
    cosmetic; we still record who created the job when a token carries an email.
    """
    token = get_access_token()
    if token is None:
        return {"sub": "mcp", "email": "mcp", "name": "MCP", "picture": ""}
    email = getattr(token, "user_email", None) or f"{token.client_id}"
    sub = getattr(token, "user_sub", None) or f"mcp:{token.client_id}"
    return {"sub": sub, "email": email, "name": email, "picture": ""}


def _clean(message: HTTPException) -> ValueError:
    """Translate an HTTPException into a plain, agent-readable error."""
    return ValueError(str(message.detail))


def _row_view(row: Any, storage: Any) -> dict[str, Any]:
    """Trim an ``AudioResult`` to the fields agents want, plus local file paths."""
    view: dict[str, Any] = {
        "index": row.index,
        "status": row.status,
        "text": row.text,
        "spoken_text": row.spoken_text,
        "voice_id": row.voice_id,
        "voice_name": row.voice_name,
        "model_id": row.model_id,
        "speech_context": row.speech_context,
        "estimated_seconds": row.estimated_seconds,
        "actual_seconds": row.actual_seconds,
        "warning": row.warning.message if row.warning else None,
        "error": row.error,
        "mp3_url": row.mp3_url,
        "m4a_url": row.m4a_url,
    }
    if row.status == "completed" and row.index is not None:
        mp3_path = storage.job_row_path(row.job_id, row.index, "mp3")
        m4a_path = storage.job_row_path(row.job_id, row.index, "m4a")
        view["mp3_path"] = str(mp3_path) if mp3_path.exists() else None
        view["m4a_path"] = str(m4a_path) if m4a_path.exists() else None
    return view


def _job_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Compact view of a job manifest (no per-row rows)."""
    return {
        "job_id": manifest.get("job_id"),
        "kind": manifest.get("kind"),
        "status": manifest.get("status"),
        "created_at": manifest.get("created_at"),
        "total_rows": manifest.get("total_rows"),
        "completed_rows": manifest.get("completed_rows"),
        "failed_rows": manifest.get("failed_rows"),
    }


@mcp.tool()
def list_voices(provider: str = "elevenlabs") -> dict[str, Any]:
    """List the voices saved in the local registry for a provider.

    These are the voices the ``voice_id`` argument of ``generate_voice_note``
    accepts. Each entry has ``voice_id``, ``display_name``, ``accent``, and
    ``source_type`` (e.g. cloned / preset / library).

    Args:
        provider: ``elevenlabs`` (default) or ``omnivoice``.
    """
    from app import main

    try:
        provider = main.validate_provider(provider)
    except HTTPException as exc:
        raise _clean(exc) from exc
    voices = main.registry_for(provider).list()
    return {
        "provider": provider,
        "voices": [
            {
                "voice_id": v.voice_id,
                "display_name": v.display_name,
                "accent": v.accent,
                "source_type": v.source_type,
            }
            for v in voices
        ],
    }


@mcp.tool()
def list_speech_contexts(provider: str = "elevenlabs") -> dict[str, Any]:
    """List the speech (delivery) contexts available for a provider.

    ElevenLabs contexts are built-in delivery styles (id + label + note).
    OmniVoice contexts are saved voice-design presets; the id is required by
    ``generate_voice_note`` for OmniVoice.

    Args:
        provider: ``elevenlabs`` (default) or ``omnivoice``.
    """
    from app import main
    from app.services.speech_context import CONTEXT_LABELS, CONTEXT_NOTES

    try:
        provider = main.validate_provider(provider)
    except HTTPException as exc:
        raise _clean(exc) from exc

    if provider == "omnivoice":
        contexts = [
            {"id": ctx.get("id"), "label": ctx.get("label") or ctx.get("id")}
            for ctx in main._load_omnivoice_contexts()
        ]
        return {"provider": provider, "contexts": contexts}

    contexts = [
        {"id": ctx_id, "label": CONTEXT_LABELS[ctx_id], "note": CONTEXT_NOTES[ctx_id]}
        for ctx_id in CONTEXT_LABELS
    ]
    return {"provider": provider, "contexts": contexts}


@mcp.tool()
async def generate_voice_note(
    text: str,
    voice_id: str,
    provider: str = "elevenlabs",
    speech_context: str = "outreach_conversational",
    enhance_text: bool = False,
    target_seconds: int = 55,
    wpm: int = 135,
    export_m4a: bool = True,
) -> dict[str, Any]:
    """Generate one voice note from text and return the result plus file paths.

    Creates a single-row job, synthesizes the audio, persists it, and returns a
    trimmed result. A failed generation is returned with ``status="failed"`` and
    an ``error`` message rather than raising, so check ``status``. When the audio
    is on disk, ``mp3_path`` / ``m4a_path`` point at the files under DATA_DIR;
    ``mp3_url`` / ``m4a_url`` are the authenticated browser download URLs.

    Args:
        text: The message to synthesize (kept short — this targets ~55s notes).
        voice_id: A voice id from ``list_voices``. ElevenLabs: the provider voice
            id. OmniVoice: a saved preset or cloned/sample voice id.
        provider: ``elevenlabs`` (default) or ``omnivoice``.
        speech_context: Delivery style. ElevenLabs: an optional built-in context
            (default ``outreach_conversational``). OmniVoice: a **required** saved
            speech-context id from ``list_speech_contexts`` (e.g. ``english_american``).
        enhance_text: ElevenLabs only — rewrite the text into spoken form and add
            Eleven v3 audio tags before generation (needs OPENROUTER_API_KEY;
            falls back to the original text when unavailable).
        target_seconds: Soft target duration for the yellow-warning check (1–60).
        wpm: Words-per-minute estimate used before generation (60–240).
        export_m4a: Also export a LinkedIn-compatible mono AAC ``.m4a`` (default true).
    """
    from app import main
    from app.models import TtsRequest
    from app.services.omnivoice_text_rules import OmniVoiceTextRuleError
    from app.services.storage import new_id, now_utc

    try:
        provider = main.validate_provider(provider)
    except HTTPException as exc:
        raise _clean(exc) from exc

    try:
        tts_request = TtsRequest(
            text=text,
            voice_id=voice_id,
            speech_context=speech_context,
            enhance_text=enhance_text,
            target_seconds=target_seconds,
            wpm=wpm,
            export_m4a=export_m4a,
        )
    except Exception as exc:  # pydantic validation
        raise ValueError(f"Invalid request: {exc}") from exc

    if provider == "omnivoice":
        try:
            main.require_omnivoice_text_ready(tts_request.text)
        except OmniVoiceTextRuleError as exc:
            raise ValueError(str(exc)) from exc

    provider_storage = main.storage_for(provider)
    job_id = new_id("job")
    created_at = now_utc()
    row = await main.generate_row(provider, job_id, 1, tts_request)
    main._save_job_manifest(provider_storage, job_id, "single", created_at, [row])

    result = _row_view(row, provider_storage)
    result["provider"] = provider
    result["job_id"] = job_id
    return result


@mcp.tool()
def list_jobs(provider: str = "elevenlabs", limit: int = 50) -> dict[str, Any]:
    """List past generation jobs for a provider, newest first.

    Args:
        provider: ``elevenlabs`` (default) or ``omnivoice``.
        limit: Max jobs to return, clamped to 1–200.
    """
    from app import main

    try:
        provider = main.validate_provider(provider)
    except HTTPException as exc:
        raise _clean(exc) from exc
    limit = min(max(limit, 1), 200)
    provider_storage = main.storage_for(provider)
    manifests = []
    for job_id in provider_storage.list_job_ids():
        manifest = provider_storage.read_job_manifest(job_id)
        if manifest:
            manifests.append(manifest)
    manifests.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return {
        "provider": provider,
        "total": len(manifests),
        "jobs": [_job_summary(m) for m in manifests[:limit]],
    }


@mcp.tool()
def get_job(job_id: str, provider: str = "elevenlabs") -> dict[str, Any]:
    """Get one job with its per-row results and local audio file paths.

    Args:
        job_id: A job id from ``generate_voice_note`` or ``list_jobs``.
        provider: ``elevenlabs`` (default) or ``omnivoice``.
    """
    from app import main
    from app.models import JobDetail

    try:
        provider = main.validate_provider(provider)
    except HTTPException as exc:
        raise _clean(exc) from exc
    provider_storage = main.storage_for(provider)
    manifest = provider_storage.read_job_manifest(job_id)
    if not manifest:
        raise ValueError("Job not found.")
    detail = JobDetail.model_validate(manifest)
    summary = _job_summary(manifest)
    summary["provider"] = provider
    summary["error"] = detail.error
    summary["workbook_url"] = detail.workbook_url
    summary["rows"] = [_row_view(row, provider_storage) for row in detail.rows]
    return summary


@mcp.tool()
def save_job_audio(job_id: str, out_dir: str, provider: str = "elevenlabs") -> dict[str, Any]:
    """Copy a job's generated audio (MP3 + M4A + transcript) into a directory.

    Writes ``row-NNN-<voice>.{mp3,m4a,txt}`` files into ``out_dir`` and returns
    the list of paths written. Use this to pull the audio out of DATA_DIR to a
    location the user asked for.

    Args:
        job_id: A job id from ``generate_voice_note`` or ``list_jobs``.
        out_dir: Absolute path to a directory to write the files into (created if
            missing).
        provider: ``elevenlabs`` (default) or ``omnivoice``.
    """
    from app import main
    from app.models import JobDetail
    from app.services.storage import safe_filename

    try:
        provider = main.validate_provider(provider)
    except HTTPException as exc:
        raise _clean(exc) from exc
    provider_storage = main.storage_for(provider)
    manifest = provider_storage.read_job_manifest(job_id)
    if not manifest:
        raise ValueError("Job not found.")
    detail = JobDetail.model_validate(manifest)

    target = Path(out_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Could not create out_dir: {exc}") from exc

    written: list[str] = []
    for row in detail.rows:
        index = row.index or 0
        base = f"row-{index:03d}"
        label = safe_filename(row.voice_name or row.voice_id or base)
        stem = f"{base}-{label}"
        for ext in ("mp3", "m4a", "txt"):
            src = provider_storage.job_row_path(job_id, index, ext)
            if src.exists():
                dest = target / f"{stem}.{ext}"
                shutil.copy2(src, dest)
                written.append(str(dest))
    return {"job_id": job_id, "provider": provider, "files": written, "count": len(written)}


@mcp.tool()
def get_job_audio(
    job_id: str,
    index: int = 1,
    fmt: str = "mp3",
    provider: str = "elevenlabs",
) -> dict[str, Any]:
    """Return one generated audio file as base64, over the MCP connection.

    Use this to pull the audio bytes to wherever the agent runs (the ``mp3_url``
    / ``mp3_path`` in other tools point at the server, not the caller). Decode
    ``audio_b64`` and write it to a ``.mp3`` / ``.m4a`` file. For a batch job,
    fetch rows one at a time via ``index`` (base64 audio is large).

    Args:
        job_id: A job id from ``generate_voice_note``, ``generate_batch``, or
            ``list_jobs``.
        index: 1-based row index within the job (default 1; single-note jobs
            only have row 1).
        fmt: ``mp3`` (default) or ``m4a`` (LinkedIn-ready mono AAC).
        provider: ``elevenlabs`` (default) or ``omnivoice``.
    """
    from app import main

    try:
        provider = main.validate_provider(provider)
    except HTTPException as exc:
        raise _clean(exc) from exc
    fmt = fmt.lower().lstrip(".")
    if fmt not in {"mp3", "m4a"}:
        raise ValueError("fmt must be 'mp3' or 'm4a'.")
    provider_storage = main.storage_for(provider)
    if provider_storage.read_job_manifest(job_id) is None:
        raise ValueError("Job not found.")
    path = provider_storage.job_row_path(job_id, index, fmt)
    if not path.exists():
        raise ValueError(
            f"No {fmt} file for row {index} of {job_id} (row may have failed, or the "
            f"job is still running — poll get_job first)."
        )
    data = path.read_bytes()
    return {
        "job_id": job_id,
        "provider": provider,
        "index": index,
        "format": fmt,
        "filename": f"{job_id}-row-{index:03d}.{fmt}",
        "bytes": len(data),
        "audio_b64": base64.b64encode(data).decode("ascii"),
    }


@mcp.tool()
async def generate_batch(
    items: list[dict[str, Any]],
    provider: str = "elevenlabs",
) -> dict[str, Any]:
    """Submit many voice notes as one async job, then poll get_job for results.

    Returns immediately with a ``job_id`` and ``status="running"``; generation
    runs in the background (bounded by the server's concurrency limit). Poll
    ``get_job(job_id)`` until ``status`` is ``completed`` / ``partial`` /
    ``failed``, then pull audio with ``get_job_audio`` or ``save_job_audio``.
    This mirrors the async submit-and-poll pattern for bulk work rather than
    blocking one long call.

    Args:
        items: One dict per note. Required keys: ``text``, ``voice_id``.
            Optional: ``voice_name``, ``accent``, ``speech_context``,
            ``enhance_text``, ``target_seconds``, ``wpm``, ``export_m4a`` —
            same fields as ``generate_voice_note``. For OmniVoice,
            ``speech_context`` is required per item.
        provider: ``elevenlabs`` (default) or ``omnivoice``.
    """
    import asyncio
    from datetime import datetime, timezone

    from app import main
    from app.models import TtsRequest
    from app.services.omnivoice_text_rules import OmniVoiceTextRuleError
    from app.services.storage import new_id

    try:
        provider = main.validate_provider(provider)
    except HTTPException as exc:
        raise _clean(exc) from exc

    if not items:
        raise ValueError("Provide at least one item.")
    if len(items) > main.settings.max_batch_rows:
        raise ValueError(
            f"This batch has {len(items)} rows, above the limit of "
            f"{main.settings.max_batch_rows}. Split it into smaller batches."
        )

    requests: list[TtsRequest] = []
    for i, item in enumerate(items, start=1):
        try:
            requests.append(TtsRequest.model_validate(item))
        except Exception as exc:  # pydantic validation
            raise ValueError(f"Item {i} is invalid: {exc}") from exc

    if provider == "omnivoice":
        rule_errors = []
        for i, request in enumerate(requests, start=1):
            try:
                main.require_omnivoice_text_ready(request.text)
            except OmniVoiceTextRuleError as exc:
                rule_errors.append(f"Item {i}: {exc}")
        if rule_errors:
            preview = " | ".join(rule_errors[:10])
            if len(rule_errors) > 10:
                preview += f" | {len(rule_errors) - 10} more invalid item(s)."
            raise ValueError(f"OmniVoice text rules failed. {preview}")

    provider_storage = main.storage_for(provider)
    job_id = new_id("job")
    created_at = datetime.now(timezone.utc)
    total = len(requests)
    main._write_job_progress(provider_storage, job_id, created_at, status="running", total_rows=total, rows=[])

    task = asyncio.create_task(main.run_batch_job(provider, job_id, created_at, requests))
    main._background_tasks.add(task)
    task.add_done_callback(main._background_tasks.discard)

    return {
        "job_id": job_id,
        "provider": provider,
        "status": "running",
        "total_rows": total,
        "poll": "Call get_job(job_id) until status is completed / partial / failed.",
    }
