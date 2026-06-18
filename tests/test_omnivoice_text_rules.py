from __future__ import annotations

import unittest

from app.services.omnivoice_text_rules import (
    OmniVoiceTextRuleError,
    check_omnivoice_text,
    require_omnivoice_text_ready,
)


class OmniVoiceTextRulesTest(unittest.TestCase):
    def test_plain_text_is_ready(self) -> None:
        result = check_omnivoice_text("We help private equity teams find opportunities.")
        self.assertTrue(result.ready)
        self.assertEqual(result.suggested_text, result.original_text)
        self.assertEqual(result.errors, ())

    def test_uppercase_shorthand_gets_a_reviewable_suggestion(self) -> None:
        result = check_omnivoice_text("This is useful for PE/VC teams.")
        self.assertFalse(result.ready)
        self.assertEqual(result.suggested_text, "This is useful for PE VC teams.")
        self.assertEqual(result.changes[0].rule, "uppercase_shorthand")

    def test_date_gets_spoken_form_suggestion(self) -> None:
        result = check_omnivoice_text("Let us speak on 15/12/2025.")
        self.assertFalse(result.ready)
        self.assertEqual(result.suggested_text, "Let us speak on 15th December, 2025.")
        self.assertEqual(result.changes[0].rule, "date_slash")

    def test_invalid_date_stays_unresolved(self) -> None:
        result = check_omnivoice_text("The date says 31/02/2025.")
        self.assertFalse(result.ready)
        self.assertEqual(result.suggested_text, result.original_text)
        self.assertTrue(any("could not be corrected" in error for error in result.errors))

    def test_url_stays_unresolved(self) -> None:
        result = check_omnivoice_text("Visit https://example.com/a/b.")
        self.assertFalse(result.ready)
        self.assertIn("/", result.suggested_text)
        self.assertTrue(any("could not be corrected" in error for error in result.errors))

    def test_generation_guard_includes_suggestion(self) -> None:
        with self.assertRaisesRegex(OmniVoiceTextRuleError, "PE VC"):
            require_omnivoice_text_ready("Built for PE/VC teams.")


if __name__ == "__main__":
    unittest.main()
