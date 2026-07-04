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
