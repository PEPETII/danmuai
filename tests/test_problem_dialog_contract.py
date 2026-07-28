"""Frontend contract: status.js uses event_id instead of is_error edge trigger."""

from __future__ import annotations

from pathlib import Path


def _read_module(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "web" / "static" / "modules" / name).read_text(
        encoding="utf-8"
    )


def test_status_js_tracks_problem_event_id():
    src = _read_module("status.js")
    assert "lastProblemEventId" in src
    assert "lastProblemOccurrenceCount" in src
    assert "active_problem" in src
    assert "maybeShowProblem" in src


def test_error_reporting_no_longer_auto_prompts_on_is_error_edge():
    src = _read_module("app-error-reporting.js")
    assert "maybePromptErrorReport" in src
    assert "openErrorReportModalFromProblem" in src
    assert "Auto prompt removed" in src or "deprecated" in src.lower()


def test_app_js_wires_problem_dialog():
    src = (Path(__file__).resolve().parents[1] / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "initProblemDialog" in src
    assert "onProblemShow" in src
