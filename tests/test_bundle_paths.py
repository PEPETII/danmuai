
import pytest
from app.bundle_paths import is_frozen, project_root, resource_path

from tests.conftest import _ensure_feedback_static_images


def test_project_root_is_repo_in_dev():
    assert not is_frozen()
    root = project_root()
    assert (root / "main.py").is_file()
    assert (root / "web" / "static" / "index.html").is_file()


def test_resource_path_data_pool():
    pool = resource_path("data", "danmu_pool_zh.json")
    assert pool.is_file()
    assert pool.parent == project_root() / "data"


def test_feedback_static_images_packaged():
    root = project_root()
    _ensure_feedback_static_images()
    for name in (
        "qrcode_1779738450536.jpg",
        "mm_reward_qrcode_1779738306814.png",
    ):
        path = root / "web" / "static" / "image" / name
        src = root / "image" / name
        if not path.is_file() and not src.is_file():
            pytest.skip(f"feedback assets missing: {src}")
        assert path.is_file(), f"missing {path}; run python scripts/copy_feedback_images.py"
        assert path.stat().st_size > 0


def test_feedback_page_in_index_html():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-page="feedback"' in html
    assert 'id="page-feedback"' in html
    assert 'id="feedbackForm"' in html
    assert 'id="feedbackContent"' in html
    assert "/static/image/qrcode_1779738450536.jpg" in html
    assert 'id="rewardModal"' in html


def test_announcements_page_in_index_html():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-page="announcements"' in html
    assert 'id="page-announcements"' in html
    assert 'id="announcementsList"' in html
    assert 'id="announcementsNavBadge"' in html
    assert 'id="overviewAnnouncementBanner"' in html
    assert 'id="btnOverviewAnnouncementDismiss"' in html
    assert "/static/supabase-client.js" in html


def test_overview_announcement_banner_in_content_pages_js():
    root = project_root()
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    content_js = (root / "web" / "static" / "modules" / "content-pages.js").read_text(
        encoding="utf-8"
    )
    assert "danmu_announcements_overview_banner_dismissed_id" in content_js
    assert "function buildAnnouncementSnippet" in content_js
    assert "function updateOverviewAnnouncementBanner" in content_js
    assert "function buildAnnouncementSnippet" not in app_js


def test_error_report_modal_in_index_html():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="errorReportModal"' in html
    assert 'id="btnErrorReportSubmit"' in html
    assert 'id="btnErrorReportDismiss"' in html


def test_app_js_imports_transport_module():
    root = project_root()
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "from './modules/transport.js'" in app_js
    assert "apiFetch" in app_js
    assert "startRealtimeTransport" in app_js
    transport_js = (root / "web" / "static" / "modules" / "transport.js").read_text(
        encoding="utf-8"
    )
    assert "export async function apiFetch" in transport_js
    assert "export function startRealtimeTransport" in transport_js


def test_web_console_modules_exist():
    root = project_root()
    modules = root / "web" / "static" / "modules"
    for name in (
        "transport.js",
        "status.js",
        "logs.js",
        "diagnostics.js",
        "settings.js",
        "content-pages.js",
        "theme.js",
    ):
        path = modules / name
        assert path.is_file(), f"missing {path}"
        assert path.stat().st_size > 0
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'type="module"' in html
    assert "/static/app.js" in html


def test_diagnostics_panel_visibility_toggle_wires_button_and_sse_gate():
    """BUG-067: 诊断面板展开/收起按钮与 hidden 门控 SSE（静态符号回归）。"""
    root = project_root()
    index_html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    diagnostics_js = (root / "web" / "static" / "modules" / "diagnostics.js").read_text(
        encoding="utf-8"
    )

    assert 'id="btnToggleDiagnosticsPanel"' in index_html
    assert 'id="diagnosticsPanel"' in index_html
    diag_panel_idx = index_html.index('id="diagnosticsPanel"')
    diag_panel_chunk = index_html[max(0, diag_panel_idx - 80) : diag_panel_idx + 120]
    assert "hidden" in diag_panel_chunk

    assert "btnToggleDiagnosticsPanel" in diagnostics_js
    assert "setDiagnosticsPanelVisible" in diagnostics_js
    assert "classList.toggle('hidden'" in diagnostics_js
    assert "aria-hidden" in diagnostics_js
    init_start = diagnostics_js.index("export function initDiagnosticsPanel")
    init_snippet = diagnostics_js[init_start : init_start + 2500]
    assert "addEventListener('click'" in init_snippet
    assert "显示诊断面板" in diagnostics_js
    assert "隐藏诊断面板" in diagnostics_js

    assert "!panel.classList.contains('hidden')" in diagnostics_js
    assert "setInterval(refreshDiagnostics" not in diagnostics_js
    assert "refreshDiagnostics, 2500" not in diagnostics_js


def test_announcements_badge_polling_stops_on_announcements_page_navigate():
    """BUG-042: 公告页停止 5min 轮询，其他页恢复（静态符号回归）。"""
    root = project_root()
    content_js = (root / "web" / "static" / "modules" / "content-pages.js").read_text(
        encoding="utf-8"
    )
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "export function stopAnnouncementsBadgePolling" in content_js
    assert "clearInterval(announcementsBadgePollTimer)" in content_js
    assert "stopAnnouncementsBadgePolling" in app_js
    nav_start = app_js.index("function navigate(page)")
    nav_end = app_js.index("\nasync function init()", nav_start)
    navigate_body = app_js[nav_start:nav_end]
    assert "page === 'announcements'" in navigate_body
    assert "stopAnnouncementsBadgePolling()" in navigate_body
    assert "startAnnouncementsBadgePolling()" in navigate_body
    init_start = app_js.index("async function init()")
    init_snippet = app_js[init_start : init_start + 8000]
    assert "page-announcements" in init_snippet
    assert "startAnnouncementsBadgePolling()" in init_snippet
    assert "onAnnouncements" in init_snippet or "page-announcements" in init_snippet


def test_status_js_renders_legacy_lifetime_token_note():
    root = project_root()
    status_js = (root / "web" / "static" / "modules" / "status.js").read_text(encoding="utf-8")
    assert "statLifetimeTokenNote" in status_js
    assert "const legacyExtra = lifetimeTotal - lifetimeIn - lifetimeOut;" in status_js
    assert "另有升级前累计" in status_js
    assert "formatTokenCount(legacyExtra)" in status_js


def test_status_js_apply_status_uses_live_message_not_stale_drops():
    """BUG-027: applyStatus 仅消费 live_message；/api/status 不再暴露 live_stale_drops。"""
    root = project_root()
    status_js = (root / "web" / "static" / "modules" / "status.js").read_text(encoding="utf-8")
    assert "export function applyStatus" in status_js
    assert "liveStatusLine" in status_js
    assert "st.live_message" in status_js
    assert "live_stale_drops" not in status_js


def test_error_report_flow_in_app_js():
    root = project_root()
    js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    status_js = (root / "web" / "static" / "modules" / "status.js").read_text(encoding="utf-8")
    assert "function maybePromptErrorReport" in js
    assert "function collectErrorReportContext" in js
    assert "function extractErrorReportSearchTerms" in js
    assert "function findErrorLogAnchorIndex" in js
    assert "localStorage.setItem(ERROR_REPORT_DISMISS_STORAGE" in js
    assert "submitErrorReport" in js
    assert "statusHadError" in status_js


def test_api_settings_visible_in_simplified_mode():
    """记忆与温度控件不得带 settings-full-only，否则简化模式下会被 CSS 隐藏。"""
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    for field_id in ("memory_mode", "memory_window", "temperature"):
        idx = html.index(f'id="{field_id}"')
        chunk = html[max(0, idx - 120) : idx]
        assert "settings-full-only" not in chunk, field_id


def test_mic_settings_tab_separate_from_api_panel():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-settings-tab="mic"' in html
    assert 'id="settingsTab-mic"' in html
    api_panel_start = html.index('id="settingsTab-api"')
    api_panel_end = html.index('id="settingsTab-mic"')
    api_panel = html[api_panel_start:api_panel_end]
    assert 'id="mic_mode_enabled"' not in api_panel
    assert 'id="mic_use_visual_model"' not in api_panel
    assert html.count('id="settingsTab-mic"') == 1


def test_pet_page_in_index_html():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-page="pet"' in html
    assert 'id="page-pet"' in html
    assert 'id="petEnabled"' in html
    assert 'id="btnPetSave"' in html
    app_js = (project_root() / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "initPetPage" in app_js
    assert "loadPetPage" in app_js


def test_tailwind_offline_bundle_packaged():
    """BUG-059: 控制台使用内置 tailwindcdn.js，不依赖外网 CDN。"""
    root = project_root()
    bundle = root / "web" / "static" / "tailwindcdn.js"
    assert bundle.is_file()
    assert bundle.stat().st_size > 10_000
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "/static/tailwindcdn.js" in html
    assert "cdn.tailwindcss.com" not in html
