"""Static checks for problem detail modal DOM."""

from __future__ import annotations

from pathlib import Path


def _read_static(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "web" / "static" / name).read_text(encoding="utf-8")


def test_problem_detail_modal_exists_in_modals_partial():
    html = _read_static("partials/modals.html")
    assert 'id="problemDetailModal"' in html
    assert 'id="problemTechnicalDetail"' in html
    assert 'id="btnProblemReportFromModal"' in html


def test_problem_and_feedback_modals_are_distinct():
    html = _read_static("partials/modals.html")
    assert 'id="problemDetailModal"' in html
    assert 'id="errorReportModal"' in html
    assert html.index('problemDetailModal') < html.index('errorReportModal')


def test_overview_banner_has_view_problem_button():
    html = _read_static("partials/overview.html")
    assert 'id="btnProblemViewFromBanner"' in html
    assert 'id="btnProblemBannerDismiss"' in html


def test_problem_dialog_module_exports():
    js = _read_static("modules/app-problem-dialog.js")
    assert "export function initProblemDialog" in js
    assert "export function showProblemDialog" in js
    assert "export function maybeShowProblem" in js
