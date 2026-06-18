from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx

from app.config import Settings


class OmniVoiceError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class OmniVoiceClient:
    """Client for the Hugging Face-hosted OmniVoice Gradio batch API."""

    # ZeroGPU spaces can be cold/queued/throttled; these statuses are transient.
    RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
    MAX_ATTEMPTS = 4

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.settings.huggingface_token:
            headers["Authorization"] = f"Bearer {self.settings.huggingface_token}"
        return headers

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(30.0, connect=10.0, read=float(self.settings.omnivoice_timeout_seconds))

    def _batch_submit_url(self) -> str:
        return f"{self.settings.omnivoice_base_url}/gradio_api/call/batch"

    def _info_url(self) -> str:
        return f"{self.settings.omnivoice_base_url}/gradio_api/info"

    async def get_api_info(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                response = await client.get(self._info_url(), headers=self._headers())
        except httpx.HTTPError as exc:
            raise OmniVoiceError(
                f"Could not reach OmniVoice: {exc!s} ({type(exc).__name__}).", retryable=True
            ) from exc
        if response.status_code >= 400:
            raise OmniVoiceError(
                self._provider_error(response),
                retryable=response.status_code in self.RETRYABLE_STATUS,
            )
        return response.json()

    async def run_batch(self, payload: dict[str, Any] | str) -> dict[str, Any]:
        payload_str = payload if isinstance(payload, str) else json.dumps(payload)
        # Each attempt resubmits (event ids are single-use), so retrying transient
        # failures from a cold/queued ZeroGPU space is safe.
        for attempt in range(self.MAX_ATTEMPTS):
            last_attempt = attempt == self.MAX_ATTEMPTS - 1
            try:
                event_id = await self._submit_batch(payload_str)
                return await self._read_batch_result(event_id)
            except OmniVoiceError as exc:
                if not exc.retryable or last_attempt:
                    raise
                await asyncio.sleep(min(2.0 * (2**attempt), 30.0))
        raise OmniVoiceError("OmniVoice retries exhausted.")

    async def synthesize_design(
        self,
        *,
        text: str,
        instruct: str,
        language: str | None = None,
        audio_format: str = "wav",
    ) -> dict[str, Any]:
        item = {"text": text, "instruct": instruct}
        if language:
            item["language"] = language
        return await self.run_batch({"items": [item], "audio_format": audio_format})

    async def synthesize_clone(
        self,
        *,
        text: str,
        reference_audio: bytes,
        reference_text: str | None = None,
        audio_format: str = "wav",
    ) -> dict[str, Any]:
        item = {
            "text": text,
            "ref_audio_b64": base64.b64encode(reference_audio).decode("ascii"),
        }
        if reference_text:
            item["ref_text"] = reference_text
        return await self.run_batch({"items": [item], "audio_format": audio_format})

    async def synthesize_auto(
        self,
        *,
        text: str,
        language: str | None = "en",
        audio_format: str = "wav",
    ) -> dict[str, Any]:
        item = {"text": text}
        if language:
            item["language"] = language
        return await self.run_batch({"items": [item], "audio_format": audio_format})

    async def _submit_batch(self, payload_str: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                response = await client.post(
                    self._batch_submit_url(),
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json={"data": [payload_str]},
                )
        except httpx.HTTPError as exc:
            raise OmniVoiceError(
                f"Could not reach OmniVoice: {exc!s} ({type(exc).__name__}).", retryable=True
            ) from exc
        if response.status_code >= 400:
            raise OmniVoiceError(
                self._provider_error(response),
                retryable=response.status_code in self.RETRYABLE_STATUS,
            )
        event_id = response.json().get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise OmniVoiceError("OmniVoice did not return a Gradio event_id.")
        return event_id

    async def _read_batch_result(self, event_id: str) -> dict[str, Any]:
        url = f"{self._batch_submit_url()}/{event_id}"
        current_event = ""
        data_lines: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                async with client.stream("GET", url, headers=self._headers()) as response:
                    if response.status_code >= 400:
                        raise OmniVoiceError(
                            self._provider_error(response),
                            retryable=response.status_code in self.RETRYABLE_STATUS,
                        )
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            current_event = line.split(":", 1)[1].strip()
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line.split(":", 1)[1].strip())
                            continue
                        if line == "":
                            parsed = self._decode_event(current_event, data_lines)
                            if parsed is not None:
                                return parsed
                            current_event = ""
                            data_lines = []
        except httpx.HTTPError as exc:
            raise OmniVoiceError(
                f"Could not reach OmniVoice: {exc!s} ({type(exc).__name__}).", retryable=True
            ) from exc

        parsed = self._decode_event(current_event, data_lines)
        if parsed is not None:
            return parsed
        raise OmniVoiceError("OmniVoice stream closed before a completed result arrived.")

    def _decode_event(self, event_name: str, data_lines: list[str]) -> dict[str, Any] | None:
        if not data_lines:
            return None
        data = "\n".join(data_lines)
        if event_name == "complete":
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise OmniVoiceError("OmniVoice returned invalid JSON in the complete event.") from exc
            if isinstance(payload, list) and payload:
                payload = payload[0]
            if not isinstance(payload, dict):
                raise OmniVoiceError("OmniVoice returned an unexpected complete payload.")
            if payload.get("error"):
                raise OmniVoiceError(str(payload["error"]))
            return payload
        if event_name == "error":
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = data
            raise OmniVoiceError(f"OmniVoice returned an error event: {payload}")
        return None

    def _provider_error(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            body = response.text[:500]
        return f"OmniVoice error {response.status_code}: {body}"
