from datetime import date

from app.providers.platform_registry import export_v2_snapshot
from scripts.audit_model_catalog import (
    _source_staleness_warnings,
    build_report,
    validate_snapshot,
)


def test_audit_snapshot_has_source_lifecycle_and_composite_identity():
    snapshot = export_v2_snapshot()
    report = build_report(snapshot)
    assert report["errors"] == []
    assert report["model_count"] > 0


def test_audit_rejects_duplicate_provider_model_key():
    snapshot = export_v2_snapshot()
    catalog = snapshot["catalogs"][0]
    catalog["models"].append(dict(catalog["models"][0]))
    errors = validate_snapshot(snapshot)
    assert any("duplicate model key" in error for error in errors)


def test_audit_warns_on_stale_official_source_without_failing():
    snapshot = {
        "catalogs": [{
            "provider_id": "openai",
            "models": [{
                "id": "example",
                "verified_at": "2026-08-01",
                "source": {
                    "source_kind": "official",
                    "url": "https://example.invalid/docs",
                    "verified_at": "2026-08-01",
                },
            }],
        }],
    }
    warnings = _source_staleness_warnings(snapshot, today=date(2026, 10, 4))
    assert warnings[0]["severity"] == "warning"
    assert warnings[0]["age_days"] == 64
