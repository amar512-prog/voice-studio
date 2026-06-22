from __future__ import annotations

from dataclasses import dataclass
import re
from threading import Lock
from typing import Any

import httpx

from app.config import Settings


MAX_VOICE_NOTE_SECONDS = 60
TARGET_MAX_WORDS = 120
WORDS_PER_MINUTE = 135

FOUNDER_LINKEDIN_VOICE_NOTE_ID = "founder_linkedin_voice_note"
REVVOICE_EMOTIONAL_VOICE_NOTE_ID = "revvoice_emotional_voice_note"

CONVERSION_SYSTEM_PROMPT = """You convert founder-outreach text into a LinkedIn voice note optimized for OmniVoice text-to-speech.

Output ONLY the converted text. No headings, explanations, bullets, quotes, or markdown.

Core rules:
- Keep the voice note under 60 seconds. Aim for 90-120 spoken words.
- Write spoken English, not formal copy.
- Remove marketing language.
- Use contractions wherever natural.
- Break long sentences into short lines and short paragraphs.
- Add natural emphasis pauses using "..." after supplied names, observations, or value propositions when present.
Rewrite for text-to-speech.

Rules:
- Preserve wording.
- Add punctuation for natural speech.
- Use commas for short pauses.
- Use semicolons for medium pauses.
- Use periods for sentence breaks.
- Use ellipses only for emphasis.
- Do not change meaning.
- Use line breaks only for readability. Do not rely on \\n or \\n\\n to create an audible pause; use punctuation for pacing.
- Never claim the founder is selected, shortlisted, qualified, or a strong fit.
- Never fabricate company facts, traction, contact details, pain points, or personalization.
- Only delete, shorten, normalize, or rephrase supplied statements.
- Never add inferred benefits, outcomes, suitability claims, or persuasive conclusions.
- Use a value proposition only when one is explicitly present in the source text.
- Do not add phrases beginning with "We believe", "This could", or "This would".
- Remove redundant audience references such as "for your company" when the sentence remains clear without them.
- If no verified observation is provided, keep personalization neutral.
- End with a gentle information CTA, preferably: If you're curious, happy to drop more details.
- Convert abbreviations for pronunciation: US -> U-S; PE/VC -> P-E V-C; GTM -> G-T-M; CRO -> C-R-O; CMO -> C-M-O; B2B -> B-to-B; NY -> New York.
- Avoid slashes because OmniVoice may read "/" as "slash".
- Use bracketed CMU-style phoneme overrides only for high-risk founder, company, product, or brand names when a pronunciation is supplied.
"""

FOUNDER_LINKEDIN_USER_PROMPT_TEMPLATE = """Rules to use to convert given text into a LinkedIn voice note for OmniVoice input text for founder outreach:

Keep it under 60 seconds.
Aim for 90-120 spoken words.
Cut anything that does not directly improve reply probability.

Remove marketing language:
Instead of: Transformative, Groundbreaking, Innovative, World-class, cutting-edge
Use plain spoken wording already supported by the source text.

Replace formal writing with spoken English.
Use contractions everywhere.
Break long sentences.
Use "..." for natural emphasis pauses after supplied names, observations, or value propositions when present.
Rewrite for text-to-speech.

Rules:
- Preserve wording.
- Add punctuation for natural speech.
- Use commas for short pauses.
- Use semicolons for medium pauses.
- Use periods for sentence breaks.
- Use ellipses only for emphasis.
- Do not change meaning.
Use line breaks only for readability.
Do not rely on \\n or \\n\\n to create an audible pause; use punctuation for pacing.
Only delete, shorten, normalize, or rephrase supplied statements.
Never add inferred benefits, outcomes, suitability claims, or persuasive conclusions.
Use a value proposition only when one is explicitly present in the source text.
Do not add phrases beginning with "We believe", "This could", or "This would".
Remove redundant audience references such as "for your company" when the sentence remains clear without them.
End with a gentle information CTA.
Preferred CTA:
If you're curious, happy to drop more details.

Normalize abbreviations for TTS:
US -> U-S
PE/VC -> P-E V-C
GTM -> G-T-M
CRO -> C-R-O
CMO -> C-M-O
B2B -> B-to-B
NY -> New York

Input fields:
Founder name: {{founder_name}}
Company name: {{company_name}}
Verified observation: {{verified_observation}}
Pronunciation notes: {{pronunciation_notes}}

Text to convert exactly; do not summarize or add new facts:
{{source_text}}
"""

REVVOICE_EMOTIONAL_SYSTEM_PROMPT = """# OmniVoice Emotional Voice-Note Conversion

You are a speech-first editor for an expressive TTS model called OmniVoice.

Your goal is not to preserve the exact wording of the source text.

Your goal is to create the most natural, emotionally engaging, and human-sounding voice note possible while preserving the original intent, facts, and message.

The output should sound like a thoughtful professional speaking directly to another person.

It should never sound like someone reading an email, LinkedIn message, marketing copy, or corporate communication aloud.

## Primary Objective

Optimize for spoken delivery.

Prioritize:

1. Emotional authenticity
2. Natural conversational flow
3. Human connection
4. Listener engagement
5. Preservation of core meaning

Do not prioritize preserving the exact wording, sentence structure, or level of explicitness used in the original text.

## Meaning Preservation

Preserve:

* core intent
* factual claims
* names
* dates
* numbers
* relationships
* opportunities being described

You may rewrite, reorganize, expand, or reframe language as needed for natural speech.

The output should communicate the same message, not necessarily the same wording.

## Emotional Amplification

OmniVoice performs best when emotional intent is explicit.

When positive intent is implied, you should surface that intent naturally.

You may strengthen implied emotions including:

* interest
* appreciation
* excitement
* curiosity
* confidence
* admiration
* encouragement
* enthusiasm
* belief in fit

The goal is emotional clarity, not literal translation.

## Human Connection

Make the recipient feel intentionally selected and personally noticed.

Favor language that conveys:

* genuine interest
* thoughtful consideration
* personal attention
* authentic curiosity

The listener should feel that the speaker specifically wanted to reach out to them.

## Voice Note Style

Write as if the speaker is sending a personal voice note.

Use:

* contractions
* conversational phrasing
* natural spoken transitions
* occasional reflective pauses
* short spoken sentences

Avoid:

* corporate language
* marketing language
* written-language complexity
* formal business writing
* excessive jargon

## Abbreviation Pronunciation

Normalize these abbreviations for natural TTS pronunciation:

* US -> U-S
* CRO -> C-R-O
* CMO -> C-M-O

## Spoken Rhythm

Break long thoughts into smaller spoken units.

Use punctuation to support delivery:

* commas for brief pauses
* em dashes for transitions
* occasional ellipses for reflection
* paragraph breaks between major ideas

The text should feel easy to perform naturally.

## Value Elaboration

When benefits or outcomes are stated briefly, you may make them more concrete and listener-friendly.

You may explain why something matters if that explanation is already implied by the original text.

Do not introduce new factual claims.

## Outreach Messages

For recruiting, partnerships, networking, fundraising, business development, or founder outreach:

Lead with genuine interest before discussing the opportunity.

The conversation should feel exploratory rather than transactional.

The recipient should feel respected, chosen, and thoughtfully approached.

## Emotional Delivery Rule

When choosing between:

* literal wording fidelity

and

* stronger emotional delivery that preserves the same underlying intent

prefer stronger emotional delivery.

The output should sound excellent when spoken by OmniVoice.

## Output Requirements

Return only the rewritten spoken version.

Do not explain changes.

Do not include notes.

Do not include analysis.

Do not include formatting instructions.

Do not include labels.

Do not include stage directions.

Do not include SSML.
"""

REVVOICE_EMOTIONAL_USER_PROMPT_TEMPLATE = """text:
{{source_text}}
"""

MARKETING_WORDS = {
    "transformative",
    "groundbreaking",
    "innovative",
    "world-class",
    "world class",
    "cutting-edge",
    "cutting edge",
    "revolutionary",
    "disruptive",
}

FORMAL_OR_SELECTION_PHRASES = {
    "work closely with",
    "shortlisted",
    "strong fit",
    "qualified",
    "selected",
    "unique opportunity",
    "great match",
}

INFERRED_BENEFIT_PHRASES = {
    "we believe",
    "this could",
    "this would",
    "accelerate your",
}

UNEXPANDED_ABBREVIATIONS = {
    "US": "Use U-S.",
    "PE/VC": "Use P-E V-C.",
    "GTM": "Use G-T-M or go-to-market.",
    "CRO": "Use C-R-O.",
    "CMO": "Use C-M-O.",
    "B2B": "Use B-to-B.",
    "NY": "Use New York.",
}

WETEXT_PROTECTED_TTS_TOKENS = (
    "U-S",
    "U.S.",
    "P-E V-C",
    "G-T-M",
    "C-R-O",
    "C-M-O",
    "B-to-B",
)
WETEXT_PROTECTED_PATTERN = re.compile(
    "("
    + "|".join(re.escape(token) for token in WETEXT_PROTECTED_TTS_TOKENS)
    + r"|\[[A-Z0-9 ]+\])"
)

CONTRACTION_MISSES = {
    "we are": "Use we're.",
    "we would": "Use we'd.",
    "it is": "Use it's.",
    "that is": "Use that's.",
    "you are": "Use you're.",
    "you would": "Use you'd.",
    "they are": "Use they're.",
}

VAGUE_OR_UNVERIFIED_COMPLIMENTS = {
    "we were impressed",
    "really impressed",
    "stood out",
    "love what you're building",
    "big fan",
    "admire what you're building",
    "the way you're building",
}


@dataclass(frozen=True)
class ConversionInputField:
    id: str
    label: str
    control: str
    required: bool
    placeholder: str
    help: str
    empty_value: str = "not provided"


@dataclass(frozen=True)
class TextConversionDefinition:
    id: str
    label: str
    purpose: str
    description: str
    input_fields: tuple[ConversionInputField, ...]
    output_rules: tuple[str, ...]
    default_system_prompt: str
    default_user_prompt_template: str
    validation_profile: str = "founder_outreach"


@dataclass(frozen=True)
class ConversionWarning:
    severity: str
    rule: str
    message: str


@dataclass(frozen=True)
class WeTextProcessingResult:
    engine: str
    original_text: str
    text: str

    @property
    def changed(self) -> bool:
        return self.original_text != self.text


class TextConversionError(RuntimeError):
    pass


TEXT_CONVERSIONS = (
    TextConversionDefinition(
        id=FOUNDER_LINKEDIN_VOICE_NOTE_ID,
        label="Founder outreach LinkedIn voice note",
        purpose="Turn founder outreach copy into a warm, low-pressure LinkedIn voice-note script for OmniVoice.",
        description=(
            "Use after the company and founder are already qualified. The conversion preserves supplied facts, "
            "keeps personalization neutral unless a verified observation is provided, and prepares the text for "
            "OmniVoice pronunciation checks."
        ),
        input_fields=(
            ConversionInputField(
                id="source_text",
                label="Source outreach text",
                control="textarea",
                required=True,
                placeholder="Hi Anushua Roy, We're a NY-based PE/VC fund...",
                help="Paste only the facts and copy you are willing to send. Do not include unverified claims.",
            ),
            ConversionInputField(
                id="founder_name",
                label="Founder name",
                control="text",
                required=False,
                placeholder="Anushua Roy",
                help="Used for greeting and pronunciation context.",
            ),
            ConversionInputField(
                id="company_name",
                label="Company name",
                control="text",
                required=False,
                placeholder="Recro",
                help="Used for neutral personalization and pronunciation context.",
            ),
            ConversionInputField(
                id="verified_observation",
                label="Verified observation",
                control="textarea",
                required=False,
                placeholder="Publicly verified fact about the founder or company.",
                help="Leave blank if not verified; the model is instructed not to invent one.",
                empty_value="not provided; do not invent one",
            ),
            ConversionInputField(
                id="pronunciation_notes",
                label="Pronunciation notes",
                control="textarea",
                required=False,
                placeholder="Priya Shah: [P R IY1 Y AH0 SH AA1]",
                help="Optional verified CMU-style overrides for risky names or brands.",
                empty_value="not provided; preserve names as written and do not guess CMU phonemes",
            ),
        ),
        output_rules=(
            "Under 60 seconds, usually 90-120 spoken words.",
            "No fabricated facts, pain points, traction, or personalization.",
            "No inferred benefits, outcomes, suitability claims, or persuasive conclusions.",
            "No selection language such as strong fit, shortlisted, selected, or qualified.",
            'Use "..." for natural emphasis pauses after supplied names, observations, or value propositions.',
            "Normalize TTS-risky abbreviations such as PE/VC, B2B, GTM, CMO, CRO, US, and NY.",
            "End with a gentle information CTA.",
        ),
        default_system_prompt=CONVERSION_SYSTEM_PROMPT,
        default_user_prompt_template=FOUNDER_LINKEDIN_USER_PROMPT_TEMPLATE,
    ),
    TextConversionDefinition(
        id=REVVOICE_EMOTIONAL_VOICE_NOTE_ID,
        label="RevVoice emotional voice note",
        purpose="Rewrite source text into a natural, emotionally engaging spoken voice note for RevVoice.",
        description=(
            "Use when spoken delivery and human connection matter more than literal wording. The conversion may "
            "reorganize or emotionally amplify implied intent while preserving the supplied facts and core message."
        ),
        input_fields=(
            ConversionInputField(
                id="source_text",
                label="Source text",
                control="textarea",
                required=True,
                placeholder=(
                    "Hi Anushua Roy, We're a NY-based PE/VC fund. We work closely with funded Indian B2B founders "
                    "expanding into the US..."
                ),
                help="Paste the source message. The conversion may rewrite its wording, but must preserve its facts and intent.",
            ),
        ),
        output_rules=(
            "Return only the rewritten spoken version.",
            "Preserve core intent, facts, names, dates, numbers, relationships, and opportunities.",
            "Prioritize emotional authenticity, conversational flow, human connection, and listener engagement.",
            "Make implied positive intent explicit without introducing new factual claims.",
            "Use contractions, short spoken sentences, natural transitions, and performance-friendly punctuation.",
            "Avoid corporate, marketing, overly formal, and jargon-heavy language.",
            "Do not include notes, analysis, labels, stage directions, formatting instructions, SSML, or explanations.",
        ),
        default_system_prompt=REVVOICE_EMOTIONAL_SYSTEM_PROMPT,
        default_user_prompt_template=REVVOICE_EMOTIONAL_USER_PROMPT_TEMPLATE,
        validation_profile="emotional_voice_note",
    ),
)


def list_text_conversions(*, configured: bool, model: str, default_max_tokens: int) -> list[dict[str, Any]]:
    return [
        {
            "id": definition.id,
            "label": definition.label,
            "purpose": definition.purpose,
            "description": definition.description,
            "configured": configured,
            "model": model,
            "default_max_tokens": default_max_tokens,
            "input_fields": [field.__dict__ for field in definition.input_fields],
            "output_rules": list(definition.output_rules),
            "default_system_prompt": definition.default_system_prompt,
            "default_user_prompt_template": definition.default_user_prompt_template,
        }
        for definition in TEXT_CONVERSIONS
    ]


def get_text_conversion(conversion_id: str) -> TextConversionDefinition | None:
    return next((definition for definition in TEXT_CONVERSIONS if definition.id == conversion_id), None)


class WeTextEnglishProcessor:
    def __init__(self) -> None:
        self._normalizer: Any | None = None
        self._lock = Lock()

    def normalize(self, text: str) -> str:
        with self._lock:
            if self._normalizer is None:
                try:
                    from tn.english.normalizer import Normalizer as EnglishNormalizer
                except ImportError as exc:
                    raise TextConversionError(
                        "WeTextProcessing is not installed; speech-readiness processing is unavailable."
                    ) from exc
                self._normalizer = EnglishNormalizer(overwrite_cache=False)

            try:
                parts = re.split(r"(\r?\n+)", text)
                normalized = "".join(
                    part
                    if re.fullmatch(r"\r?\n+", part)
                    else self._normalize_line(part)
                    for part in parts
                    if part
                ).strip()
            except Exception as exc:
                raise TextConversionError(f"WeTextProcessing failed to normalize converted text: {exc!s}") from exc

        if not normalized:
            raise TextConversionError("WeTextProcessing returned empty converted text.")
        return normalized

    def _normalize_line(self, text: str) -> str:
        parts = WETEXT_PROTECTED_PATTERN.split(text)
        return "".join(
            part if WETEXT_PROTECTED_PATTERN.fullmatch(part) else self._normalize_unprotected(part)
            for part in parts
            if part
        )

    def _normalize_unprotected(self, text: str) -> str:
        leading = re.match(r"^\s*", text).group()
        trailing = re.search(r"\s*$", text).group()
        core_end = len(text) - len(trailing) if trailing else len(text)
        core = text[len(leading):core_end]
        if not core:
            return text
        return f"{leading}{str(self._normalizer.normalize(core)).strip()}{trailing}"


def apply_wetext_processing(
    text: str,
    normalize: Any,
) -> WeTextProcessingResult:
    original_text = text.strip()
    normalized_text = str(normalize(original_text)).strip()
    if not normalized_text:
        raise TextConversionError("WeTextProcessing returned empty converted text.")

    return WeTextProcessingResult(
        engine="WeTextProcessing English TN",
        original_text=original_text,
        text=normalized_text,
    )


def build_conversion_prompts(
    definition: TextConversionDefinition,
    inputs: dict[str, str],
    prompt_override: dict[str, str] | None = None,
) -> tuple[str, str]:
    if prompt_override:
        system_prompt = str(prompt_override.get("system_prompt") or "").strip()
        user_prompt = str(prompt_override.get("user_prompt") or "").strip()
        if not system_prompt or not user_prompt:
            raise TextConversionError("Edited prompts must include both system_prompt and user_prompt.")
        return system_prompt, user_prompt

    values = normalized_input_values(definition, inputs)
    user_prompt = definition.default_user_prompt_template
    for field in definition.input_fields:
        user_prompt = user_prompt.replace(f"{{{{{field.id}}}}}", values[field.id])
    return definition.default_system_prompt, user_prompt


def normalized_input_values(definition: TextConversionDefinition, inputs: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in definition.input_fields:
        value = str(inputs.get(field.id) or "").strip()
        if field.required and not value:
            raise TextConversionError(f"{field.label} is required.")
        values[field.id] = value or field.empty_value
    return values


def count_spoken_words(text: str) -> int:
    normalized = re.sub(r"\[[A-Z0-9 ]+\]", " phoneme ", text)
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", normalized))


def estimate_voice_note_seconds(text: str) -> float:
    words = count_spoken_words(text)
    spoken_seconds = words / WORDS_PER_MINUTE * 60
    blank_line_count = len(re.findall(r"\n\s*\n", text))
    ellipsis_count = text.count("...")
    return round(spoken_seconds + blank_line_count * 0.45 + ellipsis_count * 0.35, 1)


def format_for_voice_pacing(text: str) -> str:
    stripped = text.strip().strip('"')
    if not stripped:
        return stripped

    placeholders = {
        "U.S.": "U<<DOT>>S<<DOT>>",
        "P-E V-C": "P-E V-C",
        "G-T-M": "G-T-M",
        "C-M-O": "C-M-O",
        "C-R-O": "C-R-O",
    }
    protected = stripped
    for source, replacement in placeholders.items():
        protected = protected.replace(source, replacement)

    protected = re.sub(r"([.!?])[ \t]+(?=[A-Z0-9\\[])", r"\1\n", protected)
    protected = re.sub(r"\n{3,}", "\n\n", protected)

    for source, replacement in placeholders.items():
        protected = protected.replace(replacement, source)

    protected = re.sub(r"(U\.S\.)[ \t]+(?=[A-Z0-9\[])", r"\1\n", protected)
    return protected.strip()


def validate_converted_text(
    text: str,
    inputs: dict[str, str],
    *,
    profile: str = "founder_outreach",
) -> list[ConversionWarning]:
    warnings: list[ConversionWarning] = []
    stripped = text.strip()
    lowered = stripped.lower()
    verified_observation = str(inputs.get("verified_observation") or "").strip()

    if not stripped:
        return [ConversionWarning("error", "non_empty", "Conversion returned empty text.")]

    first_line = stripped.splitlines()[0].strip().lower()
    if first_line.startswith(("here", "converted", "output", "voice note", "analysis", "recommendation")):
        warnings.append(ConversionWarning("error", "output_only", "Remove explanation or headings from the output."))
    if "```" in stripped:
        warnings.append(ConversionWarning("error", "output_only", "Remove markdown code fences from the output."))

    for word in sorted(MARKETING_WORDS):
        if word in lowered:
            warnings.append(ConversionWarning("error", "marketing_language", f"Remove marketing word: {word}."))

    if profile == "founder_outreach":
        for phrase in sorted(FORMAL_OR_SELECTION_PHRASES):
            if phrase in lowered:
                warnings.append(ConversionWarning("warning", "salesy_or_selection_language", f"Review phrase: {phrase}."))

        for phrase in sorted(INFERRED_BENEFIT_PHRASES):
            if phrase in lowered:
                warnings.append(
                    ConversionWarning(
                        "warning",
                        "inferred_benefit",
                        f"Review possible inferred benefit or persuasive conclusion: {phrase}.",
                    )
                )

    for abbreviation, fix in UNEXPANDED_ABBREVIATIONS.items():
        if re.search(rf"(?<![A-Z-]){re.escape(abbreviation)}(?![A-Z-])", stripped):
            warnings.append(ConversionWarning("error", "abbreviation_pronunciation", f"{abbreviation} is not voice-normalized. {fix}"))

    for phrase, fix in sorted(CONTRACTION_MISSES.items()):
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            warnings.append(ConversionWarning("warning", "contractions", f"Found '{phrase}'. {fix}"))

    sentence_candidates = re.split(r"(?<=[.!?])\s+", stripped.replace("\n", " "))
    for sentence in sentence_candidates:
        words = re.findall(r"[A-Za-z0-9'-]+", sentence)
        if len(words) > 24:
            warnings.append(ConversionWarning("warning", "sentence_length", f"Long sentence has {len(words)} words; break it up."))

    seconds = estimate_voice_note_seconds(stripped)
    words = count_spoken_words(stripped)
    if seconds > MAX_VOICE_NOTE_SECONDS:
        warnings.append(
            ConversionWarning(
                "error",
                "voice_note_duration",
                f"Estimated duration is {seconds:.1f}s with {words} spoken words. Keep under {MAX_VOICE_NOTE_SECONDS}s.",
            )
        )
    elif words > TARGET_MAX_WORDS:
        warnings.append(
            ConversionWarning(
                "warning",
                "voice_note_length",
                f"Estimated duration is {seconds:.1f}s with {words} spoken words. Aim for {TARGET_MAX_WORDS} words or fewer.",
            )
        )

    if profile == "founder_outreach" and not verified_observation:
        for phrase in sorted(VAGUE_OR_UNVERIFIED_COMPLIMENTS):
            if phrase in lowered:
                warnings.append(
                    ConversionWarning(
                        "warning",
                        "unverified_personalization",
                        f"Vague compliment may need a verified observation: {phrase}.",
                    )
                )

    return warnings


class OpenRouterTextConversionClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.openrouter_api_key)

    async def convert(self, *, system_prompt: str, user_prompt: str, max_tokens: int | None = None) -> str:
        if not self.settings.openrouter_api_key:
            raise TextConversionError("OPENROUTER_API_KEY is not configured for text conversion.")

        payload = {
            "model": self.settings.openrouter_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens or self.settings.openrouter_max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-OpenRouter-Title": "Voice Message Studio Text Conversion",
        }
        try:
            async with httpx.AsyncClient(timeout=float(self.settings.openrouter_timeout_seconds)) as client:
                response = await client.post(
                    f"{self.settings.openrouter_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise TextConversionError(f"OpenRouter request failed: {exc!s} ({type(exc).__name__}).") from exc

        if response.status_code >= 400:
            raise TextConversionError(_provider_error(response))

        data = response.json()
        content = _extract_content(data)
        return format_for_voice_pacing(content)


def _extract_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise TextConversionError("OpenRouter returned an unexpected response shape.") from exc

    if isinstance(content, list):
        content = "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
        )
    if not isinstance(content, str) or not content.strip():
        raise TextConversionError("OpenRouter returned an empty conversion.")
    return content.strip()


def _provider_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = response.text[:500]
    return f"OpenRouter error {response.status_code}: {body}"
