from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.audio_export import (
    AudioExportService,
    ReferenceClipSelectionError,
    SilenceSpan,
    select_reference_clip,
)


def make_plan(source_duration: float, silences: list[SilenceSpan]):
    return select_reference_clip(
        source_duration=source_duration,
        silences=silences,
        min_seconds=3.0,
        max_seconds=10.0,
        boundary_padding_seconds=0.2,
        silence_threshold_db=-35,
        min_pause_seconds=0.25,
    )


class ReferenceClipSelectionTest(unittest.TestCase):
    def test_long_recording_selects_one_pause_bounded_clip(self) -> None:
        result = make_plan(
            14.0,
            [
                SilenceSpan(0.0, 0.5),
                SilenceSpan(3.0, 3.5),
                SilenceSpan(11.0, 11.6),
            ],
        )

        self.assertTrue(result.trimmed)
        self.assertEqual(result.selection_mode, "pause_bounded")
        self.assertAlmostEqual(result.selected_start_seconds, 3.3)
        self.assertAlmostEqual(result.selected_end_seconds, 11.2)
        self.assertLessEqual(result.selected_duration_seconds, 10.0)
        self.assertGreater(result.score, 0)
        self.assertIn("fluency", result.score_breakdown)
        self.assertIn("human_like", result.score_breakdown)
        self.assertIn("emotional_expression", result.score_breakdown)

    def test_multiple_valid_clips_keep_best_scored_segment(self) -> None:
        result = make_plan(
            18.0,
            [
                SilenceSpan(0.0, 0.5),
                SilenceSpan(3.0, 3.4),
                SilenceSpan(11.0, 11.4),
                SilenceSpan(15.0, 15.5),
            ],
        )

        self.assertEqual(result.selection_mode, "pause_bounded")
        self.assertEqual(result.candidate_count, 2)
        self.assertAlmostEqual(result.selected_start_seconds, 11.2)
        self.assertAlmostEqual(result.selected_end_seconds, 15.2)
        self.assertAlmostEqual(result.score, result.score_breakdown["overall"])
        self.assertGreater(result.score_breakdown["fluency"], 0)
        self.assertGreater(result.score_breakdown["human_like"], 0)
        self.assertGreater(result.score_breakdown["emotional_expression"], 0)

    def test_equal_overall_scores_keep_first_segment(self) -> None:
        def tied_score(*args):
            start = args[3]
            component_score = 0.9 if start > 10 else 0.5
            return 0.8, {
                "overall": 0.8,
                "fluency": component_score,
                "human_like": component_score,
                "emotional_expression": component_score,
                "boundary": 1.0,
                "duration": 1.0,
            }

        with patch("app.services.audio_export._score_reference_candidate", side_effect=tied_score):
            result = make_plan(
                18.0,
                [
                    SilenceSpan(0.0, 0.5),
                    SilenceSpan(3.0, 3.4),
                    SilenceSpan(11.0, 11.4),
                    SilenceSpan(15.0, 15.5),
                ],
            )

        self.assertEqual(result.candidate_count, 2)
        self.assertAlmostEqual(result.selected_start_seconds, 3.2)
        self.assertAlmostEqual(result.selected_end_seconds, 11.2)
        self.assertEqual(result.score, 0.8)

    def test_long_recording_without_pause_boundaries_keeps_whole_clip(self) -> None:
        result = make_plan(12.0, [])

        self.assertFalse(result.trimmed)
        self.assertEqual(result.selection_mode, "smallest_boundary_clip")
        self.assertEqual(result.selected_start_seconds, 0.0)
        self.assertEqual(result.selected_end_seconds, 12.0)
        self.assertEqual(result.candidate_count, 1)
        self.assertIn("no_clean_3_to_10_second_pause_bounded_window", result.warnings)

    def test_long_recording_without_valid_target_uses_smallest_boundary_clip(self) -> None:
        result = make_plan(
            24.0,
            [
                SilenceSpan(0.0, 0.5),
                SilenceSpan(2.0, 2.5),
                SilenceSpan(15.5, 16.0),
            ],
        )

        self.assertTrue(result.trimmed)
        self.assertEqual(result.selection_mode, "smallest_boundary_clip")
        self.assertAlmostEqual(result.selected_start_seconds, 0.3)
        self.assertAlmostEqual(result.selected_end_seconds, 2.2)
        self.assertGreaterEqual(result.candidate_count, 1)
        self.assertIn("no_clean_3_to_10_second_pause_bounded_window", result.warnings)

    def test_short_recording_without_pause_boundaries_stays_whole(self) -> None:
        result = make_plan(6.0, [])

        self.assertFalse(result.trimmed)
        self.assertEqual(result.selection_mode, "full_recording_no_clear_boundaries")
        self.assertEqual(result.selected_start_seconds, 0.0)
        self.assertEqual(result.selected_end_seconds, 6.0)
        self.assertIn("no_clear_pause_bounded_window", result.warnings)

    def test_silent_recording_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReferenceClipSelectionError, "appears to be silent"):
            make_plan(8.0, [SilenceSpan(0.0, 8.0)])

    def test_parse_silencedetect_handles_trailing_silence(self) -> None:
        service = AudioExportService()
        spans = service._parse_silencedetect_output(
            """
            [silencedetect @ abc] silence_start: 0
            [silencedetect @ abc] silence_end: 0.42 | silence_duration: 0.42
            [silencedetect @ abc] silence_start: 6.4
            """,
            7.5,
        )

        self.assertEqual(spans, (SilenceSpan(0.0, 0.42), SilenceSpan(6.4, 7.5)))


if __name__ == "__main__":
    unittest.main()
