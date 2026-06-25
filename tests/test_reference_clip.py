from app.services.audio_export import SilenceSpan, select_reference_clip


def _select(source_duration, silences):
    return select_reference_clip(
        source_duration=source_duration,
        silences=silences,
        min_seconds=3.0,
        max_seconds=10.0,
        boundary_padding_seconds=0.2,
        silence_threshold_db=-35,
        min_pause_seconds=0.25,
    )


def test_sparse_pause_long_source_uses_longest_run_not_tiny_fragment():
    # Regression: a 38.9s sample with one brief early pause used to fall back to
    # the *shortest* speech fragment (~0.3s), collapsing OmniVoice output to 1-2s.
    res = _select(38.9, [SilenceSpan(0.343, 0.6)])
    dur = res.selected_end_seconds - res.selected_start_seconds
    assert 3.0 <= dur <= 10.0, f"reference clip should be 3-10s, got {dur}s"


def test_no_pauses_long_source_takes_max_window():
    res = _select(38.9, [])
    dur = res.selected_end_seconds - res.selected_start_seconds
    assert 3.0 <= dur <= 10.0


def test_short_source_uses_whole_clip():
    res = _select(5.0, [])
    assert res.selected_start_seconds == 0.0
    assert abs(res.selected_end_seconds - 5.0) < 0.01


def test_clean_pause_window_is_preferred():
    # Pauses at ~5s and ~12s -> a clean 3-10s pause-bounded window exists.
    res = _select(20.0, [SilenceSpan(5.0, 5.5), SilenceSpan(12.0, 12.5)])
    dur = res.selected_end_seconds - res.selected_start_seconds
    assert 3.0 <= dur <= 10.0
