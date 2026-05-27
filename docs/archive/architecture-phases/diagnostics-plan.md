# Phase 5-A Diagnostics Plan

> Archived. Implemented: `DiagnosticSnapshotBuilder`, `GET /api/diagnostics`.

## Scope

Post-freeze diagnostics only; no main-pipeline or `/api/status` contract changes.

## Read-Only Diagnostic Snapshot

`app/application/diagnostic_snapshot.py` — groups: `scheduler`, `timing`, `runtime_state`.

## Boundary Rules

- Read-only; no writeback to `DanmuApp` or services
- No `_trigger_api_call`, reply, or queue calls
- No Qt / Overlay / DanmuEngine imports
- Separate from `StatusSnapshotBuilder`

## Web/API

- `GET /api/diagnostics` → `build_diagnostic_snapshot()`
- Must not reuse `build_status_snapshot()`
- Web UI: `web/static/` — no private field references

## Freeze

Obey [phase4-freeze.md](phase4-freeze.md). Do not expose `_last_api_trigger_at`, `_request_started_at_by_id`, `_rtt_history` via status snapshot.
