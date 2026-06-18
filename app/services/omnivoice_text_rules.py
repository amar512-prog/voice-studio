from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re


DATE_SLASH_RE = re.compile(
    r"(?<!\d)(?P<day>0?[1-9]|[12]\d|3[01])/"
    r"(?P<month>0?[1-9]|1[0-2])/"
    r"(?P<year>(?:19|20)\d{2})(?!\d)"
)
UPPERCASE_SHORTHAND_RE = re.compile(r"\b[A-Z]{1,10}(?:/[A-Z]{1,10})+\b")
SLASH_CONTEXT_RE = re.compile(r".{0,24}/.{0,24}")
MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class TextRuleChange:
    rule: str
    original: str
    replacement: str


@dataclass(frozen=True)
class TextRuleResult:
    ready: bool
    original_text: str
    suggested_text: str
    changes: tuple[TextRuleChange, ...]
    errors: tuple[str, ...]


class OmniVoiceTextRuleError(ValueError):
    pass


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _date_replacement(match: re.Match[str]) -> str:
    day = int(match.group("day"))
    month = int(match.group("month"))
    year = int(match.group("year"))
    date(year, month, day)
    return f"{_ordinal(day)} {MONTH_NAMES[month]}, {year}"


def check_omnivoice_text(text: str) -> TextRuleResult:
    original = text
    suggested = text
    changes: list[TextRuleChange] = []

    def replace_date(match: re.Match[str]) -> str:
        try:
            replacement = _date_replacement(match)
        except ValueError:
            return match.group(0)
        changes.append(
            TextRuleChange(
                rule="date_slash",
                original=match.group(0),
                replacement=replacement,
            )
        )
        return replacement

    suggested = DATE_SLASH_RE.sub(replace_date, suggested)

    def replace_shorthand(match: re.Match[str]) -> str:
        replacement = match.group(0).replace("/", " ")
        changes.append(
            TextRuleChange(
                rule="uppercase_shorthand",
                original=match.group(0),
                replacement=replacement,
            )
        )
        return replacement

    suggested = UPPERCASE_SHORTHAND_RE.sub(replace_shorthand, suggested)

    errors: list[str] = []
    if "/" in original:
        errors.append(
            "OmniVoice reads '/' as the word 'slash'. Review and apply the suggested text before generation."
        )
    if "/" in suggested:
        contexts = []
        for match in SLASH_CONTEXT_RE.finditer(suggested):
            context = " ".join(match.group(0).split())
            if context and context not in contexts:
                contexts.append(context)
        detail = "; ".join(f'"{context}"' for context in contexts[:3])
        errors.append(
            "Some slash usage could not be corrected automatically"
            + (f": {detail}." if detail else ".")
            + " Replace it with words or punctuation."
        )

    return TextRuleResult(
        ready="/" not in original,
        original_text=original,
        suggested_text=suggested,
        changes=tuple(changes),
        errors=tuple(errors),
    )


def require_omnivoice_text_ready(text: str) -> None:
    result = check_omnivoice_text(text)
    if result.ready:
        return
    message = " ".join(result.errors)
    if result.suggested_text != result.original_text:
        message += f' Suggested text: "{result.suggested_text}"'
    raise OmniVoiceTextRuleError(message)
