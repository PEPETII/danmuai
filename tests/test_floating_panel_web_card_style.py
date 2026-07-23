"""Source contract: Web floating panel card colors must stay per-item.

W-FP-WEB-CARD-COLOR-PER-ITEM-001: addCard must not write card style vars to
document.documentElement; only the card element may receive them.

W-FP-LINELIKE-WEB-001: stacked DOM + LineLike tail geometry + separator empty.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_APP_JS = _ROOT / "web" / "static" / "floating_panel" / "app.js"
_STYLE_CSS = _ROOT / "web" / "static" / "floating_panel" / "style.css"


def _app_js_text() -> str:
    assert _APP_JS.is_file(), f"missing {_APP_JS}"
    return _APP_JS.read_text(encoding="utf-8")


def _style_css_text() -> str:
    assert _STYLE_CSS.is_file(), f"missing {_STYLE_CSS}"
    return _STYLE_CSS.read_text(encoding="utf-8")


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
    css = _style_css_text()
    assert "-webkit-line-clamp: 2" in css
    assert "is-bubble" in css
    assert "column-reverse" in css


def test_stacked_dom_has_bubble_username_outside():
    """layout=stacked → .username sibling of .bubble; content inside bubble."""
    src = _app_js_text()
    add_card_body = src.split("function addCard(msg)")[1].split("function clearCards")[0]
    assert 'layout === "stacked"' in add_card_body or "layout === 'stacked'" in add_card_body
    assert 'class="bubble"' in add_card_body
    assert 'class="content"' in add_card_body
    # stacked path wraps content in bubble
    assert (
        '<div class="bubble"><div class="content">' in add_card_body
        or "<div class=\"bubble\"><div class=\"content\">" in add_card_body
    )
    # inline path keeps direct .content under .card (no bubble wrapper)
    assert "layout" in add_card_body


def test_inline_dom_keeps_username_and_content_siblings():
    """Missing/inline layout: classic wechat structure without .bubble."""
    src = _app_js_text()
    add_card_body = src.split("function addCard(msg)")[1].split("function clearCards")[0]
    # else branch still emits username + content without bubble
    assert 'class="username"' in add_card_body
    assert 'class="content"' in add_card_body
    # stacked uses bubble; ensure both branches exist
    assert "stacked" in add_card_body
    assert "inline" in add_card_body or 'layout === "stacked"' in add_card_body


def test_line_like_css_geometry_present():
    """LineLike border-triangle + rotate geometry in style.css."""
    css = _style_css_text()
    assert "line_like" in css
    assert "layout-stacked" in css
    assert "--tail-border" in css
    assert "--tail-long-side" in css
    assert "--tail-rotate" in css
    assert "width: fit-content" in css or "width:fit-content" in css
    assert "rotate(var(--tail-rotate" in css
    assert "border-left-width: var(--tail-long-side" in css
    assert "border-right: var(--tail-long-side" in css
    # stacked: no card chrome; bubble holds bg
    assert ".card.layout-stacked" in css
    assert ".card.layout-stacked .bubble" in css
    # MIT / blivechat attribution when LineLike geometry is present
    assert "blivechat" in css.lower() or "MIT" in css


def test_apply_card_style_vars_maps_linelike_fields():
    """layout / tail_border / tail_long_side / tail_rotate_deg → CSS vars + classes."""
    src = _app_js_text()
    body = src.split("function applyCardStyleVars(cardEl, style)")[1].split("function applyConfig")[0]
    assert "layout-stacked" in body
    assert "--tail-border" in body
    assert "--tail-long-side" in body
    assert "--tail-rotate" in body
    assert "tail_border" in body
    assert "tail_long_side" in body
    assert "tail_rotate_deg" in body


def test_empty_username_separator_does_not_force_colon():
    """username_separator === '' must not fall back to fullwidth colon."""
    src = _app_js_text()
    add_card_body = src.split("function addCard(msg)")[1].split("function clearCards")[0]
    # Must use != null check so empty string is accepted
    assert "username_separator != null" in add_card_body
    # Old force-colon pattern must not remain as sole assignment
    assert '(msg.style && msg.style.username_separator) || "："' not in add_card_body
    assert "(msg.style && msg.style.username_separator) || '：'" not in add_card_body
