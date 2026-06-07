"""One-off: remove pytest/cache artifacts that should not be tracked."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    for name in (".pytest_cache", ".pytest_tmp"):
        path = ROOT / name
        if path.exists():
            shutil.rmtree(path)
            print(f"removed {path}")

    for path in ROOT.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)
            print(f"removed {path}")

    for path in ROOT.rglob("*.pyc"):
        if path.is_file():
            path.unlink()
            print(f"removed {path}")

    report = ROOT / ".acceptance_gates_report.txt"
    if report.is_file():
        report.unlink()
        print(f"removed {report}")


if __name__ == "__main__":
    main()
