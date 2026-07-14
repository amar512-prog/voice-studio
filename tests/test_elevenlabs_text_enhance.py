from __future__ import annotations

import unittest

from app.services.elevenlabs_text_enhance import build_enhance_prompts


class BuildEnhancePromptsTest(unittest.TestCase):
    def prompts(self, *, model_id: str = "eleven_v3", target_seconds: int = 55) -> tuple[str, str]:
        return build_enhance_prompts(
            text="  We booked 24 meetings; see acme.com/demo.  ",
            context_label="Founder outreach — human-like",
            context_note="Warm, grounded founder outreach with restrained energy and natural pacing.",
            model_id=model_id,
            target_seconds=target_seconds,
        )

    def test_v3_prompt_directs_audio_tags(self) -> None:
        system_prompt, _ = self.prompts()
        self.assertIn("audio tags in square brackets", system_prompt)
        self.assertIn("[warmly]", system_prompt)
        self.assertIn("at most 3 more tags", system_prompt)

    def test_short_target_gets_smaller_tag_budget(self) -> None:
        system_prompt, _ = self.prompts(target_seconds=20)
        self.assertIn("at most 2 more tags", system_prompt)

    def test_non_v3_prompt_forbids_tags(self) -> None:
        system_prompt, _ = self.prompts(model_id="eleven_multilingual_v2")
        self.assertIn("Do not add square-bracket tags", system_prompt)
        self.assertNotIn("audio tags in square brackets", system_prompt)

    def test_normalization_rules_present_for_all_models(self) -> None:
        for model_id in ("eleven_v3", "eleven_multilingual_v2"):
            with self.subTest(model_id=model_id):
                system_prompt, _ = self.prompts(model_id=model_id)
                self.assertIn("Normalize everything that is spoken differently than written", system_prompt)
                self.assertIn("Never leave a slash character", system_prompt)
                self.assertIn("Output only the final spoken text", system_prompt)

    def test_user_prompt_carries_context_target_and_text(self) -> None:
        _, user_prompt = self.prompts()
        self.assertIn("Founder outreach — human-like", user_prompt)
        self.assertIn("restrained energy", user_prompt)
        self.assertIn("about 55 seconds", user_prompt)
        self.assertIn("We booked 24 meetings; see acme.com/demo.", user_prompt)
        self.assertTrue(user_prompt.endswith("acme.com/demo."))


if __name__ == "__main__":
    unittest.main()
