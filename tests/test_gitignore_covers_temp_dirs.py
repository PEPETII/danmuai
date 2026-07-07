"""Regression for BUG-004 / BUG-012: .gitignore must ignore local temp and venv dirs."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

REQUIRED_PATTERNS = (
    ".tmp/",
    ".tmp-*/",
    ".venv-*/",
    ".venv-build/",
    ".venv-build-*/",
)


def test_gitignore_covers_temp_dirs() -> None:
    """BUG-004: temp install / scratch dirs must be ignored explicitly."""
    text = GITIGNORE_PATH.read_text(encoding="utf-8")
    lines = {line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")}
    missing = [pattern for pattern in REQUIRED_PATTERNS if pattern not in lines]
    assert not missing, f".gitignore missing patterns: {missing}"


def test_gitignore_ignores_venv_suffix_variants() -> None:
    """BUG-012: .venv-*/ must ignore scratch venv dirs like .venv-bug001/."""
    for rel_path in (".venv-bug001/pyvenv.cfg", ".venv-scratch/pyvenv.cfg"):
        result = subprocess.run(
            ["git", "check-ignore", "-v", rel_path],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"git check-ignore failed for {rel_path}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert ".venv-*/" in result.stdout, (
            f"expected .venv-*/ to match {rel_path}, got: {result.stdout!r}"
        )
