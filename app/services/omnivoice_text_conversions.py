from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import httpx

from app.config import Settings


MAX_VOICE_NOTE_SECONDS = 60
TARGET_MAX_WORDS = 120
WORDS_PER_MINUTE = 135

FOUNDER_LINKEDIN_VOICE_NOTE_ID = "founder_linkedin_voice_note"

CONVERSION_SYSTEM_PROMPT = """You convert founder-outreach text into a LinkedIn voice note optimized for OmniVoice text-to-speech.

Output ONLY the converted text. No headings, explanations, bullets, quotes, or markdown.

Core rules:
- Keep the voice note under 60 seconds. Aim for 90-120 spoken words.
- Write spoken English, not formal copy.
- Remove marketing language.
- Use contractions wherever natural.
- Break long sentences into short lines and short paragraphs.
- Add natural emphasis pauses using "..." after the founder name, company name, compliment, and value proposition.
- Never claim the founder is selected, shortlisted, qualified, or a strong fit.
- Never fabricate company facts, traction, contact details, pain points, or personalization.
- If no verified observation is provided, keep personalization neutral.
- End with a gentle information CTA, preferably: If you're curious, happy to drop more details.
- Convert abbreviations for pronunciation: US -> U.S.; PE/VC -> P-E V-C; GTM -> G-T-M; CRO -> C-R-O; CMO -> C-M-O; B2B -> B-to-B; NY -> New York.
- Avoid slashes because OmniVoice may read "/" as "slash".
- Use bracketed CMU-style phoneme overrides only for high-risk founder, company, product, or brand names when a pronunciation is supplied.
"""

FOUNDER_LINKEDIN_USER_PROMPT_TEMPLATE = """Rules to use to convert given text into a LinkedIn voice note for OmniVoice input text for founder outreach:

Keep it under 60 seconds.
Aim for 90-120 spoken words.
Cut anything that does not directly improve reply probability.

Remove marketing language:
Instead of: Transformative, Groundbreaking, Innovative, World-class, cutting-edge
Use: Practical, Hands-on, Real, Direct

Replace formal writing with spoken English.
Use contractions everywhere.
Break long sentences.
Use "..." for natural emphasis pauses after the founder name, company name, compliment, and value proposition.
End with a gentle information CTA.
Preferred CTA:
If you're curious, happy to drop more details.

Normalize abbreviations for TTS:
US -> U.S.
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

UNEXPANDED_ABBREVIATIONS = {
    "US": "Use U.S.",
    "PE/VC": "Use P-E V-C.",
    "GTM": "Use G-T-M or go-to-market.",
    "CRO": "Use C-R-O.",
    "CMO": "Use C-M-O.",
    "B2B": "Use B-to-B.",
    "NY": "Use New York.",
}

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


@dataclass(frozen=True)
class ConversionWarning:
    severity: str
    rule: str
    message: str


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
            "No selection language such as strong fit, shortlisted, selected, or qualified.",
            'Use "..." for natural emphasis pauses after the founder name, company name, compliment, and value proposition.',
            "Normalize TTS-risky abbreviations such as PE/VC, B2B, GTM, CMO, CRO, US, and NY.",
            "End with a gentle information CTA.",
        ),
        default_system_prompt=CONVERSION_SYSTEM_PROMPT,
        default_user_prompt_template=FOUNDER_LINKEDIN_USER_PROMPT_TEMPLATE,
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


def validate_converted_text(text: str, inputs: dict[str, str]) -> list[ConversionWarning]:
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

    for phrase in sorted(FORMAL_OR_SELECTION_PHRASES):
        if phrase in lowered:
            warnings.append(ConversionWarning("warning", "salesy_or_selection_language", f"Review phrase: {phrase}."))

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

    if not verified_observation:
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
