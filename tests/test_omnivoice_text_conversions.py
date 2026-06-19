from __future__ import annotations

import unittest

from app.services.omnivoice_text_conversions import (
    FOUNDER_LINKEDIN_VOICE_NOTE_ID,
    build_conversion_prompts,
    estimate_voice_note_seconds,
    get_text_conversion,
    validate_converted_text,
)


class OmniVoiceTextConversionsTest(unittest.TestCase):
    def test_founder_conversion_requires_source_text(self) -> None:
        definition = get_text_conversion(FOUNDER_LINKEDIN_VOICE_NOTE_ID)
        self.assertIsNotNone(definition)
        with self.assertRaisesRegex(Exception, "Source outreach text is required"):
            build_conversion_prompts(definition, {})

    def test_prompt_keeps_missing_observation_neutral(self) -> None:
        definition = get_text_conversion(FOUNDER_LINKEDIN_VOICE_NOTE_ID)
        system, user = build_conversion_prompts(
            definition,
            {
                "source_text": "Hi Anushua Roy, we help funded Indian B2B founders.",
                "founder_name": "Anushua Roy",
                "company_name": "Recro",
            },
        )
        self.assertIn("Founder name: Anushua Roy", user)
        self.assertIn("Company name: Recro", user)
        self.assertIn("Verified observation: not provided; do not invent one", user)
        self.assertIn('using "..."', system)
        self.assertIn('Use "..." for natural emphasis pauses', user)

    def test_warning_flags_unexpanded_abbreviations_and_slash(self) -> None:
        warnings = validate_converted_text(
            "Hi Anushua Roy, this is useful for PE/VC and GTM teams.",
            {"verified_observation": ""},
        )
        rules = {warning.rule for warning in warnings}
        self.assertIn("abbreviation_pronunciation", rules)
        self.assertGreater(estimate_voice_note_seconds("Short text."), 0)

    def test_warning_flags_unverified_personalization(self) -> None:
        warnings = validate_converted_text(
            "Hi Anushua Roy.\n\nWhat you're building really stood out to us.",
            {"verified_observation": ""},
        )
        self.assertTrue(any(warning.rule == "unverified_personalization" for warning in warnings))


if __name__ == "__main__":
    unittest.main()
