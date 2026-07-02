"""Tests for Web console theme API and static assets."""

from unittest.mock import MagicMock

from app.web_api.console_theme import get_from_config, normalize_theme, validate_payload
from app.web_api.routes import register_web_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fakes import FakeConfig
from tests.test_bundle_paths import project_root


def test_normalize_theme_defaults_invalid_to_dark():
    assert normalize_theme("dark") == "dark"
    assert normalize_theme("DARK") == "dark"
    assert normalize_theme("light") == "light"
    assert normalize_theme(None) == "dark"
    assert normalize_theme("invalid") == "dark"


def test_console_theme_get_default():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.get("/api/console-theme")
    assert res.status_code == 200
    assert res.json() == {"theme": "dark"}


def test_console_theme_put_roundtrip():
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
        "/api/console-theme",
        json={"theme": "dark"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "theme": "dark"}

    res = client.get("/api/console-theme")
    assert res.status_code == 200
    assert res.json() == {"theme": "dark"}
    assert get_from_config(bridge.danmu_app.config) == {"theme": "dark"}


def test_console_theme_put_rejects_invalid():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.put("/api/console-theme", json={"theme": "neon"})
    assert res.status_code == 400


def test_console_theme_validate_payload():
    assert validate_payload({"theme": "dark"}) == "dark"
    assert validate_payload({"theme": "light"}) == "light"


def test_theme_static_assets_present():
    root = project_root()
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    css = (root / "web" / "static" / "warm-tokens.css").read_text(encoding="utf-8")
    base_css = (root / "web" / "static" / "warm-tokens-base.css").read_text(encoding="utf-8")
    components_css = (root / "web" / "static" / "warm-tokens-components.css").read_text(
        encoding="utf-8"
    )
    theme_js = (root / "web" / "static" / "modules" / "theme.js").read_text(encoding="utf-8")
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="themeToggle"' in html
    assert "danmu_console_theme" in html
    assert '[data-theme="dark"]' in css
    assert "--tooltip-bg" in base_css
    assert "--tooltip-fg" in base_css
    assert "background-color: var(--tooltip-bg)" in components_css
    assert "color: var(--tooltip-fg)" in components_css
    assert "export function initTheme" in theme_js
    assert "from './modules/theme.js'" in app_js
    assert "initTheme()" in app_js
