"""Audit the model registry without mutating the runtime catalog.

The command validates the v2 provider/catalog snapshot and, when given a
previous JSON snapshot, reports additions, removals, and changed composite
keys.  It never performs authenticated requests and never writes the catalog.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

VALID_STATUSES = {"active", "preview", "testing", "deprecated", "retired", "legacy", "unknown"}
VALID_AVAILABILITY = {"curated", "account_discovery", "fallback", "restricted", "unknown"}
STALE_SOURCE_WARNING_DAYS = 30
STALE_SOURCE_HIGH_PRIORITY_DAYS = 90

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _model_key(model: dict[str, Any]) -> tuple[str, str]:
    return str(model.get("provider_id") or ""), str(model.get("id") or "")


def _flatten(snapshot: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for catalog in snapshot.get("catalogs", []):
        provider_id = catalog.get("provider_id")
        for model in catalog.get("models", []):
            item = dict(model)
            item.setdefault("provider_id", provider_id)
            key = _model_key(item)
            models[key] = item
    return models


def validate_snapshot(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    providers = snapshot.get("providers")
    catalogs = snapshot.get("catalogs")
    if not isinstance(providers, list) or not isinstance(catalogs, list):
        return ["snapshot must contain providers and catalogs lists"]

    provider_ids = [item.get("id") for item in providers]
    if len(provider_ids) != len(set(provider_ids)):
        errors.append("duplicate provider id")
    known_providers = {item for item in provider_ids if item}
    keys: set[tuple[str, str]] = set()
    for catalog in catalogs:
        provider_id = catalog.get("provider_id")
        if provider_id not in known_providers:
            errors.append(f"catalog references unknown provider: {provider_id}")
        for model in catalog.get("models", []):
            key = _model_key({**model, "provider_id": provider_id})
            if key in keys:
                errors.append(f"duplicate model key: {key[0]}:{key[1]}")
            keys.add(key)
            if not key[1]:
                errors.append(f"empty model id for provider: {provider_id}")
            if model.get("supports_vision") not in (True, False, None):
                errors.append(f"invalid supports_vision: {key[0]}:{key[1]}")
            if model.get("status") not in VALID_STATUSES:
                errors.append(f"invalid status: {key[0]}:{key[1]}:{model.get('status')}")
            if model.get("availability") not in VALID_AVAILABILITY:
                errors.append(f"invalid availability: {key[0]}:{key[1]}:{model.get('availability')}")
            source = model.get("source")
            if not isinstance(source, dict) or not source.get("url"):
                errors.append(f"missing source: {key[0]}:{key[1]}")
            if not model.get("verified_at"):
                errors.append(f"missing verified_at: {key[0]}:{key[1]}")
    return errors


def _source_staleness_warnings(
    snapshot: dict[str, Any],
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Report stale official-source evidence without failing the contract.

    Catalog freshness is a review signal, not a runtime validity gate.  This
    keeps the no-credential audit deterministic while making old evidence
    visible before a later connectivity phase.
    """
    reference_date = today or date.today()
    warnings: list[dict[str, Any]] = []
    for catalog in snapshot.get("catalogs", []):
        provider_id = catalog.get("provider_id")
        for model in catalog.get("models", []):
            source = model.get("source")
            if not isinstance(source, dict) or source.get("source_kind") != "official":
                continue
            verified_at = model.get("verified_at") or source.get("verified_at")
            if not verified_at:
                continue
            try:
                verified_date = datetime.fromisoformat(str(verified_at)[:10]).date()
            except ValueError:
                continue
            age_days = (reference_date - verified_date).days
            if age_days <= STALE_SOURCE_WARNING_DAYS:
                continue
            severity = (
                "high"
                if age_days > STALE_SOURCE_HIGH_PRIORITY_DAYS
                else "warning"
            )
            warnings.append({
                "provider_id": provider_id,
                "model_id": model.get("id"),
                "verified_at": str(verified_at),
                "age_days": age_days,
                "severity": severity,
                "message": (
                    "official source evidence is older than "
                    f"{STALE_SOURCE_HIGH_PRIORITY_DAYS if severity == 'high' else STALE_SOURCE_WARNING_DAYS} days"
                ),
            })
    return warnings


def build_report(snapshot: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    current = _flatten(snapshot)
    report: dict[str, Any] = {
        "schema_version": 1,
        "provider_count": len(snapshot.get("providers", [])),
        "catalog_platform_count": len(snapshot.get("catalogs", [])),
        "model_count": len(current),
        "errors": validate_snapshot(snapshot),
        "warnings": _source_staleness_warnings(snapshot),
        "added": [],
        "removed": [],
        "changed": [],
    }
    if baseline is None:
        return report
    previous = _flatten(baseline)
    for key in sorted(current.keys() - previous.keys()):
        report["added"].append(f"{key[0]}:{key[1]}")
    for key in sorted(previous.keys() - current.keys()):
        report["removed"].append(f"{key[0]}:{key[1]}")
    for key in sorted(current.keys() & previous.keys()):
        if current[key] != previous[key]:
            report["changed"].append({
                "key": f"{key[0]}:{key[1]}",
                "before": previous[key],
                "after": current[key],
            })
    return report


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, help="previous export_v2_snapshot JSON")
    parser.add_argument("--output", type=Path, help="write the audit report JSON here")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    from app.providers.platform_registry import export_v2_snapshot

    snapshot = export_v2_snapshot()
    baseline = _load_json(args.baseline) if args.baseline else None
    report = build_report(snapshot, baseline)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if args.json or not args.output:
        print(encoded, end="")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
