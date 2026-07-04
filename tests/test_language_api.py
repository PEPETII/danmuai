"""Tests for Web console language API and static assets."""

from unittest.mock import MagicMock, patch

from app.translations import Translator
from app.web_api.language import (
    DEFAULT_LANGUAGE,
    get_from_config,
    normalize_language,
    save_to_config,
    validate_payload,
)
from app.web_api.routes import register_web_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fakes import FakeConfig
from tests.test_bundle_paths import project_root


def test_normalize_language_defaults_invalid_to_zh():
    assert normalize_language("zh") == "zh"
    assert normalize_language("ZH") == "zh"
    assert normalize_language("en") == "en"
    assert normalize_language(None) == "zh"
    assert normalize_language("invalid") == "zh"


def test_language_get_default_returns_system_language():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    with patch.object(Translator, "detect_system_language", return_value="en"):
        register_web_routes(app, bridge, _check_token)
        client = TestClient(app)

        res = client.get("/api/language")
        assert res.status_code == 200
        body = res.json()
        assert body["language"] == DEFAULT_LANGUAGE
        assert body["system_language"] == "en"


def test_language_put_roundtrip():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def _check_token(authorization: str | None = None) -> None:
        if authorization != "Bearer test-token":
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="unauthorized")

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.put(
        "/api/language",
        json={"language": "en"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "language": "en"}

    res = client.get("/api/language")
    assert res.status_code == 200
    assert res.json()["language"] == "en"
    assert get_from_config(bridge.danmu_app.config)["language"] == "en"


def test_language_put_rejects_invalid():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.put("/api/language", json={"language": "french"})
    assert res.status_code == 400


def test_language_validate_payload():
    assert validate_payload({"language": "zh"}) == "zh"
    assert validate_payload({"language": "en"}) == "en"


def test_save_to_config_triggers_translator_set_language():
    config = FakeConfig()
    with patch.object(Translator, "set_language") as mock_set:
        save_to_config(config, "en")
        mock_set.assert_called_once_with("en")
    assert config.get("language") == "en"


def test_language_static_assets_present():
    root = project_root()
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    lang_js = (root / "web" / "static" / "modules" / "language.js").read_text(encoding="utf-8")
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="languageSelect"' in html
    assert "lang-select" in html
    assert "export function initLanguage" in lang_js
    assert "from './modules/language.js'" in app_js
    assert "initLanguage(" in app_js
