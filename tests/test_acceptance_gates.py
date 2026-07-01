"""Architecture-round acceptance: in-process boundary guard on repository root."""

from __future__ import annotations

from pathlib import Path

from scripts.boundary_guard import format_findings, run_boundary_guard
from scripts.run_acceptance_gates import COMMANDS, REPO_ROOT, _missing_pytest_targets


def test_boundary_guard_passes_on_repository_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    findings = run_boundary_guard(repo_root)
    assert findings == [], format_findings(findings)


def test_run_acceptance_gates_commands_target_existing_files() -> None:
    missing: list[str] = []
    for name, cmd in COMMANDS:
        for path in _missing_pytest_targets(cmd):
            missing.append(f"{name}: {path}")
    assert missing == [], "missing pytest targets in run_acceptance_gates.py:\n" + "\n".join(
        missing
    )


def test_final_architecture_baseline_doc_exists() -> None:
    assert (REPO_ROOT / "docs" / "final-architecture-baseline.md").is_file()
