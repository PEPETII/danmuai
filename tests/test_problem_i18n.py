"""Problem catalog i18n completeness."""

from __future__ import annotations

import json
from pathlib import Path

from app.problems.catalog import PROBLEM_CATALOG
from app.translations import Translator


def _load_dynamic(lang: str) -> dict:
    path = Path(__file__).resolve().parents[1] / "web" / "static" / "locales" / lang / "dynamic.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_backend_problem_keys_have_zh_and_en():
    Translator.set_language("zh")
    for code, entry in PROBLEM_CATALOG.items():
        title = Translator.tr(str(entry["title_key"]))
        assert title and title != entry["title_key"], code
    Translator.set_language("en")
    for code, entry in PROBLEM_CATALOG.items():
        title = Translator.tr(str(entry["title_key"]))
        assert title and title != entry["title_key"], code


def test_frontend_problem_modal_keys_exist():
    for lang in ("zh", "en"):
        data = _load_dynamic(lang)
        problem = data["dynamic"]["problem"]
        assert problem["section"]["what"]
        assert problem["action"]["view"]
        assert problem["category"]["authentication"]
