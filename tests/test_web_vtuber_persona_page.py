from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "web" / "static"


def test_vtuber_persona_module_wires_persona_api():
    source = (STATIC_ROOT / "modules" / "app-vtuber-persona-page.js").read_text(encoding="utf-8")

    assert "/api/virtual-host/persona" in source
    assert "vtuberPersonaSystemPrompt" in source
    assert "vtuberPersonaVoicePrompt" in source
    assert "btnVtuberPersonaSave" in source
    assert "btnVtuberPersonaReset" in source
    assert "reset=true" in source
    assert "personaCache" in source
    assert "personaRequestInFlight" in source
    assert "MAX_PROMPT_CHARS" in source
    assert "applyPersonaForm(personaCache)" in source
    assert "handlersBound" in source
    assert "maxlength" not in source
    assert "localStorage" not in source


def test_vtuber_persona_tab_in_source_and_built_index():
    partial = (STATIC_ROOT / "partials" / "content-pages.html").read_text(encoding="utf-8")
    index = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    pet_page = (STATIC_ROOT / "modules" / "app-pet-page.js").read_text(encoding="utf-8")

    for html in (partial, index):
        assert 'data-pet-tab="vtuber-persona"' in html
        assert 'id="petTabBtn-vtuber-persona"' in html
        assert 'aria-controls="petTab-vtuber-persona"' in html
        assert 'data-pet-panel="vtuber-persona"' in html
        assert 'id="vtuberPersonaSystemPrompt"' in html
        assert 'id="vtuberPersonaVoicePrompt"' in html
        assert 'id="btnVtuberPersonaSave"' in html
        assert 'id="btnVtuberPersonaReset"' in html
        assert re.search(r'id="petTab-vtuber-persona"[^>]*\bhidden\b', html)
        assert 'aria-describedby="vtuberPersonaSystemHint vtuberPersonaStatus"' in html
        assert 'maxlength="8000"' in html

    assert "vtuber-persona" in pet_page
    assert "app-vtuber-persona-page.js" in pet_page
    assert "onVtuberPersonaTabActivated" in pet_page


def test_vtuber_persona_locale_keys_exist():
    keys = (
        ("content", "text", "虚拟主播人格"),
        ("content", "hint", "vtuberPersonaScope"),
        ("content", "hint", "vtuberPersonaSystem"),
        ("content", "hint", "vtuberPersonaVoice"),
        ("content", "label", "vtuberPersonaSystem"),
        ("content", "label", "vtuberPersonaVoice"),
        ("content", "placeholder", "vtuberPersonaSystem"),
        ("content", "placeholder", "vtuberPersonaVoice"),
        ("content", "text", "保存"),
        ("content", "text", "恢复默认"),
    )
    for language in ("zh", "en"):
        content = json.loads(
            (STATIC_ROOT / "locales" / language / "content.json").read_text(encoding="utf-8"),
        )
        for section, group, key in keys:
            assert content[section][group][key]
