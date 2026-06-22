from __future__ import annotations

import unittest

from app.services.omnivoice_text_conversions import (
    FOUNDER_LINKEDIN_VOICE_NOTE_ID,
    REVVOICE_EMOTIONAL_VOICE_NOTE_ID,
    TextConversionError,
    WeTextEnglishProcessor,
    apply_wetext_processing,
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

    def test_revvoice_emotional_conversion_uses_supplied_prompt_and_source_only(self) -> None:
        definition = get_text_conversion(REVVOICE_EMOTIONAL_VOICE_NOTE_ID)
        self.assertIsNotNone(definition)
        self.assertEqual([field.id for field in definition.input_fields], ["source_text"])

        system, user = build_conversion_prompts(
            definition,
            {
                "source_text": (
                    "Hi Anushua Roy, We're a NY-based PE/VC fund. We came across Recro "
                    "and think you'd be a strong fit."
                ),
            },
        )

        self.assertIn("# OmniVoice Emotional Voice-Note Conversion", system)
        self.assertIn("prefer stronger emotional delivery", system)
        self.assertIn("Return only the rewritten spoken version.", system)
        self.assertIn("US -> U-S", system)
        self.assertIn("CRO -> C-R-O", system)
        self.assertIn("CMO -> C-M-O", system)
        self.assertEqual(
            user,
            (
                "text:\n"
                "Hi Anushua Roy, We're a NY-based PE/VC fund. We came across Recro "
                "and think you'd be a strong fit.\n"
            ),
        )

    def test_revvoice_emotional_validation_allows_prompt_requested_amplification(self) -> None:
        warnings = validate_converted_text(
            (
                "Hi Anushua Roy, we were genuinely impressed by Recro. "
                "We believe you'd be a strong fit for the shortlisted cohort."
            ),
            {},
            profile="emotional_voice_note",
        )
        rules = {warning.rule for warning in warnings}
        self.assertNotIn("salesy_or_selection_language", rules)
        self.assertNotIn("inferred_benefit", rules)
        self.assertNotIn("unverified_personalization", rules)

    def test_revvoice_emotional_validation_keeps_shared_duration_gate(self) -> None:
        warnings = validate_converted_text(
            " ".join(["word"] * 140),
            {},
            profile="emotional_voice_note",
        )
        self.assertTrue(any(warning.rule == "voice_note_duration" for warning in warnings))

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
        self.assertIn('Use "..." for natural emphasis pauses after supplied names', user)
        for prompt in (system, user):
            self.assertIn("Only delete, shorten, normalize, or rephrase supplied statements", prompt)
            self.assertIn("Never add inferred benefits, outcomes, suitability claims", prompt)
            self.assertIn('Do not add phrases beginning with "We believe", "This could", or "This would"', prompt)
            self.assertIn('Remove redundant audience references such as "for your company"', prompt)
            self.assertIn("Rewrite for text-to-speech.", prompt)
            self.assertIn("- Preserve wording.", prompt)
            self.assertIn("- Add punctuation for natural speech.", prompt)
            self.assertIn("- Use commas for short pauses.", prompt)
            self.assertIn("- Use semicolons for medium pauses.", prompt)
            self.assertIn("- Use periods for sentence breaks.", prompt)
            self.assertIn("- Use ellipses only for emphasis.", prompt)
            self.assertIn("- Do not change meaning.", prompt)
            self.assertIn("Use line breaks only for readability", prompt)
            self.assertIn("Do not rely on \\n or \\n\\n to create an audible pause", prompt)
            self.assertIn("US -> U-S", prompt)

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

    def test_warning_flags_inferred_benefit_conclusion(self) -> None:
        warnings = validate_converted_text(
            "We believe this could be a practical way to accelerate your market entry.",
            {"verified_observation": ""},
        )
        self.assertTrue(any(warning.rule == "inferred_benefit" for warning in warnings))

    def test_llm_output_is_processed_by_wetext_for_speech_readiness(self) -> None:
        wetext_processing = apply_wetext_processing(
            "Call me at 3:30 PM.",
            lambda text: text.replace("3:30 PM", "three thirty p m"),
        )

        self.assertTrue(wetext_processing.changed)
        self.assertEqual(wetext_processing.engine, "WeTextProcessing English TN")
        self.assertEqual(wetext_processing.original_text, "Call me at 3:30 PM.")
        self.assertEqual(wetext_processing.text, "Call me at three thirty p m.")

    def test_prompt_keeps_original_natural_language_source(self) -> None:
        definition = get_text_conversion(FOUNDER_LINKEDIN_VOICE_NOTE_ID)
        _, user = build_conversion_prompts(
            definition,
            {
                "source_text": "Call me at 3:30 PM about a $25,000 budget.",
                "founder_name": "Maya Patel",
            },
        )

        self.assertIn("Call me at 3:30 PM about a $25,000 budget.", user)

    def test_empty_wetext_result_is_rejected(self) -> None:
        with self.assertRaisesRegex(TextConversionError, "returned empty converted text"):
            apply_wetext_processing("Hello.", lambda _text: "")

    def test_wetext_processor_preserves_line_breaks(self) -> None:
        class UppercaseNormalizer:
            def normalize(self, text: str) -> str:
                return text.upper()

        processor = WeTextEnglishProcessor()
        processor._normalizer = UppercaseNormalizer()

        self.assertEqual(
            processor.normalize("First line.\n\nSecond line."),
            "FIRST LINE.\n\nSECOND LINE.",
        )

    def test_wetext_processor_preserves_tts_safe_tokens(self) -> None:
        class RegressingNormalizer:
            def normalize(self, text: str) -> str:
                return text.replace("U.S.", "US")

        processor = WeTextEnglishProcessor()
        processor._normalizer = RegressingNormalizer()

        text = (
            "The U-S team supports P-E V-C and B-to-B founders with G-T-M planning. "
            "Ask the C-R-O or C-M-O. [M EY1 Y AH0]"
        )
        self.assertEqual(processor.normalize(text), text)

    def test_wetext_processor_does_not_hide_raw_us_warning(self) -> None:
        class IdentityNormalizer:
            def normalize(self, text: str) -> str:
                return text

        processor = WeTextEnglishProcessor()
        processor._normalizer = IdentityNormalizer()
        output = processor.normalize("The US team is growing.")

        self.assertEqual(output, "The US team is growing.")
        warnings = validate_converted_text(output, {"verified_observation": ""})
        abbreviation_warning = next(warning for warning in warnings if warning.rule == "abbreviation_pronunciation")
        self.assertEqual(abbreviation_warning.message, "US is not voice-normalized. Use U-S.")


if __name__ == "__main__":
    unittest.main()
