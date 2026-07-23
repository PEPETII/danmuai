"""Static contract: early theme script matches modules/theme.js normalize rules."""

from __future__ import annotations

import re
from pathlib import Path

from tests.test_bundle_paths import project_root


def _static() -> Path:
    return project_root() / "web" / "static"


def _read(name: str) -> str:
    return (_static() / name).read_text(encoding="utf-8")


def _js_normalize_theme(value: object, default: str = "dark") -> str:
    """Mirror modules/theme.js normalizeTheme + DEFAULT_THEME='dark'."""
    return "light" if value == "light" else default


def _early_normalize_theme(raw: object | None, default: str = "dark") -> str:
    """Mirror index early script: only exact 'light' is light; else default."""
    return "light" if raw == "light" else default


def test_default_theme_is_dark_in_early_and_module():
    template = _read("index.template.html")
    theme_js = _read("modules/theme.js")
    assert "window.DANMU_DEFAULT_THEME = 'dark'" in template
    assert "DEFAULT_THEME" in theme_js
    assert re.search(r"['\"]dark['\"]", theme_js)
    # Comment must not claim non-dark → light
    assert "非 'dark' 全部归一为 'light'" not in theme_js
    assert "非 dark 全部归一" not in theme_js


def test_normalize_rules_match_between_early_and_module():
    cases = [
        ("light", "light"),
        ("dark", "dark"),
        (None, "dark"),
        ("", "dark"),
        ("invalid", "dark"),
        ("DARK", "dark"),
        ("Light", "dark"),
        (0, "dark"),
    ]
    for raw, expected in cases:
        assert _js_normalize_theme(raw) == expected, f"module rule fail for {raw!r}"
        assert _early_normalize_theme(raw) == expected, f"early rule fail for {raw!r}"
        assert _js_normalize_theme(raw) == _early_normalize_theme(raw)


def test_theme_js_normalize_source_is_light_only_else_default():
    theme_js = _read("modules/theme.js")
    # Implementation: value === 'light' ? 'light' : DEFAULT_THEME
    assert re.search(
        r"return\s+value\s*===\s*['\"]light['\"]\s*\?\s*['\"]light['\"]\s*:\s*DEFAULT_THEME",
        theme_js,
    )


def test_early_script_uses_same_light_else_default_rule():
    template = _read("index.template.html")
    assert "raw === 'light' ? 'light' : def" in template or re.search(
        r"raw\s*===\s*['\"]light['\"].*['\"]light['\"].*def",
        template,
        re.DOTALL,
    )
    assert "setAttribute('data-theme', 'dark')" in template
    assert "removeAttribute('data-theme')" in template


def test_built_index_html_contains_early_default_dark():
    html = _read("index.html")
    assert "window.DANMU_DEFAULT_THEME = 'dark'" in html
    assert "danmu_console_theme" in html
    # Must not only set dark when raw === 'dark' (old FOUC bug)
    assert re.search(
        r"raw\s*===\s*['\"]light['\"]\s*\?\s*['\"]light['\"]\s*:\s*def",
        html,
    )


def test_semantic_surface_text_border_aliases_in_base():
    base = _read("warm-tokens-base.css")
    required = [
        "--surface-page",
        "--surface-subtle",
        "--surface-card",
        "--surface-control",
        "--surface-overlay",
        "--text-primary",
        "--text-secondary",
        "--text-muted",
        "--text-on-brand",
        "--border-default",
        "--border-soft",
        "--border-brand",
    ]
    for token in required:
        assert re.search(rf"{re.escape(token)}\s*:", base), f"missing {token}"
    # Aliases should point at existing tokens where applicable
    assert "--surface-page: var(--color-bg)" in base
    assert "--surface-subtle: var(--color-bg-subtle)" in base
    assert "--surface-card: var(--color-surface)" in base
    assert "--border-default: var(--border)" in base
    # Dark block also redeclares overlays
    assert "rgba(28, 25, 23, 0.78)" in base
    assert "rgba(253, 251, 247, 0.72)" in base
