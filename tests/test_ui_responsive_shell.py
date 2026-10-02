"""Static contract: desktop responsive shell (task G / W-UI-RESPONSIVE-SHELL-001)."""

from __future__ import annotations

import json
from pathlib import Path


def _static() -> Path:
    return Path(__file__).resolve().parents[1] / "web" / "static"


def _layout_css() -> str:
    return (_static() / "warm-tokens-layout.css").read_text(encoding="utf-8")


def _sidebar() -> str:
    return (_static() / "partials" / "sidebar.html").read_text(encoding="utf-8")


def _template() -> str:
    return (_static() / "index.template.html").read_text(encoding="utf-8")


def _shell_js() -> str:
    return (_static() / "modules" / "responsive-shell.js").read_text(encoding="utf-8")


def test_shell_breakpoints_and_main_padding_tokens():
    css = _layout_css()
    assert ".ui-main" in css
    assert "var(--space-8)" in css
    assert "@media (max-width: 1199px) and (min-width: 960px)" in css
    assert "@media (max-width: 959px)" in css
    assert "@media (max-width: 719px)" in css
    assert "var(--space-4)" in css
    assert "shell-nav-open" in css
    assert ".ui-shell-backdrop" in css
    assert ".ui-shell-nav-toggle" in css


def test_sidebar_shell_structure_and_preserved_ids():
    html = _sidebar()
    content = (_static() / "partials" / "content-pages.html").read_text(encoding="utf-8")
    assert 'id="consoleSidebar"' in html
    assert "ui-sidebar" in html
    assert 'id="nav"' in html
    assert 'id="announcementsNavBadge"' in html
    assert 'id="btnHelpSystem"' in html
    assert 'id="appUpdateNavBadge"' in html
    assert 'id="sidebarVersionFooter"' in html
    assert "sidebar-version-icon" in html
    assert 'id="appVersionCurrent"' in html
    assert 'id="appVersionLatest"' in html
    assert 'id="btnCheckAppUpdate"' not in html
    assert 'id="btnDownloadRestartAppUpdate"' not in html
    assert 'id="page-help-system"' in content
    assert 'id="appVersionCurrent"' not in content
    assert 'id="appVersionLatest"' not in content
    assert 'id="btnCheckAppUpdate"' in content
    assert 'id="btnDownloadRestartAppUpdate"' in content
    assert 'id="btnSidebarReward"' in html
    assert 'id="btnShellNavClose"' in html
    assert "sidebar-item-label" in html
    # 样式生成器已迁移为独立侧栏页面
    for page in (
        "overview",
        "settings",
        "style-generator",
        "persona",
        "knowledge",
        "danmu-pool",
        "virtual-host",
        "guide",
    ):
        assert f'data-page="{page}"' in html
        assert f'href="#{page}"' in html
    assert 'data-page="ai-butler"' not in html
    assert 'href="#ai-butler"' not in html


def test_help_system_groups_and_moved_update_controls():
    content = (_static() / "partials" / "content-pages.html").read_text(encoding="utf-8")
    sidebar = _sidebar()
    app = (_static() / "app.js").read_text(encoding="utf-8")
    update = (_static() / "modules" / "app-update-banner.js").read_text(encoding="utf-8")

    assert content.count('class="help-system-group ui-card"') == 3
    for label in ("使用帮助", "应用信息", "问题处理"):
        assert f"content.text.{label}" in content
    for control in (
        'data-help-navigate="tutorial"',
        'data-help-navigate="announcements"',
        'data-help-navigate="feedback"',
        'data-help-navigate="diagnostics"',
        'id="btnExportLogs"',
        'id="helpLanguageSelect"',
        'id="helpThemeToggle"',
    ):
        assert control in content
    assert 'id="btnHelpSystem"' in sidebar
    assert 'id="appUpdateNavBadge"' in sidebar
    assert 'id="sidebarVersionFooter"' in sidebar
    assert "navigate('help-system')" in app
    assert "appUpdateNavBadge" in update
    assert "maybeShowAppUpdateModal();" not in update


def test_sidebar_navigation_uses_common_group_and_collapsed_enhanced_group():
    html = _sidebar()
    app = (_static() / "app.js").read_text(encoding="utf-8")
    css = _layout_css()

    assert 'id="sidebarNavSections"' in html
    assert 'id="btnSidebarEnhancedToggle"' in html
    assert 'id="sidebarEnhancedItems"' in html
    assert 'data-i18n="nav.commonFeatures"' in html
    assert 'data-i18n="nav.enhancedFeatures"' in html
    assert 'data-i18n="nav.expandEnhanced"' in html
    assert 'data-i18n="nav.collapseEnhanced"' in html
    assert ">常用</div>" in html
    assert ">增强</span>" in html
    assert ">展开增强功能</span>" in html
    assert html.count('data-page="') == 8
    assert 'data-nav-scope' not in html
    assert 'aria-expanded="false"' in html
    assert 'hidden>收起增强功能</span>' in html
    assert "initSidebarNavDisclosure" in app
    assert "enhancedItems.hidden = !expanded;" in app
    assert "toggle.setAttribute('aria-expanded', String(expanded));" in app
    filter_fn = app[app.index("function initSidebarNavDisclosure()") : app.index("function bindCoreInteractions()")]
    assert "navigate(" not in filter_fn
    assert "window.location" not in filter_fn
    assert "#nav [hidden]" in css


def test_sidebar_navigation_groups_are_ordered_and_localized():
    html = _sidebar()
    common_start = html.index('sidebar-nav-common-group')
    enhanced_start = html.index('id="btnSidebarEnhancedToggle"')
    utility_start = html.index('class="sidebar-nav-utility-group"')
    assert common_start < enhanced_start < utility_start
    assert html.index('data-page="overview"', common_start) < html.index('data-page="settings"', common_start)
    assert html.index('data-page="settings"', common_start) < html.index('data-page="persona"', common_start)
    assert html.index('data-page="style-generator"', enhanced_start) < html.index('data-page="danmu-pool"', enhanced_start)
    assert html.index('data-page="danmu-pool"', enhanced_start) < html.index('data-page="knowledge"', enhanced_start)
    assert html.index('data-page="knowledge"', enhanced_start) < html.index('data-page="virtual-host"', enhanced_start)

    zh = json.loads((_static() / "locales" / "zh" / "nav.json").read_text(encoding="utf-8"))
    en = json.loads((_static() / "locales" / "en" / "nav.json").read_text(encoding="utf-8"))
    assert zh["nav"]["commonFeatures"] == "常用"
    assert zh["nav"]["enhancedFeatures"] == "增强"
    assert zh["nav"]["expandEnhanced"] == "展开增强功能"
    assert zh["nav"]["collapseEnhanced"] == "收起增强功能"
    assert en["nav"]["commonFeatures"] == "Common"
    assert en["nav"]["enhancedFeatures"] == "Enhanced"
    assert en["nav"]["expandEnhanced"] == "Show enhanced features"
    assert en["nav"]["collapseEnhanced"] == "Hide enhanced features"


def test_template_shell_toggle_and_ui_main():
    tpl = _template()
    assert "ui-shell" in tpl
    assert 'id="btnShellNavToggle"' in tpl
    assert 'id="shellNavBackdrop"' in tpl
    assert "ui-main" in tpl
    assert "aria-controls=\"consoleSidebar\"" in tpl
    # No fixed Tailwind p-8 on main (padding via .ui-main)
    assert 'class="flex-1 overflow-y-auto p-8 bg-cream relative"' not in tpl


def test_responsive_shell_module_api():
    js = _shell_js()
    assert "export function initResponsiveShell" in js
    assert "export function openShellNav" in js
    assert "export function closeShellNav" in js
    assert "export function closeShellNavIfDrawer" in js
    assert "Escape" in js
    assert "max-width: 959px" in js
    assert "shell-nav-open" in js


def test_app_js_wires_responsive_shell():
    app = (_static() / "app.js").read_text(encoding="utf-8")
    assert "responsive-shell.js" in app
    assert "initResponsiveShell" in app
    assert "closeShellNavIfDrawer" in app


def test_built_index_contains_shell_markers():
    index = (_static() / "index.html").read_text(encoding="utf-8")
    assert 'id="consoleSidebar"' in index
    assert 'id="btnShellNavToggle"' in index
    assert 'id="shellNavBackdrop"' in index
    assert "ui-main" in index
    assert 'id="announcementsNavBadge"' in index
