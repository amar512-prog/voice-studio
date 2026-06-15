from pathlib import Path
import subprocess


class AudioExportService:
    def export_linkedin_m4a(self, input_mp3: Path, output_m4a: Path) -> None:
        output_m4a.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_mp3),
            "-ac",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-t",
            "60",
            str(output_m4a),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
