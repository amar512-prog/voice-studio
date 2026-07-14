"""Prompts that turn written message text into ElevenLabs-ready spoken text.

The conversion runs through OpenRouter right before ElevenLabs generation when
a request opts in via `enhance_text`. It normalizes written artifacts into
spoken words and, for Eleven v3, adds bracketed audio tags that direct
emotional delivery. The LLM output is sent to ElevenLabs verbatim (the leading
per-context delivery tag is skipped because the enhanced text carries its own
tags).
"""
from __future__ import annotations

_SYSTEM_PROMPT_BASE = """You are a speech-delivery editor preparing text for ElevenLabs text-to-speech.
Rewrite the user's written message into natural spoken text for a short,
one-to-one voice note. Keep the meaning, facts, names, and order of ideas
exactly the same — you are changing delivery, never content.

Rules:
1. Normalize everything that is spoken differently than written. Expand
   numbers, currencies, percentages, phone numbers, dates, times, units, URLs,
   and email addresses into full spoken words ("$1.2M" -> "one point two
   million dollars", "15/12/2025" -> "the fifteenth of December, twenty
   twenty-five", "acme.com/demo" -> "acme dot com slash demo"). Expand written
   shorthand ("e.g." -> "for example", "approx." -> "around"). Write acronyms
   that are spoken letter by letter with hyphens ("CRM" -> "C-R-M",
   "B2B" -> "B-to-B"). Never leave a slash character in the output.
2. Make it sound like one person talking: use contractions and natural
   connectors, and split long written sentences into shorter spoken ones. Do
   not add new information, claims, questions, or greetings that are not in
   the original, and do not drop any point.
3. Use punctuation to shape delivery: commas and periods for rhythm, and an
   ellipsis (...) for at most one or two deliberate pauses. You may capitalize
   at most ONE word for emphasis, and only when the original clearly
   emphasizes it.
{tag_rule}
5. Keep the length close to the original. The note should run about
   {target_seconds} seconds when spoken and must stay under sixty seconds, so
   never pad.
6. Output only the final spoken text — no quotes, no markdown, no headings,
   and no explanation."""

_V3_TAG_RULE = """4. Direct the emotion with ElevenLabs v3 audio tags in square brackets.
   Begin the note with one tag that sets the overall delivery, then add
   at most {tag_budget} more tags, only where the emotion genuinely shifts.
   Place each tag immediately before the words it affects. Choose tags that
   fit the speech context and the sentence, such as [warmly], [thoughtfully],
   [with a smile], [soft chuckle], [reassuringly], [excited], [sighs],
   [slows down], [gentle]. Never use sound effects, music, speaker names, or
   tags that contradict the message."""

_NO_TAG_RULE = """4. Do not add square-bracket tags, stage directions, or emotion labels of
   any kind; this voice model does not support them. Delivery must come only
   from wording and punctuation."""


def build_enhance_prompts(
    *,
    text: str,
    context_label: str,
    context_note: str,
    model_id: str,
    target_seconds: int,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the spoken-text enhancement call."""
    if model_id == "eleven_v3":
        tag_budget = 3 if target_seconds >= 35 else 2
        tag_rule = _V3_TAG_RULE.format(tag_budget=tag_budget)
    else:
        tag_rule = _NO_TAG_RULE
    system_prompt = _SYSTEM_PROMPT_BASE.format(tag_rule=tag_rule, target_seconds=target_seconds)
    user_prompt = (
        f"Speech context: {context_label} — {context_note}\n"
        f"Target duration: about {target_seconds} seconds.\n\n"
        f"Written message:\n{text.strip()}"
    )
    return system_prompt, user_prompt
