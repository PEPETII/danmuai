"""Contract: static .card must not translate on hover; interactive may."""

from __future__ import annotations

import re
from pathlib import Path


def _static_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "web" / "static"


def _base_css() -> str:
    return (_static_dir() / "warm-tokens-base.css").read_text(encoding="utf-8")


def _rule_block(css: str, selector: str) -> str | None:
    """Return body of first rule whose selector matches exactly (simple)."""
    pattern = re.compile(
        rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}",
    )
    match = pattern.search(css)
    return match.group(1) if match else None


def test_static_card_hover_has_no_translatey():
    css = _base_css()
    # Global .card:hover (alone or combined with .ui-card:hover) must not translateY.
    card_hover = _rule_block(css, ".card:hover")
    combined = re.search(
        r"\.card:hover\s*,\s*\.ui-card:hover\s*\{([^}]*)\}",
        css,
    )
    ui_only = re.search(
        r"\.ui-card:hover\s*,\s*\.card:hover\s*\{([^}]*)\}",
        css,
    )
    body = None
    if card_hover is not None:
        body = card_hover
    elif combined is not None:
        body = combined.group(1)
    elif ui_only is not None:
        body = ui_only.group(1)
    assert body is not None, ".card:hover rule missing"
    assert "translateY" not in body, (
        ".card:hover must not use translateY (static cards must not lift)"
    )


def test_interactive_card_hover_may_translatey():
    css = _base_css()
    assert ".ui-card--interactive" in css
    interactive_hover = _rule_block(css, ".ui-card--interactive:hover")
    assert interactive_hover is not None
    assert "translateY" in interactive_hover


def test_card_transition_not_all():
    css = _base_css()
    # Prefer explicit property transitions over transition: all on .card
    card_block = re.search(
        r"\.card\s*,\s*\.ui-card\s*\{([^}]*)\}|\.card\s*\{([^}]*)\}",
        css,
    )
    assert card_block is not None
    body = card_block.group(1) or card_block.group(2) or ""
    assert re.search(r"transition\s*:\s*all\b", body) is None, (
        ".card should not use transition: all"
    )


def test_overview_stat_cards_have_interactive_class():
    overview = (_static_dir() / "partials" / "overview.html").read_text(encoding="utf-8")
    # Eight overview stat cards (session + lifetime).
    count = overview.count("ui-card--interactive")
    assert count == 8, f"expected 8 ui-card--interactive on overview stats, got {count}"
    for sid in (
        "statDanmu",
        "statQueue",
        "statRuntime",
        "statDisplay",
        "statLifetimeDanmu",
        "statLifetimeRuntime",
        "statLifetimeInputTokens",
        "statLifetimeOutputTokens",
    ):
        assert sid in overview


def test_settings_form_card_not_interactive():
    settings = (_static_dir() / "partials" / "settings.html").read_text(encoding="utf-8")
    # Large settings form remains static .card without interactive lift.
    assert 'id="settingsForm"' in settings
    assert "ui-card--interactive" not in settings


def _components_css() -> str:
    return (_static_dir() / "warm-tokens-components.css").read_text(encoding="utf-8")


def test_ui_button_semantic_selectors_exist():
    css = _components_css()
    required = [
        ".ui-button",
        ".ui-button--primary",
        ".ui-button--secondary",
        ".ui-button--danger",
        ".ui-button--ghost",
        ".ui-button--sm",
        ".ui-button--md",
        ".ui-button--lg",
        ".ui-button:focus-visible",
        ".ui-button.is-loading",
    ]
    for sel in required:
        assert sel in css, f"missing button selector {sel}"
    assert "var(--control-height-sm)" in css
    assert "var(--control-height-md)" in css
    assert "var(--control-height-lg)" in css


def test_ui_field_and_control_selectors_exist():
    css = _components_css()
    required = [
        ".ui-field",
        ".ui-field__label",
        ".ui-field__hint",
        ".ui-control",
        ".ui-input",
        ".ui-select",
        ".ui-textarea",
        "aria-invalid",
        ".is-error",
        ".is-readonly",
        ".is-disabled",
    ]
    for sel in required:
        assert sel in css, f"missing form selector fragment {sel}"


def test_btn_primary_compat_mapping_present():
    base = _base_css()
    components = _components_css()
    assert ".btn-primary" in base
    assert "btn-primary" in components
    assert "ui-button--primary" in components


def test_settings_footer_demo_uses_ui_button():
    settings = (_static_dir() / "partials" / "settings.html").read_text(encoding="utf-8")
    assert 'id="btnProbe"' in settings
    assert 'id="btnRestoreSettingsDefaults"' in settings
    footer_start = settings.find("settings-form-footer")
    assert footer_start != -1
    footer = settings[footer_start : footer_start + 800]
    assert "ui-button" in footer
    assert "ui-button--primary" in footer
    assert "ui-button--secondary" in footer
    assert "ui-button--lg" in footer
    # IDs preserved
    assert 'id="btnProbe"' in footer
    assert 'id="btnRestoreSettingsDefaults"' in footer


def test_settings_page_controls_use_ui_dual_class():
    """W-UI-SETTINGS-MIGRATE-001：设置页主要控件双 class，无内联 style。"""
    settings = (_static_dir() / "partials" / "settings.html").read_text(encoding="utf-8")
    assert "<style>" not in settings
    assert "ui-control" in settings
    assert "ui-input" in settings
    assert "ui-select" in settings
    assert "ui-textarea" in settings
    assert "settings-field-control" in settings
    # 主要裸 Tailwind 视觉 class 已迁出
    assert "px-4 py-3 bg-cream" not in settings
    # 关键 ID / name 保留
    for field_id in (
        "api_endpoint",
        "temperature",
        "screen_index",
        "danmuReadInterval",
        "danmu_render_mode",
        "languageSelect",
        "themeToggle",
    ):
        assert f'id="{field_id}"' in settings
    # dual-class samples
    assert re.search(
        r'id="temperature"[^>]*class="[^"]*settings-field-control[^"]*ui-control',
        settings,
    )
    assert re.search(
        r'id="languageSelect"[^>]*class="[^"]*lang-select[^"]*ui-control',
        settings,
    ) or re.search(
        r'id="languageSelect"[^>]*class="[^"]*ui-control[^"]*lang-select',
        settings,
    )


def test_settings_legacy_hide_lives_in_compat_css():
    static = _static_dir()
    entry = (static / "warm-tokens.css").read_text(encoding="utf-8")
    compat = (static / "warm-tokens-compat.css").read_text(encoding="utf-8")
    assert "warm-tokens-compat.css" in entry
    assert ".legacy-api-fields" in compat
    assert "display: none !important" in compat or "display:none !important" in compat


def test_overview_demo_topic_nickname_use_ui_field():
    overview = (_static_dir() / "partials" / "overview.html").read_text(encoding="utf-8")
    assert 'id="liveTopicInput"' in overview
    assert 'id="userNicknameInput"' in overview
    assert 'id="btnSaveLiveTopic"' in overview
    assert 'id="btnSaveUserNickname"' in overview
    assert 'id="btnToggle"' in overview
    assert "ui-field" in overview
    assert "ui-field__label" in overview
    assert "ui-control" in overview
    assert "ui-input" in overview
    assert "ui-textarea" in overview
    assert "ui-button" in overview
    # Dual-class primary toggle keeps btn-primary for status.js
    assert re.search(
        r'id="btnToggle"[^>]*class="[^"]*btn-primary[^"]*ui-button',
        overview,
    ) or re.search(
        r'id="btnToggle"[^>]*class="[^"]*ui-button[^"]*btn-primary',
        overview,
    )


def test_overview_f1_semantic_shell():
    """W-UI-PAGES-OVERVIEW-001: page header, group titles, status banners, IDs."""
    overview = (_static_dir() / "partials" / "overview.html").read_text(encoding="utf-8")
    components = _components_css()
    pages = (_static_dir() / "warm-tokens-pages-overview.css").read_text(
        encoding="utf-8"
    )

    assert "ui-page-header" in overview
    assert "ui-page-header__copy" in overview
    assert "ui-page-header__actions" in overview
    assert "ui-page-description" in overview
    assert 'id="statusSub"' in overview
    assert 'id="statusPill"' in overview
    assert 'id="realtimeConnStatus"' in overview
    assert 'id="statusDot"' in overview
    assert 'id="errorBanner"' in overview
    assert 'id="overlayCompatBanner"' in overview
    assert 'id="sessionRunLog"' in overview
    assert "ui-status-banner" in overview
    assert "ui-status-banner--danger" in overview
    assert "ui-status-banner--warning" in overview
    assert "overview-group-title" in overview
    assert "本场" in overview
    assert "累计" in overview
    # Lifetime cards no longer rely only on opacity/softPeach wash for grouping
    assert "bg-white/80" not in overview
    # Static large cards (topic/persona/log) keep .card without only-interactive
    assert overview.count("ui-card--interactive") == 8
    assert 'id="btnErrorReportFromBanner"' in overview
    assert "ui-button" in overview
    assert "ui-button--secondary" in overview

    for sel in (
        ".ui-page-header",
        ".ui-page-description",
        ".ui-status-banner",
        ".ui-status-banner--danger",
        ".ui-status-banner--warning",
    ):
        assert sel in components, f"missing component selector {sel}"

    assert ".overview-group-title" in pages
    assert ".session-run-log" in pages
    assert "max-height" in pages
    assert ".overview-stat-value" in pages


def test_content_pages_f2_semantic_shell():
    """W-UI-PAGES-CONTENT-001: content pages + modals dual-class semantic migration."""
    static = _static_dir()
    content = (static / "partials" / "content-pages.html").read_text(encoding="utf-8")
    modals = (static / "partials" / "modals.html").read_text(encoding="utf-8")
    pages = (static / "warm-tokens-pages.css").read_text(encoding="utf-8")

    for page_id in (
        "page-knowledge",
        "page-ai-butler",
        "page-persona",
        "page-danmu-pool",
        "page-pet",
        "page-live-settings",
        "page-guide",
        "page-logs",
        "page-feedback",
        "page-announcements",
    ):
        assert f'id="{page_id}"' in content

    assert content.count("ui-page-header") >= 10
    assert content.count("ui-page-header__copy") >= 10
    assert content.count("ui-page-title") >= 10
    assert content.count("ui-card") >= 10
    assert "ui-button--primary" in content
    assert "ui-button--secondary" in content
    assert "ui-control" in content
    assert "ui-input" in content
    assert "ui-select" in content
    assert "ui-textarea" in content
    # Static content cards must not use interactive lift
    assert "ui-card--interactive" not in content

    for bid in (
        "btnSaveMemeBarrageSettings",
        "btnPetSave",
        "btnSavePersona",
        "btnAiButlerSend",
        "btnKnowledgeNewPackage",
        "btnFeedbackSubmit",
        "btnLiveOverlayTest",
    ):
        assert re.search(
            rf'id="{bid}"[^>]*class="[^"]*ui-button',
            content,
        ), f"missing ui-button on {bid}"

    for iid in (
        "memeCollectInterval",
        "poolMinOnScreen",
        "personaSelect",
        "aiButlerModelSelect",
        "knowledgePackageName",
        "petScale",
    ):
        assert re.search(
            rf'id="{iid}"[^>]*class="[^"]*ui-control',
            content,
        ), f"missing ui-control on {iid}"

    # Critical IDs / data hooks preserved
    for sid in (
        "memeBarrageEnabled",
        "poolCustomTextarea",
        "petEnabled",
        "personaSelect",
        "liveOverlayUrl",
        "aiButlerMessages",
        "knowledgePackageList",
        "feedbackForm",
        "logView",
        "btnAnnouncementsRefresh",
    ):
        assert f'id="{sid}"' in content

    assert 'id="modelModal"' in modals
    assert "ui-button--primary" in modals
    assert "ui-button--secondary" in modals
    assert "ui-button--danger" in modals
    assert "ui-control" in modals
    assert re.search(
        r'id="btnDeleteModelConfirmOk"[^>]*class="[^"]*ui-button--danger',
        modals,
    )
    assert re.search(
        r'id="btnModelCancel"[^>]*class="[^"]*ui-button',
        modals,
    )
    assert re.search(
        r'id="modelName"[^>]*class="[^"]*ui-control',
        modals,
    )

    assert "W-UI-PAGES-CONTENT-001" in pages or "#page-knowledge" in pages
    assert "#page-danmu-pool" in pages
    assert "#page-ai-butler" in pages
