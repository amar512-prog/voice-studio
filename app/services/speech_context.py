from app.models import SpeechContext


CONTEXT_LABELS: dict[SpeechContext, str] = {
    "outreach_conversational": "Outreach conversational",
    "founder_outreach_human": "Founder outreach — human-like",
    "customer_support": "Customer support",
    "narration": "Narration",
    "announcement": "Announcement",
    "character_dialogue": "Character dialogue",
    "dramatic_storytelling": "Dramatic storytelling",
}


CONTEXT_NOTES: dict[SpeechContext, str] = {
    "outreach_conversational": "Warm, natural, concise, one-to-one delivery.",
    "founder_outreach_human": "Warm, grounded founder outreach with restrained energy and natural pacing.",
    "customer_support": "Calm, patient, reassuring, clear phrasing.",
    "narration": "Steady explanatory pacing with balanced emphasis.",
    "announcement": "Confident and brighter, with clean articulation.",
    "character_dialogue": "Expressive character delivery while preserving clarity.",
    "dramatic_storytelling": "Higher emotional range and deliberate pacing.",
}


DELIVERY_TAGS_BY_CONTEXT: dict[SpeechContext, str] = {
    "outreach_conversational": "[warmly]",
    "founder_outreach_human": "[warmly and conversationally]",
    "customer_support": "[calm]",
    "narration": "[thoughtful]",
    "announcement": "[confident]",
    "character_dialogue": "[playfully]",
    "dramatic_storytelling": "[dramatic]",
}


VOICE_SETTINGS_BY_CONTEXT: dict[SpeechContext, dict[str, float | bool]] = {
    "outreach_conversational": {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "speed": 0.94,
    },
    "founder_outreach_human": {
        "stability": 0.5,
        "similarity_boost": 0.70,
        "style": 0.0,
        "speed": 0.96,
    },
    "customer_support": {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "speed": 0.95,
    },
    "narration": {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "speed": 0.97,
    },
    "announcement": {
        "stability": 0.5,
        "similarity_boost": 0.72,
        "style": 0.0,
        "speed": 1.0,
    },
    "character_dialogue": {
        "stability": 0.0,
        "similarity_boost": 0.8,
        "style": 0.0,
        "speed": 0.96,
    },
    "dramatic_storytelling": {
        "stability": 0.0,
        "similarity_boost": 0.77,
        "style": 0.0,
        "speed": 0.94,
    },
}


def resolve_voice_settings(
    speech_context: str,
    overrides: dict[str, float | bool] | None = None,
) -> dict[str, float | bool]:
    """Return a fresh context settings map with validated request overrides applied."""
    settings = dict(
        VOICE_SETTINGS_BY_CONTEXT.get(
            speech_context,
            VOICE_SETTINGS_BY_CONTEXT["outreach_conversational"],
        )
    )
    if overrides:
        settings.update(
            {
                key: value
                for key, value in overrides.items()
                if key in settings and value is not None
            }
        )
    return settings
