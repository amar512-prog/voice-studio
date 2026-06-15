from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


class DurationService:
    def estimate_seconds(self, text: str, wpm: int) -> float:
        words = [word for word in text.split() if word.strip()]
        if not words:
            return 0.0
        return round((len(words) / max(wpm, 1)) * 60, 2)

    def has_ffmpeg(self) -> bool:
        return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

    def measure_seconds(self, path: Path) -> float:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(path),
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        return round(float(completed.stdout.strip()), 2)
