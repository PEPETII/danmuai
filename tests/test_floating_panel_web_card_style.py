"""Source contract: Web floating panel card colors must stay per-item.

W-FP-WEB-CARD-COLOR-PER-ITEM-001: addCard must not write card style vars to
document.documentElement; only the card element may receive them.
"""

from __future__ import annotations

from pathlib import Path

_APP_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "floating_panel" / "app.js"
)


def _app_js_text() -> str:
    assert _APP_JS.is_file(), f"missing {_APP_JS}"
    return _APP_JS.read_text(encoding="utf-8")


def test_apply_card_style_vars_targets_card_element_not_document_root():
    src = _app_js_text()
    assert "function applyCardStyleVars(cardEl, style)" in src
    assert "cardEl.style" in src or "var s = cardEl.style" in src
    # Must not reintroduce global card style pollution
    assert "function applyStyleVars(style)" not in src
    assert "document.documentElement.style" not in src.split("function applyCardStyleVars")[1].split(
        "function applyConfig"
    )[0]


def test_add_card_applies_style_to_card_only():
    src = _app_js_text()
    # addCard body must call per-card helper with the card node
    assert "applyCardStyleVars(card, msg.style)" in src
    # Guard: no leftover call that paints style onto the document root for cards
    add_card_body = src.split("function addCard(msg)")[1].split("function clearCards")[0]
    assert "document.documentElement" not in add_card_body
    assert "applyStyleVars" not in add_card_body


def test_apply_config_still_uses_document_root_for_panel_layout():
    """Panel-level gap/padding/duration remain global; only card palette is per-item."""
    src = _app_js_text()
    config_body = src.split("function applyConfig(msg)")[1].split("function removeOldestIfNeeded")[0]
    assert "document.documentElement.style.setProperty" in config_body
    assert "--stack-gap" in config_body or "stack_gap" in config_body


def test_apply_card_style_vars_supports_extended_style_fields():
    """W-FP-WEB-STYLE-PARITY: padding/opacity/tail/outline applied per card."""
    src = _app_js_text()
    body = src.split("function applyCardStyleVars(cardEl, style)")[1].split("function applyConfig")[0]
    for token in (
        "--padding-x",
        "--padding-y",
        "--tail-w",
        "is-bubble",
        "has-outline",
        "no-border",
        "is-bold",
    ):
        assert token in body


def test_panel_css_two_line_clamp_and_bubble_tail():
    css = (
        Path(__file__).resolve().parents[1]
        / "web"
        / "static"
        / "floating_panel"
        / "style.css"
    ).read_text(encoding="utf-8")
    assert "-webkit-line-clamp: 2" in css
    assert "is-bubble" in css
    assert "column-reverse" in css
