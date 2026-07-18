"""Run architecture acceptance gates and write a summary report."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS: list[tuple[str, list[str]]] = [
    ("boundary_guard", [sys.executable, "scripts/boundary_guard.py"]),
    ("test_boundary_guard_rules", [sys.executable, "-m", "pytest", "tests/test_boundary_guard_web_rules.py", "tests/test_boundary_guard_runtime_rules.py", "tests/test_boundary_guard_request_rules.py", "tests/test_boundary_guard_diagnostics_rules.py", "-q"]),
    ("test_diagnostics", [sys.executable, "-m", "pytest", "tests/test_diagnostics_snapshot.py", "tests/test_danmu_diagnostics.py", "-q"]),
    ("test_request_scheduling", [sys.executable, "-m", "pytest", "tests/test_request_scheduling.py", "-q"]),
    (
        "test_web_console_p0",
        [sys.executable, "-m", "pytest", "tests/test_web_console.py", "tests/test_p0_main_flow.py", "-q"],
    ),
    ("test_web_custom_models", [sys.executable, "-m", "pytest", "tests/test_web_custom_models.py", "-q"]),
    ("test_ai_client", [sys.executable, "-m", "pytest", "tests/test_ai_client.py", "-q"]),
]


def _missing_pytest_targets(cmd: list[str]) -> list[str]:
    """Return pytest file paths in *cmd* that do not exist under REPO_ROOT."""
    missing: list[str] = []
    for arg in cmd:
        if not arg.startswith("tests/") or not arg.endswith(".py"):
            continue
        if not (REPO_ROOT / arg).is_file():
            missing.append(arg)
    return missing


def main() -> int:
    report_path = REPO_ROOT / ".acceptance_gates_report.txt"
    lines: list[str] = []
    failed = False

    for name, cmd in COMMANDS:
        missing = _missing_pytest_targets(cmd)
        if missing:
            lines.append(f"=== {name} ===")
            lines.append(f"$ {' '.join(cmd)}")
            lines.append(
                "ERROR: missing pytest target file(s): "
                + ", ".join(missing)
            )
            lines.append("EXIT_CODE: 2")
            lines.append("")
            failed = True
            continue

    for name, cmd in COMMANDS:
        if _missing_pytest_targets(cmd):
            continue
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
    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")
    try:
        print(report_text, end="")
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write(report_text.encode(encoding, errors="replace"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
