#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import Workbook


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
API_KEY = "swagger-test-api-key"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def configure_environment(data_dir: str) -> None:
    os.environ.update(
        {
            "AUTH_MODE": "development",
            "AUTH_USERNAME": "swagger-user",
            "AUTH_PASSWORD": "swagger-password",
            "API_KEY": API_KEY,
            "DATA_DIR": data_dir,
            "SESSION_SECRET": "swagger-test-session-secret-20260616",
            "SESSION_SECURE": "false",
            "ELEVENLABS_API_KEY": "test-elevenlabs-key",
            "STATIC_DIR": str(Path(data_dir) / "missing-static"),
        }
    )


class FakeElevenLabs:
    async def text_to_speech(self, voice_id: str, text: str, speech_context: str) -> bytes:
        return b"fake-mp3-bytes"

    async def list_voices(self) -> list[dict[str, Any]]:
        return [
            {
                "voice_id": "premade_us_voice",
                "name": "QA Premade American",
                "category": "premade",
                "description": "Premade American conversational test voice.",
                "preview_url": "https://example.com/premade.mp3",
                "created_at_unix": 1_700_000_000,
                "labels": {
                    "language": "English",
                    "accent": "American",
                    "use_case": "conversational",
                    "descriptive": "calm",
                    "gender": "male",
                    "age": "young",
                },
            },
            {
                "voice_id": "workspace_indian_voice",
                "name": "QA Workspace Indian",
                "category": "generated",
                "description": "Workspace Indian conversational test voice.",
                "preview_url": "https://example.com/workspace.mp3",
                "labels": {
                    "language": "English",
                    "accent": "Indian",
                    "use_case": "conversational",
                    "descriptive": "warm",
                    "gender": "female",
                    "age": "middle_aged",
                },
            },
        ]

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
        return {
            "voices": [
                {
                    "voice_id": "shared_us_voice",
                    "name": "QA Shared American",
                    "public_owner_id": "owner_123",
                    "accent": "american",
                    "language": language or "en",
                    "use_case": "conversational",
                    "description": "Shared American conversational test voice.",
                    "descriptive": "bright",
                    "preview_url": "https://example.com/shared.mp3",
                    "cloned_by_count": 123,
                    "gender": "female",
                    "age": "young",
                    "date_unix": 1_700_100_000,
                }
            ],
            "has_more": False,
            "total_count": 1,
        }

    async def get_voice(self, voice_id: str) -> dict[str, Any]:
        return {
            "voice_id": voice_id,
            "name": f"Fetched {voice_id}",
            "preview_url": "https://example.com/fetched.mp3",
            "labels": {"language": "English", "accent": "American", "use_case": "conversational"},
        }

    async def add_shared_voice(self, public_owner_id: str, voice_id: str, new_name: str) -> dict[str, Any]:
        return {"voice_id": f"workspace_{voice_id}", "name": new_name}

    async def clone_voice(
        self,
        name: str,
        description: str,
        sample_path: Path,
        content_type: str | None,
    ) -> dict[str, Any]:
        return {"voice_id": "cloned_test_voice", "name": name, "preview_url": "https://example.com/clone.mp3"}


class FakeDurationService:
    def estimate_seconds(self, text: str, wpm: int) -> float:
        words = len(text.split())
        return round((words / max(wpm, 1)) * 60, 1)

    def has_ffmpeg(self) -> bool:
        return True

    def measure_seconds(self, path: Path) -> float:
        return 4.2


class FakeAudioExportService:
    def export_wav(self, input_audio: Path, output_wav: Path) -> None:
        output_wav.write_bytes(input_audio.read_bytes())

    def export_mp3(self, input_wav: Path, output_mp3: Path) -> None:
        output_mp3.write_bytes(b"fake-mp3-bytes")

    def export_linkedin_m4a(self, input_mp3: Path, output_m4a: Path) -> None:
        output_m4a.write_bytes(b"fake-m4a-bytes")


class FakeOmniVoice:
    async def run_batch(self, payload: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(payload, str):
            raise AssertionError("Smoke tests expect a decoded OmniVoice payload")
        return {
            "results": [
                {
                    "status": "success",
                    "audio_b64": base64.b64encode(b"fake-wav-bytes").decode("ascii"),
                    "duration": 4.2,
                }
                for _item in payload.get("items", [])
            ]
        }


def make_batch_workbook(
    *,
    voice_id: str = "premade_us_voice",
    speech_context: str = "outreach_conversational",
    text: str = "Batch test message.",
    export_m4a: bool | None = None,
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "tts_requests"
    headers = ["text", "voice_id", "voice_name", "accent", "speech_context", "target_seconds", "wpm"]
    values = [text, voice_id, "QA Voice", "us", speech_context, 55, 135]
    if export_m4a is not None:
        headers.append("export_m4a")
        values.append(export_m4a)
    sheet.append(headers)
    sheet.append(values)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def assert_ok(response, expected: int | tuple[int, ...], label: str) -> None:
    expected_statuses = expected if isinstance(expected, tuple) else (expected,)
    if response.status_code not in expected_statuses:
        raise AssertionError(f"{label} expected {expected_statuses}, got {response.status_code}: {response.text[:500]}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vms-swagger-test-") as data_dir:
        configure_environment(data_dir)

        from app import main as app_module

        app_module.elevenlabs = FakeElevenLabs()
        app_module._clients["omnivoice"] = FakeOmniVoice()
        app_module.duration_service = FakeDurationService()
        app_module.audio_export_service = FakeAudioExportService()

        tested: set[tuple[str, str]] = set()

        def call(method: str, openapi_path: str, url: str, expected: int | tuple[int, ...] = 200, **kwargs):
            response = client.request(method, url, **kwargs)
            assert_ok(response, expected, f"{method} {openapi_path}")
            tested.add((method.upper(), openapi_path))
            return response

        with TestClient(app_module.app) as client:
            api_headers = {"X-API-Key": API_KEY}

            docs_response = client.get("/docs")
            assert_ok(docs_response, 200, "GET /docs")
            openapi_response = client.get("/openapi.json")
            assert_ok(openapi_response, 200, "GET /openapi.json")
            openapi = openapi_response.json()
            assert "get" in openapi["paths"]["/api/{provider}/voices"]
            assert "post" not in openapi["paths"]["/api/{provider}/voices"]
            assert "/api/{provider}/voices/{record_id}/preview" not in openapi["paths"]
            assert "/api/{provider}/voices/options" not in openapi["paths"]
            assert "/api/{provider}/voices/by-id" not in openapi["paths"]
            assert "/api/{provider}/voice-options/{voice_id}/save" not in openapi["paths"]
            assert "/api/{provider}/voices/cache" not in openapi["paths"]
            assert "/api/{provider}/speech-contexts/preview" not in openapi["paths"]
            context_request_schema = openapi["components"]["schemas"]["OmniVoiceContextRequest"]["properties"]
            tone_settings_schema = openapi["components"]["schemas"]["OmniVoiceToneSettings"]["properties"]
            assert "male or female" in context_request_schema["instruct"]["description"]
            assert "american accent or indian accent" in context_request_schema["instruct"]["description"]
            assert "Leave empty for a clone-only context" in context_request_schema["instruct"]["description"]
            assert "minLength" not in context_request_schema["instruct"]
            assert "clone owner" in context_request_schema["name"]["description"]
            assert tone_settings_schema["speed"]["minimum"] == 0.5
            assert tone_settings_schema["speed"]["maximum"] == 1.5
            assert tone_settings_schema["speed"]["multipleOf"] == 0.05
            assert tone_settings_schema["num_step"]["minimum"] == 4
            assert tone_settings_schema["num_step"]["maximum"] == 64
            assert tone_settings_schema["guidance_scale"]["minimum"] == 0
            assert tone_settings_schema["guidance_scale"]["maximum"] == 4
            assert "reference audio" in tone_settings_schema["preprocess_prompt"]["description"]
            assert "long silences" in tone_settings_schema["postprocess_output"]["description"]
            clone_operation = openapi["paths"]["/api/{provider}/voices/clone"]["post"]
            clone_provider_parameter = next(
                parameter
                for parameter in clone_operation["parameters"]
                if parameter["name"] == "provider"
            )
            assert "local reference-audio cloning" in clone_provider_parameter["description"]
            clone_body_ref = clone_operation["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
            clone_body_schema = openapi["components"]["schemas"][clone_body_ref.rsplit("/", 1)[-1]]
            assert "OmniVoice accepts `us`" in clone_body_schema["properties"]["accent"]["description"]
            assert "`auto` (detect from the reference sample)" in clone_body_schema["properties"]["accent"]["description"]
            assert "ElevenLabs accepts `us`" in clone_body_schema["properties"]["accent"]["description"]
            text_rules_operation = openapi["paths"]["/api/{provider}/text-rules/check"]["post"]
            assert "Check following rules in the text" in text_rules_operation["description"]
            assert "Replace slash `/` symbol" in text_rules_operation["description"]
            assert "word `slash`" in text_rules_operation["description"]
            tts_operation = openapi["paths"]["/api/{provider}/tts"]["post"]
            tts_description = " ".join(tts_operation["description"].split())
            assert "OmniVoice uses `voice_id` as a saved" in tts_description
            assert "requires `speech_context` to be a saved OmniVoice speech-context id" in tts_description
            tts_body_ref = tts_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            tts_schema = openapi["components"]["schemas"][tts_body_ref.rsplit("/", 1)[-1]]["properties"]
            assert set(tts_schema) == {"text", "voice_id", "speech_context"}
            assert "OmniVoice preset or cloned/sample voice id" in tts_schema["voice_id"]["description"]
            assert "OmniVoice: required saved speech-context id" in tts_schema["speech_context"]["description"]
            files_operation = openapi["paths"]["/api/{provider}/files/{relative_path}"]["get"]
            files_description = " ".join(files_operation["description"].split())
            assert "Use only the path segment after `/files/`" in files_description
            relative_path_parameter = next(
                parameter
                for parameter in files_operation["parameters"]
                if parameter["name"] == "relative_path"
            )
            assert "Append only the file path after `/files/`" in relative_path_parameter["description"]
            assert "enter `jobs/job_xxx/row-001.mp3`" in relative_path_parameter["description"]
            delete_voice_operation = openapi["paths"]["/api/{provider}/voices/{record_id}"]["delete"]
            record_id_parameter = next(
                parameter
                for parameter in delete_voice_operation["parameters"]
                if parameter["name"] == "record_id"
            )
            assert "returned by `GET /api/{provider}/voices`" in record_id_parameter["description"]
            assert "Use the `id` field" in record_id_parameter["description"]
            assert "not the provider `voice_id`" in record_id_parameter["description"]
            delete_context_operation = openapi["paths"]["/api/{provider}/speech-contexts/{context_id}"]["delete"]
            context_id_parameter = next(
                parameter
                for parameter in delete_context_operation["parameters"]
                if parameter["name"] == "context_id"
            )
            assert "returned by `GET /api/{provider}/speech-contexts`" in context_id_parameter["description"]
            assert "Use the `id` field" in context_id_parameter["description"]
            providers_operation = openapi["paths"]["/api/providers"]["get"]
            assert providers_operation["security"] == [{"APIKeyHeader": []}]
            provider_operations = [
                operation
                for path, path_item in openapi["paths"].items()
                if "{provider}" in path
                for method, operation in path_item.items()
                if method in HTTP_METHODS
            ]
            assert provider_operations
            omnivoice_only_operations = {
                "list_omnivoice_contexts_api__provider__speech_contexts_get",
                "upsert_omnivoice_context_api__provider__speech_contexts_post",
                "check_omnivoice_text_rules_api__provider__text_rules_check_post",
                "delete_omnivoice_context_api__provider__speech_contexts__context_id__delete",
            }
            for operation in provider_operations:
                provider_parameter = next(
                    parameter
                    for parameter in operation["parameters"]
                    if parameter["name"] == "provider"
                )
                expected_description = (
                    "Provider id: `omnivoice` only."
                    if operation["operationId"] in omnivoice_only_operations
                    else (
                        "Provider id: use `omnivoice` for local reference-audio cloning, "
                        "or `elevenlabs` for provider-hosted instant voice cloning."
                        if operation["operationId"] == "clone_voice_api__provider__voices_clone_post"
                        else "Provider id: `omnivoice` or `elevenlabs`."
                    )
                )
            assert provider_parameter["description"] == expected_description

            call("GET", "/api/health", "/api/health")
            call("GET", "/api/providers", "/api/providers", expected=401)
            providers = call("GET", "/api/providers", "/api/providers", headers=api_headers).json()
            assert providers["default_provider"] == "omnivoice"
            assert [provider["id"] for provider in providers["providers"]] == ["omnivoice", "elevenlabs"]
            assert "text_rules" in providers["providers"][0]["capabilities"]
            assert "voice_library" in providers["providers"][1]["capabilities"]
            call("GET", "/api/config", "/api/config")
            call("GET", "/api/auth/me", "/api/auth/me")

            original_auth_mode = app_module.settings.auth_mode
            original_verify = app_module.verify_google_credential
            app_module.settings.auth_mode = "google"
            app_module.verify_google_credential = lambda credential, settings: {
                "sub": "google-user",
                "email": "google@example.com",
                "name": "Google User",
                "picture": "",
            }
            call("POST", "/api/auth/google", "/api/auth/google", json={"credential": "fake-google-jwt"})
            app_module.verify_google_credential = original_verify
            app_module.settings.auth_mode = original_auth_mode

            call(
                "POST",
                "/api/auth/password",
                "/api/auth/password",
                json={"username": "swagger-user", "password": "swagger-password"},
            )
            call("POST", "/api/auth/development", "/api/auth/development")
            call("POST", "/api/auth/logout", "/api/auth/logout")

            call("GET", "/api/{provider}/health", "/api/elevenlabs/health")
            call("GET", "/api/{provider}/health", "/api/omnivoice/health")

            call("GET", "/api/{provider}/voices", "/api/elevenlabs/voices", headers=api_headers)
            manual_voice = call(
                "POST",
                "/api/{provider}/voices",
                "/api/elevenlabs/voices",
                headers=api_headers,
                json={
                    "display_name": "Manual QA Voice",
                    "voice_id": "manual_qa_voice",
                    "source_type": "manual",
                    "accent": "us",
                    "consent_status": "not_required",
                },
            ).json()
            call(
                "GET",
                "/api/{provider}/voices/{record_id}/preview",
                f"/api/elevenlabs/voices/{manual_voice['id']}/preview",
                expected=(307, 302),
                headers=api_headers,
                follow_redirects=False,
            )
            call(
                "DELETE",
                "/api/{provider}/voices/{record_id}",
                f"/api/elevenlabs/voices/{manual_voice['id']}",
                headers=api_headers,
            )

            premade_page = call(
                "GET",
                "/api/{provider}/voices/options",
                "/api/elevenlabs/voices/options?page=0&page_size=10&sort=trending&accent=us&premade_only=true",
                headers=api_headers,
            ).json()
            assert premade_page["voices"], "Expected premade voices"
            shared_page = call(
                "GET",
                "/api/{provider}/voices/options",
                "/api/elevenlabs/voices/options?page=0&page_size=10&sort=most_users&accent=us&premade_only=false",
                headers=api_headers,
            ).json()
            assert shared_page["voices"], "Expected shared voices"
            call(
                "DELETE",
                "/api/{provider}/voices/cache",
                "/api/elevenlabs/voices/cache",
                headers=api_headers,
            )

            by_id_voice = call(
                "POST",
                "/api/{provider}/voices/by-id",
                "/api/elevenlabs/voices/by-id",
                headers=api_headers,
                json={"voice_id": "raw_provider_voice"},
            ).json()
            assert by_id_voice["voice_id"] == "raw_provider_voice"

            picked_premade = premade_page["voices"][0]
            call(
                "POST",
                "/api/{provider}/voice-options/{voice_id}/save",
                f"/api/elevenlabs/voice-options/{picked_premade['id']}/save",
                headers=api_headers,
                json={
                    "public_owner_id": picked_premade.get("public_owner_id"),
                    "name": picked_premade["display_name"],
                    "accent": picked_premade["accent"],
                },
            )
            picked_shared = shared_page["voices"][0]
            call(
                "POST",
                "/api/{provider}/voice-options/{voice_id}/save",
                f"/api/elevenlabs/voice-options/{picked_shared['id']}/save",
                headers=api_headers,
                json={
                    "public_owner_id": picked_shared.get("public_owner_id"),
                    "name": picked_shared["display_name"],
                    "accent": picked_shared["accent"],
                },
            )
            call(
                "POST",
                "/api/{provider}/voices/sync",
                "/api/elevenlabs/voices/sync",
                headers=api_headers,
            )

            call(
                "POST",
                "/api/{provider}/voices/clone",
                "/api/elevenlabs/voices/clone",
                headers=api_headers,
                data={"name": "Cloned QA Voice", "accent": "us", "consent_confirmed": "true", "description": "QA clone"},
                files={"sample": ("sample.mp3", b"sample-audio", "audio/mpeg")},
            )

            tts_result = call(
                "POST",
                "/api/{provider}/tts",
                "/api/elevenlabs/tts",
                headers=api_headers,
                json={
                    "text": "Single endpoint test message.",
                    "voice_id": "premade_us_voice",
                    "voice_name": "QA Premade American",
                    "accent": "us",
                    "speech_context": "outreach_conversational",
                    "target_seconds": 55,
                    "wpm": 135,
                },
            ).json()
            assert tts_result["status"] == "completed"
            assert tts_result["m4a_url"], "Expected default export_m4a=true to create an M4A URL"

            batch_job = call(
                "POST",
                "/api/{provider}/tts/batch",
                "/api/elevenlabs/tts/batch",
                expected=202,
                headers=api_headers,
                files={
                    "file": (
                        "tts_requests.xlsx",
                        make_batch_workbook(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            ).json()
            batch_detail = None
            for _ in range(40):
                batch_detail = call(
                    "GET",
                    "/api/{provider}/jobs/{job_id}",
                    f"/api/elevenlabs/jobs/{batch_job['job_id']}",
                    headers=api_headers,
                ).json()
                if batch_detail["status"] != "running":
                    break
                time.sleep(0.05)
            assert batch_detail is not None and batch_detail["status"] != "running"
            assert batch_detail["rows"][0]["m4a_url"], "Expected workbook default export_m4a=true to create M4A"

            jobs = call(
                "GET",
                "/api/{provider}/jobs",
                "/api/elevenlabs/jobs",
                headers=api_headers,
            ).json()
            assert jobs, "Expected at least one job"
            job_id = tts_result["job_id"]
            call(
                "GET",
                "/api/{provider}/jobs/{job_id}",
                f"/api/elevenlabs/jobs/{job_id}",
                headers=api_headers,
            )
            zip_response = call(
                "GET",
                "/api/{provider}/jobs/{job_id}/download",
                f"/api/elevenlabs/jobs/{job_id}/download",
                headers=api_headers,
            )
            with zipfile.ZipFile(io.BytesIO(zip_response.content)) as archive:
                assert archive.namelist(), "Expected files in job ZIP"

            transcript_url = tts_result["transcript_url"]
            assert transcript_url and transcript_url.startswith("/api/elevenlabs/files/")
            call("GET", "/api/{provider}/files/{relative_path}", transcript_url, headers=api_headers)

            omnivoice_voices = call(
                "GET",
                "/api/{provider}/voices",
                "/api/omnivoice/voices",
                headers=api_headers,
            ).json()
            assert len(omnivoice_voices) >= 2, "Expected seeded OmniVoice design presets"
            call(
                "POST",
                "/api/{provider}/voices/sync",
                "/api/omnivoice/voices/sync",
                headers=api_headers,
            )
            contexts = call(
                "GET",
                "/api/{provider}/speech-contexts",
                "/api/omnivoice/speech-contexts",
                headers=api_headers,
            ).json()
            assert {context["id"] for context in contexts} >= {"english_american", "english_indian"}
            rules = call(
                "POST",
                "/api/{provider}/text-rules/check",
                "/api/omnivoice/text-rules/check",
                headers=api_headers,
                json={"text": "A date like 15/12/2025 needs review."},
            ).json()
            assert not rules["ready"]
            assert rules["suggested_text"] == "A date like 15th December, 2025 needs review."

            custom_context = call(
                "POST",
                "/api/{provider}/speech-contexts",
                "/api/omnivoice/speech-contexts",
                headers=api_headers,
                json={
                    "name": "QA Context",
                    "instruct": "",
                    "language": "en",
                    "settings": {"speed": 1.0, "num_step": 8, "guidance_scale": 1.5},
                },
            ).json()
            assert custom_context["instruct"] == ""
            call(
                "POST",
                "/api/{provider}/speech-contexts/preview",
                "/api/omnivoice/speech-contexts/preview",
                headers=api_headers,
                json={
                    "text": "Preview this design.",
                    "instruct": "",
                    "language": "en",
                    "settings": {"speed": 1.0, "num_step": 8, "guidance_scale": 1.5},
                },
            )
            call(
                "DELETE",
                "/api/{provider}/speech-contexts/{context_id}",
                f"/api/omnivoice/speech-contexts/{custom_context['id']}",
                headers=api_headers,
            )

            cloned_omnivoice = call(
                "POST",
                "/api/{provider}/voices/clone",
                "/api/omnivoice/voices/clone",
                headers=api_headers,
                data={
                    "name": "OmniVoice QA Clone",
                    "accent": "auto",
                    "consent_confirmed": "true",
                    "description": "Local QA clone",
                    "reference_text": "This is the reference transcript.",
                },
                files={"sample": ("sample.wav", b"sample-audio", "audio/wav")},
            ).json()
            assert cloned_omnivoice["provider_metadata"]["reference_text"] == "This is the reference transcript."
            assert cloned_omnivoice["accent"] == "auto"

            invalid_accent = call(
                "POST",
                "/api/{provider}/voices/clone",
                "/api/omnivoice/voices/clone",
                expected=400,
                headers=api_headers,
                data={
                    "name": "Invalid Accent Clone",
                    "accent": "neutral",
                    "consent_confirmed": "true",
                },
                files={"sample": ("sample.wav", b"sample-audio", "audio/wav")},
            )
            assert invalid_accent.json()["detail"] == (
                "Invalid argument `accent` for provider `omnivoice`: `neutral`. Expected one of: "
                "`us` (American English), `in` (Indian English), `auto` (detect from reference sample)."
            )

            invalid_elevenlabs_accent = call(
                "POST",
                "/api/{provider}/voices/clone",
                "/api/elevenlabs/voices/clone",
                expected=400,
                headers=api_headers,
                data={
                    "name": "Invalid ElevenLabs Accent",
                    "accent": "auto",
                    "consent_confirmed": "true",
                },
                files={"sample": ("sample.wav", b"sample-audio", "audio/wav")},
            )
            assert invalid_elevenlabs_accent.json()["detail"] == (
                "Invalid argument `accent` for provider `elevenlabs`: `auto`. Expected one of: "
                "`us` (American English), `in` (Indian English), `neutral` (unspecified)."
            )

            invalid_provider = call(
                "POST",
                "/api/{provider}/voices/clone",
                "/api/not-a-provider/voices/clone",
                expected=404,
                headers=api_headers,
                data={
                    "name": "Invalid Provider Clone",
                    "accent": "in",
                    "consent_confirmed": "true",
                },
                files={"sample": ("sample.wav", b"sample-audio", "audio/wav")},
            )
            assert invalid_provider.json()["detail"] == (
                "Invalid argument `provider`: `not-a-provider`. "
                "Expected one of: elevenlabs, omnivoice."
            )

            american_preset = next(
                voice for voice in omnivoice_voices if voice["voice_id"] == "ov_design_english_american"
            )
            omnivoice_tts = call(
                "POST",
                "/api/{provider}/tts",
                "/api/omnivoice/tts",
                headers=api_headers,
                json={
                    "text": "OmniVoice endpoint test message.",
                    "voice_id": american_preset["voice_id"],
                    "voice_name": american_preset["display_name"],
                    "accent": "us",
                    "speech_context": "english_american",
                    "target_seconds": 55,
                    "wpm": 135,
                },
            ).json()
            assert omnivoice_tts["status"] == "completed"
            assert omnivoice_tts["m4a_url"], "Expected default export_m4a=true to create an M4A URL"
            omnivoice_batch_job = call(
                "POST",
                "/api/{provider}/tts/batch",
                "/api/omnivoice/tts/batch",
                expected=202,
                headers=api_headers,
                files={
                    "file": (
                        "omnivoice_requests.xlsx",
                        make_batch_workbook(
                            voice_id=american_preset["voice_id"],
                            speech_context="english_american",
                            text="OmniVoice batch test message.",
                        ),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            ).json()
            omnivoice_batch_detail = None
            for _ in range(40):
                omnivoice_batch_detail = call(
                    "GET",
                    "/api/{provider}/jobs/{job_id}",
                    f"/api/omnivoice/jobs/{omnivoice_batch_job['job_id']}",
                    headers=api_headers,
                ).json()
                if omnivoice_batch_detail["status"] != "running":
                    break
                time.sleep(0.05)
            assert omnivoice_batch_detail is not None and omnivoice_batch_detail["status"] != "running"
            assert omnivoice_batch_detail["rows"][0]["m4a_url"], (
                "Expected workbook default export_m4a=true to create M4A"
            )

            visible_operations = {
                (method.upper(), path)
                for path, path_item in openapi["paths"].items()
                for method in path_item
                if method in HTTP_METHODS
            }
            missing = sorted(visible_operations - tested)
            if missing:
                raise AssertionError(f"Visible Swagger operations not exercised: {missing}")

        print(
            f"PASS: exercised {len(visible_operations)} visible Swagger operations "
            f"and {len(tested)} total endpoint smoke calls."
        )
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise
