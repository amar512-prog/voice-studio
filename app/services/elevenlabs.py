from __future__ import annotations

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.services.speech_context import DELIVERY_TAGS_BY_CONTEXT, resolve_voice_settings


class ElevenLabsError(RuntimeError):
    pass


class ElevenLabsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _require_key(self) -> str:
        if not self.settings.elevenlabs_api_key:
            raise ElevenLabsError("ELEVENLABS_API_KEY is not configured.")
        return self.settings.elevenlabs_api_key

    async def text_to_speech(
        self,
        voice_id: str,
        text: str,
        speech_context: str,
        voice_settings: dict[str, float | bool] | None = None,
        language_code: str | None = None,
        apply_delivery_tag: bool = True,
    ) -> bytes:
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url}/text-to-speech/{voice_id}"
        # Callers pass the fully resolved settings (saved context + overrides);
        # the built-in context preset is only a fallback when nothing is passed.
        voice_settings = dict(voice_settings) if voice_settings else resolve_voice_settings(speech_context)
        payload = {
            # Enhanced text arrives with its own audio tags, so the per-context
            # leading delivery tag is skipped for it.
            "text": self._prepare_text(text, speech_context) if apply_delivery_tag else text.strip(),
            "model_id": self.settings.elevenlabs_model_id,
            "language_code": language_code or self.settings.elevenlabs_language_code,
            "voice_settings": voice_settings,
        }
        headers = {
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        params = {"output_format": "mp3_44100_128"}

        # Retry transient failures: transport errors (connection blips/timeouts),
        # 429 (ElevenLabs concurrency/rate limit), and 5xx (system busy). Other 4xx
        # (bad voice, plan limit, quota) are real errors and are surfaced at once.
        max_attempts = 4
        for attempt in range(max_attempts):
            last_attempt = attempt == max_attempts - 1
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(url, headers=headers, params=params, json=payload)
            except httpx.HTTPError as exc:
                if last_attempt:
                    raise ElevenLabsError(
                        f"Could not reach ElevenLabs after {max_attempts} attempts: "
                        f"{exc!s} ({type(exc).__name__})."
                    ) from exc
                await asyncio.sleep(self._backoff_seconds(None, attempt))
                continue

            if response.status_code in self.RETRYABLE_STATUS and not last_attempt:
                await asyncio.sleep(self._backoff_seconds(response, attempt))
                continue
            if response.status_code >= 400:
                raise ElevenLabsError(self._provider_error(response))
            return response.content
        raise ElevenLabsError("Could not reach ElevenLabs.")

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def _backoff_seconds(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(float(retry_after), 30.0)
                except ValueError:
                    pass
        return min(1.5 * (2**attempt), 30.0)

    def _prepare_text(self, text: str, speech_context: str) -> str:
        clean_text = text.strip()
        if self.settings.elevenlabs_model_id != "eleven_v3" or clean_text.startswith("["):
            return clean_text
        tag = DELIVERY_TAGS_BY_CONTEXT.get(speech_context, DELIVERY_TAGS_BY_CONTEXT["outreach_conversational"])
        return f"{tag} {clean_text}"

    async def list_voices(self) -> list[dict[str, Any]]:
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url.replace('/v1', '/v2')}/voices"
        headers = {"xi-api-key": api_key}
        voices: list[dict[str, Any]] = []
        next_page_token: str | None = None
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                while True:
                    params: dict[str, str | int | bool] = {
                        "page_size": 100,
                        "include_total_count": True,
                    }
                    if next_page_token:
                        params["next_page_token"] = next_page_token
                    response = await client.get(url, headers=headers, params=params)
                    if response.status_code >= 400:
                        raise ElevenLabsError(self._provider_error(response))
                    data = response.json()
                    voices.extend(data.get("voices", []))
                    if not data.get("has_more"):
                        break
                    next_page_token = data.get("next_page_token")
                    if not next_page_token:
                        break
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"Could not reach ElevenLabs: {exc!s} ({type(exc).__name__}).") from exc
        return voices

    async def list_shared_voices(
        self,
        *,
        page: int,
        page_size: int,
        sort: str,
        language: str | None = None,
        accent: str | None = None,
        use_cases: list[str] | None = None,
    ) -> dict[str, Any]:
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url}/shared-voices"
        headers = {"xi-api-key": api_key}
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "sort": sort,
        }
        if language:
            params["language"] = language
        if accent:
            params["accent"] = accent
        if use_cases:
            params["use_cases"] = use_cases
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"Could not reach ElevenLabs: {exc!s} ({type(exc).__name__}).") from exc
        if response.status_code >= 400:
            raise ElevenLabsError(self._provider_error(response))
        return response.json()

    async def get_voice(self, voice_id: str) -> dict[str, Any]:
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url}/voices/{voice_id}"
        headers = {"xi-api-key": api_key}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"Could not reach ElevenLabs: {exc!s} ({type(exc).__name__}).") from exc
        if response.status_code >= 400:
            raise ElevenLabsError(self._provider_error(response))
        return response.json()

    async def delete_voice(self, voice_id: str) -> bool:
        """Delete a voice from the ElevenLabs account.

        Returns True when the voice was deleted and False when it did not exist
        upstream (already removed); raises ElevenLabsError for other failures.
        """
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url}/voices/{voice_id}"
        headers = {"xi-api-key": api_key}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.delete(url, headers=headers)
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"Could not reach ElevenLabs: {exc!s} ({type(exc).__name__}).") from exc
        if response.status_code >= 400:
            if response.status_code == 404 or "voice_does_not_exist" in response.text:
                return False
            raise ElevenLabsError(self._provider_error(response))
        return True

    async def add_shared_voice(self, public_owner_id: str, voice_id: str, new_name: str) -> dict[str, Any]:
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url}/voices/add/{public_owner_id}/{voice_id}"
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(url, headers=headers, json={"new_name": new_name})
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"Could not reach ElevenLabs: {exc!s} ({type(exc).__name__}).") from exc
        if response.status_code >= 400:
            raise ElevenLabsError(self._provider_error(response))
        return response.json()

    async def clone_voice(
        self,
        name: str,
        description: str,
        sample_files: list[tuple[Path, str | None]],
        labels: dict[str, str],
        remove_background_noise: bool,
    ) -> dict[str, Any]:
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url}/voices/add"
        headers = {"xi-api-key": api_key}
        data = {
            "name": name,
            "description": description,
            "labels": json.dumps(labels),
            "remove_background_noise": str(remove_background_noise).lower(),
        }
        try:
            with ExitStack() as stack:
                files = [
                    (
                        "files",
                        (
                            sample_path.name,
                            stack.enter_context(sample_path.open("rb")),
                            content_type or "application/octet-stream",
                        ),
                    )
                    for sample_path, content_type in sample_files
                ]
                async with httpx.AsyncClient(timeout=180) as client:
                    response = await client.post(url, headers=headers, data=data, files=files)
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"Could not reach ElevenLabs: {exc!s} ({type(exc).__name__}).") from exc
        if response.status_code >= 400:
            raise ElevenLabsError(self._provider_error(response))
        return response.json()

    def _provider_error(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            body = response.text[:500]
        if isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, dict):
                if detail.get("status") == "can_not_use_instant_voice_cloning":
                    return (
                        "Instant voice cloning requires a paid ElevenLabs plan. "
                        "Your current subscription does not include it."
                    )
                message = detail.get("message")
                if isinstance(message, str) and message:
                    return message
        return f"ElevenLabs error {response.status_code}: {body}"
