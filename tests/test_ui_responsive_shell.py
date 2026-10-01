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
    assert 'id="consoleSidebar"' in html
    assert "ui-sidebar" in html
    assert 'id="nav"' in html
    assert 'id="announcementsNavBadge"' in html
    assert 'id="sidebarVersionFooter"' in html
    assert 'id="btnCheckAppUpdate"' in html
    assert 'id="btnDownloadRestartAppUpdate"' in html
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
        "pet",
        "guide",
    ):
        assert f'data-page="{page}"' in html
        assert f'href="#{page}"' in html
    assert 'data-page="ai-butler"' not in html
    assert 'href="#ai-butler"' not in html


def test_sidebar_navigation_filter_scopes_common_and_enhanced_items():
    html = _sidebar()
    app = (_static() / "app.js").read_text(encoding="utf-8")
    css = _layout_css()

    assert 'id="sidebarNavFilter"' in html
    assert 'data-nav-filter="common"' in html
    assert 'data-nav-filter="enhanced"' in html
    assert 'data-i18n="nav.commonFeatures"' in html
    assert 'data-i18n="nav.enhancedFeatures"' in html
    assert ">常用功能</button>" in html
    assert ">增强功能</button>" in html
    assert html.count('data-page="') == 8
    assert html.count('data-nav-scope="common"') == 5
    assert html.count('data-nav-scope="enhanced"') == 3
    assert 'data-nav-filter="all"' not in html
    assert 'data-nav-scope="all"' not in html
    assert "initSidebarNavCategoryFilter" in app
    assert "const filter = requestedFilter === 'enhanced' ? 'enhanced' : 'common';" in app
    assert "item.hidden = item.dataset.navScope !== filter;" in app
    assert "applyFilter('common');" in app
    filter_fn = app[app.index("function initSidebarNavCategoryFilter()") : app.index("function bindCoreInteractions()")]
    assert "navigate(" not in filter_fn
    assert "window.location" not in filter_fn
    assert "#nav [data-nav-scope][hidden]" in css


def test_sidebar_navigation_filter_categories_are_mutually_exclusive_and_localized():
    html = _sidebar()
    nav_start = html.index('<nav ')
    nav_html = html[nav_start:]
    common_pages = {
        line.split('data-page="', 1)[1].split('"', 1)[0]
        for line in nav_html.splitlines()
        if 'data-nav-scope="common"' in line and 'data-page="' in line
    }
    enhanced_pages = {
        line.split('data-page="', 1)[1].split('"', 1)[0]
        for line in nav_html.splitlines()
        if 'data-nav-scope="enhanced"' in line and 'data-page="' in line
    }
    assert common_pages
    assert enhanced_pages
    assert common_pages.isdisjoint(enhanced_pages)

    zh = json.loads((_static() / "locales" / "zh" / "nav.json").read_text(encoding="utf-8"))
    en = json.loads((_static() / "locales" / "en" / "nav.json").read_text(encoding="utf-8"))
    assert zh["nav"]["commonFeatures"] == "常用功能"
    assert zh["nav"]["enhancedFeatures"] == "增强功能"
    assert en["nav"]["commonFeatures"] == "Frequently used"
    assert en["nav"]["enhancedFeatures"] == "Enhanced features"


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
