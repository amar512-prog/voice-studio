#!/usr/bin/env python3
from __future__ import annotations

import io
import os
import sys
import tempfile
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
    def export_linkedin_m4a(self, input_mp3: Path, output_m4a: Path) -> None:
        output_m4a.write_bytes(b"fake-m4a-bytes")


def make_batch_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "tts_requests"
    sheet.append(["text", "voice_id", "voice_name", "accent", "speech_context", "target_seconds", "wpm", "export_m4a"])
    sheet.append(
        [
            "Batch test message.",
            "premade_us_voice",
            "QA Premade American",
            "us",
            "outreach_conversational",
            55,
            135,
            True,
        ]
    )
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

            call("GET", "/api/health", "/api/health")
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

            call("GET", "/api/voices", "/api/voices", headers=api_headers)
            manual_voice = call(
                "POST",
                "/api/voices",
                "/api/voices",
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
                "/api/voices/{record_id}/preview",
                f"/api/voices/{manual_voice['id']}/preview",
                expected=(307, 302),
                headers=api_headers,
                follow_redirects=False,
            )
            call("DELETE", "/api/voices/{record_id}", f"/api/voices/{manual_voice['id']}", headers=api_headers)

            premade_page = call(
                "GET",
                "/api/elevenlabs/voices",
                "/api/elevenlabs/voices?page=0&page_size=10&sort=trending&accent=us&premade_only=true",
                headers=api_headers,
            ).json()
            assert premade_page["voices"], "Expected premade voices"
            shared_page = call(
                "GET",
                "/api/elevenlabs/voices",
                "/api/elevenlabs/voices?page=0&page_size=10&sort=most_users&accent=us&premade_only=false",
                headers=api_headers,
            ).json()
            assert shared_page["voices"], "Expected shared voices"
            call("DELETE", "/api/elevenlabs/voices/cache", "/api/elevenlabs/voices/cache", headers=api_headers)

            by_id_voice = call(
                "POST",
                "/api/elevenlabs/voices/by-id",
                "/api/elevenlabs/voices/by-id",
                headers=api_headers,
                json={"voice_id": "raw_provider_voice"},
            ).json()
            assert by_id_voice["voice_id"] == "raw_provider_voice"

            picked_premade = premade_page["voices"][0]
            call(
                "POST",
                "/api/elevenlabs/voices/{voice_id}",
                f"/api/elevenlabs/voices/{picked_premade['id']}",
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
                "/api/elevenlabs/voices/{voice_id}",
                f"/api/elevenlabs/voices/{picked_shared['id']}",
                headers=api_headers,
                json={
                    "public_owner_id": picked_shared.get("public_owner_id"),
                    "name": picked_shared["display_name"],
                    "accent": picked_shared["accent"],
                },
            )
            call("POST", "/api/voices/sync", "/api/voices/sync", headers=api_headers)

            call(
                "POST",
                "/api/voices/clone",
                "/api/voices/clone",
                headers=api_headers,
                data={"name": "Cloned QA Voice", "accent": "us", "consent_confirmed": "true", "description": "QA clone"},
                files={"sample": ("sample.mp3", b"sample-audio", "audio/mpeg")},
            )

            tts_result = call(
                "POST",
                "/api/tts",
                "/api/tts",
                headers=api_headers,
                json={
                    "text": "Single endpoint test message.",
                    "voice_id": "premade_us_voice",
                    "voice_name": "QA Premade American",
                    "accent": "us",
                    "speech_context": "outreach_conversational",
                    "target_seconds": 55,
                    "wpm": 135,
                    "export_m4a": True,
                },
            ).json()
            assert tts_result["status"] == "completed"

            call(
                "POST",
                "/api/tts/batch",
                "/api/tts/batch",
                headers=api_headers,
                files={
                    "file": (
                        "tts_requests.xlsx",
                        make_batch_workbook(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

            jobs = call("GET", "/api/jobs", "/api/jobs", headers=api_headers).json()
            assert jobs, "Expected at least one job"
            job_id = tts_result["job_id"]
            call("GET", "/api/jobs/{job_id}", f"/api/jobs/{job_id}", headers=api_headers)
            zip_response = call(
                "GET",
                "/api/jobs/{job_id}/download",
                f"/api/jobs/{job_id}/download",
                headers=api_headers,
            )
            with zipfile.ZipFile(io.BytesIO(zip_response.content)) as archive:
                assert archive.namelist(), "Expected files in job ZIP"

            transcript_url = tts_result["transcript_url"]
            assert transcript_url and transcript_url.startswith("/files/")
            call("GET", "/files/{relative_path}", transcript_url, headers=api_headers)

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
