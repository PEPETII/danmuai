"""Run architecture acceptance gates and write a summary report."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS: list[tuple[str, list[str]]] = [
    ("boundary_guard", [sys.executable, "scripts/boundary_guard.py"]),
    ("test_boundary_guard", [sys.executable, "-m", "pytest", "tests/test_boundary_guard.py", "-q"]),
    ("test_diagnostics", [sys.executable, "-m", "pytest", "tests/test_diagnostics.py", "-q"]),
    ("test_request_scheduling", [sys.executable, "-m", "pytest", "tests/test_request_scheduling.py", "-q"]),
    (
        "test_web_console_p0",
        [sys.executable, "-m", "pytest", "tests/test_web_console.py", "tests/test_p0_main_flow.py", "-q"],
    ),
    ("test_web_custom_models", [sys.executable, "-m", "pytest", "tests/test_web_custom_models.py", "-q"]),
    ("test_ai_client", [sys.executable, "-m", "pytest", "tests/test_ai_client.py", "-q"]),
]


def main() -> int:
    report_path = REPO_ROOT / ".acceptance_gates_report.txt"
    lines: list[str] = []
    failed = False

    for name, cmd in COMMANDS:
        lines.append(f"=== {name} ===")
        lines.append(f"$ {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout:
            lines.append(result.stdout.rstrip())
        if result.stderr:
            lines.append(result.stderr.rstrip())
        lines.append(f"EXIT_CODE: {result.returncode}")
        lines.append("")
        if result.returncode != 0:
            failed = True

    summary = "ACCEPTANCE_GATES: FAIL" if failed else "ACCEPTANCE_GATES: PASS"
    lines.insert(0, summary)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
