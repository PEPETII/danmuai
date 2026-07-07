"""BUG-002: SanitizedLogger must persist logs when frozen with stderr=None."""

from __future__ import annotations

import logging
import sys

import pytest

from app.logger import SanitizedLogger


@pytest.fixture(autouse=True)
def _reset_danmu_logger():
    logger = logging.getLogger("DanmuAI")
    logger.handlers.clear()
    yield
    logger.handlers.clear()


def test_frozen_stderr_none_writes_app_log(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("app.logger.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "stderr", None)

    SanitizedLogger().error("frozen diagnostic %s", "marker")

    log_file = tmp_path / "DanmuAI" / "app.log"
    assert log_file.is_file()
    text = log_file.read_text(encoding="utf-8")
    assert "frozen diagnostic marker" in text
    assert "[ERROR]" in text


def test_dev_stderr_present_no_app_log(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("app.logger.is_frozen", lambda: False)

    SanitizedLogger().info("dev only message")

    log_file = tmp_path / "DanmuAI" / "app.log"
    assert not log_file.exists()
    logger = logging.getLogger("DanmuAI")
    assert any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    )
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_stderr_none_non_frozen_still_writes_app_log(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("app.logger.is_frozen", lambda: False)
    monkeypatch.setattr(sys, "stderr", None)

    SanitizedLogger().warning("windowed fallback %s", "ok")

    log_file = tmp_path / "DanmuAI" / "app.log"
    assert log_file.is_file()
    text = log_file.read_text(encoding="utf-8")
    assert "windowed fallback ok" in text
    assert "[WARNING]" in text


def test_append_frozen_log_sanitizes_api_key(tmp_path, monkeypatch):
    """BUG-009: startup.log must not contain raw sk- keys."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("app.bundle_paths.is_frozen", lambda: True)

    from app.bundle_paths import append_frozen_log

    secret = "sk-abc1234567890abcdef1234567890abcdef"
    append_frozen_log(f"crash api_key={secret}")

    text = (tmp_path / "DanmuAI" / "startup.log").read_text(encoding="utf-8")
    assert secret not in text
    assert "sk-****" in text


def test_append_frozen_log_sanitizes_bearer_and_encrypted_key(tmp_path, monkeypatch):
    """BUG-009: append_frozen_log applies full sanitize rules, not only sk- pattern."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr("app.bundle_paths.is_frozen", lambda: True)

    from app.bundle_paths import append_frozen_log

    bearer = "Bearer abc1234567890abcdef1234567890abcdef"
    encrypted = "gAAAA" + ("A" * 60)
    append_frozen_log(f"headers: Authorization: {bearer}\nkey={encrypted}")

    text = (tmp_path / "DanmuAI" / "startup.log").read_text(encoding="utf-8")
    assert bearer not in text
    assert encrypted not in text
    assert "Authorization: Bearer" in text
    assert "gAAAA****" in text
