from app.models import SpeechContext


CONTEXT_LABELS: dict[SpeechContext, str] = {
    "outreach_conversational": "Outreach conversational",
    "customer_support": "Customer support",
    "narration": "Narration",
    "announcement": "Announcement",
    "character_dialogue": "Character dialogue",
    "dramatic_storytelling": "Dramatic storytelling",
}


CONTEXT_NOTES: dict[SpeechContext, str] = {
    "outreach_conversational": "Warm, natural, concise, one-to-one delivery.",
    "customer_support": "Calm, patient, reassuring, clear phrasing.",
    "narration": "Steady explanatory pacing with balanced emphasis.",
    "announcement": "Confident and brighter, with clean articulation.",
    "character_dialogue": "Expressive character delivery while preserving clarity.",
    "dramatic_storytelling": "Higher emotional range and deliberate pacing.",
}


DELIVERY_TAGS_BY_CONTEXT: dict[SpeechContext, str] = {
    "outreach_conversational": "[warmly]",
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
        "use_speaker_boost": True,
        "speed": 0.94,
    },
    "customer_support": {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 0.95,
    },
    "narration": {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 0.97,
    },
    "announcement": {
        "stability": 0.5,
        "similarity_boost": 0.72,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 1.0,
    },
    "character_dialogue": {
        "stability": 0.0,
        "similarity_boost": 0.8,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 0.96,
    },
    "dramatic_storytelling": {
        "stability": 0.0,
        "similarity_boost": 0.77,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 0.94,
    },
}
