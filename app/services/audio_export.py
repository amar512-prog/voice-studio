from pathlib import Path
import subprocess


class AudioExportService:
    def export_wav(self, input_audio: Path, output_wav: Path) -> None:
        """Normalize any input (webm/opus/m4a/mp3/...) to mono 24kHz PCM WAV.

        OmniVoice loads reference audio with soundfile/torchaudio, which cannot
        read browser recordings (webm/opus); this gives it a readable sample.
        """
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_audio),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(output_wav),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

    def export_mp3(self, input_audio: Path, output_mp3: Path) -> None:
        output_mp3.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_audio),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output_mp3),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)

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
