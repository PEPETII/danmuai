from __future__ import annotations

import json
from pathlib import Path

STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"


def test_vtuber_knowledge_locale_keys_exist():
    keys = (
        ("content", "hint", "vtuberKnowledgeEnabled"),
        ("content", "label", "vtuberKnowledgeEnabled"),
    )
    for language in ("zh", "en"):
        content = json.loads(
            (STATIC_ROOT / "locales" / language / "content.json").read_text(encoding="utf-8"),
        )
        for section, group, key in keys:
            assert content[section][group][key]
