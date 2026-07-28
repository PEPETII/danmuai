"""Tests for PROBLEM_CATALOG."""

from app.problems.catalog import PROBLEM_CATALOG, catalog_actions, catalog_entry

REQUIRED_CODES = (
    "CONFIG-001",
    "AI-AUTH-001",
    "AI-BALANCE-001",
    "AI-RATE-001",
    "AI-MODEL-001",
    "AI-TIMEOUT-001",
    "NETWORK-001",
    "CAPTURE-001",
    "DISPLAY-001",
    "WEBVIEW-001",
    "WEBVIEW-002",
    "STORAGE-001",
    "KNOWLEDGE-001",
    "TTS-001",
    "INTERNAL-001",
)


def test_problem_catalog_contains_all_required_codes():
    assert set(REQUIRED_CODES) == set(PROBLEM_CATALOG.keys())


def test_catalog_entry_has_required_fields():
    for code in REQUIRED_CODES:
        entry = catalog_entry(code)
        assert entry["severity"] in ("info", "warning", "error", "fatal")
        assert entry["category"]
        assert str(entry["title_key"]).startswith("problem.")
        assert str(entry["summary_key"]).startswith("problem.")
        assert entry["suggestion_keys"]
        assert isinstance(catalog_actions(code), tuple)
