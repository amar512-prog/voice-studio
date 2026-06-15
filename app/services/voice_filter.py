from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_ACCENTS = {"us", "in", "neutral"}
@dataclass(frozen=True)
class ProviderVoiceProfile:
    accent: str
    language: str = "en"
    use_case: str = "conversational"


def provider_voice_profile(voice: dict[str, Any]) -> ProviderVoiceProfile | None:
    labels = _collect_labels(voice)
    verified_languages = voice.get("verified_languages") or []

    primary_language = _normalize(labels.get("language") or labels.get("language_code"))
    if primary_language:
        is_english = primary_language in {"en", "eng", "english"}
    else:
        is_english = any(
            _normalize(item.get("language")) in {"en", "eng", "english"}
            for item in verified_languages
            if isinstance(item, dict)
        )
    if not is_english:
        return None

    use_case = next(
        (
            value
            for value in [
                _normalize(labels.get("use_case")),
                _normalize(labels.get("usecase")),
                _normalize(labels.get("usage")),
            ]
            if value
        ),
        "general",
    )
    if "convers" not in use_case:
        return None

    primary_accent = _normalize(labels.get("accent"))
    if primary_accent:
        accent = _supported_accent([primary_accent])
    else:
        accent = _supported_accent(
            [
                _normalize(item.get("accent"))
                for item in verified_languages
                if isinstance(item, dict)
                and _normalize(item.get("language")) in {"en", "eng", "english"}
            ]
        )
    if accent is None:
        return None

    return ProviderVoiceProfile(accent=accent, use_case=use_case)


def provider_voice_rank(voice: dict[str, Any], profile: ProviderVoiceProfile) -> tuple[int, str]:
    return 0, _normalize(voice.get("name"))


def is_registry_eligible(record: dict[str, Any]) -> bool:
    accent = _normalize(record.get("accent"))
    if accent not in ALLOWED_ACCENTS:
        return False

    if record.get("source_type") == "elevenlabs_library":
        metadata = record.get("provider_metadata") or {}
        return provider_voice_profile(metadata) is not None

    return True


def _collect_labels(voice: dict[str, Any]) -> dict[str, Any]:
    labels: dict[str, Any] = {}
    # Shared-library voices expose language/accent/use_case as top-level fields
    # rather than nested labels; seed them as fallbacks before nested labels win.
    for key in ("language", "language_code", "accent", "use_case", "usecase", "usage", "gender", "age", "descriptive"):
        value = voice.get(key)
        if value is not None:
            labels[key] = value
    for candidate in [voice.get("labels"), (voice.get("sharing") or {}).get("labels")]:
        if isinstance(candidate, dict):
            labels.update(candidate)
    return labels


def _supported_accent(accents: list[str]) -> str | None:
    for accent in accents:
        if accent in {"us", "usa", "american", "general american", "united states"}:
            return "us"
        if accent in {"in", "india", "indian", "indian english"}:
            return "in"
        if accent in {"neutral", "standard", "general", "international"}:
            return "neutral"
    return None


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace("-", " ")
