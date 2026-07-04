"""Supported UI languages registry (extensible for ja/fr)."""

from __future__ import annotations

SUPPORTED_LANGUAGES: tuple[str, ...] = ("zh", "en")

LANGUAGE_LABELS: dict[str, dict[str, str]] = {
    "zh": {"zh": "中文", "en": "英语"},
    "en": {"zh": "Chinese", "en": "English"},
}

DEFAULT_LANGUAGE = "zh"


def is_supported(code: str) -> bool:
    return code in SUPPORTED_LANGUAGES


def normalize_language(value: object) -> str:
    if isinstance(value, str):
        code = value.strip().lower()
        if is_supported(code):
            return code
    return DEFAULT_LANGUAGE


def supported_languages_payload(display_lang: str = "zh") -> list[dict[str, str]]:
    labels = LANGUAGE_LABELS.get(display_lang, LANGUAGE_LABELS["en"])
    return [
        {"code": code, "label": labels.get(code, code)}
        for code in SUPPORTED_LANGUAGES
    ]
