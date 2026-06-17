
import pytest
from app.bundle_paths import is_frozen, project_root

from tests.conftest import _ensure_feedback_static_images


def test_project_root_is_repo_in_dev():
    assert not is_frozen()
    root = project_root()
    assert (root / "main.py").is_file()
    assert (root / "web" / "static" / "index.html").is_file()


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


def test_overview_global_fields_in_index_html():
    root = project_root()
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    persona_html = (root / "web" / "static" / "partials" / "content-pages.html").read_text(
        encoding="utf-8"
    )
    overview_start = html.index('id="page-overview"')
    persona_start = html.index('id="page-persona"')
    overview_slice = html[overview_start:persona_start]
    assert 'id="liveTopicInput"' in overview_slice
    assert 'id="userNicknameInput"' in overview_slice
    assert 'id="btnSaveLiveTopic"' in overview_slice
    assert 'id="btnSaveUserNickname"' in overview_slice
    assert 'id="liveTopicInput"' not in persona_html
    assert 'id="userNicknameInput"' not in persona_html
    lifetime_idx = overview_slice.index('id="statLifetimeDanmu"')
    topic_idx = overview_slice.index('id="liveTopicInput"')
    persona_idx = overview_slice.index('id="activePersonae"')
    assert lifetime_idx < topic_idx < persona_idx


def test_persona_name_prefix_toggle_in_built_index_html():
    """W-PERSONA-NAME-DISPLAY-001: partial edits must be rebuilt into index.html."""
    root = project_root()
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    persona_html = (root / "web" / "static" / "partials" / "content-pages.html").read_text(
        encoding="utf-8"
    )
    assert 'id="personaNamePrefixEnabled"' in persona_html
    assert 'id="personaNamePrefixEnabled"' in html
    persona_start = html.index('id="page-persona"')
    tutorial_start = html.index('id="page-tutorial"')
    persona_slice = html[persona_start:tutorial_start]
    save_idx = persona_slice.index('id="btnSavePersona"')
    prefix_idx = persona_slice.index('id="personaNamePrefixEnabled"')
    active_idx = persona_slice.index('id="hintPersonaActiveTitle"')
    assert save_idx < prefix_idx < active_idx


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
    assert 'id="errorReportUserNote"' in html
    assert 'id="btnErrorReportFromBanner"' in html


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
        "app-setup-guide.js",
    ):
        path = modules / name
        assert path.is_file(), f"missing {path}"
        assert path.stat().st_size > 0
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'type="module"' in html
    assert "/static/app.js" in html


def test_first_run_setup_guide_wired_to_overview():
    root = project_root()
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    setup_js = (root / "web" / "static" / "modules" / "app-setup-guide.js").read_text(
        encoding="utf-8"
    )
    css = (root / "web" / "static" / "warm-tokens-pages.css").read_text(encoding="utf-8")

    assert 'id="firstRunSetupGuide"' in html
    assert 'id="setupGuideSteps"' in html
    assert 'id="btnSetupGuideProbe"' in html
    assert 'id="btnSetupGuideTestDanmu"' in html
    assert "from './modules/app-setup-guide.js'" in app_js
    assert "initSetupGuide(cfg, initialStatus)" in app_js
    assert "updateSetupGuideConfig(savedCfg)" in app_js
    assert "updateSetupGuideStatus(status)" in app_js
    assert "danmu_setup_guide_dismissed_v1" in setup_js
    assert "/api/probe" in setup_js
    assert "/api/test/danmu" in setup_js
    assert "switchSettingsTab(tabId)" in setup_js
    assert ".setup-guide" in css


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

    assert "isIntersecting: true" not in diagnostics_js
    assert "isDiagnosticsPanelVisible" in diagnostics_js
    assert "page-overview" in diagnostics_js
    assert "panel.classList.contains('hidden')" in diagnostics_js
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


def test_meme_barrage_meta_polling_stops_when_leaving_danmu_pool():
    """W-PERF-MED-004 P-24: 离开弹幕池页停止 meta 轮询（静态符号回归）。"""
    root = project_root()
    meme_js = (root / "web" / "static" / "modules" / "app-meme-barrage-page.js").read_text(
        encoding="utf-8"
    )
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "export function stopMemeBarrageMetaPolling" in meme_js
    assert "clearInterval(metaPollTimer)" in meme_js
    assert "stopMemeBarrageMetaPolling" in app_js
    nav_start = app_js.index("function navigate(page)")
    nav_end = app_js.index("\nasync function init()", nav_start)
    navigate_body = app_js[nav_start:nav_end]
    assert "page === 'danmu-pool'" in navigate_body
    assert "startMemeBarrageMetaPolling()" in navigate_body
    assert "stopMemeBarrageMetaPolling()" in navigate_body


def test_realtime_transport_and_diagnostics_teardown_on_pagehide():
    """W-PERF-MED-004 P-38: pagehide 统一清理 WS/SSE/轮询（静态符号回归）。"""
    root = project_root()
    transport_js = (root / "web" / "static" / "modules" / "transport.js").read_text(encoding="utf-8")
    diagnostics_js = (root / "web" / "static" / "modules" / "diagnostics.js").read_text(
        encoding="utf-8"
    )
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "export function stopRealtimeTransport" in transport_js
    assert "detachWebSocket(REALTIME.statusWs)" in transport_js
    assert "export function destroyDiagnosticsPanel" in diagnostics_js
    assert "export function disconnectDiagnosticsPanel" in diagnostics_js
    assert "pagehide" in app_js
    assert "stopRealtimeTransport()" in app_js
    assert "destroyDiagnosticsPanel()" in app_js
    assert "disconnectDiagnosticsPanel()" in app_js


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


def test_logs_js_uses_set_dedup():
    """W-PERF-MED-003: 日志去重使用 Set O(1) 查找，避免 logBuffer.some 线性扫描。"""
    logs_js = (project_root() / "web" / "static" / "modules" / "logs.js").read_text(encoding="utf-8")
    assert "logKeySet" in logs_js
    assert "logKeySet.has" in logs_js
    assert "logBuffer.some" not in logs_js


def test_logs_js_exports_clear_log_buffer():
    logs_js = (project_root() / "web" / "static" / "modules" / "logs.js").read_text(encoding="utf-8")
    assert "export function clearLogBuffer" in logs_js


def test_status_js_skips_unchanged_session_runs():
    """W-PERF-MED-003: session runs 脏检查避免 500ms 全量 DOM 重建。"""
    status_js = (project_root() / "web" / "static" / "modules" / "status.js").read_text(encoding="utf-8")
    assert "lastSessionRunsKey" in status_js
    assert "if (key === lastSessionRunsKey) return" in status_js


def test_status_js_update_text_if_changed():
    status_js = (project_root() / "web" / "static" / "modules" / "status.js").read_text(encoding="utf-8")
    assert "function updateTextIfChanged" in status_js


def test_app_init_parallelizes_independent_fetches():
    """W-PERF-MED-003: init() 在 refreshSession 后并行拉取独立 API。"""
    app_js = (project_root() / "web" / "static" / "app.js").read_text(encoding="utf-8")
    init_start = app_js.index("async function init()")
    init_end = app_js.index("\ndocument.addEventListener('visibilitychange'", init_start)
    init_body = app_js[init_start:init_end]
    assert "await Promise.all([" in init_body
    assert "loadModelCatalog()" in init_body
    assert "loadProviders()" in init_body
    assert "loadConfigDefaults()" in init_body
    assert "reloadConfigFromServer()" in init_body


def test_index_html_font_preconnect():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'rel="preconnect"' in html
    assert "fonts.gstatic.com" in html
    head_end = html.index("</head>")
    tailwind_idx = html.index("/static/tailwindcdn.js")
    assert tailwind_idx > head_end, "tailwindcdn.js should load at end of body, not in head"


def test_error_report_flow_in_app_js():
    root = project_root()
    js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    reporting_js = (root / "web" / "static" / "modules" / "app-error-reporting.js").read_text(
        encoding="utf-8"
    )
    status_js = (root / "web" / "static" / "modules" / "status.js").read_text(encoding="utf-8")
    assert "function maybePromptErrorReport" in js
    assert "function openErrorReportModal" in js
    assert "export async function openErrorReportModal" in reporting_js
    assert "function collectErrorReportContext" in reporting_js
    assert "function extractErrorReportSearchTerms" in reporting_js
    assert "function findErrorLogAnchorIndex" in reporting_js
    assert "localStorage.setItem(ERROR_REPORT_DISMISS_STORAGE" in reporting_js
    assert "submitErrorReport" in js
    assert "statusHadError" in status_js
    assert "btnErrorReportFromBanner" in reporting_js


def test_api_settings_visible_in_simplified_mode():
    """温度控件不得带 settings-full-only，否则简化模式下会被 CSS 隐藏。"""
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    for field_id in ("temperature",):
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


def test_meme_source_credit_in_index_html():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "https://github.com/SEhzm/sb6657/" in html
    assert "meme-source-credit" in html
    assert "我们的烂梗库内容来自开源项目" in html
    meme_tab_idx = html.index('id="danmuPoolTab-meme"')
    credit_idx = html.index("meme-source-credit", meme_tab_idx)
    switch_idx = html.index('settings-section-title">总开关', meme_tab_idx)
    assert credit_idx < switch_idx


def test_pet_page_in_index_html():
    html = (project_root() / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-page="pet"' in html
    assert 'id="page-pet"' in html
    assert 'id="petEnabled"' in html
    assert 'id="btnPetSave"' in html
    assert 'https://petdex.dev/zh' in html
    assert 'id="btnPetImportFolder"' in html
    assert 'id="btnPetResetAsset"' in html
    assert 'id="petAssetSourceText"' in html
    assert 'id="petAssetPathText"' in html
    assert 'id="petAssetErrorText"' in html
    assert '去 PetDex 查找更多桌宠' in html
    assert '目录中需包含 pet.json 与 spritesheet.webp 或 spritesheet.png' in html
    assert 'id="petVisible"' not in html
    assert 'id="btnPetShow"' not in html
    assert 'id="btnPetHide"' not in html
    assert 'id="btnPetClose"' not in html
    app_js = (project_root() / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "initPetPage" in app_js
    assert "loadPetPage" in app_js
    pet_js = (project_root() / "web" / "static" / "modules" / "app-pet-page.js").read_text(
        encoding="utf-8"
    )
    assert "asset_source: currentAssetSource" in pet_js
    assert "asset_path: currentAssetPath" in pet_js
    assert "/api/pet/import-folder" in pet_js
    assert "/api/pet/reset-asset" in pet_js


def test_tailwind_offline_bundle_packaged():
    """BUG-059: 控制台使用内置 tailwindcdn.js，不依赖外网 CDN。"""
    root = project_root()
    bundle = root / "web" / "static" / "tailwindcdn.js"
    assert bundle.is_file()
    assert bundle.stat().st_size > 10_000
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "/static/tailwindcdn.js" in html
    assert "cdn.tailwindcss.com" not in html


def test_danmu_pool_txt_import_controls_in_content_pages():
    root = project_root()
    content_html = (root / "web" / "static" / "partials" / "content-pages.html").read_text(
        encoding="utf-8"
    )
    index_html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    pool_js = (root / "web" / "static" / "modules" / "app-danmu-pool-page.js").read_text(
        encoding="utf-8"
    )
    for html in (content_html, index_html):
        assert 'id="btnPoolImportTxt"' in html
        assert 'id="poolImportTxtInput"' in html
        assert "每个文件最多 1000 行" in html
    assert "importCustomDanmuPoolTxtFiles" in pool_js
    assert "formatCustomPoolCount" in pool_js


def test_resource_path_pet_default_pet_json_and_spritesheet():
    """PET-009: 验证 resource_path('data', 'pet', 'default', 'pet.json') 与
    spritesheet.webp 指向真实文件，便于打包断言（与 tests/test_pet_assets.py 中
    test_resource_path_pet_default_exists 区分，这里再覆盖 spritesheet 与 pet.json 同时存在）。"""
    root = project_root()
    pet_json = root / "data" / "pet" / "default" / "pet.json"
    sheet = root / "data" / "pet" / "default" / "spritesheet.webp"
    assert pet_json.is_file(), f"missing {pet_json}"
    assert sheet.is_file(), f"missing {sheet}"
    assert sheet.stat().st_size > 0


def test_danmuai_spec_includes_pet_default_assets():
    """PET-009: PyInstaller 打包声明必须覆盖 data/pet/default/，
    否则 BUILTIN_PET_DIR 在 sys._MEIPASS 下找不到 pet.json / spritesheet.webp，
    load_pet_assets 会抛 ValueError，桌宠窗口显示「宠物加载失败」。"""
    spec_text = (project_root() / "DanmuAI.spec").read_text(encoding="utf-8")
    # datas tuple 第二项必须是字符串（见 PACKAGING_WINDOWS.md §问题 1）
    assert '"data/pet/default"' in spec_text, (
        "DanmuAI.spec datas must bundle data/pet/default for the builtin pet pack"
    )
    # 同时确认源路径出现在源端（str(root / "data" / "pet" / "default") 形式）
    assert "data" in spec_text and "pet" in spec_text and "default" in spec_text
