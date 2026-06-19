from pathlib import Path
from dataclasses import dataclass, field
import re
import shutil
import subprocess


@dataclass(frozen=True)
class SilenceSpan:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class ReferenceClipResult:
    source_duration_seconds: float
    selected_start_seconds: float
    selected_end_seconds: float
    selected_duration_seconds: float
    trimmed: bool
    selection_mode: str
    detected_silence_count: int
    silence_threshold_db: int
    min_pause_seconds: float
    boundary_padding_seconds: float
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    candidate_count: int = 0
    warnings: tuple[str, ...] = ()

    def to_metadata(self) -> dict:
        return {
            "source_duration_seconds": self.source_duration_seconds,
            "selected_start_seconds": self.selected_start_seconds,
            "selected_end_seconds": self.selected_end_seconds,
            "selected_duration_seconds": self.selected_duration_seconds,
            "trimmed": self.trimmed,
            "selection_mode": self.selection_mode,
            "detected_silence_count": self.detected_silence_count,
            "silence_threshold_db": self.silence_threshold_db,
            "min_pause_seconds": self.min_pause_seconds,
            "boundary_padding_seconds": self.boundary_padding_seconds,
            "score": self.score,
            "score_breakdown": self.score_breakdown,
            "candidate_count": self.candidate_count,
            "warnings": list(self.warnings),
        }


class ReferenceClipSelectionError(ValueError):
    pass


class AudioExportService:
    reference_min_seconds = 3.0
    reference_max_seconds = 10.0
    reference_silence_threshold_db = -35
    reference_min_pause_seconds = 0.25
    reference_boundary_padding_seconds = 0.2
    _silence_start_pattern = re.compile(r"silence_start:\s*(?P<start>[0-9.]+)")
    _silence_end_pattern = re.compile(
        r"silence_end:\s*(?P<end>[0-9.]+)\s*\|\s*silence_duration:\s*(?P<duration>[0-9.]+)"
    )

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

    def export_reference_wav(self, input_audio: Path, output_wav: Path) -> ReferenceClipResult:
        """Create an OmniVoice reference WAV from one continuous pause-bounded clip.

        The full recording is analyzed for clear pauses. The selected reference
        is the best-scored 3-10 second pause-bounded clip when available;
        otherwise it falls back to the shortest pause/source-bounded clip
        rather than cutting through active speech.
        """
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        analysis_wav = output_wav.with_name(f"{output_wav.stem}-analysis.wav")
        if analysis_wav == input_audio:
            analysis_wav = output_wav.with_name(f"{output_wav.stem}-analysis-source.wav")

        self.export_wav(input_audio, analysis_wav)
        try:
            source_duration = self._measure_seconds(analysis_wav)
            silences = self.detect_silences(analysis_wav, source_duration)
            result = select_reference_clip(
                source_duration=source_duration,
                silences=silences,
                min_seconds=self.reference_min_seconds,
                max_seconds=self.reference_max_seconds,
                boundary_padding_seconds=self.reference_boundary_padding_seconds,
                silence_threshold_db=self.reference_silence_threshold_db,
                min_pause_seconds=self.reference_min_pause_seconds,
            )
            if result.trimmed:
                self._export_wav_segment(
                    analysis_wav,
                    output_wav,
                    result.selected_start_seconds,
                    result.selected_end_seconds,
                )
            else:
                shutil.copyfile(analysis_wav, output_wav)
            return result
        finally:
            if analysis_wav != output_wav and analysis_wav.exists():
                analysis_wav.unlink()

    def detect_silences(self, input_wav: Path, source_duration: float | None = None) -> tuple[SilenceSpan, ...]:
        duration = source_duration if source_duration is not None else self._measure_seconds(input_wav)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(input_wav),
            "-af",
            (
                "silencedetect="
                f"noise={self.reference_silence_threshold_db}dB:"
                f"d={self.reference_min_pause_seconds}"
            ),
            "-f",
            "null",
            "-",
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        return self._parse_silencedetect_output(
            "\n".join(part for part in [completed.stderr, completed.stdout] if part),
            duration,
        )

    def _parse_silencedetect_output(self, output: str, source_duration: float) -> tuple[SilenceSpan, ...]:
        spans: list[SilenceSpan] = []
        pending_start: float | None = None
        for line in output.splitlines():
            start_match = self._silence_start_pattern.search(line)
            if start_match:
                pending_start = float(start_match.group("start"))
                continue

            end_match = self._silence_end_pattern.search(line)
            if not end_match:
                continue
            end = float(end_match.group("end"))
            silence_duration = float(end_match.group("duration"))
            start = pending_start if pending_start is not None else end - silence_duration
            pending_start = None
            spans.append(SilenceSpan(max(0.0, start), min(source_duration, end)))

        if pending_start is not None and pending_start < source_duration:
            spans.append(SilenceSpan(max(0.0, pending_start), source_duration))

        return _normalize_silences(spans, source_duration)

    def _measure_seconds(self, path: Path) -> float:
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
        return round(float(completed.stdout.strip()), 3)

    def _export_wav_segment(self, input_wav: Path, output_wav: Path, start_seconds: float, end_seconds: float) -> None:
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_wav),
            "-vn",
            "-af",
            f"atrim=start={start_seconds:.3f}:end={end_seconds:.3f},asetpts=PTS-STARTPTS",
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


def select_reference_clip(
    *,
    source_duration: float,
    silences: tuple[SilenceSpan, ...] | list[SilenceSpan],
    min_seconds: float,
    max_seconds: float,
    boundary_padding_seconds: float,
    silence_threshold_db: int,
    min_pause_seconds: float,
) -> ReferenceClipResult:
    source_duration = round(float(source_duration), 3)
    if source_duration <= 0:
        raise ReferenceClipSelectionError("The uploaded sample has no measurable audio.")

    normalized_silences = _normalize_silences(silences, source_duration)
    strict_pause_boundaries = source_duration > max_seconds
    speech_intervals = _speech_intervals(source_duration, normalized_silences)
    if not speech_intervals:
        raise ReferenceClipSelectionError("The uploaded sample appears to be silent. Record a clear spoken sample.")
    if not normalized_silences and source_duration <= max_seconds:
        warnings = ["no_clear_pause_bounded_window"]
        if source_duration < min_seconds:
            warnings.insert(0, "shorter_than_recommended")
        score, score_breakdown = _score_reference_candidate(
            source_duration,
            normalized_silences,
            speech_intervals,
            0.0,
            source_duration,
            False,
            False,
            min_seconds,
            max_seconds,
        )
        return _clip_result(
            source_duration,
            0.0,
            source_duration,
            "full_recording_no_clear_boundaries",
            0,
            silence_threshold_db,
            min_pause_seconds,
            boundary_padding_seconds,
            warnings=tuple(warnings),
            score=score,
            score_breakdown=score_breakdown,
            candidate_count=1,
        )

    start_candidates: list[tuple[float, bool, str]] = [(0.0, False, "source_start")]
    end_candidates: list[tuple[float, bool, str]] = [(source_duration, False, "source_end")]
    for silence in normalized_silences:
        if silence.end < source_duration:
            start_candidates.append(
                (round(max(0.0, silence.end - boundary_padding_seconds), 3), True, "pause_start")
            )
        if silence.start > 0:
            end_candidates.append(
                (round(min(source_duration, silence.start + boundary_padding_seconds), 3), True, "pause_end")
            )

    candidates = []
    for start, start_clear, start_kind in start_candidates:
        for end, end_clear, end_kind in end_candidates:
            if end <= start:
                continue
            selected_duration = round(end - start, 3)
            if selected_duration < min_seconds or selected_duration > max_seconds:
                continue
            clear_boundaries = int(start_clear) + int(end_clear)
            if strict_pause_boundaries and clear_boundaries < 2:
                continue
            speech_seconds = _speech_seconds_inside(speech_intervals, start, end)
            if speech_seconds < min(1.0, selected_duration * 0.35):
                continue
            score, score_breakdown = _score_reference_candidate(
                source_duration,
                normalized_silences,
                speech_intervals,
                start,
                end,
                start_clear,
                end_clear,
                min_seconds,
                max_seconds,
            )
            candidates.append(
                (
                    score,
                    score_breakdown["fluency"],
                    score_breakdown["human_like"],
                    score_breakdown["emotional_expression"],
                    clear_boundaries,
                    -start,
                    start,
                    end,
                    start_kind,
                    end_kind,
                    score_breakdown,
                )
            )

    if not candidates:
        if source_duration <= max_seconds:
            warnings = []
            if source_duration < min_seconds:
                warnings.append("shorter_than_recommended")
            warnings.append("no_clear_pause_bounded_window")
            score, score_breakdown = _score_reference_candidate(
                source_duration,
                normalized_silences,
                speech_intervals,
                0.0,
                source_duration,
                False,
                False,
                min_seconds,
                max_seconds,
            )
            return _clip_result(
                source_duration,
                0.0,
                source_duration,
                "full_recording_no_clear_boundaries",
                len(normalized_silences),
                silence_threshold_db,
                min_pause_seconds,
                boundary_padding_seconds,
                warnings=tuple(warnings),
                score=score,
                score_breakdown=score_breakdown,
                candidate_count=1,
            )
        fallback = _smallest_boundary_clip(
            source_duration,
            normalized_silences,
            speech_intervals,
            min_seconds,
            max_seconds,
            silence_threshold_db,
            min_pause_seconds,
            boundary_padding_seconds,
            len(normalized_silences),
        )
        if fallback is not None:
            return fallback
        raise ReferenceClipSelectionError("The uploaded sample appears to be silent. Record a clear spoken sample.")

    _, _, _, _, _, _, start, end, start_kind, end_kind, score_breakdown = max(
        candidates,
        key=lambda candidate: (candidate[0], candidate[5]),
    )
    selection_mode = "pause_bounded" if start_kind == "pause_start" and end_kind == "pause_end" else "edge_bounded"
    return _clip_result(
        source_duration,
        start,
        end,
        selection_mode,
        len(normalized_silences),
        silence_threshold_db,
        min_pause_seconds,
        boundary_padding_seconds,
        score=score_breakdown["overall"],
        score_breakdown=score_breakdown,
        candidate_count=len(candidates),
    )


def _clip_result(
    source_duration: float,
    start: float,
    end: float,
    selection_mode: str,
    detected_silence_count: int,
    silence_threshold_db: int,
    min_pause_seconds: float,
    boundary_padding_seconds: float,
    *,
    score: float = 0.0,
    score_breakdown: dict[str, float] | None = None,
    candidate_count: int = 0,
    warnings: tuple[str, ...] = (),
) -> ReferenceClipResult:
    start = round(max(0.0, start), 3)
    end = round(max(start, end), 3)
    return ReferenceClipResult(
        source_duration_seconds=round(source_duration, 3),
        selected_start_seconds=start,
        selected_end_seconds=end,
        selected_duration_seconds=round(end - start, 3),
        trimmed=start > 0.001 or abs(end - source_duration) > 0.001,
        selection_mode=selection_mode,
        detected_silence_count=detected_silence_count,
        silence_threshold_db=silence_threshold_db,
        min_pause_seconds=min_pause_seconds,
        boundary_padding_seconds=boundary_padding_seconds,
        score=round(score, 3),
        score_breakdown=score_breakdown or {},
        candidate_count=candidate_count,
        warnings=warnings,
    )


def _smallest_boundary_clip(
    source_duration: float,
    silences: tuple[SilenceSpan, ...],
    speech_intervals: tuple[tuple[float, float], ...],
    min_seconds: float,
    max_seconds: float,
    silence_threshold_db: int,
    min_pause_seconds: float,
    boundary_padding_seconds: float,
    detected_silence_count: int,
) -> ReferenceClipResult | None:
    clips = []
    for speech_start, speech_end in speech_intervals:
        start = max(0.0, speech_start - boundary_padding_seconds)
        end = min(source_duration, speech_end + boundary_padding_seconds)
        if end <= start:
            continue
        clips.append((round(end - start, 3), start, end))
    if not clips:
        return None
    _, start, end = min(clips)
    score, score_breakdown = _score_reference_candidate(
        source_duration,
        silences,
        speech_intervals,
        start,
        end,
        start <= 0.001,
        end >= source_duration - 0.001,
        min_seconds,
        max_seconds,
    )
    return _clip_result(
        source_duration,
        start,
        end,
        "smallest_boundary_clip",
        detected_silence_count,
        silence_threshold_db,
        min_pause_seconds,
        boundary_padding_seconds,
        score=score,
        score_breakdown=score_breakdown,
        candidate_count=len(clips),
        warnings=("no_clean_3_to_10_second_pause_bounded_window",),
    )


def _score_reference_candidate(
    source_duration: float,
    silences: tuple[SilenceSpan, ...],
    speech_intervals: tuple[tuple[float, float], ...],
    start: float,
    end: float,
    start_clear: bool,
    end_clear: bool,
    min_seconds: float,
    max_seconds: float,
) -> tuple[float, dict[str, float]]:
    duration = max(0.001, round(end - start, 3))
    speech_seconds = _speech_seconds_inside(speech_intervals, start, end)
    speech_ratio = _clamp(speech_seconds / duration)
    internal_silences = _internal_silences(silences, start, end)
    internal_silence_seconds = round(sum(span.duration for span in internal_silences), 3)
    internal_pause_ratio = _clamp(internal_silence_seconds / duration)
    internal_pause_count = len(internal_silences)
    phrase_count = _phrase_count(speech_intervals, start, end)
    boundary_score = (int(start_clear) + int(end_clear)) / 2
    duration_score = _range_score(duration, 5.0, 8.0, min_seconds, max_seconds)
    speech_ratio_score = _range_score(speech_ratio, 0.68, 0.92, 0.35, 1.0)
    pause_load_score = _clamp(1 - max(0.0, internal_pause_ratio - 0.08) / 0.26)
    pause_count_score = _clamp(1 - max(0, internal_pause_count - 2) * 0.22)
    phrase_score = _phrase_score(phrase_count)

    fluency = _weighted_score(
        (speech_ratio_score, 0.52),
        (pause_load_score, 0.30),
        (pause_count_score, 0.18),
    )
    human_like = _weighted_score(
        (speech_ratio_score, 0.30),
        (duration_score, 0.25),
        (boundary_score, 0.25),
        (phrase_score, 0.20),
    )
    emotional_expression = _weighted_score(
        (phrase_score, 0.42),
        (speech_ratio_score, 0.28),
        (duration_score, 0.20),
        (pause_load_score, 0.10),
    )
    overall = _weighted_score(
        (fluency, 0.38),
        (human_like, 0.30),
        (emotional_expression, 0.22),
        (boundary_score, 0.06),
        (duration_score, 0.04),
    )
    breakdown = {
        "overall": overall,
        "fluency": fluency,
        "human_like": human_like,
        "emotional_expression": emotional_expression,
        "boundary": round(boundary_score, 3),
        "duration": duration_score,
        "speech_ratio": round(speech_ratio, 3),
        "internal_pause_ratio": round(internal_pause_ratio, 3),
        "phrase_count": float(phrase_count),
    }
    return overall, breakdown


def _internal_silences(silences: tuple[SilenceSpan, ...], start: float, end: float) -> tuple[SilenceSpan, ...]:
    spans: list[SilenceSpan] = []
    for silence in silences:
        overlap_start = max(start, silence.start)
        overlap_end = min(end, silence.end)
        if overlap_end - overlap_start > 0.08:
            spans.append(SilenceSpan(overlap_start, overlap_end))
    return tuple(spans)


def _phrase_count(intervals: tuple[tuple[float, float], ...], start: float, end: float) -> int:
    return sum(
        1
        for speech_start, speech_end in intervals
        if min(end, speech_end) - max(start, speech_start) > 0.25
    )


def _phrase_score(phrase_count: int) -> float:
    if phrase_count <= 0:
        return 0.0
    if phrase_count == 1:
        return 0.72
    if phrase_count in {2, 3}:
        return 1.0
    if phrase_count == 4:
        return 0.84
    return _clamp(0.84 - (phrase_count - 4) * 0.14)


def _range_score(value: float, ideal_min: float, ideal_max: float, hard_min: float, hard_max: float) -> float:
    if ideal_min <= value <= ideal_max:
        return 1.0
    if value < ideal_min:
        return _clamp((value - hard_min) / max(ideal_min - hard_min, 0.001))
    return _clamp((hard_max - value) / max(hard_max - ideal_max, 0.001))


def _weighted_score(*parts: tuple[float, float]) -> float:
    total_weight = sum(weight for _score, weight in parts)
    if total_weight <= 0:
        return 0.0
    return round(sum(score * weight for score, weight in parts) / total_weight, 3)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _normalize_silences(silences: tuple[SilenceSpan, ...] | list[SilenceSpan], source_duration: float) -> tuple[SilenceSpan, ...]:
    ordered = sorted(
        (
            SilenceSpan(max(0.0, span.start), min(source_duration, span.end))
            for span in silences
            if span.end > span.start
        ),
        key=lambda span: span.start,
    )
    merged: list[SilenceSpan] = []
    for span in ordered:
        if not merged or span.start > merged[-1].end:
            merged.append(span)
            continue
        previous = merged[-1]
        merged[-1] = SilenceSpan(previous.start, max(previous.end, span.end))
    return tuple(merged)


def _speech_intervals(source_duration: float, silences: tuple[SilenceSpan, ...]) -> tuple[tuple[float, float], ...]:
    intervals: list[tuple[float, float]] = []
    cursor = 0.0
    for silence in silences:
        if silence.start > cursor:
            intervals.append((cursor, silence.start))
        cursor = max(cursor, silence.end)
    if cursor < source_duration:
        intervals.append((cursor, source_duration))
    return tuple(interval for interval in intervals if interval[1] - interval[0] > 0.05)


def _speech_seconds_inside(intervals: tuple[tuple[float, float], ...], start: float, end: float) -> float:
    total = 0.0
    for speech_start, speech_end in intervals:
        overlap_start = max(start, speech_start)
        overlap_end = min(end, speech_end)
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start
    return round(total, 3)
