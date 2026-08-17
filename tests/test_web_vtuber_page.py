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


def test_vtuber_controls_stay_disabled_until_web_api_is_connected():
    panel = _vtuber_panel()

    for control_id in (
        "vtuberModel",
        "vtuberVoice",
        "vtuberScale",
        "vtuberEnabled",
        "vtuberInteractionEnabled",
    ):
        assert re.search(
            rf'id="{control_id}"[^>]*\bdisabled\b',
            panel,
        ), f"{control_id} must remain disabled before API integration"

    for control_id in ("btnVtuberImportModel", "btnVtuberClearModel"):
        assert f'id="{control_id}"' in panel
    assert 'id="btnVtuberImportModel"' in panel and 'disabled' not in panel.split('id="btnVtuberImportModel"', 1)[1].split('>', 1)[0]
    assert 'id="btnVtuberClearModel"' in panel and re.search(r'id="btnVtuberClearModel"[^>]*\bdisabled\b', panel)
    assert "通过桌面原生文件选择器" in panel
    assert "模型文件不会上传或复制" in panel
    assert 'data-settings-rhythm-accordion' not in panel


def test_vtuber_module_uses_native_model_api_and_keeps_runtime_controls_out():
    source = (STATIC_ROOT / "modules" / "app-vtuber-page.js").read_text(encoding="utf-8")
    app_source = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    for endpoint in ("/api/live2d/model", "/api/live2d/import-model", "/api/live2d/clear-model"):
        assert endpoint in source
    assert "apiFetch" in source
    assert "cancelled" in source
    assert "FormData" not in source
    assert "app-vtuber-page.js" in app_source
    assert "Promise.all" in app_source
