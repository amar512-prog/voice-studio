from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.models import SpeechContext
from app.services.speech_context import DELIVERY_TAGS_BY_CONTEXT, VOICE_SETTINGS_BY_CONTEXT


class ElevenLabsError(RuntimeError):
    pass


class ElevenLabsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _require_key(self) -> str:
        if not self.settings.elevenlabs_api_key:
            raise ElevenLabsError("ELEVENLABS_API_KEY is not configured.")
        return self.settings.elevenlabs_api_key

    async def text_to_speech(self, voice_id: str, text: str, speech_context: SpeechContext) -> bytes:
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url}/text-to-speech/{voice_id}"
        payload = {
            "text": self._prepare_text(text, speech_context),
            "model_id": self.settings.elevenlabs_model_id,
            "language_code": self.settings.elevenlabs_language_code,
            "voice_settings": VOICE_SETTINGS_BY_CONTEXT[speech_context],
        }
        headers = {
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        params = {"output_format": "mp3_44100_128"}

        # Retry transient transport errors (connection blips, timeouts); a 4xx/5xx
        # status is a real API error and is surfaced without retrying.
        last_error: httpx.HTTPError | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(url, headers=headers, params=params, json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise ElevenLabsError(
                    f"Could not reach ElevenLabs after 3 attempts: {last_error!s} "
                    f"({type(last_error).__name__})."
                ) from last_error
            if response.status_code >= 400:
                raise ElevenLabsError(self._provider_error(response))
            return response.content
        raise ElevenLabsError("Could not reach ElevenLabs.")

    def _prepare_text(self, text: str, speech_context: SpeechContext) -> str:
        clean_text = text.strip()
        if self.settings.elevenlabs_model_id != "eleven_v3" or clean_text.startswith("["):
            return clean_text
        return f"{DELIVERY_TAGS_BY_CONTEXT[speech_context]} {clean_text}"

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
        sample_path: Path,
        content_type: str | None,
    ) -> dict[str, Any]:
        api_key = self._require_key()
        url = f"{self.settings.elevenlabs_base_url}/voices/add"
        headers = {"xi-api-key": api_key}
        data = {
            "name": name,
            "description": description,
            "remove_background_noise": "true",
        }
        try:
            with sample_path.open("rb") as handle:
                files = {"files": (sample_path.name, handle, content_type or "application/octet-stream")}
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
