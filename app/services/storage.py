from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import uuid

from app.config import Settings


SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def safe_filename(name: str) -> str:
    cleaned = SAFE_NAME_RE.sub("-", name.strip()).strip(".-")
    return cleaned[:120] or "file"


class StorageService:
    def __init__(self, settings: Settings, provider: str = "elevenlabs") -> None:
        self.settings = settings
        self.provider = provider
        # Each provider gets its own subtree: data/{provider}/... so a provider's
        # voices, jobs, and source audio are fully separated on disk.
        self.root = settings.data_dir / provider
        self.voices_dir = self.root / "voices"
        self.audio_dir = self.root / "generated_audio"
        self.batch_dir = self.root / "batches"
        self.job_dir = self.root / "jobs"
        self.source_dir = self.root / "source_audio"

    def ensure(self) -> None:
        for path in [
            self.root,
            self.voices_dir,
            self.audio_dir,
            self.batch_dir,
            self.job_dir,
            self.source_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    @property
    def registry_path(self) -> Path:
        return self.voices_dir / "registry.json"

    @property
    def speech_contexts_path(self) -> Path:
        return self.root / "speech_contexts.json"

    def read_json(self, path: Path, default):
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_json(self, path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, default=str)
        tmp.replace(path)

    def job_folder(self, job_id: str) -> Path:
        return self.job_dir / safe_filename(job_id)

    def job_manifest_path(self, job_id: str) -> Path:
        return self.job_folder(job_id) / "job.json"

    def job_row_path(self, job_id: str, index: int, extension: str) -> Path:
        return self.job_folder(job_id) / f"row-{index:03d}.{extension.lstrip('.')}"

    def save_job_manifest(self, job_id: str, payload: dict) -> None:
        self.write_json(self.job_manifest_path(job_id), payload)

    def read_job_manifest(self, job_id: str) -> dict | None:
        path = self.job_manifest_path(job_id)
        if not path.exists():
            return None
        return self.read_json(path, None)

    def list_job_ids(self) -> list[str]:
        if not self.job_dir.exists():
            return []
        return [
            entry.name
            for entry in self.job_dir.iterdir()
            if entry.is_dir() and (entry / "job.json").exists()
        ]

    def batch_path(self, batch_id: str, filename: str) -> Path:
        return self.batch_dir / safe_filename(f"{batch_id}-{filename}")

    def source_audio_path(self, voice_record_id: str, filename: str) -> Path:
        suffix = Path(filename).suffix or ".audio"
        return self.source_dir / f"{voice_record_id}{suffix}"

    def relative_to_data(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def file_url(self, path: Path) -> str:
        return f"/api/{self.provider}/files/{self.relative_to_data(path)}"

    def resolve_file(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("Path escapes data directory")
        return candidate
