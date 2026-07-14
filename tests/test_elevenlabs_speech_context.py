from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.models import ElevenLabsContextSettingsRequest, TtsApiRequest
from app.services.elevenlabs import ElevenLabsClient
from app.services.speech_context import VOICE_SETTINGS_BY_CONTEXT, resolve_voice_settings


class ElevenLabsSpeechContextTest(unittest.TestCase):
    def test_founder_outreach_human_context_uses_tested_settings(self) -> None:
        self.assertEqual(
            VOICE_SETTINGS_BY_CONTEXT["founder_outreach_human"],
            {
                "stability": 0.5,
                "similarity_boost": 0.70,
                "style": 0.0,
                "speed": 0.96,
            },
        )

    def test_voice_settings_overrides_merge_without_mutating_context(self) -> None:
        resolved = resolve_voice_settings(
            "founder_outreach_human",
            {"stability": 0.35, "style": 0.15, "speed": 0.98},
        )

        self.assertEqual(resolved["stability"], 0.35)
        self.assertEqual(resolved["style"], 0.15)
        self.assertEqual(resolved["speed"], 0.98)
        self.assertEqual(VOICE_SETTINGS_BY_CONTEXT["founder_outreach_human"]["stability"], 0.5)

    def test_public_tts_request_accepts_all_elevenlabs_settings(self) -> None:
        request = TtsApiRequest(
            text="Hi Anushua, quick note.",
            voice_id="voice-id",
            speech_context="founder_outreach_human",
            voice_settings_override={
                "stability": 0.45,
                "similarity_boost": 0.72,
                "style": 0.1,
                "speed": 0.97,
            },
        ).to_tts_request()

        self.assertIsNotNone(request.voice_settings_override)
        self.assertEqual(
            request.voice_settings_override.model_dump(exclude_none=True),
            {
                "stability": 0.45,
                "similarity_boost": 0.72,
                "style": 0.1,
                "speed": 0.97,
            },
        )

    def test_legacy_complete_context_settings_request_remains_valid(self) -> None:
        request = ElevenLabsContextSettingsRequest(
            voice_settings={
                "stability": 0.5,
                "similarity_boost": 0.70,
                "style": 0.0,
                "speed": 0.96,
            }
        )

        self.assertIsNotNone(request.voice_settings)
        self.assertEqual(
            request.voice_settings.model_dump(exclude_none=True),
            {
                "stability": 0.5,
                "similarity_boost": 0.70,
                "style": 0.0,
                "speed": 0.96,
            },
        )

    def test_context_settings_request_accepts_partial_empty_and_null_values(self) -> None:
        for payload, expected in (
            ({"voice_settings": {"stability": 0.42}}, {"stability": 0.42}),
            ({"voice_settings": {"stability": None, "speed": 0.98}}, {"speed": 0.98}),
            ({"voice_settings": {}}, {}),
            ({"voice_settings": None}, {}),
            ({}, {}),
        ):
            with self.subTest(payload=payload):
                request = ElevenLabsContextSettingsRequest.model_validate(payload)
                actual = (
                    request.voice_settings.model_dump(exclude_none=True)
                    if request.voice_settings is not None
                    else {}
                )
                self.assertEqual(actual, expected)

    def test_context_settings_request_rejects_out_of_range_values(self) -> None:
        for field, value in (
            ("stability", -0.01),
            ("similarity_boost", 1.01),
            ("style", 1.01),
            ("speed", 1.21),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ElevenLabsContextSettingsRequest(voice_settings={field: value})

    def test_public_tts_request_rejects_out_of_range_settings(self) -> None:
        for field, value in (
            ("stability", 1.01),
            ("similarity_boost", -0.01),
            ("style", 1.1),
            ("speed", 1.21),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                TtsApiRequest(
                    text="Hi Anushua, quick note.",
                    voice_id="voice-id",
                    voice_settings_override={field: value},
                )

    def test_founder_context_adds_phrase_level_delivery_tag_for_v3(self) -> None:
        client = ElevenLabsClient(SimpleNamespace(elevenlabs_model_id="eleven_v3"))
        prepared = client._prepare_text("Hi Anushua, quick note.", "founder_outreach_human")
        self.assertEqual(prepared, "[warmly and conversationally] Hi Anushua, quick note.")


class ElevenLabsRequestPayloadTest(unittest.IsolatedAsyncioTestCase):
    def settings(self) -> SimpleNamespace:
        return SimpleNamespace(
            elevenlabs_api_key="test-key",
            elevenlabs_base_url="https://api.elevenlabs.io/v1",
            elevenlabs_model_id="eleven_v3",
            elevenlabs_language_code="en",
        )

    def async_client(self, response: MagicMock) -> tuple[MagicMock, AsyncMock]:
        post = AsyncMock(return_value=response)
        http_client = MagicMock()
        http_client.post = post
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=http_client)
        context.__aexit__ = AsyncMock(return_value=None)
        return context, post

    async def test_tts_uses_saved_clone_language_code(self) -> None:
        response = MagicMock(status_code=200, content=b"mp3")
        context, post = self.async_client(response)
        client = ElevenLabsClient(self.settings())

        with patch("app.services.elevenlabs.httpx.AsyncClient", return_value=context):
            result = await client.text_to_speech(
                voice_id="clone-id",
                text="Hi Anushua, quick note.",
                speech_context="founder_outreach_human",
                language_code="hi",
            )

        self.assertEqual(result, b"mp3")
        self.assertEqual(post.await_args.kwargs["json"]["language_code"], "hi")

    async def test_clone_sends_all_labels_multiple_files_and_noise_choice(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"voice_id": "clone-id", "requires_verification": False}
        context, post = self.async_client(response)
        client = ElevenLabsClient(self.settings())

        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.mp3"
            second = Path(directory) / "two.wav"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            with patch("app.services.elevenlabs.httpx.AsyncClient", return_value=context):
                result = await client.clone_voice(
                    name="Founder clone",
                    description="Consented founder outreach samples",
                    sample_files=[(first, "audio/mpeg"), (second, "audio/wav")],
                    labels={
                        "language": "en",
                        "accent": "American",
                        "gender": "female",
                        "age": "middle-aged",
                    },
                    remove_background_noise=False,
                )

        self.assertEqual(result["voice_id"], "clone-id")
        request = post.await_args.kwargs
        self.assertEqual(request["data"]["remove_background_noise"], "false")
        self.assertEqual(
            json.loads(request["data"]["labels"]),
            {
                "language": "en",
                "accent": "American",
                "gender": "female",
                "age": "middle-aged",
            },
        )
        self.assertEqual([field for field, _file in request["files"]], ["files", "files"])
        self.assertEqual([file_tuple[0] for _field, file_tuple in request["files"]], ["one.mp3", "two.wav"])


if __name__ == "__main__":
    unittest.main()
