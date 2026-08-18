from __future__ import annotations

import re
from pathlib import Path

CONTENT_PAGES_HTML = (
    Path(__file__).resolve().parents[1]
    / "web"
    / "static"
    / "partials"
    / "content-pages.html"
)
STATIC_ROOT = CONTENT_PAGES_HTML.parents[1]


def _vtuber_panel() -> str:
    html = CONTENT_PAGES_HTML.read_text(encoding="utf-8")
    start = html.index('id="petTab-vtuber"')
    end = html.index('id="page-persona"', start)
    return html[start:end]


def test_vtuber_panel_is_wired_to_pet_tabs():
    html = CONTENT_PAGES_HTML.read_text(encoding="utf-8")
    panel = _vtuber_panel()

    assert 'data-pet-tab="vtuber"' in html
    assert 'aria-controls="petTab-vtuber"' in html
    assert 'data-pet-panel="vtuber"' in panel
    assert 'role="tabpanel"' in panel
    assert 'aria-labelledby="petTabBtn-vtuber"' in panel
    assert re.search(r'id="petTab-vtuber"[^>]*\bhidden\b', panel)
    assert "虚拟桌宠状态" in panel


def test_vtuber_runtime_exposes_start_stop_desktop_status():
    panel = _vtuber_panel()

    for control_id in (
        "btnVtuberImportModel",
        "btnVtuberImportModelAdvanced",
        "btnVtuberClearModel",
        "btnVtuberStart",
        "btnVtuberStop",
    ):
        assert f'id="{control_id}"' in panel
    assert 'id="btnVtuberImportModel"' in panel and 'disabled' not in panel.split('id="btnVtuberImportModel"', 1)[1].split('>', 1)[0]
    assert 'id="btnVtuberClearModel"' in panel and re.search(r'id="btnVtuberClearModel"[^>]*\bdisabled\b', panel)
    assert 'id="vtuberDesktopStatusText"' in panel
    assert 'id="vtuberDesktopStatusHint"' in panel
    assert 'id="vtuberCanvas"' not in panel
    assert 'id="vtuberParameters"' not in panel
    assert 'id="vtuberActions"' not in panel
    assert 'id="vtuberMotions"' not in panel
    assert 'id="vtuberExpressions"' not in panel
    assert 'id="vtuberVisionModelSelect"' in panel
    assert 'id="vtuberTtsModelSelect"' in panel
    assert 'id="vtuberModelSettingsStatus"' in panel
    assert 'id="vtuberClickThrough"' in panel
    assert 'id="vtuberDisplayScaleRange"' in panel
    assert 'id="vtuberDisplayScaleInput"' in panel
    assert 'id="btnVtuberDisplayScaleReset"' in panel
    assert "显示大小" in panel
    assert "鼠标穿透" in panel
    assert "选择包含 Live2D 模型的文件夹" in panel
    assert "高级导入" in panel


def test_vtuber_module_uses_native_model_api_without_web_control_panel():
    source = (STATIC_ROOT / "modules" / "app-vtuber-page.js").read_text(encoding="utf-8")
    app_source = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    for endpoint in (
        "/api/live2d/model",
        "/api/live2d/settings",
        "/api/live2d/import-model",
        "/api/live2d/import-model-file",
        "/api/live2d/clear-model",
        "/api/live2d/start",
        "/api/live2d/stop",
        "/api/virtual-host/models",
    ):
        assert endpoint in source
    assert "apiFetch" in source
    assert "cancelled" in source
    assert "FormData" not in source
    assert "motion_files" in source
    assert "expression_files" in source
    assert "PARAMETER_ACTIONS" not in source
    assert "/api/live2d/control/" not in source
    assert "setParameterValueById" not in source
    assert "getParameterIds" not in source
    assert "Live2DModel.from" not in source
    assert "WEBGL_LEGACY" not in source
    assert "checkMaxIfStatementsInShader" not in source
    assert "vtuberCanvas" not in source
    assert "vtuberVisionModelSelect" in source
    assert "vtuberTtsModelSelect" in source
    assert "vtuberClickThrough" in source
    assert "vtuberDisplayScaleRange" in source
    assert "display_scale_percent" in source
    assert "/api/live2d/settings" in source
    assert "app-vtuber-page.js" in app_source
    assert "Promise.all" in app_source
