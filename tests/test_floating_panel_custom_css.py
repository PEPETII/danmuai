"""Managed custom CSS storage, config selection, protocol, and API contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.application.config_service import apply_web_config_patch
from app.config_store import ConfigStore
from app.floating_panel_custom_css import (
    custom_css_dir_for_config,
    custom_css_templates,
    import_custom_css_bytes,
    list_custom_css_files,
    read_custom_css,
    selected_custom_css_text,
    validate_custom_css_text,
)
from app.floating_panel_web.panel_protocol import ConfigMessage
from app.web_api.custom_css_routes import register_custom_css_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_for_store(store):
    return SimpleNamespace(config=store, config_changed=MagicMock())


def test_import_list_read_and_duplicate_are_managed(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    record = import_custom_css_bytes(store, b".card { color: red; }", "Pixel.css")
    assert record["file_name"] == "Pixel.css"
    assert custom_css_dir_for_config(store).is_dir()
    assert read_custom_css(store, "Pixel.css") == ".card { color: red; }"
    assert list_custom_css_files(store) == [{"file_name": "Pixel.css", "name": "Pixel.css"}]

    duplicate = import_custom_css_bytes(store, b".card { color: blue; }", "Pixel.css")
    assert duplicate["file_name"] == "Pixel (1).css"
    assert read_custom_css(store, "Pixel.css") == ".card { color: red; }"
    assert read_custom_css(store, duplicate["file_name"]) == ".card { color: blue; }"

    (custom_css_dir_for_config(store) / "ignored.txt").write_text("ignored", encoding="utf-8")
    assert [item["file_name"] for item in list_custom_css_files(store)] == [
        "Pixel (1).css",
        "Pixel.css",
    ]


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("../escape.css", id="parent-slash"),
        pytest.param(r"..\escape.css", id="parent-backslash"),
        pytest.param(r"C:\escape.css", id="absolute-windows"),
        pytest.param("theme.txt", id="wrong-extension"),
        pytest.param("bad?.css", id="invalid-character"),
    ],
)
def test_import_rejects_unsafe_or_non_css_names(tmp_path, name):
    store = ConfigStore(db_path=tmp_path / "config.db")
    with pytest.raises(ValueError):
        import_custom_css_bytes(store, b".card { color: red; }", name)


@pytest.mark.parametrize(
    "css",
    [
        "@import url('https://example.com/theme.css');",
        ".card { background: url(http://example.com/a.png); }",
        ".card { background: javascript:alert(1); }",
        "   ",
    ],
)
def test_css_content_is_validated_before_storage(css):
    with pytest.raises(ValueError):
        validate_custom_css_text(css)


def test_custom_css_selection_is_separate_from_manual_custom(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    import_custom_css_bytes(store, b".card { color: red; }", "Pixel.css")
    store.set_batch(
        {
            "floating_panel_style_preset": "custom_css",
            "floating_panel_custom_css_file": "Pixel.css",
        }
    )
    assert selected_custom_css_text(store) == ".card { color: red; }"

    store.set("floating_panel_style_preset", "custom")
    assert selected_custom_css_text(store) == ""

    apply_web_config_patch(
        _app_for_store(store),
        {
            "floating_panel_style_preset": "custom_css",
            "floating_panel_custom_css_file": r"..\escape.css",
        },
    )
    assert store.get("floating_panel_style_preset") == "custom_css"
    assert store.get("floating_panel_custom_css_file") == ""


def test_builtin_templates_use_contract_selectors():
    templates = custom_css_templates()
    assert {item["id"] for item in templates} == {"no_bubble", "bubble"}
    for item in templates:
        assert "#panel" in item["css"]
        assert ".card" in item["css"]
        assert ".card .username" in item["css"]
        assert ".card .content" in item["css"]


def test_config_message_round_trips_custom_css():
    data = ConfigMessage(custom_css=".card { color: red; }").to_dict()
    assert data["custom_css"] == ".card { color: red; }"
    assert ConfigMessage.from_mapping(data).custom_css == ".card { color: red; }"
    assert ConfigMessage.from_mapping({k: v for k, v in data.items() if k != "custom_css"}).custom_css == ""


def test_custom_css_routes_require_and_use_managed_store(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    app = FastAPI()
    bridge = SimpleNamespace(danmu_app=SimpleNamespace(config=store))

    def check_token(_authorization=None):
        return None

    def invoke_main(fn, *args):
        return fn(*args)

    register_custom_css_routes(app, bridge, check_token, invoke_main)
    client = TestClient(app)

    response = client.post(
        "/api/floating-panel/custom-css/import",
        files={"file": ("Pixel.css", b".card { color: red; }", "text/css")},
    )
    assert response.status_code == 200
    file_name = response.json()["file_name"]
    assert client.get("/api/floating-panel/custom-css").json()["files"]
    assert client.get(f"/api/floating-panel/custom-css/{file_name}").json()["css"] == ".card { color: red; }"
    assert client.get("/api/floating-panel/custom-css/templates").json()["templates"]


def test_custom_css_ui_and_webview_use_one_text_only_override():
    root = Path(__file__).resolve().parents[1]
    partial = (root / "web" / "static" / "partials" / "style-generator.html").read_text(
        encoding="utf-8"
    )
    built = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    generator_js = (root / "web" / "static" / "modules" / "app-style-generator-page.js").read_text(
        encoding="utf-8"
    )
    panel_html = (root / "web" / "static" / "floating_panel" / "index.html").read_text(
        encoding="utf-8"
    )
    panel_js = (root / "web" / "static" / "floating_panel" / "app.js").read_text(encoding="utf-8")

    for text in (partial, built):
        assert 'value="custom_css"' in text
        assert 'id="sgCustomCssSection"' in text
        assert 'id="sgBtnImportCustomCss"' in text
        assert 'id="sgCustomCssTemplateModal"' in text
    assert "attachShadow({ mode: 'open' })" in generator_js
    assert "customCssStyle.textContent" in panel_js
    assert "custom_css" in generator_js
    assert 'id="customCssOverride"' in panel_html
